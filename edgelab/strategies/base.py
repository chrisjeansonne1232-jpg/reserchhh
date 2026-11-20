"""Common Strategy interface.

A strategy turns a bar history into `Signals`. EVERYTHING in `Signals[t]` must be computable from bars <= t
(information available at the CLOSE of bar t). The backtester executes decisions at the OPEN of bar t+1.
`strategies.causality.check_causality` proves this property mechanically for any strategy.

Signals:
  target       desired position after bar t as a signed fraction of equity (+1 = fully long, -1 = fully short,
               0 = flat, NaN = no opinion yet / warm-up -> flat). Orders are only sent when the target CHANGES.
  stop_dist    optional price distance for a protective stop, applied to the trade that this bar's decision opens
  target_dist  optional profit-target distance      trail_dist  optional trailing-stop distance
  max_hold     optional maximum holding period in bars
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class Signals:
    target: pd.Series
    stop_dist: pd.Series | None = None
    target_dist: pd.Series | None = None
    trail_dist: pd.Series | None = None
    max_hold: int | None = None

    def first_valid(self):
        return self.target.first_valid_index()


@dataclass(frozen=True)
class ParamSpec:
    """Search-space entry the generator will use to mutate a parameter."""
    kind: str                       # 'int' | 'float' | 'cat'
    low: float | None = None
    high: float | None = None
    choices: tuple = ()
    log: bool = False


class Strategy(ABC):
    name: str = "strategy"
    family: str = "generic"

    def __init__(self, **params):
        self.params = params

    @classmethod
    def param_space(cls) -> dict[str, ParamSpec]:
        return {}

    @abstractmethod
    def signals(self, bars: pd.DataFrame) -> Signals: ...

    def describe(self) -> str:
        return f"{self.name}({', '.join(f'{k}={v}' for k, v in self.params.items())})"

    def __repr__(self) -> str:
        return self.describe()


def from_entries_exits(index: pd.Index, long_entry=None, long_exit=None, short_entry=None, short_exit=None,
                       size=None, direction: str = "both") -> pd.Series:
    """Build a `target` series from boolean entry/exit signals (the classic entries/exits/sizing formulation).

    State machine over bars: flat -> long on long_entry, long -> flat on long_exit, same for shorts; if both a
    long and short entry fire on one bar, no new position is opened. `size` (fraction of equity, default 1) is
    sampled on the bar the position is opened and held. Pure function of signals at <= t, so it stays causal.
    """
    n = len(index)
    z = lambda x: np.zeros(n, bool) if x is None else np.asarray(x, dtype=bool)  # noqa: E731
    le, lx, se, sx = z(long_entry), z(long_exit), z(short_entry), z(short_exit)
    sz = np.ones(n) if size is None else np.asarray(size, dtype=float)
    out = np.zeros(n)
    pos, cur = 0, 0.0
    allow_long, allow_short = direction in ("long", "both"), direction in ("short", "both")
    for t in range(n):
        if pos > 0 and lx[t]:
            pos, cur = 0, 0.0
        elif pos < 0 and sx[t]:
            pos, cur = 0, 0.0
        if pos == 0:
            if allow_long and le[t] and not (allow_short and se[t]):
                pos, cur = 1, sz[t]
            elif allow_short and se[t] and not (allow_long and le[t]):
                pos, cur = -1, -sz[t]
        out[t] = cur
    return pd.Series(out, index=index)
