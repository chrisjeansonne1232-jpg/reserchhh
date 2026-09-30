# DAILY_SWING_V2 -- requirements (version 2)

Spec hash (sha256 of the canonical JSON in `edgelab/daily_swing_v2_spec.py`): `3f0611ef0d58f4e7ac33be4d26fe1e3a943cbec8f4a2c785370e39394d3f378b`

A **third, separate** gate: V1 plus ONE change (the ticker hand-over identity fix). `DAILY_SWING_V1` (frozen, run, BLOCKED) and the original gate (`overnight_news_open_to_close`) are not modified. Every V1 parameter and threshold is copied unchanged (a test asserts it). The two NEW requirements, R6c and R6d, were fixed before any V2 statistic was computed, but NOT blind: R6d's 3% ceiling was set with the V1 audit's estimate (at most 1.77% of member cells after a hand-over) already known. They are recorded in the append-only registry and the audit refuses to run if they change. A change means a new version, never an edit. **Passing this gate does not start strategy discovery; that needs explicit confirmation.**

## Scope

- **window_start**: 2019-01-01
- **window_end**: last completed XNYS session at audit time
- **market**: US_EQUITY (XNYS calendar)
- **instruments**: Massive reference type CS (US common stock), active or delisted
- **price_source**: Alpaca SIP daily bars, adjustment=raw (primary). Massive: reference, splits, cross-validation only.
- **tradable_cell**: a raw daily bar with volume > 0. Zero-volume bars (provider carry-forward placeholders) are never cells.
- **not_used**: news, fundamentals, minute bars, trades, quotes
- **execution_costs**: cannot be observed from daily bars: spreads/slippage/borrow are ASSUMED and must be stress-tested per experiment

## Identity

- **unit**: spell = maximal run of real bars of one ticker with no gap of >= spell_gap_sessions sessions without a real bar
- **spell_gap_sessions**: 60
- **rationale**: the master keeps one row per ticker (current issuer only) and Alpaca bridges dead periods of re-used tickers with placeholder bars, so identity must come from the bars
- **no_returns_across_spells**: True
- **ticker_hand_over_fix**:
  - `problem`: one bar series can run across a change of issuer for a ticker (V1 audit: 91 ever-member spells carried a FIGI change on one continuous series; 33 also changed name)
  - `key`: issuer cik; composite FIGI only for observations where cik is missing; a pair with no common key is skipped and counted
  - `observations`: Massive point-in-time listings on the first XNYS session of each quarter (2019-Q1 .. last quarter) plus the current master's key for active names at the last data session
  - `boundary`: a ticker's key differs between an observation at session s1 and the next comparable observation at s2 > s1: the hand-over happened in (s1, s2]
  - `mask`: applied AFTER ranking. For each spell of the ticker that (a) has a real bar at or before s1 and a real bar after s1, or (b) has any real bar inside the ambiguity window (s1, s2), cells in (s1, s2 + lookback_sessions) are not cells: the ambiguity window plus the sessions until the new issuer has a lookback of its own. (b) covers a series that starts inside the window: it is not known to hold a single issuer
  - `ranking_untouched`: membership ranking is exactly V1's (strictly point-in-time, truncation-tested). The mask can only remove cells
  - `bounded_look_ahead`: the mask starts at s1+1 but is knowable only at s2 (at most one quarter later) and only for names with an identity event; cells at or after s2 are masked causally. The audit reports the two parts separately
  - `independent_cross_check`: R6c re-derives, per ticker, an issuer label for every session from the observation timeline (label = key when both neighbouring observations agree, AMBIGUOUS between differing ones) and counts unmasked member cells whose lookback holds more than one label or an AMBIGUOUS one

## Point-in-time liquid universe

- **type**: point-in-time top-N by trailing dollar volume
- **lookback_sessions**: 60
- **min_real_bars_in_lookback**: 50
- **rank_metric**: median of close*volume over the lookback window, real bars only, sessions STRICTLY BEFORE t
- **top_n**: 1000
- **min_last_close**: 5.0
- **price_ffill_limit_sessions**: 5
- **membership_for_session_t_uses**: sessions < t only
- **exclusions_applied**: AFTER ranking (membership of other names never depends on an exclusion), effective from the stated session onward

## Empirical split resolution

- **disputed_event**: a split claimed by exactly one of {Massive, Alpaca} (ticker, ratio within 1e-3, date within 3 days), window 2019-01-01..last session
- **claimed_price_multiplier**: split_from / split_to (forward 2-for-1 -> 0.5; reverse 1-for-10 -> 10)
- **test_window_sessions**: 4
- **observed**: overnight ratio R = open_s / previous real close, s in [claimed-4, claimed+4] sessions
- **sigma**: 1.4826 * MAD of overnight log ratios over the 60 real bars before the window; floor 0.015; 0.03 if < 20 observations
- **tolerance**: tol = max(4 * sigma, 0.05)
- **untestable_if_abs_log_ratio_below**: 0.3
- **verdicts**:
  - `CONFIRMED`: some session in the window has |ln R - ln m| <= tol, and dollar volume that day is <= 5x the median of the prior 20 real bars
  - `REFUTED`: no session matches and every session in the window has |ln R| <= tol (no price jump at all: claim false, or bars already adjusted)
  - `AMBIGUOUS`: untestable ratio; a jump that does not match the claim; a match with a dollar-volume spike > 5x (crash-like); or a tolerance so wide the claim and 'no split' overlap
  - `NO_PRICE_DATA`: no real bar in the window: the claim cannot touch any cell
- **event_resolution**: claims of one ticker/spell within 4 sessions form an event. CONFIRMED if >=1 claim CONFIRMED and all confirmed claims agree on the ratio within 1%; REFUTED if all claims REFUTED; else AMBIGUOUS.
- **ambiguous_disputed_event**: the spell is EXCLUDED from (claimed date - 4 sessions) onward (causal: no earlier cell is affected, no name is dropped retroactively)
- **agreed_events**: claimed by both providers: same test; CONFIRMED -> adjust; REFUTED -> do not adjust; untestable-small ratio -> accepted as corroborated but unverified (counted); testable-and-AMBIGUOUS -> excluded like a disputed one
- **unrecorded_discontinuity**: an overnight ratio matching a common split ratio (1/k, k) within tol and |ln R| >= 0.30, no claim within +-4 sessions, and dollar volume <= 5x prior median -> spell EXCLUDED from that session onward. Jumps with a dollar-volume spike > 5x are treated as genuine moves and kept.
- **common_ratios**: [1.5, 2, 3, 4, 5, 6, 8, 10, 15, 20, 25, 50, 100]

## Hard requirements (the gate is OPEN only if every one passes)

| id | requirement | comparison |
|---|---|---|
| R1 | Scope integrity: every panel cell has volume > 0; only CS instruments; window as declared | violations == 0 |
| R2a | No market-wide missing or partial XNYS session in the window | sessions == 0 |
| R2b | Member cells without a real bar (halts, provider drops), share of member cells | share <= 0.005 |
| R2c | Worst single session: share of that day's members without a real bar | share <= 0.05 |
| R3 | Structural validity of member cells: OHLC ordering, positive prices, duplicate (ticker, date) keys | violations == 0 |
| R4a | Every disputed split event (window, all names) has a verdict; none is left unclassified | unclassified == 0 |
| R4b | After exclusions, member cells within a still-AMBIGUOUS split or unrecorded discontinuity | cells == 0 |
| R4c | Member cells removed by split/discontinuity exclusions, share of member cells | share <= 0.05 |
| R5a | Point-in-time: membership recomputed from data truncated at random cut sessions equals the full-data membership at every session <= cut | differences == 0 |
| R5b | Universe size (after exclusions) is at least 800 on at least 99% of window sessions | share_of_sessions >= 0.99 |
| R6a | No member cell's lookback window spans two spells | cells == 0 |
| R6b | No return is computed across a spell boundary (returns are undefined at a spell's first bar) | returns == 0 |
| R6c | Independent timeline cross-check: unmasked member cells whose 60-session lookback (plus the cell itself) covers more than one issuer label, or an ambiguous hand-over window | cells == 0 |
| R6d | Identity mask: share of raw (ranked) member cells removed by the ticker hand-over mask | share <= 0.03 |
| R7a | Cross-provider (Alpaca vs Massive, unadjusted, sample of universe members >= 25 names, >= 5000 bars): share of bars whose close differs by > 0.5% | share <= 0.005 |
| R7b | Cross-provider: no sampled name has more than 5% of its bars mismatching | share <= 0.05 |
| R8 | Residual survivorship bias is quantified (missing listed names via point-in-time listings, expected liquid share, terminal-return exposure) and recorded as a known limitation | recorded == True |
| R9 | Every MATERIAL gap in the ledger has a DAILY_SWING_V2 disposition backed by scope evidence: RESOLVED, EXCLUDED (scope), or an accepted limitation. None is left undispositioned. | undispositioned == 0 |

## Accepted limitation (authorised, quantified, recorded, not a blocker)

- `SURVIVORSHIP_RESIDUAL_DAILY_SWING_V1`: authorised by the requester: remaining survivorship bias (delisted names with no bars, unknown terminal returns of delisted members) is a KNOWN LIMITATION to be quantified, not a blocker

## Declared limitations (not gated, always stated in the report)

- Alpaca is the only price source before 2024-10 (Massive aggregates cover ~2 years): cross-validation exists for the recent window only
- Execution costs are assumed, not observed
- The two providers' split tables are not independent of each other; agreement is corroboration, not proof
- Instrument type (CS) is taken from today's master; names whose type changed are misclassified
- Ticker hand-overs are detectable only at quarterly resolution from 2019-01-02 (plus the current master): hand-overs before that, or reversed within one quarter, or between observations that share no key, are not detected
- A CIK change with a continuing business (e.g. a holding-company reorganisation) is treated as a hand-over (conservative); a hand-over that keeps the CIK is not detected
- The identity mask has a bounded look-ahead (at most one quarter, only for names with an identity event): cells in the ambiguity window (s1, s2) are removed although the change is observable only at s2
