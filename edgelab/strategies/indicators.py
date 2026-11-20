"""Causal indicators: value at t uses bars <= t only (rolling windows, no centering, no negative shifts)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma(x: pd.Series, n: int) -> pd.Series:
    return x.rolling(n, min_periods=n).mean()


def ema(x: pd.Series, n: int) -> pd.Series:
    return x.ewm(span=n, adjust=False, min_periods=n).mean()


def true_range(bars: pd.DataFrame) -> pd.Series:
    pc = bars["close"].shift(1)
    return pd.concat([bars["high"] - bars["low"], (bars["high"] - pc).abs(), (bars["low"] - pc).abs()], axis=1).max(axis=1, skipna=False)


def atr(bars: pd.DataFrame, n: int = 14) -> pd.Series:
    return true_range(bars).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def rsi(x: pd.Series, n: int = 14) -> pd.Series:
    d = x.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def zscore(x: pd.Series, n: int) -> pd.Series:
    return (x - x.rolling(n, min_periods=n).mean()) / x.rolling(n, min_periods=n).std()


def donchian_high(bars: pd.DataFrame, n: int) -> pd.Series:
    """Highest high of the PREVIOUS n bars (excludes the current bar so a breakout can be detected causally)."""
    return bars["high"].shift(1).rolling(n, min_periods=n).max()


def donchian_low(bars: pd.DataFrame, n: int) -> pd.Series:
    return bars["low"].shift(1).rolling(n, min_periods=n).min()
