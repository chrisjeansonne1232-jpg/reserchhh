"""Alpaca/Massive clients (offline, mocked transport) and the rename / delisted / cross-provider / tick integrity checks."""
import io
import json
import urllib.error

import numpy as np
import pandas as pd
import pytest

from edgelab import providers
from edgelab.alpaca import AlpacaData
from edgelab.integrity import (AMBIGUOUS, MATERIAL, MINOR, MarketCalendar, check_cross_provider_daily, check_daily_ohlc, check_zero_volume_bars, check_cross_provider_splits, aggregate_gaps, Gap, GapLedger, check_delisted_coverage,
                               check_rename_feed, check_ticker_renames, check_ticks)
from edgelab.providers import MissingCredentials, ProviderError, RecentDataRefused, redact

CAL = MarketCalendar("US_EQUITY")
KEY, SECRET = "PKTESTKEY1234567890", "sEcReTsEcReT0987654321"


@pytest.fixture
def creds(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY_ID", KEY)
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", SECRET)
    monkeypatch.setenv("MASSIVE_API_KEY", "MASSIVEKEY000111222")


def kinds(gaps, sev=None):
    return sorted(g.kind for g in gaps if sev is None or g.severity == sev)


# ------------------------------------------------------------------ credentials & embargo
def test_missing_credentials_refused(monkeypatch):
    monkeypatch.delenv("ALPACA_API_KEY_ID", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET_KEY", raising=False)
    with pytest.raises(MissingCredentials) as e:
        AlpacaData()
    assert "ALPACA_API_KEY_ID" in str(e.value)          # names the variable, never a value


def test_recent_sip_window_is_refused_not_clipped(creds):
    a = AlpacaData(now="2026-09-30T12:00:00Z")
    with pytest.raises(RecentDataRefused):
        a.bars(["AAPL"], "1Min", "2026-09-30T11:00:00Z", "2026-09-30T11:50:00Z")       # ends 10 min ago
    with pytest.raises(RecentDataRefused):
        a.bars(["AAPL"], "1Day", "2026-09-01", "2026-09-30T12:00:00Z")
    with pytest.raises(ProviderError):
        a.bars(["AAPL"], "1Day", "2015-06-01", "2016-01-10")                             # before supported history


def test_embargo_boundary(creds, monkeypatch):
    a = AlpacaData(now="2026-09-30T12:00:00Z")
    monkeypatch.setattr(a.http, "get_json", lambda *a_, **k: {"bars": {}})
    a.bars(["AAPL"], "1Min", "2026-09-30T11:00:00Z", "2026-09-30T11:44:00Z")             # 16 min old: allowed
    with pytest.raises(RecentDataRefused):
        a.bars(["AAPL"], "1Min", "2026-09-30T11:00:00Z", "2026-09-30T11:45:00Z")         # 15 min old: refused


def test_pagination_merges_pages_and_always_requests_raw_sip(creds, monkeypatch):
    a = AlpacaData(now="2026-09-30T12:00:00Z")
    seen = []
    pages = [{"bars": {"AAA": [{"t": "2020-01-02T05:00:00Z", "o": 1, "h": 2, "l": 1, "c": 2, "v": 10, "vw": 1.5, "n": 3}]}, "next_page_token": "x"},
             {"bars": {"AAA": [{"t": "2020-01-03T05:00:00Z", "o": 2, "h": 3, "l": 2, "c": 3, "v": 11, "vw": 2.5, "n": 4}],
                       "BBB": [{"t": "2020-01-03T05:00:00Z", "o": 9, "h": 9, "l": 9, "c": 9, "v": 1, "vw": 9, "n": 1}]}, "next_page_token": None}]

    def fake(path, params):
        seen.append(params)
        return pages[len(seen) - 1]
    monkeypatch.setattr(a.http, "get_json", fake)
    df = a.bars(["AAA", "BBB"], "1Day", "2020-01-01", "2020-02-01")
    assert len(df) == 3 and set(df["symbol"]) == {"AAA", "BBB"}
    assert all(p["feed"] == "sip" and p["adjustment"] == "raw" for p in seen) and seen[1]["page_token"] == "x"


# ------------------------------------------------------------------ keys never leak
def test_error_messages_never_contain_keys(creds, monkeypatch):
    a = AlpacaData()

    def boom(req, timeout=0):
        raise urllib.error.HTTPError(req.full_url, 401, "unauthorized", {}, io.BytesIO(f'{{"message":"bad key {KEY} secret {SECRET}"}}'.encode()))
    monkeypatch.setattr("urllib.request.urlopen", boom)
    with pytest.raises(ProviderError) as e:
        a.http.get_json("/v2/stocks/bars", {"symbols": "AAPL"})
    msg = str(e.value)
    assert KEY not in msg and SECRET not in msg and "401" in msg


def test_redact_scrubs_secrets_and_key_shaped_params():
    assert KEY not in redact(f"url?apiKey={KEY}&x=1 and {KEY}", [KEY])
    assert "abc123" not in redact("Authorization: Bearer abc123", [])
    assert "apiKey=abc123" not in redact("https://h/p?apiKey=abc123&limit=1", [])


# ------------------------------------------------------------------ ticker renames
NC = pd.DataFrame([
    {"old_symbol": "FB", "new_symbol": "META", "process_date": "2022-06-09", "old_cusip": "30303M102", "new_cusip": "30303M102"},
    {"old_symbol": "META", "new_symbol": "METV", "process_date": "2022-01-31", "old_cusip": "53656F417", "new_cusip": "53656F417"},
    {"old_symbol": "OLDCO", "new_symbol": "NEWCO", "process_date": "2021-03-01", "old_cusip": "111", "new_cusip": "111"},
])


def obs(rows):
    return pd.DataFrame(rows, columns=["symbol", "first_date", "last_date"])


def test_backmapped_rename_and_reuse_are_flagged():
    gaps, st = check_ticker_renames(NC, obs([("META", "2016-01-04", "2026-09-29"), ("METV", "2022-01-31", "2026-09-29"),
                                             ("NEWCO", "2021-03-01", "2026-09-29"), ("OLDCO", "2016-01-04", "2021-02-26")]), "d")
    by = {k: [g for g in gaps if g.kind == k] for k in kinds(gaps)}
    assert [g.ticker for g in by["RENAME_HISTORY_BACKMAPPED"]] == ["META"]                    # FB history served as META; FB dark
    assert "returns no bars at all" in by["RENAME_HISTORY_BACKMAPPED"][0].detail
    assert [g.ticker for g in by["SYMBOL_REUSED_ACROSS_ISSUERS"]] == ["META"] and by["SYMBOL_REUSED_ACROSS_ISSUERS"][0].severity == MATERIAL
    assert st["backmapped"] == 1 and st["reused_symbols"] == 1


def test_clean_rename_has_no_gap():
    nc = NC[NC["new_symbol"] == "NEWCO"]
    gaps, st = check_ticker_renames(nc, obs([("NEWCO", "2021-03-01", "2026-09-29"), ("OLDCO", "2016-01-04", "2021-02-26")]), "d")
    assert gaps == [] and st["renames_with_bars_checked"] == 1


def test_rename_price_discontinuity_flagged():
    nc = NC[NC["new_symbol"] == "NEWCO"]
    daily = pd.DataFrame({"ticker": "NEWCO", "date": pd.to_datetime(["2021-02-26", "2021-03-01", "2021-03-02"]),
                          "open": [100, 20, 20.5], "close": [100, 20.2, 20.4]})
    gaps, _ = check_ticker_renames(nc, obs([("NEWCO", "2021-02-26", "2026-09-29")]), "d", daily=daily)
    assert "RENAME_WITH_PRICE_DISCONTINUITY" in kinds(gaps, MATERIAL)


def test_reuse_without_cusips_is_ambiguous_not_silent():
    nc = NC.drop(columns=["old_cusip", "new_cusip"]).iloc[:2]
    gaps, _ = check_ticker_renames(nc, obs([]), "d")
    assert kinds(gaps) == ["SYMBOL_REUSED_ACROSS_ISSUERS"] and gaps[0].severity == AMBIGUOUS


# ------------------------------------------------------------------ delisted coverage
def master(n_active=50, n_delisted=100):
    rows = [(f"A{i}", True, None) for i in range(n_active)]
    rows += [(f"D{i}", False, f"{2017 + i % 8}-06-15T00:00:00Z") for i in range(n_delisted)]
    rows += [("OLDDEL", False, "2012-01-03T00:00:00Z"), ("UNDATED", False, None)]
    return pd.DataFrame(rows, columns=["ticker", "active", "delisted_utc"])


def observed_all(m, drop=(), truncate=()):
    rows = []
    for _, r in m.iterrows():
        if r["ticker"] in drop or r["ticker"] in ("OLDDEL", "UNDATED"):
            continue
        last = pd.Timestamp(r["delisted_utc"]).tz_localize(None).normalize() if pd.notna(r["delisted_utc"]) else pd.Timestamp("2026-09-29")
        if r["ticker"] in truncate:
            last -= pd.Timedelta(days=90)
        rows.append((r["ticker"], "2016-01-04", str(last.date()), 500))
    return pd.DataFrame(rows, columns=["symbol", "first_date", "last_date", "n_bars"])


def test_full_delisted_coverage_is_clean_and_old_delistings_out_of_window_ignored():
    m = master()
    gaps, st = check_delisted_coverage(m, observed_all(m), ("2016-01-01", "2026-09-30"), "d", cal=CAL)
    assert [g for g in gaps if g.severity == MATERIAL] == []
    assert st["delisted_in_window"] == 100 and st["delisted_missing"] == 0 and st["inactive_without_delist_date"] == 1
    assert "INACTIVE_WITHOUT_DELIST_DATE" in kinds(gaps)


def test_survivorship_bias_flagged_above_threshold_with_full_list_kept():
    m = master()
    drop = {f"D{i}" for i in range(0, 100, 4)}                                     # 25% of delisted names have no bars
    gaps, st = check_delisted_coverage(m, observed_all(m, drop=drop), ("2016-01-01", "2026-09-30"), "d", cal=CAL)
    g = [g for g in gaps if g.kind == "DELISTED_NAMES_NO_BARS"][0]
    assert g.severity == MATERIAL and g.n == 25 and set(st["missing_names"]) == drop        # nothing dropped silently
    assert sum(v["delisted"] - v["with_bars"] for v in st["delisted_coverage_by_delist_year"].values()) == 25


def test_missing_within_tolerance_is_minor():
    m = master(n_delisted=200)
    gaps, _ = check_delisted_coverage(m, observed_all(m, drop={"D0", "D1"}), ("2016-01-01", "2026-09-30"), "d", cal=CAL)      # 1% < 2%
    assert [(g.kind, g.severity) for g in gaps if g.kind == "DELISTED_NAMES_NO_BARS"] == [("DELISTED_NAMES_NO_BARS", MINOR)]


def test_tail_truncation_detected():
    m = master()
    gaps, st = check_delisted_coverage(m, observed_all(m, truncate={f"D{i}" for i in range(20)}), ("2016-01-01", "2026-09-30"), "d", cal=CAL)
    assert st["delisted_tail_truncated"] == 20 and "DELISTED_TAIL_TRUNCATED" in kinds(gaps, MATERIAL)


def test_active_names_without_bars_flagged():
    m = master()
    gaps, st = check_delisted_coverage(m, observed_all(m, drop={f"A{i}" for i in range(10)}), ("2016-01-01", "2026-09-30"), "d", cal=CAL)
    assert st["active_missing"] == 10 and "ACTIVE_NAMES_NO_BARS" in kinds(gaps, MATERIAL)


# ------------------------------------------------------------------ cross-provider
def daily_frame(n=60, seed=1):
    rng = np.random.default_rng(seed)
    d = CAL.sessions("2025-01-02", "2025-06-30")[:n]
    rows = []
    for tk in ("AAA", "BBB"):
        px = 50.0
        for x in d:
            o = px * (1 + rng.normal(0, .005)); c = o * (1 + rng.normal(0, .01))
            rows.append((tk, x, o, max(o, c) * 1.003, min(o, c) * .997, c, 1e6)); px = c
    return pd.DataFrame(rows, columns=["ticker", "date", "open", "high", "low", "close", "volume"])


def test_identical_providers_are_clean():
    a = daily_frame()
    gaps, st = check_cross_provider_daily(a, a.copy(), "d")
    assert gaps == [] and st["close_mismatch_frac"] == 0 and st["rows_both"] == 120


def test_seeded_cross_provider_defects():
    a, b = daily_frame(), daily_frame()
    b.loc[b.index[:5], "close"] *= 1.05                                            # 5 wrong closes
    b = b.drop(b.index[100:103])                                                   # 3 bars missing in the reference
    gaps, st = check_cross_provider_daily(a, b, "d")
    assert st["only_primary"] == 3 and st["close_mismatch_frac"] == pytest.approx(5 / 117, abs=1e-4)
    assert {"PRICE_MISMATCH_BETWEEN_PROVIDERS", "BAR_PRESENT_IN_ONE_PROVIDER_ONLY"} <= set(kinds(gaps))


# ------------------------------------------------------------------ ticks
def test_crossed_quotes_and_bad_trades_flagged():
    t0 = pd.Timestamp("2025-07-03 14:30", tz="UTC")
    q = pd.DataFrame({"t": [t0 + pd.Timedelta(milliseconds=i) for i in range(6)], "bid": [10, 10, 10.05, 10, 0, 10], "ask": [10.01, 10.02, 10.0, 10.01, 10.01, 10.01],
                      "bid_size": 1, "ask_size": 1})
    tr = pd.DataFrame({"t": [t0, t0 + pd.Timedelta(seconds=1), t0], "price": [10, -1, 10], "size": [100, 100, 100], "trade_id": [1, 2, 3]})
    gaps, st = check_ticks(tr, q, "d", "AAA", "2025-07-03")
    assert st["quotes_crossed"] == 1 and st["quotes_one_sided_or_zero"] == 1 and st["trades_nonpositive_price_or_size"] == 1 and st["trades_out_of_order"] == 1
    assert {"CROSSED_QUOTES", "NONPOSITIVE_TRADE", "TRADES_OUT_OF_ORDER"} <= set(kinds(gaps))
    assert check_ticks(None, None, "d", "AAA", "2025-07-03") == ([], {})


# ------------------------------------------------------------------ rename feed quality
def feed(counts):
    rows = []
    for y, n in counts.items():
        rows += [{"old_symbol": f"O{y}{i}", "new_symbol": f"N{y}{i}", "process_date": f"{y}-{1 + i % 12:02d}-15"} for i in range(n)]
    return pd.DataFrame(rows)


def test_sparse_early_years_of_rename_feed_are_flagged():
    counts = {2016: 0, 2017: 2, 2018: 2, 2019: 53, 2020: 304, 2021: 576, 2022: 399, 2023: 500, 2024: 700, 2025: 670, 2026: 461}
    gaps, st = check_rename_feed(feed(counts), ("2016-01-01", "2026-09-30"), "d")
    g = [g for g in gaps if g.kind == "RENAME_FEED_SPARSE"][0]
    assert g.severity == MATERIAL and st["sparse_years"] == [2016, 2017, 2018, 2019] and g.start == "2016-01-01" and g.end == "2019-12-31"


def test_dense_feed_with_partial_final_year_is_clean_and_noops_counted():
    counts = {y: 400 for y in range(2016, 2027)}
    counts[2026] = 300                                                                    # ~74% of the year elapsed: partial year must not be flagged
    df = feed(counts)
    df.loc[0, "new_symbol"] = df.loc[0, "old_symbol"]
    gaps, st = check_rename_feed(df, ("2016-01-01", "2026-09-30"), "d")
    assert st["sparse_years"] == [] and kinds(gaps) == ["NOOP_RENAME_EVENTS"] and st["noop_renames"] == 1


def test_cusip_in_symbol_field_flagged():
    df = feed({2020: 100, 2021: 100}).assign(process_date="2021-05-05")
    df.loc[0, "new_symbol"] = "22112H119"
    gaps, st = check_rename_feed(df, ("2020-01-01", "2021-12-31"), "d")
    assert st["cusip_as_symbol"] == 1 and "CUSIP_IN_SYMBOL_FIELD" in kinds(gaps)


# ------------------------------------------------------------------ registry: fresh checkout continues the SAME chain
def test_registry_restores_chain_from_committed_mirror(tmp_path):
    from edgelab.registry import Registry, RegistryError
    r = Registry(tmp_path / "r.sqlite")
    r.append("NOTE", {"a": 1}); r.append("NOTE", {"b": 2.5})
    (tmp_path / "r.sqlite").unlink()                                   # sqlite is git-ignored; only the JSONL travels
    r2 = Registry(tmp_path / "r.sqlite")
    assert len(r2.events()) == 2 and r2.verify_chain()
    ev = r2.append("NOTE", {"c": 3})
    assert ev["prev_hash"] == r.events()[-1]["hash"] and ev["seq"] == 3 and r2.verify_chain()
    assert len((tmp_path / "r.jsonl").read_text().splitlines()) == 3   # one chain, no duplicate genesis


def test_registry_refuses_tampered_mirror(tmp_path):
    from edgelab.registry import Registry, RegistryError
    r = Registry(tmp_path / "r.sqlite"); r.append("NOTE", {"a": 1})
    (tmp_path / "r.sqlite").unlink()
    j = tmp_path / "r.jsonl"; j.write_text(j.read_text().replace('"a":1', '"a":2'))
    with pytest.raises(RegistryError):
        Registry(tmp_path / "r.sqlite")


# ------------------------------------------------------------------ ledger persistence / aggregation
def test_ledger_replays_from_registry_and_is_idempotent(tmp_path):
    from edgelab.registry import Registry
    r = Registry(tmp_path / "r.sqlite")
    L = GapLedger(r)
    g = Gap("d", "coverage", "X", MATERIAL, "detail")
    L.add([g]); L.resolve(g.gap_id, "fixed by Y")
    n = len(r.events("DATA_GAP"))
    L2 = GapLedger(r)                                                         # a later run
    L2.add([Gap("d", "coverage", "X", MATERIAL, "detail")]); L2.resolve(g.gap_id, "fixed by Y")
    assert len(r.events("DATA_GAP")) == n and L2.gaps[g.gap_id].status == "RESOLVED" and L2.unresolved_material() == []


def test_aggregate_gaps_keeps_full_detail_and_counts():
    gs = [Gap("d", "sessions", "MISSING_SESSION_LIQUID", MATERIAL, f"t{i}: gap", ticker=f"T{i}", start="2020-01-02", end="2020-01-03", n=2) for i in range(50)]
    gs += [Gap("d", "sessions", "NO_TRADE_OR_MISSING", AMBIGUOUS, "x", ticker="Z", n=1)]
    agg, detail = aggregate_gaps(gs, "d")
    assert len(agg) == 2 and len(detail) == 51
    m = [g for g in agg if g.severity == MATERIAL][0]
    assert m.n == 100 and "50 occurrence(s)" in m.detail and "50 distinct ticker(s)" in m.detail


# ------------------------------------------------------------------ OHLC & split-table agreement
def test_ohlc_validity_seeded():
    d = daily_frame(10)
    assert check_daily_ohlc(d, "d")[0] == []
    d = d.copy(); d.loc[d.index[0], "high"] = d.loc[d.index[0], "low"] - 1; d.loc[d.index[1], "close"] = -3; d.loc[d.index[2], "volume"] = -1
    gaps, st = check_daily_ohlc(d, "d")
    assert {"HIGH_BELOW_LOW", "NONPOSITIVE_OR_NULL_PRICE", "NEGATIVE_VOLUME"} <= set(kinds(gaps)) and st["negative_volume"] == 1


def test_split_tables_agree_and_disagree():
    a = pd.DataFrame({"ticker": ["A", "B", "C"], "execution_date": ["2020-05-01", "2021-06-01", "2027-01-01"], "split_from": [1, 1, 1], "split_to": [2, 4, 2]})
    b = pd.DataFrame({"ticker": ["A", "B", "D"], "execution_date": ["2020-05-02", "2021-06-01", "2022-01-01"], "split_from": [1, 1, 1], "split_to": [2, 5, 3]})
    gaps, st = check_cross_provider_splits(a, b, "d", ("2016-01-01", "2026-09-30"), "massive", "alpaca")
    assert st["agree"] == 1 and st["only_in_massive"] == 1 and st["only_in_alpaca"] == 2       # C is future-dated: out of window, not compared
    assert kinds(gaps) == ["SPLIT_TABLES_DISAGREE"]


def test_mixed_timestamp_precision_is_parsed_per_element(creds, monkeypatch):
    a = AlpacaData(now="2026-09-30T12:00:00Z")
    rows = [{"t": "2016-11-25T14:30:04Z", "x": "P", "p": 1.0, "s": 1, "c": [], "i": 1, "z": "C"},
            {"t": "2016-11-25T14:30:04.002Z", "x": "P", "p": 1.0, "s": 1, "c": [], "i": 2, "z": "C"}]
    monkeypatch.setattr(a.http, "get_json", lambda *a_, **k: {"trades": {"AAA": rows}, "next_page_token": None})
    df = a.trades("AAA", "2016-11-25T14:30:00Z", "2016-11-25T14:31:00Z")
    assert df["t"].notna().all() and df["t"].iloc[1] - df["t"].iloc[0] == pd.Timedelta(milliseconds=2)


def test_tick_check_reports_measured_venue_mix_not_an_assumption():
    t0 = pd.Timestamp("2025-07-03 14:30", tz="UTC")
    q = pd.DataFrame({"t": [t0 + pd.Timedelta(milliseconds=i) for i in range(4)], "bid": [10, 10.05, 10, 10], "ask": [10.01, 10.0, 10.01, 10.02],
                      "bid_exchange": ["K", "K", "P", "Q"], "ask_exchange": ["P", "P", "P", "Q"], "bid_size": 1, "ask_size": 1})
    gaps, st = check_ticks(None, q, "d", "AAA", "2025-07-03")
    assert st["quotes_bid_ask_venue_differ_frac"] == 0.5 and st["quotes_crossed"] == 1 and st["distinct_bid_venues"] == 3
    assert "cannot prove it is the official NBBO" in gaps[0].detail and "per-exchange quote stream, not an NBBO" not in gaps[0].detail


def test_zero_volume_placeholders_detected_for_illiquid_names_too():
    d = daily_frame(20)
    d.loc[d["ticker"] == "BBB", "volume"] = 300                                             # illiquid: check_stale_daily would skip this ticker
    idx = d[d["ticker"] == "BBB"].index[5:8]
    prev = d.loc[idx[0] - 1, "close"]
    d.loc[idx, ["open", "high", "low", "close"]] = prev
    d.loc[idx, "volume"] = 0
    gaps, st = check_zero_volume_bars(d, "d")
    assert st["zero_volume_bars"] == 3 and st["zero_volume_equal_previous_close"] == 3 and st["tickers_affected"] == 1   # a chain of carry-forwards: each equals the bar before it
    assert kinds(gaps, MATERIAL) == ["ZERO_VOLUME_PLACEHOLDER_BARS"]
    assert check_zero_volume_bars(daily_frame(20), "d")[0] == []


def test_rename_with_prior_history_on_both_symbols_is_ambiguous_not_backmapped():
    nc = NC[NC["new_symbol"] == "NEWCO"]
    gaps, st = check_ticker_renames(nc, obs([("NEWCO", "2019-01-02", "2026-09-29"), ("OLDCO", "2016-01-04", "2021-02-26")]), "d")
    assert kinds(gaps) == ["RENAME_TARGET_SYMBOL_HAS_PRIOR_HISTORY"] and gaps[0].severity == AMBIGUOUS and st["backmapped"] == 0


def test_long_placeholder_runs_reveal_dead_period_between_issuers():
    d = daily_frame(80)
    idx = d[d["ticker"] == "AAA"].index[10:75]                       # 65 consecutive sessions bridged by placeholders (ticker re-use)
    d.loc[idx, ["open", "high", "low", "close"]] = d.loc[idx[0] - 1, "close"]
    d.loc[idx, "volume"] = 0
    gaps, st = check_zero_volume_bars(d, "d")
    r = st["placeholder_runs_ge_min_run"]
    assert r["runs"] == 1 and r["tickers"] == 1 and "AAA" in r["examples"][0] and "(65 sessions)" in r["examples"][0]
    assert "derive alive from volume > 0" in gaps[0].detail
