"""Seeded-defect tests: every detector must find exactly what was planted and nothing on clean data."""
import numpy as np
import pandas as pd
import pytest

from edgelab.data import DataGapError
from edgelab.engine import Exec, run_backtest
from edgelab.integrity import (DiscoveryGate, ExperimentRequirements, GapLedger, IntegrityReport, MarketCalendar, MATERIAL,
                               AMBIGUOUS, UnknownMarket, check_corporate_actions, check_daily_sessions, check_duplicates,
                               check_minute_bars, check_news, check_stale_daily)
from edgelab.synthetic import make_market

CAL = MarketCalendar("US_EQUITY")


def clean_daily(start="2024-10-01", end="2025-03-31", tickers=("AAA", "BBB", "ILL")):
    sess = CAL.sessions(start, end)
    rng = np.random.default_rng(0)
    rows = []
    for tk in tickers:
        px = 100.0
        for d in sess:
            o = px * (1 + rng.normal(0, 0.004)); c = o * (1 + rng.normal(0, 0.01))
            rows.append((tk, d, o, max(o, c) * 1.002, min(o, c) * 0.998, c, 5e6 if tk != "ILL" else 2e4))
            px = c
    return pd.DataFrame(rows, columns=["ticker", "date", "open", "high", "low", "close", "volume"])


def kinds(gaps, sev=None):
    return sorted(g.kind for g in gaps if sev is None or g.severity == sev)


# ------------------------------------------------------------------ calendar: expected vs missing
def test_calendar_classifies_expected_non_trading_days():
    days = CAL.classify_days("2024-11-25", "2024-12-02").set_index("date")["kind"]
    assert days["2024-11-28"] == "HOLIDAY" and days["2024-11-29"] == "EARLY_CLOSE"
    assert days["2024-11-30"] == "WEEKEND" and days["2024-11-27"] == "TRADING"
    assert CAL.classify_days("2025-01-08", "2025-01-10").set_index("date")["kind"]["2025-01-09"] == "HOLIDAY"  # national day of mourning


def test_unknown_market_is_refused():
    with pytest.raises(UnknownMarket):
        MarketCalendar("JP_EQUITY")


def test_clean_daily_data_has_no_material_gaps_holidays_are_not_flagged():
    gaps, st = check_daily_sessions(clean_daily(), CAL, "d")
    assert not [g for g in gaps if g.severity in (MATERIAL, AMBIGUOUS)], kinds(gaps)
    assert st["expected_sessions"] == st["observed_sessions"] and "2024-11-28" in st["weekday_holidays"]


def test_seeded_session_defects_are_detected_exactly():
    df = clean_daily()
    df = df[df["date"] != "2024-12-12"]                                                   # provider outage, market-wide
    holiday = df[(df["ticker"] == "AAA") & (df["date"] == "2024-11-27")].assign(date=pd.Timestamp("2024-11-28"))
    df = pd.concat([df, holiday])                                                          # bars on Thanksgiving
    df = df[~((df["ticker"] == "AAA") & df["date"].isin(pd.to_datetime(["2025-01-14", "2025-01-15", "2025-01-16"])))]  # liquid: 3 sessions
    df = df[~((df["ticker"] == "ILL") & df["date"].isin(pd.to_datetime(["2025-02-10", "2025-02-11"])))]                 # illiquid: 2 sessions
    gaps, _ = check_daily_sessions(df, CAL, "d")
    by = {k: [g for g in gaps if g.kind == k] for k in set(kinds(gaps))}
    assert len(by["MISSING_SESSION_MARKETWIDE"]) == 1 and by["MISSING_SESSION_MARKETWIDE"][0].start == "2024-12-12"
    assert len(by["DATA_ON_NON_TRADING_DAY"]) == 1 and by["DATA_ON_NON_TRADING_DAY"][0].start == "2024-11-28"
    liq = by["MISSING_SESSION_LIQUID"]
    assert len(liq) == 1 and liq[0].ticker == "AAA" and liq[0].n == 3 and liq[0].severity == MATERIAL
    amb = by["NO_TRADE_OR_MISSING"]
    assert len(amb) == 1 and amb[0].ticker == "ILL" and amb[0].n == 2 and amb[0].severity == AMBIGUOUS


def test_listing_and_delisting_reference_checks():
    df = clean_daily()
    ref = pd.DataFrame({"ticker": ["AAA", "BBB", "ILL"], "list_date": [pd.NaT, pd.NaT, pd.NaT],
                        "delist_date": [pd.NaT, pd.Timestamp("2025-03-14"), pd.NaT]})
    df = df[~((df["ticker"] == "BBB") & (df["date"] > "2025-02-14"))]                # data stops a month before delisting
    gaps, _ = check_daily_sessions(df, CAL, "d", ref=ref)
    tail = [g for g in gaps if g.kind == "MISSING_TAIL"]
    assert len(tail) == 1 and tail[0].ticker == "BBB" and tail[0].n >= 15


def test_duplicates_exact_vs_conflicting():
    df = clean_daily()
    exact = pd.concat([df, df.iloc[[5]]])
    g = check_duplicates(exact, ["ticker", "date"], "d")
    assert kinds(g) == ["EXACT_DUPLICATES"]
    conflict = pd.concat([df, df.iloc[[5]].assign(close=999.0)])
    g = check_duplicates(conflict, ["ticker", "date"], "d")
    assert kinds(g) == ["CONFLICTING_DUPLICATES"] and g[0].severity == MATERIAL
    assert not check_duplicates(df, ["ticker", "date"], "d")


def test_stale_daily_prices():
    df = clean_daily()
    m = (df["ticker"] == "AAA") & (df["date"].between("2025-01-06", "2025-01-10"))
    df.loc[m, ["open", "high", "low", "close"]] = 123.0
    g = check_stale_daily(df, "d")
    assert kinds(g) == ["STALE_DAILY_PRICES"] and g[0].ticker == "AAA"
    assert not check_stale_daily(clean_daily(), "d")


# ------------------------------------------------------------------ minute bars: DST, early close, gaps
def minute_session(tk, session, cal=CAL, vol=2000, ext=False, drop=()):
    o, c = cal.window_utc(session)
    ts = pd.date_range(o, c, freq="1min", inclusive="left")
    if ext:
        ts = ts.append(pd.date_range(o - pd.Timedelta(minutes=30), o, freq="1min", inclusive="left")).sort_values()
    ts = ts.difference(pd.DatetimeIndex(drop))
    px = 100 + np.cumsum(np.random.default_rng(1).normal(0, 0.02, len(ts)))
    return pd.DataFrame({"ticker": tk, "ts": ts, "open": px, "high": px + 0.01, "low": px - 0.01, "close": px + 0.005, "volume": vol})


@pytest.mark.parametrize("session", ["2025-03-07", "2025-03-10", "2024-11-01", "2024-11-04", "2024-11-29"])  # pre/post DST, half-day
def test_clean_minute_sessions_across_dst_and_early_close_have_no_gaps(session):
    b = minute_session("AAA", session, ext=True)
    gaps, st = check_minute_bars(b, CAL, "m")
    assert not [g for g in gaps if g.severity == MATERIAL], kinds(gaps)
    assert st["regular_expected"] == (210 if session == "2024-11-29" else 390)
    assert st["extended_hours_bars"] == 30


def test_dst_changes_utc_open():
    a, _ = CAL.window_utc("2025-03-07"); b, _ = CAL.window_utc("2025-03-10")
    assert (a.hour, b.hour) == (14, 13)          # 09:30 ET = 14:30Z before DST, 13:30Z after


def test_seeded_minute_defects():
    o, _ = CAL.window_utc("2025-03-10")
    drop = list(pd.date_range(o + pd.Timedelta(minutes=100), periods=10, freq="1min"))
    b = minute_session("AAA", "2025-03-10", drop=drop)
    b = pd.concat([b, b.iloc[[50]], b.iloc[[60]].assign(close=1.0)])                 # exact + conflicting duplicate
    b.loc[b.index[5], "ts"] += pd.Timedelta(seconds=17)                              # off-grid timestamp
    gaps, st = check_minute_bars(b, CAL, "m")
    ks = kinds(gaps)
    assert "MISSING_MINUTES_LIQUID" in ks and any(g.n == 10 for g in gaps if g.kind == "MISSING_MINUTES_LIQUID")
    assert "TIMESTAMP_MISALIGNED" in ks and "CONFLICTING_DUPLICATE_BARS" in ks
    assert any(g.kind == "INTRASESSION_TIMESTAMP_GAP" and g.n == 11 for g in gaps)
    thin = minute_session("ILL", "2025-03-10", vol=1, drop=drop)
    g2, _ = check_minute_bars(thin, CAL, "m")
    assert all(g.severity == AMBIGUOUS for g in g2 if g.kind in ("NO_TRADE_OR_MISSING_MINUTES", "INTRASESSION_TIMESTAMP_GAP"))


def test_naive_timestamps_flagged():
    b = minute_session("AAA", "2025-03-10")
    b["ts"] = b["ts"].dt.tz_convert(None)
    gaps, _ = check_minute_bars(b, CAL, "m")
    assert "NAIVE_TIMESTAMPS" in kinds(gaps)


# ------------------------------------------------------------------ news
def clean_news(n=400):
    sess = CAL.sessions("2025-01-02", "2025-03-28")
    rng = np.random.default_rng(3)
    ts = [pd.Timestamp(d).tz_localize("UTC") + pd.Timedelta(hours=int(rng.integers(12, 22)), minutes=int(rng.integers(0, 60)), seconds=int(rng.integers(1, 59)))
          for d in rng.choice(sess, n)]
    # make sure every session has coverage
    ts += [pd.Timestamp(d).tz_localize("UTC") + pd.Timedelta(hours=15, minutes=1, seconds=7) for d in sess for _ in range(6)]
    df = pd.DataFrame({"id": [f"id{i}" for i in range(len(ts))], "published_utc": [t.isoformat() for t in ts],
                       "title": [f"Unique headline number {i} about the company" for i in range(len(ts))],
                       "publisher_name": "Pub", "tickers": '["AAA"]', "vendor_receipt_ts": ts, "system_receipt_ts": ts})
    return df


def test_clean_news_has_no_material_gaps():
    gaps, _ = check_news(clean_news(), "n", pd.Timestamp("2025-04-01", tz="UTC"), CAL)
    assert not [g for g in gaps if g.severity == MATERIAL], [(g.kind, g.detail) for g in gaps]


def test_seeded_news_defects():
    df = clean_news()
    df.loc[0, "published_utc"] = None
    df.loc[1, "published_utc"] = "garbage"
    df.loc[2, "published_utc"] = "2025-02-03T14:00:00"                       # no timezone
    df.loc[3, "published_utc"] = "2026-01-01T00:00:00Z"                      # after retrieval
    df.loc[4, "id"] = df.loc[5, "id"]                                        # duplicate id
    df.loc[6, "publisher_name"] = "Other"; df.loc[7, "publisher_name"] = "Other"
    df.loc[7, "title"] = df.loc[6, "title"] = "Big merger announced between two firms today"; df.loc[6, "publisher_name"] = "Pub"
    d = pd.Timestamp("2025-02-18")                                            # coverage hole on a trading day
    hole = pd.to_datetime(df["published_utc"], utc=True, errors="coerce", format="ISO8601").dt.tz_convert("America/New_York").dt.tz_localize(None).dt.normalize() == d
    df = df[~hole]
    gaps, st = check_news(df.drop(columns=["vendor_receipt_ts", "system_receipt_ts"]), "n", pd.Timestamp("2025-04-01", tz="UTC"), CAL)
    ks = kinds(gaps)
    for k in ("MISSING_OR_UNPARSEABLE_TIMESTAMP", "TIMEZONE_MISSING", "PUBLISHED_AFTER_RETRIEVAL", "NEWS_COVERAGE_GAP",
              "NO_VENDOR_RECEIPT_TS", "NO_SYSTEM_RECEIPT_TS", "SYNDICATED_ARTICLES"):
        assert k in ks, (k, ks)
    assert [g for g in gaps if g.kind == "MISSING_OR_UNPARSEABLE_TIMESTAMP"][0].n == 2
    assert st["syndicated_titles_multi_publisher"] == 1


# ------------------------------------------------------------------ corporate actions
def test_corporate_action_gap_detection():
    df = clean_daily(tickers=("AAA", "BBB", "CCC", "DDD"))
    def split(tk, date, ratio):
        m = (df["ticker"] == tk) & (df["date"] >= date)
        df.loc[m, ["open", "high", "low", "close"]] = df.loc[m, ["open", "high", "low", "close"]] / ratio
    split("AAA", pd.Timestamp("2024-12-10"), 10)      # recorded 10:1, visible in unadjusted prices  -> confirmed
    split("CCC", pd.Timestamp("2025-01-15"), 4)       # 4:1 with NO record                            -> unrecorded
    # BBB: split recorded 2:1 but prices are already adjusted (no discontinuity)                      -> flagged
    m = (df["ticker"] == "DDD") & (df["date"] == "2025-02-05"); df.loc[m, ["open", "high", "low", "close"]] *= 0.55   # 45% gap, no action
    splits = pd.DataFrame({"ticker": ["AAA", "BBB"], "execution_date": ["2024-12-10", "2025-02-03"], "split_from": [1, 1], "split_to": [10, 2]})
    ref = pd.DataFrame({"ticker": ["DDD"], "delist_date": [pd.Timestamp("2025-03-20")]})
    gaps, st = check_corporate_actions(df, splits, "d", ref=ref)
    ks = kinds(gaps)
    assert st["splits_confirmed_in_prices"] == 1 and st["splits_without_discontinuity"] == 1
    assert "SPLIT_WITHOUT_DISCONTINUITY" in ks and "UNRECORDED_SPLIT_LIKE_DISCONTINUITY" in ks
    assert "DELISTING_RETURN_UNKNOWN" in ks
    assert any(g.ticker == "CCC" and g.kind == "UNRECORDED_SPLIT_LIKE_DISCONTINUITY" for g in gaps)
    assert not any(g.ticker == "AAA" for g in gaps)          # the recorded, confirmed split is silent


# ------------------------------------------------------------------ engine never treats unknown as zero
def test_unknown_delisting_return_is_a_data_gap_not_zero():
    p = make_market(T=120, N=15, seed=5, delist_frac=0.3)
    p.delist_ret = None                                       # terminal returns unknown
    W = np.full((120, 15), 0.02)
    with pytest.raises(DataGapError):
        run_backtest(p, W, Exec())
    p.excluded = np.zeros((120, 15), bool)                    # documented exclusion of the delisted names -> explicit
    for i in range(15):
        if not p.alive[-1, i]:
            p.excluded[:, i] = True
    run_backtest(p, W, Exec())


# ------------------------------------------------------------------ ledger and gate
def test_discovery_gate_blocks_until_resolved_or_excluded(reg):
    ledger = GapLedger(reg)
    df = clean_daily(); df = df[df["date"] != "2024-12-12"]
    gaps, st = check_daily_sessions(df, CAL, "d")
    ledger.add(gaps)
    rep = IntegrityReport(checks_run=list(IntegrityReport.REQUIRED_CHECKS), coverage={"daily": {"complete": True}})
    req = ExperimentRequirements("exp1", ["US_EQUITY"], ["daily"], ("2024-10-01", "2025-03-31"), "test")
    ok, why = DiscoveryGate.check(rep, req, ledger)
    assert not ok and any("MISSING_SESSION_MARKETWIDE" in w for w in why)
    gid = next(iter(ledger.gaps))
    with pytest.raises(ValueError):
        ledger.exclude(gid, [], "because")                       # exclusions must name experiments
    ledger.exclude(gid, ["exp1"], "provider outage; session excluded from exp1")
    ok, why = DiscoveryGate.check(rep, req, ledger)
    assert ok, why
    assert not DiscoveryGate.check(rep, ExperimentRequirements("exp2", ["US_EQUITY"], ["daily"], ("a", "b"), ""), ledger)[0]  # not excluded for exp2
    assert reg.verify_chain() and len(reg.events("DATA_GAP")) >= 2


def test_gate_blocks_on_incomplete_coverage_and_missing_checks(reg):
    ledger = GapLedger(reg)
    rep = IntegrityReport(checks_run=["calendar"], coverage={"daily": {"complete": False, "note": "sample only"}})
    req = ExperimentRequirements("e", ["US_EQUITY"], ["daily", "news"], ("2024-10-01", "2025-03-31"), "")
    ok, why = DiscoveryGate.check(rep, req, ledger)
    assert not ok and any("news" in w for w in why) and any("sample only" in w for w in why) and any("minute_bars" in w for w in why)
