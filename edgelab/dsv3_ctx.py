"""DAILY_SWING_V3 context = V2 + corrections found by the adversarial review (see daily_swing_v3_spec.py). Kept separate from dsv2_ctx so V1/V2 stay reproducible.

1. twin resolution BEFORE ranking (same security under old and new ticker, bit-identical bars)
2. identity mask is CAUSAL: only [s2, s2 + lookback) after a hand-over is observable; cells inside the unresolved window are retained and measured
3. splits both providers agree on use a wider tolerance floor (reverse-split ex-dates are noisy)
4. jumps are NEVER excluded (that hid crash losses); an unrecorded split is adjusted only when |ln R| >= 1.0 with continuous dollar volume
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

from .daily_swing import build_cube, build_claims, pit_membership, resolve_claims, unrecorded_discontinuities
from .daily_swing_identity import boundaries, identity_mask, observations
from .daily_swing_v3_spec import SPEC
from .integrity import MarketCalendar

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
BIG = 10 ** 9
BASE = dict(top_n=SPEC["universe"]["top_n"], lookback=SPEC["universe"]["lookback_sessions"], min_price=SPEC["universe"]["min_last_close"])
TW = SPEC["twins"]
CONT_DAYS = SPEC["twins"].get("continuation_calendar_days", 90)
COMMON = np.array(SPEC["split_resolution"]["common_ratios"], dtype=float)


def resolve_twins(daily: pd.DataFrame, min_identical: int = TW["min_identical_sessions"], min_frac: float = TW["min_identical_fraction_within_stretch"]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The provider serves a renamed security's full history under the NEW ticker while the OLD ticker keeps its own history: two tickers, bit-identical bars.
    Detect pairs from the bars alone (identical open/high/low/close/volume on >= min_identical sessions and on >= min_frac of their overlap), keep the ticker whose
    history ends later (tie: starts earlier, then alphabetical) and drop the other's identical bars. Same-day information only; no return is used. Vectorised."""
    real = daily[daily["volume"] > 0]
    key = ["date", "open", "high", "low", "close", "volume"]
    dup = real[real.duplicated(key, keep=False)][["ticker"] + key].copy()
    dup["gid"] = dup.groupby(key, sort=False).ngroup()
    sz = dup.groupby("gid")["ticker"].transform("nunique")
    dup = dup[sz >= 2]
    # all ordered pairs (a, b) of DIFFERENT tickers within a group (groups are almost always of size 2)
    pr = dup[["gid", "ticker", "date"]].merge(dup[["gid", "ticker"]], on="gid", suffixes=("", "_b"))
    pr = pr[pr["ticker"] < pr["ticker_b"]]
    cnt = pr.groupby(["ticker", "ticker_b"])["date"].agg(identical_sessions="size", first_identical="min", last_identical="max").reset_index()
    cnt = cnt[cnt["identical_sessions"] >= min_identical]
    span = real.groupby("ticker")["date"].agg(first="min", last="max", n="nunique")
    rows = []
    if len(cnt):
        nd = real.groupby("ticker")["date"].agg(lambda x: set(x.tolist()))
        for r in cnt.itertuples():
            overlap = sum(1 for x in (nd[r.ticker] & nd[r.ticker_b]) if r.first_identical <= x <= r.last_identical)      # sessions both traded inside the identical stretch
            if overlap and r.identical_sessions / overlap >= min_frac:
                end_ = r.last_identical + pd.Timedelta(days=CONT_DAYS)
                cont = {t: any(r.last_identical < x <= end_ for x in nd[t]) for t in (r.ticker, r.ticker_b)}      # bars continue just after the stretch
                keep, drop = sorted((r.ticker, r.ticker_b), key=lambda t: (not cont[t], -span.loc[t, "last"].value, span.loc[t, "first"].value, t))
                rows.append({"kept": keep, "dropped": drop, "identical_sessions": int(r.identical_sessions), "overlap_sessions": int(overlap),
                             "first_identical": r.first_identical, "last_identical": r.last_identical})
    tw = pd.DataFrame(rows, columns=["kept", "dropped", "identical_sessions", "overlap_sessions", "first_identical", "last_identical"])
    if not len(tw):
        tw["cells_dropped"] = []
        return daily, tw
    # rows of a dropped ticker in a group that also contains its kept partner
    d1 = dup.merge(tw[["kept", "dropped"]], left_on="ticker", right_on="dropped")
    has_keeper = d1.merge(dup[["gid", "ticker"]].rename(columns={"ticker": "kept"}), on=["gid", "kept"])
    drop_rows = has_keeper[["ticker", "date"]].drop_duplicates()
    out = daily.merge(drop_rows.assign(_drop=1), on=["ticker", "date"], how="left")
    out = out[out["_drop"].isna()].drop(columns="_drop")
    tw["cells_dropped"] = tw["dropped"].map(drop_rows.groupby("ticker").size()).fillna(0).astype(int)
    # merge: the dropped twin's own real bars INSIDE the identical stretch (sessions the kept ticker has no real bar) move to the kept ticker, so one security is one column
    realk = real[["ticker", "date"]]
    mv = []
    for r in tw.itertuples():
        own = out[(out["ticker"] == r.dropped) & (out["volume"] > 0) & (out["date"] >= r.first_identical) & (out["date"] <= r.last_identical)]
        if len(own):
            own = own[~own["date"].isin(realk.loc[realk["ticker"] == r.kept, "date"])]
        mv.append(own.assign(ticker=r.kept))
    moved = pd.concat(mv) if mv else out.iloc[0:0]
    tw["cells_moved"] = [int(len(m_)) for m_ in mv]
    if len(moved):
        gone = moved[["ticker", "date"]].assign(_g=1)
        out = out.merge(gone, on=["ticker", "date"], how="left")            # the kept ticker's placeholder row on a moved date
        out = out[out["_g"].isna()].drop(columns="_g")
        orig = pd.concat([m_.assign(ticker=r.dropped) for m_, r in zip(mv, tw.itertuples()) if len(m_)])[["ticker", "date"]].assign(_o=1)
        out = out.merge(orig, on=["ticker", "date"], how="left")
        out = out[out["_o"].isna()].drop(columns="_o")
        out = pd.concat([out, moved], ignore_index=True).sort_values(["ticker", "date"], ignore_index=True)
    return out, tw


@dataclass
class Ctx3:
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
    id_tail: np.ndarray
    id_win: np.ndarray
    split_excl_from: np.ndarray
    split_excl_rows: list = field(default_factory=list)
    twins: pd.DataFrame = None
    twin_stats: dict = field(default_factory=dict)
    cube_stats: dict = field(default_factory=dict)


def build_ctx3(d: pd.DataFrame, master: pd.DataFrame, snaps: pd.DataFrame, sm: pd.DataFrame, sa: pd.DataFrame, last: pd.Timestamp | None = None, current_master_obs: bool = True) -> Ctx3:
    """Everything derives from the inputs given (bars, listings, split tables); truncating `d` and `snaps` reproduces what was knowable then (except announced split dates)."""
    last = pd.Timestamp(d["date"].max()) if last is None else last
    raw_bars = len(d)
    d, tw = resolve_twins(d)
    sess = MarketCalendar("US_EQUITY").sessions("2016-01-04", str(last.date()))
    cube, cube_stats = build_cube(d, sess)
    t0 = int(sess.searchsorted(pd.Timestamp(SPEC["scope"]["window_start"])))
    U = set(master["ticker"])
    sm = sm[sm["ticker"].isin(U)]; sa = sa[sa["ticker"].isin(U)]
    claims = build_claims(sm, sa, (SPEC["scope"]["window_start"], str(last.date())))
    cl, ev = resolve_claims(claims, cube, agreed_tol_floor=SPEC["split_resolution"]["agreed_tolerance_floor"])
    cs: dict = {}
    for r in cl[cl["spell"] >= 0].itertuples():
        cs.setdefault(int(r.spell), []).append(r.s0)
    cs = {k: np.array(v) for k, v in cs.items()}
    obs = observations(snaps, master if current_master_obs else master.assign(active=False), last)      # truncated rebuilds must not see today's keys
    bnd, _ = boundaries(obs, sess)
    id_tail, id_win = identity_mask(cube, bnd, part="tail"), identity_mask(cube, bnd, part="window")
    sef = np.full(cube.S, BIG, dtype=np.int64)
    rows = []
    for r in ev[ev["action"] == "EXCLUDE_SPELL"].itertuples():
        if r.spell >= 0:
            sef[r.spell] = min(sef[r.spell], r.exclude_from_session)
            rows.append({"spell": r.spell, "ticker": r.ticker, "from_session": r.exclude_from_session, "cause": "DISPUTED_SPLIT_AMBIGUOUS" if r.disputed else "AGREED_SPLIT_TESTABLE_AMBIGUOUS", "why": r.why})
    return Ctx3(d, master, sess, cube, t0, last, claims, cl, ev, cs, obs, snaps, bnd, id_tail, id_win, sef, rows, tw,
                {"bars_in": raw_bars, "bars_after_twin_resolution": len(d), "twin_pairs": int(len(tw)), "twin_cells_dropped": int(tw["cells_dropped"].sum()) if len(tw) else 0}, cube_stats)


def load_ctx3() -> Ctx3:
    d = pd.read_parquet(RAW / "alpaca_daily_all.parquet")
    master = pd.read_parquet(RAW / "massive_security_master_CS.parquet")
    snaps = pd.concat([pd.read_parquet(f) for f in sorted((RAW / "massive_pit_master").glob("snapshot_*.parquet"))])
    sm = pd.read_parquet(RAW / "massive_splits_since_2016.parquet")
    sa = pd.read_parquet(RAW / "alpaca_splits.parquet")
    sa = pd.DataFrame({"ticker": sa["symbol"], "execution_date": sa["ex_date"], "split_from": sa["old_rate"], "split_to": sa["new_rate"]})
    return build_ctx3(d, master, snaps, sm, sa)


def state3(ctx: Ctx3, top_n=BASE["top_n"], lookback=BASE["lookback"], min_price=BASE["min_price"]) -> dict:
    cube, t0, T = ctx.cube, ctx.t0, ctx.cube.T
    min_real = int(round(lookback * 5 / 6))
    member_raw = pit_membership(cube.close, cube.volume, top_n=top_n, lookback=lookback, min_real=min_real, min_price=min_price, start=t0 - 1)
    member_raw[:t0] = False
    disc = unrecorded_discontinuities(cube, member_raw, ctx.claim_sessions, t0)
    big = disc[(disc["class"] == "UNRECORDED_SPLIT_LIKE") & (disc["ln_R"].abs() >= SPEC["split_resolution"]["unrecorded_adjust_min_abs_ln_r"]) & (disc["dv_ratio"].fillna(99) <= SPEC["split_resolution"]["unrecorded_adjust_max_dv_ratio"])]
    extra_adj = []
    for r in big.itertuples():                              # snap to the nearest common ratio; pre-event prices are multiplied by the snapped overnight ratio
        k = COMMON[np.argmin(np.abs(np.log(COMMON) - abs(r.ln_R)))]
        extra_adj.append((int(r.spell), int(r.session), float(np.exp(np.sign(r.ln_R) * np.log(k))), "unrecorded_large_jump"))
    tt = np.arange(T)[:, None]
    after_excl = member_raw & (tt < ctx.split_excl_from[None, :])
    member = after_excl & ~ctx.id_tail
    return dict(params=dict(top_n=top_n, lookback=lookback, min_real=min_real, min_price=min_price), member_raw=member_raw, disc=disc, extra_adj=extra_adj,
                excl_from=ctx.split_excl_from.copy(), excl_rows=ctx.split_excl_rows, member_after_excl=after_excl, member=member,
                removed_split=member_raw & ~after_excl, removed_id=member_raw & ctx.id_tail, id_applied=ctx.id_tail, retained_window=member & ctx.id_win)
