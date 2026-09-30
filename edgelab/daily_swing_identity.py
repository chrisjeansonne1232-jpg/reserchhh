"""DAILY_SWING_V2 identity fix: ticker hand-over boundaries from point-in-time listings, the mask, and an independent timeline cross-check.

The membership ranking is NOT touched (it stays strictly point-in-time). The mask only removes cells, after ranking. See daily_swing_v2_spec.py."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .daily_swing_v2_spec import SPEC

LOOK = SPEC["universe"]["lookback_sessions"]


def observations(snaps: pd.DataFrame, master: pd.DataFrame, last_date: pd.Timestamp) -> pd.DataFrame:
    """[ticker, date, cik, figi, name]: every PIT snapshot row plus the current master's key for ACTIVE names at the last data date."""
    a = snaps.rename(columns={"snapshot_date": "date", "composite_figi": "figi"})[["ticker", "date", "cik", "figi", "name"]]
    m = master[master["active"].astype(bool)].rename(columns={"composite_figi": "figi"})[["ticker", "cik", "figi", "name"]].assign(date=pd.Timestamp(last_date))
    o = pd.concat([a, m[["ticker", "date", "cik", "figi", "name"]]], ignore_index=True)
    o["date"] = pd.to_datetime(o["date"]).dt.tz_localize(None).dt.normalize()
    for c in ("cik", "figi"):
        o[c] = o[c].where(o[c].notna() & (o[c].astype(str).str.len() > 0), None)
    return o.drop_duplicates(["ticker", "date"], keep="first").sort_values(["ticker", "date"]).reset_index(drop=True)


def boundaries(obs: pd.DataFrame, sessions: pd.DatetimeIndex) -> tuple[pd.DataFrame, dict]:
    """A boundary for a ticker = the key differs between an observation and the NEXT observation that has a comparable key.
    cik chain: every observation with a cik. figi fallback chain: observations WITHOUT a cik, compared only among themselves."""
    rows, skipped, compared = [], 0, 0
    for tk, g in obs.groupby("ticker", sort=False):
        last_cik = last_fig = None
        for r in g.itertuples():
            if pd.notna(r.cik):
                if last_cik is not None:
                    compared += 1
                    if r.cik != last_cik.cik:
                        rows.append((tk, "cik", last_cik.cik, r.cik, last_cik.date, r.date, last_cik.name, r.name))
                last_cik = r
            elif pd.notna(r.figi):
                if last_fig is not None:
                    compared += 1
                    if r.figi != last_fig.figi:
                        rows.append((tk, "figi_fallback", last_fig.figi, r.figi, last_fig.date, r.date, last_fig.name, r.name))
                last_fig = r
            else:
                skipped += 1
    b = pd.DataFrame(rows, columns=["ticker", "key_type", "key_before", "key_after", "d1", "d2", "name_before", "name_after"])
    b["s1"] = sessions.searchsorted(b["d1"]).astype(int) if len(b) else []
    b["s2"] = sessions.searchsorted(b["d2"]).astype(int) if len(b) else []
    return b, {"observations": int(len(obs)), "comparisons": compared, "boundaries": int(len(b)), "observations_with_no_key_skipped": skipped,
               "boundaries_by_key_type": b["key_type"].value_counts().to_dict() if len(b) else {}, "tickers_with_a_boundary": int(b["ticker"].nunique()) if len(b) else 0}


def identity_mask(cube, bnd: pd.DataFrame, lookback: int = LOOK, part: str = "all") -> np.ndarray:
    """(T,S) bool: True = NOT a cell. For every boundary and every spell of that ticker that (a) has a real bar at or before s1 and one after s1, or (b) has any real bar inside (s1, s2): (s1, s2 + lookback).
    part='window' -> only (s1, s2): the ambiguity window, whose removal depends on the LATER observation at s2 (bounded look-ahead);
    part='tail'   -> only [s2, s2 + lookback): known at s2, i.e. causal. window + tail == all."""
    mask = np.zeros((cube.T, cube.S), dtype=bool)
    cols: dict[str, list[int]] = {}
    for c, t in enumerate(cube.spell_ticker):
        cols.setdefault(str(t), []).append(c)
    for r in bnd.itertuples():
        for c in cols.get(r.ticker, []):
            in_window = r.s2 > r.s1 + 1 and bool(np.isfinite(cube.close[r.s1 + 1: r.s2, c]).any())      # a series that STARTS inside the ambiguity window is not known to be clean
            if cube.first[c] <= r.s1 < cube.last[c] or in_window:
                lo, hi = {"all": (r.s1 + 1, r.s2 + lookback), "window": (r.s1 + 1, r.s2), "tail": (r.s2, r.s2 + lookback)}[part]
                mask[lo: min(cube.T, hi), c] = True
    return mask


def timeline_violations(cube, member: np.ndarray, obs: pd.DataFrame, lookback: int = LOOK) -> tuple[int, pd.DataFrame]:
    """Independent cross-check of the mask. Per ticker, give every session an issuer label from the cik observation timeline: the key when the observations on
    both sides agree, AMBIGUOUS when they differ (the hand-over is somewhere between), the first/last key outside the observed range. Then count member cells whose
    window [t-lookback, t] (only sessions on which the spell has a real bar) carries more than one label or an AMBIGUOUS one. Uses cik only (fallback tickers are
    checked on figi)."""
    real = cube.real()
    rows, total = [], 0
    cols: dict[str, list[int]] = {}
    for c, t in enumerate(cube.spell_ticker):
        cols.setdefault(str(t), []).append(c)
    for tk, g in obs.groupby("ticker", sort=False):
        for key in ("cik", "figi"):
            seq = g[g[key].notna() & (g["cik"].isna() if key == "figi" else True)]
            if len(seq) < 2 or seq[key].nunique() < 2:
                continue
            s = cube.sessions.searchsorted(seq["date"]).astype(int)
            keys = seq[key].tolist()
            lab = np.empty(cube.T, dtype=object)
            for t in range(cube.T):
                i = int(np.searchsorted(s, t, side="right")) - 1
                if i < 0:
                    lab[t] = keys[0]
                elif s[i] == t or i >= len(keys) - 1:          # on an observation date the observation's own key applies; after the last one, the last key
                    lab[t] = keys[i]
                else:
                    lab[t] = keys[i] if keys[i] == keys[i + 1] else "AMBIGUOUS"
            codes, uniq = pd.factorize(pd.Series(lab))
            amb = np.array([u == "AMBIGUOUS" for u in uniq])[codes]
            for c in cols.get(tk, []):
                ts = np.flatnonzero(member[:, c])
                bad = 0
                for t in ts:
                    w = np.flatnonzero(real[max(0, t - lookback): t + 1, c]) + max(0, t - lookback)
                    if len(w) and (len(set(codes[w])) > 1 or amb[w].any()):
                        bad += 1
                if bad:
                    rows.append({"ticker": tk, "spell": c, "key": key, "violating_member_cells": bad})
                    total += bad
    return total, pd.DataFrame(rows, columns=["ticker", "spell", "key", "violating_member_cells"])
