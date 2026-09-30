"""DAILY_SWING_V3 audit (corrects V2 after the adversarial review): runs the frozen V3 requirements and reports the gate status. Does NOT start strategy discovery.

Order: verify the frozen spec hash (refuse otherwise) -> cube + point-in-time universe -> empirical split resolution -> unrecorded discontinuities ->
exclusions -> measure every requirement -> quantify residual survivorship -> disposition existing MATERIAL gaps (only where the scope evidence supports it)
-> evaluate the gate. AUDIT_DRY_RUN=1 works on a temporary registry copy and writes into it (nothing committed is touched).
"""
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from edgelab.daily_swing import (DailySwingGate, build_claims, build_cube, evaluate_requirements, member_pairs, pit_membership, resolve_claims,
                                 unrecorded_discontinuities)
from edgelab.daily_swing_identity import boundaries, identity_mask, observations, timeline_violations
from edgelab.daily_swing_v3_spec import GATE_NAME, SPEC, SPEC_SHA256
from edgelab.dsv3_ctx import BIG, build_ctx3, load_ctx3, resolve_twins, state3
from edgelab.daily_swing_surv import glued_spells, instrument_mix, pit_listing_coverage, terminal_exposure
from edgelab.integrity import MATERIAL, Gap, GapLedger, MarketCalendar, check_daily_ohlc, check_stale_daily
from edgelab.registry import Registry

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
DRY = bool(os.environ.get("AUDIT_DRY_RUN"))
if DRY:
    tmp = Path(tempfile.mkdtemp())
    shutil.copy(ROOT / "registry" / "registry.jsonl", tmp / "registry.jsonl")
    reg, OUT, AUD = Registry(tmp / "registry.sqlite"), tmp / "DAILY_SWING_V3_AUDIT.md", tmp / "audit"
else:
    reg, OUT, AUD = Registry(ROOT / "registry" / "registry.sqlite"), ROOT / "docs" / "DAILY_SWING_V3_AUDIT.md", ROOT / "data" / "audit" / "daily_swing_v3"
AUD.mkdir(parents=True, exist_ok=True)
T_START = time.time()


def md_table(df: pd.DataFrame) -> str:
    cols = [df.index.name or ""] + list(df.columns) if df.index.name or not isinstance(df.index, pd.RangeIndex) else list(df.columns)
    d_ = df.reset_index() if len(cols) > len(df.columns) else df
    rows = ["| " + " | ".join(str(c) for c in d_.columns) + " |", "|" + "---|" * len(d_.columns)]
    rows += ["| " + " | ".join(f"{v:.4f}" if isinstance(v, float) else str(v) for v in r) + " |" for r in d_.itertuples(index=False)]
    return "\n".join(rows)

log = lambda *a: print(f"[{time.time() - T_START:5.0f}s]", *a, flush=True)

# ---------------------------------------------------------------- 0. the requirements must be exactly the frozen ones
frozen = [e for e in reg.events("NOTE") if e["payload"].get("spec_sha256") == SPEC_SHA256 and e["payload"].get("experiment") == GATE_NAME]
superseded = [e for e in reg.events("NOTE") if e["payload"].get("superseded_spec_sha256") == SPEC_SHA256]
if superseded:
    sys.exit("REFUSING TO RUN: this spec hash has been SUPERSEDED in the registry.")
if not frozen:
    sys.exit("REFUSING TO RUN: the current SPEC hash is not registered. Run scripts/freeze_daily_swing_v3_requirements.py (a changed spec needs a new version).")
log("spec verified against registry seq", frozen[0]["seq"], SPEC_SHA256[:12])

# ---------------------------------------------------------------- 1-4. the V3 pipeline: twins -> cube -> claims (agreed tolerance) -> causal identity mask -> PIT ranking -> final universe
prov_d = json.loads((ROOT / "data/samples/alpaca_daily_universe.provenance.json").read_text())
d_raw = pd.read_parquet(RAW / "alpaca_daily_all.parquet")
ctx = load_ctx3()
st = state3(ctx)
d, master, LAST, sess, cube, cube_stats = ctx.daily, ctx.master, ctx.last, ctx.sess, ctx.cube, ctx.cube_stats
T, S, t0 = cube.T, cube.S, ctx.t0
claims, cl, ev, claim_sessions = ctx.claims, ctx.cl, ctx.ev, ctx.claim_sessions
snaps, obs, bnd = ctx.snaps, ctx.obs, ctx.bnd
snap_files = sorted((RAW / "massive_pit_master").glob("snapshot_*.parquet"))
expected_dates = json.loads((ROOT / "data/samples/massive_pit_master.provenance.json").read_text())["dates"]
snaps_complete = len(snap_files) == len(expected_dates) and len(snap_files) > 0
bst = {"boundaries": int(len(bnd)), "observations": int(len(obs)), "boundaries_by_key_type": bnd["key_type"].value_counts().to_dict() if len(bnd) else {}}
bnd.to_csv(AUD / "identity_boundaries.csv.gz", index=False)
sm = pd.read_parquet(RAW / "massive_splits_since_2016.parquet")
sa = pd.read_parquet(RAW / "alpaca_splits.parquet")
sa = pd.DataFrame({"ticker": sa["symbol"], "execution_date": sa["ex_date"], "split_from": sa["old_rate"], "split_to": sa["new_rate"]})
member_raw, disc, excl_from = st["member_raw"], st["disc"], st["excl_from"]
member_after_excl, removed, removed_id, member = st["member_after_excl"], st["removed_split"], st["removed_id"], st["member"]
id_tail, id_win, id_all = ctx.id_tail, ctx.id_win, ctx.id_tail
UNIVERSE_TICKERS = set(master["ticker"])
ever_raw = member_raw.any(0)
ev["ever_member"] = [bool(ever_raw[s_]) if s_ >= 0 else False for s_ in ev["spell"]]
DS = f"dsv3_panel_{prov_d['parts_sha256'][:8]}_{SPEC_SHA256[:8]}"
excl = pd.DataFrame([{**r_, "from_date": sess[max(0, r_["from_session"])].date(), "ever_member": bool(ever_raw[r_["spell"]])} for r_ in st["excl_rows"]])
tt = np.arange(T)[:, None]
ncell_raw, ncell_removed = int(member_raw.sum()), int(removed.sum())
size = member[t0:].sum(1)
log(f"twins {ctx.twin_stats}; claims {len(claims)}; events {len(ev)} ({ev['verdict'].value_counts().to_dict()}, actions {ev['action'].value_counts().to_dict()}); unrecorded large-jump adjustments {len(st['extra_adj'])}")
log(f"final member cells {int(member.sum()):,}; removed by split exclusions {ncell_removed:,} ({ncell_removed / ncell_raw:.2%}); identity TAIL mask {int(removed_id.sum()):,} ({removed_id.sum() / ncell_raw:.2%}); "
    f"retained unresolved-window cells {int(st['retained_window'].sum()):,}; universe size min/median {size.min()}/{int(np.median(size))}")

# ---------------------------------------------------------------- 5. measure the requirements
real = cube.real()
M, D = {}, {}
# R1
bad_vol = int((member & real & ~(cube.volume > 0)).sum())
non_cs_spells = sorted({str(t) for t in cube.spell_ticker if t not in UNIVERSE_TICKERS})
non_cs = int(sum(int(member[:, c_].sum()) for c_, t in enumerate(cube.spell_ticker) if t not in UNIVERSE_TICKERS))    # R1 is about PANEL cells: member cells of a non-CS spell
pre_window = int(member[:t0].sum())
M["R1"] = bad_vol + non_cs + pre_window
D["R1"] = f"member cells with volume<=0: {bad_vol}; member cells of spells not in the CS master: {non_cs} (spells outside the master: {non_cs_spells}, returned by Alpaca though not requested); member cells before the window: {pre_window}; placeholder bars set aside (never cells): {cube_stats['placeholder_bars_not_cells']:,}"
# R2
cnt = real[t0:].sum(1)
med = float(np.median(cnt))
partial = int(((cnt < 0.5 * med) | (cnt == 0)).sum())
M["R2a"] = partial
D["R2a"] = f"{len(cnt)} sessions; median real bars/session {med:.0f}; min {int(cnt.min())}; sessions below 50% of the median: {partial}"
miss = member & ~real
share = float(miss[t0:].sum() / max(1, member[t0:].sum()))
per_sess = miss[t0:].sum(1) / np.maximum(1, member[t0:].sum(1))
M["R2b"], M["R2c"] = share, float(per_sess.max())
D["R2b"] = f"{int(miss[t0:].sum()):,} of {int(member[t0:].sum()):,} member cells have no real bar"
D["R2c"] = f"worst session {sess[t0 + int(per_sess.argmax())].date()}: {per_sess.max():.2%}"
# R3
o, h, l, c = (cube.open[member & real], cube.high[member & real], cube.low[member & real], cube.close[member & real])
viol = int(((h < l - 1e-9) | (h < np.maximum(o, c) - 1e-9) | (l > np.minimum(o, c) + 1e-9) | (o <= 0) | (c <= 0) | (h <= 0) | (l <= 0)).sum()) + cube_stats["duplicate_ticker_session_keys"]
M["R3"] = viol
D["R3"] = f"{len(o):,} member cells checked; duplicate (ticker,session) keys in the whole store: {cube_stats['duplicate_ticker_session_keys']}"
# R4
valid_verdicts = {"CONFIRMED", "REFUTED", "AMBIGUOUS", "NO_PRICE_DATA"}
M["R4a"] = int((~cl["verdict"].isin(valid_verdicts)).sum() + (len(cl) != len(claims)))
D["R4a"] = f"{len(claims)} claims in the window ({claims['source'].value_counts().to_dict()}); every claim has a verdict"
still = 0
for r in ev[ev["action"] == "EXCLUDE_SPELL"].itertuples():
    if r.spell >= 0:
        still += int(member[max(0, r.exclude_from_session):, r.spell].sum())
M["R4b"] = still
D["R4b"] = (f"construction check. Jumps are NEVER excluded (candidates {disc['class'].value_counts().to_dict()}); large unrecorded splits adjusted: {len(st['extra_adj'])}; ambiguous split events excluded: {int((ev['action'] == 'EXCLUDE_SPELL').sum())}; "
            f"agreed, untestable-small, accepted as corroborated-but-unverified: {int((ev['action'] == 'ACCEPT_CORROBORATED_UNVERIFIED').sum())}")
M["R4c"] = ncell_removed / max(1, ncell_raw)
D["R4c"] = f"{ncell_removed:,} of {ncell_raw:,} member cells removed; {int((member_raw.any(0) & (excl_from < BIG)).sum())} of {int(ever_raw.sum())} member spells affected"
# R5a (ranking) and R5c (FINAL panel): rebuild the whole pipeline from bars and listings truncated at random cuts
rng = np.random.default_rng(0)
cuts = sorted(int(x) for x in rng.choice(np.arange(t0 + 150, T - 5), 3, replace=False))
def _cells(cb, m, upto):
    """member cells as bar content (session, open, close, volume): a ticker label is not part of the cell"""
    r_, c_ = np.nonzero(m[:upto + 1])
    return set(zip(r_.tolist(), np.round(cb.open[r_, c_], 6).tolist(), np.round(cb.close[r_, c_], 6).tolist(), cb.volume[r_, c_].tolist()))


diffs_raw, worst_share, per_cut = 0, 0.0, []
for cut in cuts:
    c3 = build_ctx3(d_raw[d_raw["date"] <= sess[cut]], master, snaps[snaps["snapshot_date"] <= sess[cut]], sm, sa, last=sess[cut], current_master_obs=False)
    s3 = state3(c3)
    a_raw, b_raw = _cells(cube, member_raw, cut), _cells(c3.cube, s3["member_raw"], cut)
    a_fin, b_fin = _cells(cube, member, cut), _cells(c3.cube, s3["member"], cut)
    diffs_raw += len(a_raw ^ b_raw)
    share_ = len(a_fin ^ b_fin) / max(1, len(a_fin))
    worst_share = max(worst_share, share_)
    per_cut.append({"cut": str(sess[cut].date()), "raw_membership_differences": len(a_raw ^ b_raw), "final_cells": len(a_fin), "final_cell_differences": len(a_fin ^ b_fin), "share": share_})
    log(f"truncated pipeline at {sess[cut].date()}: raw diffs {len(a_raw ^ b_raw)}; final cells {len(a_fin):,}, differing {len(a_fin ^ b_fin):,} ({share_:.4%})")
M["R5a"] = diffs_raw
D["R5a"] = f"cuts {[str(sess[c].date()) for c in cuts]}; the whole pipeline rebuilt from truncated bars/listings; raw (ranked) membership differences summed over cuts"
M["R5c"] = float(worst_share)
D["R5c"] = f"FINAL panel, whole pipeline rebuilt from truncated data (no current-master observation): {per_cut}"
pd.DataFrame(per_cut).to_csv(AUD / "pit_final_panel_truncation.csv", index=False)
M["R5b"] = float((size >= 800).mean())
D["R5b"] = f"universe size after exclusions: min {size.min()}, median {int(np.median(size))}, share of sessions >= 800: {(size >= 800).mean():.4f}"
# R6
bad_span = 0
cs = np.vstack([np.zeros((1, S), dtype=np.int32), np.cumsum(real, axis=0, dtype=np.int32)])
cols_by_ticker: dict[str, list[int]] = {}
for c_, t_ in enumerate(cube.spell_ticker):
    cols_by_ticker.setdefault(str(t_), []).append(c_)
for tk, cols in cols_by_ticker.items():
    if len(cols) < 2:
        continue
    for c_ in cols:
        ts_ = np.flatnonzero(member[:, c_])
        for c2 in cols:
            if c2 != c_ and len(ts_):
                lo = np.maximum(0, ts_ - 60)
                bad_span += int(((cs[ts_, c2] - cs[lo, c2]) > 0).sum())
M["R6a"] = bad_span
D["R6a"] = f"{sum(1 for v in cols_by_ticker.values() if len(v) > 1)} tickers have more than one spell; member cells whose 60-session lookback holds a bar of another spell of the same ticker: {bad_span}"
ret = cube.close[1:] / cube.close[:-1] - 1
first_bar = np.zeros((T, S), dtype=bool)
first_bar[cube.first, np.arange(S)] = True
across = int((np.isfinite(ret) & first_bar[1:]).sum())      # a return whose end point is the first real bar of a spell needs a previous real bar of that spell: impossible by construction
M["R6b"] = across
D["R6b"] = "returns are computed inside a spell only: a spell's first bar has no predecessor in its column"
if snaps_complete:
    viol, viol_df = timeline_violations(cube, member, obs, ambiguous_ok=True)
    viol_nomask, _ = timeline_violations(cube, member_after_excl, obs, ambiguous_ok=True)          # the SAME check without the tail mask
    tickers_b = set(bnd["ticker"])
    cells_checked = int(sum(member[:, c_].sum() for c_, t_ in enumerate(cube.spell_ticker) if str(t_) in tickers_b))
    viol_df.to_csv(AUD / "identity_timeline_violations.csv", index=False)
    M["R6c"] = int(viol)
    D["R6c"] = (f"construction check. {bst['boundaries']} boundaries from {bst['observations']:,} observations; {int(viol)} unmasked member cells see two different KNOWN issuer labels "
                f"(examined {cells_checked:,} member cells of boundary tickers; without the tail mask the same check finds {int(viol_nomask):,})")
    M["R6d"] = float(st["retained_window"].sum() / max(1, member.sum()))
    D["R6d"] = f"{int(st['retained_window'].sum()):,} of {int(member.sum()):,} final member cells sit inside unresolved hand-over windows and are RETAINED (may mix two issuers)"
    M["R6f"] = float(removed_id.sum() / max(1, ncell_raw))
    D["R6f"] = f"causal tail mask removes {int(removed_id.sum()):,} of {ncell_raw:,} raw member cells"
else:
    M["R6c"] = M["R6d"] = M["R6f"] = None
    D["R6c"] = D["R6d"] = D["R6f"] = f"PIT snapshots incomplete ({len(snap_files)}/{len(expected_dates)})"
_tt, _cc = np.nonzero(member)
_df = pd.DataFrame({"t": _tt, "o": cube.open[_tt, _cc], "h": cube.high[_tt, _cc], "l": cube.low[_tt, _cc], "c": cube.close[_tt, _cc], "v": cube.volume[_tt, _cc]}).dropna()
_dupmask = _df.duplicated(["t", "o", "h", "l", "c", "v"], keep=False)
M["R6e"] = int(_dupmask.sum())
D["R6e"] = f"{len(ctx.twins):,} twin pairs resolved before ranking ({ctx.twin_stats['twin_cells_dropped']:,} duplicate bars dropped); {int(_dupmask.sum())} final member cells still have a bit-identical twin among members"
ctx.twins.to_csv(AUD / "twin_pairs_resolved.csv.gz", index=False)
# R7
xv_path, xv_prov = RAW / "massive_xval_universe_daily.parquet", ROOT / "data/samples/massive_xval_universe_daily.provenance.json"
if xv_path.exists():
    xv = pd.read_parquet(xv_path)
    xv = xv[xv["volume"] > 0]
    rows = []
    for tk in sorted(xv["ticker"].unique()):
        for c_ in cols_by_ticker.get(tk, []):
            ix = np.flatnonzero(real[:, c_])
            rows.append(pd.DataFrame({"ticker": tk, "date": sess[ix], "close_a": cube.close[ix, c_]}))
    al = pd.concat(rows)
    mm = al.merge(xv[["ticker", "date", "close"]], on=["ticker", "date"], how="inner")
    mm["bad"] = (mm["close_a"] / mm["close"] - 1).abs() > 0.005
    per = mm.groupby("ticker")["bad"].mean()
    M["R7a"] = float(mm["bad"].mean()) if (len(mm) >= 5000 and mm["ticker"].nunique() >= 25) else None
    M["R7b"] = float(per.max()) if len(per) else None
    both = al[al["date"] >= xv["date"].min()].merge(xv[["ticker", "date"]], on=["ticker", "date"], how="outer", indicator=True)
    only_a, only_m = int((both["_merge"] == "left_only").sum()), int((both["_merge"] == "right_only").sum())
    D["R7a"] = f"{len(mm):,} overlapping bars, {mm['ticker'].nunique()} names ({xv_prov.exists() and json.loads(xv_prov.read_text())['start']}..{LAST.date()}); bars only in Alpaca: {only_a}; only in Massive: {only_m}"
    D["R7b"] = f"worst name: {per.idxmax() if len(per) else None} {per.max() if len(per) else float('nan'):.2%}"
else:
    M["R7a"] = M["R7b"] = None
    D["R7a"] = D["R7b"] = "universe cross-validation sample not ingested"

# ---------------------------------------------------------------- 6. residual survivorship (KNOWN LIMITATION): measure, bound, record
surv = {"recorded": False}
if len(snap_files) and len(snap_files) == len(expected_dates):
    per_name, per_date = pit_listing_coverage(snaps, master, cube, member_raw)
    per_name[~per_name["has_bars"]].to_csv(AUD / "survivorship_listed_names_without_bars.csv.gz", index=False)
    per_date.to_csv(AUD / "survivorship_pit_coverage_by_snapshot.csv", index=False)
    glue_v1 = glued_spells(snaps, cube, member_raw)            # V1's FIGI-based finding, kept for comparison only
    term_df, term_st = terminal_exposure(cube, member, t0, master)
    term_df.to_csv(AUD / "terminal_exposure_member_spells_ended.csv", index=False)
    mix = instrument_mix(cube, member_raw, t0, master)
    med_d = per_date.median(numeric_only=True)
    yrs = sess[t0:].year
    avg_size = float(np.mean(size))
    hazard = term_df.groupby("year").size().reindex(sorted(set(yrs)), fill_value=0) / avg_size
    # exclusion composition (composition only; forward returns are deliberately NOT computed here)
    ended_all = float((cube.last[member_raw.any(0)] < T - 6).mean())
    ex_rows = excl[excl["ever_member"]] if len(excl) else excl                                  # one row per exclusion EVENT (a spell can have several)
    ex_ever = ex_rows.sort_values("from_session").drop_duplicates("spell") if len(ex_rows) else ex_rows   # one row per distinct SPELL (its earliest exclusion)
    ended_ex = float((cube.last[ex_ever["spell"].to_numpy(dtype=int)] < T - 6).mean()) if len(ex_ever) else float("nan")
    prior = []
    for r in ex_ever.itertuples():
        s = int(r.from_session)
        ix = np.flatnonzero(np.isfinite(cube.close[:max(1, s), r.spell]))
        if len(ix) > 61:
            prior.append(float(np.log(cube.close[ix[-1], r.spell] / cube.close[ix[-61], r.spell])))
    surv = {
        "recorded": True, "snapshots": len(snap_files),
        "A_listed_but_no_bars": {"median_missing_share": round(float(med_d["missing_share"]), 4), "range_missing_share": [round(float(per_date["missing_share"].min()), 4), round(float(per_date["missing_share"].max()), 4)],
                                 "median_expected_missing_members_point": round(float(med_d["expected_missing_members"]), 1), "range_expected": [round(float(per_date["expected_missing_members"].min()), 1), round(float(per_date["expected_missing_members"].max()), 1)],
                                 "median_upper_bound_missing_members": int(med_d["upper_bound_missing_members"]), "lower_bound": 0,
                                 "median_p_member_given_bars": round(float(med_d["p_member_given_bars"]), 3),
                                 "universe_size": 1000, "point_estimate_share_of_universe": round(float(med_d["expected_missing_members"]) / 1000, 4),
                                 "outlier_snapshots": per_date.loc[per_date["missing_share"] > 3 * per_date["missing_share"].median(), "snapshot_date"].astype(str).tolist(),
                                 "assumption": "missing names are as likely to be liquid as names with bars on the same exchange/date (upper-leaning: illiquid names are the ones that lack bars); the upper bound counts every missing name"},
        "B_terminal_returns": {**term_st, "annual_hazard_of_a_member_stopping_trading": {int(k): round(float(v), 4) for k, v in hazard.items()}, "mean_annual_hazard": round(float(hazard.mean()), 4),
                               "observed_final_20_session_raw_log_return_quantiles": {q: round(float(term_df['final_20_session_log_return_raw'].quantile(q)), 3) for q in (0.1, 0.25, 0.5, 0.75, 0.9)} if len(term_df) else {},
                               "sensitivity_annual_drag_bps_of_an_always_invested_equal_weight_book_if_unobserved_terminal_return_were": {f"{x:+.0%}": round(float(hazard.mean()) * x * 1e4, 1) for x in (-0.3, -0.6, -1.0)},
                               "note": "the return from the last observed bar to the end of the security (cash-out, distressed exit, delisting) is not observed for any of these; the sensitivity is arithmetic, not an estimate"},
        "C_exclusion_composition": {"excluded_member_spells_distinct": int(len(ex_ever)), "exclusion_events_touching_member_spells": int(len(ex_rows)),
                                    "share_of_member_spells": round(len(ex_ever) / max(1, int(ever_raw.sum())), 4),
                                    "cause_of_each_spells_earliest_exclusion": ex_ever["cause"].value_counts().to_dict() if len(ex_ever) else {},
                                    "exclusion_events_by_cause": ex_rows["cause"].value_counts().to_dict() if len(ex_rows) else {}, "member_cells_removed_share": round(ncell_removed / ncell_raw, 4),
                                    "share_of_excluded_spells_that_later_stop_trading": round(ended_ex, 3), "same_share_for_all_member_spells": round(ended_all, 3),
                                    "median_prior_60_session_raw_log_return_at_exclusion": round(float(np.median(prior)), 3) if prior else None, "n_prior": len(prior),
                                    "note": "exclusions remove names from the moment the data becomes ambiguous; this is a composition change, direction of the return bias NOT measured"},
        "D_identity": {
            "observations": bst, "ever_member_spells_with_masked_cells": int(removed_id.any(0).sum()), "raw_member_cells_masked": int(removed_id.sum()),
            "share_of_raw_member_cells": round(float(removed_id.sum() / ncell_raw), 4),
            "tail_mask_cells_causal": int(removed_id.sum()), "unresolved_window_cells_retained": int(st["retained_window"].sum()), "unresolved_window_share_of_final_cells": round(float(st["retained_window"].sum() / member.sum()), 4),
            "twin_pairs_resolved": int(len(ctx.twins)), "twin_duplicate_bars_dropped": int(ctx.twin_stats["twin_cells_dropped"]),
            "timeline_cross_check_violations": M["R6c"], "timeline_cross_check_violations_without_the_mask": int(viol_nomask), "member_cells_of_boundary_tickers_checked": cells_checked,
            "v1_figi_glued_member_spells": int(glue_v1["member_ever"].sum()),
            "v1_figi_glued_member_spells_whose_ticker_has_a_cik_boundary": int(glue_v1[glue_v1["member_ever"]]["ticker"].isin(set(bnd["ticker"])).sum()),
            "v1_figi_glued_member_spells_same_issuer_figi_churn_not_masked": int((~glue_v1[glue_v1["member_ever"]]["ticker"].isin(set(bnd["ticker"]))).sum()),
            "examples_masked_hand_overs": [{"ticker": r.ticker, "before": r.name_before, "after": r.name_after, "d1": str(r.d1.date()), "d2": str(r.d2.date())}
                                           for r in bnd[bnd["ticker"].isin({str(cube.spell_ticker[c_]) for c_ in np.flatnonzero(removed_id.any(0))})].head(10).itertuples()],
            "not_detected": SPEC["declared_limitations_not_gated"][-3:]},
        "E_instrument_mix": mix,
    }
    (AUD / "survivorship_quantification.json").write_text(json.dumps(surv, indent=1, default=str))
    log("survivorship:", json.dumps(surv["A_listed_but_no_bars"])[:300])
else:
    log(f"PIT snapshots incomplete ({len(snap_files)}/{len(expected_dates)}): residual survivorship NOT quantified")
M["R8"] = bool(surv["recorded"])
D["R8"] = "see 'Residual survivorship' section" if surv["recorded"] else f"PIT snapshots incomplete ({len(snap_files)}/{len(expected_dates)})"

# ---------------------------------------------------------------- 7. the gate's own ledger (gate-tagged events; invisible to the existing gate)
ledger = GapLedger(reg, gate=GATE_NAME)
tt_, cc_ = np.nonzero(member & real)
panel = pd.DataFrame({"ticker": cube.spell_ticker[cc_].astype(str), "date": sess[tt_], "open": cube.open[tt_, cc_], "high": cube.high[tt_, cc_], "low": cube.low[tt_, cc_],
                      "close": cube.close[tt_, cc_], "volume": cube.volume[tt_, cc_]})
g_ohlc, _ = check_daily_ohlc(panel, DS)
g_stale = check_stale_daily(panel, DS)
ledger.add(g_ohlc + [g for g in g_stale if g.severity == MATERIAL])
# after delisting: member cells later than a master delisting date (+3 days) for the same ticker
dl = pd.to_datetime(master.loc[~master["active"].astype(bool), ["ticker", "delisted_utc"]].set_index("ticker")["delisted_utc"], utc=True, errors="coerce").dt.tz_convert(None)
after_delist = 0
for tk, dd_ in dl.dropna().items():
    for c_ in cols_by_ticker.get(tk, []):
        after_delist += int((member & real)[int(sess.searchsorted(dd_ + pd.Timedelta(days=3))):, c_].sum())      # member cells WITH A REAL BAR after the delisting date
# NO_PRICE_DATA events that touch a final member cell
npd_touch = 0
for r in ev[ev["verdict"] == "NO_PRICE_DATA"].itertuples():
    for c_ in cols_by_ticker.get(r.ticker, []):
        lo, hi = max(0, r.claimed_session - 4), min(T, r.claimed_session + 5)
        npd_touch += int(member[lo:hi, c_].sum())
ren = pd.read_parquet(RAW / "alpaca_name_changes.parquet")
ren["d"] = pd.to_datetime(ren["process_date"])
ren_w = ren[(ren["d"] >= SPEC["scope"]["window_start"]) & (ren["old_symbol"] != ren["new_symbol"])]
ren_member = 0
for r in ren_w.itertuples():
    s_ = int(sess.searchsorted(r.d))
    for c_ in cols_by_ticker.get(r.new_symbol, []):
        if member[max(0, s_ - 4):s_ + 5, c_].any():
            ren_member += 1
            break
E = {
    "scope": "not an input of DAILY_SWING_V3 (SPEC scope.not_used); the panel is built from daily bars only",
    "placeholder": f"member cells with volume<=0: {bad_vol} (R1); {cube_stats['placeholder_bars_not_cells']:,} placeholder bars were set aside and are never cells",
    "stale": f"member-panel flat-bar runs (check_stale_daily on {len(panel):,} member cells): {len([g for g in g_stale if g.severity == MATERIAL])}",
    "missing": f"R2b={M['R2b']:.4%}, R2c={M['R2c']:.2%} on member cells; missing member cells are masked, never filled",
    "after_delist": f"member cells WITH a real bar more than 3 days after a master delisting date: {after_delist} (member cells without a bar shortly after a stock's last bar are the no-look-ahead lag, counted in R2b and masked)",
    "npd": f"claims with no real bar within +-4 sessions that touch a member cell: {npd_touch}",
    "splits": f"R4a={M['R4a']}, R4b={M['R4b']}; disputed events: {int(ev['disputed'].sum())} (confirmed {int(((ev['disputed']) & (ev['verdict'] == 'CONFIRMED')).sum())}, refuted {int(((ev['disputed']) & (ev['verdict'] == 'REFUTED')).sum())}, "
              f"ambiguous->spell excluded {int(((ev['disputed']) & (ev['action'] == 'EXCLUDE_SPELL')).sum())}, no price data {int(((ev['disputed']) & (ev['verdict'] == 'NO_PRICE_DATA')).sum())})",
    "identity": (f"R6e={M['R6e']} twin cells (substantive), R5c={M['R5c']:.4%} (substantive, full pipeline rebuilt from truncated data), R6d={M['R6d']:.3%} retained unresolved-window cells, R6c={M['R6c']}/R6a={M['R6a']}/R6b={M['R6b']} (construction checks); "
                 f"{bst.get('boundaries')} issuer boundaries, causal tail mask {(removed_id.sum() / ncell_raw):.2%} of raw member cells; rename events in the window touching a member name: {ren_member}. "
                 "Residual (declared): hand-overs are detectable only at quarterly resolution from 2019-01-02 plus the current master; cells inside unresolved windows are retained and may mix two issuers"),
}
ACCEPT = SPEC["accepted_limitations"]
kind_rules = {  # kind -> (condition, evidence text). A gap is only dispositioned if its condition is TRUE.
    "NO_VENDOR_RECEIPT_TS": (True, E["scope"]), "NO_SYSTEM_RECEIPT_TS": (True, E["scope"]), "NEWS_HAS_NO_RECEIPT_TIMESTAMPS": (True, E["scope"]),
    "NO_POINT_IN_TIME_FUNDAMENTALS": (True, E["scope"]),
    "MINUTE_AND_TICK_HISTORY_NOT_MATERIALISED": (True, E["scope"] + "; execution costs are assumed (SPEC scope.execution_costs)"),
    "QUOTES_NBBO_NOT_MATERIALISED": (True, E["scope"] + "; execution costs are assumed (SPEC scope.execution_costs)"),
    "MISSING_MINUTES_LIQUID": (True, E["scope"]), "BAR_PRESENT_IN_ONE_PROVIDER_ONLY": (True, E["scope"] + " (this MATERIAL entry is the minute-bar comparison)"),
    "ZERO_VOLUME_PLACEHOLDER_BARS": (M["R1"] == 0, E["placeholder"]),
    "STALE_DAILY_PRICES": (len([g for g in g_stale if g.severity == MATERIAL]) == 0, E["stale"]),
    "MISSING_SESSION_LIQUID": (M["R2b"] <= 0.005 and M["R2c"] <= 0.05, E["missing"]),
    "BARS_AFTER_DELISTING": (after_delist == 0, E["after_delist"]),
    "SPLIT_NO_PRICE_DATA": (npd_touch == 0, E["npd"]),
    "SPLIT_WITHOUT_DISCONTINUITY": (M["R4a"] == 0 and M["R4b"] == 0, E["splits"]),
    "UNRECORDED_SPLIT_LIKE_DISCONTINUITY": (M["R4b"] == 0, E["splits"]),
    "SPLIT_TABLES_DISAGREE": (M["R4a"] == 0 and M["R4b"] == 0, E["splits"]),
    "RENAME_FEED_SPARSE": (M["R6e"] == 0 and M["R5c"] <= 0.0005 and M["R6d"] <= 0.01 and M["R6c"] == 0 and M["R6a"] == 0 and M["R6b"] == 0, E["identity"] + "; NB the rename feed is sparse in 2019 (in the window): identity rests on PIT listings and bars, not on rename events"),
    "RENAME_HISTORY_BACKMAPPED": (M["R6e"] == 0 and M["R5c"] <= 0.0005 and M["R6d"] <= 0.01 and M["R6c"] == 0 and M["R6a"] == 0 and M["R6b"] == 0, E["identity"]),
    "RENAME_WITH_PRICE_DISCONTINUITY": (M["R6e"] == 0 and M["R5c"] <= 0.0005 and M["R6d"] <= 0.01 and M["R6c"] == 0, E["identity"]),
    "SYMBOL_REUSED_ACROSS_ISSUERS": (M["R6e"] == 0 and M["R5c"] <= 0.0005 and M["R6d"] <= 0.01 and M["R6c"] == 0, E["identity"]),
}
acc_kind = "SURVIVORSHIP_RESIDUAL_DAILY_SWING_V1"
if surv["recorded"]:
    A, B, Cc = surv["A_listed_but_no_bars"], surv["B_terminal_returns"], surv["C_exclusion_composition"]
    ledger.add([Gap(DS, "survivorship", acc_kind, MATERIAL,
                    f"KNOWN LIMITATION (authorised). (A) Names listed per point-in-time Massive listings but with no bars: median {A['median_missing_share']:.1%} of listed names (range {A['range_missing_share'][0]:.1%}-{A['range_missing_share'][1]:.1%}); "
                    f"expected missing universe members ~{A['median_expected_missing_members_point']:.0f} of 1000 per date (range {A['range_expected'][0]:.0f}-{A['range_expected'][1]:.0f}; upper bound {A['median_upper_bound_missing_members']}, lower bound 0). "
                    f"(B) {B['member_spells_ended']} member spells stop trading before the data ends (mean annual hazard {B['mean_annual_hazard']:.1%} of the universe); their terminal returns are unobserved; sensitivity of an always-invested equal-weight book: "
                    f"{B['sensitivity_annual_drag_bps_of_an_always_invested_equal_weight_book_if_unobserved_terminal_return_were']} bps/yr. (C) Exclusions removed {Cc['member_cells_removed_share']:.2%} of member cells "
                    f"({Cc['excluded_member_spells_distinct']} distinct spells from {Cc['exclusion_events_touching_member_spells']} exclusion events; composition change, return-bias direction not measured). Details: data/audit/daily_swing_v3/survivorship_quantification.json.",
                    start=SPEC["scope"]["window_start"], end=str(LAST.date()))])
    for kind in ("DELISTED_NAMES_NO_BARS", "DELISTING_RETURN_UNKNOWN", "MISSING_TAIL"):
        kind_rules[kind] = (True, f"ACCEPTED LIMITATION: component of {acc_kind} (authorised by the requester), quantified there. Not resolved.")
disp_rows, stale_dispositions = [], []
for g in list(ledger.gaps.values()):
    if g.severity != MATERIAL or g.status == "RESOLVED" or g.kind == acc_kind or g.dataset_id == DS:
        continue
    rule = kind_rules.get(g.kind)
    if g.status == "EXCLUDED":
        if GATE_NAME not in g.excluded_from:
            continue                                   # excluded for another gate: not ours
        if rule is not None and not rule[0]:           # an earlier disposition whose scope condition no longer holds
            stale_dispositions.append(g)
            disp_rows.append((g.gap_id, g.kind, "DISPOSITION NO LONGER SUPPORTED", "scope condition NOT satisfied now: " + rule[1]))
        else:
            disp_rows.append((g.gap_id, g.kind, "EXCLUDED for " + GATE_NAME + " (earlier run)", g.resolution))
        continue
    if rule is not None and rule[0]:
        ledger.exclude(g.gap_id, [GATE_NAME], f"DAILY_SWING_V3 scope disposition. {rule[1]}")
        disp_rows.append((g.gap_id, g.kind, "EXCLUDED for " + GATE_NAME, rule[1]))
    else:
        disp_rows.append((g.gap_id, g.kind, "NOT DISPOSITIONED", "no rule for this kind" if rule is None else "scope condition NOT satisfied: " + rule[1]))
U = len(DailySwingGate.undispositioned(ledger, set(ACCEPT), GATE_NAME)) + len(stale_dispositions)
M["R9"] = U
D["R9"] = f"{sum(1 for r in disp_rows if r[2].startswith('EXCLUDED'))} dispositioned; {U} not"
results = evaluate_requirements(M, D, SPEC)
ok, why = DailySwingGate.check(results, ledger, set(ACCEPT), GATE_NAME)
for g in stale_dispositions:
    why.append(f"MATERIAL gap {g.gap_id} [{g.kind}]: the earlier DAILY_SWING_V3 disposition no longer holds on this data")
ok = ok and not stale_dispositions
log("GATE", "OPEN" if ok else "BLOCKED", f"({len(why)} reasons)")

# ---------------------------------------------------------------- 8. artifacts + report
cl.drop(columns=["claim_id"]).assign(date=lambda x: x["date"].dt.date).to_csv(AUD / "split_claims_resolved.csv.gz", index=False)
ev.assign(claimed_date=lambda x: pd.to_datetime(x["claimed_date"]).dt.date).to_csv(AUD / "split_events_resolved.csv.gz", index=False)
disc.assign(date=lambda x: x["date"].dt.date).to_csv(AUD / "unrecorded_discontinuities_member_cells.csv.gz", index=False)
excl.to_csv(AUD / "exclusions.csv", index=False)
ev[ev["action"] == "ADJUST"][["ticker", "spell", "adjust_session", "adjust_multiplier"]].assign(date=lambda x: sess[x["adjust_session"].to_numpy(dtype=int)].date).to_csv(AUD / "split_adjustments_confirmed.csv", index=False)
years = pd.Series(size, index=sess[t0:]).groupby(sess[t0:].year)
by_year = pd.DataFrame({"sessions": years.size(), "universe_min": years.min(), "universe_median": years.median().astype(int)})
by_year["split_exclusions_share"] = [float(removed[t0:][sess[t0:].year == y].sum() / max(1, member_raw[t0:][sess[t0:].year == y].sum())) for y in by_year.index]
by_year["identity_mask_share"] = [float(removed_id[t0:][sess[t0:].year == y].sum() / max(1, member_raw[t0:][sess[t0:].year == y].sum())) for y in by_year.index]
by_year.to_csv(AUD / "universe_by_year.csv")
np.savez_compressed(RAW / "dsv3_membership.npz", member=member, member_raw=member_raw, identity_mask=id_all, excl_from=excl_from, sessions=sess.values, spell_ticker=cube.spell_ticker.astype(str))

L = [f"# {GATE_NAME} audit (status as of {pd.Timestamp.now(tz='UTC').strftime('%Y-%m-%d %H:%M UTC')})", "",
     f"**Gate: {'OPEN' if ok else 'BLOCKED'}**  |  frozen spec `{SPEC_SHA256[:16]}...` (registry seq {frozen[0]['seq']}) | window {SPEC['scope']['window_start']}..{LAST.date()} | "
     f"data `{DS}`", "",
     "This audit does **not** start strategy discovery. The existing gate (`overnight_news_open_to_close`) is untouched.", "", "## Requirements", "",
     "| id | requirement | comparison | measured | result | detail |", "|---|---|---|---|---|---|"]
for r in results:
    m = r.measured
    ms = f"{m:.4%}" if isinstance(m, float) and r.rid in ("R2b", "R2c", "R4c", "R6d", "R7a", "R7b") else (f"{m:.4f}" if isinstance(m, float) else str(m))
    L.append(f"| {r.rid} | {r.text} | {r.comparison} | {ms} | **{'PASS' if r.passed else 'FAIL'}** | {r.detail} |")
L += ["", "Notes on the measurements: **R7** compares two vendors that both deliver consolidated SIP prints (closes are bit-identical on 100% of the sampled bars; volume is identical on about two thirds), so it validates the data path, not an independent price source. "
      "The point-in-time test (R5a) is run on the real data at three random cut dates; the rest of the universe logic is covered by unit tests with planted defects.", "", "## Why the gate is " + ("open" if ok else "blocked"), ""] + ([f"- {w}" for w in why] or ["- every requirement passed and no gap is undispositioned"])
L += ["", "## Point-in-time universe", "", f"Top {SPEC['universe']['top_n']} by trailing {SPEC['universe']['lookback_sessions']}-session median dollar volume (>= {SPEC['universe']['min_real_bars_in_lookback']} real bars, last close >= ${SPEC['universe']['min_last_close']:.0f}), "
      "membership for session t computed from sessions < t only; exclusions applied afterwards.", "", md_table(by_year), "",
      f"Spells: {S:,} ({cube_stats['tickers']:,} tickers; {cube_stats['tickers_with_multiple_spells']} with more than one spell). Placeholder bars set aside: {cube_stats['placeholder_bars_not_cells']:,}. Ever-member spells (window): {int(ever_raw.sum()):,}."]
c_tot = ev.groupby(["disputed", "verdict", "action"]).size().rename("events").reset_index()
c_mem = ev[ev["ever_member"]].groupby(["disputed", "verdict", "action"]).size().rename("events_touching_a_member_spell").reset_index()
L += ["", "## Empirical split resolution", "", f"{len(claims)} claims in the window: {claims['source'].value_counts().to_dict()} ('both' = agreed by Massive and Alpaca; single-source claims are the **disputed** events). "
      f"{len(ev)} events after clustering claims within {SPEC['split_resolution']['test_window_sessions']} sessions.", "", "All events:", "", md_table(c_tot), "", "Events touching a spell that was ever a universe member:", "", md_table(c_mem), ""]
dis = ev[ev["disputed"]]
tst = dis[~dis["why"].str.startswith("untestable")]
L += [f"Disputed events: {len(dis)}. Testable from prices: {len(tst)}; verdicts {tst['verdict'].value_counts().to_dict()}. Untestable (claimed adjustment below |ln m| = {SPEC['split_resolution']['untestable_if_abs_log_ratio_below']}): "
      f"{int(dis['why'].str.startswith('untestable').sum())}. **Who was right** when prices decided a single-source claim: CONFIRMED {({k: int(v) for k, v in dis[dis['verdict'] == 'CONFIRMED']['sources'].value_counts().items()})}, "
      f"REFUTED {({k: int(v) for k, v in dis[dis['verdict'] == 'REFUTED']['sources'].value_counts().items()})}: neither provider's table is reliable on its own.",
      "", f"Unrecorded overnight discontinuities among raw member cells: {disc['class'].value_counts().to_dict()}. Full tables in `data/audit/daily_swing_v3/`."]
if surv["recorded"]:
    A, B, Cc, Dd, Ee = (surv[k] for k in ("A_listed_but_no_bars", "B_terminal_returns", "C_exclusion_composition", "D_identity", "E_instrument_mix"))
    L += ["", "## Residual survivorship (KNOWN LIMITATION, authorised; quantified, not a blocker)", "",
          "**A. Names listed (point-in-time) but with no bars.** " + json.dumps(A), "", "**B. Terminal returns of members that stop trading.** " + json.dumps(B), "",
          "**C. What the exclusions removed (composition only).** " + json.dumps(Cc), "", "**D. Identity fix (V2's one change).** " + json.dumps(Dd), "",
          "**E. Instrument mix: Massive's `CS` is not pure US common stock.** " + json.dumps(Ee), "",
          "Not quantified: names whose Massive type changed; provider-side omission of names that were never listed in Massive's PIT snapshots."]
L += ["", "## Gap dispositions for DAILY_SWING_V3 (recorded as gate-tagged registry events; the existing gate's ledger view is unchanged)", "", "| gap | kind | result | evidence |", "|---|---|---|---|"]
L += [f"| `{a}` | {b} | {c} | {d_} |" for a, b, c, d_ in disp_rows]
L += ["", "## Declared limitations (not gated)", ""] + [f"- {x}" for x in SPEC["declared_limitations_not_gated"]]
L += ["", "## What V3 does NOT fix (declared)", "",
      "- Cells inside unresolved hand-over windows are retained and may mix two issuers (gated share R6d; windows are 87..2,827 days).",
      "- Unrecorded splits with |ln R| < 1.0 cannot be told from genuine moves and are kept as raw returns; spin-offs and dividends are not adjusted.",
      "- Requirements labelled construction_check cannot fail by design (R1, R4a, R4b, R6a, R6b, R6c, R8, R9); only the substantive ones are evidence.",
      "- Cross-provider agreement (R7) validates the data path only: both vendors carry the same SIP prints and the sample is 40 names.",
      "- The thresholds new in V3 (R5c, R6d, R6f) were set knowing the V2 measurements."]
OUT.write_text("\n".join(L) + "\n")
reg.append("INTEGRITY_REPORT", {"experiment": GATE_NAME, "gate_open": bool(ok), "n_reasons": len(why), "spec_sha256": SPEC_SHA256, "dataset": DS,
                               "requirements": {r.rid: [None if r.measured is None else (bool(r.measured) if isinstance(r.measured, (bool, np.bool_)) else float(r.measured)), bool(r.passed)] for r in results}})
log("chain valid:", reg.verify_chain(), "| dry run:", DRY, "|", OUT)
print("GATE:", "OPEN" if ok else "BLOCKED")
for w in why:
    print(" -", w[:230])
