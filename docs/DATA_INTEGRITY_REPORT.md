# Data-integrity report (status as of 2026-09-30 11:10 UTC)

## Coverage of the intended research dataset

| dataset | complete | requested | ingested | note |
|---|---|---|---|---|
| daily_bars | **NO** | all US common stocks, 2024-10..2026-09 | 10,043/10,387 symbols x 2016-01-01..2026-09-29 (14,521,836 bars, Alpaca SIP raw) | 344 requested symbols returned no bars; delisted missing 5.7% (tolerance 2%): survivorship-biased |
| minute_bars | **NO** | same universe, premarket+regular | 11 sessions x 4 tickers (Alpaca SIP, 04:00-20:00 ET) + 1 Massive session | sample only; full-universe minute history is not on disk (measured size bounds in gap MINUTE_AND_TICK_HISTORY_NOT_MATERIALISED) |
| news | **NO** | all tickers, 2024-10..2026-09 | 6 articles | sample only; no receipt timestamps (unchanged) |
| corporate_actions | **NO** | splits+dividends, universe | Massive splits 3,725 rows (2016+); Alpaca splits/dividends ingested | splits cross-checked between providers; terminal/delisting returns unknown; dividends not price-validated |
| security_master_incl_delisted | **NO** | full reference incl. delisted | 5,323 active + 6,625 inactive common stocks (Massive) | no list dates; 201 inactive names lack delisted_utc; ticker reuse/rename history incomplete |
| quotes_nbbo | **NO** | NBBO around the open | sample: 2 tickers x 11 sessions x 2 min (Alpaca SIP quotes) | entitled but sample only; AAPL, first 2 min of the open, 11 sessions: bid and ask venues differ in 68%-84% of quotes (consolidated-style stream; not proven to be the official NBBO); crossed quotes 0.00%-0.60%; median spread 1.1-8.7 bps. |

## Checks run

calendar, sessions, duplicates, stale, corporate_actions, minute_bars, timestamp_gaps, news_timestamps, cross_provider, ticker_renames, delisted_coverage, ticks

## Statistics

```json
{
 "massive_daily_sample_2025-06..07": {
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
 "massive_minute_sample_provider_side_sql": {
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
 "massive_news_sample": {
  "n_articles": 6,
  "midnight_utc_fraction": 0.0,
  "zero_seconds_fraction": 1.0,
  "quarter_hour_fraction": 0.16666666666666666,
  "syndicated_titles_multi_publisher": 0,
  "distinct_publishers": 3,
  "median_articles_per_session": 6.0
 },
 "alpaca_daily_universe": {
  "dataset_id": "alpaca_sip_daily_raw_2016-01-01_2026-09-30_0d20f42a",
  "bars": 14521836,
  "symbols_returned": 10043,
  "symbols_requested": 10387,
  "sessions": {
   "calendar": "XNYS (exchange_calendars 4.13.2)",
   "range": [
    "2016-01-04",
    "2026-09-29"
   ],
   "expected_sessions": 2700,
   "observed_sessions": 2700,
   "non_trading_days_expected": {
    "WEEKEND": 1120,
    "HOLIDAY": 102
   },
   "early_closes": 21,
   "weekday_holidays": [
    "2016-01-18",
    "2016-02-15",
    "2016-03-25",
    "2016-05-30",
    "2016-07-04",
    "2016-09-05",
    "2016-11-24",
    "2016-12-26",
    "2017-01-02",
    "2017-01-16",
    "2017-02-20",
    "2017-04-14",
    "2017-05-29",
    "2017-07-04",
    "2017-09-04",
    "2017-11-23",
    "2017-12-25",
    "2018-01-01",
    "2018-01-15",
    "2018-02-19",
    "2018-03-30",
    "2018-05-28",
    "2018-07-04",
    "2018-09-03",
    "2018-11-22",
    "2018-12-05",
    "2018-12-25",
    "2019-01-01",
    "2019-01-21",
    "2019-02-18",
    "2019-04-19",
    "2019-05-27",
    "2019-07-04",
    "2019-09-02",
    "2019-11-28",
    "2019-12-25",
    "2020-01-01",
    "2020-01-20",
    "2020-02-17",
    "2020-04-10",
    "2020-05-25",
    "2020-07-03",
    "2020-09-07",
    "2020-11-26",
    "2020-12-25",
    "2021-01-01",
    "2021-01-18",
    "2021-02-15",
    "2021-04-02",
    "2021-05-31",
    "2021-07-05",
    "2021-09-06",
    "2021-11-25",
    "2021-12-24",
    "2022-01-17",
    "2022-02-21",
    "2022-04-15",
    "2022-05-30",
    "2022-06-20",
    "2022-07-04",
    "2022-09-05",
    "2022-11-24",
    "2022-12-26",
    "2023-01-02",
    "2023-01-16",
    "2023-02-20",
    "2023-04-07",
    "2023-05-29",
    "2023-06-19",
    "2023-07-04",
    "2023-09-04",
    "2023-11-23",
    "2023-12-25",
    "2024-01-01",
    "2024-01-15",
    "2024-02-19",
    "2024-03-29",
    "2024-05-27",
    "2024-06-19",
    "2024-07-04",
    "2024-09-02",
    "2024-11-28",
    "2024-12-25",
    "2025-01-01",
    "2025-01-09",
    "2025-01-20",
    "2025-02-17",
    "2025-04-18",
    "2025-05-26",
    "2025-06-19",
    "2025-07-04",
    "2025-09-01",
    "2025-11-27",
    "2025-12-25",
    "2026-01-01",
    "2026-01-19",
    "2026-02-16",
    "2026-04-03",
    "2026-05-25",
    "2026-06-19",
    "2026-07-03",
    "2026-09-07"
   ],
   "missing_ticker_sessions_liquid": 31792,
   "missing_ticker_sessions_ambiguous": 51547,
   "gap_detail_rows": 414
  },
  "ohlc": {
   "bars": 14521836,
   "nonpositive_or_null_price": 0,
   "high_below_low": 0,
   "high_below_open_or_close": 0,
   "low_above_open_or_close": 0,
   "negative_volume": 0
  },
  "zero_volume_placeholder_bars": {
   "bars": 14521836,
   "zero_volume_bars": 544945,
   "zero_volume_frac": 0.03753,
   "tickers_affected": 3718,
   "zero_volume_flat_ohlc": 544945,
   "zero_volume_equal_previous_close": 544881,
   "zero_volume_first_bar_of_ticker": 46,
   "worst_tickers": {
    "BIO.B": 2231,
    "WSO.B": 2192,
    "CAPN": 2069,
    "LINE": 2055,
    "GRO": 2029
   },
   "placeholder_runs_ge_min_run": {
    "min_run_sessions": 60,
    "runs": 552,
    "tickers": 531,
    "examples": [
     "LINE 2016-05-24..2024-07-24 (2055 sessions)",
     "GRO 2016-11-03..2024-11-26 (2029 sessions)",
     "CAPN 2017-05-12..2024-10-23 (1875 sessions)",
     "PN 2017-11-24..2025-03-03 (1826 sessions)",
     "BMR 2016-01-28..2023-02-27 (1783 sessions)",
     "NATL 2016-11-11..2023-10-16 (1742 sessions)"
    ]
   }
  },
  "corporate_actions_vs_massive_splits": {
   "recorded_splits": 3713,
   "splits_confirmed_in_prices": 2466,
   "splits_without_discontinuity": 857,
   "unrecorded_discontinuities": 6737,
   "massive_splits_future_dated_excluded": 12,
   "massive_splits_out_of_universe_excluded": 9780
  },
  "provider_timestamp_convention": "t = 00:00 America/New_York expressed in UTC (04:00Z EDT / 05:00Z EST); 'session' column = that NY date"
 },
 "cross_provider_daily_alpaca_vs_massive": {
  "rows_both": 12100,
  "only_primary": 1,
  "only_reference": 0,
  "open_mismatch_frac": 0.00967,
  "high_mismatch_frac": 0.00967,
  "low_mismatch_frac": 0.00983,
  "close_mismatch_frac": 0.00992,
  "volume_mismatch_frac": 0.01017,
  "volume_median_ratio_primary_over_reference": 1.0,
  "mismatch_attribution": {
   "rows_mismatching_close": 120,
   "by_ticker": {
    "ASNS": 117,
    "CDT": 1,
    "TRUG": 1,
    "VRME": 1
   },
   "of_which_alpaca_volume_zero": 117,
   "of_which_massive_volume_positive": 120
  },
  "sample": {
   "liquid": [
    "NVDA",
    "TSLA",
    "AAPL",
    "MSFT",
    "AMZN",
    "META",
    "GOOGL",
    "PLTR",
    "AMD",
    "AVGO"
   ],
   "random": [
    "STRZ",
    "SLDP",
    "NTST",
    "LAES",
    "DOCS",
    "ALKT",
    "ADM",
    "EQX",
    "CDTG",
    "ASNS"
   ],
   "with_split": [
    "VRME",
    "TRUG",
    "ONMD",
    "CDT",
    "AGRZ"
   ]
  },
  "window": [
   "2024-10-01",
   "2026-09-29"
  ]
 },
 "cross_provider_splits_massive_vs_alpaca": {
  "n_massive": 3713,
  "n_alpaca": 3106,
  "only_in_massive": 838,
  "only_in_alpaca": 227,
  "agree": 2875,
  "window": [
   "2016-01-01",
   "2026-09-29"
  ],
  "examples_only_massive": [
   "GPUS 2026-09-15 1.04067:1",
   "METCB 2026-09-11 1.02563:1",
   "HLSQ 2026-09-09 1:10",
   "TREO 2026-08-20 1:4",
   "SCCO 2026-08-11 1.012:1",
   "CLBK 2026-07-21 2.2:1",
   "GORO 2026-07-20 1:4",
   "SNFCA 2026-07-10 1.05:1"
  ],
  "examples_only_alpaca": [
   "APD 2016-10-03 1081:1000",
   "BF.A 2016-08-19 2:1",
   "BF.B 2016-08-19 2:1",
   "CAG 2016-11-10 1285:1000",
   "EBIX 2016-08-02 3:1",
   "GILT 2016-02-29 2:1",
   "HON 2016-10-03 10000:9947",
   "AA 2016-11-01 0.33333:1"
  ],
  "integer_ratio_subset": {
   "n_massive": 3252,
   "n_alpaca": 2910,
   "agree": 2730,
   "only_in_massive": 522,
   "only_in_alpaca": 177
  },
  "fractional_ratio_events": {
   "massive": 462,
   "alpaca": 196
  }
 },
 "ticker_renames": {
  "feed_quality": {
   "events": 3667,
   "events_per_year": {
    "2016": 0,
    "2017": 2,
    "2018": 2,
    "2019": 53,
    "2020": 304,
    "2021": 576,
    "2022": 399,
    "2023": 500,
    "2024": 700,
    "2025": 670,
    "2026": 461
   },
   "reference_events_per_year": 576.0,
   "sparse_years": [
    2016,
    2017,
    2018,
    2019
   ],
   "first_event": "2017-04-10",
   "noop_renames": 219,
   "cusip_as_symbol": 37,
   "duplicate_events": 0
  },
  "checks": {
   "renames_in_scope": 3448,
   "renames_with_bars_checked": 1489,
   "backmapped": 222,
   "old_symbol_dark": 222,
   "target_symbol_prior_history": 977,
   "reused_symbols": 180,
   "price_discontinuities": 158
  }
 },
 "delisted_coverage": {
  "window": [
   "2016-01-01",
   "2026-09-29"
  ],
  "master_active": 5323,
  "master_inactive": 6625,
  "delisted_in_window": 4863,
  "delisted_with_bars": 4587,
  "delisted_missing": 276,
  "delisted_missing_frac": 0.0568,
  "active_with_bars": 5320,
  "active_missing": 3,
  "delisted_coverage_by_delist_year": {
   "2016": {
    "delisted": 230,
    "with_bars": 209,
    "coverage": 0.9087
   },
   "2017": {
    "delisted": 354,
    "with_bars": 322,
    "coverage": 0.9096
   },
   "2018": {
    "delisted": 343,
    "with_bars": 307,
    "coverage": 0.895
   },
   "2019": {
    "delisted": 364,
    "with_bars": 340,
    "coverage": 0.9341
   },
   "2020": {
    "delisted": 339,
    "with_bars": 313,
    "coverage": 0.9233
   },
   "2021": {
    "delisted": 473,
    "with_bars": 446,
    "coverage": 0.9429
   },
   "2022": {
    "delisted": 518,
    "with_bars": 501,
    "coverage": 0.9672
   },
   "2023": {
    "delisted": 702,
    "with_bars": 679,
    "coverage": 0.9672
   },
   "2024": {
    "delisted": 569,
    "with_bars": 550,
    "coverage": 0.9666
   },
   "2025": {
    "delisted": 514,
    "with_bars": 497,
    "coverage": 0.9669
   },
   "2026": {
    "delisted": 457,
    "with_bars": 423,
    "coverage": 0.9256
   }
  },
  "inactive_without_delist_date": 201,
  "delisted_tail_truncated": 24
 },
 "alpaca_intraday_sample": {
  "sessions": [
   {
    "session": "2016-11-25",
    "why": "early close (day after Thanksgiving)",
    "minute_bars": 854,
    "per_ticker_bars": {
     "AAPL": 312,
     "AMS": 6,
     "META": 338,
     "ORLY": 198
    },
    "gap_kinds": [
     "NO_TRADE_OR_MISSING_MINUTES",
     "SCATTERED_MISSING_MINUTES_LIQUID"
    ]
   },
   {
    "session": "2017-03-13",
    "why": "first Monday after DST start",
    "minute_bars": 1324,
    "per_ticker_bars": {
     "AAPL": 492,
     "AMS": 21,
     "META": 461,
     "ORLY": 350
    },
    "gap_kinds": [
     "MISSING_MINUTES_LIQUID",
     "NO_TRADE_OR_MISSING_MINUTES",
     "SCATTERED_MISSING_MINUTES_LIQUID"
    ]
   },
   {
    "session": "2018-07-03",
    "why": "early close",
    "minute_bars": 1085,
    "per_ticker_bars": {
     "AAPL": 443,
     "AMS": 1,
     "META": 444,
     "ORLY": 197
    },
    "gap_kinds": [
     "NO_TRADE_OR_MISSING_MINUTES",
     "SCATTERED_MISSING_MINUTES_LIQUID"
    ]
   },
   {
    "session": "2019-06-12",
    "why": "normal",
    "minute_bars": 1430,
    "per_ticker_bars": {
     "AAPL": 587,
     "AMS": 17,
     "META": 549,
     "ORLY": 277
    },
    "gap_kinds": [
     "MISSING_MINUTES_LIQUID",
     "NO_TRADE_OR_MISSING_MINUTES",
     "SCATTERED_MISSING_MINUTES_LIQUID"
    ]
   },
   {
    "session": "2020-03-16",
    "why": "COVID crash, circuit breakers",
    "minute_bars": 2046,
    "per_ticker_bars": {
     "AAPL": 906,
     "AMS": 21,
     "META": 743,
     "ORLY": 376
    },
    "gap_kinds": [
     "MISSING_MINUTES_LIQUID",
     "NO_TRADE_OR_MISSING_MINUTES",
     "SCATTERED_MISSING_MINUTES_LIQUID"
    ]
   },
   {
    "session": "2021-11-26",
    "why": "early close",
    "minute_bars": 1341,
    "per_ticker_bars": {
     "AAPL": 717,
     "AMS": 11,
     "META": 456,
     "ORLY": 157
    },
    "gap_kinds": [
     "MISSING_MINUTES_LIQUID",
     "NO_TRADE_OR_MISSING_MINUTES",
     "SCATTERED_MISSING_MINUTES_LIQUID"
    ]
   },
   {
    "session": "2022-06-09",
    "why": "FB->META rename day",
    "minute_bars": 1710,
    "per_ticker_bars": {
     "AAPL": 820,
     "AMS": 6,
     "META": 618,
     "ORLY": 266
    },
    "gap_kinds": [
     "MISSING_MINUTES_LIQUID",
     "NO_TRADE_OR_MISSING_MINUTES",
     "SCATTERED_MISSING_MINUTES_LIQUID"
    ]
   },
   {
    "session": "2023-11-06",
    "why": "first Monday after DST end",
    "minute_bars": 1510,
    "per_ticker_bars": {
     "AAPL": 739,
     "AMS": 9,
     "META": 578,
     "ORLY": 184
    },
    "gap_kinds": [
     "NO_TRADE_OR_MISSING_MINUTES"
    ]
   },
   {
    "session": "2024-07-03",
    "why": "early close",
    "minute_bars": 1079,
    "per_ticker_bars": {
     "AAPL": 591,
     "AMS": 2,
     "META": 330,
     "ORLY": 156
    },
    "gap_kinds": [
     "NO_TRADE_OR_MISSING_MINUTES"
    ]
   },
   {
    "session": "2025-07-03",
    "why": "early close (Massive cross-check day)",
    "minute_bars": 1296,
    "per_ticker_bars": {
     "AAPL": 645,
     "AMS": 7,
     "META": 419,
     "ORLY": 225
    },
    "gap_kinds": [
     "NO_TRADE_OR_MISSING_MINUTES"
    ]
   },
   {
    "session": "2026-09-29",
    "why": "latest completed session",
    "minute_bars": 2157,
    "per_ticker_bars": {
     "AAPL": 871,
     "AMS": 3,
     "META": 890,
     "ORLY": 393
    },
    "gap_kinds": [
     "NO_TRADE_OR_MISSING_MINUTES"
    ]
   }
  ],
  "ticks_first_2min_of_open": {
   "2016-11-25": {
    "AAPL": {
     "n_trades": 2189,
     "trades_nonpositive_price_or_size": 0,
     "trades_out_of_order": 0,
     "trades_duplicate_ids": 0,
     "n_quotes": 2073,
     "quotes_crossed": 2,
     "quotes_locked": 49,
     "quotes_one_sided_or_zero": 0,
     "quotes_out_of_order": 0,
     "median_spread_bps": 1.798,
     "quotes_bid_ask_venue_differ_frac": 0.8143,
     "distinct_bid_venues": 9
    },
    "ORLY": {
     "n_trades": 97,
     "trades_nonpositive_price_or_size": 0,
     "trades_out_of_order": 0,
     "trades_duplicate_ids": 0,
     "n_quotes": 95,
     "quotes_crossed": 0,
     "quotes_locked": 0,
     "quotes_one_sided_or_zero": 0,
     "quotes_out_of_order": 0,
     "median_spread_bps": 33.028,
     "quotes_bid_ask_venue_differ_frac": 0.5053,
     "distinct_bid_venues": 6
    }
   },
   "2017-03-13": {
    "AAPL": {
     "n_trades": 1756,
     "trades_nonpositive_price_or_size": 0,
     "trades_out_of_order": 0,
     "trades_duplicate_ids": 0,
     "n_quotes": 2337,
     "quotes_crossed": 0,
     "quotes_locked": 82,
     "quotes_one_sided_or_zero": 0,
     "quotes_out_of_order": 0,
     "median_spread_bps": 2.157,
     "quotes_bid_ask_venue_differ_frac": 0.8049,
     "distinct_bid_venues": 9
    },
    "ORLY": {
     "n_trades": 24,
     "trades_nonpositive_price_or_size": 0,
     "trades_out_of_order": 0,
     "trades_duplicate_ids": 0,
     "n_quotes": 51,
     "quotes_crossed": 0,
     "quotes_locked": 0,
     "quotes_one_sided_or_zero": 0,
     "quotes_out_of_order": 0,
     "median_spread_bps": 58.266,
     "quotes_bid_ask_venue_differ_frac": 0.7647,
     "distinct_bid_venues": 5
    }
   },
   "2018-07-03": {
    "AAPL": {
     "n_trades": 2677,
     "trades_nonpositive_price_or_size": 0,
     "trades_out_of_order": 0,
     "trades_duplicate_ids": 0,
     "n_quotes": 3652,
     "quotes_crossed": 0,
     "quotes_locked": 39,
     "quotes_one_sided_or_zero": 0,
     "quotes_out_of_order": 0,
     "median_spread_bps": 1.597,
     "quotes_bid_ask_venue_differ_frac": 0.7191,
     "distinct_bid_venues": 10
    },
    "ORLY": {
     "n_trades": 54,
     "trades_nonpositive_price_or_size": 0,
     "trades_out_of_order": 0,
     "trades_duplicate_ids": 0,
     "n_quotes": 182,
     "quotes_crossed": 0,
     "quotes_locked": 0,
     "quotes_one_sided_or_zero": 0,
     "quotes_out_of_order": 0,
     "median_spread_bps": 23.72,
     "quotes_bid_ask_venue_differ_frac": 0.6374,
     "distinct_bid_venues": 10
    }
   },
   "2019-06-12": {
    "AAPL": {
     "n_trades": 2930,
     "trades_nonpositive_price_or_size": 0,
     "trades_out_of_order": 0,
     "trades_duplicate_ids": 0,
     "n_quotes": 3866,
     "quotes_crossed": 7,
     "quotes_locked": 25,
     "quotes_one_sided_or_zero": 0,
     "quotes_out_of_order": 0,
     "median_spread_bps": 2.582,
     "quotes_bid_ask_venue_differ_frac": 0.7015,
     "distinct_bid_venues": 12
    },
    "ORLY": {
     "n_trades": 50,
     "trades_nonpositive_price_or_size": 0,
     "trades_out_of_order": 0,
     "trades_duplicate_ids": 0,
     "n_quotes": 183,
     "quotes_crossed": 0,
     "quotes_locked": 0,
     "quotes_one_sided_or_zero": 0,
     "quotes_out_of_order": 0,
     "median_spread_bps": 40.025,
     "quotes_bid_ask_venue_differ_frac": 0.8907,
     "distinct_bid_venues": 9
    }
   },
   "2020-03-16": {
    "AAPL": {
     "n_trades": 1247,
     "trades_nonpositive_price_or_size": 0,
     "trades_out_of_order": 0,
     "trades_duplicate_ids": 10,
     "n_quotes": 376,
     "quotes_crossed": 1,
     "quotes_locked": 0,
     "quotes_one_sided_or_zero": 0,
     "quotes_out_of_order": 0,
     "median_spread_bps": 8.696,
     "quotes_bid_ask_venue_differ_frac": 0.6755,
     "distinct_bid_venues": 11
    },
    "ORLY": {
     "n_trades": 25,
     "trades_nonpositive_price_or_size": 0,
     "trades_out_of_order": 0,
     "trades_duplicate_ids": 8,
     "n_quotes": 16,
     "quotes_crossed": 0,
     "quotes_locked": 0,
     "quotes_one_sided_or_zero": 0,
     "quotes_out_of_order": 0,
     "median_spread_bps": 250.225,
     "quotes_bid_ask_venue_differ_frac": 0.6875,
     "distinct_bid_venues": 7
    }
   },
   "2021-11-26": {
    "AAPL": {
     "n_trades": 21782,
     "trades_nonpositive_price_or_size": 0,
     "trades_out_of_order": 0,
     "trades_duplicate_ids": 8557,
     "n_quotes": 11850,
     "quotes_crossed": 4,
     "quotes_locked": 109,
     "quotes_one_sided_or_zero": 0,
     "quotes_out_of_order": 0,
     "median_spread_bps": 1.878,
     "quotes_bid_ask_venue_differ_frac": 0.8346,
     "distinct_bid_venues": 14
    },
    "ORLY": {
     "n_trades": 109,
     "trades_nonpositive_price_or_size": 0,
     "trades_out_of_order": 0,
     "trades_duplicate_ids": 75,
     "n_quotes": 297,
     "quotes_crossed": 0,
     "quotes_locked": 0,
     "quotes_one_sided_or_zero": 0,
     "quotes_out_of_order": 0,
     "median_spread_bps": 39.525,
     "quotes_bid_ask_venue_differ_frac": 0.7475,
     "distinct_bid_venues": 5
    }
   },
   "2022-06-09": {
    "AAPL": {
     "n_trades": 17205,
     "trades_nonpositive_price_or_size": 0,
     "trades_out_of_order": 0,
     "trades_duplicate_ids": 9201,
     "n_quotes": 23017,
     "quotes_crossed": 11,
     "quotes_locked": 210,
     "quotes_one_sided_or_zero": 0,
     "quotes_out_of_order": 0,
     "median_spread_bps": 1.358,
     "quotes_bid_ask_venue_differ_frac": 0.8413,
     "distinct_bid_venues": 15
    },
    "ORLY": {
     "n_trades": 216,
     "trades_nonpositive_price_or_size": 0,
     "trades_out_of_order": 0,
     "trades_duplicate_ids": 94,
     "n_quotes": 211,
     "quotes_crossed": 0,
     "quotes_locked": 0,
     "quotes_one_sided_or_zero": 0,
     "quotes_out_of_order": 0,
     "median_spread_bps": 41.082,
     "quotes_bid_ask_venue_differ_frac": 0.7536,
     "distinct_bid_venues": 6
    }
   },
   "2023-11-06": {
    "AAPL": {
     "n_trades": 16905,
     "trades_nonpositive_price_or_size": 0,
     "trades_out_of_order": 0,
     "trades_duplicate_ids": 5295,
     "n_quotes": 12218,
     "quotes_crossed": 9,
     "quotes_locked": 138,
     "quotes_one_sided_or_zero": 0,
     "quotes_out_of_order": 0,
     "median_spread_bps": 1.134,
     "quotes_bid_ask_venue_differ_frac": 0.834,
     "distinct_bid_venues": 13
    },
    "ORLY": {
     "n_trades": 201,
     "trades_nonpositive_price_or_size": 0,
     "trades_out_of_order": 0,
     "trades_duplicate_ids": 27,
     "n_quotes": 33,
     "quotes_crossed": 0,
     "quotes_locked": 0,
     "quotes_one_sided_or_zero": 0,
     "quotes_out_of_order": 0,
     "median_spread_bps": 60.732,
     "quotes_bid_ask_venue_differ_frac": 0.6364,
     "distinct_bid_venues": 6
    }
   },
   "2024-07-03": {
    "AAPL": {
     "n_trades": 17188,
     "trades_nonpositive_price_or_size": 0,
     "trades_out_of_order": 0,
     "trades_duplicate_ids": 5825,
     "n_quotes": 12093,
     "quotes_crossed": 8,
     "quotes_locked": 127,
     "quotes_one_sided_or_zero": 0,
     "quotes_out_of_order": 0,
     "median_spread_bps": 1.821,
     "quotes_bid_ask_venue_differ_frac": 0.7309,
     "distinct_bid_venues": 15
    },
    "ORLY": {
     "n_trades": 133,
     "trades_nonpositive_price_or_size": 0,
     "trades_out_of_order": 0,
     "trades_duplicate_ids": 38,
     "n_quotes": 272,
     "quotes_crossed": 0,
     "quotes_locked": 0,
     "quotes_one_sided_or_zero": 0,
     "quotes_out_of_order": 0,
     "median_spread_bps": 79.797,
     "quotes_bid_ask_venue_differ_frac": 0.4963,
     "distinct_bid_venues": 6
    }
   },
   "2025-07-03": {
    "AAPL": {
     "n_trades": 15818,
     "trades_nonpositive_price_or_size": 0,
     "trades_out_of_order": 0,
     "trades_duplicate_ids": 4500,
     "n_quotes": 5052,
     "quotes_crossed": 2,
     "quotes_locked": 24,
     "quotes_one_sided_or_zero": 0,
     "quotes_out_of_order": 0,
     "median_spread_bps": 2.358,
     "quotes_bid_ask_venue_differ_frac": 0.7284,
     "distinct_bid_venues": 12
    },
    "ORLY": {
     "n_trades": 616,
     "trades_nonpositive_price_or_size": 0,
     "trades_out_of_order": 0,
     "trades_duplicate_ids": 235,
     "n_quotes": 99,
     "quotes_crossed": 0,
     "quotes_locked": 0,
     "quotes_one_sided_or_zero": 0,
     "quotes_out_of_order": 0,
     "median_spread_bps": 30.203,
     "quotes_bid_ask_venue_differ_frac": 0.7475,
     "distinct_bid_venues": 7
    }
   },
   "2026-09-29": {
    "AAPL": {
     "n_trades": 22305,
     "trades_nonpositive_price_or_size": 0,
     "trades_out_of_order": 0,
     "trades_duplicate_ids": 9182,
     "n_quotes": 14757,
     "quotes_crossed": 89,
     "quotes_locked": 72,
     "quotes_one_sided_or_zero": 0,
     "quotes_out_of_order": 0,
     "median_spread_bps": 2.693,
     "quotes_bid_ask_venue_differ_frac": 0.7314,
     "distinct_bid_venues": 14
    },
    "ORLY": {
     "n_trades": 240,
     "trades_nonpositive_price_or_size": 0,
     "trades_out_of_order": 0,
     "trades_duplicate_ids": 62,
     "n_quotes": 186,
     "quotes_crossed": 0,
     "quotes_locked": 0,
     "quotes_one_sided_or_zero": 0,
     "quotes_out_of_order": 0,
     "median_spread_bps": 37.086,
     "quotes_bid_ask_venue_differ_frac": 0.6989,
     "distinct_bid_venues": 9
    }
   }
  },
  "cross_provider_minute_AAPL_2025-07-03": {
   "rows_both": 499,
   "only_primary": 146,
   "only_reference": 0,
   "open_mismatch_frac": 0.0,
   "high_mismatch_frac": 0.0,
   "low_mismatch_frac": 0.0,
   "close_mismatch_frac": 0.0,
   "volume_mismatch_frac": 0.002,
   "volume_median_ratio_primary_over_reference": 1.0,
   "gap_kinds": [
    "BAR_PRESENT_IN_ONE_PROVIDER_ONLY"
   ]
  }
 },
 "free_tier_feasibility": {
  "symbol_sessions_with_daily_bar": 14521836,
  "bytes_per_row_measured_parquet": {
   "minute": 42.1,
   "trades": 15.5,
   "quotes": 11.2
  },
  "minute_rows_upper_bound_sum_min_trades_960": 10323036933.0,
  "minute_gb_upper_bound": 434.5998548793,
  "minute_days_pulling_upper_bound_150rpm_10k_rows": 4.779183765277778,
  "trades_rows_total": 143956221781.0,
  "trades_gb_at_measured_bytes": 2231.3214376055,
  "trades_days_pulling_150rpm_10k_rows": 66.64639897268519,
  "free_disk_gb": 30.9,
  "minute_true_row_count_fraction_that_would_fit_disk": 0.07109860097072881
 }
}
```

## Gap ledger summary

| check | kind | severity | status | n_gaps |
|---|---|---|---|---|
| access | NO_BULK_EXPORT_PATH | MATERIAL | RESOLVED | 1 |
| corporate_actions | DELISTING_RETURN_UNKNOWN | MATERIAL | OPEN | 1 |
| corporate_actions | LARGE_UNEXPLAINED_GAP | MINOR | OPEN | 1 |
| corporate_actions | SPLITS_TABLE_INCLUDES_FUTURE_ACTIONS | MINOR | OPEN | 1 |
| corporate_actions | SPLIT_NO_PRICE_DATA | MATERIAL | OPEN | 1 |
| corporate_actions | SPLIT_TABLES_DISAGREE | MATERIAL | OPEN | 1 |
| corporate_actions | SPLIT_TYPED_AS_STOCK_DIVIDEND | MINOR | OPEN | 1 |
| corporate_actions | SPLIT_WITHOUT_DISCONTINUITY | MATERIAL | OPEN | 1 |
| corporate_actions | UNRECORDED_SPLIT_LIKE_DISCONTINUITY | MATERIAL | OPEN | 1 |
| coverage | BENZINGA_NEWS_NOT_ENTITLED | MINOR | OPEN | 1 |
| coverage | MINUTE_AND_TICK_HISTORY_NOT_MATERIALISED | MATERIAL | OPEN | 1 |
| coverage | MINUTE_AND_TICK_HISTORY_NOT_MATERIALISED | MATERIAL | RESOLVED | 1 |
| coverage | NO_HISTORICAL_QUOTES_NBBO | MATERIAL | RESOLVED | 1 |
| coverage | NO_POINT_IN_TIME_FUNDAMENTALS | MATERIAL | OPEN | 1 |
| coverage | PRICE_HISTORY_LIMITED_TO_~2Y | MATERIAL | RESOLVED | 1 |
| coverage | QUOTES_NBBO_NOT_MATERIALISED | MATERIAL | OPEN | 1 |
| coverage | REALTIME_EMBARGO_15MIN | EXPECTED | RESOLVED | 1 |
| cross_provider | BAR_PRESENT_IN_ONE_PROVIDER_ONLY | AMBIGUOUS | OPEN | 1 |
| cross_provider | BAR_PRESENT_IN_ONE_PROVIDER_ONLY | MATERIAL | OPEN | 1 |
| cross_provider | PRICE_MISMATCH_BETWEEN_PROVIDERS | MINOR | OPEN | 1 |
| cross_provider | VOLUME_MISMATCH_BETWEEN_PROVIDERS | MINOR | OPEN | 1 |
| delisted_coverage | DELISTED_NAMES_NO_BARS | MATERIAL | OPEN | 1 |
| delisted_coverage | DELISTED_TAIL_TRUNCATED | MINOR | OPEN | 1 |
| delisted_coverage | INACTIVE_WITHOUT_DELIST_DATE | AMBIGUOUS | OPEN | 1 |
| minute_bars | EXTENDED_HOURS_SPARSE | AMBIGUOUS | OPEN | 1 |
| minute_bars | MISSING_MINUTES_LIQUID | MATERIAL | OPEN | 1 |
| minute_bars | NO_TRADE_OR_MISSING_MINUTES | AMBIGUOUS | OPEN | 1 |
| minute_bars | SCATTERED_MISSING_MINUTES_LIQUID | MINOR | OPEN | 1 |
| news_independence | NEWS_HAS_NO_RECEIPT_TIMESTAMPS | MATERIAL | OPEN | 1 |
| news_timestamps | MINUTE_RESOLUTION_ONLY | MINOR | OPEN | 1 |
| news_timestamps | NO_SYSTEM_RECEIPT_TS | MATERIAL | OPEN | 1 |
| news_timestamps | NO_VENDOR_RECEIPT_TS | MATERIAL | OPEN | 1 |
| sessions | BARS_AFTER_DELISTING | MATERIAL | OPEN | 1 |
| sessions | MISSING_SESSION_LIQUID | MATERIAL | OPEN | 1 |
| sessions | MISSING_TAIL | MATERIAL | OPEN | 1 |
| sessions | NO_TRADE_OR_MISSING | AMBIGUOUS | OPEN | 1 |
| stale | STALE_DAILY_PRICES | MATERIAL | OPEN | 1 |
| stale | ZERO_VOLUME_BARS | MINOR | OPEN | 1 |
| stale | ZERO_VOLUME_PLACEHOLDER_BARS | MATERIAL | OPEN | 1 |
| ticker_renames | CUSIP_IN_SYMBOL_FIELD | MINOR | OPEN | 1 |
| ticker_renames | NOOP_RENAME_EVENTS | MINOR | OPEN | 1 |
| ticker_renames | RENAME_FEED_SPARSE | MATERIAL | OPEN | 1 |
| ticker_renames | RENAME_HISTORY_BACKMAPPED | MATERIAL | OPEN | 1 |
| ticker_renames | RENAME_TARGET_SYMBOL_HAS_PRIOR_HISTORY | AMBIGUOUS | OPEN | 1 |
| ticker_renames | RENAME_WITH_PRICE_DISCONTINUITY | MATERIAL | OPEN | 1 |
| ticker_renames | SYMBOL_REUSED_ACROSS_ISSUERS | MATERIAL | OPEN | 1 |
| ticks | CROSSED_QUOTES | AMBIGUOUS | OPEN | 1 |

## Material gaps (all listed)

- `8656ad608dd5` **NO_VENDOR_RECEIPT_TS**  .. — dataset has no vendor_receipt_ts: true availability time of each article is unknown; a latency assumption is required and must be stress-tested — status: **OPEN** 
- `b02630318686` **NO_SYSTEM_RECEIPT_TS**  .. — dataset has no system_receipt_ts: true availability time of each article is unknown; a latency assumption is required and must be stress-tested — status: **OPEN** 
- `30799fa8a9b1` **PRICE_HISTORY_LIMITED_TO_~2Y**  .. — Daily/minute bars are entitled only from ~late 2024 (2024-12 OK, 2024-09 NOT_ENTITLED, 2010/2000/2022 NOT_ENTITLED). History is ~2 years: covers one market regime; leaves little room for a locked OOS after training/validation. — status: **RESOLVED** SUPERSEDED for DAILY bars: Alpaca SIP daily (raw) 2016-01-01..2026-09-30 ingested for 10,043/10,387 requested symbols (14,521,836 bars, dataset alpaca_sip_daily_raw_2016-01-01_2026-09-30_0d20f42a); 2700 XNYS sessions. Minute bars/ticks remain SAMPLE-ONLY (gap MINUTE_AND_TICK_HISTORY_NOT_MATERIALISED). Other regimes now exist to train/validate/lock-OOS on, subject to the survivorship, rename and terminal-return gaps below.
- `9dbf1a205b56` **NO_HISTORICAL_QUOTES_NBBO**  .. — /v3/quotes and NBBO ticks are NOT_ENTITLED: no observed bid/ask/spread/depth. Spreads and opening-auction fills must be ASSUMED; the overnight/premarket-news track cannot validate execution realism. — status: **RESOLVED** ENTITLEMENT closed: Alpaca free SIP serves historical quotes and trades back to 2016 (verified on a stratified 11-session sample, dataset alpaca_sip_intraday_sample). Observed spreads are still NOT available for the research universe: see QUOTES_NBBO_NOT_MATERIALISED (opened below). Spreads remain ASSUMED in any experiment until then.
- `9676ac77713c` **NO_POINT_IN_TIME_FUNDAMENTALS**  .. — /vX/reference/financials returns HTTP 410 (deprecated); replacement income-statement endpoints are NOT_ENTITLED. Fundamentals must come from SEC EDGAR (acceptance timestamps), which is a different provider and must be declared, not substituted silently. — status: **OPEN** 
- `4ece3b95d505` **NEWS_HAS_NO_RECEIPT_TIMESTAMPS**  .. — Only publisher-side published_utc (minute resolution). No vendor/system receipt time, no revision history; 5 distinct publishers seen on one ticker/day. Latency assumptions are unavoidable and must be stress-tested. — status: **OPEN** 
- `84c79cb09927` **NO_BULK_EXPORT_PATH**  .. — No Massive API key exists in the execution environment; data is reachable only through the MCP connector (one bounded request at a time, rate-limited) and cannot be bulk-exported into local storage. The research dataset cannot be materialised for local backtesting. — status: **RESOLVED** RESOLVED for daily bars and reference data: keys present in the environment; REST bulk-ingested 14,521,836 daily bars (Alpaca), 11,948 security-master rows and the full splits table (Massive). NOT resolved for minute bars/ticks (see MINUTE_AND_TICK_HISTORY_NOT_MATERIALISED).
- `3e8515467789` **BARS_AFTER_DELISTING**  2021-08-04..2026-09-29 — 284 occurrence(s), 284 unit(s), 284 distinct ticker(s). Worst/examples: AAGR: bars until 2025-09-24 after delisting 2024-09-26; AATC: bars until 2025-03-21 after delisting 2022-12-30; ACER: bars until 2024-10-17 after delisting 2023-11-09; ADTX: bars until 2026-09-29 after delisting 2026-06-25; ADXS: bars until 2025-03-21 after delisting 2021-12-23; AFIB: bars until 2025-05-07 after delisting 2024-05-09 — status: **OPEN** 
- `3dec60b1f364` **MISSING_SESSION_LIQUID**  2016-09-14..2026-09-17 — 33 occurrence(s), 31792 unit(s), 33 distinct ticker(s). Worst/examples: MGN: 2271 consecutive session(s) without a bar (liquid name always trades -> provider gap); NCT: 2072 consecutive session(s) without a bar (liquid name always trades -> provider gap); HAWK: 1983 consecutive session(s) without a bar (liquid name always trades -> provider gap); JONE: 1951 consecutive session(s) without a bar (liquid name always trades -> provider gap); ITG: 1843 consecutive session(s) without a bar (liquid name always trades -> provider gap); KTWO: 1830 consecutive session(s) without a bar (liquid name always trades -> provider gap) — status: **OPEN** 
- `ae601a72adde` **MISSING_TAIL**  2016-04-04..2026-08-14 — 24 occurrence(s), 3524 unit(s), 24 distinct ticker(s). Worst/examples: TFG: last bar 2016-10-03 but delisted 2024-02-08 (1849 sessions without data); BABY: last bar 2019-07-25 but delisted 2023-03-09 (912 sessions without data); DSKX: last bar 2016-04-04 but delisted 2016-12-23 (185 sessions without data); CO: last bar 2022-09-23 but delisted 2023-06-08 (177 sessions without data); NTP: last bar 2022-05-23 but delisted 2022-11-18 (125 sessions without data); DGLT: last bar 2017-08-16 but delisted 2017-10-06 (36 sessions without data) — status: **OPEN** 
- `b71003d84970` **STALE_DAILY_PRICES**  .. — 364 occurrence(s), 54787 unit(s), 364 distinct ticker(s). Worst/examples: MBLY: 1297 consecutive identical flat daily bars in a liquid name; SN: 1119 consecutive identical flat daily bars in a liquid name; NRDY: 936 consecutive identical flat daily bars in a liquid name; AXAS: 913 consecutive identical flat daily bars in a liquid name; MEG: 885 consecutive identical flat daily bars in a liquid name; DJT: 872 consecutive identical flat daily bars in a liquid name — status: **OPEN** 
- `166eeea120dc` **ZERO_VOLUME_PLACEHOLDER_BARS**  .. — 544,945 bars (3.75%) across 3,718 tickers have volume 0; 544,945 are flat O=H=L=C and 544,881 equal the previous close, i.e. provider-side carry-forward of the last price on days with no trades. They are kept in the raw store, never used as prices or fills; a panel must mask them explicitly, and no-trade days for these names are otherwise indistinguishable from real bars. — status: **OPEN** 
- `e03589a7e0be` **DELISTING_RETURN_UNKNOWN**  2016-01-04..2026-09-29 — 4863 occurrence(s), 4863 unit(s), 4863 distinct ticker(s). Worst/examples: AABA: delisted 2019-10-07; terminal return/reason unknown (bankruptcy vs acquisition); it is NOT assumed to be 0; AACB: delisted 2026-08-20; terminal return/reason unknown (bankruptcy vs acquisition); it is NOT assumed to be 0; AACQ: delisted 2021-06-25; terminal return/reason unknown (bankruptcy vs acquisition); it is NOT assumed to be 0; AACT: delisted 2025-09-25; terminal return/reason unknown (bankruptcy vs acquisition); it is NOT assumed to be 0; AAGR: delisted 2024-09-26; terminal return/reason unknown (bankruptcy vs acquisition); it is NOT assumed to be 0; AAIC: delisted 2023-12-15; terminal return/reason unknown (bankruptcy vs acquisition); it is NOT assumed to be 0 — status: **OPEN** 
- `5b409b031d34` **SPLIT_NO_PRICE_DATA**  2016-01-04..2026-09-02 — 390 occurrence(s), 390 unit(s), 298 distinct ticker(s). Worst/examples: BURU: split on 2026-09-02 but no bars within ±4 days; IDXG: split on 2026-08-27 but no bars within ±4 days; ALCE: split on 2026-08-20 but no bars within ±4 days; GRTX: split on 2026-07-13 but no bars within ±4 days; CFNB: split on 2026-06-12 but no bars within ±4 days; ELOX: split on 2026-06-01 but no bars within ±4 days — status: **OPEN** 
- `4342e13eeb3e` **SPLIT_WITHOUT_DISCONTINUITY**  2016-01-05..2026-09-29 — 857 occurrence(s), 857 unit(s), 717 distinct ticker(s). Worst/examples: VRME: split 1-for-10 on 2026-09-29 not visible in prices (open/prev close=0.80..8.44): series may be adjusted, or a bar is missing; AGRZ: split 1-for-20 on 2026-09-29 not visible in prices (open/prev close=1.02..17.41): series may be adjusted, or a bar is missing; DLXY: split 1-for-5 on 2026-09-28 not visible in prices (open/prev close=0.95..6.10): series may be adjusted, or a bar is missing; DCX: split 1-for-160 on 2026-09-28 not visible in prices (open/prev close=0.83..125.71): series may be adjusted, or a bar is missing; BTLN: split 1-for-8 on 2026-09-28 not visible in prices (open/prev close=0.98..6.25): series may be adjusted, or a bar is missing; VSEE: split 1-for-80 on 2026-09-24 not visible in prices (open/prev close=1.00..1.00): series may be adjusted, or a bar is missing — status: **OPEN** 
- `8ecf6ed9bcdf` **UNRECORDED_SPLIT_LIKE_DISCONTINUITY**  2016-01-07..2026-09-29 — 3964 occurrence(s), 3964 unit(s), 2142 distinct ticker(s). Worst/examples: AABA 2019-09-24: open/prev close=0.273 with no recorded corporate action (matches a common split ratio); AAC 2021-03-25: open/prev close=20.729 with no recorded corporate action (matches a common split ratio); AAMC 2023-08-15: open/prev close=0.326 with no recorded corporate action (matches a common split ratio); AAN 2020-12-01: open/prev close=0.345 with no recorded corporate action (matches a common split ratio); AARD 2026-03-02: open/prev close=0.479 with no recorded corporate action (matches a common split ratio); ABEO 2024-04-23: open/prev close=0.518 with no recorded corporate action (matches a common split ratio) — status: **OPEN** 
- `fe0f9533db10` **SPLIT_TABLES_DISAGREE**  .. — 838 split(s) only in massive, 227 only in alpaca of 3944 distinct actions in 2016-01-01..2026-09-29 (27.0%); e.g. GPUS 2026-09-15 1.04067:1, METCB 2026-09-11 1.02563:1, HLSQ 2026-09-09 1:10, APD 2016-10-03 1081:1000, BF.A 2016-08-19 2:1, BF.B 2016-08-19 2:1. Neither table is preferred or merged. — status: **OPEN** 
- `f9dc315d8340` **RENAME_FEED_SPARSE**  2016-01-01..2019-12-31 — rename feed has 2016: 0, 2017: 2, 2018: 2, 2019: 53 events vs ~576/yr in well-covered years (first event 2017-04-10): renames in 2016..2019 are NOT observable, so ticker continuity there is unverified and the rename check cannot clear it — status: **OPEN** 
- `312f692e1491` **RENAME_HISTORY_BACKMAPPED**  2016-01-04..2026-09-28 — 222 occurrence(s), 222 unit(s), 211 distinct ticker(s). Worst/examples: 067BAS012->BNED on 2024-06-11: provider returns bars under 'BNED' from 2016-01-04, 3081 days BEFORE the rename, and '067BAS012' returns no bars at all: history ; 1ORIC->ORIC on 2025-02-19: provider returns bars under 'ORIC' from 2020-04-24, 1762 days BEFORE the rename, and '1ORIC' returns no bars at all: history is keyed; 23248B208->CXAI on 2023-09-19: provider returns bars under 'CXAI' from 2021-02-04, 957 days BEFORE the rename, and '23248B208' returns no bars at all: history i; AAN.WI->AAN on 2020-12-01: provider returns bars under 'AAN' from 2016-01-04, 1793 days BEFORE the rename, and 'AAN.WI' returns no bars at all: history is keyed; AAN.WI->AAN on 2020-12-03: provider returns bars under 'AAN' from 2016-01-04, 1795 days BEFORE the rename, and 'AAN.WI' returns no bars at all: history is keyed; AAXN->AXON on 2021-01-26: provider returns bars under 'AXON' from 2016-01-04, 1849 days BEFORE the rename, and 'AAXN' returns no bars at all: history is keyed b — status: **OPEN** 
- `052ab8b73687` **RENAME_WITH_PRICE_DISCONTINUITY**  2019-11-11..2026-09-11 — 158 occurrence(s), 158 unit(s), 155 distinct ticker(s). Worst/examples: 067BAS012->BNED on 2024-06-11: price jumps across the rename (open/prev close 0.90..74.76); possible different issuer under the same series or an unrecorded act; AAN.WI->AAN on 2020-12-01: price jumps across the rename (open/prev close 0.34..1.01); possible different issuer under the same series or an unrecorded action; AAN.WI->AAN on 2020-12-03: price jumps across the rename (open/prev close 0.34..1.01); possible different issuer under the same series or an unrecorded action; ABIO->ORKA on 2024-09-03: price jumps across the rename (open/prev close 0.95..10.62); possible different issuer under the same series or an unrecorded action; ACQC->BIOT on 2026-07-24: price jumps across the rename (open/prev close 0.57..0.72); possible different issuer under the same series or an unrecorded action; ADD->ZNB on 2025-08-22: price jumps across the rename (open/prev close 0.73..50.41); possible different issuer under the same series or an unrecorded action — status: **OPEN** 
- `b6a2dcb79c50` **SYMBOL_REUSED_ACROSS_ISSUERS**  2019-12-09..2026-09-14 — 180 occurrence(s), 180 unit(s), 180 distinct ticker(s). Worst/examples: 'AAMCF' was retired on 2025-11-24 (->AAMCD) and later assigned on 2025-12-23 (from AAMCD); CUSIPs differ (02153X108 vs 02153X306): bars keyed 'AAMCF' before 202; 'ABP' was retired on 2026-02-23 (->ABPO) and later assigned on 2024-11-13 (from ACAB); CUSIPs differ (000847202 vs 000847103): bars keyed 'ABP' before 2024-11-1; 'ACIC' was retired on 2021-09-17 (->ACHR) and later assigned on 2023-08-15 (from UIHC); CUSIPs differ (03945R102 vs 910710102): bars keyed 'ACIC' before 2023-08; 'AIKI' was retired on 2022-12-22 (->DOMH) and later assigned on 2020-03-16 (from SPEX); CUSIPs differ (008875304 vs 008875106): bars keyed 'AIKI' before 2020-03; 'AIM' was retired on 2025-04-07 (->AIMI) and later assigned on 2025-06-17 (from AIMID); CUSIPs differ (00901B105 vs 00901B303): bars keyed 'AIM' before 2025-06-; 'ALCE' was retired on 2025-09-05 (->ALCED) and later assigned on 2025-10-03 (from ALCED); CUSIPs differ (02157G200 vs 02157G309): bars keyed 'ALCE' before 2025- — status: **OPEN** 
- `28b832dfe714` **DELISTED_NAMES_NO_BARS**  2016-01-01..2026-09-29 — 276/4863 names the security master lists as delisted in 2016-01-01..2026-09-29 (5.7%) have NO bars from the provider (threshold 2%). The panel is survivorship-biased; by delist year: 2016: 209/230, 2017: 322/354, 2018: 307/343, 2019: 340/364, 2020: 313/339, 2021: 446/473, 2022: 501/518, 2023: 679/702, 2024: 550/569, 2025: 497/514, 2026: 423/457 — status: **OPEN** 
- `326b3633ee36` **BAR_PRESENT_IN_ONE_PROVIDER_ONLY**  .. — 1 occurrence(s), 146 unit(s), 0 distinct ticker(s). Worst/examples: 146 bars only in primary, 0 only in reference (22.64% of union): cannot tell which provider is complete — status: **OPEN** 
- `cdbceb6465cb` **MISSING_MINUTES_LIQUID**  2017-03-13T16:35:00+00:00..2022-06-09T18:09:00+00:00 — 28 occurrence(s), 139 unit(s), 3 distinct ticker(s). Worst/examples: ORLY 2020-03-16: 14 consecutive missing regular-session minutes from 13:31Z; AAPL 2020-03-16: 14 consecutive missing regular-session minutes from 13:31Z; META 2020-03-16: 14 consecutive missing regular-session minutes from 13:31Z; ORLY 2021-11-26: 7 consecutive missing regular-session minutes from 15:37Z; ORLY 2022-06-09: 7 consecutive missing regular-session minutes from 16:51Z; ORLY 2022-06-09: 7 consecutive missing regular-session minutes from 17:12Z — status: **OPEN** 
- `d459b7af9edd` **MINUTE_AND_TICK_HISTORY_NOT_MATERIALISED**  .. — Free tier allows ~150-200 requests/min and 10,000 rows/page. Measured universe: 14,521,836 symbol-sessions; minute bars ~5.2bn rows (~2 days of continuous pulling); trades (sum of daily bar trade counts) ~144bn rows (~0 years of continuous pulling); free disk ~30 GB. Only a stratified sample (11 sessions x 4 tickers minute bars; 2-minute trade/quote windows at the open for 2 tickers) is on disk. Minute-level experiments must be scoped to an explicitly chosen subset of tickers/sessions, declared per experiment; full-universe minute/tick research is infeasible on this tier. — status: **RESOLVED** SUPERSEDED BY CORRECTION (not a fix of the data gap): this entry's sizing text was wrong (unit error; unrepresentative extrapolation). The same gap is restated with measured bounds as f89d81a0d721, which is OPEN.
- `b93e856d2909` **QUOTES_NBBO_NOT_MATERIALISED**  .. — Historical SIP quotes are accessible but only sampled (2 minutes at the open, 2 tickers, 11 sessions). No observed-spread series exists for the universe; execution-realism for the overnight/premarket track still rests on assumed spreads. Measured: AAPL, first 2 min of the open, 11 sessions: bid and ask venues differ in 68%-84% of quotes (consolidated-style stream; not proven to be the official NBBO); crossed quotes 0.00%-0.60%; median spread 1.1-8.7 bps. Crossed rows must be excluded explicitly before any spread is used. — status: **OPEN** 
- `f89d81a0d721` **MINUTE_AND_TICK_HISTORY_NOT_MATERIALISED**  2016-01-01..2026-09-29 — Not on disk: only a stratified sample (11 sessions x 4 tickers of minute bars; 2-minute trade/quote windows at the open for 2 tickers). Measured bounds for the 14,521,836 symbol-sessions in the daily universe: MINUTE bars <= 10.3bn rows (upper bound = sum of min(daily trade count, 960); the true count is lower and NOT measured) = <= 435 GB at the measured 42.1 B/row and <= 4.8 days of pulling at 150 req/min x 10k rows, versus 30.9 GB free: it fits only if the true row count is < 7% of the bound (unmeasured; a stream-and-discard design would avoid storage). TRADES = 144bn rows exactly (sum of daily trade counts) = ~67 days of pulling and ~2.2 TB: not feasible on this tier. Minute-level experiments must be scoped to an explicit ticker/session subset declared per experiment; tick-level research on the full universe is not possible. — status: **OPEN** 

## Provider notes / limitations

- PRIMARY price source: Alpaca free Market Data API, feed=sip, adjustment=raw, historical-only (end >= 15 min ago). Daily t = 00:00 America/New_York; minute t = window start UTC.
- Massive free tier (5 req/min; aggregates entitled only for ~2 years; bearer-header auth): splits, reference tickers (incl. delisted), cross-validation ONLY.
- Alpaca history is keyed by the CURRENT symbol (e.g. FB returns nothing; META returns Facebook from 2016): join on a permanent identifier (FIGI) with an effective-dated ticker map, not on the ticker.
- Bars are omitted for empty intervals; illiquid-name gaps are therefore AMBIGUOUS by construction.
- Other reachable sources (SEC EDGAR, FRED, Nasdaq Trader symbol directory, Yahoo chart API) are still not ingested; using any of them for prices would be a provider substitution and must be declared per experiment.

## Interpretation of the measurements (what the numbers do and do not show)

**Alpaca `adjustment=raw` is unadjusted.** Verified on known splits: ORLY 15:1 (1348.10 -> 91.71), NVDA 10:1 (1208.88 -> 121.79), AAPL 4:1 (499.23 -> 129.04), TSLA 3:1 (891.29 -> 296.07). Prices are therefore comparable to Massive `adjusted=false` and splits must be applied by us from a splits table.

**Cross-provider daily bars (Alpaca vs Massive, 12,100 overlapping bars, 25 tickers, sample only).** 120 bars differ by >0.5% in close; {'ASNS': 117, 'CDT': 1, 'TRUG': 1, 'VRME': 1}. Of those, 117 are Alpaca zero-volume placeholder bars (last price carried forward) while Massive shows positive volume; cause not determined. The remaining {ma.get('rows_mismatching_close', 0) - ma.get('of_which_alpaca_volume_zero', 0)} are in tickers that were sampled for having a split in the window and were not individually attributed. The two providers are not reconciled or averaged.

**Minute bars (AAPL 2025-07-03, Alpaca vs Massive).** All 499 common bars have identical OHLC (0 mismatches) and volume within 0.2%. The 146 bars present only in Alpaca are all extended-hours: the regular session is 210/210 in both (Massive: 210 regular + 250 pre + 39 post = 499 from the earlier provider-side check; Alpaca: 645 = 210 regular + 435 extended).

**Zero-volume placeholder bars.** 544,945 bars (3.75%) in 3,718 tickers; 544,881 equal the previous close. 552 runs of >=60 consecutive placeholder sessions (e.g. LINE 2016-05-24..2024-07-24 (2055 sessions); GRO 2016-11-03..2024-11-26 (2029 sessions); CAPN 2017-05-12..2024-10-23 (1875 sessions)) are stretches with no trades for years after which real trading resumes (consistent with a delisting followed by ticker re-use, or a very long halt); runs are not individually attributed. Consequence: never derive `alive` from bar existence; use volume > 0. Because placeholders stand in for no-trade days, the session-gap check under-reports missing bars for illiquid names.

**Delisted-name coverage.** 4,587/4,863 delisted names have bars (94.3%); tolerance is 98%. Coverage by delisting year: 2016: 91%, 2017: 91%, 2018: 90%, 2019: 93%, 2020: 92%, 2021: 94%, 2022: 97%, 2023: 97%, 2024: 97%, 2025: 97%, 2026: 93%. Coverage is lowest for 2016-2018 delistings (~90-91%) and highest for 2022-2025 (~97%). Names without bars are listed in data/audit/delisted_names_without_bars.csv (276 rows). 24 further names have bars that stop >5 sessions before delisting.

**Splits.** Massive and Alpaca agree on 2,875 splits; 838 appear only in Massive and 227 only in Alpaca. Restricted to integer-ratio splits the disagreement is 522 / 177 of 3,252 / 2,910; Massive additionally lists 462 fractional-ratio events (ratios that are not integers or reciprocals of integers) vs 196 in Alpaca. Neither table is treated as truth. Recorded splits confirmed in the price data: 2,466 of 3,713 in-universe as-of splits.

**Ticker renames.** The rename feed is unusable before 2019 ({2016: 0, 2017: 2, 2018: 2, 2019: 53, 2020: 304, 2021: 576, 2022: 399, 2023: 500, 2024: 700, 2025: 670, 2026: 461}). Of 1,489 renames that could be checked, 222 show the old symbol dark and history back-mapped onto the new one, 977 have prior history under both symbols (ambiguous), and 180 symbols were re-used by a different issuer. A ticker is not an identity: join on FIGI/CUSIP with an effective-dated ticker map.

## Discovery gate

**Gate: BLOCKED**

- dataset 'daily_bars': coverage incomplete (344 requested symbols returned no bars; delisted missing 5.7% (tolerance 2%): survivorship-biased)
- dataset 'minute_bars': coverage incomplete (sample only; full-universe minute history is not on disk (measured size bounds in gap MINUTE_AND_TICK_HISTORY_NOT_MATERIALISED))
- dataset 'news': coverage incomplete (sample only; no receipt timestamps (unchanged))
- dataset 'corporate_actions': coverage incomplete (splits cross-checked between providers; terminal/delisting returns unknown; dividends not price-validated)
- dataset 'security_master_incl_delisted': coverage incomplete (no list dates; 201 inactive names lack delisted_utc; ticker reuse/rename history incomplete)
- dataset 'quotes_nbbo': coverage incomplete (entitled but sample only; AAPL, first 2 min of the open, 11 sessions: bid and ask venues differ in 68%-84% of quotes (consolidated-style stream; not proven to be the official NBBO); crossed quotes 0.00%-0.60%; median spread 1.1-8.7 bps.)
- OPEN material gap 8656ad608dd5 [NO_VENDOR_RECEIPT_TS]  : dataset has no vendor_receipt_ts: true availability time of each article is unknown; a lat
- OPEN material gap b02630318686 [NO_SYSTEM_RECEIPT_TS]  : dataset has no system_receipt_ts: true availability time of each article is unknown; a lat
- OPEN material gap 9676ac77713c [NO_POINT_IN_TIME_FUNDAMENTALS]  : /vX/reference/financials returns HTTP 410 (deprecated); replacement income-statement endpo
- OPEN material gap 4ece3b95d505 [NEWS_HAS_NO_RECEIPT_TIMESTAMPS]  : Only publisher-side published_utc (minute resolution). No vendor/system receipt time, no r
- OPEN material gap 3e8515467789 [BARS_AFTER_DELISTING]  2021-08-04: 284 occurrence(s), 284 unit(s), 284 distinct ticker(s). Worst/examples: AAGR: bars until 2
- OPEN material gap 3dec60b1f364 [MISSING_SESSION_LIQUID]  2016-09-14: 33 occurrence(s), 31792 unit(s), 33 distinct ticker(s). Worst/examples: MGN: 2271 consecut
- OPEN material gap ae601a72adde [MISSING_TAIL]  2016-04-04: 24 occurrence(s), 3524 unit(s), 24 distinct ticker(s). Worst/examples: TFG: last bar 2016-
- OPEN material gap b71003d84970 [STALE_DAILY_PRICES]  : 364 occurrence(s), 54787 unit(s), 364 distinct ticker(s). Worst/examples: MBLY: 1297 conse
- OPEN material gap 166eeea120dc [ZERO_VOLUME_PLACEHOLDER_BARS]  : 544,945 bars (3.75%) across 3,718 tickers have volume 0; 544,945 are flat O=H=L=C and 544,
- OPEN material gap e03589a7e0be [DELISTING_RETURN_UNKNOWN]  2016-01-04: 4863 occurrence(s), 4863 unit(s), 4863 distinct ticker(s). Worst/examples: AABA: delisted 
- OPEN material gap 5b409b031d34 [SPLIT_NO_PRICE_DATA]  2016-01-04: 390 occurrence(s), 390 unit(s), 298 distinct ticker(s). Worst/examples: BURU: split on 202
- OPEN material gap 4342e13eeb3e [SPLIT_WITHOUT_DISCONTINUITY]  2016-01-05: 857 occurrence(s), 857 unit(s), 717 distinct ticker(s). Worst/examples: VRME: split 1-for-
- OPEN material gap 8ecf6ed9bcdf [UNRECORDED_SPLIT_LIKE_DISCONTINUITY]  2016-01-07: 3964 occurrence(s), 3964 unit(s), 2142 distinct ticker(s). Worst/examples: AABA 2019-09-24
- OPEN material gap fe0f9533db10 [SPLIT_TABLES_DISAGREE]  : 838 split(s) only in massive, 227 only in alpaca of 3944 distinct actions in 2016-01-01..2
- OPEN material gap f9dc315d8340 [RENAME_FEED_SPARSE]  2016-01-01: rename feed has 2016: 0, 2017: 2, 2018: 2, 2019: 53 events vs ~576/yr in well-covered year
- OPEN material gap 312f692e1491 [RENAME_HISTORY_BACKMAPPED]  2016-01-04: 222 occurrence(s), 222 unit(s), 211 distinct ticker(s). Worst/examples: 067BAS012->BNED on
- OPEN material gap 052ab8b73687 [RENAME_WITH_PRICE_DISCONTINUITY]  2019-11-11: 158 occurrence(s), 158 unit(s), 155 distinct ticker(s). Worst/examples: 067BAS012->BNED on
- OPEN material gap b6a2dcb79c50 [SYMBOL_REUSED_ACROSS_ISSUERS]  2019-12-09: 180 occurrence(s), 180 unit(s), 180 distinct ticker(s). Worst/examples: 'AAMCF' was retire
- OPEN material gap 28b832dfe714 [DELISTED_NAMES_NO_BARS]  2016-01-01: 276/4863 names the security master lists as delisted in 2016-01-01..2026-09-29 (5.7%) have
- OPEN material gap 326b3633ee36 [BAR_PRESENT_IN_ONE_PROVIDER_ONLY]  : 1 occurrence(s), 146 unit(s), 0 distinct ticker(s). Worst/examples: 146 bars only in prima
- OPEN material gap cdbceb6465cb [MISSING_MINUTES_LIQUID]  2017-03-13T16:35:00+00:00: 28 occurrence(s), 139 unit(s), 3 distinct ticker(s). Worst/examples: ORLY 2020-03-16: 14 c
- OPEN material gap b93e856d2909 [QUOTES_NBBO_NOT_MATERIALISED]  : Historical SIP quotes are accessible but only sampled (2 minutes at the open, 2 tickers, 1
- OPEN material gap f89d81a0d721 [MINUTE_AND_TICK_HISTORY_NOT_MATERIALISED]  2016-01-01: Not on disk: only a stratified sample (11 sessions x 4 tickers of minute bars; 2-minute tr