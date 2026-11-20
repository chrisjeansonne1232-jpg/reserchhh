"""Reference strategies used to prove the pipeline (they are NOT expected to have an edge)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..base import ParamSpec, Signals, Strategy
from ..indicators import sma


class SMACross(Strategy):
    """Long when the fast SMA is above the slow SMA. direction='both' also goes short when it is below."""
    name, family = "sma_cross", "trend"

    def __init__(self, fast: int = 50, slow: int = 200, direction: str = "long"):
        super().__init__(fast=int(fast), slow=int(slow), direction=direction)
        if self.params["fast"] >= self.params["slow"]:
            raise ValueError("fast must be < slow")

    @classmethod
    def param_space(cls):
        return {"fast": ParamSpec("int", 5, 100), "slow": ParamSpec("int", 20, 300), "direction": ParamSpec("cat", choices=("long", "both"))}

    def signals(self, bars: pd.DataFrame) -> Signals:
        p = self.params
        f, s = sma(bars["close"], p["fast"]), sma(bars["close"], p["slow"])
        valid = s.notna()
        up = (f > s).astype(float)
        tgt = up if p["direction"] == "long" else up * 2 - 1
        return Signals(target=tgt.where(valid, np.nan))

    def describe(self) -> str:
        p = self.params
        side = "Go long" if p["direction"] == "long" else "Go long (and short)"
        return (f"{side} when the {p['fast']}-bar average of closes is above the {p['slow']}-bar average; "
                f"{'otherwise stay in cash' if p['direction'] == 'long' else 'go short when it is below'}. "
                "Decide at a bar's close, trade at the next bar's open.")


class BuyHold(Strategy):
    name, family = "buy_hold", "benchmark"

    def signals(self, bars: pd.DataFrame) -> Signals:
        return Signals(target=pd.Series(1.0, index=bars.index))

    def describe(self) -> str:
        return "Buy at the first opportunity and hold."
