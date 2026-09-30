"""Isolation for untrusted (generator-written) strategy code.

Layers of defence:
  1. Static AST analysis: import whitelist, forbidden builtins/dunders.
  2. Runtime: restricted builtins in the exec namespace (no open/exec/eval/__import__ escape).
  3. OS: child runs as an unprivileged uid (if we are root), in a fresh network namespace (if permitted),
     with CPU/memory/file/process rlimits, an empty environment and a private temp cwd.
  4. Protocol: bars are streamed to the child ONE AT A TIME. The child never holds future data, so
     look-ahead is structurally impossible for code running inside the sandbox.
Residual risk (documented in docs/PROTOCOL.md): without a container/VM the isolation is best-effort.
"""
from __future__ import annotations

import ast
import json
import os
import resource
import select
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field

import numpy as np

from .data import Panel

ALLOWED_IMPORTS = {"numpy", "math", "statistics", "collections", "itertools", "functools", "dataclasses",
                   "typing", "heapq", "bisect", "random", "__future__"}
FORBIDDEN_NAMES = {"open", "exec", "eval", "compile", "__import__", "globals", "locals", "vars", "input",
                   "breakpoint", "help", "exit", "quit", "memoryview", "setattr", "delattr"}
FORBIDDEN_ATTR_PARTS = ("__",)  # any dunder attribute (e.g. __class__, __subclasses__, __globals__)
ALLOWED_DUNDERS = {"__init__", "__name__", "__future__"}
NOBODY = 65534


@dataclass
class Violation:
    line: int
    msg: str


def static_check(source: str) -> list[Violation]:
    out: list[Violation] = []
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return [Violation(e.lineno or 0, f"syntax error: {e.msg}")]
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                if a.name.split(".")[0] not in ALLOWED_IMPORTS:
                    out.append(Violation(n.lineno, f"import of '{a.name}' not allowed"))
        elif isinstance(n, ast.ImportFrom):
            if (n.module or "").split(".")[0] not in ALLOWED_IMPORTS:
                out.append(Violation(n.lineno, f"import from '{n.module}' not allowed"))
        elif isinstance(n, ast.Name) and n.id in FORBIDDEN_NAMES:
            out.append(Violation(n.lineno, f"use of '{n.id}' not allowed"))
        elif isinstance(n, ast.Attribute) and n.attr.startswith("__") and n.attr not in ALLOWED_DUNDERS:
            out.append(Violation(n.lineno, f"dunder attribute '{n.attr}' not allowed"))
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and any(
                k in n.value for k in ("/vault", "registry", "evaluator", "thresholds")):
            out.append(Violation(n.lineno, "string references protected evaluator/vault/registry paths"))
        elif isinstance(n, (ast.Global, ast.Nonlocal)):
            out.append(Violation(n.lineno, "global/nonlocal not allowed"))
    return out


CHILD = r'''
import sys, json, builtins
_real_import = builtins.__import__
_ALLOWED = set(%(allowed)r)
def _imp(name, globals=None, locals=None, fromlist=(), level=0):
    if level != 0 or name.split(".")[0] not in _ALLOWED:
        raise ImportError("import not allowed: " + name)
    return _real_import(name, globals, locals, fromlist, level)
_proto_out = sys.stdout
sys.stdout = sys.stderr          # stray prints must not corrupt the protocol
_safe = {k: getattr(builtins, k) for k in dir(builtins) if k not in %(forbidden)r and not k.startswith("__")}
_safe["__import__"] = _imp
_safe["__build_class__"] = builtins.__build_class__
_safe["__name__"] = "strategy"
ns = {"__builtins__": _safe, "__name__": "strategy"}
def _send(o):
    _proto_out.write(json.dumps(o) + "\n"); _proto_out.flush()
try:
    exec(compile(open(sys.argv[1]).read(), "strategy", "exec"), ns)
    init = json.loads(sys.stdin.readline())
    strat = ns[init["cls"]](**init["params"])
    _send({"ready": 1})
except BaseException as e:
    _send({"error": "init: %%s: %%s" %% (type(e).__name__, e)}); raise SystemExit(0)
for line in sys.stdin:
    m = json.loads(line)
    if m.get("end"):
        break
    try:
        bars = {k: tuple(v) for k, v in m["bars"].items()}
        w = strat.on_bar(m["ts"], bars) or {}
        _send({"w": {k: float(v) for k, v in w.items()}})
    except BaseException as e:
        _send({"error": "%%s: %%s" %% (type(e).__name__, e)}); break
'''


def _limits():
    resource.setrlimit(resource.RLIMIT_CPU, (600, 600))
    resource.setrlimit(resource.RLIMIT_AS, (3 * 1024 ** 3, 3 * 1024 ** 3))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1_000_000, 1_000_000))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


@dataclass
class IsolationReport:
    uid_dropped: bool = False
    netns: bool = False
    notes: list[str] = field(default_factory=list)


def _preexec_factory(report: IsolationReport, want_netns: bool = True):
    def fn():
        os.setsid()
        _limits()
        if want_netns and os.geteuid() == 0:
            try:
                import ctypes
                libc = ctypes.CDLL(None, use_errno=True)
                if libc.unshare(0x40000000) != 0:  # CLONE_NEWNET
                    pass
            except Exception:
                pass
        if os.geteuid() == 0:
            os.setgroups([])
            os.setgid(NOBODY)
            os.setuid(NOBODY)
    return fn


class SandboxError(Exception):
    pass


def run_sandboxed(source: str, cls: str, params: dict, panel: Panel, *, bar_timeout: float = 20.0,
                  python: str | None = None, allow_violations: bool = False) -> tuple[np.ndarray, IsolationReport]:
    """Run strategy source bar-by-bar in an isolated child; return decided weights (T,N)."""
    v = static_check(source)
    if v and not allow_violations:
        raise SandboxError("static analysis rejected code: " + "; ".join(f"L{x.line}: {x.msg}" for x in v))
    rep = IsolationReport(uid_dropped=os.geteuid() == 0)
    tmp = tempfile.mkdtemp(prefix="edgelab_sbx_")
    try:
        os.chmod(tmp, 0o755)
        code = os.path.join(tmp, "strategy_src.py")
        runner = os.path.join(tmp, "runner.py")
        with open(code, "w") as f:
            f.write(source)
        with open(runner, "w") as f:
            f.write(CHILD % {"allowed": sorted(ALLOWED_IMPORTS), "forbidden": sorted(FORBIDDEN_NAMES)})
        os.chmod(code, 0o644)
        os.chmod(runner, 0o644)
        env = {"PATH": "/usr/bin:/bin", "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "HOME": tmp,
               "PYTHONDONTWRITEBYTECODE": "1"}
        proc = subprocess.Popen([python or sys.executable, "-I", runner, code], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=tmp, env=env,
                                preexec_fn=_preexec_factory(rep), text=True, bufsize=1)
        W = np.zeros((panel.T, panel.N))
        idx = {t: i for i, t in enumerate(panel.tickers)}

        def recv():
            r, _, _ = select.select([proc.stdout], [], [], bar_timeout)
            if not r:
                proc.kill()
                raise SandboxError("strategy timed out")
            line = proc.stdout.readline()
            if not line:
                err = proc.stderr.read()[-800:]
                raise SandboxError("child exited: " + err)
            return json.loads(line)

        try:
            proc.stdin.write(json.dumps({"cls": cls, "params": params}) + "\n")
            proc.stdin.flush()
            m = recv()
            if "error" in m:
                raise SandboxError(m["error"])
            for t in range(panel.T):
                bars = {k: list(b) for k, b in panel.bars_at(t).items()}
                proc.stdin.write(json.dumps({"ts": int(panel.ts[t].astype("datetime64[ns]").astype("int64")), "bars": bars}) + "\n")
                proc.stdin.flush()
                m = recv()
                if "error" in m:
                    raise SandboxError(m["error"])
                for k, v_ in m["w"].items():
                    j = idx.get(k)
                    if j is not None and np.isfinite(v_):
                        W[t, j] = v_
            proc.stdin.write(json.dumps({"end": 1}) + "\n")
            proc.stdin.flush()
        finally:
            try:
                proc.stdin.close()
            except Exception:
                pass
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
        return W, rep
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
