# Data-integrity report (status as of 2026-09-30 09:54 UTC)

## Coverage of the intended research dataset

| dataset | complete | requested | ingested | note |
|---|---|---|---|---|
| daily_bars | **NO** | all US common stocks, 2024-10..2026-09 | 2 tickers x 28 sessions | sample only; no bulk path |
| minute_bars | **NO** | same universe, premarket+regular | 1 ticker x 1 session (provider-side check) | sample only |
| news | **NO** | all tickers, 2024-10..2026-09 | 6 articles | sample only; no receipt timestamps |
| corporate_actions | **NO** | splits+dividends, universe | 1 ticker | sample only |
| security_master_incl_delisted | **NO** | full reference incl. delisted | 5 rows probed | not ingested |
| quotes_nbbo | **NO** | NBBO around the open | none | NOT ENTITLED |

## Checks run

calendar, sessions, duplicates, stale, corporate_actions, minute_bars, timestamp_gaps, news_timestamps

## Statistics

```json
{
 "daily_sample": {
  "calendar": "XNYS (exchange_calendars 4.13.2)",
  "range": [
   "2025-06-02",
   "2025-07-11"
  ],
  "expected_sessions": 28,
  "observed_sessions": 28,
  "non_trading_days_expected": {
   "WEEKEND": 10,
   "HOLIDAY": 2
  },
  "early_closes": 1,
  "weekday_holidays": [
   "2025-06-19",
   "2025-07-04"
  ],
  "missing_ticker_sessions_liquid": 0,
  "missing_ticker_sessions_ambiguous": 0,
  "corporate_actions": {
   "recorded_splits": 1,
   "splits_confirmed_in_prices": 1,
   "splits_without_discontinuity": 0,
   "unrecorded_discontinuities": 0
  },
  "provider_timestamp_convention": "midnight America/New_York on the session date (verified: 56/56 bars)",
  "adjusted_flag_verified": "adjusted=false returns UNADJUSTED prices: the ORLY 15:1 split is visible (1348.10 close -> 90.00 open)"
 },
 "minute_sample_provider_side_sql": {
  "ticker/session": "AAPL 2025-07-03 (early close 13:00 ET)",
  "bars": 499,
  "regular_expected": 210,
  "regular_observed": 210,
  "duplicate_timestamps": 0,
  "off_grid_timestamps": 0,
  "inconsistent_ohlc": 0,
  "zero_volume_bars": 0,
  "gaps_in_regular_session": 0,
  "max_gap_regular_min": 1.0,
  "premarket_bars": 250,
  "premarket_possible": 330,
  "after_hours_bars": 39,
  "max_gap_all_min": 180.0,
  "method": "SQL executed inside the provider workspace on the stored response (same definitions as edgelab.integrity.check_minute_bars)"
 },
 "news_sample": {
  "n_articles": 6,
  "midnight_utc_fraction": 0.0,
  "zero_seconds_fraction": 1.0,
  "quarter_hour_fraction": 0.16666666666666666,
  "syndicated_titles_multi_publisher": 0,
  "distinct_publishers": 3,
  "median_articles_per_session": 6.0
 }
}
```

## Gap ledger summary

| check | kind | severity | status | n_gaps |
|---|---|---|---|---|
| access | NO_BULK_EXPORT_PATH | MATERIAL | OPEN | 1 |
| corporate_actions | SPLITS_TABLE_INCLUDES_FUTURE_ACTIONS | MINOR | OPEN | 1 |
| corporate_actions | SPLIT_TYPED_AS_STOCK_DIVIDEND | MINOR | OPEN | 1 |
| coverage | BENZINGA_NEWS_NOT_ENTITLED | MINOR | OPEN | 1 |
| coverage | NO_HISTORICAL_QUOTES_NBBO | MATERIAL | OPEN | 1 |
| coverage | NO_POINT_IN_TIME_FUNDAMENTALS | MATERIAL | OPEN | 1 |
| coverage | PRICE_HISTORY_LIMITED_TO_~2Y | MATERIAL | OPEN | 1 |
| minute_bars | EXTENDED_HOURS_SPARSE | AMBIGUOUS | OPEN | 1 |
| news_independence | NEWS_HAS_NO_RECEIPT_TIMESTAMPS | MATERIAL | OPEN | 1 |
| news_timestamps | MINUTE_RESOLUTION_ONLY | MINOR | OPEN | 1 |
| news_timestamps | NO_SYSTEM_RECEIPT_TS | MATERIAL | OPEN | 1 |
| news_timestamps | NO_VENDOR_RECEIPT_TS | MATERIAL | OPEN | 1 |

## Material gaps (all listed)

- `8656ad608dd5` **NO_VENDOR_RECEIPT_TS**  .. — dataset has no vendor_receipt_ts: true availability time of each article is unknown; a latency assumption is required and must be stress-tested — status: **OPEN** 
- `b02630318686` **NO_SYSTEM_RECEIPT_TS**  .. — dataset has no system_receipt_ts: true availability time of each article is unknown; a latency assumption is required and must be stress-tested — status: **OPEN** 
- `30799fa8a9b1` **PRICE_HISTORY_LIMITED_TO_~2Y**  .. — Daily/minute bars are entitled only from ~late 2024 (2024-12 OK, 2024-09 NOT_ENTITLED, 2010/2000/2022 NOT_ENTITLED). History is ~2 years: covers one market regime; leaves little room for a locked OOS after training/validation. — status: **OPEN** 
- `9dbf1a205b56` **NO_HISTORICAL_QUOTES_NBBO**  .. — /v3/quotes and NBBO ticks are NOT_ENTITLED: no observed bid/ask/spread/depth. Spreads and opening-auction fills must be ASSUMED; the overnight/premarket-news track cannot validate execution realism. — status: **OPEN** 
- `9676ac77713c` **NO_POINT_IN_TIME_FUNDAMENTALS**  .. — /vX/reference/financials returns HTTP 410 (deprecated); replacement income-statement endpoints are NOT_ENTITLED. Fundamentals must come from SEC EDGAR (acceptance timestamps), which is a different provider and must be declared, not substituted silently. — status: **OPEN** 
- `4ece3b95d505` **NEWS_HAS_NO_RECEIPT_TIMESTAMPS**  .. — Only publisher-side published_utc (minute resolution). No vendor/system receipt time, no revision history; 5 distinct publishers seen on one ticker/day. Latency assumptions are unavoidable and must be stress-tested. — status: **OPEN** 
- `84c79cb09927` **NO_BULK_EXPORT_PATH**  .. — No Massive API key exists in the execution environment; data is reachable only through the MCP connector (one bounded request at a time, rate-limited) and cannot be bulk-exported into local storage. The research dataset cannot be materialised for local backtesting. — status: **OPEN** 

## Provider notes / limitations

- Reference tickers endpoint includes delisted securities with delisted_utc (survivorship-free universe is available in principle).
- Bars are omitted for empty intervals; illiquid-name gaps are therefore AMBIGUOUS by construction.
- Rate limiting was hit during probing; bulk collection would need pacing.
- Free/other sources reachable from the sandbox (SEC EDGAR, FRED, Nasdaq Trader symbol directory, Yahoo chart API): none has been ingested; using any of them for prices would be a provider substitution and must be declared per experiment.

## Discovery gate

**Gate: BLOCKED**

- dataset 'daily_bars': coverage incomplete (sample only; no bulk path)
- dataset 'minute_bars': coverage incomplete (sample only)
- dataset 'news': coverage incomplete (sample only; no receipt timestamps)
- dataset 'corporate_actions': coverage incomplete (sample only)
- dataset 'security_master_incl_delisted': coverage incomplete (not ingested)
- dataset 'quotes_nbbo': coverage incomplete (NOT ENTITLED)
- OPEN material gap 8656ad608dd5 [NO_VENDOR_RECEIPT_TS]  : dataset has no vendor_receipt_ts: true availability time of each article is unknown; a lat
- OPEN material gap b02630318686 [NO_SYSTEM_RECEIPT_TS]  : dataset has no system_receipt_ts: true availability time of each article is unknown; a lat
- OPEN material gap 30799fa8a9b1 [PRICE_HISTORY_LIMITED_TO_~2Y]  : Daily/minute bars are entitled only from ~late 2024 (2024-12 OK, 2024-09 NOT_ENTITLED, 201
- OPEN material gap 9dbf1a205b56 [NO_HISTORICAL_QUOTES_NBBO]  : /v3/quotes and NBBO ticks are NOT_ENTITLED: no observed bid/ask/spread/depth. Spreads and 
- OPEN material gap 9676ac77713c [NO_POINT_IN_TIME_FUNDAMENTALS]  : /vX/reference/financials returns HTTP 410 (deprecated); replacement income-statement endpo
- OPEN material gap 4ece3b95d505 [NEWS_HAS_NO_RECEIPT_TIMESTAMPS]  : Only publisher-side published_utc (minute resolution). No vendor/system receipt time, no r
- OPEN material gap 84c79cb09927 [NO_BULK_EXPORT_PATH]  : No Massive API key exists in the execution environment; data is reachable only through the