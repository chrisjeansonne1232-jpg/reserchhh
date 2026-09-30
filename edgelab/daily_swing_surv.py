"""Residual-survivorship quantification for DAILY_SWING_V1 (a KNOWN LIMITATION: measured and bounded, never silently ignored).

Three components, each with an explicit lower bound, point estimate and upper bound where an estimate is possible:
  A. listed-but-no-bars: names that Massive's POINT-IN-TIME listing shows as listed on a date but that have no real bar near that date under their
     ticker or under the current ticker of the same FIGI (so renames are not miscounted). Their liquidity is unobserved: the expected number that
     would have been PIT members is estimated from the members/with-bars ratio of names WITH bars on the same date and exchange (assumes missing
     at random -- an upper-leaning guess, because illiquid names are the ones most likely to lack bars); the upper bound counts every missing name.
  B. terminal returns of delisted members: member spells that end before the data ends, per year, with the observed final-20-session return; the
     return from the last bar to the end of the security is NOT observed (acquisition cash, bankruptcy, ...). Sensitivity, not an estimate.
  C. exclusion-induced composition change: what the split/discontinuity exclusions removed (declared in the audit; measured, never assumed harmless).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MAJOR = {"XNYS", "XNAS", "XASE", "ARCX", "BATS"}


def pit_listing_coverage(snaps: pd.DataFrame, master: pd.DataFrame, cube, member_raw: np.ndarray, near: int = 20) -> tuple[pd.DataFrame, pd.DataFrame]:
    """snaps: [snapshot_date, ticker, composite_figi, share_class_figi, primary_exchange, name]. Returns (per-name table, per-date summary)."""
    real = cube.real()
    cs = np.vstack([np.zeros((1, real.shape[1]), dtype=np.int32), np.cumsum(real, axis=0, dtype=np.int32)])
    cols_by_ticker: dict[str, list[int]] = {}
    for c, t in enumerate(cube.spell_ticker):
        cols_by_ticker.setdefault(str(t), []).append(c)
    fig_to_ticker = {}
    for r in master.itertuples():
        for f in (r.composite_figi, r.share_class_figi):
            if isinstance(f, str) and f:
                fig_to_ticker.setdefault(f, r.ticker)
    rows = []
    for D, g in snaps.groupby("snapshot_date"):
        s = int(cube.sessions.searchsorted(pd.Timestamp(D)))
        a, b = max(0, s - near), min(cube.T - 1, s + near)
        for r in g.itertuples():
            cands = {r.ticker}
            for f in (r.composite_figi, r.share_class_figi):
                if isinstance(f, str) and f in fig_to_ticker:
                    cands.add(fig_to_ticker[f])
            cols = [c for t in cands for c in cols_by_ticker.get(t, [])]
            has = bool(cols) and bool((cs[b + 1, cols] - cs[a, cols]).sum() > 0)
            mem = bool(cols) and bool(member_raw[s, cols].any())
            via = "ticker" if any(c in cols_by_ticker.get(r.ticker, []) and (cs[b + 1, c] - cs[a, c]) > 0 for c in cols) else ("figi_current_ticker" if has else "")
            rows.append((pd.Timestamp(D), r.ticker, r.composite_figi, r.primary_exchange, r.name, has, mem, via))
    df = pd.DataFrame(rows, columns=["snapshot_date", "ticker", "composite_figi", "primary_exchange", "name", "has_bars", "was_member", "matched_via"])
    out = []
    for D, g in df.groupby("snapshot_date"):
        wb, miss = g[g["has_bars"]], g[~g["has_bars"]]
        p = (wb.groupby("primary_exchange")["was_member"].mean()).to_dict()
        exp = float(sum(p.get(x, 0.0) for x in miss["primary_exchange"]))
        out.append({"snapshot_date": D, "listed": len(g), "with_bars": len(wb), "missing": len(miss), "missing_share": len(miss) / max(1, len(g)),
                    "members_among_with_bars": int(wb["was_member"].sum()), "p_member_given_bars": float(wb["was_member"].mean()) if len(wb) else float("nan"),
                    "expected_missing_members": exp, "upper_bound_missing_members": int(miss["primary_exchange"].isin(MAJOR).sum()), "matched_via_figi": int((g["matched_via"] == "figi_current_ticker").sum())})
    return df, pd.DataFrame(out)


def terminal_exposure(cube, member_final: np.ndarray, t0: int, master: pd.DataFrame, end_slack: int = 5) -> tuple[pd.DataFrame, dict]:
    """Member spells whose last real bar is before the end of the data: the security stopped trading while (or after) being a member."""
    ever = member_final[t0:].any(0)
    inactive = set(master.loc[~master["active"].astype(bool), "ticker"])
    rows = []
    for c in np.flatnonzero(ever):
        last = int(cube.last[c])
        if last >= cube.T - 1 - end_slack:
            continue
        ix = np.flatnonzero(np.isfinite(cube.close[:last + 1, c]))
        r20 = float(np.log(cube.close[ix[-1], c] / cube.close[ix[-21], c])) if len(ix) > 21 else float("nan")   # close-to-close inside the spell: no split adjustment here
        was_member_last = bool(member_final[max(t0, last - 1):last + 1, c].any())
        rows.append({"spell": int(c), "ticker": str(cube.spell_ticker[c]), "last_bar": cube.sessions[last], "year": int(cube.sessions[last].year), "master_inactive": str(cube.spell_ticker[c]) in inactive,
                     "member_at_last_bar": was_member_last, "final_20_session_log_return_raw": r20})
    df = pd.DataFrame(rows)
    return df, {"member_spells_ended": int(len(df)), "of_which_master_inactive": int(df["master_inactive"].sum()) if len(df) else 0}


def glued_spells(snaps: pd.DataFrame, cube, member_raw: np.ndarray, near: int = 20) -> pd.DataFrame:
    """Independent identity test. A ticker that carries DIFFERENT composite FIGIs on different PIT snapshot dates was re-used by another issuer. If ONE spell (one
    column of the cube) has real bars near both dates, two issuers were glued into a single series (the 60-session gap rule did not separate them)."""
    real = cube.real()
    cs = np.vstack([np.zeros((1, real.shape[1]), dtype=np.int32), np.cumsum(real, axis=0, dtype=np.int32)])
    cols_by_ticker: dict[str, list[int]] = {}
    for c, t in enumerate(cube.spell_ticker):
        cols_by_ticker.setdefault(str(t), []).append(c)
    s = snaps.dropna(subset=["composite_figi"])
    multi = s.groupby("ticker")["composite_figi"].nunique()
    rows = []
    for tk in multi[multi > 1].index:
        g = s[s["ticker"] == tk].sort_values("snapshot_date")
        first_seen = g.groupby("composite_figi")["snapshot_date"].agg(["min", "max"]).sort_values("min")
        figs = list(first_seen.index)
        for i in range(len(figs) - 1):
            d1, d2 = first_seen.iloc[i]["max"], first_seen.iloc[i + 1]["min"]
            s1, s2 = int(cube.sessions.searchsorted(d1)), int(cube.sessions.searchsorted(d2))
            for c in cols_by_ticker.get(tk, []):
                n1 = cs[min(cube.T, s1 + near + 1), c] - cs[max(0, s1 - near), c]
                n2 = cs[min(cube.T, s2 + near + 1), c] - cs[max(0, s2 - near), c]
                if n1 > 0 and n2 > 0:
                    rows.append({"ticker": tk, "figi_before": figs[i], "figi_after": figs[i + 1], "last_snapshot_before": d1, "first_snapshot_after": d2, "spell": int(c),
                                 "member_near_either": bool(member_raw[s1, c] or member_raw[s2, c])})
    return pd.DataFrame(rows, columns=["ticker", "figi_before", "figi_after", "last_snapshot_before", "first_snapshot_after", "spell", "member_near_either"])


ADS_OR_FUND = r"American Depositary|\bADS\b|\bADR\b|\bFund\b|\bFd\b|Closed[- ]End|\bETF\b|\bETN\b"


def instrument_mix(cube, member_raw: np.ndarray, t0: int, master: pd.DataFrame) -> dict:
    """How much of the universe is not a plain US common stock although Massive types it 'CS' (ADS lines, closed-end funds), judged by NAME only."""
    ever = np.flatnonzero(member_raw[t0:].any(0))
    names = master.set_index("ticker")["name"].to_dict()
    nm = pd.Series([names.get(str(cube.spell_ticker[c]), "") for c in ever])
    flag = nm.str.contains(ADS_OR_FUND, regex=True, case=False, na=False).to_numpy()
    cells = member_raw[t0:][:, ever].sum(0)
    return {"ever_member_spells": int(len(ever)), "name_matches_ads_or_fund": int(flag.sum()), "share_of_spells": round(float(flag.mean()), 4) if len(ever) else 0.0,
            "share_of_member_cells": round(float(cells[flag].sum() / max(1, cells.sum())), 4), "examples": nm[flag].head(8).tolist(),
            "method": "case-insensitive name match on " + ADS_OR_FUND + " (heuristic: neither exhaustive nor exact)"}
