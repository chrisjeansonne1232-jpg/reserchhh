"""Shared DAILY_SWING_V2 context: the cube, empirical split resolution, identity masks and per-variant membership/exclusions.

Used by the pre-discovery sweep, the exclusion-bias diagnostic and the discovery panel builder. The BASELINE state must reproduce the audited V2 numbers exactly
(1,946,000 raw member cells; 50,503 removed by split/discontinuity exclusions; 12,402 by the identity mask; 1,883,548 final) -- asserted by check_baseline()."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .daily_swing import build_cube, build_claims, pit_membership, resolve_claims, unrecorded_discontinuities
from .daily_swing_identity import boundaries, identity_mask, observations
from .daily_swing_v2_spec import SPEC
from .integrity import MarketCalendar

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
BASE = dict(top_n=SPEC["universe"]["top_n"], lookback=SPEC["universe"]["lookback_sessions"], min_price=SPEC["universe"]["min_last_close"])
BIG = 10 ** 9


@dataclass
class Ctx:
    daily: pd.DataFrame
    master: pd.DataFrame
    sess: pd.DatetimeIndex
    cube: object
    t0: int
    last: pd.Timestamp
    claims: pd.DataFrame
    cl: pd.DataFrame
    ev: pd.DataFrame
    claim_sessions: dict
    obs: pd.DataFrame
    snaps: pd.DataFrame
    bnd: pd.DataFrame
    id_all: np.ndarray
    split_excl_from: np.ndarray                  # variant-independent split-event exclusions (session index, BIG = none)
    split_excl_rows: list = field(default_factory=list)


def load_ctx() -> Ctx:
    d = pd.read_parquet(RAW / "alpaca_daily_all.parquet")
    master = pd.read_parquet(RAW / "massive_security_master_CS.parquet")
    last = pd.Timestamp(d["date"].max())
    sess = MarketCalendar("US_EQUITY").sessions("2016-01-04", str(last.date()))
    cube, _ = build_cube(d, sess)
    t0 = int(sess.searchsorted(pd.Timestamp(SPEC["scope"]["window_start"])))
    U = set(master["ticker"])
    sm = pd.read_parquet(RAW / "massive_splits_since_2016.parquet"); sm = sm[sm["ticker"].isin(U)]
    sa = pd.read_parquet(RAW / "alpaca_splits.parquet")
    sa = pd.DataFrame({"ticker": sa["symbol"], "execution_date": sa["ex_date"], "split_from": sa["old_rate"], "split_to": sa["new_rate"]}); sa = sa[sa["ticker"].isin(U)]
    claims = build_claims(sm, sa, (SPEC["scope"]["window_start"], str(last.date())))
    cl, ev = resolve_claims(claims, cube)
    cs: dict[int, list] = {}
    for r in cl[cl["spell"] >= 0].itertuples():
        cs.setdefault(int(r.spell), []).append(r.s0)
    cs = {k: np.array(v) for k, v in cs.items()}
    snap_files = sorted((RAW / "massive_pit_master").glob("snapshot_*.parquet"))
    snaps = pd.concat([pd.read_parquet(f) for f in snap_files])
    obs = observations(snaps, master, last)
    bnd, _ = boundaries(obs, sess)
    id_all = identity_mask(cube, bnd, part="all")
    sef = np.full(cube.S, BIG, dtype=np.int64)
    rows = []
    for r in ev[ev["action"] == "EXCLUDE_SPELL"].itertuples():
        if r.spell >= 0:
            sef[r.spell] = min(sef[r.spell], r.exclude_from_session)
            rows.append({"spell": r.spell, "ticker": r.ticker, "from_session": r.exclude_from_session, "cause": "DISPUTED_SPLIT_AMBIGUOUS" if r.disputed else "AGREED_SPLIT_TESTABLE_AMBIGUOUS", "why": r.why})
    return Ctx(d, master, sess, cube, t0, last, claims, cl, ev, cs, obs, snaps, bnd, id_all, sef, rows)


def build_state(ctx: Ctx, top_n=BASE["top_n"], lookback=BASE["lookback"], min_price=BASE["min_price"]) -> dict:
    """Membership + exclusions + identity mask for one universe variant. min_real scales as round(5/6*lookback) (50 for 60)."""
    cube, t0, T, S = ctx.cube, ctx.t0, ctx.cube.T, ctx.cube.S
    min_real = int(round(lookback * 5 / 6))
    member_raw = pit_membership(cube.close, cube.volume, top_n=top_n, lookback=lookback, min_real=min_real, min_price=min_price, start=t0 - 1)
    member_raw[:t0] = False
    disc = unrecorded_discontinuities(cube, member_raw, ctx.claim_sessions, t0)
    excl_from = ctx.split_excl_from.copy()
    disc_rows = []
    for r in disc[disc["class"] == "UNRECORDED_SPLIT_LIKE"].itertuples():
        excl_from[r.spell] = min(excl_from[r.spell], r.session)
        disc_rows.append({"spell": r.spell, "ticker": r.ticker, "from_session": r.session, "cause": "UNRECORDED_SPLIT_LIKE_DISCONTINUITY"})
    tt = np.arange(T)[:, None]
    after_excl = member_raw & (tt < excl_from[None, :])
    member = after_excl & ~ctx.id_all
    return dict(params=dict(top_n=top_n, lookback=lookback, min_real=min_real, min_price=min_price), member_raw=member_raw, disc=disc, excl_from=excl_from,
                excl_rows=ctx.split_excl_rows + disc_rows, member_after_excl=after_excl, member=member,
                removed_split=member_raw & ~after_excl, removed_id=member_raw & ctx.id_all)


def check_baseline(st: dict) -> dict:
    got = dict(raw=int(st["member_raw"].sum()), removed_split=int(st["removed_split"].sum()), removed_id=int(st["removed_id"].sum()), final=int(st["member"].sum()))
    want = dict(raw=1_946_000, removed_split=50_503, removed_id=12_402, final=1_883_548)
    assert got == want, f"baseline does not reproduce the audited V2 numbers: {got} != {want}"
    return got
