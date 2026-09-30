"""DAILY_SWING_V1 -- frozen requirements (pure data).

This is a SECOND, SEPARATE gate. It does not touch DiscoveryGate, ExperimentRequirements, REQUIRED_CHECKS or the requirements of the
existing gate ('overnight_news_open_to_close'). Every parameter and threshold below was fixed BEFORE any universe-level statistic was
computed; scripts/freeze_daily_swing_requirements.py hashes SPEC into the immutable registry and the audit refuses to run if the hash differs.
Changing anything requires a new version (DAILY_SWING_V2), never an edit.
"""
from __future__ import annotations

from .registry import canon, sha256

GATE_NAME = "DAILY_SWING_V1"

SPEC = {
    "name": GATE_NAME,
    "version": 1,
    "scope": {
        "window_start": "2019-01-01",
        "window_end": "last completed XNYS session at audit time",
        "market": "US_EQUITY (XNYS calendar)",
        "instruments": "Massive reference type CS (US common stock), active or delisted",
        "price_source": "Alpaca SIP daily bars, adjustment=raw (primary). Massive: reference, splits, cross-validation only.",
        "tradable_cell": "a raw daily bar with volume > 0. Zero-volume bars (provider carry-forward placeholders) are never cells.",
        "not_used": ["news", "fundamentals", "minute bars", "trades", "quotes"],
        "execution_costs": "cannot be observed from daily bars: spreads/slippage/borrow are ASSUMED and must be stress-tested per experiment",
    },
    "identity": {
        "unit": "spell = maximal run of real bars of one ticker with no gap of >= spell_gap_sessions sessions without a real bar",
        "spell_gap_sessions": 60,
        "rationale": "the master keeps one row per ticker (current issuer only) and Alpaca bridges dead periods of re-used tickers with placeholder bars, so identity must come from the bars",
        "no_returns_across_spells": True,
    },
    "universe": {
        "type": "point-in-time top-N by trailing dollar volume",
        "lookback_sessions": 60,
        "min_real_bars_in_lookback": 50,
        "rank_metric": "median of close*volume over the lookback window, real bars only, sessions STRICTLY BEFORE t",
        "top_n": 1000,
        "min_last_close": 5.0,
        "price_ffill_limit_sessions": 5,
        "membership_for_session_t_uses": "sessions < t only",
        "exclusions_applied": "AFTER ranking (membership of other names never depends on an exclusion), effective from the stated session onward",
    },
    "split_resolution": {
        "disputed_event": "a split claimed by exactly one of {Massive, Alpaca} (ticker, ratio within 1e-3, date within 3 days), window 2019-01-01..last session",
        "claimed_price_multiplier": "split_from / split_to (forward 2-for-1 -> 0.5; reverse 1-for-10 -> 10)",
        "test_window_sessions": 4,
        "observed": "overnight ratio R = open_s / previous real close, s in [claimed-4, claimed+4] sessions",
        "sigma": "1.4826 * MAD of overnight log ratios over the 60 real bars before the window; floor 0.015; 0.03 if < 20 observations",
        "tolerance": "tol = max(4 * sigma, 0.05)",
        "untestable_if_abs_log_ratio_below": 0.30,
        "verdicts": {
            "CONFIRMED": "some session in the window has |ln R - ln m| <= tol, and dollar volume that day is <= 5x the median of the prior 20 real bars",
            "REFUTED": "no session matches and every session in the window has |ln R| <= tol (no price jump at all: claim false, or bars already adjusted)",
            "AMBIGUOUS": "untestable ratio; a jump that does not match the claim; a match with a dollar-volume spike > 5x (crash-like); or a tolerance so wide the claim and 'no split' overlap",
            "NO_PRICE_DATA": "no real bar in the window: the claim cannot touch any cell",
        },
        "event_resolution": "claims of one ticker/spell within 4 sessions form an event. CONFIRMED if >=1 claim CONFIRMED and all confirmed claims agree on the ratio within 1%; REFUTED if all claims REFUTED; else AMBIGUOUS.",
        "ambiguous_disputed_event": "the spell is EXCLUDED from (claimed date - 4 sessions) onward (causal: no earlier cell is affected, no name is dropped retroactively)",
        "agreed_events": "claimed by both providers: same test; CONFIRMED -> adjust; REFUTED -> do not adjust; untestable-small ratio -> accepted as corroborated but unverified (counted); testable-and-AMBIGUOUS -> excluded like a disputed one",
        "unrecorded_discontinuity": "an overnight ratio matching a common split ratio (1/k, k) within tol and |ln R| >= 0.30, no claim within +-4 sessions, and dollar volume <= 5x prior median -> spell EXCLUDED from that session onward. Jumps with a dollar-volume spike > 5x are treated as genuine moves and kept.",
        "common_ratios": [1.5, 2, 3, 4, 5, 6, 8, 10, 15, 20, 25, 50, 100],
    },
    "requirements": [
        {"id": "R1", "text": "Scope integrity: every panel cell has volume > 0; only CS instruments; window as declared", "metric": "violations", "op": "==", "threshold": 0},
        {"id": "R2a", "text": "No market-wide missing or partial XNYS session in the window", "metric": "sessions", "op": "==", "threshold": 0},
        {"id": "R2b", "text": "Member cells without a real bar (halts, provider drops), share of member cells", "metric": "share", "op": "<=", "threshold": 0.005},
        {"id": "R2c", "text": "Worst single session: share of that day's members without a real bar", "metric": "share", "op": "<=", "threshold": 0.05},
        {"id": "R3", "text": "Structural validity of member cells: OHLC ordering, positive prices, duplicate (ticker, date) keys", "metric": "violations", "op": "==", "threshold": 0},
        {"id": "R4a", "text": "Every disputed split event (window, all names) has a verdict; none is left unclassified", "metric": "unclassified", "op": "==", "threshold": 0},
        {"id": "R4b", "text": "After exclusions, member cells within a still-AMBIGUOUS split or unrecorded discontinuity", "metric": "cells", "op": "==", "threshold": 0},
        {"id": "R4c", "text": "Member cells removed by split/discontinuity exclusions, share of member cells", "metric": "share", "op": "<=", "threshold": 0.05},
        {"id": "R5a", "text": "Point-in-time: membership recomputed from data truncated at random cut sessions equals the full-data membership at every session <= cut", "metric": "differences", "op": "==", "threshold": 0, "min_cuts": 3},
        {"id": "R5b", "text": "Universe size (after exclusions) is at least 800 on at least 99% of window sessions", "metric": "share_of_sessions", "op": ">=", "threshold": 0.99},
        {"id": "R6a", "text": "No member cell's lookback window spans two spells", "metric": "cells", "op": "==", "threshold": 0},
        {"id": "R6b", "text": "No return is computed across a spell boundary (returns are undefined at a spell's first bar)", "metric": "returns", "op": "==", "threshold": 0},
        {"id": "R7a", "text": "Cross-provider (Alpaca vs Massive, unadjusted, sample of universe members >= 25 names, >= 5000 bars): share of bars whose close differs by > 0.5%", "metric": "share", "op": "<=", "threshold": 0.005, "min_names": 25, "min_bars": 5000},
        {"id": "R7b", "text": "Cross-provider: no sampled name has more than 5% of its bars mismatching", "metric": "share", "op": "<=", "threshold": 0.05},
        {"id": "R8", "text": "Residual survivorship bias is quantified (missing listed names via point-in-time listings, expected liquid share, terminal-return exposure) and recorded as a known limitation", "metric": "recorded", "op": "==", "threshold": True},
        {"id": "R9", "text": "Every MATERIAL gap in the ledger has a DAILY_SWING_V1 disposition backed by scope evidence: RESOLVED, EXCLUDED (scope), or an accepted limitation. None is left undispositioned.", "metric": "undispositioned", "op": "==", "threshold": 0},
    ],
    "accepted_limitations": {
        "SURVIVORSHIP_RESIDUAL_DAILY_SWING_V1": "authorised by the requester: remaining survivorship bias (delisted names with no bars, unknown terminal returns of delisted members) is a KNOWN LIMITATION to be quantified, not a blocker",
    },
    "declared_limitations_not_gated": [
        "Alpaca is the only price source before 2024-10 (Massive aggregates cover ~2 years): cross-validation exists for the recent window only",
        "Execution costs are assumed, not observed",
        "The two providers' split tables are not independent of each other; agreement is corroboration, not proof",
        "Instrument type (CS) is taken from today's master; names whose type changed are misclassified",
    ],
}

SPEC_SHA256 = sha256(canon(SPEC))
