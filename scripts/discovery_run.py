"""DAILY_SWING_V2 discovery round 1, dev phase (search -> select -> evaluate). The plan is frozen in edgelab/discovery_spec.py and registered; this refuses to run otherwise.
The locked OOS is NOT touched here."""
import itertools
import json
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from edgelab import stats as S
from edgelab.discovery_spec import FAMILY, SPEC, SPEC_SHA256
from edgelab.dsv2_ctx import build_state, check_baseline, load_ctx
from edgelab.dsv2_panel import TERMINAL_SCENARIOS, build_panel, unobservable_holding_bars, with_terminal
from edgelab.engine import BASELINE, SCENARIOS, Exec, collect_weights, run_backtest
from edgelab.evaluator import Candidate, Evaluator
from edgelab.registry import Registry, sha256
from edgelab.swing_strategies import make_build

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "audit" / "discovery_r1"
OUT.mkdir(parents=True, exist_ok=True)
reg = Registry(ROOT / "registry" / "registry.sqlite")
assert any(e["payload"].get("spec_sha256") == SPEC_SHA256 for e in reg.events("NOTE")), "discovery plan is not registered"
T0 = time.time()
log = lambda *a: print(f"[{time.time() - T0:5.0f}s]", *a, flush=True)
KIND = {"swing_reversal": "rev", "swing_momentum": "mom", "swing_volshock": "volshock", "swing_overnight": "overnight"}
ctx = load_ctx(); st = build_state(ctx); check_baseline(st)
W_DEV = SPEC["windows"]["dev"]
panel_s1, meta = build_panel(ctx, st, *W_DEV, terminal=TERMINAL_SCENARIOS["S1_shumway"])
sess_dev = pd.DatetimeIndex(panel_s1.ts)
tr_end = int(sess_dev.searchsorted(pd.Timestamp(SPEC["windows"]["train"][1]), side="right"))
log(f"dev panel {panel_s1.T} x {panel_s1.N}; train sessions {tr_end}, validation {panel_s1.T - tr_end}; ended {meta['ended_spells']}, mask-terminated {meta['mask_terminated_spells']}")

# ------------------------------------------------------------------ search: all 29 variants, logged as trials
grids = []
for fam, v in SPEC["families"].items():
    keys = list(v["grid"])
    for vals in itertools.product(*(v["grid"][k] for k in keys)):
        grids.append((fam, v["hyp"], dict(zip(keys, vals))))
assert len(grids) == SPEC["n_variants_total"]
rows, NET, WEIGHTS = [], [], {}
for i, (fam, hyp, params) in enumerate(grids):
    W = collect_weights(make_build(meta, KIND[fam])(panel_s1, params), panel_s1)
    res = run_backtest(panel_s1, W, BASELINE)
    net = res.net
    NET.append(net); WEIGHTS[i] = W
    tr, va = net[:tr_end], net[tr_end:]
    r = {"i": i, "family": fam, "hyp": hyp, **params, "train_net_sharpe": S.sharpe(tr), "val_net_sharpe": S.sharpe(va), "dev_net_sharpe": S.sharpe(net), "dev_gross_sharpe": S.sharpe(res.gross),
         "mean_daily_turnover": float(res.turnover.mean()), "mean_cost_bps_per_day": float(res.cost.mean() * 1e4)}
    rows.append(r)
    reg.log_experiment(hyp, 1, code_sha=sha256(f"swing:{KIND[fam]}"), dataset_ids=["dev_2019_2024"], params={"family": fam, **params}, seed=SPEC_SHA256[:8] and 12345, family=FAMILY,
                       results={"phase": "SEARCH", "train_net_sharpe": r["train_net_sharpe"], "val_net_sharpe": r["val_net_sharpe"], "dev_net_sharpe": r["dev_net_sharpe"]}, status="SEARCH")
    log(f"{i + 1:2d}/29 {fam} {params}: train {r['train_net_sharpe']:+.2f} val {r['val_net_sharpe']:+.2f} gross {r['dev_gross_sharpe']:+.2f} turnover {r['mean_daily_turnover']:.3f}")
tab = pd.DataFrame(rows); tab.to_csv(OUT / "search_table.csv", index=False)
NETM = np.column_stack(NET); np.save(RAW / "dsv2_discovery_r1_search_returns.npy", NETM)

# ------------------------------------------------------------------ select one per family on TRAIN, evaluate with the frozen evaluator
ev = Evaluator(reg)
bench = meta["benchmark"]
summary = []
for fam, v in SPEC["families"].items():
    t = tab[tab["family"] == fam].copy()
    best = t.sort_values(["train_net_sharpe", "mean_daily_turnover"], ascending=[False, True]).iloc[0]
    keys = list(v["grid"])
    chosen = {k: (best[k] if not isinstance(best[k], (np.floating, float)) else best[k]) for k in keys}
    chosen = {k: (int(x) if float(x).is_integer() else float(x)) for k, x in chosen.items()}
    neigh = []
    for k in keys:
        vals = v["grid"][k]
        j = vals.index(chosen[k])
        for jj in (j - 1, j + 1):
            if 0 <= jj < len(vals):
                neigh.append({**chosen, k: vals[jj]})
    cand = Candidate(name=f"{fam}:{chosen}", build=make_build(meta, KIND[fam]), params=chosen, hyp_id=v["hyp"], version=1, neighbors=[chosen] + neigh, exec_base=BASELINE,
                     search_returns=NETM, family=FAMILY, benchmark=bench)
    log(f"evaluating {cand.name} (train {best['train_net_sharpe']:+.2f}, val {best['val_net_sharpe']:+.2f})")
    sc = ev.evaluate_dev(cand, panel_s1, dataset_id="dev_2019_2024")
    sc.flags.append("SUBSTITUTION: the evaluator's survivorship hard gate was fed the delisted names that were ever universe members (a subset of the panel), so it passes trivially; the real safeguards are S1/S2 terminal returns and the V2 residual-survivorship limitation")
    # terminal-return scenarios and unobservable holding bars for the chosen variant
    idx = int(tab[(tab["family"] == fam) & (tab[keys] == pd.Series(chosen)).all(axis=1)]["i"].iloc[0])
    W = WEIGHTS[idx]
    sc_res = {}
    for name, val in TERMINAL_SCENARIOS.items():
        pnl = with_terminal(panel_s1, meta, val)
        r_b, r_p = run_backtest(pnl, W, BASELINE), run_backtest(pnl, W, Exec(**{**BASELINE.__dict__, **SCENARIOS["pessimistic"].__dict__, "mode": BASELINE.mode}))
        sc_res[name] = {"baseline_net_sharpe": S.sharpe(r_b.net), "pessimistic_net_sharpe": S.sharpe(r_p.net), "baseline_mean_bps_day": float(r_b.net.mean() * 1e4)}
    unobs = unobservable_holding_bars(panel_s1, run_backtest(panel_s1, W, BASELINE).Wexec)
    summary.append({"family": fam, "chosen": chosen, "train_sharpe": float(best["train_net_sharpe"]), "val_sharpe": float(best["val_net_sharpe"]), "classification": sc.classification,
                    "hard_fail": sc.hard_fail, "gates": {k: [bool(g[0]), g[1]] for k, g in sc.gates.items()}, "flags": sc.flags, "inconclusive": sc.inconclusive,
                    "numbers": {k: (v_ if isinstance(v_, (int, float, str, list, dict)) else str(v_)) for k, v_ in sc.numbers.items() if k in ("sharpe_by_scenario", "gross_sharpe", "dsr", "trials", "perm_p_placebo_timing", "spa_p", "rc_p", "pbo", "sharpe_ci95", "subperiod_sharpes", "break_even", "power", "sharpe_by_delay", "capacity_sharpe", "factor")},
                    "terminal_scenarios": sc_res, "unobservable_holding": unobs})
    log(f"   -> {sc.classification}; hard_fail {len(sc.hard_fail)}; gates failed {[k for k, g in sc.gates.items() if not g[0]]}")
json.dump(summary, open(OUT / "dev_summary.json", "w"), indent=1, default=str)
log("done")
