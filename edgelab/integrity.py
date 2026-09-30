"""Data-integrity checks, gap ledger, and the discovery gate.

Design rules (never violated anywhere in edgelab):
  * nothing is silently dropped, forward-filled, interpolated, re-timestamped, substituted from another
    provider, or treated as zero -- every problem becomes a Gap in the ledger;
  * a Gap is MATERIAL, MINOR, AMBIGUOUS or EXPECTED; MATERIAL gaps must end RESOLVED or EXCLUDED
    (naming the experiments they are excluded from) before DiscoveryGate opens;
  * AMBIGUOUS means the data cannot distinguish "no trades occurred" from "provider dropped it"
    (aggregate bars are not emitted for empty intervals) -- it is documented, never assumed harmless.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

MATERIAL, MINOR, AMBIGUOUS, EXPECTED = "MATERIAL", "MINOR", "AMBIGUOUS", "EXPECTED"
OPEN, RESOLVED, EXCLUDED = "OPEN", "RESOLVED", "EXCLUDED"
MARKETS = {"US_EQUITY": "XNYS"}       # every market used by an experiment MUST be registered with a calendar


class UnknownMarket(Exception):
    pass


# =============================================================================== ledger
@dataclass
class Gap:
    dataset_id: str
    check: str
    kind: str
    severity: str
    detail: str
    ticker: str | None = None
    start: str | None = None
    end: str | None = None
    n: int = 1
    status: str = OPEN
    resolution: str = ""
    excluded_from: list = field(default_factory=list)
    gap_id: str = ""

    def __post_init__(self):
        if not self.gap_id:
            key = f"{self.dataset_id}|{self.check}|{self.kind}|{self.ticker}|{self.start}|{self.end}"
            self.gap_id = hashlib.sha1(key.encode()).hexdigest()[:12]
        if self.severity == EXPECTED:
            self.status = RESOLVED


class GapLedger:
    """In-memory ledger; if a Registry is supplied every gap and status change is appended (immutable)."""

    def __init__(self, registry=None):
        self.gaps: dict[str, Gap] = {}
        self.reg = registry

    def add(self, gaps: list[Gap]):
        for g in gaps:
            if g.gap_id in self.gaps:
                continue
            self.gaps[g.gap_id] = g
            if self.reg is not None:
                self.reg.append("DATA_GAP", {"event": "OPENED", **asdict(g)})

    def resolve(self, gap_id: str, how: str):
        g = self.gaps[gap_id]
        g.status, g.resolution = RESOLVED, how
        if self.reg is not None:
            self.reg.append("DATA_GAP", {"event": "RESOLVED", "gap_id": gap_id, "resolution": how})

    def exclude(self, gap_id: str, experiments: list[str], why: str):
        if not experiments:
            raise ValueError("an exclusion must name the experiments it applies to")
        g = self.gaps[gap_id]
        g.status, g.resolution, g.excluded_from = EXCLUDED, why, list(experiments)
        if self.reg is not None:
            self.reg.append("DATA_GAP", {"event": "EXCLUDED", "gap_id": gap_id, "resolution": why, "experiments": experiments})

    def unresolved_material(self, experiment: str | None = None) -> list[Gap]:
        out = []
        for g in self.gaps.values():
            if g.severity != MATERIAL or g.status == RESOLVED:
                continue
            if g.status == EXCLUDED and (experiment is None or experiment in g.excluded_from):
                continue
            out.append(g)
        return out

    def excluded_cells(self, experiment: str) -> list[Gap]:
        return [g for g in self.gaps.values() if g.status == EXCLUDED and experiment in g.excluded_from]

    def summary(self) -> pd.DataFrame:
        if not self.gaps:
            return pd.DataFrame(columns=["check", "kind", "severity", "status", "n_gaps"])
        df = pd.DataFrame([asdict(g) for g in self.gaps.values()])
        return df.groupby(["check", "kind", "severity", "status"]).size().rename("n_gaps").reset_index()


# =============================================================================== calendar (checks 1-2)
class MarketCalendar:
    def __init__(self, market: str = "US_EQUITY"):
        import exchange_calendars as xc
        if market not in MARKETS:
            raise UnknownMarket(f"market '{market}' has no registered trading calendar; register one before use")
        self.market, self.code = market, MARKETS[market]
        self.cal = xc.get_calendar(self.code)
        self.lib_version = xc.__version__

    def sessions(self, start, end) -> pd.DatetimeIndex:
        return self.cal.sessions_in_range(pd.Timestamp(start).tz_localize(None), pd.Timestamp(end).tz_localize(None))

    def classify_days(self, start, end) -> pd.DataFrame:
        days = pd.date_range(pd.Timestamp(start).tz_localize(None), pd.Timestamp(end).tz_localize(None), freq="D")
        sess = set(self.sessions(start, end))
        early = set(self.cal.early_closes)
        kind = []
        for d in days:
            if d in sess:
                kind.append("EARLY_CLOSE" if d in early else "TRADING")
            elif d.dayofweek >= 5:
                kind.append("WEEKEND")
            else:
                kind.append("HOLIDAY")
        return pd.DataFrame({"date": days, "kind": kind})

    def window_utc(self, session) -> tuple[pd.Timestamp, pd.Timestamp]:
        s = pd.Timestamp(session).tz_localize(None)
        return self.cal.session_open(s), self.cal.session_close(s)


# =============================================================================== helpers
def _runs(idx: list[int]) -> list[tuple[int, int]]:
    """Consecutive-integer runs -> [(first,last)]."""
    out, s, p = [], None, None
    for i in idx:
        if s is None:
            s = p = i
        elif i == p + 1:
            p = i
        else:
            out.append((s, p)); s = p = i
    if s is not None:
        out.append((s, p))
    return out


def _d(x) -> str:
    return pd.Timestamp(x).strftime("%Y-%m-%d")


# =============================================================================== check 3/2: sessions (daily bars)
def check_daily_sessions(daily: pd.DataFrame, cal: MarketCalendar, dataset_id: str, ref: pd.DataFrame | None = None,
                         liquid_min_volume: float = 100_000, partial_frac: float = 0.5) -> tuple[list[Gap], dict]:
    """daily: columns [ticker, date, open, high, low, close, volume]; `date` is the session date.
    ref (optional): [ticker, list_date, delist_date] (NaT allowed) from the security master."""
    gaps: list[Gap] = []
    df = daily.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.normalize()
    start, end = df["date"].min(), df["date"].max()
    days = cal.classify_days(start, end)
    expected = pd.DatetimeIndex(days.loc[days["kind"].isin(["TRADING", "EARLY_CLOSE"]), "date"])
    observed = pd.DatetimeIndex(sorted(df["date"].unique()))
    stats = {"calendar": f"{cal.code} (exchange_calendars {cal.lib_version})", "range": [_d(start), _d(end)],
             "expected_sessions": int(len(expected)), "observed_sessions": int(len(observed)),
             "non_trading_days_expected": days["kind"].value_counts().drop(["TRADING", "EARLY_CLOSE"], errors="ignore").to_dict(),
             "early_closes": int((days["kind"] == "EARLY_CLOSE").sum())}
    hol = days.loc[days["kind"] == "HOLIDAY", "date"]
    stats["weekday_holidays"] = [_d(x) for x in hol]
    # market-wide missing sessions
    miss = expected.difference(observed)
    for a, b in _runs([expected.get_loc(x) for x in miss]):
        gaps.append(Gap(dataset_id, "sessions", "MISSING_SESSION_MARKETWIDE", MATERIAL,
                        f"no bars for any ticker on expected sessions {_d(expected[a])}..{_d(expected[b])}",
                        start=_d(expected[a]), end=_d(expected[b]), n=b - a + 1))
    # data on days the market was closed
    unexp = observed.difference(expected)
    for d in unexp:
        gaps.append(Gap(dataset_id, "sessions", "DATA_ON_NON_TRADING_DAY", MATERIAL,
                        f"{int((df['date'] == d).sum())} bars on {_d(d)} which the calendar lists as closed "
                        f"({days.loc[days['date'] == d, 'kind'].iloc[0] if (days['date'] == d).any() else 'n/a'}): calendar or provider error",
                        start=_d(d), end=_d(d)))
    # cross-sectional coverage per session
    cov = df.groupby("date")["ticker"].nunique().reindex(expected)
    med = cov.median()
    part = cov[(cov.notna()) & (cov < partial_frac * med)]
    for d, n in part.items():
        gaps.append(Gap(dataset_id, "sessions", "PARTIAL_SESSION", MATERIAL,
                        f"only {int(n)} tickers on {_d(d)} vs median {int(med)}", start=_d(d), end=_d(d)))
    # per-ticker missing sessions
    pos = {d: i for i, d in enumerate(expected)}
    refi = ref.set_index("ticker") if ref is not None else None
    n_liq = n_amb = 0
    for tk, g in df.groupby("ticker"):
        dates = pd.DatetimeIndex(sorted(g["date"].unique()))
        first, last = dates.min(), dates.max()
        lo, hi = first, last
        if refi is not None and tk in refi.index:
            ld, dd = refi.loc[tk, "list_date"], refi.loc[tk, "delist_date"]
            if pd.notna(ld):
                ld = pd.Timestamp(ld).tz_localize(None).normalize()
                lag = int(((expected >= ld) & (expected < first)).sum())
                if lag > 5:
                    gaps.append(Gap(dataset_id, "sessions", "MISSING_HEAD", MATERIAL if lag > 20 else MINOR,
                                    f"{tk}: first bar {_d(first)} is {lag} sessions after listing {_d(ld)}", ticker=tk,
                                    start=_d(ld), end=_d(first), n=lag))
                lo = min(lo, ld) if ld > first else first
                if ld > first:
                    gaps.append(Gap(dataset_id, "sessions", "BARS_BEFORE_LISTING", MATERIAL,
                                    f"{tk}: bars from {_d(first)} precede listing date {_d(ld)}", ticker=tk, start=_d(first), end=_d(ld)))
            if pd.notna(dd):
                dd = pd.Timestamp(dd).tz_localize(None).normalize()
                tail = int(((expected > last) & (expected <= dd)).sum())
                if tail > 5:
                    gaps.append(Gap(dataset_id, "sessions", "MISSING_TAIL", MATERIAL,
                                    f"{tk}: last bar {_d(last)} but delisted {_d(dd)} ({tail} sessions without data)", ticker=tk,
                                    start=_d(last), end=_d(dd), n=tail))
                if last > dd + pd.Timedelta(days=3):
                    gaps.append(Gap(dataset_id, "sessions", "BARS_AFTER_DELISTING", MATERIAL,
                                    f"{tk}: bars until {_d(last)} after delisting {_d(dd)}", ticker=tk, start=_d(dd), end=_d(last)))
        window = expected[(expected >= lo) & (expected <= hi)].difference(miss)   # market-wide outages are already recorded above
        missing = window.difference(dates)
        if len(missing) == 0:
            continue
        liquid = float(g["volume"].median()) >= liquid_min_volume
        idx = [pos[d] for d in missing]
        for a, b in _runs(idx):
            sev = MATERIAL if liquid else AMBIGUOUS
            kind = "MISSING_SESSION_LIQUID" if liquid else "NO_TRADE_OR_MISSING"
            gaps.append(Gap(dataset_id, "sessions", kind, sev,
                            f"{tk}: {b - a + 1} consecutive session(s) without a bar ({'liquid name always trades -> provider gap' if liquid else 'illiquid: cannot distinguish no trades from provider drop'})",
                            ticker=tk, start=_d(expected[a]), end=_d(expected[b]), n=b - a + 1))
        n_liq += int(liquid) * len(missing); n_amb += int(not liquid) * len(missing)
    stats["missing_ticker_sessions_liquid"] = n_liq
    stats["missing_ticker_sessions_ambiguous"] = n_amb
    return gaps, stats


# =============================================================================== check 4/6: intraday bars & timestamp gaps
def check_minute_bars(bars: pd.DataFrame, cal: MarketCalendar, dataset_id: str, liquid_min_session_volume: float = 200_000,
                      max_gap_minutes: int = 5) -> tuple[list[Gap], dict]:
    """bars: [ticker, ts (tz-aware UTC or epoch ms), open, high, low, close, volume]. Regular session expected grid
    is derived from the exchange calendar in UTC, so DST and early closes are handled by construction."""
    gaps: list[Gap] = []
    b = bars.copy()
    if pd.api.types.is_numeric_dtype(b["ts"].dtype):
        b["ts"] = pd.to_datetime(b["ts"], unit="ms", utc=True)
    elif b["ts"].dt.tz is None:
        gaps.append(Gap(dataset_id, "minute_bars", "NAIVE_TIMESTAMPS", MATERIAL, "timestamps carry no timezone", n=len(b)))
        b["ts"] = b["ts"].dt.tz_localize("UTC")
    off = b["ts"].dt.second.ne(0) | b["ts"].dt.microsecond.ne(0)
    if off.any():
        gaps.append(Gap(dataset_id, "minute_bars", "TIMESTAMP_MISALIGNED", MATERIAL, f"{int(off.sum())} bars not on a minute boundary", n=int(off.sum())))
    b["session"] = b["ts"].dt.tz_convert("America/New_York").dt.tz_localize(None).dt.normalize()
    stats = {"n_bars": int(len(b)), "sessions": 0, "regular_expected": 0, "regular_observed": 0, "missing_regular_liquid": 0,
             "missing_regular_ambiguous": 0, "extended_hours_bars": 0}
    sessions = cal.sessions(b["session"].min(), b["session"].max())
    exp_sessions = set(sessions)
    for s in sorted(set(b["session"]) - exp_sessions):
        gaps.append(Gap(dataset_id, "minute_bars", "DATA_ON_NON_TRADING_DAY", MATERIAL,
                        f"bars on closed day {_d(s)}", start=_d(s), end=_d(s), n=int((b["session"] == s).sum())))
    for (tk, s), g in b[b["session"].isin(exp_sessions)].groupby(["ticker", "session"]):
        stats["sessions"] += 1
        o, c = cal.window_utc(s)
        ts = g["ts"]
        # duplicates
        dup = ts.duplicated(keep=False)
        if dup.any():
            conflicting = g[dup].groupby("ts")[["open", "high", "low", "close", "volume"]].nunique().gt(1).any(axis=1).any()
            gaps.append(Gap(dataset_id, "duplicates", "CONFLICTING_DUPLICATE_BARS" if conflicting else "EXACT_DUPLICATE_BARS",
                            MATERIAL if conflicting else MINOR, f"{tk} {_d(s)}: {int(dup.sum())} duplicated timestamps", ticker=tk,
                            start=_d(s), end=_d(s), n=int(dup.sum())))
        reg = g[(g["ts"] >= o) & (g["ts"] < c)]
        stats["extended_hours_bars"] += int(len(g) - len(reg))
        grid = pd.date_range(o, c, freq="1min", inclusive="left")
        have = pd.DatetimeIndex(reg["ts"].unique())
        miss = grid.difference(have)
        stats["regular_expected"] += len(grid); stats["regular_observed"] += len(have)
        if len(miss):
            liquid = float(reg["volume"].sum()) >= liquid_min_session_volume
            key = "missing_regular_liquid" if liquid else "missing_regular_ambiguous"
            stats[key] += len(miss)
            gi = [grid.get_loc(x) for x in miss]
            for a, z in _runs(gi):
                if liquid and (z - a + 1) < 3:
                    continue    # isolated 1-2 minute holes in a liquid name: counted in stats, reported in aggregate below
                gaps.append(Gap(dataset_id, "minute_bars", "MISSING_MINUTES_LIQUID" if liquid else "NO_TRADE_OR_MISSING_MINUTES",
                                MATERIAL if liquid else AMBIGUOUS,
                                f"{tk} {_d(s)}: {z - a + 1} consecutive missing regular-session minutes from {grid[a].strftime('%H:%M')}Z",
                                ticker=tk, start=grid[a].isoformat(), end=grid[z].isoformat(), n=z - a + 1))
            if liquid and len(miss) >= 3:
                gaps.append(Gap(dataset_id, "minute_bars", "SCATTERED_MISSING_MINUTES_LIQUID", MINOR,
                                f"{tk} {_d(s)}: {len(miss)} missing minutes in total", ticker=tk, start=_d(s), end=_d(s), n=len(miss)))
        # timestamp gaps inside the observed span
        if len(have) > 1:
            gapmin = np.diff(have.asi8) / 60e9
            big = np.flatnonzero(gapmin > max_gap_minutes)
            for i in big:
                liquid = float(reg["volume"].sum()) >= liquid_min_session_volume
                gaps.append(Gap(dataset_id, "timestamp_gaps", "INTRASESSION_TIMESTAMP_GAP", MATERIAL if liquid else AMBIGUOUS,
                                f"{tk}: {gapmin[i]:.0f} min between consecutive bars at {have[i].strftime('%H:%M')}Z {_d(s)}", ticker=tk,
                                start=have[i].isoformat(), end=have[i + 1].isoformat(), n=int(gapmin[i])))
        # stale: >= 10 identical closes with volume in a liquid name
        if len(reg) >= 10 and float(reg["volume"].sum()) >= liquid_min_session_volume:
            r = reg.sort_values("ts")
            same = (r["close"].diff() == 0) & (r["high"] == r["low"]) & (r["volume"] > 0)
            run = (same.groupby((~same).cumsum()).cumsum()).max()
            if run >= 10:
                gaps.append(Gap(dataset_id, "stale", "STALE_MINUTE_PRICES", MATERIAL,
                                f"{tk} {_d(s)}: {int(run)} consecutive flat bars with volume", ticker=tk, start=_d(s), end=_d(s), n=int(run)))
    return gaps, stats


# =============================================================================== check 5/7: duplicates & stale (daily)
def check_duplicates(df: pd.DataFrame, key: list[str], dataset_id: str, label: str = "rows") -> list[Gap]:
    dup = df[df.duplicated(key, keep=False)]
    if dup.empty:
        return []
    val_cols = [c for c in df.columns if c not in key]
    conflicting = int((dup.groupby(key)[val_cols].nunique(dropna=False).gt(1).any(axis=1)).sum())
    return [Gap(dataset_id, "duplicates", "CONFLICTING_DUPLICATES" if conflicting else "EXACT_DUPLICATES",
                MATERIAL if conflicting else MINOR,
                f"{len(dup)} {label} share a key {key}; {conflicting} key(s) have conflicting values", n=len(dup))]


def check_stale_daily(daily: pd.DataFrame, dataset_id: str, liquid_min_volume: float = 100_000, run_len: int = 3) -> list[Gap]:
    gaps = []
    for tk, g in daily.sort_values("date").groupby("ticker"):
        if float(g["volume"].median()) < liquid_min_volume:
            continue
        same = (g["close"].diff() == 0) & (g["open"] == g["close"]) & (g["high"] == g["low"])
        run = int(same.groupby((~same).cumsum()).cumsum().max())
        if run >= run_len:
            gaps.append(Gap(dataset_id, "stale", "STALE_DAILY_PRICES", MATERIAL,
                            f"{tk}: {run + 1} consecutive identical flat daily bars in a liquid name", ticker=tk, n=run + 1))
        zero = g["volume"] <= 0
        if zero.any():
            gaps.append(Gap(dataset_id, "stale", "ZERO_VOLUME_BARS", MINOR, f"{tk}: {int(zero.sum())} zero-volume bars", ticker=tk, n=int(zero.sum())))
    return gaps


# =============================================================================== check 8: news timestamps
def check_news(news: pd.DataFrame, dataset_id: str, retrieved_at: pd.Timestamp, cal: MarketCalendar | None = None) -> tuple[list[Gap], dict]:
    """news: [id, published_utc, title, publisher_name, tickers(list|json str), article_url]."""
    gaps: list[Gap] = []
    n = len(news)
    ts_raw = news["published_utc"]
    # strict per-element ISO-8601 parsing: pandas otherwise infers ONE format from the first value and silently
    # coerces every non-matching row to NaT
    ts = pd.to_datetime(ts_raw, utc=True, errors="coerce", format="ISO8601")
    stats = {"n_articles": n}
    bad = ts.isna()
    notz = ts_raw.astype(str).str.match(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?(\.\d+)?$")
    if bad.any():
        gaps.append(Gap(dataset_id, "news_timestamps", "MISSING_OR_UNPARSEABLE_TIMESTAMP", MATERIAL,
                        f"{int((bad & ~notz).sum())} articles have null/unparseable publication time (cannot be used as point-in-time signals)", n=int((bad & ~notz).sum())))
    if notz.any():
        gaps.append(Gap(dataset_id, "news_timestamps", "TIMEZONE_MISSING", MATERIAL, f"{int(notz.sum())} timestamps lack a timezone designator (treated as UNUSABLE, not assumed UTC)", n=int(notz.sum())))
        ts = ts.mask(notz)      # never guess the timezone
        bad = ts.isna()
    fut = ts > pd.Timestamp(retrieved_at).tz_convert("UTC") if pd.Timestamp(retrieved_at).tzinfo else ts > pd.Timestamp(retrieved_at, tz="UTC")
    if fut.any():
        gaps.append(Gap(dataset_id, "news_timestamps", "PUBLISHED_AFTER_RETRIEVAL", MATERIAL, f"{int(fut.sum())} articles dated after retrieval time", n=int(fut.sum())))
    old = ts < pd.Timestamp("1995-01-01", tz="UTC")
    if old.any():
        gaps.append(Gap(dataset_id, "news_timestamps", "IMPLAUSIBLE_EARLY_TIMESTAMP", MATERIAL, f"{int(old.sum())} articles before 1995", n=int(old.sum())))
    midnight = (ts.dt.hour == 0) & (ts.dt.minute == 0) & (ts.dt.second == 0)
    stats["midnight_utc_fraction"] = float(midnight[~bad].mean()) if (~bad).any() else float("nan")
    if midnight.sum() > 0.02 * n:
        gaps.append(Gap(dataset_id, "news_timestamps", "DATE_ONLY_TIMESTAMPS", MATERIAL, f"{int(midnight.sum())} articles at exactly 00:00:00Z (date-only precision?)", n=int(midnight.sum())))
    coarse = (ts.dt.second == 0)
    stats["zero_seconds_fraction"] = float(coarse[~bad].mean()) if (~bad).any() else float("nan")
    q = ts[~bad].dt.minute.isin([0, 15, 30, 45]).mean() if (~bad).any() else float("nan")
    stats["quarter_hour_fraction"] = float(q)
    if coarse[~bad].mean() > 0.9:
        gaps.append(Gap(dataset_id, "news_timestamps", "MINUTE_RESOLUTION_ONLY", MINOR, "publication times have minute resolution only: latency below 1 minute is unobservable"))
    # vendor/system receipt timestamps are required for latency modelling
    for col in ("vendor_receipt_ts", "system_receipt_ts"):
        if col not in news.columns:
            gaps.append(Gap(dataset_id, "news_timestamps", f"NO_{col.upper()}", MATERIAL,
                            f"dataset has no {col}: true availability time of each article is unknown; a latency assumption is required and must be stress-tested"))
    # duplicates / syndication
    if "id" in news:
        gaps += check_duplicates(news[["id", "published_utc", "title"]], ["id"], dataset_id, "articles")
    norm = news["title"].fillna("").str.lower().str.replace(r"[^a-z0-9 ]", "", regex=True).str.strip()
    syn = pd.DataFrame({"t": norm, "pub": news.get("publisher_name"), "ts": ts}).dropna()
    syn = syn[syn["t"].str.len() > 15]
    grp = syn.groupby("t")["pub"].nunique()
    multi = int((grp > 1).sum())
    stats["syndicated_titles_multi_publisher"] = multi
    stats["distinct_publishers"] = int(news["publisher_name"].nunique()) if "publisher_name" in news else None
    if multi:
        gaps.append(Gap(dataset_id, "news_independence", "SYNDICATED_ARTICLES", MINOR,
                        f"{multi} headlines appear under multiple publishers: sources are not independent", n=multi))
    # ticker mapping
    if "tickers" in news:
        empty = news["tickers"].apply(lambda x: (x is None) or (isinstance(x, (list, str)) and len(x) in (0, 2)) or (isinstance(x, float)))
        if empty.any():
            gaps.append(Gap(dataset_id, "news_timestamps", "NO_TICKER_MAPPING", MINOR, f"{int(empty.sum())} articles carry no ticker tags", n=int(empty.sum())))
    # coverage: calendar days with zero articles vs typical (only plausible timestamps: not future-dated, not ancient)
    valid = ~bad & ~fut & ~old
    if cal is not None and valid.any():
        tv = ts[valid]
        d0, d1 = tv.min().tz_convert(None).normalize(), tv.max().tz_convert(None).normalize()
        expected = cal.sessions(d0, d1)
        per_day = tv.dt.tz_convert("America/New_York").dt.tz_localize(None).dt.normalize().value_counts()
        cnt = per_day.reindex(expected).fillna(0)
        med = float(cnt.median())
        if med >= 5:
            dead = cnt[cnt < 0.1 * med]
            for d in dead.index:
                gaps.append(Gap(dataset_id, "news_coverage", "NEWS_COVERAGE_GAP", MATERIAL,
                                f"{int(cnt[d])} articles on trading day {_d(d)} vs median {int(med)}", start=_d(d), end=_d(d)))
        stats["median_articles_per_session"] = med
    return gaps, stats


# =============================================================================== check 9: corporate-action gaps
COMMON_RATIOS = [2, 3, 4, 5, 6, 8, 10, 15, 20, 25, 50, 100]


def check_corporate_actions(daily_unadj: pd.DataFrame, splits: pd.DataFrame, dataset_id: str, ref: pd.DataFrame | None = None,
                            dividends: pd.DataFrame | None = None, jump: float = 0.35, tol: float = 0.12) -> tuple[list[Gap], dict]:
    """daily_unadj: UNADJUSTED [ticker,date,open,close,...]. splits: [ticker, execution_date, split_from, split_to].
    A split with ratio r means shares x r, price / r. Flags: recorded split without price discontinuity (data may be adjusted
    or bar missing), price discontinuity without a recorded action, delistings with missing terminal information."""
    gaps: list[Gap] = []
    df = daily_unadj.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.normalize()
    df = df.sort_values(["ticker", "date"])
    df["prev_close"] = df.groupby("ticker")["close"].shift(1)
    df["r"] = df["open"] / df["prev_close"]
    sp = splits.copy() if splits is not None else pd.DataFrame(columns=["ticker", "execution_date", "split_from", "split_to"])
    if len(sp):
        sp["execution_date"] = pd.to_datetime(sp["execution_date"]).dt.tz_localize(None).dt.normalize()
        sp["ratio"] = sp["split_to"] / sp["split_from"]
    stats = {"recorded_splits": int(len(sp)), "splits_confirmed_in_prices": 0, "splits_without_discontinuity": 0, "unrecorded_discontinuities": 0}
    covered = set()
    for _, s in sp.iterrows():
        g = df[(df["ticker"] == s["ticker"]) & (df["date"] >= s["execution_date"] - pd.Timedelta(days=4)) & (df["date"] <= s["execution_date"] + pd.Timedelta(days=4))]
        if g.empty:
            gaps.append(Gap(dataset_id, "corporate_actions", "SPLIT_NO_PRICE_DATA", MATERIAL,
                            f"{s['ticker']}: split on {_d(s['execution_date'])} but no bars within ±4 days", ticker=s["ticker"],
                            start=_d(s["execution_date"]), end=_d(s["execution_date"])))
            continue
        expect = 1.0 / s["ratio"]
        hit = g[np.abs(g["r"] / expect - 1) < tol]
        covered.add((s["ticker"], s["execution_date"]))
        for d in g["date"]:
            covered.add((s["ticker"], d))
        if len(hit):
            stats["splits_confirmed_in_prices"] += 1
        else:
            stats["splits_without_discontinuity"] += 1
            gaps.append(Gap(dataset_id, "corporate_actions", "SPLIT_WITHOUT_DISCONTINUITY", MATERIAL,
                            f"{s['ticker']}: split {s['split_to']:g}-for-{s['split_from']:g} on {_d(s['execution_date'])} not visible in prices "
                            f"(open/prev close={g['r'].min():.2f}..{g['r'].max():.2f}): series may be adjusted, or a bar is missing",
                            ticker=s["ticker"], start=_d(s["execution_date"]), end=_d(s["execution_date"])))
    big = df[np.isfinite(df["r"]) & ((df["r"] < 1 - jump) | (df["r"] > 1 + 2 * jump))]
    for _, row in big.iterrows():
        if (row["ticker"], row["date"]) in covered:
            continue
        stats["unrecorded_discontinuities"] += 1
        near_ratio = any(abs(row["r"] - 1 / k) / (1 / k) < tol or abs(row["r"] - k) / k < tol for k in COMMON_RATIOS)
        gaps.append(Gap(dataset_id, "corporate_actions", "UNRECORDED_SPLIT_LIKE_DISCONTINUITY" if near_ratio else "LARGE_UNEXPLAINED_GAP",
                        MATERIAL if near_ratio else MINOR,
                        f"{row['ticker']} {_d(row['date'])}: open/prev close={row['r']:.3f} with no recorded corporate action"
                        + (" (matches a common split ratio)" if near_ratio else " (may be a genuine news gap; verify)"),
                        ticker=row["ticker"], start=_d(row["date"]), end=_d(row["date"])))
    # delistings need terminal information; unknown is never assumed to be zero
    if ref is not None and "delist_date" in ref:
        for _, r_ in ref[ref["delist_date"].notna()].iterrows():
            if "delist_return" not in ref.columns or pd.isna(r_.get("delist_return")):
                gaps.append(Gap(dataset_id, "corporate_actions", "DELISTING_RETURN_UNKNOWN", MATERIAL,
                                f"{r_['ticker']}: delisted {_d(r_['delist_date'])}; terminal return/reason unknown (bankruptcy vs acquisition); it is NOT assumed to be 0",
                                ticker=r_["ticker"], start=_d(r_["delist_date"]), end=_d(r_["delist_date"])))
    if dividends is not None and len(dividends):
        stats["recorded_dividends"] = int(len(dividends))
    return gaps, stats


# =============================================================================== report & gate
@dataclass
class ExperimentRequirements:
    name: str
    markets: list[str]
    needs: list[str]                 # dataset kinds that must have been validated over the full intended period
    period: tuple[str, str]
    universe_desc: str


class DiscoveryGate:
    """Opens only if the report is COMPLETE for the requested dataset coverage and no material gap is OPEN."""

    @staticmethod
    def check(report: "IntegrityReport", req: ExperimentRequirements, ledger: GapLedger) -> tuple[bool, list[str]]:
        why: list[str] = []
        for m in req.markets:
            if m not in MARKETS:
                why.append(f"market {m} has no registered trading calendar")
        for need in req.needs:
            c = report.coverage.get(need)
            if not c:
                why.append(f"dataset '{need}' has not been ingested or validated")
            elif not c.get("complete"):
                why.append(f"dataset '{need}': coverage incomplete ({c.get('note', 'sample only')})")
        for chk in report.REQUIRED_CHECKS:
            if chk not in report.checks_run:
                why.append(f"integrity check '{chk}' has not been run")
        for g in ledger.unresolved_material(req.name):
            why.append(f"OPEN material gap {g.gap_id} [{g.kind}] {g.ticker or ''} {g.start or ''}: {g.detail[:90]}")
        return (not why), why


@dataclass
class IntegrityReport:
    REQUIRED_CHECKS = ("calendar", "sessions", "minute_bars", "duplicates", "timestamp_gaps", "stale", "news_timestamps", "corporate_actions")
    dataset_ids: list[str] = field(default_factory=list)
    checks_run: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    coverage: dict = field(default_factory=dict)      # dataset kind -> {"complete": bool, "requested":..., "ingested":..., "note":...}
    provider_notes: list[str] = field(default_factory=list)

    def to_markdown(self, ledger: GapLedger, title: str = "Data-integrity report") -> str:
        L = [f"# {title}", ""]
        L += ["## Coverage of the intended research dataset", "", "| dataset | complete | requested | ingested | note |", "|---|---|---|---|---|"]
        for k, c in self.coverage.items():
            L.append(f"| {k} | {'YES' if c.get('complete') else '**NO**'} | {c.get('requested','')} | {c.get('ingested','')} | {c.get('note','')} |")
        L += ["", "## Checks run", "", ", ".join(self.checks_run) or "(none)", ""]
        L += ["## Statistics", "", "```json", json.dumps(self.stats, indent=1, default=str), "```", ""]
        L += ["## Gap ledger summary", ""]
        s = ledger.summary()
        L.append(s.to_markdown(index=False) if len(s) else "_no gaps recorded_")
        L += ["", "## Material gaps (all listed)", ""]
        mg = [g for g in ledger.gaps.values() if g.severity == MATERIAL]
        if not mg:
            L.append("_none_")
        for g in mg[:200]:
            L.append(f"- `{g.gap_id}` **{g.kind}** {g.ticker or ''} {g.start or ''}..{g.end or ''} — {g.detail} — status: **{g.status}** {g.resolution}")
        if len(mg) > 200:
            L.append(f"- … {len(mg) - 200} more in the registry")
        if self.provider_notes:
            L += ["", "## Provider notes / limitations", ""] + [f"- {x}" for x in self.provider_notes]
        return "\n".join(L)
