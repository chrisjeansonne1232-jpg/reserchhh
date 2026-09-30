"""Causal bar-by-bar backtest engine with realistic-ish execution costs.

Decision at bar t uses only bars <= t (the strategy is fed one bar at a time). Orders fill at the
OPEN of bar t+1+latency. Two holding conventions:
  open_to_open  : hold until next bar's open (overnight risk included)
  open_to_close : enter at open, exit at close, flat overnight (gap included on entry only)
Costs: half-spread, slippage, commission, opening-auction penalty, square-root market impact
(capital dependent), borrow on shorts, financing on leverage.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Callable, Protocol

import numpy as np
import pandas as pd

from .data import DataGapError, Panel


class Strategy(Protocol):
    def on_bar(self, ts: int, bars: dict) -> dict: ...


@dataclass(frozen=True)
class Exec:
    name: str = "baseline"
    spread_mult: float = 1.0
    default_spread_bps: float = 4.0      # used when panel has no spread data (full spread)
    slip_bps: float = 1.0                # per side
    comm_bps: float = 0.5                # per side (commission+exchange fees)
    open_penalty_bps: float = 2.0        # extra per-side cost for open-auction/gap fills
    impact_coef: float = 0.10            # sqrt-participation impact coefficient (x daily vol)
    latency_bars: int = 0
    borrow_bps_annual: float = 50.0
    financing_bps_annual: float = 400.0
    delist_haircut: float = 0.0
    capital: float = 100_000.0
    max_weight: float = 0.10
    max_gross: float = 2.0
    mode: str = "open_to_open"          # or open_to_close
    periods_per_year: int = 252


OPTIMISTIC = Exec("optimistic", spread_mult=0.6, slip_bps=0.3, comm_bps=0.2, open_penalty_bps=0.5, impact_coef=0.05, borrow_bps_annual=30)
BASELINE = Exec("baseline")
PESSIMISTIC = Exec("pessimistic", spread_mult=2.0, slip_bps=3.0, comm_bps=1.0, open_penalty_bps=5.0, impact_coef=0.25,
                   latency_bars=1, borrow_bps_annual=150, delist_haircut=0.10)
SCENARIOS = {"optimistic": OPTIMISTIC, "baseline": BASELINE, "pessimistic": PESSIMISTIC}


@dataclass
class BacktestResult:
    W: np.ndarray                 # decided weights (T,N)
    Wexec: np.ndarray             # weights actually held at each bar
    gross: np.ndarray             # gross return series (T,)
    cost: np.ndarray              # cost series (T,)
    net: np.ndarray               # net return series (T,)
    turnover: np.ndarray          # sum |dw| per bar
    exposure: np.ndarray          # gross exposure per bar
    net_exposure: np.ndarray
    ret_matrix: np.ndarray        # per-asset holding-period return (T,N)
    ts: np.ndarray
    exec: Exec
    trades: pd.DataFrame = field(default_factory=pd.DataFrame)
    assumptions: dict = field(default_factory=dict)   # modelling assumptions that substituted for missing inputs

    def series(self, which: str = "net") -> pd.Series:
        return pd.Series(getattr(self, which), index=pd.DatetimeIndex(self.ts))


def collect_weights(strategy: Strategy, panel: Panel) -> np.ndarray:
    """Feed bars one at a time (structural causality) and record decided target weights."""
    W = np.zeros((panel.T, panel.N))
    idx = {t: i for i, t in enumerate(panel.tickers)}
    for t in range(panel.T):
        out = strategy.on_bar(int(panel.ts[t].astype("datetime64[ns]").astype("int64")), panel.bars_at(t)) or {}
        for k, v in out.items():
            j = idx.get(k)
            if j is not None and np.isfinite(v):
                W[t, j] = float(v)
    return W


def holding_returns(panel: Panel, mode: str, delist_haircut: float = 0.0) -> np.ndarray:
    """R[t,i]: return earned by a position entered at open[t] under `mode`. NaN -> 0."""
    o, c = panel.open, panel.close
    with np.errstate(invalid="ignore", divide="ignore"):
        if mode == "open_to_close":
            R = c / o - 1
        else:
            nxt = np.vstack([o[1:], np.full((1, panel.N), np.nan)])
            R = nxt / o - 1
    alive = panel.alive & np.isfinite(o)
    # terminal bar for delisted names: hold to last close, then apply terminal return
    if panel.delist_ret is not None:
        last = np.zeros_like(alive)
        nxt_alive = np.vstack([alive[1:], np.zeros((1, panel.N), dtype=bool)])
        last = alive & ~nxt_alive
        final_bar = panel.T - 1
        for i in np.flatnonzero(last.any(axis=0)):
            t = np.flatnonzero(last[:, i])[-1]
            if t == final_bar:
                continue  # still alive at panel end
            dr = panel.delist_ret[i]
            if mode == "open_to_close":
                continue  # flat overnight: terminal event never hit
            R[t, i] = (c[t, i] / o[t, i]) * (1 + dr - delist_haircut) - 1
    # cells that are not alive/tradable carry no position (Wexec is masked by `tradable`); they are not 'zero returns'
    R = np.where(np.isfinite(R) & alive, R, 0.0)
    return R


def unknown_terminal_cells(panel: Panel) -> np.ndarray:
    """Final alive bar of every name that stops trading before the panel ends but has no known terminal return."""
    out = np.zeros((panel.T, panel.N), dtype=bool)
    alive = panel.alive & np.isfinite(panel.open)
    if panel.excluded is not None:
        alive = alive & ~panel.excluded
    for i in range(panel.N):
        idx = np.flatnonzero(alive[:, i])
        if len(idx) == 0 or idx[-1] >= panel.T - 1:
            continue
        known = panel.delist_ret is not None and np.isfinite(panel.delist_ret[i])
        if not known:
            out[idx[-1], i] = True
    return out


def run_backtest(panel: Panel, W: np.ndarray, ex: Exec = BASELINE, periods_per_year: int | None = None) -> BacktestResult:
    T, N = panel.T, panel.N
    ppy = periods_per_year or ex.periods_per_year
    excl = panel.excluded if panel.excluded is not None else np.zeros((T, N), bool)
    missing = panel.alive & ~excl & ~(np.isfinite(panel.open) & np.isfinite(panel.close))
    if missing.any():
        raise DataGapError(f"{int(missing.sum())} alive bars have missing prices and are not documented exclusions; "
                           "resolve them or record them in the GapLedger -- the engine never zero-fills or forward-fills")
    # position limits
    Wc = np.clip(W, -ex.max_weight, ex.max_weight)
    gross_w = np.abs(Wc).sum(axis=1, keepdims=True)
    Wc = np.where(gross_w > ex.max_gross, Wc * ex.max_gross / np.maximum(gross_w, 1e-12), Wc)
    # latency: decision at t fills at open of t+1+L; Wexec[t] is what is held from open[t]
    shift = 1 + ex.latency_bars
    Wexec = np.zeros_like(Wc)
    if shift < T:
        Wexec[shift:] = Wc[:-shift]
    tradable = panel.alive & np.isfinite(panel.open) & ~excl
    if ex.mode == "open_to_open":
        tradable[-1] = False   # final bar: next open is unobserved, so no holding period is claimed
    Wexec = np.where(tradable, Wexec, 0.0)
    R = holding_returns(panel, ex.mode, ex.delist_haircut)
    unk = unknown_terminal_cells(panel)
    if ex.mode == "open_to_open" and (unk & (np.abs(Wexec) > 0)).any():
        bad = [panel.tickers[i] for i in np.flatnonzero((unk & (np.abs(Wexec) > 0)).any(axis=0))]
        raise DataGapError(f"positions held through delisting with UNKNOWN terminal return for {bad[:5]}: unknown is never "
                           "assumed to be zero -- supply delist_ret or exclude these names via the GapLedger")
    gross = (Wexec * R).sum(axis=1)

    # turnover & costs
    if ex.mode == "open_to_close":
        dW = 2 * np.abs(Wexec)
    else:
        prev = np.vstack([np.zeros((1, N)), Wexec[:-1]])
        # forced exit of a delisted name is not a discretionary trade -> no trading cost
        prev_t = np.vstack([np.zeros((1, N), dtype=bool), tradable[:-1]])
        prev = np.where(prev_t, prev, 0.0)
        dW = np.abs(Wexec - prev)
    held = (np.abs(Wexec) > 0)
    if panel.spread_bps is not None:
        sp = np.where(np.isfinite(panel.spread_bps), panel.spread_bps, ex.default_spread_bps)
        n_default_spread = int((~np.isfinite(panel.spread_bps) & held).sum())
    else:
        sp = np.full((T, N), ex.default_spread_bps)
        n_default_spread = int(held.sum())
    per_side = 0.5 * sp * ex.spread_mult + ex.slip_bps + ex.comm_bps + ex.open_penalty_bps
    # sqrt-participation impact using trailing (t-1) ADV -- no look-ahead
    dollar = np.where(np.isfinite(panel.close * panel.volume), panel.close * panel.volume, 0.0)
    adv = pd.DataFrame(dollar).rolling(20, min_periods=5).mean().shift(1).to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        ret_c = pd.DataFrame(panel.close).pct_change(fill_method=None)
        vol = ret_c.rolling(20, min_periods=5).std().shift(1).to_numpy()
        part = np.where(adv > 0, dW * ex.capital / adv, 0.0)
        impact_bps = ex.impact_coef * np.where(np.isfinite(vol), vol, 0.02) * 1e4 * np.sqrt(np.clip(part, 0, 5))
    n_default_vol = int((~np.isfinite(vol) & (dW > 0)).sum())
    impact_bps = np.where(np.isfinite(impact_bps), impact_bps, 0.0)
    side_bps = per_side + impact_bps
    cost = (dW * side_bps).sum(axis=1) * 1e-4
    short_notional = np.clip(-Wexec, 0, None).sum(axis=1)
    lev = np.clip(np.abs(Wexec).sum(axis=1) - 1.0, 0, None)
    cost += short_notional * ex.borrow_bps_annual * 1e-4 / ppy + lev * ex.financing_bps_annual * 1e-4 / ppy
    net = gross - cost
    res = BacktestResult(Wc, Wexec, gross, cost, net, dW.sum(axis=1), np.abs(Wexec).sum(axis=1),
                         Wexec.sum(axis=1), R, panel.ts, ex)
    res.assumptions = {"default_spread_held_cells": n_default_spread, "default_vol_traded_cells": n_default_vol,
                       "spread_source": "panel" if panel.spread_bps is not None else "assumed_constant"}
    res.trades = trade_table(panel, Wexec, R, cost_matrix=dW * side_bps * 1e-4)
    return res


def trade_table(panel: Panel, Wexec: np.ndarray, R: np.ndarray, cost_matrix: np.ndarray) -> pd.DataFrame:
    """Position episodes per ticker (contiguous same-sign holding) with net P&L contribution."""
    rows = []
    pnl = Wexec * R - cost_matrix
    for i in range(panel.N):
        w = Wexec[:, i]
        sign = np.sign(w)
        t = 0
        while t < len(w):
            if sign[t] == 0:
                t += 1
                continue
            s = t
            while t < len(w) and sign[t] == sign[s]:
                t += 1
            rows.append((panel.tickers[i], s, t - 1, float(sign[s]), float(pnl[s:t, i].sum())))
    return pd.DataFrame(rows, columns=["ticker", "t_in", "t_out", "side", "pnl"])


def break_even_cost_multiplier(res: BacktestResult, baseline_side_cost_bps: float | None = None) -> dict:
    """Extra per-side bps (on top of the modelled cost) that would drive mean net return to zero."""
    turn = res.turnover.mean()
    if turn <= 0:
        return {"extra_bps_per_side": float("inf"), "cost_multiple": float("inf")}
    extra = res.net.mean() / turn * 1e4
    base = res.cost.mean()
    return {"extra_bps_per_side": float(extra),
            "cost_multiple": float((res.gross.mean()) / base) if base > 0 else float("inf")}


def evaluate_scenarios(panel: Panel, W: np.ndarray, base: Exec | None = None) -> dict[str, BacktestResult]:
    out = {}
    for name, ex in SCENARIOS.items():
        if base is not None:
            ex = replace(ex, mode=base.mode, capital=base.capital, max_weight=base.max_weight, max_gross=base.max_gross)
        out[name] = run_backtest(panel, W, ex)
    return out
