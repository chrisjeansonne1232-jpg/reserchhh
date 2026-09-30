"""Pre-discovery check 1: universe-parameter sweep (registered in PREDISCOVERY_DAILY_SWING_V2). No returns are used anywhere in this script."""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from edgelab.daily_swing_surv import pit_listing_coverage, terminal_exposure
from edgelab.dsv2_ctx import BASE, build_state, check_baseline, load_ctx
from edgelab.predisc_spec import SPEC as PRE, SPEC_SHA256 as PRE_SHA
from edgelab.registry import Registry

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "audit" / "predisc"
OUT.mkdir(parents=True, exist_ok=True)
reg = Registry(ROOT / "registry" / "registry.sqlite")
assert any(e["payload"].get("spec_sha256") == PRE_SHA for e in reg.events("NOTE")), "pre-discovery plan is not registered"
T0 = time.time()
log = lambda *a: print(f"[{time.time() - T0:5.0f}s]", *a, flush=True)
ctx = load_ctx()
cube, t0, T = ctx.cube, ctx.t0, ctx.cube.T
real = cube.real()
TH = {"R2b": 0.005, "R2c": 0.05, "R4c": 0.05, "R6d": 0.03}      # frozen V2 thresholds; R5b scaled to 0.8*top_n (see the registered clarification)
variants = [{"id": "baseline"}] + PRE["sweep"]["variants"]
rows, base_final = [], None
for v in variants:
    cfg = {**BASE, **{("min_price" if k == "min_last_close" else k): x for k, x in v.items() if k != "id"}}       # the registered spec names it min_last_close
    st = build_state(ctx, **cfg)
    if v["id"] == "baseline":
        check_baseline(st)
        base_final = st["member"].copy()
    m, mr = st["member"], st["member_raw"]
    size = m[t0:].sum(1)
    miss = m & ~real
    per = miss[t0:].sum(1) / np.maximum(1, m[t0:].sum(1))
    lb = cfg["lookback"]
    dvm = pd.DataFrame(cube.close * cube.volume).rolling(lb, min_periods=st["params"]["min_real"]).median().shift(1).to_numpy()
    both = m[t0:] & base_final[t0:]
    turn = np.mean([(mr[t] & ~mr[t - 1]).sum() / max(1, mr[t].sum()) for t in range(t0 + 1, T)])
    _, per_date = pit_listing_coverage(ctx.snaps, ctx.master, cube, mr)
    term_df, term_st = terminal_exposure(cube, m, t0, ctx.master)
    yrs = ctx.sess[t0:].year
    hazard = (term_df.groupby("year").size().reindex(sorted(set(yrs)), fill_value=0) / float(size.mean())).mean() if len(term_df) else 0.0
    r = {"variant": v["id"], **{k: cfg[k] for k in ("top_n", "lookback", "min_price")}, "size_min": int(size.min()), "size_median": int(np.median(size)),
         "R2b": float(miss[t0:].sum() / m[t0:].sum()), "R2c": float(per.max()), "R4c": float(st["removed_split"].sum() / mr.sum()), "R6d": float(st["removed_id"].sum() / mr.sum()),
         "R5b_scaled": float((size >= 0.8 * cfg["top_n"]).mean()), "median_member_trailing_dollar_volume": float(np.median(dvm[mr & (np.arange(T)[:, None] >= t0)])),
         "containment_vs_baseline": float(both.sum() / min(m[t0:].sum(), base_final[t0:].sum())), "mean_daily_entry_share": float(turn),
         "expected_missing_members_median": float(per_date["expected_missing_members"].median()), "expected_missing_share_of_universe": float(per_date["expected_missing_members"].median() / cfg["top_n"]),
         "upper_bound_missing_members_median": float(per_date["upper_bound_missing_members"].median()), "member_spells_ended": int(term_st["member_spells_ended"]),
         "mean_annual_ending_hazard": float(hazard), "split_exclusion_events": int(len(st["excl_rows"]))}
    r["passes"] = bool(r["R2b"] <= TH["R2b"] and r["R2c"] <= TH["R2c"] and r["R4c"] <= TH["R4c"] and r["R6d"] <= TH["R6d"] and r["R5b_scaled"] >= 0.99)
    rows.append(r)
    log(v["id"], {k: (round(x, 4) if isinstance(x, float) else x) for k, x in r.items() if k in ("size_min", "size_median", "R2b", "R2c", "R4c", "R6d", "R5b_scaled", "passes")})
df = pd.DataFrame(rows)
df.to_csv(OUT / "sweep_metrics.csv", index=False)
n_pass_var = int(df[df["variant"] != "baseline"]["passes"].sum())
proceed = bool(df.loc[df["variant"] == "baseline", "passes"].iloc[0] and n_pass_var >= 6)
verdict = {"baseline_passes": bool(df.loc[df["variant"] == "baseline", "passes"].iloc[0]), "variants_passing": n_pass_var, "of": len(df) - 1, "criterion_met": proceed}
reg.append("NOTE", {"kind": "PREDISCOVERY_SWEEP_RESULT", "experiment": PRE["name"], "spec_sha256": PRE_SHA, **verdict})
fmt = lambda x: f"{x:.4f}" if isinstance(x, float) else str(x)
L = ["# Pre-discovery check 1: universe-parameter sweep (no returns used)", "",
     f"Registered plan `{PRE_SHA[:16]}...`. One-at-a-time variations around the frozen V2 baseline; the spell-level split resolution and identity mask are unchanged, membership and the membership-dependent discontinuity exclusions are recomputed for each variant.",
     "Thresholds are V2's (R2b <= 0.5%, R2c <= 5%, R4c <= 5%, R6d <= 3%); R5b is scaled to 0.8 x top_n on >= 99% of sessions (registered clarification, seq 112).", "",
     "| variant | top_n | lookback | min price | size min/median | R2b | R2c | R4c | R6d | R5b (scaled) | passes |", "|---|---|---|---|---|---|---|---|---|---|---|"]
for r in rows:
    L.append(f"| {r['variant']} | {r['top_n']} | {r['lookback']} | {r['min_price']} | {r['size_min']}/{r['size_median']} | {r['R2b']:.4%} | {r['R2c']:.3%} | {r['R4c']:.3%} | {r['R6d']:.3%} | {r['R5b_scaled']:.4f} | **{'PASS' if r['passes'] else 'FAIL'}** |")
L += ["", "Descriptive metrics (not gated):", "", "| variant | median trailing $ volume of members | containment vs baseline | daily entry share | expected missing members (median) | as share of universe | upper bound | member spells ended | mean annual ending hazard |", "|---|---|---|---|---|---|---|---|---|"]
for r in rows:
    L.append(f"| {r['variant']} | {r['median_member_trailing_dollar_volume']:,.0f} | {r['containment_vs_baseline']:.3f} | {r['mean_daily_entry_share']:.4f} | {r['expected_missing_members_median']:.1f} | {r['expected_missing_share_of_universe']:.3%} | {r['upper_bound_missing_members_median']:.0f} | {r['member_spells_ended']} | {r['mean_annual_ending_hazard']:.3%} |")
L += ["", f"**Registered criterion**: baseline and at least 6 of the 7 variants pass -> baseline passes: {verdict['baseline_passes']}; variants passing: {n_pass_var}/{len(df) - 1}; **criterion met: {proceed}**."]
(ROOT / "docs" / "PREDISCOVERY_SWEEP.md").write_text("\n".join(L) + "\n")
log("verdict", verdict)
