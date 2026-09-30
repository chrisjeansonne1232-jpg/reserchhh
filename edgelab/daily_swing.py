"""DAILY_SWING_V1 machinery: spell identity, point-in-time liquid universe, empirical split resolution, unrecorded-discontinuity detection.

Parameters come ONLY from edgelab.daily_swing_spec.SPEC (frozen and hashed in the registry). Nothing here fills, interpolates, adjusts or drops a bar
silently: every exclusion is a row in a returned table with its reason and effective session.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .daily_swing_spec import SPEC

UNI, IDN, SR = SPEC["universe"], SPEC["identity"], SPEC["split_resolution"]
LOOK, MINREAL, TOPN, MINPX, FFILL = (UNI["lookback_sessions"], UNI["min_real_bars_in_lookback"], UNI["top_n"], UNI["min_last_close"],
                                     UNI["price_ffill_limit_sessions"])
WIN = SR["test_window_sessions"]


# =============================================================================== cube: sessions x spells
@dataclass
class Cube:
    sessions: pd.DatetimeIndex
    spell_ticker: np.ndarray            # (S,) str
    first: np.ndarray                   # (S,) session index of the first real bar
    last: np.ndarray                    # (S,) session index of the last real bar
    open: np.ndarray                    # (T, S) NaN where there is no REAL bar (volume > 0)
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray

    @property
    def T(self) -> int:
        return len(self.sessions)

    @property
    def S(self) -> int:
        return len(self.spell_ticker)

    def real(self) -> np.ndarray:
        return np.isfinite(self.close)


def assign_spells(ticker: np.ndarray, sess: np.ndarray, gap: int = IDN["spell_gap_sessions"]) -> np.ndarray:
    """Spell id per REAL bar (arrays sorted by ticker, session). A new spell starts when the ticker changes or >= `gap` sessions passed without a real bar."""
    new = np.ones(len(ticker), dtype=bool)
    new[1:] = (ticker[1:] != ticker[:-1]) | ((sess[1:] - sess[:-1]) > gap)
    return np.cumsum(new) - 1


def build_cube(daily: pd.DataFrame, sessions: pd.DatetimeIndex, gap: int = IDN["spell_gap_sessions"]) -> tuple[Cube, dict]:
    """daily: [ticker, date, open, high, low, close, volume] (UNADJUSTED, provider bars incl. zero-volume placeholders).
    Only bars with volume > 0 become cells. Returns the cube and counts of what was set aside (never silently)."""
    d = daily
    st = {"bars_in": int(len(d))}
    d = d[d["volume"] > 0]
    st["real_bars"] = int(len(d))
    st["placeholder_bars_not_cells"] = st["bars_in"] - st["real_bars"]
    idx = sessions.get_indexer(pd.DatetimeIndex(d["date"]))
    off = idx < 0
    st["real_bars_on_non_sessions"] = int(off.sum())
    d, idx = d[~off], idx[~off]
    order = np.lexsort((idx, d["ticker"].to_numpy()))
    d, idx = d.iloc[order], idx[order]
    tk = d["ticker"].to_numpy()
    dup = (tk[1:] == tk[:-1]) & (idx[1:] == idx[:-1])
    st["duplicate_ticker_session_keys"] = int(dup.sum())
    keep = np.ones(len(d), dtype=bool)
    keep[1:] = ~dup                                             # duplicates are counted (R3) and only the first is placed; they are never averaged
    d, idx, tk = d[keep], idx[keep], tk[keep]
    sp = assign_spells(tk, idx, gap)
    S, T = int(sp.max()) + 1 if len(sp) else 0, len(sessions)
    arrs = {k: np.full((T, S), np.nan) for k in ("open", "high", "low", "close", "volume")}
    for k in arrs:
        arrs[k][idx, sp] = d[k].to_numpy(dtype=float)
    first = np.full(S, T, dtype=int); last = np.full(S, -1, dtype=int)
    np.minimum.at(first, sp, idx); np.maximum.at(last, sp, idx)
    spell_ticker = np.empty(S, dtype=object); spell_ticker[sp] = tk
    st["spells"], st["tickers"] = S, int(len(set(tk)))
    st["tickers_with_multiple_spells"] = int(pd.Series(spell_ticker).duplicated(keep=False).sum() and pd.Series(spell_ticker).value_counts().gt(1).sum())
    return Cube(sessions, spell_ticker, first, last, **arrs), st


# =============================================================================== point-in-time universe
def pit_membership(close: np.ndarray, volume: np.ndarray, top_n: int = TOPN, lookback: int = LOOK, min_real: int = MINREAL, min_price: float = MINPX,
                   ffill_limit: int = FFILL, start: int = 0) -> np.ndarray:
    """(T,S) bool. Row t uses ONLY rows < t: rolling median of dollar volume over the previous `lookback` sessions (>= `min_real` real bars),
    last known close >= min_price (forward-filled at most `ffill_limit` sessions), then the top_n by that median. No exclusions are applied here."""
    dv = pd.DataFrame(close * volume)
    med = dv.rolling(lookback, min_periods=min_real).median().shift(1).to_numpy()
    px = pd.DataFrame(close).ffill(limit=ffill_limit).shift(1).to_numpy()
    elig = np.isfinite(med) & (px >= min_price)
    member = np.zeros(close.shape, dtype=bool)
    for t in range(start, close.shape[0]):
        e = np.flatnonzero(elig[t])
        if len(e) <= top_n:
            member[t, e] = True
        else:
            member[t, e[np.argpartition(-med[t, e], top_n - 1)[:top_n]]] = True
    return member


def member_pairs(cube: Cube, member: np.ndarray, t_max: int | None = None) -> np.ndarray:
    """Sorted int64 codes ticker_id * T_full + t for every (ticker, session) membership; comparable across cubes built from different data cuts."""
    tickers, tid = np.unique(cube.spell_ticker.astype(str), return_inverse=True)
    t, s = np.nonzero(member if t_max is None else member[: t_max + 1])
    return tickers, np.sort(tid[s].astype(np.int64) * 10_000 + t)


# =============================================================================== split claims
def build_claims(massive: pd.DataFrame, alpaca: pd.DataFrame, window: tuple[str, str], day_tol: int = 3, ratio_tol: float = 1e-3) -> pd.DataFrame:
    """massive: [ticker, execution_date, split_from, split_to]; alpaca: [ticker, execution_date, split_from, split_to] (from old_rate/new_rate).
    One row per claim: agreed pairs collapse to a single 'both' claim (Massive's numbers); single-source claims are the DISPUTED events."""
    w0, w1 = pd.Timestamp(window[0]), pd.Timestamp(window[1])

    def prep(x, src):
        x = x[["ticker", "execution_date", "split_from", "split_to"]].copy()
        x["date"] = pd.to_datetime(x["execution_date"]).dt.tz_localize(None).dt.normalize()
        x["ratio"] = x["split_to"].astype(float) / x["split_from"].astype(float)
        x["source"] = src
        return x[(x["date"] >= w0) & (x["date"] <= w1)].drop(columns="execution_date").reset_index(drop=True)
    m, a = prep(massive, "massive"), prep(alpaca, "alpaca")
    pool = {}
    for i, r in enumerate(a.itertuples()):
        pool.setdefault(r.ticker, []).append((i, r.date, r.ratio))
    used = set()
    both = []
    for r in m.itertuples():
        hit = next(((i, d, q) for i, d, q in pool.get(r.ticker, []) if i not in used and abs((d - r.date).days) <= day_tol and abs(q / r.ratio - 1) < ratio_tol), None)
        if hit is not None:
            used.add(hit[0]); both.append(r.Index)
    m.loc[both, "source"] = "both"
    a = a[~a.index.isin(used)]
    out = pd.concat([m, a], ignore_index=True)
    out["claim_id"] = np.arange(len(out))
    out["price_multiplier"] = out["split_from"].astype(float) / out["split_to"].astype(float)
    return out[["claim_id", "ticker", "date", "split_from", "split_to", "ratio", "price_multiplier", "source"]]


def _sigma(open_: np.ndarray, close: np.ndarray, col: int, before: int) -> tuple[float, int]:
    """Robust overnight-log-ratio scale from the (up to) 60 real bars before session `before`."""
    ix = np.flatnonzero(np.isfinite(close[:before, col]))[-(LOOK + 1):]
    if len(ix) < 21:
        return 0.03, int(max(0, len(ix) - 1))
    lr = np.log(open_[ix[1:], col] / close[ix[:-1], col])
    lr = lr[np.isfinite(lr)]
    if len(lr) < 20:
        return 0.03, int(len(lr))
    return float(max(1.4826 * np.median(np.abs(lr - np.median(lr))), 0.015)), int(len(lr))


def _prior_dv(cube: Cube, col: int, s: int, n: int = 20) -> float:
    ix = np.flatnonzero(np.isfinite(cube.close[:s, col]))[-n:]
    if len(ix) < 5:
        return float("nan")
    return float(np.median(cube.close[ix, col] * cube.volume[ix, col]))


def _prev_close(close: np.ndarray, col: int, s: int, max_back: int = 10) -> float:
    lo = max(0, s - max_back)
    ix = np.flatnonzero(np.isfinite(close[lo:s, col]))
    return float(close[lo + ix[-1], col]) if len(ix) else float("nan")


def classify_claim(cube: Cube, col_candidates: list[int], s0: int, multiplier: float) -> dict:
    """Empirical test of ONE claim: does the raw overnight change match the claimed price multiplier? See SPEC['split_resolution'] for the rules."""
    lo, hi = max(1, s0 - WIN), min(cube.T - 1, s0 + WIN)
    best = None
    for c in col_candidates:
        n = int(np.isfinite(cube.close[lo:hi + 1, c]).sum())
        if n and (best is None or n > best[1]):
            best = (c, n)
    if best is None:
        return {"verdict": "NO_PRICE_DATA", "reason": "no real bar within the test window", "spell": -1}
    c = best[0]
    lnm = float(np.log(multiplier))
    sig, nobs = _sigma(cube.open, cube.close, c, lo)
    tol = max(4 * sig, 0.05)
    rows = []
    for s in range(lo, hi + 1):
        if not np.isfinite(cube.open[s, c]):
            continue
        pc = _prev_close(cube.close, c, s)
        if np.isfinite(pc) and pc > 0:
            rows.append((s, float(np.log(cube.open[s, c] / pc))))
    base = {"spell": c, "sigma": round(sig, 4), "tol": round(tol, 4), "sigma_obs": nobs, "ln_multiplier": round(lnm, 4), "sessions_tested": len(rows)}
    if not rows:
        return {**base, "verdict": "NO_PRICE_DATA", "reason": "no comparable overnight ratio in the window"}
    lnR = np.array([r[1] for r in rows]); ss = np.array([r[0] for r in rows])
    err_split, err_none = np.abs(lnR - lnm), np.abs(lnR)
    j = int(np.argmin(err_split))
    base.update(best_session=int(ss[j]), best_offset=int(ss[j] - s0), ln_R_best=round(float(lnR[j]), 4), err_split_best=round(float(err_split[j]), 4),
                max_abs_ln_R=round(float(err_none.max()), 4))
    if abs(lnm) < SR["untestable_if_abs_log_ratio_below"]:
        return {**base, "verdict": "AMBIGUOUS", "reason": f"untestable ratio (|ln m|={abs(lnm):.3f} < {SR['untestable_if_abs_log_ratio_below']})"}
    if 2 * tol >= abs(lnm):
        return {**base, "verdict": "AMBIGUOUS", "reason": f"tolerance {tol:.3f} too wide: claim and 'no split' overlap"}
    if err_split[j] <= tol:
        dv, med = float(cube.close[ss[j], c] * cube.volume[ss[j], c]), _prior_dv(cube, c, int(ss[j]))
        ratio = dv / med if np.isfinite(med) and med > 0 else float("nan")
        base["dv_ratio"] = round(ratio, 2) if np.isfinite(ratio) else None
        if np.isfinite(ratio) and ratio > 5:
            return {**base, "verdict": "AMBIGUOUS", "reason": f"price matches but dollar volume is {ratio:.1f}x the prior median (crash-like)"}
        return {**base, "verdict": "CONFIRMED", "reason": f"raw overnight ratio {np.exp(lnR[j]):.4f} matches claimed {multiplier:.4f} (offset {int(ss[j] - s0)} sessions)"}
    if (err_none <= tol).all():
        return {**base, "verdict": "REFUTED", "reason": "no price jump at all in the window (claim false, or bars already adjusted)"}
    return {**base, "verdict": "AMBIGUOUS", "reason": f"a jump exists (max |ln R|={err_none.max():.3f}) that does not match the claim"}


def resolve_claims(claims: pd.DataFrame, cube: Cube) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Per-claim verdicts, then per-EVENT resolution. Returns (claims_with_verdicts, events)."""
    by_ticker: dict[str, list[int]] = {}
    for c, t in enumerate(cube.spell_ticker):
        by_ticker.setdefault(str(t), []).append(c)
    res = []
    for r in claims.itertuples():
        s0 = int(cube.sessions.searchsorted(r.date))
        s0 = min(s0, cube.T - 1)
        v = classify_claim(cube, by_ticker.get(r.ticker, []), s0, r.price_multiplier)
        res.append({"claim_id": r.claim_id, "s0": s0, **v})
    cl = claims.merge(pd.DataFrame(res), on="claim_id")
    # events: same ticker + spell, claimed sessions within WIN of each other
    cl = cl.sort_values(["ticker", "spell", "s0"]).reset_index(drop=True)
    new = np.ones(len(cl), dtype=bool)
    if len(cl):
        new[1:] = ((cl["ticker"].to_numpy()[1:] != cl["ticker"].to_numpy()[:-1]) | (cl["spell"].to_numpy()[1:] != cl["spell"].to_numpy()[:-1])
                   | (np.diff(cl["s0"].to_numpy()) > WIN))
    cl["event_id"] = np.cumsum(new) - 1
    ev = []
    for eid, g in cl.groupby("event_id"):
        vs = set(g["verdict"])
        disputed = bool((g["source"] != "both").any())
        conf = g[g["verdict"] == "CONFIRMED"]
        if len(conf):
            m = conf["price_multiplier"].to_numpy()
            verdict = "CONFIRMED" if (m.max() / m.min() - 1) <= 0.01 else "AMBIGUOUS"
            reason = "confirmed by the raw overnight change" if verdict == "CONFIRMED" else "confirmed claims disagree on the ratio by > 1%"
        elif vs == {"REFUTED"}:
            verdict, reason = "REFUTED", "every claim refuted: no price jump"
        elif vs == {"NO_PRICE_DATA"}:
            verdict, reason = "NO_PRICE_DATA", "no bars to test"
        else:
            verdict, reason = "AMBIGUOUS", "; ".join(sorted(set(g.loc[g["verdict"] == "AMBIGUOUS", "reason"]))) or "mixed verdicts"
        untestable_only = bool(verdict == "AMBIGUOUS" and (g["reason"].str.startswith("untestable")).all())
        if verdict == "AMBIGUOUS" and not disputed and untestable_only:
            action, why = "ACCEPT_CORROBORATED_UNVERIFIED", "both providers agree; ratio too small to verify from prices"
        elif verdict == "AMBIGUOUS":
            action, why = "EXCLUDE_SPELL", reason
        elif verdict == "CONFIRMED":
            action, why = "ADJUST", reason
        else:
            action, why = "NONE", reason
        first = g.iloc[0]
        cm = conf.iloc[0] if len(conf) else None
        ev.append({"event_id": int(eid), "ticker": first["ticker"], "spell": int(first["spell"]), "claimed_session": int(g["s0"].min()), "claimed_date": g["date"].min(),
                   "n_claims": len(g), "sources": "+".join(sorted(set(g["source"]))), "disputed": disputed, "verdict": verdict, "action": action, "why": why,
                   "adjust_session": int(cm["best_session"]) if cm is not None else -1, "adjust_multiplier": float(cm["price_multiplier"]) if cm is not None else np.nan,
                   "exclude_from_session": int(g["s0"].min() - WIN) if action == "EXCLUDE_SPELL" else -1})
    return cl, pd.DataFrame(ev)


# =============================================================================== unrecorded discontinuities among member cells
def unrecorded_discontinuities(cube: Cube, member: np.ndarray, claim_sessions: dict[int, np.ndarray], t0: int) -> pd.DataFrame:
    """Member cells whose overnight ratio looks like a split (common ratio within tol, |ln R| >= 0.30), with no claim within WIN sessions and no dollar-volume
    spike (> 5x prior median, which marks a genuine move). Genuine-looking large moves are returned too, labelled, so nothing is hidden."""
    cl = pd.DataFrame(cube.close).ffill(limit=10).shift(1).to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        lnR = np.log(cube.open / cl)
    cand = member & np.isfinite(lnR) & (np.abs(lnR) >= 0.30)
    cand[:t0] = False
    ln_common = np.log(np.array(SR["common_ratios"], dtype=float))
    targets = np.concatenate([ln_common, -ln_common])
    rows = []
    for t, c in zip(*np.nonzero(cand)):
        x = float(lnR[t, c])
        sig, _ = _sigma(cube.open, cube.close, int(c), int(t))
        tol = max(4 * sig, 0.05)
        near = float(np.min(np.abs(targets - x)))
        cs = claim_sessions.get(int(c))
        claimed = cs is not None and bool((np.abs(cs - t) <= WIN).any())
        dv = float(cube.close[t, c] * cube.volume[t, c]); med = _prior_dv(cube, int(c), int(t))
        ratio = dv / med if np.isfinite(med) and med > 0 else float("nan")
        looks_split = near <= tol
        spike = bool(np.isfinite(ratio) and ratio > 5)
        if claimed:
            cls = "COVERED_BY_CLAIM"
        elif looks_split and not spike:
            cls = "UNRECORDED_SPLIT_LIKE"
        elif looks_split and spike:
            cls = "SPLIT_LIKE_BUT_GENUINE_MOVE_DV_SPIKE"
        else:
            cls = "LARGE_MOVE_NOT_SPLIT_LIKE"
        rows.append({"spell": int(c), "ticker": str(cube.spell_ticker[c]), "session": int(t), "date": cube.sessions[t], "ln_R": round(x, 4), "sigma": round(sig, 4),
                     "dv_ratio": round(ratio, 2) if np.isfinite(ratio) else None, "class": cls})
    return pd.DataFrame(rows)


# =============================================================================== the gate (separate from DiscoveryGate, which is untouched)
@dataclass
class ReqResult:
    rid: str
    text: str
    comparison: str
    measured: object
    passed: bool
    detail: str = ""


def _passes(op: str, measured, threshold) -> bool:
    if measured is None or (isinstance(measured, float) and not np.isfinite(measured)):
        return False
    return {"==": measured == threshold, "<=": measured <= threshold, ">=": measured >= threshold}[op]


def evaluate_requirements(measured: dict[str, object], details: dict[str, str] | None = None) -> list[ReqResult]:
    """Pass/fail comes ONLY from the frozen SPEC (operator + threshold). A requirement with no measurement fails."""
    out = []
    for r in SPEC["requirements"]:
        m = measured.get(r["id"])
        ok = _passes(r["op"], m, r["threshold"])
        out.append(ReqResult(r["id"], r["text"], f"{r['metric']} {r['op']} {r['threshold']}", m, ok, (details or {}).get(r["id"], "")))
    return out


class DailySwingGate:
    """OPEN only if every frozen requirement passes AND no MATERIAL gap is left without a DAILY_SWING_V1 disposition (RESOLVED, EXCLUDED, or an
    authorised accepted-limitation kind, which must still be present, quantified and OPEN in the record)."""

    @staticmethod
    def undispositioned(ledger, accepted_kinds) -> list:
        from .daily_swing_spec import GATE_NAME
        return [g for g in ledger.unresolved_material(GATE_NAME) if g.kind not in accepted_kinds]

    @staticmethod
    def check(results: list[ReqResult], ledger, accepted_kinds) -> tuple[bool, list[str]]:
        why = [f"requirement {r.rid} FAILED: {r.text} (measured {r.measured}; needs {r.comparison})" for r in results if not r.passed]
        for g in DailySwingGate.undispositioned(ledger, accepted_kinds):
            why.append(f"MATERIAL gap {g.gap_id} [{g.kind}] has no DAILY_SWING_V1 disposition: {g.detail[:110]}")
        for k in accepted_kinds:
            if not any(g.kind == k for g in ledger.gaps.values()):
                why.append(f"accepted limitation {k} is not recorded in the ledger")
        return (not why), why
