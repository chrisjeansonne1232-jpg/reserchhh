"""The evaluator must reject intentionally flawed strategies and accept a planted real edge."""
import dataclasses
import os
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from edgelab import stats as S
from edgelab.engine import BASELINE, Exec, run_backtest, collect_weights
from edgelab.evaluator import Candidate, Evaluator, EvaluatorTampered, Thresholds, Vault, evaluator_code_hash
from edgelab.refstrategies import MOMENTUM_SRC, momentum_build, reversal_build
from edgelab.registry import Registry
from edgelab.sandbox import SandboxError, run_sandboxed, static_check
from edgelab.synthetic import make_market, market_return_series, survivors_only
from selftest import flawed as F

NOT_ROBUST = ("REJECTED", "INTERESTING BUT UNPROVEN")


@pytest.fixture
def ev(reg):
    return Evaluator(reg)


def mom_candidate(p, hyp, reg, **kw):
    reg.preregister(hyp, 1, {"hypothesis": "cross-sectional momentum", "window": 40})
    grid = [dict(window=w, rebalance=5) for w in (20, 30, 40, 50, 60)]
    return Candidate("xs_momentum", momentum_build, dict(window=40, rebalance=5), hyp, neighbors=grid,
                     benchmark=market_return_series(p), **kw)


# ------------------------------------------------------------------ flawed strategies
@pytest.mark.parametrize("name,builder", [("lookahead", F.lookahead_next_return()), ("centered_window", F.centered_window()),
                                          ("fullsample_scaling", F.fullsample_scaling())])
def test_leaky_pipelines_are_hard_rejected(ev, reg, name, builder):
    p = make_market(T=500, N=50, seed=21, edge_sd=0.0)
    reg.preregister(name, 1, {})
    c = Candidate(name, builder, {"window": 11}, name)
    sc = ev.evaluate_dev(c, p)
    assert sc.classification == "REJECTED"
    assert any(x.startswith("leakage:") for x in sc.hard_fail), sc.hard_fail


def test_survivorship_biased_dataset_rejected_at_data_gate(ev, reg):
    full = make_market(T=600, N=80, seed=22, delist_frac=0.3, distress_drift=0.004)
    biased = survivors_only(full)
    reg.preregister("surv", 1, {})
    c = Candidate("reversal_longonly", reversal_build, dict(quantile=0.2), "surv")
    sc = ev.evaluate_dev(c, biased)
    assert sc.classification == "REJECTED" and any("survivorship" in x for x in sc.hard_fail)
    assert sc.dims["data_integrity"] == "FAIL"


def test_cost_omission_rejected_when_costs_applied(ev, reg):
    p = make_market(T=800, N=60, seed=23, reversal_phi=0.04, delist_frac=0, late_list_frac=0)
    reg.preregister("rev", 1, {})
    c = Candidate("reversal", reversal_build, dict(quantile=0.2), "rev", benchmark=market_return_series(p))
    sc = ev.evaluate_dev(c, p)
    assert sc.numbers["gross_sharpe"] > 1.0                      # attractive before costs...
    assert sc.numbers["sharpe_by_scenario"]["baseline"] < 0.5    # ...but not after
    assert sc.classification == "REJECTED"


def test_best_of_many_noise_strategies_is_not_robust(ev, reg):
    p = make_market(T=800, N=40, seed=24, edge_sd=0.0, delist_frac=0, late_list_frac=0)
    Ws, R = F.noise_family(p, 120, BASELINE)
    best = int(np.argmax(R.mean(0) / R.std(0)))
    assert S.sharpe(R[:, best]) > 0.5                            # the snooped winner looks decent in-sample
    reg.preregister("snoop", 1, {})
    c = F.precomputed_candidate("noise_best", Ws[best], p, "snoop", dict(idx=best), search_returns=R, benchmark=market_return_series(p))
    sc = ev.evaluate_dev(c, p)
    assert sc.classification in NOT_ROBUST
    assert not sc.gates["spa_reality_check"][0] or not sc.gates["pbo"][0] or not sc.gates["deflated_sharpe"][0]


def test_sharp_isolated_optimum_fails_neighbourhood(ev, reg):
    p = make_market(T=800, N=40, seed=25, edge_sd=0.0, delist_frac=0, late_list_frac=0)
    build = F.seeded_random_build(p)
    scores = {s: S.sharpe(run_backtest(p, collect_weights(build(p, {"seed": s}), p)).net) for s in range(60)}
    best = max(scores, key=scores.get)
    reg.preregister("sharp", 1, {})
    c = Candidate("sharp_opt", build, {"seed": best}, "sharp", neighbors=[{"seed": s} for s in range(60)], benchmark=market_return_series(p))
    sc = ev.evaluate_dev(c, p)
    assert sc.classification in NOT_ROBUST


def test_unregistered_hypothesis_cannot_be_evaluated(ev):
    p = make_market(T=200, N=30, seed=1)
    with pytest.raises(Exception):
        ev.evaluate_dev(Candidate("x", momentum_build, dict(window=40), "never_registered"), p)


# ------------------------------------------------------------------ positive control + calibration
def test_planted_edge_sensitivity_and_locked_oos(reg, tmp_path):
    """Pre-declared protocol (seeds 100-107, edge_sd=0.0016 fixed BEFORE running; no tuning afterwards).
    A single lucky/unlucky seed proves nothing (winner's curse), so we measure rates."""
    ev = Evaluator(reg)
    vault = Vault(reg, tmp_path / "vault")
    n, robust, oos_pass, locked_once = 8, 0, 0, None
    for s in range(100, 100 + n):
        full = make_market(T=1700, N=80, seed=s, edge_sd=0.0016)
        dev, oos = full.slice(0, 1000), full.slice(1000, 1700)
        c = mom_candidate(dev, f"planted{s}", reg)
        sc = ev.evaluate_dev(c, dev)
        if sc.classification.startswith("ROBUST"):
            robust += 1
            vault.seal(f"oos{s}", oos)
            out = ev.final_test(c, sc, vault.open(f"oos{s}"), dataset_id=f"oos{s}")
            oos_pass += out.classification.startswith("ROBUST")
            locked_once = locked_once or (c, sc, vault, s)
    assert robust >= 6, f"sensitivity too low: {robust}/{n}"
    assert oos_pass >= 0.8 * robust, f"OOS confirmation {oos_pass}/{robust}"
    c, sc, vault, s = locked_once
    with pytest.raises(PermissionError):                     # single-shot per lineage
        ev.final_test(c, sc, vault.open(f"oos{s}"), dataset_id=f"oos{s}")
    print(f"planted-edge sensitivity: dev ROBUST {robust}/{n}, locked OOS confirmed {oos_pass}/{robust}")


def test_low_power_real_edge_is_not_called_evidence_against(ev, reg):
    p = make_market(T=300, N=80, seed=11, edge_sd=0.0011)
    c = mom_candidate(p, "shortsample", reg)
    sc = ev.evaluate_dev(c, p)
    assert sc.dims["statistical_power"] == "LOW"
    assert sc.classification in ("INTERESTING BUT UNPROVEN", "REJECTED") and not sc.classification.startswith("ROBUST")
    assert any("low statistical power" in x for x in sc.inconclusive)


def test_false_robust_rate_on_pure_noise_is_controlled(reg):
    ev = Evaluator(reg)
    robust = interesting = 0
    n = 24
    for s in range(n):
        p = make_market(T=800, N=60, seed=1000 + s, edge_sd=0.0)
        c = mom_candidate(p, f"noise{s}", reg)
        cl = ev.evaluate_dev(c, p).classification
        robust += cl.startswith("ROBUST"); interesting += cl.startswith("INTERESTING")
    assert robust == 0, f"false-ROBUST on noise: {robust}/{n}"
    print(f"noise sweep: robust={robust}/{n} interesting={interesting}/{n}")


def test_locked_test_refused_for_non_robust_and_contaminated(ev, reg, tmp_path):
    p = make_market(T=500, N=50, seed=41)
    c = mom_candidate(p, "noise_lock", reg)
    sc = ev.evaluate_dev(c, p)
    oos = make_market(T=300, N=50, seed=42)
    with pytest.raises(PermissionError):
        ev.final_test(c, sc, oos)
    reg.mark_contaminated("seen_oos", "generator saw results", "test")
    sc.classification = "ROBUST RESEARCH CANDIDATE"
    with pytest.raises(PermissionError):
        ev.final_test(c, sc, oos, dataset_id="seen_oos")


# ------------------------------------------------------------------ evaluator integrity
def test_evaluator_refuses_modified_thresholds(reg):
    Evaluator(reg)                                          # registers genesis
    weaker = dataclasses.replace(Thresholds(), min_dsr=0.5)  # generator loosens the bar
    with pytest.raises(EvaluatorTampered):
        Evaluator(reg, thresholds=weaker)


def test_generator_only_sees_public_verdict(ev, reg):
    p = make_market(T=300, N=40, seed=5)
    sc = ev.evaluate_dev(mom_candidate(p, "pub", reg), p)
    pub = sc.public()
    assert set(pub) == {"name", "classification", "n_hard_fails", "n_gates_failed"}


# ------------------------------------------------------------------ sandbox
@pytest.mark.parametrize("name", list(F.ESCAPES))
def test_static_analysis_blocks_escape_attempts(name):
    assert static_check(F.ESCAPES[name])


@pytest.mark.parametrize("name", ["builtin_open", "os_import_runtime", "dunder_import"])
def test_runtime_layers_block_obfuscated_escapes(name):
    p = make_market(T=30, N=12, seed=1)
    with pytest.raises(SandboxError):
        run_sandboxed(F.RUNTIME_ESCAPES[name], "S", {}, p, allow_violations=True, bar_timeout=10)


def test_sandbox_kills_infinite_loop():
    p = make_market(T=40, N=12, seed=1)
    with pytest.raises(SandboxError):
        run_sandboxed(F.RUNTIME_ESCAPES["infinite_loop"], "S", {}, p, allow_violations=True, bar_timeout=2)


@pytest.mark.skipif(os.geteuid() != 0, reason="uid isolation needs root")
def test_sandboxed_child_cannot_read_root_only_files(tmp_path):
    secret = Path("/var/lib/edgelab/vault"); secret.mkdir(parents=True, exist_ok=True); os.chmod(secret, 0o700)
    (secret / "probe.txt").write_text("secret"); os.chmod(secret / "probe.txt", 0o600)
    src = "class S:\n    def __init__(self): pass\n    def on_bar(self, ts, bars):\n        return {}\n"
    # bypass builtins restriction by using a *pre-opened* path through the unprivileged uid check directly
    import subprocess
    def drop():
        os.setgid(65534); os.setuid(65534)
    r = subprocess.run([sys.executable, "-c", "open('/var/lib/edgelab/vault/probe.txt').read()"], preexec_fn=drop, capture_output=True)
    assert r.returncode != 0 and b"Permission" in r.stderr


def test_sandbox_matches_in_process_results():
    p = make_market(T=120, N=25, seed=3)
    W_sbx, rep = run_sandboxed(MOMENTUM_SRC, "XSMomentum", dict(window=20, rebalance=5), p)
    W_in = collect_weights(momentum_build(p, dict(window=20, rebalance=5)), p)
    np.testing.assert_allclose(W_sbx, W_in)
