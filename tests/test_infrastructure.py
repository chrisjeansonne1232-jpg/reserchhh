import sqlite3
import numpy as np
import pandas as pd
import pytest

from edgelab import stats as S
from edgelab.data import Panel, validate_panel, audit_universe_pit, audit_news_timestamps, asof_fundamentals, audit_survivorship
from edgelab.engine import Exec, run_backtest, break_even_cost_multiplier
from edgelab.registry import Registry, RegistryError
from edgelab.synthetic import make_market


def tiny_panel(o, c=None, alive=None, delist=None):
    o = np.array(o, float)
    c = o.copy() if c is None else np.array(c, float)
    T, N = o.shape
    ts = (pd.bdate_range("2024-01-02", periods=T) + pd.Timedelta(hours=21)).to_numpy().astype("datetime64[ns]")
    return Panel(ts, [f"A{i}" for i in range(N)], o, np.maximum(o, c), np.minimum(o, c), c, np.full((T, N), 1e9),
                 np.ones((T, N), bool) if alive is None else alive, np.full((T, N), 0.0), delist)


ZERO = Exec(spread_mult=0, default_spread_bps=0, slip_bps=0, comm_bps=0, open_penalty_bps=0, impact_coef=0,
            borrow_bps_annual=0, financing_bps_annual=0, max_weight=1, max_gross=5)


# ------------------------------------------------------------------ engine timing / accounting
def test_decision_at_t_earns_open_t1_to_open_t2():
    o = [[100], [110], [121], [133.1], [133.1]]
    p = tiny_panel(o)
    W = np.zeros((5, 1)); W[0, 0] = 1.0            # decided after bar 0, held from open[1]
    r = run_backtest(p, W, ZERO)
    assert r.gross[0] == 0                          # nothing earned at bar 0
    assert r.gross[1] == pytest.approx(121 / 110 - 1)   # earns open[2]/open[1]-1, NOT open[1]/open[0]-1
    assert r.gross[2:].sum() == pytest.approx(0)


def test_latency_delays_fill():
    o = [[100], [110], [121], [133.1], [146.41], [146.41]]
    W = np.zeros((6, 1)); W[0, 0] = 1
    import dataclasses
    r = run_backtest(tiny_panel(o), W, dataclasses.replace(ZERO, latency_bars=1))
    assert r.gross[1] == 0 and r.gross[2] == pytest.approx(133.1 / 121 - 1)


def test_costs_scale_with_turnover_and_breakeven():
    rng = np.random.default_rng(0)
    p = make_market(T=300, N=20, seed=1, edge_sd=0.002, delist_frac=0, late_list_frac=0)
    W = np.zeros((300, 20)); W[:, :5] = 0.05; W[:, 5:10] = -0.05
    ex = Exec(spread_mult=1)
    r = run_backtest(p, W, ex)
    assert r.cost.sum() > 0 and r.turnover[2:].sum() < 1.0      # constant book: only entry turnover
    W2 = W * np.where(np.arange(300)[:, None] % 2 == 0, 1, -1)   # flip daily => heavy turnover
    r2 = run_backtest(p, W2, ex)
    assert r2.cost.sum() > 20 * r.cost.sum()
    be = break_even_cost_multiplier(r2)
    import dataclasses
    # add exactly the break-even extra cost per side -> mean net ~ 0
    extra = be["extra_bps_per_side"]
    assert abs(r2.net.mean() - extra * 1e-4 * r2.turnover.mean()) < 1e-12


def test_delisting_terminal_return_applied_and_no_trade_cost_on_forced_exit():
    o = np.full((6, 1), 100.0)
    alive = np.array([[1], [1], [1], [0], [0], [0]], bool)
    o = np.where(alive, o, np.nan)
    p = tiny_panel(np.nan_to_num(o, nan=1.0), alive=alive, delist=np.array([-0.5]))
    p.open[~alive] = np.nan; p.close[~alive] = np.nan
    W = np.zeros((6, 1)); W[:3, 0] = 1
    r = run_backtest(p, W, ZERO)
    assert r.gross.sum() == pytest.approx(-0.5)      # bankruptcy wipe-out after last bar is realised


def test_no_position_in_dead_names():
    p = make_market(T=200, N=30, seed=2, delist_frac=0.3)
    W = np.ones((200, 30)) * 0.01
    r = run_backtest(p, W, ZERO)
    assert np.all(r.Wexec[~p.alive] == 0)


# ------------------------------------------------------------------ registry
def test_registry_chain_and_append_only(reg):
    reg.append("NOTE", {"a": 1}); reg.append("NOTE", {"a": 2})
    assert reg.verify_chain()
    with pytest.raises(sqlite3.DatabaseError):
        reg.db.execute("UPDATE events SET payload='{}' WHERE seq=1")
    with pytest.raises(sqlite3.DatabaseError):
        reg.db.execute("DELETE FROM events WHERE seq=1")


def test_registry_detects_tampering(tmp_path):
    r = Registry(tmp_path / "r.sqlite")
    r.append("NOTE", {"a": 1}); r.append("NOTE", {"a": 2})
    r.db.execute("DROP TRIGGER no_update")               # a sophisticated attacker removes the trigger...
    r.db.execute("UPDATE events SET payload='{\"a\":99}' WHERE seq=1")
    r.db.commit()
    assert not r.verify_chain()                          # ...but the hash chain still exposes the edit


def test_prereg_immutable_and_required(reg):
    reg.preregister("h", 1, {"x": 1})
    with pytest.raises(RegistryError):
        reg.preregister("h", 1, {"x": 2})                # cannot rewrite after the fact
    reg.preregister("h", 2, {"x": 2})                    # new version is fine and visible
    with pytest.raises(RegistryError):
        reg.log_experiment("nope", 1, code_sha="", dataset_ids=[], params={}, seed=0, family="f", results={})


def test_trial_counts_include_failures(reg):
    reg.preregister("h", 1, {})
    for p in ({"a": 1}, {"a": 2}, {"a": 2}):
        reg.log_experiment("h", 1, code_sha="c", dataset_ids=["d"], params=p, seed=0, family="f", results={}, status="FAILED")
    tc = reg.trial_count("f")
    assert tc["experiments"] == 3 and tc["variants"] == 2


# ------------------------------------------------------------------ data audits
def test_survivorship_audit():
    assert audit_survivorship(["A"], ["A", "B", "C"], ["B", "C"])
    assert not audit_survivorship(["A", "B", "C"], ["A", "B", "C"], ["B", "C"])


def test_universe_pit_audit():
    bad = audit_universe_pit({"2020-01-01": ["X"]}, {"X": "2020-06-01"}, {})
    assert any(f.check == "universe_leakage" for f in bad)
    bad = audit_universe_pit({"2020-01-01": ["X"]}, {"X": "2010-01-01"}, {"X": "2019-01-01"})
    assert any(f.check == "universe_survivorship" for f in bad)


def test_news_timestamp_audit():
    ok = pd.DataFrame({"event_ts": ["2024-01-02 07:00"], "publication_ts": ["2024-01-02 08:00"], "signal_ts": ["2024-01-02 08:00:05"]})
    assert not audit_news_timestamps(ok)
    bad = pd.DataFrame({"event_ts": ["2024-01-02 07:00"], "publication_ts": ["2024-01-02 08:00"], "signal_ts": ["2024-01-02 07:00"]})
    assert audit_news_timestamps(bad)


def test_fundamentals_use_availability_not_period_end():
    f = pd.DataFrame({"ticker": ["A", "A"], "field": ["eps", "eps"], "period_end": ["2023-12-31", "2024-03-31"],
                      "available_ts": ["2024-02-20", "2024-05-05"], "value": [1.0, 2.0]})
    got = asof_fundamentals(pd.Timestamp("2024-04-15"), f)
    assert list(got["value"]) == [1.0]                    # Q1 period ended before 4/15 but was not yet published


def test_panel_validator_catches_corruption():
    p = make_market(T=100, N=10, seed=1, delist_frac=0, late_list_frac=0)
    assert not [f for f in validate_panel(p) if f.severity == "FAIL"]
    p.high[10, 3] = p.low[10, 3] * 0.5
    assert [f for f in validate_panel(p) if f.check == "ohlc_consistency"]
    p.ts[5] = p.ts[4]
    assert [f for f in validate_panel(p) if f.check.startswith("timestamps")]


# ------------------------------------------------------------------ statistics calibration
def test_null_calibration_of_multiple_testing_tools():
    ps_rc, ps_spa = [], []
    for s in range(60):
        M = np.random.default_rng(s).normal(0, 0.01, (400, 15))
        ps_rc.append(S.white_reality_check(M, 150, seed=s)); ps_spa.append(S.hansen_spa(M, 150, seed=s))
    assert np.mean(np.array(ps_rc) < 0.05) < 0.12 and np.mean(np.array(ps_spa) < 0.05) < 0.14


def test_dsr_deflates_with_more_trials():
    r = np.random.default_rng(3).normal(0.0006, 0.01, 750)
    assert S.deflated_sharpe(r, 1)["dsr"] > S.deflated_sharpe(r, 1000, 1 / 750)["dsr"]


def test_bh_fdr():
    p = np.array([0.001, 0.008, 0.039, 0.041, 0.9])
    assert list(S.bh_fdr(p, 0.05)) == [True, True, False, False, False]


def test_power_statement():
    assert S.min_detectable_sharpe(250) > 2 * S.min_detectable_sharpe(1250) * 0.9
    assert S.power_at_sharpe(2500, 1.0) > 0.9 > S.power_at_sharpe(250, 1.0)


def test_pbo_high_for_selection_on_noise_low_for_real_edge():
    rng = np.random.default_rng(0)
    noise = rng.normal(0, 0.01, (800, 40))
    assert S.pbo_cscv(noise)["pbo"] > 0.3
    real = rng.normal(0, 0.01, (800, 40)); real[:, 7] += 0.002
    assert S.pbo_cscv(real)["pbo"] < 0.2


# ------------------------------------------------------------------ no silent missing-data handling
def test_engine_refuses_to_zero_fill_undocumented_gaps():
    from edgelab.data import DataGapError
    p = make_market(T=100, N=10, seed=1, delist_frac=0, late_list_frac=0)
    W = np.full((100, 10), 0.05)
    p.open[40, 3] = np.nan; p.close[40, 3] = np.nan          # provider dropped a bar while the name is alive
    with pytest.raises(DataGapError):
        run_backtest(p, W, Exec())
    p.excluded = np.zeros((100, 10), bool); p.excluded[40, 3] = True   # documented exclusion -> explicit, allowed
    r = run_backtest(p, W, Exec())
    assert r.Wexec[40, 3] == 0                                # excluded cell is never traded


def test_assumed_spreads_are_reported_not_hidden():
    p = make_market(T=100, N=10, seed=1, delist_frac=0, late_list_frac=0)
    p.spread_bps = None
    r = run_backtest(p, np.full((100, 10), 0.05), Exec())
    assert r.assumptions["spread_source"] == "assumed_constant" and r.assumptions["default_spread_held_cells"] > 0
