"""Immutable, hash-chained, append-only experiment registry.

Tamper-evident (not tamper-proof): every event embeds the hash of its predecessor,
SQLite triggers reject UPDATE/DELETE, and verify_chain() detects any edit. A JSONL
mirror is written alongside so the ledger can be committed and diffed.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path

GENESIS_PREV = "0" * 64


def canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def sha256(data: str | bytes) -> str:
    if isinstance(data, str):
        data = data.encode()
    return hashlib.sha256(data).hexdigest()


class RegistryError(Exception):
    pass


class Registry:
    KINDS = {
        "GENESIS", "DATASET", "PREREG", "EXPERIMENT", "EVAL", "LEAKAGE_TEST", "CONTAMINATION",
        "CLASSIFICATION", "REPLICATION", "PAPER", "SELFTEST", "NOTE", "FINAL_TEST", "VAULT_SEAL", "DATA_GAP", "INTEGRITY_REPORT",
    }

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.jsonl = self.path.with_suffix(".jsonl")
        self.db = sqlite3.connect(self.path)
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS events(
              seq INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, kind TEXT NOT NULL,
              payload TEXT NOT NULL, prev_hash TEXT NOT NULL, hash TEXT NOT NULL);
            CREATE TRIGGER IF NOT EXISTS no_update BEFORE UPDATE ON events
              BEGIN SELECT RAISE(ABORT,'registry is append-only'); END;
            CREATE TRIGGER IF NOT EXISTS no_delete BEFORE DELETE ON events
              BEGIN SELECT RAISE(ABORT,'registry is append-only'); END;
            """
        )

    # ------------------------------------------------------------------ core
    def _last_hash(self) -> str:
        row = self.db.execute("SELECT hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
        return row[0] if row else GENESIS_PREV

    def append(self, kind: str, payload: dict) -> dict:
        if kind not in self.KINDS:
            raise RegistryError(f"unknown event kind {kind}")
        prev = self._last_hash()
        ts = time.time()
        body = canon(payload)
        h = sha256(f"{prev}|{ts!r}|{kind}|{body}")
        cur = self.db.execute(
            "INSERT INTO events(ts,kind,payload,prev_hash,hash) VALUES (?,?,?,?,?)",
            (ts, kind, body, prev, h),
        )
        self.db.commit()
        ev = {"seq": cur.lastrowid, "ts": ts, "kind": kind, "payload": payload, "prev_hash": prev, "hash": h}
        with open(self.jsonl, "a") as f:
            f.write(canon(ev) + "\n")
        return ev

    def events(self, kind: str | None = None) -> list[dict]:
        q = "SELECT seq,ts,kind,payload,prev_hash,hash FROM events"
        args: tuple = ()
        if kind:
            q += " WHERE kind=?"
            args = (kind,)
        rows = self.db.execute(q + " ORDER BY seq", args).fetchall()
        return [dict(seq=r[0], ts=r[1], kind=r[2], payload=json.loads(r[3]), prev_hash=r[4], hash=r[5]) for r in rows]

    def verify_chain(self) -> bool:
        prev = GENESIS_PREV
        for r in self.db.execute("SELECT ts,kind,payload,prev_hash,hash FROM events ORDER BY seq"):
            ts, kind, body, ph, h = r
            if ph != prev or sha256(f"{ph}|{ts!r}|{kind}|{body}") != h:
                return False
            prev = h
        return True

    # ------------------------------------------------------ research objects
    def preregister(self, hyp_id: str, version: int, spec: dict) -> str:
        """Pre-register a hypothesis version. Specs are immutable; changes need a new version."""
        for e in self.events("PREREG"):
            p = e["payload"]
            if p["hyp_id"] == hyp_id and p["version"] == version:
                raise RegistryError(f"{hyp_id} v{version} already pre-registered; create a new version")
        spec_hash = sha256(canon(spec))
        self.append("PREREG", {"hyp_id": hyp_id, "version": version, "spec": spec, "spec_hash": spec_hash})
        return spec_hash

    def prereg(self, hyp_id: str, version: int) -> dict:
        for e in self.events("PREREG"):
            p = e["payload"]
            if p["hyp_id"] == hyp_id and p["version"] == version:
                return p
        raise RegistryError(f"{hyp_id} v{version} not pre-registered")

    def log_experiment(self, hyp_id: str, version: int, *, code_sha: str, dataset_ids: list[str],
                       params: dict, seed: int, family: str, results: dict, status: str = "COMPLETE") -> dict:
        """Every run is logged; experiments require a matching pre-registration."""
        self.prereg(hyp_id, version)
        return self.append("EXPERIMENT", dict(hyp_id=hyp_id, version=version, code_sha=code_sha,
                                             dataset_ids=dataset_ids, params=params, seed=seed,
                                             family=family, results=results, status=status))

    def trial_count(self, family: str | None = None) -> dict:
        """Counts used for multiple-testing correction (failed runs count too)."""
        exps = [e["payload"] for e in self.events("EXPERIMENT")]
        if family:
            exps = [p for p in exps if p["family"] == family]
        return {
            "experiments": len(exps),
            "hypotheses": len({p["hyp_id"] for p in exps}),
            "variants": len({(p["hyp_id"], p["version"], canon(p["params"])) for p in exps}),
            "datasets": len({d for p in exps for d in p["dataset_ids"]}),
        }

    def mark_contaminated(self, dataset_id: str, reason: str, by: str) -> None:
        self.append("CONTAMINATION", {"dataset_id": dataset_id, "reason": reason, "by": by})

    def contaminated(self, dataset_id: str) -> bool:
        return any(e["payload"]["dataset_id"] == dataset_id for e in self.events("CONTAMINATION"))
