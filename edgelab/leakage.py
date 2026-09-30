"""Automated leakage detection.

Core idea: a leak-free candidate's decisions at time <= T must be a pure function of data <= T.
We therefore REBUILD the whole candidate (feature pipeline + strategy) on (a) the data truncated at T and
(b) the data whose future (after T) has been replaced by scrambled noise, and require identical decisions
up to T. Any full-sample normalisation, centred window, shifted target, future join or universe built from
end-of-sample facts changes the decisions and is flagged.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np

from .data import Panel
from .engine import collect_weights


@dataclass
class LeakResult:
    name: str
    passed: bool
    detail: str
    max_abs_diff: float = 0.0


def run_build(build: Callable, params: dict, panel: Panel) -> np.ndarray:
    return collect_weights(build(panel, params), panel)


def truncation_test(build, params, panel: Panel, cuts=(0.5, 0.7, 0.85), tol=1e-9) -> LeakResult:
    W = run_build(build, params, panel)
    worst = 0.0
    for c in cuts:
        k = int(panel.T * c)
        Wc = run_build(build, params, panel.slice(0, k))
        d = float(np.abs(W[:k] - Wc).max()) if k else 0.0
        worst = max(worst, d)
    ok = worst <= tol
    return LeakResult("truncation_invariance", ok,
                      "decisions independent of data after decision time" if ok else
                      f"decisions at t<=T change when future data is removed (max |dw|={worst:.3g})", worst)


def scramble_future(panel: Panel, k: int, seed: int = 0) -> Panel:
    """Replace bars after k with a time-permutation of themselves, then perturb prices."""
    rng = np.random.default_rng(seed)
    p = panel.slice(0, panel.T)
    perm = k + rng.permutation(panel.T - k)
    for name in ("open", "high", "low", "close", "volume", "alive"):
        a = getattr(p, name).copy()
        a[k:] = a[perm]
        setattr(p, name, a)
    mult = np.exp(rng.normal(0, 0.05, (panel.T - k, panel.N)))
    for name in ("open", "high", "low", "close"):
        a = getattr(p, name)
        a[k:] = a[k:] * mult
    return p


def scramble_test(build, params, panel: Panel, cuts=(0.5, 0.75), tol=1e-9) -> LeakResult:
    W = run_build(build, params, panel)
    worst = 0.0
    for c in cuts:
        k = int(panel.T * c)
        Ws = run_build(build, params, scramble_future(panel, k))
        worst = max(worst, float(np.abs(W[:k] - Ws[:k]).max()))
    ok = worst <= tol
    return LeakResult("future_scramble", ok,
                      "unchanged when the future is replaced by noise" if ok else
                      f"decisions depend on future data (max |dw|={worst:.3g})", worst)


def implausible_performance(net_sharpe: float, limit: float = 5.0) -> LeakResult:
    ok = net_sharpe < limit
    return LeakResult("implausible_performance", ok,
                      f"net Sharpe {net_sharpe:.2f} {'within' if ok else 'above'} plausibility limit {limit}")


def delay_fragility(sharpe_by_delay: dict[int, float]) -> LeakResult:
    """Informational: information-timing leaks typically vanish under one bar of delay."""
    s0, s1 = sharpe_by_delay.get(0, 0.0), sharpe_by_delay.get(1, 0.0)
    frag = s0 > 1.0 and s1 < 0.15 * s0
    return LeakResult("delay_fragility", not frag,
                      f"Sharpe delay0={s0:.2f}, delay1={s1:.2f}" + (" -> collapses under 1-bar delay (timing leak or ultra-fast edge)" if frag else ""))


def leakage_suite(build, params, panel: Panel) -> list[LeakResult]:
    return [truncation_test(build, params, panel), scramble_test(build, params, panel)]
