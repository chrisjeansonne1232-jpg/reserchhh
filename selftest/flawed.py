"""Intentionally flawed strategies/pipelines. The evaluator MUST NOT classify any as a robust candidate.

Each factory returns (Candidate-or-data, expectation). These are the system's own adversarial test-suite;
they live in selftest/ so that they are never confused with research strategies.
"""
from __future__ import annotations

import numpy as np

from edgelab.data import Panel
from edgelab.engine import Exec
from edgelab.evaluator import Candidate
from edgelab.refstrategies import momentum_build, reversal_build


class _Weights:
    """Strategy whose per-bar weights were precomputed by a (leaky) pipeline."""
    def __init__(self, Wpre: np.ndarray, tickers: list[str]):
        self.W, self.tk, self.i = Wpre, tickers, -1

    def on_bar(self, ts, bars):
        self.i += 1
        w = self.W[self.i]
        return {t: float(w[j]) for j, t in enumerate(self.tk) if t in bars and w[j] != 0}


def _ls_from_score(score: np.ndarray, alive: np.ndarray, q=0.2, gross=1.0) -> np.ndarray:
    T, N = score.shape
    W = np.zeros((T, N))
    for t in range(T):
        m = alive[t] & np.isfinite(score[t])
        idx = np.flatnonzero(m)
        if len(idx) < 10:
            continue
        o = idx[np.argsort(score[t, idx])]
        k = max(1, int(len(o) * q))
        W[t, o[-k:]] = gross / 2 / k
        W[t, o[:k]] = -gross / 2 / k
    return W


def _next_ret(panel: Panel) -> np.ndarray:
    o = panel.open
    nxt = np.vstack([o[1:], np.full((1, panel.N), np.nan)])
    return np.where(np.isfinite(nxt / o), nxt / o - 1, 0.0)


# ---- 1. classic look-ahead: signal = the return we are about to earn
def lookahead_next_return(panel_hint=None):
    def build(panel, params):
        # decision at t (after close t) trades at open t+1 and earns open[t+2]/open[t+1]-1 -> peek at t+1..t+2
        fut = np.vstack([_next_ret(panel)[1:], np.zeros((1, panel.N))])
        return _Weights(_ls_from_score(fut, panel.alive), panel.tickers)
    return build


# ---- 2. centred rolling window (a very common accidental leak)
def centered_window(window=11):
    def build(panel, params):
        c = panel.close
        r = np.where(np.isfinite(c), np.log(np.where(np.isfinite(c), c, 1.0)), np.nan)
        r = np.diff(r, axis=0, prepend=np.nan)
        k = params.get("window", window)
        sc = np.full_like(r, np.nan)
        h = k // 2
        for t in range(h, panel.T - h):
            sc[t] = np.nan_to_num(np.nanmean(np.where(np.isfinite(r[t - h:t + h + 1]), r[t - h:t + h + 1], np.nan), axis=0), nan=0.0) if np.isfinite(r[t - h:t + h + 1]).any() else 0.0
        return _Weights(_ls_from_score(sc, panel.alive), panel.tickers)
    return build


# ---- 3. full-sample normalisation (target/statistic leakage)
def fullsample_scaling():
    def build(panel, params):
        legit = momentum_build(panel, dict(window=40, rebalance=5))
        c = panel.close
        gstd = float(np.nanstd(np.diff(np.log(c), axis=0)))     # computed on the WHOLE sample
        class S:
            def on_bar(self, ts, bars):
                w = legit.on_bar(ts, bars)
                return {k: v * 0.02 / gstd for k, v in w.items()}
        return S()
    return build


# ---- 4. survivorship-biased dataset is a *data* flaw: see evaluator data gate

# ---- 5. pure noise strategies + best-of-K selection
def random_smooth_signal(seed: int, T: int, N: int, alive: np.ndarray, rebalance=5):
    rng = np.random.default_rng(seed)
    x = np.zeros(N)
    sc = np.zeros((T, N))
    for t in range(T):
        x = 0.97 * x + rng.normal(0, 1, N) * 0.25
        sc[t] = x
    W = _ls_from_score(sc, alive)
    for t in range(T):
        if t % rebalance:
            W[t] = W[t - 1] if t else 0
    return W


def noise_family(panel: Panel, K: int, exec_: Exec, base_seed: int = 1000):
    from edgelab.engine import run_backtest
    Ws, rets = [], []
    for k in range(K):
        W = random_smooth_signal(base_seed + k, panel.T, panel.N, panel.alive)
        Ws.append(W)
        rets.append(run_backtest(panel, W, exec_).net)
    return Ws, np.column_stack(rets)


def precomputed_candidate(name, W, panel, hyp_id, params, search_returns=None, neighbors=None, benchmark=None, family="noise"):
    def build(p, prm):
        return _Weights(W, panel.tickers)
    return Candidate(name, build, params, hyp_id, neighbors=neighbors or [], search_returns=search_returns,
                     benchmark=benchmark, family=family)


# ---- 7. sharp isolated optimum: only one seed "works" (selected on the same data)
def seeded_random_build(panel_ref):
    def build(panel, params):
        W = random_smooth_signal(params["seed"], panel.T, panel.N, panel.alive)
        return _Weights(W, panel.tickers)
    return build


# ---- 8. transaction-cost omission: high-turnover reversal on a market with genuine 1-day reversal
def reversal_no_costs():
    return reversal_build


# ---- 9. sandbox escape attempts (must each be stopped)
ESCAPES = {
    "import_os": "import os\nclass S:\n    def __init__(self): pass\n    def on_bar(self, ts, bars): return {}\n",
    "open_file": "class S:\n    def __init__(self): open('/etc/passwd').read()\n    def on_bar(self, ts, bars): return {}\n",
    "read_vault": "class S:\n    def __init__(self): self.x = open('/var/lib/edgelab/vault/x').read()\n    def on_bar(self, ts, bars): return {}\n",
    "dunder_escape": "class S:\n    def __init__(self): self.x = ().__class__.__bases__[0].__subclasses__()\n    def on_bar(self, ts, bars): return {}\n",
    "eval_call": "class S:\n    def __init__(self): eval('1+1')\n    def on_bar(self, ts, bars): return {}\n",
    "import_in_func": "class S:\n    def __init__(self): pass\n    def on_bar(self, ts, bars):\n        import subprocess\n        return {}\n",
    "touch_evaluator_path": "class S:\n    def __init__(self): self.p = 'edgelab/evaluator.py'\n    def on_bar(self, ts, bars): return {}\n",
}
# Escapes that survive static analysis only by obfuscation -- run with allow_violations=True to prove the runtime layers hold.
RUNTIME_ESCAPES = {
    "builtin_open": "class S:\n    def __init__(self): pass\n    def on_bar(self, ts, bars):\n        f = open('/etc/hostname')\n        return {}\n",
    "os_import_runtime": "class S:\n    def __init__(self): pass\n    def on_bar(self, ts, bars):\n        import os\n        return {}\n",
    "dunder_import": "class S:\n    def __init__(self): pass\n    def on_bar(self, ts, bars):\n        m = __import__('os')\n        return {}\n",
    "infinite_loop": "class S:\n    def __init__(self): pass\n    def on_bar(self, ts, bars):\n        while True: pass\n",
}
