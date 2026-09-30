# DAILY_SWING_V3 -- requirements (version 3)

Spec hash (sha256 of the canonical JSON in `edgelab/daily_swing_v3_spec.py`): `9e976ed76dd3ef40bf30a13a74140502027df21e2a1a412d9c401d3393339342`

A **fourth, separate** gate: it CORRECTS DAILY_SWING_V2, whose OPEN verdict was withdrawn after an adversarial review (registry NOTE GATE_RELIANCE_WITHDRAWN). V1 and V2 are unchanged. Shared parameters are copied from V2; the corrections are listed in the spec. Thresholds new in V3 (R5c, R6d, R6f) were set knowing the V2 measurements (not blind). Requirements are labelled substantive or construction_check so a check that cannot fail is never mistaken for evidence. A change means a new version, never an edit. **Passing this gate does not start strategy discovery; that needs explicit confirmation.**

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
  - `mask`: CAUSAL. For each spell that has a real bar at or before s1 and after s1, or any real bar inside (s1, s2): cells in [s2, s2 + lookback_sessions) are not cells. s2 is the observation that reveals the change, so this uses no information dated after the cell
  - `unresolved_window`: cells inside (s1, s2) are RETAINED (the change is not yet observable). Their share is gated (R6d) and reported; they may mix two issuers. Windows are 87..2,827 days long (median 273)
  - `ranking_untouched`: membership ranking is V1's (strictly point-in-time)
  - `independent_cross_check`: R6c re-derives issuer labels from the observation timeline and counts unmasked member cells whose lookback holds two DIFFERENT KNOWN labels (sessions inside an unresolved window are ignored). It is a construction check against the mask, not evidence that every hand-over was found

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
- **tolerance**: tol = max(4 * sigma, floor); floor 0.05 for claims from one provider, 0.25 for claims BOTH providers agree on
- **untestable_if_abs_log_ratio_below**: 0.3
- **verdicts**:
  - `CONFIRMED`: some session in the window has |ln R - ln m| <= tol, and dollar volume that day is <= 5x the median of the prior 20 real bars
  - `REFUTED`: no session matches and every session in the window has |ln R| <= tol (no price jump at all: claim false, or bars already adjusted)
  - `AMBIGUOUS`: untestable ratio; a jump that does not match the claim; a match with a dollar-volume spike > 5x (crash-like); or a tolerance so wide the claim and 'no split' overlap
  - `NO_PRICE_DATA`: no real bar in the window: the claim cannot touch any cell
- **event_resolution**: claims of one ticker/spell within 4 sessions form an event. CONFIRMED if >=1 claim CONFIRMED and all confirmed claims agree on the ratio within 1%; REFUTED if all claims REFUTED; else AMBIGUOUS.
- **ambiguous_disputed_event**: the spell is EXCLUDED from (claimed date - 4 sessions) onward. Bounded look-ahead: the claimed date is announced in advance, but the verdict uses prices through claimed+4, so a cell can be removed up to 8 sessions before the verdict is knowable; R5c measures the effect
- **agreed_events**: claimed by both providers: same test; CONFIRMED -> adjust; REFUTED -> do not adjust; untestable-small ratio -> accepted as corroborated but unverified (counted); testable-and-AMBIGUOUS -> excluded like a disputed one
- **unrecorded_discontinuity**: NEVER excluded. Overnight jumps with no claim are kept as genuine moves (raw returns) because volume scaling does not separate splits from crashes at small ratios (measured: DD, RGTI, QBTS, QUBT, MAC, DVN, HDS 'scale' like splits and were genuine). Exception: |ln R| >= 1.0 with dollar volume <= 2.5x the prior median matching a common ratio is adjusted as an unrecorded split (snapped to the nearest common ratio)
- **common_ratios**: [1.5, 2, 3, 4, 5, 6, 8, 10, 15, 20, 25, 50, 100]
- **agreed_tolerance_floor**: 0.25
- **unrecorded_adjust_min_abs_ln_r**: 1.0
- **unrecorded_adjust_max_dv_ratio**: 2.5

## Hard requirements (the gate is OPEN only if every one passes)

| id | kind | requirement | comparison |
|---|---|---|---|
| R1 | construction_check | Scope integrity: every panel cell has volume > 0; only CS instruments; window as declared | violations == 0 |
| R2a | substantive | No market-wide missing or partial XNYS session in the window | sessions == 0 |
| R2b | substantive | Member cells without a real bar (halts, provider drops), share of member cells | share <= 0.005 |
| R2c | substantive | Worst single session: share of that day's members without a real bar | share <= 0.05 |
| R3 | substantive | Structural validity of member cells: OHLC ordering, positive prices, duplicate (ticker, date) keys | violations == 0 |
| R4a | construction_check | Every disputed split event (window, all names) has a verdict; none is left unclassified | unclassified == 0 |
| R4b | construction_check | After exclusions, member cells within a still-AMBIGUOUS split or unrecorded discontinuity | cells == 0 |
| R4c | substantive | Member cells removed by split/discontinuity exclusions, share of member cells | share <= 0.05 |
| R5a | substantive | Point-in-time: membership recomputed from data truncated at random cut sessions equals the full-data membership at every session <= cut | differences == 0 |
| R5b | substantive | Distinct-security universe size (after twin resolution and masks) is at least 800 on at least 99% of window sessions | share_of_sessions >= 0.99 |
| R5c | substantive | Point-in-time of the FINAL panel: rebuilding the whole pipeline (twins, claims, masks, ranking) from bars and listings truncated at each of 3 random cut sessions changes at most this share of the final member cells at sessions <= cut | share <= 0.0005 |
| R6a | construction_check | No member cell's lookback window spans two spells | cells == 0 |
| R6b | construction_check | No return is computed across a spell boundary (returns are undefined at a spell's first bar) | returns == 0 |
| R6c | construction_check | Causal timeline cross-check: unmasked member cells whose 60-session lookback covers two different, already-known issuer labels | cells == 0 |
| R6d | substantive | Identity: member cells RETAINED inside unresolved hand-over windows, share of final member cells (declared contamination risk) | share <= 0.01 |
| R6e | substantive | Twin securities: final member cells whose bar is bit-identical to another member's bar on the same session | cells == 0 |
| R6f | substantive | Causal identity tail mask: share of raw (ranked) member cells removed | share <= 0.03 |
| R7a | substantive | Cross-provider (Alpaca vs Massive, unadjusted, sample of universe members >= 25 names, >= 5000 bars): share of bars whose close differs by > 0.5% | share <= 0.005 |
| R7b | substantive | Cross-provider: no sampled name has more than 5% of its bars mismatching | share <= 0.05 |
| R8 | construction_check | Residual survivorship bias is quantified (missing listed names via point-in-time listings, expected liquid share, terminal-return exposure) and recorded as a known limitation | recorded == True |
| R9 | construction_check | Every MATERIAL gap in the ledger has a DAILY_SWING_V3 disposition backed by scope evidence: RESOLVED, EXCLUDED (scope), or an accepted limitation. None is left undispositioned. | undispositioned == 0 |

## Accepted limitation (authorised, quantified, recorded, not a blocker)

- `SURVIVORSHIP_RESIDUAL_DAILY_SWING_V1`: authorised by the requester: remaining survivorship bias (delisted names with no bars, unknown terminal returns of delisted members) is a KNOWN LIMITATION to be quantified, not a blocker

## Declared limitations (not gated, always stated in the report)

- Alpaca is the only price source before 2024-10 (Massive aggregates cover ~2 years): cross-validation exists for the recent window only
- Execution costs are assumed, not observed
- The two providers' split tables are not independent of each other; agreement is corroboration, not proof
- Instrument type (CS) is taken from today's master; names whose type changed are misclassified
- Ticker hand-overs are detectable only at quarterly resolution from 2019-01-02 (plus the current master): hand-overs before that, or reversed within one quarter, or between observations that share no key, are not detected
- A CIK change with a continuing business (e.g. a holding-company reorganisation) is treated as a hand-over (conservative); a hand-over that keeps the CIK is not detected
- Cells inside unresolved hand-over windows are retained and may mix two issuers (share gated by R6d); windows are up to years long when a ticker is absent from the listings in between
- Split-verdict look-ahead of up to 8 sessions around announced claims (measured by R5c)
- Unrecorded splits with |ln R| < 1.0 cannot be told from genuine moves and are kept as raw returns; spin-offs and dividends are not adjusted
- Massive/Alpaca 'twin' resolution keeps one ticker per security; the dropped ticker's identical bars are removed, so panel tickers are provider keys, not point-in-time symbols
