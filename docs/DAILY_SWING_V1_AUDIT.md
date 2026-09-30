# DAILY_SWING_V1 audit (status as of 2026-09-30 12:38 UTC)

**Gate: BLOCKED**  |  frozen spec `e54bdc870124aaca...` (registry seq 56) | window 2019-01-01..2026-09-29 | data `dsv1_panel_0d20f42a_e54bdc87`

This audit does **not** start strategy discovery. The existing gate (`overnight_news_open_to_close`) is untouched.

## Requirements

| id | requirement | comparison | measured | result | detail |
|---|---|---|---|---|---|
| R1 | Scope integrity: every panel cell has volume > 0; only CS instruments; window as declared | violations == 0 | 0 | **PASS** | member cells with volume<=0: 0; member cells of spells not in the CS master: 0 (spells outside the master: ['GEW', 'IBMW', 'METW'], returned by Alpaca though not requested); member cells before the window: 0; placeholder bars set aside (never cells): 544,945 |
| R2a | No market-wide missing or partial XNYS session in the window | sessions == 0 | 0 | **PASS** | 1946 sessions; median real bars/session 5353; min 4683; sessions below 50% of the median: 0 |
| R2b | Member cells without a real bar (halts, provider drops), share of member cells | share <= 0.005 | 0.0948% | **PASS** | 1,796 of 1,895,497 member cells have no real bar |
| R2c | Worst single session: share of that day's members without a real bar | share <= 0.05 | 0.5149% | **PASS** | worst session 2022-04-11: 0.51% |
| R3 | Structural validity of member cells: OHLC ordering, positive prices, duplicate (ticker, date) keys | violations == 0 | 0 | **PASS** | 1,893,701 member cells checked; duplicate (ticker,session) keys in the whole store: 0 |
| R4a | Every disputed split event (window, all names) has a verdict; none is left unclassified | unclassified == 0 | 0 | **PASS** | 3141 claims in the window ({'both': 2516, 'massive': 509, 'alpaca': 116}); every claim has a verdict |
| R4b | After exclusions, member cells within a still-AMBIGUOUS split or unrecorded discontinuity | cells == 0 | 0 | **PASS** | unrecorded split-like jumps: 52; ambiguous split events excluded: 1612; agreed, untestable-small, accepted as corroborated-but-unverified: 14 |
| R4c | Member cells removed by split/discontinuity exclusions, share of member cells | share <= 0.05 | 2.5952% | **PASS** | 50,503 of 1,946,000 member cells removed; 126 of 2135 member spells affected |
| R5a | Point-in-time: membership recomputed from data truncated at random cut sessions equals the full-data membership at every session <= cut | differences == 0 | 0 | **PASS** | cuts at sessions ['2023-03-27', '2024-02-16', '2025-08-26']; membership rebuilt from data truncated at the cut vs full data, compared on every session <= cut |
| R5b | Universe size (after exclusions) is at least 800 on at least 99% of window sessions | share_of_sessions >= 0.99 | 1.0000 | **PASS** | universe size after exclusions: min 955, median 972, share of sessions >= 800: 1.0000 |
| R6a | No member cell's lookback window spans two spells | cells == 0 | 0 | **PASS** | 296 tickers have more than one spell; member cells whose 60-session lookback holds a bar of another spell of the same ticker: 0 |
| R6b | No return is computed across a spell boundary (returns are undefined at a spell's first bar) | returns == 0 | 0 | **PASS** | returns are computed inside a spell only: a spell's first bar has no predecessor in its column |
| R7a | Cross-provider (Alpaca vs Massive, unadjusted, sample of universe members >= 25 names, >= 5000 bars): share of bars whose close differs by > 0.5% | share <= 0.005 | 0.0000% | **PASS** | 20,000 overlapping bars, 40 names (2024-10-01..2026-09-29); bars only in Alpaca: 0; only in Massive: 0 |
| R7b | Cross-provider: no sampled name has more than 5% of its bars mismatching | share <= 0.05 | 0.0000% | **PASS** | worst name: AFRM 0.00% |
| R8 | Residual survivorship bias is quantified (missing listed names via point-in-time listings, expected liquid share, terminal-return exposure) and recorded as a known limitation | recorded == True | True | **PASS** | see 'Residual survivorship' section |
| R9 | Every MATERIAL gap in the ledger has a DAILY_SWING_V1 disposition backed by scope evidence: RESOLVED, EXCLUDED (scope), or an accepted limitation. None is left undispositioned. | undispositioned == 0 | 4 | **FAIL** | 19 dispositioned; 4 not |

Notes on the measurements: **R7** compares two vendors that both deliver consolidated SIP prints (closes are bit-identical on 100% of the sampled bars; volume is identical on about two thirds), so it validates the data path, not an independent price source. The point-in-time test (R5a) is run on the real data at three random cut dates; the rest of the universe logic is covered by unit tests with planted defects.

## Why the gate is blocked

- requirement R9 FAILED: Every MATERIAL gap in the ledger has a DAILY_SWING_V1 disposition backed by scope evidence: RESOLVED, EXCLUDED (scope), or an accepted limitation. None is left undispositioned. (measured 4; needs undispositioned == 0)
- MATERIAL gap f9dc315d8340 [RENAME_FEED_SPARSE] has no DAILY_SWING_V1 disposition: rename feed has 2016: 0, 2017: 2, 2018: 2, 2019: 53 events vs ~576/yr in well-covered years (first event 2017-
- MATERIAL gap 312f692e1491 [RENAME_HISTORY_BACKMAPPED] has no DAILY_SWING_V1 disposition: 222 occurrence(s), 222 unit(s), 211 distinct ticker(s). Worst/examples: 067BAS012->BNED on 2024-06-11: provide
- MATERIAL gap 052ab8b73687 [RENAME_WITH_PRICE_DISCONTINUITY] has no DAILY_SWING_V1 disposition: 158 occurrence(s), 158 unit(s), 155 distinct ticker(s). Worst/examples: 067BAS012->BNED on 2024-06-11: price j
- MATERIAL gap b6a2dcb79c50 [SYMBOL_REUSED_ACROSS_ISSUERS] has no DAILY_SWING_V1 disposition: 180 occurrence(s), 180 unit(s), 180 distinct ticker(s). Worst/examples: 'AAMCF' was retired on 2025-11-24 (->A

## Point-in-time universe

Top 1000 by trailing 60-session median dollar volume (>= 50 real bars, last close >= $5), membership for session t computed from sessions < t only; exclusions applied afterwards.

| index | sessions | universe_min | universe_median | member_cells_removed_share |
|---|---|---|---|---|
| 2019 | 252 | 996 | 996 | 0.0032 |
| 2020 | 253 | 971 | 979 | 0.0185 |
| 2021 | 252 | 969 | 972 | 0.0279 |
| 2022 | 251 | 970 | 972 | 0.0276 |
| 2023 | 250 | 970 | 973 | 0.0273 |
| 2024 | 252 | 969 | 972 | 0.0278 |
| 2025 | 250 | 956 | 963 | 0.0381 |
| 2026 | 186 | 955 | 959 | 0.0413 |

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

Unrecorded overnight discontinuities among raw member cells: {'LARGE_MOVE_NOT_SPLIT_LIKE': 169, 'SPLIT_LIKE_BUT_GENUINE_MOVE_DV_SPIKE': 133, 'COVERED_BY_CLAIM': 106, 'UNRECORDED_SPLIT_LIKE': 52}. Full tables in `data/audit/daily_swing_v1/`.

## Residual survivorship (KNOWN LIMITATION, authorised; quantified, not a blocker)

**A. Names listed (point-in-time) but with no bars.** {"median_missing_share": 0.0127, "range_missing_share": [0.0042, 0.1094], "median_expected_missing_members_point": 11.0, "range_expected": [3.0, 187.7], "median_upper_bound_missing_members": 74, "lower_bound": 0, "median_p_member_given_bars": 0.19, "universe_size": 1000, "point_estimate_share_of_universe": 0.011, "outlier_snapshots": ["2019-07-01"], "assumption": "missing names are as likely to be liquid as names with bars on the same exchange/date (upper-leaning: illiquid names are the ones that lack bars); the upper bound counts every missing name"}

**B. Terminal returns of members that stop trading.** {"member_spells_ended": 490, "of_which_master_inactive": 478, "annual_hazard_of_a_member_stopping_trading": {"2019": 0.0483, "2020": 0.0544, "2021": 0.0585, "2022": 0.0688, "2023": 0.0647, "2024": 0.0647, "2025": 0.0791, "2026": 0.0616}, "mean_annual_hazard": 0.0625, "observed_final_20_session_raw_log_return_quantiles": {"0.1": -0.274, "0.25": -0.032, "0.5": 0.006, "0.75": 0.029, "0.9": 0.109}, "sensitivity_annual_drag_bps_of_an_always_invested_equal_weight_book_if_unobserved_terminal_return_were": {"-30%": -187.5, "-60%": -375.0, "-100%": -625.0}, "note": "the return from the last observed bar to the end of the security (cash-out, distressed exit, delisting) is not observed for any of these; the sensitivity is arithmetic, not an estimate"}

**C. What the exclusions removed (composition only).** {"excluded_member_spells_distinct": 126, "exclusion_events_touching_member_spells": 167, "share_of_member_spells": 0.059, "cause_of_each_spells_earliest_exclusion": {"UNRECORDED_SPLIT_LIKE_DISCONTINUITY": 46, "AGREED_SPLIT_TESTABLE_AMBIGUOUS": 43, "DISPUTED_SPLIT_AMBIGUOUS": 37}, "exclusion_events_by_cause": {"DISPUTED_SPLIT_AMBIGUOUS": 62, "AGREED_SPLIT_TESTABLE_AMBIGUOUS": 53, "UNRECORDED_SPLIT_LIKE_DISCONTINUITY": 52}, "member_cells_removed_share": 0.026, "share_of_excluded_spells_that_later_stop_trading": 0.254, "same_share_for_all_member_spells": 0.232, "median_prior_60_session_raw_log_return_at_exclusion": -0.057, "n_prior": 126, "note": "exclusions remove names from the moment the data becomes ambiguous; this is a composition change, direction of the return bias NOT measured"}

**D. Identity (ticker re-use glued into one series).** {"glued_spells_total": 324, "glued_spells_with_member_cells": 91, "of_which_name_also_changed_similarity_below_0.6": 33, "member_cells_after_the_swap_window": {"lower_bound_from_first_snapshot_after": 28635, "upper_bound_from_last_snapshot_before": 34499}, "examples_name_changed": [{"ticker": "AAN", "name_before": "Aaron's, Inc.", "name_after": "The Aaron's Company, Inc."}, {"ticker": "AMR", "name_before": "Alta Mesa Resources, Inc. Class A Common Stock", "name_after": "Alpha Metallurgical Resources, Inc."}, {"ticker": "APA", "name_before": "Apache Corporation", "name_after": "APA Corporation Common Stock"}, {"ticker": "ARCH", "name_before": "Arch Coal, Inc.", "name_after": "Arch Resources, Inc."}, {"ticker": "B", "name_before": "Barnes Group Inc.", "name_after": "Barrick Mining Corporation"}, {"ticker": "BNY", "name_before": "Blackrock New York Muni Tr", "name_after": "Bank of New York Mellon Corporation"}, {"ticker": "BX", "name_before": "The Blackstone Group Lp", "name_after": "Blackstone Inc."}, {"ticker": "CADE", "name_before": "Cadence Bancorporation", "name_after": "Cadence Bank"}, {"ticker": "CCMP", "name_before": "Cabot Microelectronics Corp", "name_after": "CMC Materials, Inc. Common Stock"}, {"ticker": "CNR", "name_before": "Cornerstone Building Brands, Inc.", "name_after": "Core Natural Resources, Inc."}], "note": "spells that hold real bars near two PIT snapshot dates on which the ticker belonged to different FIGIs. A FIGI change is NOT proof of a different issuer (renames and restructurings also change it), so the count is conservative; the name-change subset is indicative only. No V1 rule separates these series."}

**E. Instrument mix: Massive's `CS` is not pure US common stock.** {"ever_member_spells": 2135, "name_matches_ads_or_fund": 0, "share_of_spells": 0.0, "share_of_member_cells": 0.0, "examples": [], "method": "case-insensitive name match on American Depositary|\\bADS\\b|\\bADR\\b|\\bFund\\b|\\bFd\\b|Closed[- ]End|\\bETF\\b|\\bETN\\b (heuristic: neither exhaustive nor exact)"}

Not quantified: names whose Massive type changed; provider-side omission of names that were never listed in Massive's PIT snapshots.

## Gap dispositions for DAILY_SWING_V1 (recorded as gate-tagged registry events; the existing gate's ledger view is unchanged)

| gap | kind | result | evidence |
|---|---|---|---|
| `8656ad608dd5` | NO_VENDOR_RECEIPT_TS | EXCLUDED for DAILY_SWING_V1 (earlier run) | DAILY_SWING_V1 scope disposition. not an input of DAILY_SWING_V1 (SPEC scope.not_used); the panel is built from daily bars only |
| `b02630318686` | NO_SYSTEM_RECEIPT_TS | EXCLUDED for DAILY_SWING_V1 (earlier run) | DAILY_SWING_V1 scope disposition. not an input of DAILY_SWING_V1 (SPEC scope.not_used); the panel is built from daily bars only |
| `9676ac77713c` | NO_POINT_IN_TIME_FUNDAMENTALS | EXCLUDED for DAILY_SWING_V1 (earlier run) | DAILY_SWING_V1 scope disposition. not an input of DAILY_SWING_V1 (SPEC scope.not_used); the panel is built from daily bars only |
| `4ece3b95d505` | NEWS_HAS_NO_RECEIPT_TIMESTAMPS | EXCLUDED for DAILY_SWING_V1 (earlier run) | DAILY_SWING_V1 scope disposition. not an input of DAILY_SWING_V1 (SPEC scope.not_used); the panel is built from daily bars only |
| `3e8515467789` | BARS_AFTER_DELISTING | EXCLUDED for DAILY_SWING_V1 (earlier run) | DAILY_SWING_V1 scope disposition. member cells WITH a real bar more than 3 days after a master delisting date: 0 (member cells without a bar shortly after a stock's last bar are the no-look-ahead lag, counted in R2b and masked) |
| `3dec60b1f364` | MISSING_SESSION_LIQUID | EXCLUDED for DAILY_SWING_V1 (earlier run) | DAILY_SWING_V1 scope disposition. R2b=0.0948%, R2c=0.51% on member cells; missing member cells are masked, never filled |
| `ae601a72adde` | MISSING_TAIL | EXCLUDED for DAILY_SWING_V1 (earlier run) | DAILY_SWING_V1 scope disposition. ACCEPTED LIMITATION: component of SURVIVORSHIP_RESIDUAL_DAILY_SWING_V1 (authorised by the requester), quantified there. Not resolved. |
| `b71003d84970` | STALE_DAILY_PRICES | EXCLUDED for DAILY_SWING_V1 (earlier run) | DAILY_SWING_V1 scope disposition. member-panel flat-bar runs (check_stale_daily on 1,893,701 member cells): 0 |
| `166eeea120dc` | ZERO_VOLUME_PLACEHOLDER_BARS | EXCLUDED for DAILY_SWING_V1 (earlier run) | DAILY_SWING_V1 scope disposition. member cells with volume<=0: 0 (R1); 544,945 placeholder bars were set aside and are never cells |
| `e03589a7e0be` | DELISTING_RETURN_UNKNOWN | EXCLUDED for DAILY_SWING_V1 (earlier run) | DAILY_SWING_V1 scope disposition. ACCEPTED LIMITATION: component of SURVIVORSHIP_RESIDUAL_DAILY_SWING_V1 (authorised by the requester), quantified there. Not resolved. |
| `5b409b031d34` | SPLIT_NO_PRICE_DATA | EXCLUDED for DAILY_SWING_V1 (earlier run) | DAILY_SWING_V1 scope disposition. claims with no real bar within +-4 sessions that touch a member cell: 0 |
| `4342e13eeb3e` | SPLIT_WITHOUT_DISCONTINUITY | EXCLUDED for DAILY_SWING_V1 (earlier run) | DAILY_SWING_V1 scope disposition. R4a=0, R4b=0; disputed events: 609 (confirmed 80, refuted 67, ambiguous->spell excluded 325, no price data 137) |
| `8ecf6ed9bcdf` | UNRECORDED_SPLIT_LIKE_DISCONTINUITY | EXCLUDED for DAILY_SWING_V1 (earlier run) | DAILY_SWING_V1 scope disposition. R4a=0, R4b=0; disputed events: 609 (confirmed 80, refuted 67, ambiguous->spell excluded 325, no price data 137) |
| `fe0f9533db10` | SPLIT_TABLES_DISAGREE | EXCLUDED for DAILY_SWING_V1 (earlier run) | DAILY_SWING_V1 scope disposition. R4a=0, R4b=0; disputed events: 609 (confirmed 80, refuted 67, ambiguous->spell excluded 325, no price data 137) |
| `f9dc315d8340` | RENAME_FEED_SPARSE | NOT DISPOSITIONED | scope condition NOT satisfied: R6a=0, R6b=0, R4b=0; glued spells (one series across two FIGIs) with member cells: 91; rename events in the window touching a member name: 65; NB the rename feed is sparse in 2019 (in the window): identity rests on bars and PIT listings, not on rename events |
| `312f692e1491` | RENAME_HISTORY_BACKMAPPED | NOT DISPOSITIONED | scope condition NOT satisfied: R6a=0, R6b=0, R4b=0; glued spells (one series across two FIGIs) with member cells: 91; rename events in the window touching a member name: 65 |
| `052ab8b73687` | RENAME_WITH_PRICE_DISCONTINUITY | NOT DISPOSITIONED | scope condition NOT satisfied: R6a=0, R6b=0, R4b=0; glued spells (one series across two FIGIs) with member cells: 91; rename events in the window touching a member name: 65 |
| `b6a2dcb79c50` | SYMBOL_REUSED_ACROSS_ISSUERS | NOT DISPOSITIONED | scope condition NOT satisfied: R6a=0, R6b=0, R4b=0; glued spells (one series across two FIGIs) with member cells: 91; rename events in the window touching a member name: 65 |
| `28b832dfe714` | DELISTED_NAMES_NO_BARS | EXCLUDED for DAILY_SWING_V1 (earlier run) | DAILY_SWING_V1 scope disposition. ACCEPTED LIMITATION: component of SURVIVORSHIP_RESIDUAL_DAILY_SWING_V1 (authorised by the requester), quantified there. Not resolved. |
| `326b3633ee36` | BAR_PRESENT_IN_ONE_PROVIDER_ONLY | EXCLUDED for DAILY_SWING_V1 (earlier run) | DAILY_SWING_V1 scope disposition. not an input of DAILY_SWING_V1 (SPEC scope.not_used); the panel is built from daily bars only (this MATERIAL entry is the minute-bar comparison) |
| `cdbceb6465cb` | MISSING_MINUTES_LIQUID | EXCLUDED for DAILY_SWING_V1 (earlier run) | DAILY_SWING_V1 scope disposition. not an input of DAILY_SWING_V1 (SPEC scope.not_used); the panel is built from daily bars only |
| `b93e856d2909` | QUOTES_NBBO_NOT_MATERIALISED | EXCLUDED for DAILY_SWING_V1 (earlier run) | DAILY_SWING_V1 scope disposition. not an input of DAILY_SWING_V1 (SPEC scope.not_used); the panel is built from daily bars only; execution costs are assumed (SPEC scope.execution_costs) |
| `f89d81a0d721` | MINUTE_AND_TICK_HISTORY_NOT_MATERIALISED | EXCLUDED for DAILY_SWING_V1 (earlier run) | DAILY_SWING_V1 scope disposition. not an input of DAILY_SWING_V1 (SPEC scope.not_used); the panel is built from daily bars only; execution costs are assumed (SPEC scope.execution_costs) |

## Declared limitations (not gated)

- Alpaca is the only price source before 2024-10 (Massive aggregates cover ~2 years): cross-validation exists for the recent window only
- Execution costs are assumed, not observed
- The two providers' split tables are not independent of each other; agreement is corroboration, not proof
- Instrument type (CS) is taken from today's master; names whose type changed are misclassified

## Weaknesses of the V1 rules found while auditing (V1 is frozen and was run exactly as written)

- **Split tolerance is tight for reverse-split ex-dates**: `tol = max(4*sigma, 0.05)` with a 1.5% sigma floor rejects true reverse splits whose ex-date open moves 7-10% around the ratio; those spells are excluded although the split is real.
- **Unrecorded-discontinuity rule can flag genuine crashes** whose size happens to match a common ratio (2020-03-09 energy names, PCG 2019-01-14) and then excludes the name from that session on, removing post-crash history: a composition bias.
- **`CS` can include ADS lines and closed-end funds** in Massive's typing (they appear among listed-but-no-bars names); a name-pattern check found none among the universe members (E above), but the check is a heuristic and V1 has no instrument filter.
- **V1 has no rule for ticker hand-overs**: the point-in-time listings show one bar series running across a FIGI change for a set of member spells, some of them clearly different issuers (see D). This is what blocks the gate.
Proposed for a DAILY_SWING_V2 (needs your confirmation; not applied): (1) split each spell at a PIT FIGI change (or exclude it from that point, the same 'ambiguous -> exclude' principle used for splits); (2) widen the split tolerance for reverse splits using post-event volume scaling; (3) exclude only the affected session window for an unrecorded jump instead of the rest of the spell; (4) filter instrument type by FIGI/exchange metadata.

*Cost of fix (1), for your decision only, not applied and not part of V1:* it would remove at most 28,635-34,499 further member cells (1.47%-1.77% of raw member cells; some overlap the split exclusions), taking total removals to at most about 4.4%, still under the 5% ceiling in R4c.

## Corrections to earlier outputs (the registry is append-only; corrections are recorded as NOTE events)

- **C1_excluded_spell_count**: was: text of the accepted-limitation gap recorded in the first audit run says '167 spells' excluded. Now: 126 distinct member spells (167 exclusion events, share of member spells 5.9%); 167 was the number of exclusion events. The 2.60% of member cells removed was correct.
