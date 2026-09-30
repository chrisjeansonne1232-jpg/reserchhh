"""Builds docs/DATA_INTEGRITY_REPORT.md from the real provider samples + provider-side verifications.

Everything found is recorded in the immutable registry via the GapLedger. Nothing is dropped, filled or substituted.
"""
import datetime as dt
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from edgelab.integrity import (DiscoveryGate, ExperimentRequirements, Gap, GapLedger, IntegrityReport, MarketCalendar, MATERIAL,
                               AMBIGUOUS, MINOR, check_corporate_actions, check_daily_sessions, check_duplicates, check_news,
                               check_stale_daily)
from edgelab.registry import Registry

ROOT = Path(__file__).resolve().parents[1]
reg = Registry(ROOT / "registry" / "registry.sqlite")
ledger = GapLedger(reg)
cal = MarketCalendar("US_EQUITY")
rep = IntegrityReport()
now = pd.Timestamp.now(tz="UTC")

# ------------------------------------------------------------------ dataset 1: daily bars (REAL SAMPLE)
DS_D = "massive_daily_unadjusted_sample_2025-06-02_2025-07-11"
raw = pd.read_csv(ROOT / "data/samples/massive_daily_unadjusted_sample.csv")
ts = pd.to_datetime(raw["t"], unit="ms", utc=True)
raw["date"] = ts.dt.tz_convert("America/New_York").dt.tz_localize(None).dt.normalize()
daily = raw.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})[["ticker", "date", "open", "high", "low", "close", "volume"]]
splits = pd.DataFrame({"ticker": ["ORLY"], "execution_date": ["2025-06-10"], "split_from": [1.0], "split_to": [15.0]})
g, st_sessions = check_daily_sessions(daily, cal, DS_D); ledger.add(g)
ledger.add(check_duplicates(daily, ["ticker", "date"], DS_D)); ledger.add(check_stale_daily(daily, DS_D))
g, st_ca = check_corporate_actions(daily, splits, DS_D); ledger.add(g)
rep.checks_run += ["calendar", "sessions", "duplicates", "stale", "corporate_actions"]
rep.stats["daily_sample"] = {**st_sessions, "corporate_actions": st_ca,
                             "provider_timestamp_convention": "midnight America/New_York on the session date (verified: 56/56 bars)",
                             "adjusted_flag_verified": "adjusted=false returns UNADJUSTED prices: the ORLY 15:1 split is visible (1348.10 close -> 90.00 open)"}

# ------------------------------------------------------------------ dataset 2: minute bars (REAL, verified provider-side with SQL)
DS_M = "massive_minute_AAPL_2025-07-03_halfday"
rep.checks_run += ["minute_bars", "timestamp_gaps"]
rep.stats["minute_sample_provider_side_sql"] = {
    "ticker/session": "AAPL 2025-07-03 (early close 13:00 ET)", "bars": 499, "regular_expected": 210, "regular_observed": 210,
    "duplicate_timestamps": 0, "off_grid_timestamps": 0, "inconsistent_ohlc": 0, "zero_volume_bars": 0,
    "gaps_in_regular_session": 0, "max_gap_regular_min": 1.0, "premarket_bars": 250, "premarket_possible": 330,
    "after_hours_bars": 39, "max_gap_all_min": 180.0,
    "method": "SQL executed inside the provider workspace on the stored response (same definitions as edgelab.integrity.check_minute_bars)"}
ledger.add([Gap(DS_M, "minute_bars", "EXTENDED_HOURS_SPARSE", AMBIGUOUS,
                "AAPL premarket has 250/330 minute bars and after-hours gaps up to 180 min: aggregates are omitted for minutes with no trades, so "
                "'no trade' cannot be distinguished from 'missing'. Extended-hours prices are therefore NOT reliable fill proxies.", ticker="AAPL",
                start="2025-07-03", end="2025-07-03", n=80)])

# ------------------------------------------------------------------ dataset 3: news (REAL SAMPLE, 6 articles)
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
rep.stats["news_sample"] = st_news

# ------------------------------------------------------------------ provider entitlement & reference findings (measured)
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
rep.provider_notes += [
    "Reference tickers endpoint includes delisted securities with delisted_utc (survivorship-free universe is available in principle).",
    "Bars are omitted for empty intervals; illiquid-name gaps are therefore AMBIGUOUS by construction.",
    "Rate limiting was hit during probing; bulk collection would need pacing.",
    "Free/other sources reachable from the sandbox (SEC EDGAR, FRED, Nasdaq Trader symbol directory, Yahoo chart API): none has been ingested; using any of them for prices would be a provider substitution and must be declared per experiment.",
]

# ------------------------------------------------------------------ coverage vs the INTENDED experiment
REQ = ExperimentRequirements("overnight_news_open_to_close", ["US_EQUITY"], ["daily_bars", "minute_bars", "news", "corporate_actions", "security_master_incl_delisted", "quotes_nbbo"],
                             ("2024-10-01", "2026-09-30"), "all US common stocks incl. delisted; entitled ~2y window")
rep.coverage = {
    "daily_bars": {"complete": False, "requested": "all US common stocks, 2024-10..2026-09", "ingested": "2 tickers x 28 sessions", "note": "sample only; no bulk path"},
    "minute_bars": {"complete": False, "requested": "same universe, premarket+regular", "ingested": "1 ticker x 1 session (provider-side check)", "note": "sample only"},
    "news": {"complete": False, "requested": "all tickers, 2024-10..2026-09", "ingested": "6 articles", "note": "sample only; no receipt timestamps"},
    "corporate_actions": {"complete": False, "requested": "splits+dividends, universe", "ingested": "1 ticker", "note": "sample only"},
    "security_master_incl_delisted": {"complete": False, "requested": "full reference incl. delisted", "ingested": "5 rows probed", "note": "not ingested"},
    "quotes_nbbo": {"complete": False, "requested": "NBBO around the open", "ingested": "none", "note": "NOT ENTITLED"},
}
ok, why = DiscoveryGate.check(rep, REQ, ledger)
md = rep.to_markdown(ledger, "Data-integrity report (status as of %s)" % now.strftime("%Y-%m-%d %H:%M UTC"))
md += "\n\n## Discovery gate\n\n**Gate: %s**\n\n" % ("OPEN" if ok else "BLOCKED") + "\n".join(f"- {w}" for w in why[:40])
reg.append("INTEGRITY_REPORT", {"experiment": REQ.name, "gate_open": ok, "n_reasons": len(why), "checks_run": rep.checks_run})
(ROOT / "docs").mkdir(exist_ok=True)
(ROOT / "docs" / "DATA_INTEGRITY_REPORT.md").write_text(md)
print(md[-3500:])
print("gate open:", ok, "| registry chain valid:", reg.verify_chain())
