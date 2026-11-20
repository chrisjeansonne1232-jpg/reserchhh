"""Data-quality checks for one symbol/timeframe. Returns issues with severities instead of silently 'fixing' data.

FAIL = do not research on this data until resolved;  WARN = look at it, it may matter;  INFO = context.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

ET = "America/New_York"
TF_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "1h": 60}
# a one-bar spike must exceed max(floor, 8 robust sigmas) and price must come back within half the jump on the next bar
SPIKE_FLOOR = {"1d": 0.08, "1h": 0.03, "15m": 0.02, "5m": 0.015, "1m": 0.01}

SURVIVORSHIP_NOTE = ("Universe = CURRENT index membership applied to all history (survivorship bias): names that were "
                     "delisted, acquired or dropped from the index are absent, which flatters long-only results. "
                     "Treat component-based results as optimistic; SPY/QQQ/IWM/BTC/ETH are not affected by this.")


@dataclass
class Issue:
    check: str
    severity: str
    n: int
    detail: str


@dataclass
class QualityReport:
    symbol: str
    timeframe: str
    rows: int = 0
    first: str = ""
    last: str = ""
    issues: list[Issue] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    def add(self, check, severity, n, detail):
        self.issues.append(Issue(check, severity, int(n), detail))

    @property
    def ok(self) -> bool:
        return not any(i.severity == "FAIL" for i in self.issues)

    def to_dict(self) -> dict:
        return {**asdict(self), "ok": self.ok}

    def summary(self) -> str:
        head = f"{self.symbol} {self.timeframe}: {self.rows} rows {self.first[:10]}..{self.last[:10]} -> {'OK' if self.ok else 'FAIL'}"
        return "\n".join([head] + [f"  [{i.severity}] {i.check} (n={i.n}): {i.detail}" for i in self.issues])


def _robust_sigma(r: pd.Series, window: int = 250) -> pd.Series:
    med = r.abs().rolling(window, min_periods=30).median()
    return (1.4826 * med).bfill()


def check_bars(df: pd.DataFrame, symbol: str, tf: str, *, crypto: bool = False, rth: bool = True) -> QualityReport:
    rep = QualityReport(symbol, tf, rows=len(df))
    if df.empty:
        rep.add("empty", "FAIL", 0, "no rows")
        return rep
    rep.first, rep.last = df.index[0].isoformat(), df.index[-1].isoformat()
    if not df.index.is_monotonic_increasing:
        rep.add("timestamps_monotonic", "FAIL", 1, "timestamps are not sorted")
    dup = int(df.index.duplicated().sum())
    if dup:
        rep.add("duplicate_timestamps", "FAIL", dup, "duplicate bar timestamps")
    px = df[["open", "high", "low", "close"]]
    nan = int(px.isna().any(axis=1).sum())
    if nan:
        rep.add("nan_prices", "FAIL", nan, "bars with NaN prices")
    nonpos = int((px <= 0).any(axis=1).sum())
    if nonpos:
        rep.add("nonpositive_prices", "FAIL", nonpos, "bars with price <= 0")
    with np.errstate(invalid="ignore"):
        bad = (df["high"] < df[["open", "close"]].max(axis=1) - 1e-9) | (df["low"] > df[["open", "close"]].min(axis=1) + 1e-9) \
            | (df["high"] < df["low"])
    if bad.any():
        rep.add("ohlc_inconsistent", "FAIL", bad.sum(), f"high<max(open,close) or low>min(open,close); first at {df.index[bad.to_numpy()][0]}")
    if (df["volume"] < 0).any():
        rep.add("negative_volume", "FAIL", (df["volume"] < 0).sum(), "negative volume")
    zv = float((df["volume"] == 0).mean())
    rep.stats["zero_volume_share"] = round(zv, 5)
    if zv > 0.02:
        rep.add("zero_volume", "WARN", (df["volume"] == 0).sum(), f"{zv:.1%} of bars have zero volume")

    # ---- calendar gaps
    if crypto:
        step = {"1d": pd.Timedelta(days=1), "1h": pd.Timedelta(hours=1), "15m": pd.Timedelta(minutes=15), "5m": pd.Timedelta(minutes=5), "1m": pd.Timedelta(minutes=1)}[tf]
        expected = int((df.index[-1] - df.index[0]) / step) + 1
        miss = expected - len(df)
        rep.stats["expected_bars"] = expected
        if miss > 0:
            frac = miss / expected
            rep.add("missing_bars", "FAIL" if frac > 0.05 else "WARN", miss, f"{frac:.2%} of the 24/7 grid is missing (provider omits bars with no trades)")
    else:
        from .loader import _calendar
        cal = _calendar()
        d0 = df.index[0].tz_convert(ET).tz_localize(None).normalize()
        d1 = df.index[-1].tz_convert(ET).tz_localize(None).normalize()
        sess = cal.sessions(d0, d1)
        have = df.index.tz_convert(ET).tz_localize(None).normalize()
        if tf == "1d":
            missing = sess.difference(pd.DatetimeIndex(have.unique()))
            rep.stats["expected_sessions"] = len(sess)
            if len(missing):
                frac = len(missing) / len(sess)
                rep.add("missing_sessions", "FAIL" if frac > 0.02 else "WARN", len(missing),
                        f"{frac:.2%} of NYSE sessions have no bar; first: {', '.join(str(m.date()) for m in missing[:5])}")
            extra = pd.DatetimeIndex(have.unique()).difference(sess)
            if len(extra):
                rep.add("bars_on_non_sessions", "WARN", len(extra), f"bars on non-session days, e.g. {extra[0].date()}")
        else:
            mins = TF_MINUTES[tf]
            sch = cal.cal.schedule.loc[d0:d1]
            length = ((sch["close"] - sch["open"]).dt.total_seconds() / 60).to_numpy()
            exp = pd.Series(np.ceil(length / mins), index=sch.index)
            obs = pd.Series(1, index=have).groupby(level=0).sum().reindex(sch.index).fillna(0)
            comp = (obs / exp).clip(upper=1.0)
            rep.stats["mean_session_completeness"] = round(float(comp.mean()), 4)
            thin = int((comp < 0.9).sum())
            if comp.mean() < 0.90:
                rep.add("intraday_incomplete", "FAIL", thin, f"mean session completeness {comp.mean():.1%}")
            elif thin or comp.mean() < 0.98:
                rep.add("intraday_incomplete", "WARN", thin, f"{thin} sessions <90% complete (mean {comp.mean():.1%}); "
                        "bars with no trades are omitted by the provider so this is expected for illiquid names")
    # ---- bad ticks and unexplained jumps
    c = df["close"]
    r = c.pct_change()
    sig = _robust_sigma(r)
    thr = np.maximum(SPIKE_FLOOR[tf], 8 * sig)
    r_next = r.shift(-1)
    back = (c.shift(-1) / c.shift(1) - 1).abs()          # net move from before the spike to after it
    spike = (r.abs() > thr) & (back <= 0.5 * r.abs()) & (np.sign(r) != np.sign(r_next))
    if spike.any():
        rep.add("possible_bad_ticks", "WARN", spike.sum(), f"one-bar spikes that reverse next bar, e.g. {df.index[spike.to_numpy()][0]}")
    big = (r.abs() > (0.35 if tf == "1d" else 0.25))
    if big.any():
        rep.add("unexplained_large_moves", "WARN", big.sum(),
                f"|bar return| > {'35%' if tf == '1d' else '25%'} (check splits/halts), e.g. {df.index[big.to_numpy()][0]}")
    same = (df[["open", "high", "low", "close"]].diff().abs().sum(axis=1) == 0) & (df["volume"] == 0)
    run = same.groupby((~same).cumsum()).cumsum()
    if (run >= 5).any():
        rep.add("stale_prices", "WARN", int((run == 5).sum()), "5+ consecutive identical zero-volume bars")
    return rep


def cross_check(primary: pd.DataFrame, secondary: pd.DataFrame, label: str = "alpaca vs massive", tol_bps: float = 10.0) -> dict:
    """Compare RAW closes/volumes of two independent sources on their overlapping timestamps."""
    j = primary[["close", "volume"]].join(secondary[["close", "volume"]], how="inner", lsuffix="_a", rsuffix="_b")
    if j.empty:
        return {"label": label, "overlap_bars": 0, "ok": False, "detail": "no overlapping timestamps"}
    diff_bps = (j["close_a"] / j["close_b"] - 1).abs() * 1e4
    vol_ratio = (j["volume_a"] / j["volume_b"].replace(0, np.nan)).dropna()
    out = {"label": label, "overlap_bars": int(len(j)), "primary_bars_in_window": int(primary.index.isin(j.index).sum()),
           "median_abs_close_diff_bps": round(float(diff_bps.median()), 3), "p99_abs_close_diff_bps": round(float(diff_bps.quantile(0.99)), 3),
           "max_abs_close_diff_bps": round(float(diff_bps.max()), 3), "share_within_tol": round(float((diff_bps <= tol_bps).mean()), 4),
           "tol_bps": tol_bps, "median_volume_ratio_a_over_b": round(float(vol_ratio.median()), 4) if len(vol_ratio) else None}
    out["ok"] = out["share_within_tol"] >= 0.99
    return out
