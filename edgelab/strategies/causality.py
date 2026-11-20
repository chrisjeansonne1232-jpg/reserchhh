"""Mechanical no-lookahead proof for a strategy: signals computed from a truncated history must equal the
signals computed from the full history at every timestamp the truncated run contains."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .base import Strategy


@dataclass
class CausalityResult:
    ok: bool
    first_violation: pd.Timestamp | None = None
    detail: str = ""


def _arrays(sig) -> dict[str, pd.Series]:
    out = {"target": sig.target}
    for k in ("stop_dist", "target_dist", "trail_dist"):
        v = getattr(sig, k)
        if v is not None:
            out[k] = v
    return out


def check_causality(strategy: Strategy, bars: pd.DataFrame, cuts=(0.35, 0.5, 0.65, 0.8, 0.95), tol: float = 1e-9) -> CausalityResult:
    full = _arrays(strategy.signals(bars))
    for frac in cuts:
        k = max(2, int(len(bars) * frac))
        part = _arrays(strategy.signals(bars.iloc[:k]))
        for name, s_part in part.items():
            a = s_part.to_numpy(float)
            b = full[name].iloc[:k].to_numpy(float)
            both_nan = np.isnan(a) & np.isnan(b)
            bad = ~both_nan & ~(np.abs(a - b) <= tol * (1 + np.abs(b)))
            if bad.any():
                i = int(np.flatnonzero(bad)[0])
                return CausalityResult(False, bars.index[i], f"'{name}' at {bars.index[i]} changes when future bars are removed "
                                       f"(cut at {frac:.0%}): full={b[i]!r} truncated={a[i]!r}")
    return CausalityResult(True)
