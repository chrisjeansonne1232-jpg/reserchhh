"""Builds docs/DATA_INTEGRITY_REPORT.md.

Price source: Alpaca free Market Data API (SIP, historical-only) -- primary. Massive free tier: splits, reference tickers, cross-validation.
Everything found is recorded in the immutable registry via the GapLedger. Nothing is dropped, filled, re-mapped or substituted, and the
discovery-gate requirements (ExperimentRequirements, REQUIRED_CHECKS, severity semantics) are UNCHANGED from the previous audit.

AUDIT_DRY_RUN=1 : work on a temporary copy of the registry and write the report to the scratchpad (nothing committed is touched).
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from edgelab.integrity import (AMBIGUOUS, MATERIAL, MINOR, EXPECTED, DiscoveryGate, ExperimentRequirements, Gap, GapLedger, IntegrityReport, MarketCalendar,
                               aggregate_gaps, check_corporate_actions, check_cross_provider_daily, check_cross_provider_splits, check_daily_ohlc,
                               check_daily_sessions, check_delisted_coverage, check_duplicates, check_news, check_rename_feed, check_stale_daily,
                               check_ticker_renames)
from edgelab.registry import Registry

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
AUDIT = ROOT / "data" / "audit"
DRY = bool(os.environ.get("AUDIT_DRY_RUN"))
if DRY:
    tmp = Path(tempfile.mkdtemp())
    shutil.copy(ROOT / "registry" / "registry.jsonl", tmp / "registry.jsonl")
    reg, OUT_MD, AUDIT = Registry(tmp / "registry.sqlite"), tmp / "DATA_INTEGRITY_REPORT.md", tmp / "audit"
else:
    reg, OUT_MD = Registry(ROOT / "registry" / "registry.sqlite"), ROOT / "docs" / "DATA_INTEGRITY_REPORT.md"
AUDIT.mkdir(parents=True, exist_ok=True)
ledger = GapLedger(reg)
cal = MarketCalendar("US_EQUITY")
rep = IntegrityReport()
now = pd.Timestamp.now(tz="UTC")
extra_md: list[str] = []          # additional report sections


def by_kind(kind: str) -> Gap:
    return next(g for g in ledger.gaps.values() if g.kind == kind)


# ============================================================================ A. previous Massive-connector samples (unchanged historical facts)
DS_D = "massive_daily_unadjusted_sample_2025-06-02_2025-07-11"
raw = pd.read_csv(ROOT / "data/samples/massive_daily_unadjusted_sample.csv")
ts = pd.to_datetime(raw["t"], unit="ms", utc=True)
raw["date"] = ts.dt.tz_convert("America/New_York").dt.tz_localize(None).dt.normalize()
daily_s = raw.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})[["ticker", "date", "open", "high", "low", "close", "volume"]]
splits_s = pd.DataFrame({"ticker": ["ORLY"], "execution_date": ["2025-06-10"], "split_from": [1.0], "split_to": [15.0]})
g, st_sessions = check_daily_sessions(daily_s, cal, DS_D); ledger.add(g)
ledger.add(check_duplicates(daily_s, ["ticker", "date"], DS_D)); ledger.add(check_stale_daily(daily_s, DS_D))
g, st_ca = check_corporate_actions(daily_s, splits_s, DS_D); ledger.add(g)
rep.checks_run += ["calendar", "sessions", "duplicates", "stale", "corporate_actions"]
rep.stats["massive_daily_sample_2025-06..07"] = {**st_sessions, "corporate_actions": st_ca,
                                                 "provider_timestamp_convention": "midnight America/New_York on the session date (verified: 56/56 bars)",
                                                 "adjusted_flag_verified": "adjusted=false returns UNADJUSTED prices: the ORLY 15:1 split is visible (1348.10 close -> 90.00 open)"}

DS_M = "massive_minute_AAPL_2025-07-03_halfday"
rep.checks_run += ["minute_bars", "timestamp_gaps"]
rep.stats["massive_minute_sample_provider_side_sql"] = {
    "ticker/session": "AAPL 2025-07-03 (early close 13:00 ET)", "bars": 499, "regular_expected": 210, "regular_observed": 210, "duplicate_timestamps": 0,
    "off_grid_timestamps": 0, "inconsistent_ohlc": 0, "zero_volume_bars": 0, "gaps_in_regular_session": 0, "max_gap_regular_min": 1.0, "premarket_bars": 250,
    "premarket_possible": 330, "after_hours_bars": 39, "max_gap_all_min": 180.0,
    "method": "SQL executed inside the provider workspace on the stored response (same definitions as edgelab.integrity.check_minute_bars)"}
ledger.add([Gap(DS_M, "minute_bars", "EXTENDED_HOURS_SPARSE", AMBIGUOUS,
                "AAPL premarket has 250/330 minute bars and after-hours gaps up to 180 min: aggregates are omitted for minutes with no trades, so "
                "'no trade' cannot be distinguished from 'missing'. Extended-hours prices are therefore NOT reliable fill proxies.", ticker="AAPL",
                start="2025-07-03", end="2025-07-03", n=80)])

DS_N = "massive_news_AAPL_2025-07-03"
news = pd.DataFrame({
    "id": ["80534833", "6cb51546", "c825161a", "2225d1fc", "dc265559", "16e431d9"],
    "published_utc": ["2025-07-03T08:41:00Z", "2025-07-03T09:30:00Z", "2025-07-03T12:33:00Z", "2025-07-03T13:32:00Z", "2025-07-03T13:33:00Z", "2025-07-03T23:41:00Z"],
    "title": ["Can US Equities Extend Record Run as Broader Market Joins the Rally?", "This Is the Best Vanguard ETF to Buy Right Now, and It's Not Even Close",
              "Nike is Back in the Race", "Top S&P 500 Stocks to Watch as Golden Cross Signals More Upside",
              "S&P 500: Jobs Data, Tariff Risks Put Bullish Conviction to the Test", "Shareholder Alert: Robbins LLP Informs Investors of the Apple case"],
    "publisher_name": ["Investing.com", "The Motley Fool", "The Motley Fool", "Investing.com", "Investing.com", "GlobeNewswire Inc."],
    "tickers": ['["AAPL","AMZN"]', '["VGT","AAPL","MSFT","NVDA","PLTR","AMD"]', '["AAPL"]', '["AAPL","AMZN"]', '["AAPL","AMZN"]', '["AAPL"]']})
g, st_news = check_news(news, DS_N, now, cal); ledger.add(g)
rep.checks_run += ["news_timestamps"]
rep.stats["massive_news_sample"] = st_news

ENT = "massive_entitlements"
ledger.add([
    Gap(ENT, "coverage", "PRICE_HISTORY_LIMITED_TO_~2Y", MATERIAL, "Daily/minute bars are entitled only from ~late 2024 (2024-12 OK, 2024-09 NOT_ENTITLED, 2010/2000/2022 NOT_ENTITLED). "
        "History is ~2 years: covers one market regime; leaves little room for a locked OOS after training/validation."),
    Gap(ENT, "coverage", "NO_HISTORICAL_QUOTES_NBBO", MATERIAL, "/v3/quotes and NBBO ticks are NOT_ENTITLED: no observed bid/ask/spread/depth. Spreads and opening-auction "
        "fills must be ASSUMED; the overnight/premarket-news track cannot validate execution realism."),
    Gap(ENT, "coverage", "NO_POINT_IN_TIME_FUNDAMENTALS", MATERIAL, "/vX/reference/financials returns HTTP 410 (deprecated); replacement income-statement endpoints are NOT_ENTITLED. "
        "Fundamentals must come from SEC EDGAR (acceptance timestamps), which is a different provider and must be declared, not substituted silently."),
    Gap(ENT, "coverage", "BENZINGA_NEWS_NOT_ENTITLED", MINOR, "Partner news feed with richer timestamps (/benzinga/v2/news) is NOT_ENTITLED; only /v2/reference/news is available."),
    Gap(ENT, "news_independence", "NEWS_HAS_NO_RECEIPT_TIMESTAMPS", MATERIAL, "Only publisher-side published_utc (minute resolution). No vendor/system receipt time, no revision history; 5 "
        "distinct publishers seen on one ticker/day. Latency assumptions are unavoidable and must be stress-tested."),
    Gap(ENT, "corporate_actions", "SPLITS_TABLE_INCLUDES_FUTURE_ACTIONS", MINOR, "/stocks/v1/splits returns actions dated after today (e.g. 2026-12-17): the table is not point-in-time as returned; "
        "always filter by an as-of date."),
    Gap(ENT, "corporate_actions", "SPLIT_TYPED_AS_STOCK_DIVIDEND", MINOR, "ORLY 15:1 (2025-06-10) is typed 'stock_dividend' not 'forward_split': action-type filters can miss real splits."),
    Gap(ENT, "access", "NO_BULK_EXPORT_PATH", MATERIAL, "No Massive API key exists in the execution environment; data is reachable only through the MCP connector (one bounded request at a time, "
        "rate-limited) and cannot be bulk-exported into local storage. The research dataset cannot be materialised for local backtesting."),
])

# ============================================================================ B. NEW: provenance of what is on disk
prov_d = json.loads((ROOT / "data/samples/alpaca_daily_universe.provenance.json").read_text())
prov_m = json.loads((ROOT / "data/samples/massive_security_master_CS.provenance.json").read_text())
START, END = prov_d["window"]
LAST = pd.Timestamp(END) - pd.Timedelta(days=1)
DS_A = f"alpaca_sip_daily_raw_{START}_{END}_{prov_d['parts_sha256'][:8]}"
DS_MASTER = f"massive_security_master_CS_{prov_m['sha256_of_sorted_ticker_active_delisted'][:8]}"

cols = ["symbol", "session", "open", "high", "low", "close", "volume", "trades", "vwap"]
daily = pd.concat([pd.read_parquet(p, columns=cols) for p in sorted((RAW / "alpaca_daily").glob("part-*.parquet"))], ignore_index=True)
daily = daily.rename(columns={"symbol": "ticker", "session": "date"})
requested = pd.read_parquet(RAW / "alpaca_daily" / "_requested.parquet")["symbol"]
master = pd.read_parquet(RAW / "massive_security_master_CS.parquet")
observed = daily.groupby("ticker").agg(first_date=("date", "min"), last_date=("date", "max"), n_bars=("date", "size")).reset_index().rename(columns={"ticker": "symbol"})
print(f"loaded {len(daily):,} daily bars, {daily['ticker'].nunique():,}/{len(requested):,} requested symbols returned", flush=True)

# ---------------------------------------------------------------- B1. sessions / duplicates / stale / ohlc / corporate actions on the FULL daily universe
dl = pd.to_datetime(master["delisted_utc"], utc=True, errors="coerce").dt.tz_convert(None).dt.normalize()
ref = pd.DataFrame({"ticker": master["ticker"], "list_date": pd.NaT, "delist_date": dl.where(~master["active"].astype(bool))}).drop_duplicates("ticker")
g, st_sess = check_daily_sessions(daily, cal, DS_A, ref=ref)
agg, det = aggregate_gaps(g, DS_A); ledger.add(agg); det.to_csv(AUDIT / "daily_session_gaps_detail.csv.gz", index=False)
st_sess["gap_detail_rows"] = int(len(det))
g = check_duplicates(daily, ["ticker", "date"], DS_A); ledger.add(g)
g = check_stale_daily(daily, DS_A); agg, det = aggregate_gaps(g, DS_A); ledger.add(agg); det.to_csv(AUDIT / "daily_stale_detail.csv.gz", index=False) if len(det) else None
g, st_ohlc = check_daily_ohlc(daily, DS_A); ledger.add(g)

sp_m = pd.read_parquet(RAW / "massive_splits_since_2016.parquet")
sp_m = sp_m[["ticker", "execution_date", "split_from", "split_to"]]
sp_asof = sp_m[pd.to_datetime(sp_m["execution_date"]) <= LAST]
sp_future = int(len(sp_m) - len(sp_asof))
ref_ca = ref[ref["delist_date"].notna() & (ref["delist_date"] >= pd.Timestamp(START))]
g, st_ca_u = check_corporate_actions(daily, sp_asof, DS_A, ref=ref_ca)
agg, det = aggregate_gaps(g, DS_A); ledger.add(agg); det.to_csv(AUDIT / "daily_corporate_action_gaps_detail.csv.gz", index=False)
st_ca_u["massive_splits_future_dated_excluded"] = sp_future
rep.checks_run += ["calendar", "sessions", "duplicates", "stale", "corporate_actions"]
rep.stats["alpaca_daily_universe"] = {"dataset_id": DS_A, "bars": int(len(daily)), "symbols_returned": int(daily["ticker"].nunique()), "symbols_requested": int(len(requested)),
                                      "sessions": st_sess, "ohlc": st_ohlc, "corporate_actions_vs_massive_splits": st_ca_u,
                                      "provider_timestamp_convention": prov_d["provider_timestamp_convention"]}

# ---------------------------------------------------------------- B2. cross-provider: daily bars (sample) and split tables (all)
xv_path = RAW / "massive_xval_daily.parquet"
if xv_path.exists():
    xv = pd.read_parquet(xv_path)
    xp = json.loads((ROOT / "data/samples/massive_xval_daily.provenance.json").read_text())
    prim = daily[daily["ticker"].isin(xv["ticker"].unique()) & (daily["date"] >= xp["start"])][["ticker", "date", "open", "high", "low", "close", "volume"]]
    g, st_x = check_cross_provider_daily(prim, xv[["ticker", "date", "open", "high", "low", "close", "volume"]], f"xval_daily_alpaca_vs_massive_{xp['start']}_{xp['end']}")
    ledger.add(g)
    rep.stats["cross_provider_daily_alpaca_vs_massive"] = {**st_x, "sample": xp["sample"], "window": [xp["start"], xp["end"]]}
    rep.checks_run += ["cross_provider"]
sp_a_path = RAW / "alpaca_splits.parquet"
if sp_a_path.exists():
    sa = pd.read_parquet(sp_a_path)
    sa = pd.DataFrame({"ticker": sa["symbol"], "execution_date": sa["ex_date"], "split_from": sa["old_rate"], "split_to": sa["new_rate"]})
    universe = set(master["ticker"])                                                    # Massive's table also covers funds/ETFs: compare the research universe only
    g, st_s = check_cross_provider_splits(sp_m[sp_m["ticker"].isin(universe)], sa[sa["ticker"].isin(universe)], f"xval_splits_massive_vs_alpaca_{START}_{END}", (START, str(LAST.date())), "massive", "alpaca")
    ledger.add(g)
    rep.stats["cross_provider_splits_massive_vs_alpaca"] = st_s

# ---------------------------------------------------------------- B3. ticker renames + rename-feed quality + delisted coverage
ren = pd.read_parquet(RAW / "alpaca_name_changes.parquet")
DS_R = f"alpaca_name_changes_{START}_{END}"
g, st_rf = check_rename_feed(ren, (START, str(LAST.date())), DS_R); ledger.add(g)
usable = ren[~ren["old_symbol"].eq(ren["new_symbol"])]
g, st_rn = check_ticker_renames(usable, observed, DS_A, daily=daily.rename(columns={}), )
agg, det = aggregate_gaps(g, DS_A + "|renames"); ledger.add(agg); det.to_csv(AUDIT / "ticker_rename_gaps_detail.csv.gz", index=False) if len(det) else None
rep.stats["ticker_renames"] = {"feed_quality": st_rf, "checks": st_rn}
rep.checks_run += ["ticker_renames"]

g, st_dl = check_delisted_coverage(master, observed, (START, str(LAST.date())), DS_MASTER + "|vs|" + DS_A, cal=cal)
ledger.add(g)
pd.DataFrame({"ticker": st_dl["missing_names"]}).to_csv(AUDIT / "delisted_names_without_bars.csv", index=False)
if st_dl.get("tail_truncated_names"):
    pd.DataFrame({"ticker": st_dl["tail_truncated_names"]}).to_csv(AUDIT / "delisted_names_tail_truncated.csv", index=False)
rep.stats["delisted_coverage"] = {k: v for k, v in st_dl.items() if k not in ("missing_names", "tail_truncated_names")}
rep.checks_run += ["delisted_coverage"]

# ============================================================================ C. NEW: intraday SAMPLE (minute bars, trades, quotes) from Alpaca SIP
isum_path = ROOT / "data/samples/alpaca_intraday_sample.summary.json"
isum = json.loads(isum_path.read_text()) if isum_path.exists() else None
if isum:
    gs = []
    for d in isum["gaps"]:
        gs.append(Gap(**{k: v for k, v in d.items() if k != "gap_id"}))
    agg, det = aggregate_gaps(gs, "alpaca_sip_intraday_sample"); ledger.add(agg); det.to_csv(AUDIT / "intraday_sample_gaps_detail.csv.gz", index=False) if len(det) else None
    rep.stats["alpaca_intraday_sample"] = {"sessions": [{k: r[k] for k in ("session", "why", "minute_bars", "per_ticker_bars", "gap_kinds")} for r in isum["sessions"]],
                                           "ticks_first_2min_of_open": {r["session"]: r["ticks_first_2min_of_open"] for r in isum["sessions"]},
                                           "cross_provider_minute_AAPL_2025-07-03": isum.get("cross_provider_minute_AAPL_2025-07-03")}
    rep.checks_run += ["minute_bars", "timestamp_gaps", "ticks"]

# ============================================================================ D. honest ledger updates (every statement below is computed from the measurements above)
cov_ratio = daily["ticker"].nunique() / max(1, len(requested))
horizon_ok = observed["first_date"].min() <= pd.Timestamp("2016-01-08") and st_sess["expected_sessions"] > 2500
frac_dl = st_dl["delisted_missing_frac"]
sizing = {}
if isum:
    bpt = {}
    for r in isum["sessions"]:
        for tk, n in r["per_ticker_bars"].items():
            bpt.setdefault(tk, []).append(n)
    mean_bars = float(np.mean([np.mean(v) for v in bpt.values()])) if bpt else float("nan")
    total_trades = float(daily["trades"].sum())
    sizing = {"symbol_sessions_with_daily_bar": int(len(daily)), "mean_minute_bars_per_symbol_session_in_sample": round(mean_bars, 1),
              "estimated_total_minute_bars": float(len(daily) * mean_bars), "total_trades_from_daily_bar_counts": total_trades,
              "pages_at_10k_rows_minute": float(len(daily) * mean_bars / 1e4), "pages_at_10k_rows_trades": total_trades / 1e4,
              "days_at_150_req_per_min_minute": float(len(daily) * mean_bars / 1e4 / 150 / 60 / 24), "days_at_150_req_per_min_trades": total_trades / 1e4 / 150 / 60 / 24}
    rep.stats["free_tier_feasibility"] = sizing

if horizon_ok:
    ledger.resolve(by_kind("PRICE_HISTORY_LIMITED_TO_~2Y").gap_id,
                   f"SUPERSEDED for DAILY bars: Alpaca SIP daily (raw) {START}..{END} ingested for {daily['ticker'].nunique():,}/{len(requested):,} requested symbols "
                   f"({len(daily):,} bars, dataset {DS_A}); {st_sess['expected_sessions']} XNYS sessions. Minute bars/ticks remain SAMPLE-ONLY (gap MINUTE_AND_TICK_HISTORY_NOT_MATERIALISED). "
                   "Other regimes now exist to train/validate/lock-OOS on, subject to the survivorship, rename and terminal-return gaps below.")
    ledger.resolve(by_kind("NO_BULK_EXPORT_PATH").gap_id,
                   f"RESOLVED for daily bars and reference data: keys present in the environment; REST bulk-ingested {len(daily):,} daily bars (Alpaca), {prov_m['n_active'] + prov_m['n_inactive']:,} "
                   "security-master rows and the full splits table (Massive). NOT resolved for minute bars/ticks (see MINUTE_AND_TICK_HISTORY_NOT_MATERIALISED).")
if isum:
    q_ok = any(r["ticks_first_2min_of_open"].get("AAPL", {}).get("n_quotes") for r in isum["sessions"])
    if q_ok:
        ledger.resolve(by_kind("NO_HISTORICAL_QUOTES_NBBO").gap_id,
                       "ENTITLEMENT closed: Alpaca free SIP serves historical quotes and trades back to 2016 (verified on a stratified 11-session sample, dataset alpaca_sip_intraday_sample). "
                       "Observed spreads are still NOT available for the research universe: see QUOTES_NBBO_NOT_MATERIALISED (opened below). Spreads remain ASSUMED in any experiment until then.")
    ledger.add([
        Gap("alpaca_sip_free", "coverage", "MINUTE_AND_TICK_HISTORY_NOT_MATERIALISED", MATERIAL,
            f"Free tier allows ~150-200 requests/min and 10,000 rows/page. Measured universe: {sizing['symbol_sessions_with_daily_bar']:,} symbol-sessions; minute bars ~"
            f"{sizing['estimated_total_minute_bars'] / 1e9:.1f}bn rows (~{sizing['days_at_150_req_per_min_minute']:.0f} days of continuous pulling); trades (sum of daily bar trade counts) "
            f"~{sizing['total_trades_from_daily_bar_counts'] / 1e9:.0f}bn rows (~{sizing['days_at_150_req_per_min_trades'] / 365:.0f} years of continuous pulling); free disk ~30 GB. "
            "Only a stratified sample (11 sessions x 4 tickers minute bars; 2-minute trade/quote windows at the open for 2 tickers) is on disk. Minute-level experiments must be scoped to an explicitly chosen "
            "subset of tickers/sessions, declared per experiment; full-universe minute/tick research is infeasible on this tier."),
        Gap("alpaca_sip_free", "coverage", "QUOTES_NBBO_NOT_MATERIALISED", MATERIAL,
            "Historical SIP quotes are accessible but only sampled (2 minutes at the open, 2 tickers, 11 sessions). No observed-spread series exists for the universe; execution-realism for the "
            "overnight/premarket track still rests on assumed spreads. See intraday sample stats for crossed-quote behaviour before relying on raw quote rows as an NBBO."),
    ])
ledger.add([Gap("alpaca_sip_free", "coverage", "REALTIME_EMBARGO_15MIN", EXPECTED,
                "Free tier serves SIP only for end >= 15 minutes ago (measured: HTTP 403 'subscription does not permit querying recent SIP data'). edgelab.alpaca refuses such windows "
                "(RecentDataRefused) instead of clipping. Historical-only by design; not usable for live signals.")])

# ============================================================================ E. coverage (computed from evidence; REQUIREMENTS unchanged)
dl_ok = (frac_dl <= 0.02) and (st_dl["active_missing"] / max(1, st_dl["master_active"]) <= 0.02)
daily_full = bool(horizon_ok and cov_ratio >= 0.98 and dl_ok)
rep.coverage = {
    "daily_bars": {"complete": daily_full, "requested": "all US common stocks, 2024-10..2026-09",
                   "ingested": f"{daily['ticker'].nunique():,}/{len(requested):,} symbols x {START}..{LAST.date()} ({len(daily):,} bars, Alpaca SIP raw)",
                   "note": ("universe returned, delisted coverage within tolerance" if daily_full else
                            f"{len(requested) - daily['ticker'].nunique():,} requested symbols returned no bars; delisted missing {frac_dl:.1%} (tolerance 2%): survivorship-biased")},
    "minute_bars": {"complete": False, "requested": "same universe, premarket+regular", "ingested": "11 sessions x 4 tickers (Alpaca SIP, 04:00-20:00 ET) + 1 Massive session",
                    "note": "sample only; full universe infeasible on free tier (see feasibility)"},
    "news": {"complete": False, "requested": "all tickers, 2024-10..2026-09", "ingested": "6 articles", "note": "sample only; no receipt timestamps (unchanged)"},
    "corporate_actions": {"complete": False, "requested": "splits+dividends, universe",
                          "ingested": f"Massive splits {len(sp_m):,} rows (2016+); Alpaca splits/dividends {'ingested' if sp_a_path.exists() else 'not ingested'}",
                          "note": "splits cross-checked between providers; terminal/delisting returns unknown; dividends not price-validated"},
    "security_master_incl_delisted": {"complete": False, "requested": "full reference incl. delisted",
                                      "ingested": f"{prov_m['n_active']:,} active + {prov_m['n_inactive']:,} inactive common stocks (Massive)",
                                      "note": f"no list dates; {st_dl['inactive_without_delist_date']} inactive names lack delisted_utc; ticker reuse/rename history incomplete"},
    "quotes_nbbo": {"complete": False, "requested": "NBBO around the open", "ingested": "sample: 2 tickers x 11 sessions x 2 min (Alpaca SIP quotes)",
                    "note": "entitled but sample only; per-venue quotes, not a reconstructed NBBO"},
}

REQ = ExperimentRequirements("overnight_news_open_to_close", ["US_EQUITY"], ["daily_bars", "minute_bars", "news", "corporate_actions", "security_master_incl_delisted", "quotes_nbbo"],
                             ("2024-10-01", "2026-09-30"), "all US common stocks incl. delisted; entitled ~2y window")     # UNCHANGED from the previous audit
rep.provider_notes += [
    "PRIMARY price source: Alpaca free Market Data API, feed=sip, adjustment=raw, historical-only (end >= 15 min ago). Daily t = 00:00 America/New_York; minute t = window start UTC.",
    "Massive free tier (5 req/min; aggregates entitled only for ~2 years; bearer-header auth): splits, reference tickers (incl. delisted), cross-validation ONLY.",
    "Alpaca history is keyed by the CURRENT symbol (e.g. FB returns nothing; META returns Facebook from 2016): join on a permanent identifier (FIGI) with an effective-dated ticker map, not on the ticker.",
    "Bars are omitted for empty intervals; illiquid-name gaps are therefore AMBIGUOUS by construction.",
    "Other reachable sources (SEC EDGAR, FRED, Nasdaq Trader symbol directory, Yahoo chart API) are still not ingested; using any of them for prices would be a provider substitution and must be declared per experiment.",
]

# ============================================================================ F. report
ok, why = DiscoveryGate.check(rep, REQ, ledger)
md = rep.to_markdown(ledger, "Data-integrity report (status as of %s)" % now.strftime("%Y-%m-%d %H:%M UTC"))
md += "\n\n" + "\n\n".join(extra_md) if extra_md else ""
md += "\n\n## Discovery gate\n\n**Gate: %s**\n\n" % ("OPEN" if ok else "BLOCKED") + "\n".join(f"- {w}" for w in why[:60])
open_mat = [g for g in ledger.gaps.values() if g.severity == MATERIAL and g.status == "OPEN"]
reg.append("INTEGRITY_REPORT", {"experiment": REQ.name, "gate_open": ok, "n_reasons": len(why), "checks_run": rep.checks_run, "dataset": DS_A, "open_material_gaps": len(open_mat)})
OUT_MD.write_text(md)
print(md[-6000:])
print("gate open:", ok, "| open material gaps:", len(open_mat), "| registry chain valid:", reg.verify_chain(), "| dry run:", DRY, "|", OUT_MD)
