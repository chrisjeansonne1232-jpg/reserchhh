"""Sealed final holdout (the most recent ~20% of history).

Rules enforced in code, not by good intentions:
  * ONE cut-off date for every asset (derived once from SPY daily history, then frozen in config/holdout.json),
    so a cross-asset or cross-regime test can never smuggle holdout information into research.
  * `load_research_bars` cannot return a bar at/after the cut-off, whatever `end` is passed.
  * `open_holdout` is the only way to read holdout bars. Each strategy may open it ONCE; every opening is written to
    the tamper-evident ledger (registry). The generator must only ever import `load_research_bars`.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd

from .config import ROOT
from .loader import load_bars

HOLDOUT_FILE = ROOT / "config" / "holdout.json"
REGISTRY_PATH = ROOT / "registry" / "lab.sqlite"


class HoldoutError(RuntimeError):
    pass


def get_registry(path: Path | None = None):
    from ..registry import Registry
    return Registry(path or REGISTRY_PATH)


def freeze_holdout(reference_index: pd.DatetimeIndex, frac: float = 0.20, path: Path = HOLDOUT_FILE, registry=None) -> dict:
    """Compute the cut-off from a reference bar index and freeze it. Refuses to run twice."""
    if path.exists():
        raise HoldoutError(f"holdout already frozen in {path}; it can never be moved (that would defeat its purpose)")
    k = int(len(reference_index) * (1 - frac))
    start = pd.Timestamp(reference_index[k]).tz_convert("UTC")
    meta = {"holdout_start_utc": start.isoformat(), "fraction": frac, "reference": "SPY 1d",
            "reference_bars": int(len(reference_index)), "reference_first_bar": reference_index[0].isoformat(),
            "reference_last_bar": reference_index[-1].isoformat(), "frozen_utc": pd.Timestamp.now("UTC").isoformat()}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(meta, indent=1))
    os.replace(tmp, path)
    (registry or get_registry()).append("VAULT_SEAL", {"what": "final holdout", **meta})
    return meta


def holdout_start(path: Path = HOLDOUT_FILE) -> pd.Timestamp:
    if not path.exists():
        raise HoldoutError("holdout not frozen yet; run: python -m edgelab.data freeze-holdout")
    return pd.Timestamp(json.loads(path.read_text())["holdout_start_utc"])


def load_research_bars(symbol: str, tf: str, start=None, end=None, *, path: Path = HOLDOUT_FILE, **kw) -> pd.DataFrame:
    """Bars strictly BEFORE the holdout cut-off. This is the only loader the generator/optimizer may use."""
    cut = holdout_start(path)
    end = cut if end is None else min(pd.Timestamp(end, tz="UTC") if pd.Timestamp(end).tzinfo is None else pd.Timestamp(end), cut)
    df = load_bars(symbol, tf, start, end, **kw)
    assert df.empty or df.index[-1] < cut, "holdout leak in research loader"
    return df


def open_holdout(symbol: str, tf: str, *, strategy_id: str, reason: str, registry=None, path: Path = HOLDOUT_FILE, **kw) -> tuple[pd.DataFrame, pd.Timestamp]:
    """Return (bars, cutoff): full history INCLUDING the holdout (indicators need warm-up) and the cut-off to pass as
    `start=` to the backtester. One opening per strategy_id; every opening is recorded in the ledger."""
    cut = holdout_start(path)
    reg = registry or get_registry()
    for e in reg.events("FINAL_TEST"):
        if e["payload"].get("event") == "HOLDOUT_OPENED" and e["payload"].get("strategy_id") == strategy_id:
            raise HoldoutError(f"strategy '{strategy_id}' already used its single holdout evaluation (ledger seq {e['seq']}); "
                               "re-testing after seeing the result would turn the holdout into training data")
    reg.append("FINAL_TEST", {"event": "HOLDOUT_OPENED", "strategy_id": strategy_id, "symbol": symbol, "timeframe": tf,
                              "reason": reason, "holdout_start": cut.isoformat()})
    return load_bars(symbol, tf, **kw), cut
