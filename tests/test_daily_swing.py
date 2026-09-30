"""DAILY_SWING_V1 machinery: spells, point-in-time universe (no look-ahead), empirical split resolution, unrecorded discontinuities."""
import numpy as np
import pandas as pd
import pytest

from edgelab.daily_swing import (Cube, assign_spells, build_claims, build_cube, classify_claim, member_pairs, pit_membership, resolve_claims,
                                 unrecorded_discontinuities)
from edgelab.daily_swing_spec import SPEC, SPEC_SHA256
from edgelab.registry import canon, sha256

SESS = pd.bdate_range("2020-01-01", periods=400)


def series(ticker, start, n, px=50.0, vol=1e6, drift=0.0, seed=0):
    rng = np.random.default_rng(seed)
    rows, p = [], px
    for i in range(n):
        o = p * (1 + rng.normal(0, 0.004)); c = o * (1 + rng.normal(drift, 0.01))
        rows.append((ticker, SESS[start + i], o, max(o, c) * 1.002, min(o, c) * 0.998, c, vol))
        p = c
    return rows


def frame(rows):
    return pd.DataFrame(rows, columns=["ticker", "date", "open", "high", "low", "close", "volume"])


def test_spec_hash_is_stable_and_matches_canonical_json():
    assert SPEC_SHA256 == sha256(canon(SPEC)) and SPEC["universe"]["top_n"] == 1000 and SPEC["scope"]["window_start"] == "2019-01-01"


# ------------------------------------------------------------------ cube / spells
def test_placeholders_are_not_cells_and_gaps_of_60_sessions_split_spells():
    a = series("AAA", 0, 100)
    b = series("AAA", 100 + 60, 100, seed=1)            # 60 sessions with no bar -> new spell (gap of 61 in index terms)
    c = series("BBB", 0, 100, seed=2)
    d = series("BBB", 100 + 58, 100, seed=3)            # 58 sessions gap: same spell
    df = frame(a + b + c + d)
    ph = df.iloc[[5]].copy(); ph["volume"] = 0; ph["date"] = SESS[300]        # zero-volume placeholder on an otherwise empty session
    cube, st = build_cube(pd.concat([df, ph]), SESS)
    assert st["placeholder_bars_not_cells"] == 1 and st["spells"] == 3 and st["tickers"] == 2
    assert not np.isfinite(cube.close[300]).any()                              # the placeholder is not a cell
    assert sorted(cube.spell_ticker) == ["AAA", "AAA", "BBB"]


def test_assign_spells_boundary_exactness():
    tk = np.array(["A"] * 4)
    assert assign_spells(tk, np.array([0, 1, 61, 62]), 60).tolist() == [0, 0, 0, 0]       # diff 60 is NOT >= gap+1 -> same spell
    assert assign_spells(tk, np.array([0, 1, 62, 63]), 60).tolist() == [0, 0, 1, 1]       # diff 61 -> new spell


def test_duplicate_keys_are_counted_and_not_averaged():
    df = frame(series("AAA", 0, 50))
    dup = df.iloc[[10]].copy(); dup["close"] = 999.0
    cube, st = build_cube(pd.concat([df, dup]), SESS)
    assert st["duplicate_ticker_session_keys"] == 1 and cube.close[10, 0] != 999.0 and cube.close[10, 0] != (999.0 + df.iloc[10]["close"]) / 2


# ------------------------------------------------------------------ point-in-time universe
def make_market(n_names=30, T=300, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n_names):
        rows += series(f"N{i:02d}", 0, T, px=20 + i, vol=float(rng.uniform(1e5, 5e6)), seed=seed * 100 + i)
    return frame(rows)


def test_membership_top_n_min_price_and_min_history():
    df = make_market(30, 200)
    df.loc[df["ticker"] == "N05", ["open", "high", "low", "close"]] *= 0.05            # sub-$5 stock: never eligible
    late = frame(series("LATE", 100, 60, vol=1e9))                                     # huge dollar volume but only 60 bars
    cube, _ = build_cube(pd.concat([df, late]), SESS)
    m = pit_membership(cube.close, cube.volume, top_n=10, lookback=60, min_real=50, min_price=5.0)
    names = cube.spell_ticker
    t = 150
    assert m[t].sum() == 10 and not m[:, list(names).index("N05")].any()
    late_c = list(names).index("LATE")
    assert not m[:150, late_c].any() and m[150, late_c]                                # first bar at 100 -> 50 real bars strictly before t=150, 49 before t=149
    assert not m[:50].any() and m[50].any()                                           # 50 real bars are needed strictly before t: eligible from t=50, not before


def test_membership_uses_only_past_sessions_truncation_invariance():
    df = make_market(40, 300, seed=3)
    full, _ = build_cube(df, SESS)
    m_full = pit_membership(full.close, full.volume, top_n=15)
    for cut in (120, 200, 260):
        trunc, _ = build_cube(df[df["date"] <= SESS[cut]], SESS[: cut + 1])
        m_tr = pit_membership(trunc.close, trunc.volume, top_n=15)
        _, a = member_pairs(full, m_full, cut); _, b = member_pairs(trunc, m_tr)
        assert np.array_equal(a, b), f"membership at sessions <= {cut} changed when the future was removed"


def test_changing_the_future_cannot_change_past_membership():
    df = make_market(40, 300, seed=4)
    full, _ = build_cube(df, SESS)
    m1 = pit_membership(full.close, full.volume, top_n=15)
    df2 = df.copy()
    fut = df2["date"] > SESS[200]
    df2.loc[fut, "volume"] = df2.loc[fut, "volume"] * 1000                              # violent change strictly after session 200
    c2, _ = build_cube(df2, SESS)
    m2 = pit_membership(c2.close, c2.volume, top_n=15)
    assert np.array_equal(m1[:201], m2[:201]) and not np.array_equal(m1[201:], m2[201:])


# ------------------------------------------------------------------ empirical split resolution
def cube_with_split(mult=0.5, day=100, T=200, vol_mult=1.0, seed=0, crash=False):
    rows = series("SPL", 0, T, seed=seed)
    df = frame(rows)
    if mult != 1.0:
        after = df["date"] >= SESS[day]
        df.loc[after, ["open", "high", "low", "close"]] *= mult
        df.loc[after, "volume"] = df.loc[after, "volume"] / mult if not crash else df.loc[after, "volume"]
    if crash:
        df.loc[df["date"] == SESS[day], "volume"] *= 30
    cube, _ = build_cube(df, SESS)
    return cube


def claim(ticker="SPL", day=100, split_from=1, split_to=2, source="massive", cid=0):
    return pd.DataFrame([{"claim_id": cid, "ticker": ticker, "date": SESS[day], "split_from": split_from, "split_to": split_to,
                          "ratio": split_to / split_from, "price_multiplier": split_from / split_to, "source": source}])


def test_true_split_is_confirmed_even_when_the_date_is_off_by_two_sessions():
    cube = cube_with_split(0.5, 100)
    for offset in (0, 2, -2):
        cl, ev = resolve_claims(claim(day=100 + offset), cube)
        assert cl.iloc[0]["verdict"] == "CONFIRMED" and ev.iloc[0]["action"] == "ADJUST" and ev.iloc[0]["adjust_session"] == 100


def test_false_claim_on_a_smooth_series_is_refuted_not_excluded():
    cube = cube_with_split(1.0, 100)
    cl, ev = resolve_claims(claim(split_from=1, split_to=2), cube)
    assert cl.iloc[0]["verdict"] == "REFUTED" and ev.iloc[0]["action"] == "NONE"


def test_wrong_ratio_claim_is_ambiguous_and_excludes_the_spell_from_window_start():
    cube = cube_with_split(0.5, 100)                                                   # prices halve, but the claim says 1-for-3
    cl, ev = resolve_claims(claim(split_from=1, split_to=3), cube)
    e = ev.iloc[0]
    assert cl.iloc[0]["verdict"] == "AMBIGUOUS" and e["action"] == "EXCLUDE_SPELL" and e["exclude_from_session"] == 100 - SPEC["split_resolution"]["test_window_sessions"]


def test_price_match_with_dollar_volume_spike_is_a_crash_not_a_split():
    cube = cube_with_split(0.5, 100, crash=True)                                       # price halves, volume does NOT scale, dollar volume spikes
    cl, ev = resolve_claims(claim(), cube)
    assert cl.iloc[0]["verdict"] == "AMBIGUOUS" and "crash-like" in cl.iloc[0]["reason"] and ev.iloc[0]["action"] == "EXCLUDE_SPELL"


def test_small_ratio_disputed_is_excluded_but_agreed_is_accepted_unverified():
    cube = cube_with_split(1.0, 100)
    _, ev_d = resolve_claims(claim(split_from=1000, split_to=1040, source="massive"), cube)       # 4% adjustment: not testable
    _, ev_a = resolve_claims(claim(split_from=1000, split_to=1040, source="both"), cube)
    assert ev_d.iloc[0]["action"] == "EXCLUDE_SPELL" and ev_a.iloc[0]["action"] == "ACCEPT_CORROBORATED_UNVERIFIED"


def test_conflicting_claims_resolved_by_the_one_the_prices_confirm():
    cube = cube_with_split(0.5, 100)
    cl = pd.concat([claim(split_from=1, split_to=2, source="massive", cid=0), claim(split_from=1, split_to=3, source="alpaca", cid=1)], ignore_index=True)
    c, ev = resolve_claims(cl, cube)
    assert len(ev) == 1 and ev.iloc[0]["verdict"] == "CONFIRMED" and ev.iloc[0]["action"] == "ADJUST" and abs(ev.iloc[0]["adjust_multiplier"] - 0.5) < 1e-9
    assert sorted(c["verdict"]) == ["AMBIGUOUS", "CONFIRMED"]                          # per-claim verdicts are kept; the event is resolved


def test_no_bars_near_the_claim_cannot_touch_any_cell():
    cube = cube_with_split(1.0, 100, T=50)
    cl, ev = resolve_claims(claim(day=180), cube)
    assert ev.iloc[0]["verdict"] == "NO_PRICE_DATA" and ev.iloc[0]["action"] == "NONE"


def test_build_claims_collapses_agreed_pairs_and_keeps_disputes():
    m = pd.DataFrame({"ticker": ["A", "B", "C"], "execution_date": ["2020-05-01", "2020-06-01", "2020-07-01"], "split_from": [1, 1, 1], "split_to": [2, 4, 2]})
    a = pd.DataFrame({"ticker": ["A", "B", "D"], "execution_date": ["2020-05-02", "2020-06-01", "2020-08-01"], "split_from": [1, 1, 1], "split_to": [2, 5, 3]})
    c = build_claims(m, a, ("2019-01-01", "2026-09-30"))
    got = {(r.ticker, r.source) for r in c.itertuples()}
    assert got == {("A", "both"), ("B", "massive"), ("B", "alpaca"), ("C", "massive"), ("D", "alpaca")}


# ------------------------------------------------------------------ unrecorded discontinuities among members
def test_unrecorded_split_like_jump_is_flagged_but_recorded_or_spiking_ones_are_not():
    cube = cube_with_split(0.5, 100)                                                   # a real halving with volume scaling, but NO claim
    member = np.ones((cube.T, cube.S), dtype=bool)
    out = unrecorded_discontinuities(cube, member, {}, t0=60)
    assert out["class"].tolist() == ["UNRECORDED_SPLIT_LIKE"] and out.iloc[0]["session"] == 100
    assert unrecorded_discontinuities(cube, member, {0: np.array([101])}, t0=60)["class"].tolist() == ["COVERED_BY_CLAIM"]
    crash = cube_with_split(0.5, 100, crash=True)
    assert unrecorded_discontinuities(crash, np.ones((crash.T, crash.S), dtype=bool), {}, t0=60)["class"].tolist() == ["SPLIT_LIKE_BUT_GENUINE_MOVE_DV_SPIKE"]


# ------------------------------------------------------------------ the gate
from edgelab.daily_swing import DailySwingGate, evaluate_requirements                    # noqa: E402
from edgelab.daily_swing_spec import GATE_NAME                                            # noqa: E402
from edgelab.integrity import Gap, GapLedger, MATERIAL                                    # noqa: E402

ACC = set(SPEC["accepted_limitations"])
PASSING = {"R1": 0, "R2a": 0, "R2b": 0.001, "R2c": 0.01, "R3": 0, "R4a": 0, "R4b": 0, "R4c": 0.02, "R5a": 0, "R5b": 1.0, "R6a": 0, "R6b": 0, "R7a": 0.001, "R7b": 0.01, "R8": True, "R9": 0}


def test_requirement_outcomes_come_only_from_the_frozen_thresholds():
    assert all(r.passed for r in evaluate_requirements(PASSING))
    for rid, bad in {"R2b": 0.0051, "R2c": 0.051, "R4c": 0.0501, "R5b": 0.98, "R5a": 1, "R7a": 0.0051, "R8": False, "R9": 1}.items():
        res = {r.rid: r.passed for r in evaluate_requirements({**PASSING, rid: bad})}
        assert res[rid] is False and sum(not v for v in res.values()) == 1, rid          # exactly the perturbed requirement fails
    assert evaluate_requirements({k: v for k, v in PASSING.items() if k != "R7a"})[[r["id"] for r in SPEC["requirements"]].index("R7a")].passed is False   # no measurement -> FAIL
    assert not evaluate_requirements({**PASSING, "R7a": None})[[r["id"] for r in SPEC["requirements"]].index("R7a")].passed


def test_gate_blocks_on_undispositioned_material_gaps_but_not_on_the_accepted_limitation(tmp_path):
    from edgelab.registry import Registry
    r = Registry(tmp_path / "r.sqlite")
    base = GapLedger(r)
    other, news = Gap("d", "coverage", "SOMETHING_ELSE", MATERIAL, "unmapped material gap"), Gap("d", "news", "NEWS_X", MATERIAL, "news gap")
    base.add([other, news])
    led = GapLedger(r, gate=GATE_NAME)
    led.add([Gap("p", "survivorship", "SURVIVORSHIP_RESIDUAL_DAILY_SWING_V1", MATERIAL, "quantified limitation")])
    led.exclude(news.gap_id, [GATE_NAME], "not used")
    ok, why = DailySwingGate.check(evaluate_requirements(PASSING), led, ACC)
    assert not ok and len(why) == 1 and "SOMETHING_ELSE" in why[0]                       # the accepted kind and the excluded news gap do not block
    led.exclude(other.gap_id, [GATE_NAME], "scope evidence")
    assert DailySwingGate.check(evaluate_requirements(PASSING), led, ACC) == (True, [])
    led.exclude(other.gap_id, ["SOME_OTHER_GATE"], "excluded for a different experiment only")
    assert not DailySwingGate.check(evaluate_requirements(PASSING), led, ACC)[0]         # an exclusion for another gate is not a disposition for this one


def test_gate_requires_the_limitation_to_be_recorded_and_failed_requirements_block(tmp_path):
    from edgelab.registry import Registry
    led = GapLedger(Registry(tmp_path / "r.sqlite"), gate=GATE_NAME)
    ok, why = DailySwingGate.check(evaluate_requirements(PASSING), led, ACC)
    assert not ok and any("not recorded" in w for w in why)                              # accepted limitation must exist, quantified, in the record
    led.add([Gap("p", "survivorship", "SURVIVORSHIP_RESIDUAL_DAILY_SWING_V1", MATERIAL, "x")])
    assert DailySwingGate.check(evaluate_requirements(PASSING), led, ACC)[0]
    ok, why = DailySwingGate.check(evaluate_requirements({**PASSING, "R5a": 3}), led, ACC)
    assert not ok and "R5a" in why[0]


# ------------------------------------------------------------------ identity: one series across two FIGIs
def test_glued_spell_detection_uses_pit_figis_and_names():
    from edgelab.daily_swing_surv import glued_spells
    rows = series("GEN", 0, 300)                                                          # ONE continuous series (glued): no 60-session gap
    cube, _ = build_cube(frame(rows + series("SEP", 0, 100, seed=5) + series("SEP", 200, 100, seed=6)), SESS)   # SEP: a real gap of 100 sessions -> two spells
    member = np.zeros((cube.T, cube.S), dtype=bool); member[100:250, list(cube.spell_ticker).index("GEN")] = True
    snaps = pd.DataFrame([
        (SESS[50], "GEN", "FIGI_A", "Genesis Healthcare, Inc."), (SESS[250], "GEN", "FIGI_B", "Gen Digital Inc. Common Stock"),
        (SESS[50], "SEP", "FIGI_C", "Separated One Inc"), (SESS[250], "SEP", "FIGI_D", "Separated Two Inc")],
        columns=["snapshot_date", "ticker", "composite_figi", "name"])
    g = glued_spells(snaps, cube, member, near=20)
    assert g["ticker"].tolist() == ["GEN"]                                                # SEP's two issuers live in two spells: correctly NOT glued
    assert bool(g.iloc[0]["member_ever"]) and g.iloc[0]["name_similarity"] < 0.6
