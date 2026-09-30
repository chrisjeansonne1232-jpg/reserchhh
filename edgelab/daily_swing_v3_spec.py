"""DAILY_SWING_V3 -- frozen requirements (pure data). Corrects DAILY_SWING_V2, whose OPEN verdict was withdrawn (registry NOTE GATE_RELIANCE_WITHDRAWN).

V3 = V2 + the corrections forced by a second-pass adversarial review (a fresh model instance, not a human), each re-derived by the author before acting:
  1 twin securities (old + new ticker, bit-identical bars) inflated the universe: resolved before ranking, and measured (R6e);
  2 the identity mask's look-ahead was 87..2,827 days, not 'one quarter': the mask is now CAUSAL (only [s2, s2+lookback) after a hand-over is observable), cells inside the unresolved
    window are retained and their share is a gated, declared risk (R6d); the final panel is tested for point-in-time-ness by a full-pipeline truncation rebuild (R5c);
  3 jumps are never excluded (49 of 52 exclusions were genuine crashes and hid losses from held positions); an unrecorded split is adjusted only for |ln R| >= 1.0 with continuous dollar volume;
  4 several V2 requirements could not fail; V3 labels every requirement 'substantive' or 'construction_check' and adds substantive ones.
Also changed: splits BOTH providers agree on use a tolerance floor of 0.25 instead of 0.05 (reverse-split ex-dates are noisy; the V2 rule excluded true reverse splits of names that then fell).
Thresholds new in V3 (R5c, R6d, R6f) were set knowing the V2 measurements (disclosed): they are not blind pre-registrations.
"""
from __future__ import annotations

import copy

from .daily_swing_v2_spec import SPEC as V2
from .registry import canon, sha256

GATE_NAME = "DAILY_SWING_V3"
SPEC = copy.deepcopy(V2)
SPEC["name"], SPEC["version"] = GATE_NAME, 3
SPEC["relation_to_v1"] = "DAILY_SWING_V1 (frozen, BLOCKED) and DAILY_SWING_V2 (frozen; reliance withdrawn) are unchanged. V3 = V2 plus the corrections listed in the module docstring."
SPEC["review_findings_addressed"] = [
    "twin securities in the panel (59,018 of 1,881,820 final member cells, 73 groups; distinct-security universe 938/953 not 950/966)",
    "identity-mask look-ahead windows of 87..2,827 days (median 273), not one quarter; R5a did not test the final panel",
    "jump exclusions removed 49 genuine down-crashes and hid their losses from held positions",
    "requirements that were true by construction (R4b, R6a, R6b, R6c against the mask)",
]
SPEC["twins"] = {
    "problem": "the provider serves a renamed security's full history under the NEW ticker while the OLD ticker keeps its own history: two tickers, bit-identical bars, both rank as members",
    "rule": "pairs of tickers with identical open/high/low/close/volume on >= min_identical_sessions sessions, and on >= min_identical_fraction_within_stretch of the sessions they both traded between their first and last identical session, are twins; keep the ticker that CONTINUES (has a real bar within continuation_calendar_days after the last identical session; tie: history ends later, then starts earlier, then alphabetical), drop the other's identical bars BEFORE ranking, and MOVE the dropped ticker's own real bars inside the identical stretch on sessions the kept ticker has no real bar to the kept ticker, so one security is one column (the first version left the two halves of one history in two columns, which changed the rank near the cut-off depending on how much data was visible). The test is within the identical STRETCH because a re-used ticker (e.g. DOC, FISV) can have an unrelated issuer's history before the twin stretch",
    "min_identical_sessions": 20, "min_identical_fraction_within_stretch": 0.9, "continuation_calendar_days": 90,
    "information": "same-day bars only; no return is used. Which ticker is kept is a LABEL choice that can depend on bars after the cut; because bars are merged into one column, the set of security-days is the same either way, and R5a/R5c compare bar content (session, open, close, volume) so a label does not count as a membership difference",
}
SPEC["identity"]["ticker_hand_over_fix"] = {
    "problem": SPEC["identity"]["ticker_hand_over_fix"]["problem"],
    "key": SPEC["identity"]["ticker_hand_over_fix"]["key"], "observations": SPEC["identity"]["ticker_hand_over_fix"]["observations"], "boundary": SPEC["identity"]["ticker_hand_over_fix"]["boundary"],
    "mask": "CAUSAL. For each spell that has a real bar at or before s1 and after s1, or any real bar inside (s1, s2): cells in [s2, s2 + lookback_sessions) are not cells. s2 is the observation that reveals the change, so this uses no information dated after the cell",
    "unresolved_window": "cells inside (s1, s2) are RETAINED (the change is not yet observable). Their share is gated (R6d) and reported; they may mix two issuers. Windows are 87..2,827 days long (median 273)",
    "ranking_untouched": "membership ranking is V1's (strictly point-in-time)",
    "independent_cross_check": "R6c re-derives issuer labels from the observation timeline and counts unmasked member cells whose lookback holds two DIFFERENT KNOWN labels (sessions inside an unresolved window are ignored). It is a construction check against the mask, not evidence that every hand-over was found",
}
SPEC["split_resolution"]["agreed_tolerance_floor"] = 0.25
SPEC["split_resolution"]["tolerance"] = "tol = max(4 * sigma, floor); floor 0.05 for claims from one provider, 0.25 for claims BOTH providers agree on"
SPEC["split_resolution"]["unrecorded_discontinuity"] = ("NEVER excluded. Overnight jumps with no claim are kept as genuine moves (raw returns) because volume scaling does not separate splits from crashes at small ratios "
                                                        "(measured: DD, RGTI, QBTS, QUBT, MAC, DVN, HDS 'scale' like splits and were genuine). Exception: |ln R| >= 1.0 with dollar volume <= 2.5x the prior median matching a common ratio is adjusted as an unrecorded split (snapped to the nearest common ratio)")
SPEC["split_resolution"]["unrecorded_adjust_min_abs_ln_r"] = 1.0
SPEC["split_resolution"]["unrecorded_adjust_max_dv_ratio"] = 2.5
SPEC["split_resolution"]["ambiguous_disputed_event"] = ("the spell is EXCLUDED from (claimed date - 4 sessions) onward. Bounded look-ahead: the claimed date is announced in advance, but the verdict uses prices through claimed+4, "
                                                       "so a cell can be removed up to 8 sessions before the verdict is knowable; R5c measures the effect")

_R = {r["id"]: r for r in SPEC["requirements"]}
_R["R5b"]["text"] = "Distinct-security universe size (after twin resolution and masks) is at least 800 on at least 99% of window sessions"
_R["R6c"]["text"] = "Causal timeline cross-check: unmasked member cells whose 60-session lookback covers two different, already-known issuer labels"
_R["R6d"] = {"id": "R6d", "text": "Identity: member cells RETAINED inside unresolved hand-over windows, share of final member cells (declared contamination risk)", "metric": "share", "op": "<=", "threshold": 0.01}
_kind = {"R1": "construction_check", "R2a": "substantive", "R2b": "substantive", "R2c": "substantive", "R3": "substantive", "R4a": "construction_check", "R4b": "construction_check", "R4c": "substantive",
         "R5a": "substantive", "R5b": "substantive", "R6a": "construction_check", "R6b": "construction_check", "R6c": "construction_check", "R6d": "substantive", "R7a": "substantive",
         "R7b": "substantive", "R8": "construction_check", "R9": "construction_check"}
new = [
    {"id": "R5c", "text": "Point-in-time of the FINAL panel: rebuilding the whole pipeline (twins, claims, masks, ranking) from bars and listings truncated at each of 3 random cut sessions changes at most this share of the final member cells at sessions <= cut (cells compared by bar content: session, open, close, volume)", "metric": "share", "op": "<=", "threshold": 0.0005, "min_cuts": 3},
    {"id": "R6e", "text": "Twin securities: final member cells whose bar is bit-identical to another member's bar on the same session", "metric": "cells", "op": "==", "threshold": 0},
    {"id": "R6f", "text": "Causal identity tail mask: share of raw (ranked) member cells removed", "metric": "share", "op": "<=", "threshold": 0.03},
]
reqs = [_R[k] for k in [r["id"] for r in V2["requirements"]]]
i5 = [r["id"] for r in reqs].index("R5b") + 1
reqs[i5:i5] = [new[0]]
i6 = [r["id"] for r in reqs].index("R6d") + 1
reqs[i6:i6] = [new[1], new[2]]
for r in reqs:
    r["kind"] = {"R5c": "substantive", "R6e": "substantive", "R6f": "substantive"}.get(r["id"], _kind.get(r["id"], "substantive"))
for r in reqs:
    if r["id"] == "R5a":
        r["text"] += " (V3: the WHOLE pipeline is rebuilt from truncated bars/listings; cells compared by bar content: session, open, close, volume)"
SPEC["requirements"] = reqs
for r in SPEC["requirements"]:
    if r["id"] == "R9":
        r["text"] = r["text"].replace("DAILY_SWING_V2", GATE_NAME)
SPEC["declared_limitations_not_gated"] = [x for x in V2["declared_limitations_not_gated"] if "bounded look-ahead (at most one quarter" not in x] + [
    "Cells inside unresolved hand-over windows are retained and may mix two issuers (share gated by R6d); windows are up to years long when a ticker is absent from the listings in between",
    "Split-verdict look-ahead of up to 8 sessions around announced claims (measured by R5c)",
    "Unrecorded splits with |ln R| < 1.0 cannot be told from genuine moves and are kept as raw returns; spin-offs and dividends are not adjusted",
    "Massive/Alpaca 'twin' resolution keeps one ticker per security; the dropped ticker's identical bars are removed, so panel tickers are provider keys, not point-in-time symbols",
]
SPEC_SHA256 = sha256(canon(SPEC))
