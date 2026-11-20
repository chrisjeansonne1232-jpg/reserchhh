"""Load analysis-ready bars from the cache: adjusted, session-filtered, with 1h built from 15m for equities."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .cache import BarCache
from .corporate import CorporateActionsStore, adjust_bars
from .downloader import is_crypto

ET = "America/New_York"
_cal = None


def _calendar():
    global _cal
    if _cal is None:
        from ..integrity import MarketCalendar
        _cal = MarketCalendar("US_EQUITY")
    return _cal


def _utc(x) -> pd.DatetimeIndex:
    idx = pd.DatetimeIndex(x)
    return idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")


def _ts(x) -> pd.Timestamp:
    t = pd.Timestamp(x)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def _ns(x) -> np.ndarray:
    """int64 nanoseconds since epoch (NaT -> very negative). Integer maths behaves identically on pandas 2.x and 3.x."""
    return _utc(x).as_unit("ns").asi8


def _sessions(index: pd.DatetimeIndex) -> dict:
    """Session date and open/close (ns since epoch) of the session each bar belongs to (NaT on days with no session)."""
    cal = _calendar().cal
    d = index.tz_convert(ET).tz_localize(None).normalize()
    sch = cal.schedule.loc[d.min():d.max()]
    return {"session": d.to_numpy(), "open": _ns(sch["open"].reindex(d)), "close": _ns(sch["close"].reindex(d))}


def rth_filter(df: pd.DataFrame) -> pd.DataFrame:
    """Keep bars that START inside the regular session (handles half days via the exchange calendar)."""
    if df.empty:
        return df
    s, t = _sessions(df.index), _ns(df.index)
    return df[(t >= s["open"]) & (t < s["close"])]


def resample_rth(df_fine: pd.DataFrame, minutes: int = 60) -> pd.DataFrame:
    """Build bars of `minutes` anchored at the 09:30 open from RTH-filtered finer bars."""
    if df_fine.empty:
        return df_fine
    s, t = _sessions(df_fine.index), _ns(df_fine.index)
    bucket = (t - s["open"]) // (minutes * 60 * 10**9)
    key = [s["session"], bucket]
    g = df_fine.groupby(key, sort=True)
    out = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                        "close": g["close"].last(), "volume": g["volume"].sum()})
    for extra, how in (("trade_count", "sum"), ("raw_close", "last")):
        if extra in df_fine:
            out[extra] = getattr(g[extra], how)()
    first_ts = df_fine.index.to_series().groupby(key, sort=True).first()
    out.index = pd.DatetimeIndex(first_ts.to_numpy(), name="ts")
    out.index = out.index.tz_localize("UTC") if out.index.tz is None else out.index.tz_convert("UTC")
    return out.sort_index()


def load_bars(symbol: str, tf: str, start=None, end=None, *, adjust: str = "total", session: str = "rth",
              cache: BarCache | None = None, actions: CorporateActionsStore | None = None, feed: str = "sip") -> pd.DataFrame:
    """adjust: 'raw' | 'split' | 'total' (splits + dividends). session: 'rth' | 'all' (equities only).

    Equity '1h' is built from cached 15m bars anchored at the open (the provider's 1h bars are clock-aligned and
    mix pre-market with the first regular minutes). Crypto is 24/7, never adjusted, session ignored.
    """
    cache = cache or BarCache()
    crypto = is_crypto(symbol)
    src_tf = "15m" if (tf == "1h" and not crypto) else tf
    df = cache.read("alpaca", "crypto" if crypto else feed, src_tf, symbol)
    if df is None:
        raise FileNotFoundError(f"no cached {src_tf} bars for {symbol}; run: python -m edgelab.data download --symbols {symbol} --tf {src_tf}")
    if not crypto:
        if adjust != "raw":
            df = adjust_bars(df, (actions or CorporateActionsStore()).for_symbol(symbol), total_return=(adjust == "total"))
        else:
            df = df.assign(raw_close=df["close"])
        if tf != "1d" and session == "rth":
            df = rth_filter(df)
        if tf == "1h":
            df = resample_rth(df, 60) if session == "rth" else df
    if start is not None:
        df = df[df.index >= _ts(start)]
    if end is not None:
        df = df[df.index < _ts(end)]
    return df
