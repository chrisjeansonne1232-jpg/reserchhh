"""The immutable evaluator.

* Thresholds are a frozen dataclass whose hash is written to the registry GENESIS event; the evaluator
  refuses to run if the code or thresholds no longer match the registered genesis (tamper-evident).
* The generator only ever receives a public verdict (no numbers, no thresholds) unless a disclosure is
  explicitly requested, which marks the corresponding dataset CONTAMINATED.
* The locked test is single-shot per hypothesis lineage and the vault lives outside the generator's
  filesystem permissions (root-owned 0700 directory; strategy code runs as an unprivileged uid).
"""
from __future__ import annotations

import hashlib
import os
import pickle
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from . import stats as S
from .data import DataGapError, Panel, audit_survivorship, validate_panel
from .engine import BASELINE, SCENARIOS, Exec, break_even_cost_multiplier, collect_weights, run_backtest
from .leakage import LeakResult, delay_fragility, implausible_performance, leakage_suite
from .registry import Registry, canon, sha256
from .sandbox import run_sandboxed, static_check

CLASSES = ["REJECTED", "INTERESTING BUT UNPROVEN", "ROBUST RESEARCH CANDIDATE",
           "PAPER-VALIDATED CANDIDATE", "LIVE CANDIDATE"]


@dataclass(frozen=True)
class Thresholds:
    version: str = "1.0"
    min_dsr: float = 0.95
    max_perm_p: float = 0.05
    max_spa_p: float = 0.10
    max_pbo: float = 0.50
    min_baseline_net_sharpe: float = 0.5
    min_gross_to_cost: float = 2.0
    min_neighbor_pos_frac: float = 0.70
    min_neighbor_median_ratio: float = 0.50
    max_top5_share: float = 0.50
    min_subperiod_pos_frac: float = 0.60
    n_subperiods: int = 5
    max_plausible_sharpe: float = 5.0
    min_power_for_claim: float = 0.50       # power to detect the observed Sharpe; below => "insufficient evidence"
    min_alpha_t: float = 2.0
    oos_max_p: float = 0.10
    oos_min_ratio: float = 0.25             # OOS Sharpe / dev Sharpe
    oos_min_sharpe: float = 0.3
    max_paper_discrepancy: float = 0.5      # |paper - backtest| / backtest mean return
    min_paper_days: int = 60
    n_perm: int = 1000
    n_boot: int = 1000
    seed: int = 12345


THRESHOLDS = Thresholds()


def thresholds_hash(t: Thresholds = THRESHOLDS) -> str:
    return sha256(canon(asdict(t)))


def evaluator_code_hash() -> str:
    h = hashlib.sha256()
    here = Path(__file__).parent
    for f in ("evaluator.py", "stats.py", "engine.py", "leakage.py", "sandbox.py", "data.py"):
        h.update((here / f).read_bytes())
    return h.hexdigest()


class EvaluatorTampered(Exception):
    pass


@dataclass
class Candidate:
    name: str
    build: Callable[[Panel, dict], object]
    params: dict
    hyp_id: str
    version: int = 1
    neighbors: list[dict] = field(default_factory=list)          # parameter neighbourhood incl. chosen
    source: str | None = None                                    # sandbox-runnable source (optional)
    cls: str | None = None
    exec_base: Exec = BASELINE
    search_returns: np.ndarray | None = None                     # (T,K) dev-period net returns of every variant tried
    family: str = "default"
    ablations: dict[str, Callable[[Panel, dict], object]] = field(default_factory=dict)
    benchmark: np.ndarray | None = None                          # dev-period benchmark (market) returns


@dataclass
class Scorecard:
    name: str
    dims: dict = field(default_factory=dict)
    gates: dict = field(default_factory=dict)     # name -> (bool, detail)
    hard_fail: list = field(default_factory=list)
    flags: list = field(default_factory=list)
    inconclusive: list = field(default_factory=list)
    classification: str = "REJECTED"
    numbers: dict = field(default_factory=dict)

    def public(self) -> dict:
        return {"name": self.name, "classification": self.classification,
                "n_hard_fails": len(self.hard_fail), "n_gates_failed": sum(1 for g in self.gates.values() if not g[0])}


class Evaluator:
    def __init__(self, registry: Registry, thresholds: Thresholds = THRESHOLDS, vault_dir: str | Path | None = None):
        self.reg, self.th = registry, thresholds
        self.vault_dir = Path(vault_dir) if vault_dir else None
        self._verify_genesis()

    # ------------------------------------------------------------------ integrity
    def _verify_genesis(self):
        g = self.reg.events("GENESIS")
        cur = {"thresholds_sha": thresholds_hash(self.th), "code_sha": evaluator_code_hash(), "version": self.th.version}
        if not g:
            self.reg.append("GENESIS", cur)
            return
        last = g[-1]["payload"]
        if last["thresholds_sha"] != cur["thresholds_sha"] or last["code_sha"] != cur["code_sha"]:
            raise EvaluatorTampered("evaluator code/thresholds differ from registered genesis; a deliberate "
                                    "evaluator release (new GENESIS event) is required and is publicly visible in the chain")

    @classmethod
    def release_new_genesis(cls, registry: Registry, note: str, thresholds: Thresholds = THRESHOLDS):
        registry.append("GENESIS", {"thresholds_sha": thresholds_hash(thresholds), "code_sha": evaluator_code_hash(),
                                    "version": thresholds.version, "note": note})

    # ------------------------------------------------------------------ helpers
    def _weights(self, cand: Candidate, params: dict, panel: Panel) -> np.ndarray:
        if cand.source:
            W, _ = run_sandboxed(cand.source, cand.cls, params, panel)
            return W
        return collect_weights(cand.build(panel, params), panel)

    def _sharpe_net(self, cand, params, panel, ex=None) -> float:
        W = self._weights(cand, params, panel)
        return S.sharpe(run_backtest(panel, W, ex or cand.exec_base).net, ex.periods_per_year if ex else 252)

    # -------------------------------------------------------------------- dev evaluation
    def evaluate_dev(self, cand: Candidate, panel: Panel, *, dataset_id: str = "dev", seed: int | None = None,
                     capital_ladder=(1e3, 1e4, 1e5, 1e6, 1e7)) -> Scorecard:
        th = self.th
        seed = th.seed if seed is None else seed
        sc = Scorecard(cand.name)
        pre = self.reg.prereg(cand.hyp_id, cand.version)   # raises if not pre-registered
        # ---- 0. data integrity
        findings = validate_panel(panel)
        fails = [f for f in findings if f.severity == "FAIL"]
        surv = audit_survivorship(panel.tickers, panel.meta.get("master_tickers", panel.tickers),
                                  panel.meta.get("delisted_in_master", []))
        sc.dims["data_integrity"] = "FAIL" if (fails or surv) else ("WARN" if findings else "PASS")
        for f in fails + surv:
            sc.hard_fail.append(f"data:{f.check}: {f.detail}")
        if self.reg.contaminated(dataset_id):
            sc.flags.append(f"dataset '{dataset_id}' is contaminated (seen by generator); results are development-grade only")
        if cand.source:
            v = static_check(cand.source)
            if v:
                sc.hard_fail.append("static_analysis: " + "; ".join(f"L{x.line} {x.msg}" for x in v))
        if sc.hard_fail:
            sc.dims["leakage_resistance"] = "NOT RUN"
            return self._finish(sc, cand, dataset_id, seed, panel)
        # ---- 1. leakage
        leaks: list[LeakResult] = [] if cand.source else leakage_suite(cand.build, cand.params, panel)
        for L in leaks:
            self.reg.append("LEAKAGE_TEST", {"hyp_id": cand.hyp_id, "name": L.name, "passed": L.passed, "detail": L.detail})
            if not L.passed:
                sc.hard_fail.append(f"leakage:{L.name}: {L.detail}")
        sc.dims["leakage_resistance"] = "FAIL" if any(not L.passed for L in leaks) else "PASS"
        if sc.hard_fail:
            return self._finish(sc, cand, dataset_id, seed, panel)
        # ---- 2. backtests under three execution regimes
        W = self._weights(cand, cand.params, panel)
        try:
            run_backtest(panel, W, cand.exec_base)
        except DataGapError as e:
            sc.hard_fail.append(f"data_gap: {e}")
            sc.dims["data_integrity"] = "FAIL"
            return self._finish(sc, cand, dataset_id, seed, panel)
        res = {k: run_backtest(panel, W, Exec(**{**asdict(ex), "mode": cand.exec_base.mode, "capital": cand.exec_base.capital,
                                                 "max_weight": cand.exec_base.max_weight, "max_gross": cand.exec_base.max_gross}))
               for k, ex in SCENARIOS.items()}
        base = res["baseline"]
        n = len(base.net)
        sc.numbers["assumptions"] = base.assumptions
        if base.assumptions["spread_source"] == "assumed_constant":
            sc.flags.append("no observed spreads (NBBO unavailable): a constant assumed spread was used -- execution realism is limited")
        elif base.assumptions["default_spread_held_cells"]:
            sc.flags.append(f"{base.assumptions['default_spread_held_cells']} held position-bars used the default spread because observed spread was missing")
        sr_b = S.sharpe(base.net)
        sc.numbers["risk_baseline"] = S.risk_summary(base.net)
        sc.numbers["sharpe_by_scenario"] = {k: S.sharpe(r.net) for k, r in res.items()}
        sc.numbers["gross_sharpe"] = S.sharpe(base.gross)
        sc.gates["baseline_net_sharpe"] = (sr_b >= th.min_baseline_net_sharpe, f"{sr_b:.2f} >= {th.min_baseline_net_sharpe}")
        sc.gates["pessimistic_net_positive"] = (res["pessimistic"].net.mean() > 0,
                                                f"pessimistic mean net {res['pessimistic'].net.mean()*1e4:.2f} bps/day")
        be = break_even_cost_multiplier(base)
        sc.numbers["break_even"] = be
        sc.gates["cost_break_even"] = (be["cost_multiple"] >= th.min_gross_to_cost,
                                       f"gross/cost {be['cost_multiple']:.2f} >= {th.min_gross_to_cost}; extra {be['extra_bps_per_side']:.1f} bps/side to zero")
        pl = implausible_performance(sr_b, th.max_plausible_sharpe)
        if not pl.passed:
            sc.hard_fail.append("leakage_suspicion: " + pl.detail)
        # ---- 3. multiple testing
        tc = self.reg.trial_count(cand.family)
        K = 1 if cand.search_returns is None else cand.search_returns.shape[1]
        n_eff = S.effective_trials(cand.search_returns) if K > 1 else 1
        n_trials = max(tc["variants"], n_eff, 1)
        var_sr = None
        if K > 1:
            srs = cand.search_returns.mean(0) / np.maximum(cand.search_returns.std(0, ddof=1), 1e-18)
            var_sr = float(np.var(srs, ddof=1))
        dsr = S.deflated_sharpe(base.net, n_trials, var_sr)
        sc.numbers["dsr"] = dsr
        sc.numbers["trials"] = {**tc, "search_variants": K, "effective_independent": n_eff, "used_for_deflation": n_trials}
        sc.gates["deflated_sharpe"] = (dsr["dsr"] >= th.min_dsr, f"DSR {dsr['dsr']:.3f} >= {th.min_dsr} (n_trials={n_trials})")
        null = S.circular_shift_null(base.Wexec, base.ret_matrix, th.n_perm, seed=seed)
        p_perm = S.perm_pvalue(float((base.Wexec * base.ret_matrix).sum(1).mean()), null)
        # shifting W preserves turnover/cost, so comparing gross to the shifted-gross null equals the net comparison
        sc.numbers["perm_p_placebo_timing"] = p_perm
        sc.gates["placebo_timing_permutation"] = (p_perm <= th.max_perm_p, f"p={p_perm:.4f} <= {th.max_perm_p}")
        if K > 1:
            D = cand.search_returns
            p_spa, p_rc = S.hansen_spa(D, th.n_boot, seed=seed), S.white_reality_check(D, th.n_boot, seed=seed)
            pbo = S.pbo_cscv(D)
            sc.numbers.update({"spa_p": p_spa, "rc_p": p_rc, "pbo": pbo["pbo"]})
            sc.gates["spa_reality_check"] = (max(p_spa, p_rc) <= th.max_spa_p, f"SPA p={p_spa:.3f}, RC p={p_rc:.3f}")
            sc.gates["pbo"] = (pbo["pbo"] <= th.max_pbo, f"PBO={pbo['pbo']:.2f} <= {th.max_pbo}")
        else:
            sc.flags.append("single variant supplied: SPA/RC/PBO not applicable; deflation uses registry trial count")
        sc.numbers["sharpe_ci95"] = S.sharpe_ci(base.net, B=th.n_boot, seed=seed)
        # ---- 4. parameter neighbourhood
        neigh = [q for q in cand.neighbors if q != cand.params]
        if neigh:
            nsr = [S.sharpe(run_backtest(panel, self._weights(cand, q, panel), base.exec).net) for q in neigh]
            pos = float(np.mean(np.array(nsr) > 0))
            ratio = float(np.median(nsr) / sr_b) if sr_b > 0 else 0.0
            sc.numbers["neighbor_sharpes"] = nsr
            sc.gates["parameter_neighbourhood"] = (pos >= th.min_neighbor_pos_frac and ratio >= th.min_neighbor_median_ratio,
                                                   f"{pos:.0%} of {len(neigh)} neighbours positive; median/chosen={ratio:.2f}")
            sc.dims["parameter_robustness"] = "PASS" if sc.gates["parameter_neighbourhood"][0] else "FAIL"
        else:
            sc.dims["parameter_robustness"] = "NOT TESTED"
            sc.flags.append("no parameter neighbourhood supplied")
        # ---- 5. trade concentration / perturbation
        conc = S.concentration(base.trades["pnl"].to_numpy()) if len(base.trades) else {"n_trades": 0}
        sc.numbers["concentration"] = conc
        if conc.get("n_trades", 0) >= 20:
            ok = (conc["top5_share"] <= th.max_top5_share or not np.isfinite(conc["top5_share"])) and conc["net_without_top1pct"] > 0
            sc.gates["trade_concentration"] = (bool(ok), f"top5 share {conc['top5_share']:.2f}; net w/o top1% {conc['net_without_top1pct']:.4f}")
        else:
            sc.inconclusive.append("too few trades for concentration analysis")
        # ---- 6. sub-period stability
        chunks = np.array_split(base.net, th.n_subperiods)
        pos = float(np.mean([c.mean() > 0 for c in chunks]))
        sc.numbers["subperiod_sharpes"] = [S.sharpe(c) for c in chunks]
        sc.gates["subperiod_stability"] = (pos >= th.min_subperiod_pos_frac, f"{pos:.0%} of {th.n_subperiods} sub-periods positive")
        # ---- 7. regimes (realised-vol terciles of the benchmark, measured with trailing data only)
        if cand.benchmark is not None and len(cand.benchmark) == n:
            b = cand.benchmark
            trail = np.array([b[max(0, t - 20):t].std() if t > 5 else np.nan for t in range(n)])
            qs = np.nanquantile(trail, [1 / 3, 2 / 3])
            reg = np.where(np.isnan(trail), -1, np.digitize(trail, qs))
            sc.numbers["regime_vol_sharpe"] = {["low", "mid", "high"][k]: S.sharpe(base.net[reg == k]) for k in range(3) if (reg == k).sum() > 20}
            fr = S.factor_regression(base.net, np.column_stack([b]), ["market"])
            sc.numbers["factor"] = fr
            sc.gates["factor_alpha"] = (fr["alpha_t"] >= th.min_alpha_t, f"alpha t={fr['alpha_t']:.2f}, market beta={fr['betas']['market']:.2f}")
            sc.dims["factor_independence"] = "PASS" if sc.gates["factor_alpha"][0] else "FAIL"
        else:
            sc.flags.append("no benchmark supplied: factor decomposition/regime analysis skipped")
        # ---- 8. ablations
        if cand.ablations:
            ab = {k: S.sharpe(run_backtest(panel, collect_weights(f(panel, cand.params), panel), base.exec).net) for k, f in cand.ablations.items()}
            sc.numbers["ablation_sharpes"] = ab
            for k, v in ab.items():
                if v >= 0.9 * sr_b:
                    sc.flags.append(f"ablation '{k}' leaves performance unchanged ({v:.2f} vs {sr_b:.2f}): component may be irrelevant")
        # ---- 9. delay fragility & capacity
        d = {0: sr_b}
        for L in (1, 2):
            r = run_backtest(panel, W, Exec(**{**asdict(base.exec), "latency_bars": base.exec.latency_bars + L}))
            d[L] = S.sharpe(r.net)
        dl = delay_fragility(d)
        sc.numbers["sharpe_by_delay"] = d
        if not dl.passed:
            sc.flags.append(dl.detail)
        cap = {}
        for c in capital_ladder:
            cap[c] = S.sharpe(run_backtest(panel, W, Exec(**{**asdict(base.exec), "capital": c})).net)
        sc.numbers["capacity_sharpe"] = cap
        # ---- 10. statistical power
        pw = S.power_at_sharpe(n, max(sr_b, 0.0))
        mds = S.min_detectable_sharpe(n)
        sc.numbers["power"] = {"n": n, "min_detectable_sharpe": mds, "power_at_observed": pw}
        sc.dims["statistical_power"] = "ADEQUATE" if pw >= th.min_power_for_claim else "LOW"
        if pw < th.min_power_for_claim:
            sc.inconclusive.append(f"low statistical power: sample can only reliably detect Sharpe >= {mds:.2f}")
        return self._finish(sc, cand, dataset_id, seed, panel)

    # ------------------------------------------------------------------ classification
    def _finish(self, sc: Scorecard, cand, dataset_id, seed, panel) -> Scorecard:
        failed = [k for k, (ok, _) in sc.gates.items() if not ok]
        # gates whose failure is what a small sample produces even for a real edge; all others are evidence against
        SIGNIFICANCE_ONLY = {"deflated_sharpe", "placebo_timing_permutation", "factor_alpha", "trade_concentration", "subperiod_stability"}
        sr_b = sc.numbers.get("sharpe_by_scenario", {}).get("baseline", 0.0)
        low_power = sc.dims.get("statistical_power") == "LOW"
        if sc.hard_fail:
            sc.classification = "REJECTED"
        elif not failed and not low_power:
            sc.classification = "ROBUST RESEARCH CANDIDATE (dev-only; locked OOS pending)"
        elif not failed:
            sc.classification = "INTERESTING BUT UNPROVEN"       # passes everything, sample too small to be conclusive
        elif set(failed) <= SIGNIFICANCE_ONLY and low_power and sr_b >= self.th.min_baseline_net_sharpe:
            sc.classification = "INTERESTING BUT UNPROVEN"       # insufficient evidence, not evidence against
        else:
            sc.classification = "REJECTED"                       # evidence against (or no supporting evidence)
        code_sha = sha256(cand.source or cand.name + canon(cand.params))
        self.reg.log_experiment(cand.hyp_id, cand.version, code_sha=code_sha, dataset_ids=[dataset_id], params=cand.params,
                                seed=seed, family=cand.family,
                                results={"classification": sc.classification, "hard_fail": sc.hard_fail,
                                         "gates": {k: bool(v[0]) for k, v in sc.gates.items()},
                                         "sharpe_baseline": sc.numbers.get("sharpe_by_scenario", {}).get("baseline")})
        return sc

    # -------------------------------------------------------------------------- locked OOS
    def final_test(self, cand: Candidate, dev_scorecard: Scorecard, panel_oos: Panel, *, dataset_id: str = "locked_oos",
                   disclose: bool = False) -> Scorecard:
        """Single-shot locked test. Refuses reruns for the same hypothesis lineage."""
        for e in self.reg.events("FINAL_TEST"):
            if e["payload"]["hyp_id"] == cand.hyp_id:
                raise PermissionError(f"lineage {cand.hyp_id} has already consumed its locked test "
                                      f"(v{e['payload']['version']}); new hypotheses need fresh data")
        if self.reg.contaminated(dataset_id):
            raise PermissionError(f"dataset {dataset_id} is contaminated and cannot serve as a locked test")
        if not dev_scorecard.classification.startswith("ROBUST"):
            raise PermissionError("candidate did not clear development gates; locked test not released")
        th = self.th
        W = self._weights(cand, cand.params, panel_oos)
        base = run_backtest(panel_oos, W, cand.exec_base)
        pess = run_backtest(panel_oos, W, Exec(**{**asdict(SCENARIOS["pessimistic"]), "mode": cand.exec_base.mode}))
        sr = S.sharpe(base.net)
        dev_sr = dev_scorecard.numbers["sharpe_by_scenario"]["baseline"]
        p = S.sign_flip_pvalue(base.net, seed=th.seed)
        ok = sr >= th.oos_min_sharpe and p <= th.oos_max_p and sr >= th.oos_min_ratio * dev_sr and S.sharpe(pess.net) >= 0
        out = Scorecard(cand.name + ":locked_oos")
        out.numbers = {"oos_sharpe": sr, "oos_p": p, "dev_sharpe": dev_sr, "oos_pess_sharpe": S.sharpe(pess.net),
                       "oos_n": len(base.net), "risk": S.risk_summary(base.net)}
        out.gates["oos_sharpe"] = (sr >= th.oos_min_sharpe, f"{sr:.2f} >= {th.oos_min_sharpe}")
        out.gates["oos_significance"] = (p <= th.oos_max_p, f"p={p:.4f} <= {th.oos_max_p}")
        out.gates["oos_pessimistic_nonneg"] = (S.sharpe(pess.net) >= 0, f"pessimistic OOS Sharpe {S.sharpe(pess.net):.2f}")
        out.gates["oos_decay"] = (sr >= th.oos_min_ratio * dev_sr, f"OOS/dev = {sr/dev_sr if dev_sr else float('nan'):.2f}")
        out.classification = "ROBUST RESEARCH CANDIDATE" if ok else "REJECTED"
        self.reg.append("FINAL_TEST", {"hyp_id": cand.hyp_id, "version": cand.version, "dataset_id": dataset_id,
                                       "classification": out.classification, "oos_sharpe": sr, "oos_p": p})
        if disclose:
            self.reg.mark_contaminated(dataset_id, "numeric OOS results disclosed to generator", cand.hyp_id)
        return out

    # ---------------------------------------------------------------- paper -> live gates
    def paper_gate(self, cand: Candidate, robust: Scorecard, paper_daily_net: np.ndarray, backtest_mean: float,
                   human_review_requested: bool = False) -> str:
        if not robust.classification.startswith("ROBUST"):
            return robust.classification
        th = self.th
        if len(paper_daily_net) < th.min_paper_days:
            return "ROBUST RESEARCH CANDIDATE"
        disc = abs(paper_daily_net.mean() - backtest_mean) / max(abs(backtest_mean), 1e-12)
        self.reg.append("PAPER", {"hyp_id": cand.hyp_id, "days": len(paper_daily_net), "paper_mean": float(paper_daily_net.mean()),
                                  "backtest_mean": float(backtest_mean), "discrepancy": float(disc)})
        if paper_daily_net.mean() <= 0 or disc > th.max_paper_discrepancy:
            return "INTERESTING BUT UNPROVEN"
        # LIVE CANDIDATE only means "worth a human's consideration"; this code can never authorise trading.
        return "LIVE CANDIDATE" if human_review_requested else "PAPER-VALIDATED CANDIDATE"


# ----------------------------------------------------------------------------- vault
class Vault:
    """Sealed store for the locked OOS panel: root-owned 0700 dir outside the repo when possible."""
    DEFAULT = Path("/var/lib/edgelab/vault")

    def __init__(self, registry: Registry, path: str | Path | None = None):
        self.reg = registry
        p = Path(path) if path else self.DEFAULT
        try:
            p.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            p = Path("vault")
            p.mkdir(exist_ok=True)
        os.chmod(p, 0o700)
        self.path = p

    def seal(self, name: str, panel: Panel) -> str:
        f = self.path / f"{name}.pkl"
        blob = pickle.dumps(panel)
        f.write_bytes(blob)
        os.chmod(f, 0o600)
        digest = hashlib.sha256(blob).hexdigest()
        self.reg.append("VAULT_SEAL", {"name": name, "sha256": digest, "n_bars": panel.T, "n_tickers": panel.N,
                                       "start": str(panel.ts[0]), "end": str(panel.ts[-1])})
        return digest

    def open(self, name: str) -> Panel:
        f = self.path / f"{name}.pkl"
        blob = f.read_bytes()
        seals = [e for e in self.reg.events("VAULT_SEAL") if e["payload"]["name"] == name]
        if not seals or seals[-1]["payload"]["sha256"] != hashlib.sha256(blob).hexdigest():
            raise EvaluatorTampered(f"vault object {name} does not match sealed hash")
        return pickle.loads(blob)
