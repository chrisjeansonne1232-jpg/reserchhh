"""Swing strategies on synthetic data with a KNOWN answer: planted effects are recovered, nulls are null, entries are members only, and the leakage detectors pass."""
import numpy as np
import pytest

from edgelab.data import Panel
from edgelab.engine import Exec, collect_weights, run_backtest
from edgelab.leakage import scramble_test, truncation_test
from edgelab.swing_strategies import make_build

T, N = 400, 300


def market(kind="null", seed=0, phi=-0.4, drift_strength=0.0):
    rng = np.random.default_rng(seed)
    r = np.zeros((T, N))
    e = rng.normal(0, 0.02, (T, N))
    for t in range(1, T):
        r[t] = (phi * r[t - 1] if kind == "reversal" else 0.0) + e[t]
    close = 50 * np.exp(np.cumsum(r, axis=0))
    open_ = np.vstack([close[:1], close[:-1]]) * (1 + rng.normal(0, 0.001, (T, N)))
    vol = np.exp(rng.normal(13, 0.3, (T, N)))
    ts = (np.datetime64("2020-01-01") + np.arange(T)).astype("datetime64[ns]")
    p = Panel(ts=ts, tickers=[f"S{i:03d}" for i in range(N)], open=open_, high=np.maximum(open_, close) * 1.001, low=np.minimum(open_, close) * .999, close=close, volume=vol,
              alive=np.ones((T, N), dtype=bool), delist_ret=np.full(N, np.nan), meta={"master_tickers": [], "delisted_in_master": []})
    member_next = np.zeros((T, N), dtype=bool)
    member_next[:, :250] = True                                                   # names 250.. are never members
    member_next[:, :50] = (np.arange(T)[:, None] % 2 == 0)                       # names 0..49 flip in and out
    meta = {"pre": {"close": np.empty((0, N)), "open": np.empty((0, N)), "dv": np.empty((0, N))}, "member_next": member_next,
            "ts_to_row": {int(t.astype("datetime64[ns]").astype("int64")): i for i, t in enumerate(ts)}}
    return p, meta


ZERO = Exec("zero", spread_mult=0, default_spread_bps=0, slip_bps=0, comm_bps=0, open_penalty_bps=0, impact_coef=0, borrow_bps_annual=0, financing_bps_annual=0)


def sharpe(x):
    return x.mean() / x.std(ddof=1) * np.sqrt(252)


def test_planted_reversal_is_recovered_and_null_is_null():
    p, m = market("reversal")
    W = collect_weights(make_build(m, "rev")(p, {"k": 1, "h": 1}), p)
    g = run_backtest(p, W, ZERO).gross
    assert sharpe(g[10:-2]) > 3                                                   # strong planted effect
    Wm = collect_weights(make_build(m, "mom")(p, {"L": 20, "h": 5}), p)
    assert abs(sharpe(run_backtest(p, Wm, ZERO).gross[30:-2])) < 3                # momentum on a pure-reversal world: no large positive edge
    pn, mn = market("null", seed=1)
    Wn = collect_weights(make_build(mn, "rev")(pn, {"k": 1, "h": 1}), pn)
    assert abs(sharpe(run_backtest(pn, Wn, ZERO).gross[10:-2])) < 3               # no planted effect -> no edge (3 sigma-ish bound; seed fixed)


@pytest.mark.parametrize("kind,params", [("rev", {"k": 3, "h": 3}), ("mom", {"L": 40, "h": 10}), ("volshock", {"dir": 1, "h": 5}), ("overnight", {"dir": -1, "k": 5, "h": 5})])
def test_entries_are_members_only_dollar_neutral_and_decile_sized(kind, params):
    p, m = market("null", seed=2)
    W = collect_weights(make_build(m, kind)(p, params), p)
    h = params["h"]
    rebal = [t for t in range(T) if t % h == 0 and np.abs(W[t]).sum() > 0]
    assert rebal
    for t in rebal:
        nz = W[t] != 0
        assert m["member_next"][t][nz].all(), "a non-member was given a weight on a rebalance bar"
        assert abs(W[t].sum()) < 1e-9 and abs(np.abs(W[t]).sum() - 1.0) < 1e-9        # +0.5 / -0.5
        assert (W[t] > 0).sum() == (W[t] < 0).sum() == max(1, int(0.10 * m["member_next"][t].sum()))
    assert not W[:, 250:].any()                                                   # names that are never members are never traded


@pytest.mark.parametrize("kind,params", [("rev", {"k": 3, "h": 3}), ("volshock", {"dir": 1, "h": 5})])
def test_leakage_detectors_pass(kind, params):
    p, m = market("reversal", seed=3)
    build = make_build(m, kind)
    assert truncation_test(build, params, p).passed and scramble_test(build, params, p).passed


def test_prehistory_gives_the_same_weights_as_running_from_the_start():
    """Starting the panel later but handing the strategy the earlier bars must reproduce the weights of the full run (no warm-up dilution, no leak)."""
    p, m = market("reversal", seed=4)
    W_full = collect_weights(make_build(m, "mom")(p, {"L": 40, "h": 5}), p)
    a = 120
    q = Panel(ts=p.ts[a:], tickers=p.tickers, open=p.open[a:], high=p.high[a:], low=p.low[a:], close=p.close[a:], volume=p.volume[a:], alive=p.alive[a:], delist_ret=p.delist_ret, meta=dict(p.meta))
    mq = dict(m, member_next=m["member_next"][a:], ts_to_row={int(t.astype("datetime64[ns]").astype("int64")): i for i, t in enumerate(q.ts)}, pre={"close": p.close[a - 70:a], "open": p.open[a - 70:a], "dv": (p.close * p.volume)[a - 70:a]})
    Wq = collect_weights(make_build(mq, "mom")(q, {"L": 40, "h": 5}), q)
    # rebalance phase differs (counter starts at the panel start), so compare on the rebalance bars that coincide: the SELECTED SETS must be identical there
    same = 0
    for t in range(a, T - 1):
        if np.abs(W_full[t]).sum() > 0 and np.abs(Wq[t - a]).sum() > 0 and (t % 5 == 0) and ((t - a) % 5 == 0):
            assert np.array_equal(W_full[t] != 0, Wq[t - a] != 0); same += 1
    assert same >= 3
