"""Market-data container, integrity validators and point-in-time helpers."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class Panel:
    """Bar panel. ts[t] is the time bar t CLOSES (when its content becomes knowable).

    alive[t,i] is True when ticker i is listed/tradable during bar t. Delisted names stay in
    the panel (survivorship-free); delist_ret[i] is the terminal return applied after the
    final bar (e.g. -0.3 bankruptcy wipe-out, 0.0 cash acquisition at last close).
    """
    ts: np.ndarray
    tickers: list[str]
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    alive: np.ndarray
    spread_bps: np.ndarray | None = None
    delist_ret: np.ndarray | None = None
    meta: dict = field(default_factory=dict)
    # Cells explicitly EXCLUDED because of a documented data gap (see GapLedger). Excluded cells are never
    # traded or zero-filled; any other alive-but-missing cell raises DataGapError in the engine.
    excluded: np.ndarray | None = None

    @property
    def T(self) -> int:
        return len(self.ts)

    @property
    def N(self) -> int:
        return len(self.tickers)

    def slice(self, a: int, b: int) -> "Panel":
        sl = slice(a, b)
        return Panel(self.ts[sl], list(self.tickers), self.open[sl], self.high[sl], self.low[sl], self.close[sl],
                     self.volume[sl], self.alive[sl], None if self.spread_bps is None else self.spread_bps[sl],
                     self.delist_ret, dict(self.meta),
                     None if self.excluded is None else self.excluded[sl])

    def bars_at(self, t: int) -> dict:
        m = self.alive[t] & np.isfinite(self.open[t]) & np.isfinite(self.close[t])
        if self.excluded is not None:
            m &= ~self.excluded[t]
        idx = np.flatnonzero(m)
        return {self.tickers[i]: (float(self.open[t, i]), float(self.high[t, i]), float(self.low[t, i]),
                                   float(self.close[t, i]), float(self.volume[t, i])) for i in idx}


# --------------------------------------------------------------------------- validators
class DataGapError(Exception):
    """Alive bars with missing prices that are not covered by a documented exclusion."""


@dataclass
class Finding:
    check: str
    severity: str  # FAIL | WARN | INFO
    detail: str


def validate_panel(p: Panel, *, max_gap_ret: float = 0.6, stale_run: int = 5) -> list[Finding]:
    out: list[Finding] = []
    ts = pd.DatetimeIndex(p.ts)
    if not ts.is_monotonic_increasing:
        out.append(Finding("timestamps_monotonic", "FAIL", "timestamps not increasing"))
    if ts.has_duplicates:
        out.append(Finding("timestamps_unique", "FAIL", f"{ts.duplicated().sum()} duplicate timestamps"))
    if p.open.shape != (p.T, p.N):
        out.append(Finding("shape", "FAIL", "array shape mismatch"))
        return out
    with np.errstate(invalid="ignore"):
        bad_ohlc = (p.high < np.maximum(p.open, p.close) - 1e-9) | (p.low > np.minimum(p.open, p.close) + 1e-9)
        bad_ohlc &= p.alive
        if bad_ohlc.any():
            out.append(Finding("ohlc_consistency", "FAIL", f"{int(bad_ohlc.sum())} bars with inconsistent OHLC"))
        nonpos = (p.close <= 0) & p.alive
        if nonpos.any():
            out.append(Finding("nonpositive_price", "FAIL", f"{int(nonpos.sum())} non-positive closes"))
        missing = p.alive & ~np.isfinite(p.close)
        if missing.any():
            out.append(Finding("missing_alive", "WARN", f"{int(missing.sum())} alive bars with missing prices"))
        r = p.close[1:] / p.close[:-1] - 1
        ext = np.isfinite(r) & (np.abs(r) > max_gap_ret) & p.alive[1:] & p.alive[:-1]
        if ext.any():
            out.append(Finding("bad_ticks_or_unadjusted_splits", "WARN",
                               f"{int(ext.sum())} close-to-close moves >{max_gap_ret:.0%}; verify against corporate actions"))
        flat = (np.diff(p.close, axis=0) == 0) & p.alive[1:]
        run = np.zeros(p.N, dtype=int)
        stale = np.zeros(p.N, dtype=bool)
        for t in range(flat.shape[0]):
            run = np.where(flat[t], run + 1, 0)
            stale |= run >= stale_run
        if stale.any():
            out.append(Finding("stale_prices", "WARN", f"{int(stale.sum())} tickers with >= {stale_run} identical closes"))
    # alive must be contiguous per ticker (no resurrection => ticker re-use ambiguity)
    for i in range(p.N):
        a = p.alive[:, i].astype(int)
        if a.size and (np.diff(a) == 1).sum() > 1:
            out.append(Finding("alive_gaps", "WARN", f"{p.tickers[i]} has multiple listing intervals"))
    return out


def audit_universe_pit(universe_by_date: dict, listing_date: dict, delist_date: dict) -> list[Finding]:
    """Every ticker in universe(d) must be listed <= d and not delisted before d."""
    out: list[Finding] = []
    for d, names in universe_by_date.items():
        d = pd.Timestamp(d)
        for n in names:
            ld, dd = listing_date.get(n), delist_date.get(n)
            if ld is None:
                out.append(Finding("universe_unknown_listing", "FAIL", f"{n}@{d.date()} has no listing date"))
            elif pd.Timestamp(ld) > d:
                out.append(Finding("universe_leakage", "FAIL", f"{n} in universe on {d.date()} before listing {pd.Timestamp(ld).date()}"))
            if dd is not None and pd.Timestamp(dd) < d:
                out.append(Finding("universe_survivorship", "FAIL", f"{n} in universe on {d.date()} after delisting {pd.Timestamp(dd).date()}"))
    return out


def audit_survivorship(panel_tickers: list[str], master_tickers: list[str], delisted_in_master: list[str]) -> list[Finding]:
    """Panel must contain the delisted names that the master security list says existed."""
    missing = sorted(set(delisted_in_master) - set(panel_tickers))
    frac = len(missing) / max(1, len(delisted_in_master))
    if frac > 0.02:
        return [Finding("survivorship_bias", "FAIL",
                        f"{len(missing)}/{len(delisted_in_master)} delisted securities ({frac:.1%}) absent from panel")]
    return []


def audit_news_timestamps(df: pd.DataFrame) -> list[Finding]:
    """Ordering: event <= publication <= vendor_receipt <= system_receipt <= signal <= order <= execution."""
    order = ["event_ts", "publication_ts", "vendor_receipt_ts", "system_receipt_ts", "signal_ts", "order_ts", "execution_ts"]
    cols = [c for c in order if c in df.columns]
    out: list[Finding] = []
    for a, b in zip(cols[:-1], cols[1:]):
        bad = (pd.to_datetime(df[a]) > pd.to_datetime(df[b])).sum()
        if bad:
            out.append(Finding("timestamp_order", "FAIL", f"{bad} rows where {a} > {b}"))
    if "publication_ts" in df and "signal_ts" in df:
        lat = (pd.to_datetime(df["signal_ts"]) - pd.to_datetime(df["publication_ts"])).dt.total_seconds()
        if (lat <= 0).any():
            out.append(Finding("zero_latency_signal", "FAIL", f"{int((lat<=0).sum())} signals at/before publication"))
    return out


def asof_fundamentals(decision_ts: pd.Timestamp, filings: pd.DataFrame) -> pd.DataFrame:
    """Latest filing per (ticker, field) whose *availability* time <= decision_ts (never period end)."""
    f = filings[pd.to_datetime(filings["available_ts"]) <= decision_ts]
    return f.sort_values("available_ts").groupby(["ticker", "field"]).tail(1)


def trading_calendar_check(ts: np.ndarray, tz: str = "America/New_York") -> list[Finding]:
    """Flags weekend bars, and DST-transition misalignment for intraday data."""
    idx = pd.DatetimeIndex(ts)
    out: list[Finding] = []
    local = idx.tz_localize("UTC").tz_convert(tz) if idx.tz is None else idx.tz_convert(tz)
    wk = (local.dayofweek >= 5).sum()
    if wk:
        out.append(Finding("weekend_bars", "WARN", f"{int(wk)} bars on weekends"))
    return out
