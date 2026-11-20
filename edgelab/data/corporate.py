"""Corporate actions: cached table + split/dividend adjustment computed by us, from RAW cached prices.

Why not use the provider's adjusted bars? Adjusted history is a moving target (every new dividend rewrites
the past), which silently invalidates a cache and makes results irreproducible. Raw prices + an explicit
action table are deterministic and auditable.

Method (standard, CRSP/Yahoo style):
  * split with ratio r = new/old (4-for-1 => r=4): bars BEFORE ex_date get price / r and volume * r.
  * cash dividend D with ex-date d: bars BEFORE d get price * (1 - D / raw_close_of_last_bar_before_d).
Both are evaluated per ET session date, so intraday bars of one session share one factor.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

from .config import CACHE_DIR

ET = "America/New_York"
_COLS = ["symbol", "ex_date", "kind", "ratio", "rate"]


class CorporateActionsStore:
    def __init__(self, root: Path | None = None):
        self.dir = Path(root) if root else CACHE_DIR / "alpaca"
        self.file, self.meta = self.dir / "corporate_actions.parquet", self.dir / "corporate_actions.meta.json"

    def _load(self) -> tuple[pd.DataFrame, dict]:
        df = pd.read_parquet(self.file) if self.file.exists() else pd.DataFrame(columns=_COLS)
        meta = json.loads(self.meta.read_text()) if self.meta.exists() else {}
        return df, meta

    def refresh(self, alpaca, symbols: list[str], max_age_hours: float = 24, batch: int = 50, log=lambda s: None) -> None:
        df, meta = self._load()
        now = pd.Timestamp.now("UTC")
        stale = [s for s in symbols if s not in meta or (now - pd.Timestamp(meta[s])) > pd.Timedelta(hours=max_age_hours)]
        for i in range(0, len(stale), batch):
            chunk = stale[i:i + batch]
            got = alpaca.corporate_actions(chunk)
            df = pd.concat([df[~df["symbol"].isin(chunk)], got], ignore_index=True)
            for s in chunk:
                meta[s] = now.isoformat()
            log(f"corporate actions: {min(i + batch, len(stale))}/{len(stale)} symbols refreshed")
        if stale:
            self.dir.mkdir(parents=True, exist_ok=True)
            tmp = self.file.with_name(self.file.name + f".tmp{os.getpid()}")
            df.to_parquet(tmp)
            os.replace(tmp, self.file)
            tmp = self.meta.with_name(self.meta.name + f".tmp{os.getpid()}")
            tmp.write_text(json.dumps(meta, indent=1))
            os.replace(tmp, self.meta)

    def for_symbol(self, symbol: str) -> pd.DataFrame:
        df, _ = self._load()
        return df[df["symbol"] == symbol].reset_index(drop=True)


def session_dates(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """ET calendar date (naive, midnight) of each bar-start timestamp."""
    return index.tz_convert(ET).tz_localize(None).normalize()


def adjustment_factors(bars_raw: pd.DataFrame, actions: pd.DataFrame, total_return: bool) -> tuple[np.ndarray, np.ndarray]:
    """(price_factor, volume_factor) per bar. price_adj = raw * price_factor; volume_adj = raw * volume_factor."""
    n = len(bars_raw)
    pf, vf = np.ones(n), np.ones(n)
    if n == 0 or actions.empty:
        return pf, vf
    dates = session_dates(bars_raw.index)
    ev_dates, ev_price, ev_vol = [], [], []
    daily_close = bars_raw["close"].groupby(dates).last()      # raw close of each session (last bar of the day)
    for r in actions.sort_values("ex_date").itertuples():
        ex = pd.Timestamp(r.ex_date).normalize()
        if r.kind == "split":
            if r.ratio and r.ratio != 1.0:
                ev_dates.append(ex); ev_price.append(1.0 / r.ratio); ev_vol.append(r.ratio)
        elif total_return and r.kind == "dividend" and r.rate > 0:
            prior = daily_close[daily_close.index < ex]
            if prior.empty:
                continue                                        # dividend before our first bar: irrelevant
            p = float(prior.iloc[-1])
            ev_dates.append(ex); ev_price.append(1.0 - r.rate / p); ev_vol.append(1.0)
    if not ev_dates:
        return pf, vf
    order = np.argsort(ev_dates, kind="stable")
    ev_dates = pd.DatetimeIndex(np.array(ev_dates, dtype="datetime64[ns]")[order])
    ev_price, ev_vol = np.array(ev_price)[order], np.array(ev_vol)[order]
    # suffix products: factor for a bar = product of events whose ex_date is AFTER the bar's session date
    suf_p = np.append(np.cumprod(ev_price[::-1])[::-1], 1.0)
    suf_v = np.append(np.cumprod(ev_vol[::-1])[::-1], 1.0)
    idx = ev_dates.searchsorted(dates.values, side="right")     # first event with ex_date > session date
    return suf_p[idx], suf_v[idx]


def adjust_bars(bars_raw: pd.DataFrame, actions: pd.DataFrame, total_return: bool = False) -> pd.DataFrame:
    """Return a copy with OHLC/volume adjusted and the untouched 'raw_close' kept for reference."""
    pf, vf = adjustment_factors(bars_raw, actions, total_return)
    out = bars_raw.copy()
    out["raw_close"] = bars_raw["close"]
    for c in ("open", "high", "low", "close"):
        out[c] = bars_raw[c].to_numpy() * pf
    out["volume"] = bars_raw["volume"].to_numpy() * vf
    if "vwap" in out:
        out["vwap"] = bars_raw["vwap"].to_numpy() * pf
    return out
