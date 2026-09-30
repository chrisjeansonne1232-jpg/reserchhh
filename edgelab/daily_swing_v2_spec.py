"""DAILY_SWING_V2 -- frozen requirements (pure data). Supersedes nothing: DAILY_SWING_V1 stays frozen, run and BLOCKED.

V2 = V1 + ONE change: an identity fix for ticker hand-overs. Every V1 parameter and threshold is copied unchanged (asserted by a test), so V1 and V2
differ by exactly that one change and their results stay comparable. The three other V1 weaknesses found while auditing (reverse-split tolerance,
exclusion window for unrecorded jumps, instrument filter) are NOT changed here; they were proposals and were not approved.

The identity key is the issuer (Massive `cik`, the SEC registrant id) and NOT the composite FIGI: measured on the point-in-time listings, cik is
present on 99.7% of rows against 85% for composite FIGI, and FIGI churn (renames, reverse splits) is far more frequent than issuer change (379
tickers with more than one FIGI, 306 with more than one CIK, 130 in both). FIGI is used only where cik is missing.

The 3% ceiling in R6d was set from the V1 audit's upper estimate (at most 1.77% of member cells sat after a swap) plus margin, before any V2 result
was computed. This is a design set with V1 results already known, not a blind pre-registration; the V2 audit's R6c/R6d numbers are computed fresh.
"""
from __future__ import annotations

import copy

from .daily_swing_spec import SPEC as V1
from .registry import canon, sha256

GATE_NAME = "DAILY_SWING_V2"

SPEC = copy.deepcopy(V1)
SPEC["name"] = GATE_NAME
SPEC["version"] = 2
SPEC["relation_to_v1"] = "DAILY_SWING_V1 (frozen, unchanged). V2 differs from V1 only in the identity section, requirements R6c/R6d and the declared limitations."

SPEC["identity"]["ticker_hand_over_fix"] = {
    "problem": "one bar series can run across a change of issuer for a ticker (V1 audit: 91 ever-member spells carried a FIGI change on one continuous series; 33 also changed name)",
    "key": "issuer cik; composite FIGI only for observations where cik is missing; a pair with no common key is skipped and counted",
    "observations": "Massive point-in-time listings on the first XNYS session of each quarter (2019-Q1 .. last quarter) plus the current master's key for active names at the last data session",
    "boundary": "a ticker's key differs between an observation at session s1 and the next comparable observation at s2 > s1: the hand-over happened in (s1, s2]",
    "mask": "applied AFTER ranking. For each spell of the ticker that (a) has a real bar at or before s1 and a real bar after s1, or (b) has any real bar inside the ambiguity window (s1, s2), cells in (s1, s2 + lookback_sessions) are not cells: the ambiguity window plus the sessions until the new issuer has a lookback of its own. (b) covers a series that starts inside the window: it is not known to hold a single issuer",
    "ranking_untouched": "membership ranking is exactly V1's (strictly point-in-time, truncation-tested). The mask can only remove cells",
    "bounded_look_ahead": "the mask starts at s1+1 but is knowable only at s2 (at most one quarter later) and only for names with an identity event; cells at or after s2 are masked causally. The audit reports the two parts separately",
    "independent_cross_check": "R6c re-derives, per ticker, an issuer label for every session from the observation timeline (label = key when both neighbouring observations agree, AMBIGUOUS between differing ones) and counts unmasked member cells whose lookback holds more than one label or an AMBIGUOUS one",
}

_reqs = [r for r in SPEC["requirements"]]
_i = [r["id"] for r in _reqs].index("R6b") + 1
_reqs[_i:_i] = [
    {"id": "R6c", "text": "Independent timeline cross-check: unmasked member cells whose 60-session lookback (plus the cell itself) covers more than one issuer label, or an ambiguous hand-over window", "metric": "cells", "op": "==", "threshold": 0},
    {"id": "R6d", "text": "Identity mask: share of raw (ranked) member cells removed by the ticker hand-over mask", "metric": "share", "op": "<=", "threshold": 0.03},
]
for _r in _reqs:
    if _r["id"] == "R9":                                   # wording only: the disposition is for THIS gate (the semantics are unchanged)
        _r["text"] = _r["text"].replace("DAILY_SWING_V1", GATE_NAME)
SPEC["requirements"] = _reqs
SPEC["declared_limitations_not_gated"] = list(V1["declared_limitations_not_gated"]) + [
    "Ticker hand-overs are detectable only at quarterly resolution from 2019-01-02 (plus the current master): hand-overs before that, or reversed within one quarter, or between observations that share no key, are not detected",
    "A CIK change with a continuing business (e.g. a holding-company reorganisation) is treated as a hand-over (conservative); a hand-over that keeps the CIK is not detected",
    "The identity mask has a bounded look-ahead (at most one quarter, only for names with an identity event): cells in the ambiguity window (s1, s2) are removed although the change is observable only at s2",
]

SPEC_SHA256 = sha256(canon(SPEC))
