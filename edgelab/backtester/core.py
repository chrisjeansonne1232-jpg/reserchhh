"""Bar-by-bar backtest engine (single asset).

Timeline of one bar t (open O, high H, low L, close C):
  1. holding costs accrue for the interval since the previous bar (short borrow, financing)
  2. an order decided at the CLOSE of bar t-1 fills at the OPEN of bar t, at an adverse price (spread + slippage)
     plus commission                                         <- "signals execute on the next bar"
  3. protective exits are checked against H/L of bar t (stop, trailing stop, profit target):
       * stop and target both reachable in the same bar  -> the STOP is assumed to fill first (pessimistic)
       * bar opens beyond the stop (gap)                  -> fills at the OPEN, not at the stop price
       * a profit target never fills better than its price
  4. equity is marked at C; the strategy's target for the close of bar t is read (it may only use bars <= t)
     and, if it changed, becomes an order for the open of bar t+1; time-stops are armed.

Position sizing: target is a fraction of equity measured at the FILL. Units are then held constant (no
rebalancing as price drifts); a new order is sent only when the target changes. After a stop/time exit the
engine will not re-enter the same side until the target has gone flat or flipped (no instant re-entry loops).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..strategies.base import Signals
from .costs import EQUITY_PESSIMISTIC, Costs


@dataclass
class BacktestResult:
    equity: pd.Series                 # close-marked equity from `start`
    position: pd.Series               # signed exposure (fraction of equity) at each close
    trades: pd.DataFrame
    fills: pd.DataFrame
    costs_paid: dict
    meta: dict = field(default_factory=dict)


def _arr(s: pd.Series | None, index: pd.Index) -> list | None:
    if s is None:
        return None
    return s.reindex(index).to_numpy(float).tolist()


def backtest(bars: pd.DataFrame, signals: Signals, costs: Costs = EQUITY_PESSIMISTIC, *, initial_equity: float = 100_000.0,
             max_leverage: float = 1.0, allow_short: bool = True, start=None, liquidate_at_end: bool = True) -> BacktestResult:
    n = len(bars)
    idx = bars.index
    O, H, L, C = (bars[c].to_numpy(float).tolist() for c in ("open", "high", "low", "close"))
    V = bars["volume"].to_numpy(float).tolist()
    tsn = idx.as_unit("ns").asi8.tolist()                      # ns since epoch (pandas 3 may store us/s units)
    tgt = np.nan_to_num(signals.target.reindex(idx).to_numpy(float), nan=0.0)
    tgt = np.clip(tgt, -max_leverage if allow_short else 0.0, max_leverage).tolist()
    stop_d, take_d, trail_d = (_arr(getattr(signals, k), idx) for k in ("stop_dist", "target_dist", "trail_dist"))
    max_hold = int(signals.max_hold) if signals.max_hold else 0
    i0 = 0 if start is None else int(idx.searchsorted(pd.Timestamp(start) if pd.Timestamp(start).tzinfo else pd.Timestamp(start, tz="UTC")))
    c_bps, k_comm = (costs.half_spread_bps + costs.slippage_bps) / 1e4, costs.commission_bps / 1e4
    borrow, finance = costs.borrow_bps_annual / 1e4, costs.financing_bps_annual / 1e4

    cash, qty = float(initial_equity), 0.0
    last_tgt, pending, lock = 0.0, None, 0
    tr = None                                                 # open trade state
    eq_arr, pos_arr = np.full(n, np.nan), np.full(n, np.nan)
    fills, trades = [], []
    tot = {"slippage_spread": 0.0, "commission": 0.0, "holding": 0.0}
    max_part, ruined = 0.0, False
    sgn = lambda x: (x > 0) - (x < 0)  # noqa: E731

    def fill(t: int, dq: float, ref: float, reason: str):
        nonlocal cash, qty
        side = sgn(dq)
        px = ref * (1 + side * c_bps)
        notional = abs(dq) * px
        comm = notional * k_comm
        cash -= dq * px + comm
        qty += dq
        tot["slippage_spread"] += abs(dq) * abs(px - ref)
        tot["commission"] += comm
        if tr is not None:
            tr["cash"] += -dq * px - comm
            tr["costs"] += abs(dq) * abs(px - ref) + comm
        fills.append((idx[t], side, abs(dq), ref, px, comm, reason))
        return px

    def open_trade(t: int, px: float):
        nonlocal tr
        side = sgn(qty)
        tr = {"entry_i": t, "entry_ts": idx[t], "side": side, "qty": abs(qty), "entry_px": px, "cash": 0.0, "costs": 0.0,
              "stop": None, "take": None, "trail": None, "extreme": px}
        # protective levels come from the decision bar t-1 (known at its close) and stay fixed for the trade
        if stop_d and t > 0 and np.isfinite(stop_d[t - 1]) and stop_d[t - 1] > 0:
            tr["stop"] = px - side * stop_d[t - 1]
        if take_d and t > 0 and np.isfinite(take_d[t - 1]) and take_d[t - 1] > 0:
            tr["take"] = px + side * take_d[t - 1]
        if trail_d and t > 0 and np.isfinite(trail_d[t - 1]) and trail_d[t - 1] > 0:
            tr["trail"] = float(trail_d[t - 1])

    def close_trade(t: int, px: float, reason: str, bars_held: int):
        nonlocal tr
        # trade cash flow so far (entry costs + exit proceeds) == realised net P&L of the round trip
        trades.append((tr["entry_ts"], idx[t], tr["side"], tr["qty"], tr["entry_px"], px, tr["cash"], tr["cash"] / (tr["qty"] * tr["entry_px"]),
                       bars_held, reason, tr["costs"]))
        tr = None

    for t in range(i0, n):
        o, h, l, c = O[t], H[t], L[t], C[t]
        # ---- 1. holding costs for the interval since the previous bar, on the position carried through it
        if t > i0 and qty != 0.0:
            days = (tsn[t] - tsn[t - 1]) / 86_400e9
            fee = 0.0
            if qty < 0:
                fee += abs(qty) * C[t - 1] * borrow * days / 365
            else:
                borrowed = qty * C[t - 1] - (cash + qty * C[t - 1])
                if borrowed > 0:
                    fee += borrowed * finance * days / 365
            if fee:
                cash -= fee
                tot["holding"] += fee
                if tr is not None:
                    tr["cash"] -= fee
                    tr["costs"] += fee
        # ---- 2. execute the order decided at the previous close
        if pending is not None:
            want, reason = pending
            pending = None
            qty_in = qty
            if qty_in != 0.0 and (want == 0.0 or sgn(want) != sgn(qty_in)):       # exit or flip: close first
                px = fill(t, -qty_in, o, reason)
                close_trade(t, px, reason, t - tr["entry_i"])
            if want != 0.0 and (qty == 0.0 or sgn(want) == sgn(qty)):
                eq_open = cash + qty * o
                qty_des = want * eq_open / (o * (1 + c_bps) * (1 + k_comm))   # sized at the adverse fill incl. commission: never over-levered
                dq = qty_des - qty
                if abs(dq) * o > 1e-9 * max(eq_open, 1.0):
                    was_flat = qty == 0.0
                    if was_flat:
                        tr = {"cash": 0.0, "costs": 0.0}      # placeholder so entry costs accrue to the trade
                    px = fill(t, dq, o, "signal")
                    if was_flat:
                        c0, k0 = tr["cash"], tr["costs"]
                        open_trade(t, px)
                        tr["cash"], tr["costs"] = c0, k0
                    if V[t] > 0:
                        max_part = max(max_part, abs(dq) * px / (o * V[t]))   # share of the bar's dollar volume
                    if tr is not None and qty != 0.0:
                        tr["qty"] = max(tr["qty"], abs(qty))
        # ---- 3. protective exits inside bar t
        if tr is not None and qty != 0.0 and (tr["stop"] is not None or tr["take"] is not None or tr["trail"] is not None):
            side = tr["side"]
            eff = tr["stop"]
            if tr["trail"] is not None:
                tl = tr["extreme"] - side * tr["trail"]
                eff = tl if eff is None else (max(eff, tl) if side > 0 else min(eff, tl))
            px_exit, why = None, ""
            if eff is not None:
                if side > 0:
                    if t > tr["entry_i"] and o <= eff:
                        px_exit, why = o, "stop_gap"
                    elif l <= eff:
                        px_exit, why = eff, "stop"
                else:
                    if t > tr["entry_i"] and o >= eff:
                        px_exit, why = o, "stop_gap"
                    elif h >= eff:
                        px_exit, why = eff, "stop"
            if px_exit is None and tr["take"] is not None:
                if (side > 0 and h >= tr["take"]) or (side < 0 and l <= tr["take"]):
                    px_exit, why = tr["take"], "target"
            if px_exit is not None:
                held = t - tr["entry_i"] + 1
                px = fill(t, -qty, px_exit, why)
                close_trade(t, px, why, held)
                lock = side
            else:
                tr["extreme"] = max(tr["extreme"], h) if side > 0 else min(tr["extreme"], l)
        # ---- 4. mark to market, then read the decision made at this close
        eq = cash + qty * c
        if eq <= 0:
            eq, ruined = 0.0, True
            eq_arr[t], pos_arr[t] = 0.0, 0.0
            break
        eq_arr[t], pos_arr[t] = eq, qty * c / eq
        if t < n - 1:
            want = tgt[t]
            if abs(want - last_tgt) > 1e-12:
                last_tgt = want
                if lock != 0 and sgn(want) == lock:
                    pass                                   # locked out after a protective exit: wait for flat/flip
                else:
                    lock = 0
                    pending = (want, "signal")
            if max_hold and tr is not None and qty != 0.0 and (t - tr["entry_i"] + 1) >= max_hold:
                pending = (0.0, "time")
                lock = tr["side"]
    # ---- end of data
    if qty != 0.0 and not ruined and liquidate_at_end:
        held = n - tr["entry_i"]
        px = fill(n - 1, -qty, C[n - 1], "end")
        close_trade(n - 1, px, "end", held)
        eq_arr[n - 1] = cash
        pos_arr[n - 1] = 0.0
    elif tr is not None and qty != 0.0:
        # still open (liquidate_at_end=False): P&L marked at the last close, exit costs not charged
        trades.append((tr["entry_ts"], idx[n - 1], tr["side"], tr["qty"], tr["entry_px"], C[n - 1], tr["cash"] + qty * C[n - 1],
                       (tr["cash"] + qty * C[n - 1]) / (tr["qty"] * tr["entry_px"]), n - tr["entry_i"], "open", tr["costs"]))
    eq_s = pd.Series(eq_arr, index=idx).iloc[i0:]
    pos_s = pd.Series(pos_arr, index=idx).iloc[i0:]
    tcols = ["entry_ts", "exit_ts", "side", "qty", "entry_px", "exit_px", "pnl", "ret", "bars_held", "exit_reason", "costs"]
    fcols = ["ts", "side", "qty", "ref_px", "fill_px", "commission", "reason"]
    return BacktestResult(eq_s, pos_s, pd.DataFrame(trades, columns=tcols), pd.DataFrame(fills, columns=fcols),
                          {**tot, "total": sum(tot.values())},
                          {"initial_equity": initial_equity, "start_index": i0, "max_participation": max_part, "ruined": ruined,
                           "costs": costs, "liquidate_at_end": liquidate_at_end})
