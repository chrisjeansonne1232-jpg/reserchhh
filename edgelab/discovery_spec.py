"""DAILY_SWING_V2 discovery, round 1 -- frozen BEFORE any strategy return was computed. Hash in the registry; the runner refuses to run if it differs."""
from __future__ import annotations

from .registry import canon, sha256

FAMILY = "daily_swing_v2_r1"
GATE = "DAILY_SWING_V2"

SPEC = {
    "name": "DISCOVERY_DAILY_SWING_V2_R1", "version": 1, "gate": GATE, "evaluator_family": FAMILY,
    "prior": "No edge is expected. Classic short-horizon reversal/momentum in a liquid, heavily arbitraged US universe after assumed costs is more likely to be null than positive; a null is a valid, reportable result.",
    "data": {"panel": "audited DAILY_SWING_V2 universe (baseline top-1000 PIT), spells as identity, V2 masks applied", "prices": "raw SIP bars, back-adjusted only for prices-confirmed or both-provider-agreed splits; NO dividends (price returns)",
             "membership": "next-session membership from sessions <= t, passed separately from the feed", "execution": "open_to_open: decide after close t, fill at open t+1 (engine)"},
    "windows": {"dev": ["2019-01-02", "2024-12-31"], "train": ["2019-01-02", "2022-12-30"], "validation": ["2023-01-03", "2024-12-31"], "locked_oos": ["2025-01-02", "2026-09-29"],
                "oos_rule": "single shot per lineage via Evaluator.final_test; only for candidates the evaluator classifies ROBUST RESEARCH CANDIDATE on dev; never used for selection"},
    "disclosure": "The exclusion-bias diagnostic (pre-discovery check 2) used pooled 60-session forward returns of raw member names and their median, for events dated throughout the window, INCLUDING the locked-OOS dates. No strategy was evaluated on them. Disclosed here instead of marking the OOS dataset contaminated, which would forbid the locked test.",
    "portfolio": {"construction": "dollar-neutral: equal-weight long the top decile of eligible members by score (total +0.5), short the bottom decile (total -0.5)", "decile": 0.10, "min_eligible_names": 100,
                  "eligible": "members at t+1 with a finite score", "between_rebalances": "hold; positions in names that leave the universe are held until the next rebalance"},
    "costs": "engine scenarios optimistic / baseline / pessimistic (assumed spreads, slippage, commissions, opening penalty, impact, 50 bps borrow at baseline). NBBO is not available for the universe: costs are ASSUMED.",
    "terminal_returns": {"S0_zero": 0.0, "S1_shumway": -0.30, "S2_total_loss": -1.0, "primary": "S1_shumway", "rule": "a candidate must clear the evaluator's frozen gates under S1 (primary); S0 and S2 are always reported"},
    "mask_terminated_spells": "spells whose cells stop because of a V2 data-quality mask exit at the last valid price (return 0.0 assumed); the count of positions affected is reported",
    "families": {
        "swing_reversal": {"hyp": "REV", "mechanism": "short-horizon losers outperform winners (liquidity provision); expected to be eroded by costs at 1-day rebalancing", "score": "-(C_t / C_{t-k} - 1)",
                           "grid": {"k": [1, 3, 5, 10], "h": [1, 3, 5]}},
        "swing_momentum": {"hyp": "MOM", "mechanism": "intermediate-horizon winners keep outperforming, skipping the most recent 5 sessions", "score": "C_{t-5} / C_{t-L} - 1",
                           "grid": {"L": [20, 40, 60], "h": [5, 10, 20]}},
        "swing_volshock": {"hyp": "VOL", "mechanism": "abnormal dollar-volume days carry information about the next days (dir=+1 continuation, -1 reversal)", "score": "dir * sign(r_1) * ln(DV_t / median(DV_{t-20..t-1}))",
                           "grid": {"dir": [1, -1], "h": [3, 5]}},
        "swing_overnight": {"hyp": "OVN", "mechanism": "the average overnight return over the last k sessions predicts the next days (dir=+1 continuation, -1 reversal)", "score": "dir * mean_k(O_j / C_{j-1} - 1)",
                            "grid": {"dir": [1, -1], "k": [5, 20], "h": [5]}},
    },
    "n_variants_total": 29,
    "not_tested": ["12-1 month momentum (needs 250 sessions of history: dilutes the sample)", "dividends/total return", "long-only or sector-neutral versions", "any signal from news, fundamentals, minute data or quotes (outside the gate's scope)"],
    "selection": "per family, the variant with the highest BASELINE net Sharpe under S1 on TRAIN (ties: lower turnover). Exactly one candidate per family goes to the evaluator. All 29 variants are logged as registry trials (family shared by all four, so the deflation uses all 29).",
    "evaluator": "edgelab.evaluator frozen thresholds (GENESIS hash in the registry), unchanged; leakage suite (truncation, future-scramble), three cost regimes, DSR with the family trial count, SPA/RC/PBO on the search returns, timing placebo, neighbourhood, sub-periods, factor alpha vs the equal-weight member benchmark, power",
    "substitution": "Evaluator.audit_survivorship compares against the master's delisted names and is not meaningful for a universe-filtered panel. It is fed the delisted names that were ever universe members (a subset of the panel), which makes it pass trivially. That substitution is disclosed in every result; the real safeguards are S1/S2 terminal returns and the V2 residual-survivorship limitation.",
    "reporting": ["the full 29-variant table (train and validation Sharpe, turnover) so nothing is hidden", "each candidate's evaluator scorecard and classification", "S0/S1/S2 results for each candidate", "count of held position-bars that cross an unobservable (masked) bar",
                  "the exclusion-bias caveat for tail-selecting strategies", "locked-OOS result only if released, exactly once"],
}
SPEC_SHA256 = sha256(canon(SPEC))
