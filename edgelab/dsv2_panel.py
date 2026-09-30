"""Engine panel from the audited DAILY_SWING_V2 universe.

* columns = spells that are ever raw PIT members in the window (identity = spell, so no returns across issuers)
* prices: raw Alpaca SIP bars, back-adjusted ONLY for splits the prices confirmed (or both providers agreed on and prices could not refute: 'accepted, unverified');
  disputed-and-ambiguous splits never get an adjustment because their spells are excluded. No dividends (price returns only): a declared limitation.
* alive = a real bar (volume > 0) and NOT masked by V2's split/discontinuity exclusions or the identity mask; masked cells are NaN, never filled
* membership is NOT expressed through `alive`: a strategy must not learn whether a name will later join the universe from its presence in the feed. It is provided separately as
  `member_next[t]` = membership at session t+1 (computed from sessions <= t), and strategies trade members only
* terminal returns: spells whose last real bar is > 5 sessions before the end of the panel get the scenario's terminal return (engine, open_to_open). Spells whose cells stop because of a
  data-quality mask get 0.0 (exit at the last valid price, ASSUMED) and are counted in meta
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .data import Panel
from .dsv2_ctx import Ctx

TERMINAL_SCENARIOS = {"S0_zero": 0.0, "S1_shumway": -0.30, "S2_total_loss": -1.0}
PRE = 70            # sessions of history handed to strategies before the panel starts (max lookback 60 + skip 5 + margin)


def adjusted_arrays(ctx: Ctx):
    """(open, high, low, close, volume) split-adjusted copies of the cube and the adjustment table."""
    cube, ev, cl = ctx.cube, ctx.ev, ctx.cl
    O, H, L, C, V = (cube.open.copy(), cube.high.copy(), cube.low.copy(), cube.close.copy(), cube.volume.copy())
    adj = []
    for r in ev[ev["action"] == "ADJUST"].itertuples():
        adj.append((int(r.spell), int(r.adjust_session), float(r.adjust_multiplier), "confirmed"))
    for r in ev[ev["action"] == "ACCEPT_CORROBORATED_UNVERIFIED"].itertuples():
        cc = cl[cl["event_id"] == r.event_id]
        if r.spell >= 0 and len(cc):
            adj.append((int(r.spell), int(r.claimed_session), float(cc.iloc[0]["price_multiplier"]), "accepted_unverified"))
    for c, s, m, _ in adj:
        for A in (O, H, L, C):
            A[:s, c] *= m
        V[:s, c] /= m
    return O, H, L, C, V, pd.DataFrame(adj, columns=["spell", "session", "multiplier", "kind"])


def build_panel(ctx: Ctx, st: dict, start: str, end: str, terminal: float = -0.30) -> tuple[Panel, dict]:
    cube, sess = ctx.cube, ctx.sess
    a, b = int(sess.searchsorted(pd.Timestamp(start))), int(sess.searchsorted(pd.Timestamp(end), side="right"))
    O, H, L, C, V, adj = adjusted_arrays(ctx)
    T = cube.T
    tt = np.arange(T)[:, None]
    masked = (tt >= st["excl_from"][None, :]) | ctx.id_all                     # data-quality masks (never fed, never traded, never filled)
    real = cube.real()
    cols = np.flatnonzero(st["member_raw"][a:b].any(0))                         # spells that are ever raw PIT members inside the panel window
    win = slice(a, b)
    keep = real[win][:, cols] & ~masked[win][:, cols]
    def cut(A, fill=np.nan):
        X = A[win][:, cols].copy(); X[~keep] = fill; return X
    o, h, l, c, v = (cut(x) for x in (O, H, L, C, V))
    Nn = len(cols)
    tick = np.array([f"{cube.spell_ticker[k]}|{k}" for k in cols])
    excluded = real[win][:, cols] & masked[win][:, cols]                        # bar exists but is masked: documented exclusion, not a gap
    end_i = b - a
    delist = np.full(Nn, np.nan)
    ended, mask_terminated = 0, 0
    ended_mask, mask_term_mask = np.zeros(Nn, dtype=bool), np.zeros(Nn, dtype=bool)
    for j, k in enumerate(cols):
        ix = np.flatnonzero(keep[:, j])
        if len(ix) == 0:
            continue
        last = ix[-1]
        cut_by_mask = bool(excluded[last + 1:, j].any()) and not bool(keep[last + 1:, j].any())
        if last >= end_i - 1:
            continue
        if cut_by_mask:
            delist[j] = 0.0; mask_terminated += 1; mask_term_mask[j] = True      # exit at the last valid price: ASSUMED, counted
        elif last < end_i - 5:
            delist[j] = terminal; ended += 1; ended_mask[j] = True
    ts = sess[win].to_numpy()
    # evaluator substitution (disclosed in the discovery plan): its survivorship hard gate compares with the master's delisted names, which is meaningless for a universe-filtered panel
    p = Panel(ts=ts, tickers=list(tick), open=o, high=h, low=l, close=c, volume=v, alive=keep | excluded, delist_ret=delist,
              meta={"master_tickers": list(tick), "delisted_in_master": [tick[j] for j in np.flatnonzero(ended_mask)]}, excluded=excluded)
    # membership at the NEXT session, from sessions <= t only (V2's ranking is strictly point-in-time); rows outside the panel are unused
    mem = st["member"][:, cols]
    member_next = np.zeros((end_i, Nn), dtype=bool)
    member_next[:-1] = mem[a + 1: b]
    if b < T:
        member_next[-1] = mem[b]
    pre_lo = max(0, a - PRE)
    pre = {"open": np.where(real[pre_lo:a][:, cols] & ~masked[pre_lo:a][:, cols], O[pre_lo:a][:, cols], np.nan),
           "close": np.where(real[pre_lo:a][:, cols] & ~masked[pre_lo:a][:, cols], C[pre_lo:a][:, cols], np.nan),
           "dv": np.where(real[pre_lo:a][:, cols] & ~masked[pre_lo:a][:, cols], (C * V)[pre_lo:a][:, cols], np.nan)}
    # equal-weight benchmark of PIT members (open_to_open), used for the evaluator's factor/regime gates
    with np.errstate(invalid="ignore", divide="ignore"):
        nxt = np.vstack([o[1:], np.full((1, Nn), np.nan)])
        R = nxt / o - 1
    bm = np.where(member_next & np.isfinite(R) & keep, R, np.nan)
    benchmark = np.nan_to_num(np.nanmean(bm, axis=1))
    meta = {"cols": cols, "member_next": member_next, "pre": pre, "benchmark": benchmark, "window": (str(sess[a].date()), str(sess[b - 1].date())), "n_spells": Nn,
            "terminal_return_ended_spells": terminal, "ended_spells": ended, "mask_terminated_spells": mask_terminated, "ended_mask": ended_mask, "mask_term_mask": mask_term_mask, "keep": keep, "adjustments": adj,
            "ts_to_row": {int(t.astype("datetime64[ns]").astype("int64")): i for i, t in enumerate(ts)}}
    p.meta.update({k: meta[k] for k in ("window", "n_spells")})
    return p, meta


def with_terminal(panel: Panel, meta: dict, value: float) -> Panel:
    """Same bars, different terminal return for the genuinely ended spells (mask-terminated spells keep their assumed 0.0)."""
    import dataclasses
    d = panel.delist_ret.copy()
    d[meta["ended_mask"]] = value
    return dataclasses.replace(panel, delist_ret=d)


def unobservable_holding_bars(panel: Panel, Wexec: np.ndarray) -> dict:
    """Held position-bars whose next open is missing because the next bar is masked or absent (engine treats such a return as 0, never as data)."""
    nxt_open = np.vstack([panel.open[1:], np.full((1, panel.N), np.nan)])
    held = (np.abs(Wexec) > 0) & np.isfinite(panel.open)
    held[-1] = False
    ended_here = np.zeros_like(held)
    unobs = held & ~np.isfinite(nxt_open)
    return {"held_position_bars": int(held.sum()), "unobservable_next_open": int(unobs.sum()), "share": float(unobs.sum() / max(1, held.sum()))}
