"""DAILY_SWING_V1 audit: runs the frozen requirements against the data and reports the gate status. Does NOT start strategy discovery.

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
from edgelab.daily_swing_spec import GATE_NAME, SPEC, SPEC_SHA256
from edgelab.daily_swing_surv import glued_spells, instrument_mix, pit_listing_coverage, terminal_exposure
from edgelab.integrity import MATERIAL, Gap, GapLedger, MarketCalendar, check_daily_ohlc, check_stale_daily
from edgelab.registry import Registry

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
DRY = bool(os.environ.get("AUDIT_DRY_RUN"))
if DRY:
    tmp = Path(tempfile.mkdtemp())
    shutil.copy(ROOT / "registry" / "registry.jsonl", tmp / "registry.jsonl")
    reg, OUT, AUD = Registry(tmp / "registry.sqlite"), tmp / "DAILY_SWING_V1_AUDIT.md", tmp / "audit"
else:
    reg, OUT, AUD = Registry(ROOT / "registry" / "registry.sqlite"), ROOT / "docs" / "DAILY_SWING_V1_AUDIT.md", ROOT / "data" / "audit" / "daily_swing_v1"
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
if not frozen:
    sys.exit("REFUSING TO RUN: the current SPEC hash is not registered. Run scripts/freeze_daily_swing_requirements.py (a changed spec needs a new version).")
log("spec verified against registry seq", frozen[0]["seq"], SPEC_SHA256[:12])

# ---------------------------------------------------------------- 1. data, cube, point-in-time universe
prov_d = json.loads((ROOT / "data/samples/alpaca_daily_universe.provenance.json").read_text())
d = pd.read_parquet(RAW / "alpaca_daily_all.parquet")
master = pd.read_parquet(RAW / "massive_security_master_CS.parquet")
LAST = pd.Timestamp(d["date"].max())
cal = MarketCalendar("US_EQUITY")
sess = cal.sessions("2016-01-04", str(LAST.date()))
cube, cube_stats = build_cube(d, sess)
T, S = cube.T, cube.S
t0 = int(sess.searchsorted(pd.Timestamp(SPEC["scope"]["window_start"])))
member_raw = pit_membership(cube.close, cube.volume, start=t0 - 1)
member_raw[:t0] = False
DS = f"dsv1_panel_{prov_d['parts_sha256'][:8]}_{SPEC_SHA256[:8]}"
log(f"cube {T} sessions x {S} spells; window starts at session {t0} ({sess[t0].date()}); raw member cells {int(member_raw.sum()):,}")

# ---------------------------------------------------------------- 2. empirical split resolution (ALL disputed and agreed claims in the window)
UNIVERSE_TICKERS = set(master["ticker"])
sm = pd.read_parquet(RAW / "massive_splits_since_2016.parquet")
sm = sm[sm["ticker"].isin(UNIVERSE_TICKERS)]
sa = pd.read_parquet(RAW / "alpaca_splits.parquet")
sa = pd.DataFrame({"ticker": sa["symbol"], "execution_date": sa["ex_date"], "split_from": sa["old_rate"], "split_to": sa["new_rate"]})
sa = sa[sa["ticker"].isin(UNIVERSE_TICKERS)]
claims = build_claims(sm, sa, (SPEC["scope"]["window_start"], str(LAST.date())))
cl, ev = resolve_claims(claims, cube)
ever_raw = member_raw.any(0)
ev["ever_member"] = [bool(ever_raw[s]) if s >= 0 else False for s in ev["spell"]]
log(f"claims {len(claims)} ({claims['source'].value_counts().to_dict()}); events {len(ev)}; verdicts {ev['verdict'].value_counts().to_dict()}")

# ---------------------------------------------------------------- 3. unrecorded discontinuities among raw member cells
claim_sessions: dict[int, np.ndarray] = {}
for r in cl[cl["spell"] >= 0].itertuples():
    claim_sessions.setdefault(int(r.spell), []).append(r.s0)
claim_sessions = {k: np.array(v) for k, v in claim_sessions.items()}
disc = unrecorded_discontinuities(cube, member_raw, claim_sessions, t0)

# ---------------------------------------------------------------- 4. exclusions (effective session per spell) and the final universe
BIG = 10 ** 9
excl_from = np.full(S, BIG, dtype=np.int64)
excl_rows = []
for r in ev[ev["action"] == "EXCLUDE_SPELL"].itertuples():
    if r.spell >= 0:
        excl_from[r.spell] = min(excl_from[r.spell], r.exclude_from_session)
        excl_rows.append({"spell": r.spell, "ticker": r.ticker, "from_session": r.exclude_from_session, "from_date": sess[max(0, r.exclude_from_session)].date(),
                          "cause": "DISPUTED_SPLIT_AMBIGUOUS" if r.disputed else "AGREED_SPLIT_TESTABLE_AMBIGUOUS", "why": r.why, "ever_member": r.ever_member})
for r in disc[disc["class"] == "UNRECORDED_SPLIT_LIKE"].itertuples():
    excl_from[r.spell] = min(excl_from[r.spell], r.session)
    excl_rows.append({"spell": r.spell, "ticker": r.ticker, "from_session": r.session, "from_date": sess[r.session].date(), "cause": "UNRECORDED_SPLIT_LIKE_DISCONTINUITY",
                      "why": f"ln R={r.ln_R}, dv_ratio={r.dv_ratio}", "ever_member": True})
excl = pd.DataFrame(excl_rows)
tt = np.arange(T)[:, None]
member = member_raw & (tt < excl_from[None, :])
removed = member_raw & ~member
ncell_raw, ncell_removed = int(member_raw.sum()), int(removed.sum())
size = member[t0:].sum(1)
log(f"final member cells {int(member.sum()):,}; removed by exclusions {ncell_removed:,} ({ncell_removed / ncell_raw:.2%}); universe size min/median {size.min()}/{int(np.median(size))}")

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
for r in disc[disc["class"] == "UNRECORDED_SPLIT_LIKE"].itertuples():
    still += int(member[r.session:, r.spell].sum())
M["R4b"] = still
D["R4b"] = (f"unrecorded split-like jumps: {int((disc['class'] == 'UNRECORDED_SPLIT_LIKE').sum())}; ambiguous split events excluded: {int((ev['action'] == 'EXCLUDE_SPELL').sum())}; "
            f"agreed, untestable-small, accepted as corroborated-but-unverified: {int((ev['action'] == 'ACCEPT_CORROBORATED_UNVERIFIED').sum())}")
M["R4c"] = ncell_removed / max(1, ncell_raw)
D["R4c"] = f"{ncell_removed:,} of {ncell_raw:,} member cells removed; {int((member_raw.any(0) & (excl_from < BIG)).sum())} of {int(ever_raw.sum())} member spells affected"
# R5a: truncation invariance on the real data
rng = np.random.default_rng(0)
cuts = sorted(int(x) for x in rng.choice(np.arange(t0 + 150, T - 5), 3, replace=False))
tick_full, pairs_full = member_pairs(cube, member_raw)
diffs = 0
for cut in cuts:
    dd = d[d["date"] <= sess[cut]]
    cu, _ = build_cube(dd, sess[: cut + 1])
    mu = pit_membership(cu.close, cu.volume, start=t0 - 1)
    mu[:t0] = False
    tk_t, pairs_t = member_pairs(cu, mu)
    # both membership sets restricted to sessions <= cut, compared by (ticker NAME, session)
    def named(tk, pr):
        return set(zip(tk[pr // 10_000], (pr % 10_000).tolist()))
    a = {x for x in named(tick_full, pairs_full) if x[1] <= cut}
    b = named(tk_t, pairs_t)
    diffs += len(a ^ b)
    log(f"truncation cut {sess[cut].date()}: {len(a):,} member pairs, symmetric difference {len(a ^ b)}")
M["R5a"] = diffs
D["R5a"] = f"cuts at sessions {[str(sess[c].date()) for c in cuts]}; membership rebuilt from data truncated at the cut vs full data, compared on every session <= cut"
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
snap_files = sorted((RAW / "massive_pit_master").glob("snapshot_*.parquet"))
expected_dates = json.loads((ROOT / "data/samples/massive_pit_master.provenance.json").read_text())["dates"] if (ROOT / "data/samples/massive_pit_master.provenance.json").exists() else []
snaps = pd.concat([pd.read_parquet(f) for f in snap_files]) if snap_files else pd.DataFrame()
surv = {"recorded": False}
if len(snap_files) and len(snap_files) == len(expected_dates):
    per_name, per_date = pit_listing_coverage(snaps, master, cube, member_raw)
    per_name[~per_name["has_bars"]].to_csv(AUD / "survivorship_listed_names_without_bars.csv.gz", index=False)
    per_date.to_csv(AUD / "survivorship_pit_coverage_by_snapshot.csv", index=False)
    glue = glued_spells(snaps, cube, member_raw)
    glue.to_csv(AUD / "identity_glued_spells.csv", index=False)
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
        "D_identity": {"glued_spells_total": int(len(glue)), "glued_spells_with_member_cells": int(glue["member_ever"].sum()) if len(glue) else 0,
                       "of_which_name_also_changed_similarity_below_0.6": int(((glue["name_similarity"] < 0.6) & glue["member_ever"]).sum()) if len(glue) else 0,
                       "member_cells_after_the_swap_window": {"lower_bound_from_first_snapshot_after": int(sum(int(member[int(r.session_hi):, int(r.spell)].sum()) for r in glue[glue["member_ever"]].itertuples())),
                                                              "upper_bound_from_last_snapshot_before": int(sum(int(member[int(r.session_lo):, int(r.spell)].sum()) for r in glue[glue["member_ever"]].itertuples()))},
                       "examples_name_changed": glue[glue["member_ever"] & (glue["name_similarity"] < 0.6)][["ticker", "name_before", "name_after"]].head(10).to_dict("records") if len(glue) else [],
                       "note": "spells that hold real bars near two PIT snapshot dates on which the ticker belonged to different FIGIs. A FIGI change is NOT proof of a different issuer (renames and restructurings also change it), "
                               "so the count is conservative; the name-change subset is indicative only. No V1 rule separates these series."},
        "E_instrument_mix": mix,
    }
    (AUD / "survivorship_quantification.json").write_text(json.dumps(surv, indent=1, default=str))
    log("survivorship:", json.dumps(surv["A_listed_but_no_bars"])[:300])
else:
    glue = pd.DataFrame(columns=["member_ever"])
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
glued_members = int(glue["member_ever"].sum()) if len(glue) else None
E = {
    "scope": "not an input of DAILY_SWING_V1 (SPEC scope.not_used); the panel is built from daily bars only",
    "placeholder": f"member cells with volume<=0: {bad_vol} (R1); {cube_stats['placeholder_bars_not_cells']:,} placeholder bars were set aside and are never cells",
    "stale": f"member-panel flat-bar runs (check_stale_daily on {len(panel):,} member cells): {len([g for g in g_stale if g.severity == MATERIAL])}",
    "missing": f"R2b={M['R2b']:.4%}, R2c={M['R2c']:.2%} on member cells; missing member cells are masked, never filled",
    "after_delist": f"member cells WITH a real bar more than 3 days after a master delisting date: {after_delist} (member cells without a bar shortly after a stock's last bar are the no-look-ahead lag, counted in R2b and masked)",
    "npd": f"claims with no real bar within +-4 sessions that touch a member cell: {npd_touch}",
    "splits": f"R4a={M['R4a']}, R4b={M['R4b']}; disputed events: {int(ev['disputed'].sum())} (confirmed {int(((ev['disputed']) & (ev['verdict'] == 'CONFIRMED')).sum())}, refuted {int(((ev['disputed']) & (ev['verdict'] == 'REFUTED')).sum())}, "
              f"ambiguous->spell excluded {int(((ev['disputed']) & (ev['action'] == 'EXCLUDE_SPELL')).sum())}, no price data {int(((ev['disputed']) & (ev['verdict'] == 'NO_PRICE_DATA')).sum())})",
    "identity": f"R6a={M['R6a']}, R6b={M['R6b']}, R4b={M['R4b']}; glued spells (one series across two FIGIs) with member cells: {glued_members}; rename events in the window touching a member name: {ren_member}",
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
    "RENAME_FEED_SPARSE": (glued_members == 0 and M["R6a"] == 0 and M["R6b"] == 0 and M["R4b"] == 0, E["identity"] + "; NB the rename feed is sparse in 2019 (in the window): identity rests on bars and PIT listings, not on rename events"),
    "RENAME_HISTORY_BACKMAPPED": (glued_members == 0 and M["R6a"] == 0 and M["R6b"] == 0, E["identity"]),
    "RENAME_WITH_PRICE_DISCONTINUITY": (glued_members == 0 and M["R4b"] == 0, E["identity"]),
    "SYMBOL_REUSED_ACROSS_ISSUERS": (glued_members == 0, E["identity"]),
}
acc_kind = "SURVIVORSHIP_RESIDUAL_DAILY_SWING_V1"
if surv["recorded"]:
    A, B, Cc = surv["A_listed_but_no_bars"], surv["B_terminal_returns"], surv["C_exclusion_composition"]
    ledger.add([Gap(DS, "survivorship", acc_kind, MATERIAL,
                    f"KNOWN LIMITATION (authorised). (A) Names listed per point-in-time Massive listings but with no bars: median {A['median_missing_share']:.1%} of listed names (range {A['range_missing_share'][0]:.1%}-{A['range_missing_share'][1]:.1%}); "
                    f"expected missing universe members ~{A['median_expected_missing_members_point']:.0f} of 1000 per date (range {A['range_expected'][0]:.0f}-{A['range_expected'][1]:.0f}; upper bound {A['median_upper_bound_missing_members']}, lower bound 0). "
                    f"(B) {B['member_spells_ended']} member spells stop trading before the data ends (mean annual hazard {B['mean_annual_hazard']:.1%} of the universe); their terminal returns are unobserved; sensitivity of an always-invested equal-weight book: "
                    f"{B['sensitivity_annual_drag_bps_of_an_always_invested_equal_weight_book_if_unobserved_terminal_return_were']} bps/yr. (C) Exclusions removed {Cc['member_cells_removed_share']:.2%} of member cells "
                    f"({Cc['excluded_member_spells_distinct']} distinct spells from {Cc['exclusion_events_touching_member_spells']} exclusion events; composition change, return-bias direction not measured). Details: data/audit/daily_swing_v1/survivorship_quantification.json.",
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
        ledger.exclude(g.gap_id, [GATE_NAME], f"DAILY_SWING_V1 scope disposition. {rule[1]}")
        disp_rows.append((g.gap_id, g.kind, "EXCLUDED for " + GATE_NAME, rule[1]))
    else:
        disp_rows.append((g.gap_id, g.kind, "NOT DISPOSITIONED", "no rule for this kind" if rule is None else "scope condition NOT satisfied: " + rule[1]))
U = len(DailySwingGate.undispositioned(ledger, set(ACCEPT))) + len(stale_dispositions)
M["R9"] = U
D["R9"] = f"{sum(1 for r in disp_rows if r[2].startswith('EXCLUDED'))} dispositioned; {U} not"
results = evaluate_requirements(M, D)
ok, why = DailySwingGate.check(results, ledger, set(ACCEPT))
for g in stale_dispositions:
    why.append(f"MATERIAL gap {g.gap_id} [{g.kind}]: the earlier DAILY_SWING_V1 disposition no longer holds on this data")
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
by_year["member_cells_removed_share"] = [float(removed[t0:][sess[t0:].year == y].sum() / max(1, member_raw[t0:][sess[t0:].year == y].sum())) for y in by_year.index]
by_year.to_csv(AUD / "universe_by_year.csv")
np.savez_compressed(RAW / "dsv1_membership.npz", member=member, member_raw=member_raw, excl_from=excl_from, sessions=sess.values, spell_ticker=cube.spell_ticker.astype(str))

L = [f"# {GATE_NAME} audit (status as of {pd.Timestamp.now(tz='UTC').strftime('%Y-%m-%d %H:%M UTC')})", "",
     f"**Gate: {'OPEN' if ok else 'BLOCKED'}**  |  frozen spec `{SPEC_SHA256[:16]}...` (registry seq {frozen[0]['seq']}) | window {SPEC['scope']['window_start']}..{LAST.date()} | "
     f"data `{DS}`", "",
     "This audit does **not** start strategy discovery. The existing gate (`overnight_news_open_to_close`) is untouched.", "", "## Requirements", "",
     "| id | requirement | comparison | measured | result | detail |", "|---|---|---|---|---|---|"]
for r in results:
    m = r.measured
    ms = f"{m:.4%}" if isinstance(m, float) and r.rid in ("R2b", "R2c", "R4c", "R7a", "R7b") else (f"{m:.4f}" if isinstance(m, float) else str(m))
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
      "", f"Unrecorded overnight discontinuities among raw member cells: {disc['class'].value_counts().to_dict()}. Full tables in `data/audit/daily_swing_v1/`."]
if surv["recorded"]:
    A, B, Cc, Dd, Ee = (surv[k] for k in ("A_listed_but_no_bars", "B_terminal_returns", "C_exclusion_composition", "D_identity", "E_instrument_mix"))
    L += ["", "## Residual survivorship (KNOWN LIMITATION, authorised; quantified, not a blocker)", "",
          "**A. Names listed (point-in-time) but with no bars.** " + json.dumps(A), "", "**B. Terminal returns of members that stop trading.** " + json.dumps(B), "",
          "**C. What the exclusions removed (composition only).** " + json.dumps(Cc), "", "**D. Identity (ticker re-use glued into one series).** " + json.dumps(Dd), "",
          "**E. Instrument mix: Massive's `CS` is not pure US common stock.** " + json.dumps(Ee), "",
          "Not quantified: names whose Massive type changed; provider-side omission of names that were never listed in Massive's PIT snapshots."]
L += ["", "## Gap dispositions for DAILY_SWING_V1 (recorded as gate-tagged registry events; the existing gate's ledger view is unchanged)", "", "| gap | kind | result | evidence |", "|---|---|---|---|"]
L += [f"| `{a}` | {b} | {c} | {d_} |" for a, b, c, d_ in disp_rows]
L += ["", "## Declared limitations (not gated)", ""] + [f"- {x}" for x in SPEC["declared_limitations_not_gated"]]
L += ["", "## Weaknesses of the V1 rules found while auditing (V1 is frozen and was run exactly as written)", "",
      "- **Split tolerance is tight for reverse-split ex-dates**: `tol = max(4*sigma, 0.05)` with a 1.5% sigma floor rejects true reverse splits whose ex-date open moves 7-10% around the ratio; those spells are excluded although the split is real.",
      "- **Unrecorded-discontinuity rule can flag genuine crashes** whose size happens to match a common ratio (2020-03-09 energy names, PCG 2019-01-14) and then excludes the name from that session on, removing post-crash history: a composition bias.",
      "- **`CS` can include ADS lines and closed-end funds** in Massive's typing (they appear among listed-but-no-bars names); a name-pattern check found none among the universe members (E above), but the check is a heuristic and V1 has no instrument filter.",
      "- **V1 has no rule for ticker hand-overs**: the point-in-time listings show one bar series running across a FIGI change for a set of member spells, some of them clearly different issuers (see D). This is what blocks the gate.",
      "Proposed for a DAILY_SWING_V2 (needs your confirmation; not applied): (1) split each spell at a PIT FIGI change (or exclude it from that point, the same 'ambiguous -> exclude' principle used for splits); (2) widen the split tolerance for reverse splits using post-event volume scaling; "
      "(3) exclude only the affected session window for an unrecorded jump instead of the rest of the spell; (4) filter instrument type by FIGI/exchange metadata."]
if surv["recorded"]:
    lo_, hi_ = surv["D_identity"]["member_cells_after_the_swap_window"]["lower_bound_from_first_snapshot_after"], surv["D_identity"]["member_cells_after_the_swap_window"]["upper_bound_from_last_snapshot_before"]
    L += ["", f"*Cost of fix (1), for your decision only, not applied and not part of V1:* it would remove at most {lo_:,}-{hi_:,} further member cells ({lo_ / ncell_raw:.2%}-{hi_ / ncell_raw:.2%} of raw member cells; some overlap the split exclusions), "
          f"taking total removals to at most about {(ncell_removed + hi_) / ncell_raw:.1%}, still under the 5% ceiling in R4c."]
CORRECTIONS = [{"correction_id": "C1_excluded_spell_count", "about_gap_kind": acc_kind,
                "was": "text of the accepted-limitation gap recorded in the first audit run says '167 spells' excluded",
                "is": f"126 distinct member spells ({int(len(ex_rows)) if surv['recorded'] else 'n/a'} exclusion events, share of member spells "
                      f"{(len(ex_ever) / max(1, int(ever_raw.sum()))) if surv['recorded'] else float('nan'):.1%}); 167 was the number of exclusion events. The 2.60% of member cells removed was correct."}]
have = {e["payload"].get("correction_id") for e in reg.events("NOTE")}
for c_ in CORRECTIONS:
    if surv["recorded"] and c_["correction_id"] not in have:
        gid = next((g.gap_id for g in ledger.gaps.values() if g.kind == c_["about_gap_kind"]), None)
        reg.append("NOTE", {"kind": "CORRECTION", "experiment": GATE_NAME, "gap_id": gid, **c_})
if surv["recorded"]:
    L += ["", "## Corrections to earlier outputs (the registry is append-only; corrections are recorded as NOTE events)", ""] + [f"- **{c_['correction_id']}**: was: {c_['was']}. Now: {c_['is']}" for c_ in CORRECTIONS]
OUT.write_text("\n".join(L) + "\n")
reg.append("INTEGRITY_REPORT", {"experiment": GATE_NAME, "gate_open": bool(ok), "n_reasons": len(why), "spec_sha256": SPEC_SHA256, "dataset": DS,
                               "requirements": {r.rid: [None if r.measured is None else (bool(r.measured) if isinstance(r.measured, (bool, np.bool_)) else float(r.measured)), bool(r.passed)] for r in results}})
log("chain valid:", reg.verify_chain(), "| dry run:", DRY, "|", OUT)
print("GATE:", "OPEN" if ok else "BLOCKED")
for w in why:
    print(" -", w[:230])
