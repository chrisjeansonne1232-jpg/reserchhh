"""Pre-discovery check 2: what did V2's split/discontinuity exclusions remove? (registered in PREDISCOVERY_DAILY_SWING_V2)

DIAGNOSTIC ONLY. Looks at the forward return of EXCLUDED names in a window that starts after the unobservable adjustment, relative to the median of raw PIT members
on the same date. It is not a strategy search and is not counted as a trial."""
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from edgelab.dsv2_ctx import build_state, check_baseline, load_ctx
from edgelab.predisc_spec import SPEC as PRE, SPEC_SHA256 as PRE_SHA
from edgelab.registry import Registry

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "audit" / "predisc"
reg = Registry(ROOT / "registry" / "registry.sqlite")
assert any(e["payload"].get("spec_sha256") == PRE_SHA for e in reg.events("NOTE"))
ctx = load_ctx(); st = build_state(ctx); check_baseline(st)
cube, t0, T = ctx.cube, ctx.t0, ctx.cube.T
WIN, H = 4, 60


def close_at(c, i, back=3):
    lo = max(0, i - back)
    ix = np.flatnonzero(np.isfinite(cube.close[lo:i + 1, c]))
    return (float(cube.close[lo + ix[-1], c]), lo + ix[-1]) if len(ix) else (np.nan, -1)


def has_claim(c, a, b):
    cs = ctx.claim_sessions.get(int(c))
    return cs is not None and bool(((cs > a) & (cs <= b)).any())


# earliest exclusion per ever-member spell
ex = pd.DataFrame(st["excl_rows"])
ever = st["member_raw"].any(0)
ex = ex[ex["spell"].map(lambda s: bool(ever[int(s)]))].sort_values("from_session").drop_duplicates("spell")
rows, dropped = [], {"no_endpoints": 0, "other_split_in_window": 0}
for r in ex.itertuples():
    c = int(r.spell)
    a = r.from_session + 2 * WIN if r.cause != "UNRECORDED_SPLIT_LIKE_DISCONTINUITY" else r.from_session       # post-window start / the jump session's own close
    if a + H >= T:
        dropped["no_endpoints"] += 1; continue
    p0, i0 = close_at(c, a)
    p1, i1 = close_at(c, a + H)
    if not (np.isfinite(p0) and i0 >= 0):
        dropped["no_endpoints"] += 1; continue
    stopped = not np.isfinite(p1) or i1 < a + H - 3
    if stopped:                                                # the name stops trading inside the window: use its last close (flagged), not an assumed terminal return
        ix = np.flatnonzero(np.isfinite(cube.close[a:a + H + 1, c]))
        p1, i1 = float(cube.close[a + ix[-1], c]), a + ix[-1]
    if has_claim(c, a, a + H):
        dropped["other_split_in_window"] += 1; continue
    m = st["member_raw"][a] & np.array([not has_claim(k, a, a + H) for k in range(cube.S)]) if False else None
    rows.append({"spell": c, "ticker": r.ticker, "cause": r.cause, "start_session": a, "start_date": ctx.sess[a].date(), "log_ret": float(np.log(p1 / p0)), "stopped_in_window": bool(stopped)})
df = pd.DataFrame(rows)
# benchmark: median raw-member 60-session log return on the same start session, members with a claim in the window excluded
bench = {}
for a in sorted(set(df["start_session"])):
    cols = np.flatnonzero(st["member_raw"][a])
    vals = []
    for c in cols:
        if has_claim(c, a, a + H):
            continue
        p0, i0 = close_at(c, a); p1, i1 = close_at(c, a + H)
        if np.isfinite(p0) and np.isfinite(p1) and i1 >= a + H - 3:
            vals.append(np.log(p1 / p0))
    bench[a] = (float(np.median(vals)), len(vals)) if vals else (np.nan, 0)
df["bench_median"] = df["start_session"].map(lambda a: bench[a][0]); df["bench_n"] = df["start_session"].map(lambda a: bench[a][1])
df = df[np.isfinite(df["bench_median"])].copy()
df["excess"] = df["log_ret"] - df["bench_median"]
rng = np.random.default_rng(0)


def summarize(d):
    if not len(d):
        return {"n": 0}
    x = d["excess"].to_numpy()
    boots = np.median(x[rng.integers(0, len(x), (2000, len(x)))], axis=1)
    return {"n": int(len(x)), "median_excess": float(np.median(x)), "mean_excess": float(x.mean()), "share_negative": float((x < 0).mean()),
            "ci95_median": [float(np.quantile(boots, .025)), float(np.quantile(boots, .975))], "share_stopped_in_window": float(d["stopped_in_window"].mean()),
            "median_bench": float(d["bench_median"].median())}


res = {"all": summarize(df), **{k: summarize(g) for k, g in df.groupby("cause")}, "excluding_stopped": summarize(df[~df["stopped_in_window"]])}
df.to_csv(OUT / "exclusion_bias_events.csv", index=False)
material = bool(abs(res["all"]["median_excess"]) > 0.02)
_ag = ex[ex["cause"] == "AGREED_SPLIT_TESTABLE_AMBIGUOUS"]["spell"].astype(int).tolist()
_c = ctx.cl[ctx.cl["spell"].isin(_ag) & (ctx.cl["verdict"] == "AMBIGUOUS")]
n_rev = int(_c.groupby("spell")["price_multiplier"].apply(lambda x: bool((x > 1).any())).sum())
subgroups = {k: v for k, v in res.items() if k not in ("all", "excluding_stopped") and v["n"] and v["ci95_median"][1] < 0 and abs(v["median_excess"]) > 0.02}      # CI entirely below zero and large
_payload = {"kind": "PREDISCOVERY_EXCLUSION_BIAS_RESULT", "experiment": PRE["name"], "spec_sha256": PRE_SHA, "n": res["all"]["n"], "median_excess": res["all"]["median_excess"],
                    "ci95_median": res["all"]["ci95_median"], "material_bias_flag_pooled_rule": material, "dropped": dropped,
                    "subgroups_with_ci_entirely_below_zero_and_abs_median_over_0.02": {k: {"n": v["n"], "median_excess": v["median_excess"], "ci95_median": v["ci95_median"]} for k, v in subgroups.items()},
                    "agreed_ambiguous_spells": len(_ag), "of_which_with_a_reverse_split_claim": n_rev}
if not any(e["payload"] == _payload for e in reg.events("NOTE")):                       # idempotent: a re-run with identical numbers adds nothing
    reg.append("NOTE", _payload)
fmt = lambda v: f"{v:+.4f}"
L = ["# Pre-discovery check 2: what the split/discontinuity exclusions removed (diagnostic, no pass/fail)", "",
     f"Registered plan `{PRE_SHA[:16]}...`. Population: universe-member spells excluded by V2's split/discontinuity rules (one row per spell, its earliest exclusion). "
     f"Window: 60 sessions of raw close-to-close log return starting AFTER the unobservable event window (split-ambiguous: claimed session + {WIN}; unrecorded jump: the jump session's own close). "
     "Benchmark: median 60-session log return of raw PIT members on the same start session (members with a split claim in the window excluded). Excess = name minus benchmark. "
     "Names that stop trading inside the window use their last close; no terminal return is assumed. This is not a trial and not a signal search.", "",
     f"Dropped before measurement: {dropped} (no usable endpoints, or another split claim inside the window).", "",
     "| group | n | median excess | mean excess | share negative | 95% CI of median | share stopping in window |", "|---|---|---|---|---|---|---|"]
for k, v in res.items():
    if v["n"]:
        L.append(f"| {k} | {v['n']} | {fmt(v['median_excess'])} | {fmt(v['mean_excess'])} | {v['share_negative']:.2f} | [{v['ci95_median'][0]:+.3f}, {v['ci95_median'][1]:+.3f}] | {v['share_stopped_in_window']:.2f} |")
L += ["", f"Median 60-session log return of the benchmark across events: {res['all']['median_bench']:+.4f}.", "",
      f"**Registered interpretation rule**: |median excess| > 0.02 is a material composition bias. Result: |{res['all']['median_excess']:.4f}| -> **{'MATERIAL' if material else 'not material by that rule'}**. "
      "The bootstrap interval is over a small number of names and is wide; 'not material' means 'not distinguishable from small', not 'zero'."]
if subgroups:
    L += ["", "**But the pooled figure hides a subgroup effect** (groups with a 95% CI entirely below zero and |median| > 0.02): "
          + "; ".join(f"`{k}`: n={v['n']}, median excess {v['median_excess']:+.3f}, CI [{v['ci95_median'][0]:+.3f}, {v['ci95_median'][1]:+.3f}]" for k, v in subgroups.items())
          + f". These are names whose split adjustment cannot be verified from prices ({n_rev} of the {len(_ag)} spells in that cause have a reverse-split claim); they subsequently underperformed the benchmark, so excluding them removes strong losers. "
            "The groups with positive medians offset them in the pooled median. Consequence for discovery: strategies that select extreme past losers (reversal longs, or momentum shorts) draw from exactly this pool, "
            "so their results must be read with this bias in mind; the pooled rule alone would understate it. The effect on a broad equal-weight book is small (a few names at a time)."]
(ROOT / "docs" / "PREDISCOVERY_EXCLUSION_BIAS.md").write_text("\n".join(L) + "\n")
print(json_ := {k: {kk: (round(vv, 4) if isinstance(vv, float) else vv) for kk, vv in v.items() if kk != "ci95_median"} for k, v in res.items()}, dropped, "material:", material)
