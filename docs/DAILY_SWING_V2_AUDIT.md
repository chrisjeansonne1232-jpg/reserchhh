# DAILY_SWING_V2 audit (status as of 2026-09-30 13:06 UTC)

**Gate: OPEN**  |  frozen spec `3f0611ef0d58f4e7...` (registry seq 85) | window 2019-01-01..2026-09-29 | data `dsv2_panel_0d20f42a_3f0611ef`

This audit does **not** start strategy discovery. The existing gate (`overnight_news_open_to_close`) is untouched.

## Requirements

| id | requirement | comparison | measured | result | detail |
|---|---|---|---|---|---|
| R1 | Scope integrity: every panel cell has volume > 0; only CS instruments; window as declared | violations == 0 | 0 | **PASS** | member cells with volume<=0: 0; member cells of spells not in the CS master: 0 (spells outside the master: ['GEW', 'IBMW', 'METW'], returned by Alpaca though not requested); member cells before the window: 0; placeholder bars set aside (never cells): 544,945 |
| R2a | No market-wide missing or partial XNYS session in the window | sessions == 0 | 0 | **PASS** | 1946 sessions; median real bars/session 5353; min 4683; sessions below 50% of the median: 0 |
| R2b | Member cells without a real bar (halts, provider drops), share of member cells | share <= 0.005 | 0.0917% | **PASS** | 1,728 of 1,883,548 member cells have no real bar |
| R2c | Worst single session: share of that day's members without a real bar | share <= 0.05 | 0.5192% | **PASS** | worst session 2022-04-11: 0.52% |
| R3 | Structural validity of member cells: OHLC ordering, positive prices, duplicate (ticker, date) keys | violations == 0 | 0 | **PASS** | 1,881,820 member cells checked; duplicate (ticker,session) keys in the whole store: 0 |
| R4a | Every disputed split event (window, all names) has a verdict; none is left unclassified | unclassified == 0 | 0 | **PASS** | 3141 claims in the window ({'both': 2516, 'massive': 509, 'alpaca': 116}); every claim has a verdict |
| R4b | After exclusions, member cells within a still-AMBIGUOUS split or unrecorded discontinuity | cells == 0 | 0 | **PASS** | unrecorded split-like jumps: 52; ambiguous split events excluded: 1612; agreed, untestable-small, accepted as corroborated-but-unverified: 14 |
| R4c | Member cells removed by split/discontinuity exclusions, share of member cells | share <= 0.05 | 2.5952% | **PASS** | 50,503 of 1,946,000 member cells removed; 126 of 2135 member spells affected |
| R5a | Point-in-time: membership recomputed from data truncated at random cut sessions equals the full-data membership at every session <= cut | differences == 0 | 0 | **PASS** | cuts at sessions ['2023-03-27', '2024-02-16', '2025-08-26']; membership rebuilt from data truncated at the cut vs full data, compared on every session <= cut |
| R5b | Universe size (after exclusions) is at least 800 on at least 99% of window sessions | share_of_sessions >= 0.99 | 1.0000 | **PASS** | universe size after exclusions: min 950, median 966, share of sessions >= 800: 1.0000 |
| R6a | No member cell's lookback window spans two spells | cells == 0 | 0 | **PASS** | 296 tickers have more than one spell; member cells whose 60-session lookback holds a bar of another spell of the same ticker: 0 |
| R6b | No return is computed across a spell boundary (returns are undefined at a spell's first bar) | returns == 0 | 0 | **PASS** | returns are computed inside a spell only: a spell's first bar has no predecessor in its column |
| R6c | Independent timeline cross-check: unmasked member cells whose 60-session lookback (plus the cell itself) covers more than one issuer label, or an ambiguous hand-over window | cells == 0 | 0 | **PASS** | 375 hand-over boundaries from 165,902 observations ({'cik': 374, 'figi_fallback': 1}); 0 unmasked member cells see more than one issuer label or an ambiguous window (checked 58,352 member cells of tickers with a boundary; the same check WITHOUT the identity mask finds 11,949) |
| R6d | Identity mask: share of raw (ranked) member cells removed by the ticker hand-over mask | share <= 0.03 | 0.6373% | **PASS** | 12,402 of 1,946,000 raw member cells masked: 9,518 inside ambiguity windows (bounded look-ahead part), 3,061 in the causal tail |
| R7a | Cross-provider (Alpaca vs Massive, unadjusted, sample of universe members >= 25 names, >= 5000 bars): share of bars whose close differs by > 0.5% | share <= 0.005 | 0.0000% | **PASS** | 20,000 overlapping bars, 40 names (2024-10-01..2026-09-29); bars only in Alpaca: 0; only in Massive: 0 |
| R7b | Cross-provider: no sampled name has more than 5% of its bars mismatching | share <= 0.05 | 0.0000% | **PASS** | worst name: AFRM 0.00% |
| R8 | Residual survivorship bias is quantified (missing listed names via point-in-time listings, expected liquid share, terminal-return exposure) and recorded as a known limitation | recorded == True | True | **PASS** | see 'Residual survivorship' section |
| R9 | Every MATERIAL gap in the ledger has a DAILY_SWING_V2 disposition backed by scope evidence: RESOLVED, EXCLUDED (scope), or an accepted limitation. None is left undispositioned. | undispositioned == 0 | 0 | **PASS** | 23 dispositioned; 0 not |

Notes on the measurements: **R7** compares two vendors that both deliver consolidated SIP prints (closes are bit-identical on 100% of the sampled bars; volume is identical on about two thirds), so it validates the data path, not an independent price source. The point-in-time test (R5a) is run on the real data at three random cut dates; the rest of the universe logic is covered by unit tests with planted defects.

## Why the gate is open

- every requirement passed and no gap is undispositioned

## Point-in-time universe

Top 1000 by trailing 60-session median dollar volume (>= 50 real bars, last close >= $5), membership for session t computed from sessions < t only; exclusions applied afterwards.

| index | sessions | universe_min | universe_median | split_exclusions_share | identity_mask_share |
|---|---|---|---|---|---|
| 2019 | 252 | 988 | 991 | 0.0032 | 0.0058 |
| 2020 | 253 | 966 | 973 | 0.0185 | 0.0064 |
| 2021 | 252 | 963 | 966 | 0.0279 | 0.0071 |
| 2022 | 251 | 959 | 964 | 0.0276 | 0.0091 |
| 2023 | 250 | 962 | 966 | 0.0273 | 0.0058 |
| 2024 | 252 | 962 | 966 | 0.0278 | 0.0061 |
| 2025 | 250 | 952 | 957 | 0.0381 | 0.0051 |
| 2026 | 186 | 950 | 953 | 0.0413 | 0.0053 |

Spells: 10,363 (10,043 tickers; 296 with more than one spell). Placeholder bars set aside: 544,945. Ever-member spells (window): 2,135.

## Empirical split resolution

3141 claims in the window: {'both': 2516, 'massive': 509, 'alpaca': 116} ('both' = agreed by Massive and Alpaca; single-source claims are the **disputed** events). 3120 events after clustering claims within 4 sessions.

All events:

| disputed | verdict | action | events |
|---|---|---|---|
| False | AMBIGUOUS | ACCEPT_CORROBORATED_UNVERIFIED | 14 |
| False | AMBIGUOUS | EXCLUDE_SPELL | 1287 |
| False | CONFIRMED | ADJUST | 1013 |
| False | NO_PRICE_DATA | NONE | 134 |
| False | REFUTED | NONE | 63 |
| True | AMBIGUOUS | EXCLUDE_SPELL | 325 |
| True | CONFIRMED | ADJUST | 80 |
| True | NO_PRICE_DATA | NONE | 137 |
| True | REFUTED | NONE | 67 |

Events touching a spell that was ever a universe member:

| disputed | verdict | action | events_touching_a_member_spell |
|---|---|---|---|
| False | AMBIGUOUS | ACCEPT_CORROBORATED_UNVERIFIED | 9 |
| False | AMBIGUOUS | EXCLUDE_SPELL | 53 |
| False | CONFIRMED | ADJUST | 169 |
| False | REFUTED | NONE | 3 |
| True | AMBIGUOUS | EXCLUDE_SPELL | 62 |
| True | CONFIRMED | ADJUST | 14 |
| True | REFUTED | NONE | 6 |

Disputed events: 609. Testable from prices: 442; verdicts {'AMBIGUOUS': 158, 'NO_PRICE_DATA': 137, 'CONFIRMED': 80, 'REFUTED': 67}. Untestable (claimed adjustment below |ln m| = 0.3): 167. **Who was right** when prices decided a single-source claim: CONFIRMED {'massive': 51, 'alpaca': 24, 'alpaca+both': 3, 'alpaca+massive': 2}, REFUTED {'massive': 54, 'alpaca': 13}: neither provider's table is reliable on its own.

Unrecorded overnight discontinuities among raw member cells: {'LARGE_MOVE_NOT_SPLIT_LIKE': 169, 'SPLIT_LIKE_BUT_GENUINE_MOVE_DV_SPIKE': 133, 'COVERED_BY_CLAIM': 106, 'UNRECORDED_SPLIT_LIKE': 52}. Full tables in `data/audit/daily_swing_v2/`.

## Residual survivorship (KNOWN LIMITATION, authorised; quantified, not a blocker)

**A. Names listed (point-in-time) but with no bars.** {"median_missing_share": 0.0127, "range_missing_share": [0.0042, 0.1094], "median_expected_missing_members_point": 11.0, "range_expected": [3.0, 187.7], "median_upper_bound_missing_members": 74, "lower_bound": 0, "median_p_member_given_bars": 0.19, "universe_size": 1000, "point_estimate_share_of_universe": 0.011, "outlier_snapshots": ["2019-07-01"], "assumption": "missing names are as likely to be liquid as names with bars on the same exchange/date (upper-leaning: illiquid names are the ones that lack bars); the upper bound counts every missing name"}

**B. Terminal returns of members that stop trading.** {"member_spells_ended": 487, "of_which_master_inactive": 477, "annual_hazard_of_a_member_stopping_trading": {"2019": 0.0475, "2020": 0.0527, "2021": 0.0589, "2022": 0.0692, "2023": 0.0651, "2024": 0.0651, "2025": 0.0796, "2026": 0.062}, "mean_annual_hazard": 0.0625, "observed_final_20_session_raw_log_return_quantiles": {"0.1": -0.283, "0.25": -0.033, "0.5": 0.006, "0.75": 0.03, "0.9": 0.11}, "sensitivity_annual_drag_bps_of_an_always_invested_equal_weight_book_if_unobserved_terminal_return_were": {"-30%": -187.5, "-60%": -375.0, "-100%": -625.1}, "note": "the return from the last observed bar to the end of the security (cash-out, distressed exit, delisting) is not observed for any of these; the sensitivity is arithmetic, not an estimate"}

**C. What the exclusions removed (composition only).** {"excluded_member_spells_distinct": 126, "exclusion_events_touching_member_spells": 167, "share_of_member_spells": 0.059, "cause_of_each_spells_earliest_exclusion": {"UNRECORDED_SPLIT_LIKE_DISCONTINUITY": 46, "AGREED_SPLIT_TESTABLE_AMBIGUOUS": 43, "DISPUTED_SPLIT_AMBIGUOUS": 37}, "exclusion_events_by_cause": {"DISPUTED_SPLIT_AMBIGUOUS": 62, "AGREED_SPLIT_TESTABLE_AMBIGUOUS": 53, "UNRECORDED_SPLIT_LIKE_DISCONTINUITY": 52}, "member_cells_removed_share": 0.026, "share_of_excluded_spells_that_later_stop_trading": 0.254, "same_share_for_all_member_spells": 0.232, "median_prior_60_session_raw_log_return_at_exclusion": -0.057, "n_prior": 126, "note": "exclusions remove names from the moment the data becomes ambiguous; this is a composition change, direction of the return bias NOT measured"}

**D. Identity fix (V2's one change).** {"observations": {"observations": 165902, "comparisons": 155784, "boundaries": 375, "observations_with_no_key_skipped": 257, "boundaries_by_key_type": {"cik": 374, "figi_fallback": 1}, "tickers_with_a_boundary": 327}, "ever_member_spells_with_masked_cells": 73, "raw_member_cells_masked": 12402, "share_of_raw_member_cells": 0.0064, "of_which_ambiguity_window_bounded_lookahead": 9518, "of_which_causal_tail": 3061, "timeline_cross_check_violations": 0, "timeline_cross_check_violations_without_the_mask": 11949, "member_cells_of_boundary_tickers_checked": 58352, "v1_figi_glued_member_spells": 91, "v1_figi_glued_member_spells_whose_ticker_has_a_cik_boundary": 47, "v1_figi_glued_member_spells_same_issuer_figi_churn_not_masked": 44, "examples_masked_hand_overs": [{"ticker": "AHT", "before": "Ashford Hospitality Trust, Inc.", "after": "Ashford Hospitality Trust, Inc.", "d1": "2020-07-01", "d2": "2020-10-01"}, {"ticker": "AHT", "before": "Ashford Hospitality Trust, Inc.", "after": "Ashford Hospitality Trust, Inc.", "d1": "2021-07-01", "d2": "2021-10-01"}, {"ticker": "AI", "before": "Arlington Asset Investment Corp.", "after": "C3.ai, Inc.", "d1": "2020-10-01", "d2": "2021-01-04"}, {"ticker": "AM", "before": "ANTERO MIDSTREAM PARTNERS LP", "after": "Antero Midstream Corporation", "d1": "2019-01-02", "d2": "2019-04-01"}, {"ticker": "APA", "before": "Apache Corporation", "after": "APA Corporation Common Stock", "d1": "2021-01-04", "d2": "2021-04-01"}, {"ticker": "APC", "before": "Anadarko Petroleum", "after": "ARKO Petroleum Corp. Class A Common Stock", "d1": "2019-07-01", "d2": "2026-04-01"}, {"ticker": "APO", "before": "Apollo Global Management, Inc.", "after": "Apollo Global Management, Inc.", "d1": "2021-10-01", "d2": "2022-01-03"}, {"ticker": "ARNC", "before": "Arconic Inc", "after": "Arconic Corporation", "d1": "2020-01-02", "d2": "2020-04-01"}, {"ticker": "ARRY", "before": "Array Biopharma Inc", "after": "Array Technologies, Inc. Common Stock", "d1": "2019-07-01", "d2": "2021-01-04"}, {"ticker": "ATHN", "before": "Athenahealth, Inc.", "after": "Athena Technology Acquisition Corp.", "d1": "2019-01-02", "d2": "2021-07-01"}], "not_detected": ["Ticker hand-overs are detectable only at quarterly resolution from 2019-01-02 (plus the current master): hand-overs before that, or reversed within one quarter, or between observations that share no key, are not detected", "A CIK change with a continuing business (e.g. a holding-company reorganisation) is treated as a hand-over (conservative); a hand-over that keeps the CIK is not detected", "The identity mask has a bounded look-ahead (at most one quarter, only for names with an identity event): cells in the ambiguity window (s1, s2) are removed although the change is observable only at s2"]}

**E. Instrument mix: Massive's `CS` is not pure US common stock.** {"ever_member_spells": 2135, "name_matches_ads_or_fund": 0, "share_of_spells": 0.0, "share_of_member_cells": 0.0, "examples": [], "method": "case-insensitive name match on American Depositary|\\bADS\\b|\\bADR\\b|\\bFund\\b|\\bFd\\b|Closed[- ]End|\\bETF\\b|\\bETN\\b (heuristic: neither exhaustive nor exact)"}

Not quantified: names whose Massive type changed; provider-side omission of names that were never listed in Massive's PIT snapshots.

## Gap dispositions for DAILY_SWING_V2 (recorded as gate-tagged registry events; the existing gate's ledger view is unchanged)

| gap | kind | result | evidence |
|---|---|---|---|
| `8656ad608dd5` | NO_VENDOR_RECEIPT_TS | EXCLUDED for DAILY_SWING_V2 | not an input of DAILY_SWING_V2 (SPEC scope.not_used); the panel is built from daily bars only |
| `b02630318686` | NO_SYSTEM_RECEIPT_TS | EXCLUDED for DAILY_SWING_V2 | not an input of DAILY_SWING_V2 (SPEC scope.not_used); the panel is built from daily bars only |
| `9676ac77713c` | NO_POINT_IN_TIME_FUNDAMENTALS | EXCLUDED for DAILY_SWING_V2 | not an input of DAILY_SWING_V2 (SPEC scope.not_used); the panel is built from daily bars only |
| `4ece3b95d505` | NEWS_HAS_NO_RECEIPT_TIMESTAMPS | EXCLUDED for DAILY_SWING_V2 | not an input of DAILY_SWING_V2 (SPEC scope.not_used); the panel is built from daily bars only |
| `3e8515467789` | BARS_AFTER_DELISTING | EXCLUDED for DAILY_SWING_V2 | member cells WITH a real bar more than 3 days after a master delisting date: 0 (member cells without a bar shortly after a stock's last bar are the no-look-ahead lag, counted in R2b and masked) |
| `3dec60b1f364` | MISSING_SESSION_LIQUID | EXCLUDED for DAILY_SWING_V2 | R2b=0.0917%, R2c=0.52% on member cells; missing member cells are masked, never filled |
| `ae601a72adde` | MISSING_TAIL | EXCLUDED for DAILY_SWING_V2 | ACCEPTED LIMITATION: component of SURVIVORSHIP_RESIDUAL_DAILY_SWING_V1 (authorised by the requester), quantified there. Not resolved. |
| `b71003d84970` | STALE_DAILY_PRICES | EXCLUDED for DAILY_SWING_V2 | member-panel flat-bar runs (check_stale_daily on 1,881,820 member cells): 0 |
| `166eeea120dc` | ZERO_VOLUME_PLACEHOLDER_BARS | EXCLUDED for DAILY_SWING_V2 | member cells with volume<=0: 0 (R1); 544,945 placeholder bars were set aside and are never cells |
| `e03589a7e0be` | DELISTING_RETURN_UNKNOWN | EXCLUDED for DAILY_SWING_V2 | ACCEPTED LIMITATION: component of SURVIVORSHIP_RESIDUAL_DAILY_SWING_V1 (authorised by the requester), quantified there. Not resolved. |
| `5b409b031d34` | SPLIT_NO_PRICE_DATA | EXCLUDED for DAILY_SWING_V2 | claims with no real bar within +-4 sessions that touch a member cell: 0 |
| `4342e13eeb3e` | SPLIT_WITHOUT_DISCONTINUITY | EXCLUDED for DAILY_SWING_V2 | R4a=0, R4b=0; disputed events: 609 (confirmed 80, refuted 67, ambiguous->spell excluded 325, no price data 137) |
| `8ecf6ed9bcdf` | UNRECORDED_SPLIT_LIKE_DISCONTINUITY | EXCLUDED for DAILY_SWING_V2 | R4a=0, R4b=0; disputed events: 609 (confirmed 80, refuted 67, ambiguous->spell excluded 325, no price data 137) |
| `fe0f9533db10` | SPLIT_TABLES_DISAGREE | EXCLUDED for DAILY_SWING_V2 | R4a=0, R4b=0; disputed events: 609 (confirmed 80, refuted 67, ambiguous->spell excluded 325, no price data 137) |
| `f9dc315d8340` | RENAME_FEED_SPARSE | EXCLUDED for DAILY_SWING_V2 | R6a=0, R6b=0, R6c=0, R4b=0; 375 issuer hand-over boundaries applied as a mask (0.64% of raw member cells); rename events in the window touching a member name: 51. Residual (declared): hand-overs are detectable only at quarterly resolution from 2019-01-02 plus the current master; earlier, intra-quarter-reversed or keyless ones are not detected; NB the rename feed is sparse in 2019 (in the window): identity rests on PIT listings and bars, not on rename events |
| `312f692e1491` | RENAME_HISTORY_BACKMAPPED | EXCLUDED for DAILY_SWING_V2 | R6a=0, R6b=0, R6c=0, R4b=0; 375 issuer hand-over boundaries applied as a mask (0.64% of raw member cells); rename events in the window touching a member name: 51. Residual (declared): hand-overs are detectable only at quarterly resolution from 2019-01-02 plus the current master; earlier, intra-quarter-reversed or keyless ones are not detected |
| `052ab8b73687` | RENAME_WITH_PRICE_DISCONTINUITY | EXCLUDED for DAILY_SWING_V2 | R6a=0, R6b=0, R6c=0, R4b=0; 375 issuer hand-over boundaries applied as a mask (0.64% of raw member cells); rename events in the window touching a member name: 51. Residual (declared): hand-overs are detectable only at quarterly resolution from 2019-01-02 plus the current master; earlier, intra-quarter-reversed or keyless ones are not detected |
| `b6a2dcb79c50` | SYMBOL_REUSED_ACROSS_ISSUERS | EXCLUDED for DAILY_SWING_V2 | R6a=0, R6b=0, R6c=0, R4b=0; 375 issuer hand-over boundaries applied as a mask (0.64% of raw member cells); rename events in the window touching a member name: 51. Residual (declared): hand-overs are detectable only at quarterly resolution from 2019-01-02 plus the current master; earlier, intra-quarter-reversed or keyless ones are not detected |
| `28b832dfe714` | DELISTED_NAMES_NO_BARS | EXCLUDED for DAILY_SWING_V2 | ACCEPTED LIMITATION: component of SURVIVORSHIP_RESIDUAL_DAILY_SWING_V1 (authorised by the requester), quantified there. Not resolved. |
| `326b3633ee36` | BAR_PRESENT_IN_ONE_PROVIDER_ONLY | EXCLUDED for DAILY_SWING_V2 | not an input of DAILY_SWING_V2 (SPEC scope.not_used); the panel is built from daily bars only (this MATERIAL entry is the minute-bar comparison) |
| `cdbceb6465cb` | MISSING_MINUTES_LIQUID | EXCLUDED for DAILY_SWING_V2 | not an input of DAILY_SWING_V2 (SPEC scope.not_used); the panel is built from daily bars only |
| `b93e856d2909` | QUOTES_NBBO_NOT_MATERIALISED | EXCLUDED for DAILY_SWING_V2 | not an input of DAILY_SWING_V2 (SPEC scope.not_used); the panel is built from daily bars only; execution costs are assumed (SPEC scope.execution_costs) |
| `f89d81a0d721` | MINUTE_AND_TICK_HISTORY_NOT_MATERIALISED | EXCLUDED for DAILY_SWING_V2 | not an input of DAILY_SWING_V2 (SPEC scope.not_used); the panel is built from daily bars only; execution costs are assumed (SPEC scope.execution_costs) |

## Declared limitations (not gated)

- Alpaca is the only price source before 2024-10 (Massive aggregates cover ~2 years): cross-validation exists for the recent window only
- Execution costs are assumed, not observed
- The two providers' split tables are not independent of each other; agreement is corroboration, not proof
- Instrument type (CS) is taken from today's master; names whose type changed are misclassified
- Ticker hand-overs are detectable only at quarterly resolution from 2019-01-02 (plus the current master): hand-overs before that, or reversed within one quarter, or between observations that share no key, are not detected
- A CIK change with a continuing business (e.g. a holding-company reorganisation) is treated as a hand-over (conservative); a hand-over that keeps the CIK is not detected
- The identity mask has a bounded look-ahead (at most one quarter, only for names with an identity event): cells in the ambiguity window (s1, s2) are removed although the change is observable only at s2

## What V2 does NOT change (weaknesses carried over from V1, still unapplied proposals)

- The split tolerance is tight for reverse-split ex-dates (true reverse splits can land in AMBIGUOUS and be excluded).
- The unrecorded-discontinuity rule can flag genuine crashes and then excludes the name from that session on (composition bias).
- No instrument filter beyond Massive's `CS` typing (see E).
- The identity mask has a bounded look-ahead (see D): cells inside a hand-over's ambiguity window are removed although the change is observable only at the later observation.
