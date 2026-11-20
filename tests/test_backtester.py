"""Backtester correctness: hand-computed answers, invariants, stop semantics, no-lookahead, cross-check vs the older engine."""
import numpy as np
import pandas as pd
import pytest

from edgelab.backtester import EQUITY_PESSIMISTIC, ZERO, Costs, backtest, summarize
from edgelab.strategies import Signals, Strategy, check_causality, from_entries_exits
from edgelab.strategies.library import BuyHold, SMACross


def mk(o, h=None, l=None, c=None, freq="D", start="2020-01-01"):
    o = np.asarray(o, float)
    c = o if c is None else np.asarray(c, float)
    h = np.maximum(o, c) if h is None else np.asarray(h, float)
    l = np.minimum(o, c) if l is None else np.asarray(l, float)
    idx = pd.date_range(start, periods=len(o), freq=freq, tz="UTC")
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": 1e6}, index=idx)


def sig(target, **kw):
    return Signals(pd.Series(target, dtype=float), **{k: (pd.Series(v, dtype=float) if isinstance(v, list) else v) for k, v in kw.items()})


def with_idx(s: Signals, bars):
    for f in ("target", "stop_dist", "target_dist", "trail_dist"):
        v = getattr(s, f)
        if v is not None:
            v.index = bars.index
    return s


def random_walk(n=1500, seed=1, freq="D", drift=0.0003, vol=0.01):
    rng = np.random.default_rng(seed)
    r = rng.normal(drift, vol, n)
    c = 100 * np.exp(np.cumsum(r))
    o = np.r_[100, c[:-1]] * np.exp(rng.normal(0, vol / 3, n))
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, vol / 2, n)))
    l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, vol / 2, n)))
    idx = pd.date_range("2018-01-01", periods=n, freq=freq, tz="UTC")
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": 1e6}, index=idx)


# ------------------------------------------------------------------ exact hand-computed answer
def test_hand_computed_round_trip_with_costs():
    # decide long at close of bar 1, fill at OPEN of bar 2 (100); decide flat at close of bar 4, fill at OPEN of bar 5 (110)
    bars = mk([100, 100, 100, 105, 108, 110, 111])
    tgt = [0, 1, 1, 1, 0, 0, 0]
    costs = Costs(half_spread_bps=5, slippage_bps=5, commission_bps=10, borrow_bps_annual=0, financing_bps_annual=0)
    res = backtest(bars, with_idx(sig(tgt), bars), costs)
    c, k = 10e-4, 10e-4
    expected = 100_000 / (100 * (1 + c) * (1 + k)) * 110 * (1 - c) * (1 - k)
    assert res.equity.iloc[-1] == pytest.approx(expected, rel=1e-12)
    f = res.fills
    assert list(f.ts) == [bars.index[2], bars.index[5]]            # next-bar-open execution, nothing earlier
    assert f.ref_px.tolist() == [100.0, 110.0]
    assert f.fill_px.tolist() == pytest.approx([100.1, 109.89])
    assert len(res.trades) == 1 and res.trades.exit_reason.iloc[0] == "signal"
    assert res.trades.pnl.iloc[0] == pytest.approx(expected - 100_000, rel=1e-9)


def test_signal_cannot_trade_on_its_own_bar():
    # target flips long on the very first bar; the earliest possible fill is the second bar's open
    bars = mk([100, 101, 102, 103])
    res = backtest(bars, with_idx(sig([1, 1, 1, 1]), bars), ZERO)
    assert res.fills.ts.iloc[0] == bars.index[1] and res.fills.ref_px.iloc[0] == 101.0


# ------------------------------------------------------------------ invariants
def test_zero_cost_buy_and_hold_equals_price_ratio():
    bars = random_walk(400)
    res = backtest(bars, BuyHold().signals(bars), ZERO)
    assert res.equity.iloc[-1] == pytest.approx(100_000 * bars.close.iloc[-1] / bars.open.iloc[1], rel=1e-12)


def test_flat_strategy_keeps_equity_constant():
    bars = random_walk(200)
    res = backtest(bars, with_idx(sig([0.0] * 200), bars), EQUITY_PESSIMISTIC)
    assert (res.equity == 100_000).all() and len(res.trades) == 0


def test_pnl_conservation_sum_of_trades_equals_equity_change():
    bars = random_walk(1500, seed=3)
    res = backtest(bars, SMACross(10, 40, "both").signals(bars), EQUITY_PESSIMISTIC)
    assert len(res.trades) > 10 and (res.trades.exit_reason != "open").all()
    assert res.trades.pnl.sum() == pytest.approx(res.equity.iloc[-1] - 100_000, rel=1e-9)
    # explicit cost ledger: costs recorded on trades equal costs in the totals
    assert res.trades.costs.sum() == pytest.approx(res.costs_paid["total"], rel=1e-9)


def test_more_cost_means_less_money():
    bars = random_walk(1500, seed=4)
    s = SMACross(10, 40, "both").signals(bars)
    eq = [backtest(bars, s, EQUITY_PESSIMISTIC.scaled(k)).equity.iloc[-1] for k in (0, 1, 2, 4)]
    assert eq[0] > eq[1] > eq[2] > eq[3]


def test_long_never_exceeds_one_x_leverage():
    bars = random_walk(600, seed=5)
    res = backtest(bars, SMACross(5, 20, "long").signals(bars), EQUITY_PESSIMISTIC)
    assert res.position.max() <= 1.0 + 1e-9


def test_short_borrow_cost_is_charged_by_calendar_time():
    bars = mk([100.0] * 12)                                    # flat price, daily calendar bars
    costs = Costs(0, 0, 0, borrow_bps_annual=3650.0, financing_bps_annual=0)   # 0.1% of notional per calendar day
    res = backtest(bars, with_idx(sig([-1.0] * 12), bars), costs, liquidate_at_end=False)
    # short opens at bar 1 open; fee accrues at the start of each later bar for the day just elapsed
    days_charged = len(bars) - 2
    assert res.equity.iloc[-1] == pytest.approx(100_000 * (1 - 0.001 * days_charged), rel=1e-9)


def test_no_short_when_not_allowed():
    bars = random_walk(300, seed=6)
    res = backtest(bars, SMACross(5, 20, "both").signals(bars), ZERO, allow_short=False)
    assert res.position.min() >= -1e-12


# ------------------------------------------------------------------ stops / targets
def run_stop(bars, **sigs):
    n = len(bars)
    tgt = [1.0] + [1.0] * (n - 1)
    return backtest(bars, with_idx(sig(tgt, **sigs), bars), ZERO)


def test_stop_fills_at_stop_price():
    bars = mk(o=[100, 100, 101], h=[100, 103, 102], l=[100, 99, 97], c=[100, 102, 98])
    res = run_stop(bars, stop_dist=[2.0, 2, 2])
    t = res.trades.iloc[0]
    assert t.exit_reason == "stop" and t.exit_px == pytest.approx(98.0)


def test_gap_through_stop_fills_at_open_not_at_stop():
    bars = mk(o=[100, 100, 95], h=[100, 103, 96], l=[100, 99, 94], c=[100, 102, 95])
    res = run_stop(bars, stop_dist=[2.0, 2, 2])
    t = res.trades.iloc[0]
    assert t.exit_reason == "stop_gap" and t.exit_px == pytest.approx(95.0)


def test_stop_beats_target_when_both_reachable_in_one_bar():
    bars = mk(o=[100, 100, 100], h=[100, 103, 100], l=[100, 97, 100], c=[100, 100, 100])
    res = run_stop(bars, stop_dist=[2.0, 2, 2], target_dist=[2.0, 2, 2])
    assert res.trades.iloc[0].exit_reason == "stop"


def test_target_never_fills_better_than_its_price():
    bars = mk(o=[100, 100, 104], h=[100, 101, 106], l=[100, 99.5, 103], c=[100, 100, 105])
    res = run_stop(bars, target_dist=[2.0, 2, 2])
    t = res.trades.iloc[0]
    assert t.exit_reason == "target" and t.exit_px == pytest.approx(102.0)      # not the 104 open


def test_trailing_stop_uses_only_prior_bars_extreme():
    # entry 100. bar1 high 105 (extreme -> 105). bar2 low 102.5 <= 105-2=103 -> exit at 103
    bars = mk(o=[100, 100, 104, 104], h=[100, 105, 104, 104], l=[100, 101, 102.5, 104], c=[100, 104, 103, 104])
    res = run_stop(bars, trail_dist=[2.0] * 4)
    t = res.trades.iloc[0]
    assert t.exit_reason == "stop" and t.exit_px == pytest.approx(103.0)


def test_time_stop_exits_at_next_open_and_no_instant_reentry():
    bars = mk(o=[100, 100, 101, 102, 103, 104, 105, 106])
    res = backtest(bars, Signals(pd.Series(1.0, index=bars.index), max_hold=3), ZERO)
    t = res.trades.iloc[0]
    # entry at open of bar 1; held bars 1,2,3; the time-stop is armed at the close of bar 3 and fills at the open of bar 4
    assert t.exit_reason == "time" and t.bars_held == 3 and t.exit_px == 103.0
    assert len(res.trades) == 1                                  # target stayed +1: no re-entry loop


def test_stop_does_not_loop_reentry_but_new_signal_reenters():
    bars = mk(o=[100, 100, 100, 100, 100, 100], h=[100, 100, 100, 100, 100, 100], l=[100, 100, 90, 100, 100, 100], c=[100] * 6)
    # long, stopped on bar 2; target goes flat at bar 3 then long again at bar 4 -> second trade
    s = with_idx(sig([1, 1, 1, 0, 1, 1], stop_dist=[5.0] * 6), bars)
    res = backtest(bars, s, ZERO)
    assert list(res.trades.exit_reason)[0] == "stop" and len(res.trades) == 2


# ------------------------------------------------------------------ no lookahead
def test_engine_is_causal_truncating_future_bars_does_not_change_past_equity():
    bars = random_walk(900, seed=7)
    sg = SMACross(10, 40, "both").signals(bars)
    n = len(bars)
    sg = Signals(sg.target, stop_dist=pd.Series(1.5, index=bars.index), target_dist=pd.Series(3.0, index=bars.index),
                 trail_dist=pd.Series(2.5, index=bars.index), max_hold=40)
    full = backtest(bars, sg, EQUITY_PESSIMISTIC, liquidate_at_end=False)
    for k in (200, 333, 500, 777):
        part = backtest(bars.iloc[:k], Signals(sg.target.iloc[:k], sg.stop_dist.iloc[:k], sg.target_dist.iloc[:k], sg.trail_dist.iloc[:k], 40),
                        EQUITY_PESSIMISTIC, liquidate_at_end=False)
        np.testing.assert_allclose(part.equity.to_numpy(), full.equity.iloc[:k].to_numpy(), rtol=1e-12)
    assert len(full.trades) > 20


class LeakyStrategy(Strategy):
    name = "leaky"

    def signals(self, bars):
        return Signals((bars["close"].shift(-1) > bars["close"]).astype(float))   # peeks at tomorrow


def test_causality_check_catches_a_leaky_strategy_and_passes_a_clean_one():
    bars = random_walk(500, seed=8)
    assert not check_causality(LeakyStrategy(), bars).ok
    assert check_causality(SMACross(10, 40, "both"), bars).ok
    assert check_causality(BuyHold(), bars).ok


def test_leaky_strategy_would_look_amazing_without_the_check():
    # documents WHY the check exists: look-ahead produces an absurd backtest
    bars = random_walk(1500, seed=9)
    res = backtest(bars, LeakyStrategy().signals(bars), ZERO)
    assert summarize(res)["sharpe"] > 3


def test_from_entries_exits_state_machine():
    n = 8
    le = [0, 1, 0, 0, 0, 0, 0, 0]; lx = [0, 0, 0, 1, 0, 0, 0, 0]
    se = [0, 0, 0, 0, 1, 0, 0, 0]; sx = [0, 0, 0, 0, 0, 0, 1, 0]
    out = from_entries_exits(pd.RangeIndex(n), le, lx, se, sx, direction="both")
    assert out.tolist() == [0, 1, 1, 0, -1, -1, 0, 0]
    assert from_entries_exits(pd.RangeIndex(n), le, lx, se, sx, direction="long").tolist() == [0, 1, 1, 0, 0, 0, 0, 0]


# ------------------------------------------------------------------ independent cross-check against the older engine
def test_matches_independent_older_engine_for_long_only_strategy():
    from edgelab.data import Panel
    from edgelab.engine import Exec, run_backtest
    bars = random_walk(1200, seed=11)
    tgt = SMACross(10, 40, "long").signals(bars).target.fillna(0.0).to_numpy().copy()
    tgt[-6:] = 0.0                                               # be flat before the data ends so both engines have closed everything
    new = backtest(bars, Signals(pd.Series(tgt, index=bars.index)), EQUITY_PESSIMISTIC)
    panel = Panel(ts=bars.index.tz_localize(None).to_numpy(), tickers=["X"], open=bars[["open"]].to_numpy(), high=bars[["high"]].to_numpy(),
                  low=bars[["low"]].to_numpy(), close=bars[["close"]].to_numpy(), volume=bars[["volume"]].to_numpy(),
                  alive=np.ones((len(bars), 1), bool))
    ex = Exec("x", default_spread_bps=4.0, slip_bps=2.0, comm_bps=0.5, open_penalty_bps=0.0, impact_coef=0.0, borrow_bps_annual=0.0,
              financing_bps_annual=0.0, max_weight=1.0, max_gross=1.0, mode="open_to_open")
    old = run_backtest(panel, tgt[:, None], ex)
    old_final = 100_000 * float(np.prod(1 + old.net))
    assert new.equity.iloc[-1] == pytest.approx(old_final, rel=2e-5)
    zero = Exec("z", default_spread_bps=0, slip_bps=0, comm_bps=0, open_penalty_bps=0, impact_coef=0, borrow_bps_annual=0,
                financing_bps_annual=0, max_weight=1.0, max_gross=1.0)
    old0 = 100_000 * float(np.prod(1 + run_backtest(panel, tgt[:, None], zero).net))
    from edgelab.backtester import ZERO as Z
    new0 = backtest(bars, Signals(pd.Series(tgt, index=bars.index)), Z).equity.iloc[-1]
    assert new0 == pytest.approx(old0, rel=1e-11)                # identical with no costs
