"""Pre-discovery diagnostics for DAILY_SWING_V2 -- pre-registered BEFORE they were run (hash in the registry).

Four checks requested before any discovery: (1) universe-parameter sweep, (2) exclusion-bias measurement, (3) delisting-return convention with a sensitivity band,
(4) independent review. None of them searches for a strategy. (2) looks at forward returns of EXCLUDED names only, as a bias diagnostic; it is declared here and counted
as a diagnostic, not as a trial.
"""
from __future__ import annotations

from .registry import canon, sha256

SPEC = {
    "name": "PREDISCOVERY_DAILY_SWING_V2", "version": 1,
    "sweep": {
        "design": "one-at-a-time around the frozen V2 baseline (top_n=1000, lookback=60, min_real=50, min_last_close=5); min_real scales as round(5/6 * lookback)",
        "variants": [{"id": "top500", "top_n": 500}, {"id": "top750", "top_n": 750}, {"id": "top1500", "top_n": 1500},
                     {"id": "lb30", "lookback": 30}, {"id": "lb120", "lookback": 120}, {"id": "px3", "min_last_close": 3.0}, {"id": "px10", "min_last_close": 10.0}],
        "recomputed_per_variant": ["raw PIT membership", "unrecorded-discontinuity exclusions (depend on membership)", "V2 split exclusions and identity mask (the spell-level rules are unchanged)"],
        "metrics": ["universe size after masks (min/median)", "R2b", "R2c", "R4c (split/discontinuity exclusion share)", "R6d (identity mask share)", "R5b", "median trailing dollar volume of members",
                    "membership overlap with baseline (containment of the smaller set)", "mean daily membership turnover", "expected missing members from PIT listings (same method as V2)", "annual hazard of a member spell ending"],
        "robustness_criterion": "every variant satisfies the frozen V2 thresholds for R2b, R2c, R4c, R5b and R6d. Descriptive metrics are reported, not gated.",
    },
    "exclusion_bias": {
        "population": "member spells excluded by V2's split/discontinuity rules (identity-masked spells are reported separately, not measured here)",
        "window": "60 sessions of raw close-to-close log return that start AFTER the ambiguous event window (claimed session + 4) for split-ambiguous exclusions and at the close of the jump session for unrecorded-jump exclusions, so no unobservable adjustment is inside the window",
        "benchmark": "median 60-session log return over raw PIT members on the same start session, excluding members with any split claim inside the window",
        "reported": ["n", "median and mean excess log return", "share negative", "bootstrap 95% CI of the median over names (2000 resamples, seed 0)", "by cause", "share that stop trading inside the window"],
        "interpretation_rule": "diagnostic only, no pass/fail. If the absolute median excess exceeds 0.02, it is declared a material composition bias and every discovery result is also reported with the excluded names' direction stated.",
    },
    "delisting_convention": {
        "applies_to": "every spell whose last real bar is more than 5 sessions before the end of the data (observed ended spells, members or not)",
        "scenarios": {"S0_zero": 0.0, "S1_shumway": -0.30, "S2_total_loss": -1.0},
        "rule": "the terminal return is applied by the engine on the last alive bar (open_to_open mode). Discovery reports every result under all three. A candidate needs to clear its frozen thresholds under S1 to be classified above REJECTED; S2 is reported as the worst-case sensitivity, S0 as the optimistic bound.",
        "not_covered": "names that never appear in the data (residual survivorship estimated in the V2 audit at a median of about 11 of 1000 expected missing members) are NOT modelled; results carry that limitation",
        "evaluator_survivorship_gate": "the evaluator's audit_survivorship hard gate compares against the master's delisted names and is not meaningful for a universe-filtered panel; it is fed the delisted names that were ever universe members, the substitution is disclosed in every scorecard and replaced by S1/S2 plus the V2 residual-survivorship limitation",
    },
    "independent_review": {"method": "a fresh model instance with no access to the author's conclusions, read-only, adversarial brief (second-pass review, NOT a human review)",
                           "blocking": "any finding it marks blocks-the-gate must be resolved or explicitly disproven with evidence before discovery"},
    "proceed_to_discovery_iff": [
        "the baseline and at least 6 of the 7 sweep variants satisfy the sweep robustness criterion",
        "no unresolved blocks-the-gate finding from the independent review",
        "the exclusion-bias diagnostic and the delisting scenarios have been run and are reported (any result is acceptable; it changes what is reported, not whether)",
    ],
}
SPEC_SHA256 = sha256(canon(SPEC))
