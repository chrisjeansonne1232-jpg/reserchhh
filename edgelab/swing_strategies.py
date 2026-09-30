"""Daily-swing strategies for DAILY_SWING_V2 discovery round 1. Bar-by-bar, causal: the decision at bar t uses bars <= t and membership computed from sessions <= t;
orders execute at open t+1 (engine). Dollar-neutral: equal-weight long the top decile of eligible members by score (+0.5 total), short the bottom decile (-0.5 total)."""
from __future__ import annotations

import numpy as np

from .data import Panel

Q, MIN_ELIGIBLE, LONG, SHORT = 0.10, 100, 0.5, -0.5


class SwingStrategy:
    """kind in {'rev','mom','volshock','overnight'}; params per family (see discovery_spec)."""

    def __init__(self, panel: Panel, meta: dict, kind: str, params: dict):
        self.kind, self.p = kind, params
        self.tick = {t: j for j, t in enumerate(panel.tickers)}
        self.N = panel.N
        self.names = panel.tickers
        self.meta = meta
        self.P = meta["pre"]["close"].shape[0] + 1 if False else 71
        self.cl = np.full((self.P, self.N), np.nan); self.op = np.full((self.P, self.N), np.nan); self.dv = np.full((self.P, self.N), np.nan)
        pre = meta["pre"]
        n = min(pre["close"].shape[0], self.P - 1)
        if n:                                                     # history strictly before the panel starts (past bars only)
            self.cl[self.P - 1 - n: self.P - 1] = pre["close"][-n:]; self.op[self.P - 1 - n: self.P - 1] = pre["open"][-n:]; self.dv[self.P - 1 - n: self.P - 1] = pre["dv"][-n:]
        self.pos = self.P - 2                                     # index of the newest stored row
        self.count = 0
        self.last: dict = {}

    def _lag(self, arr, k):
        return arr[(self.pos - k) % self.P]

    def _score(self):
        k, kind = self.p, self.kind
        cl0, op0 = self._lag(self.cl, 0), self._lag(self.op, 0)
        with np.errstate(invalid="ignore", divide="ignore"):
            if kind == "rev":
                return -(cl0 / self._lag(self.cl, k["k"]) - 1)
            if kind == "mom":
                return self._lag(self.cl, 5) / self._lag(self.cl, k["L"]) - 1
            if kind == "volshock":
                hist = np.stack([self._lag(self.dv, j) for j in range(1, 21)])
                med = np.nanmedian(np.where(np.isfinite(hist), hist, np.nan), axis=0) if np.isfinite(hist).sum() else np.full(self.N, np.nan)
                z = np.log(self._lag(self.dv, 0) / med)
                r1 = cl0 / self._lag(self.cl, 1) - 1
                return k["dir"] * np.sign(r1) * z
            if kind == "overnight":
                ov = np.stack([self._lag(self.op, j) / self._lag(self.cl, j + 1) - 1 for j in range(k["k"])])
                return k["dir"] * np.nanmean(ov, axis=0)
        raise ValueError(kind)

    def on_bar(self, ts: int, bars: dict) -> dict:
        row = self.meta["ts_to_row"][ts]
        self.pos = (self.pos + 1) % self.P
        self.cl[self.pos] = np.nan; self.op[self.pos] = np.nan; self.dv[self.pos] = np.nan
        for name, b in bars.items():
            j = self.tick.get(name)
            if j is not None:
                self.op[self.pos, j], self.cl[self.pos, j], self.dv[self.pos, j] = b[0], b[3], b[3] * b[4]
        h = self.p["h"]
        reb = (self.count % h == 0)
        self.count += 1
        if not reb:
            return self.last
        elig = self.meta["member_next"][row]
        with np.errstate(all="ignore"):
            s = self._score()
        ok = elig & np.isfinite(s)
        n = int(ok.sum())
        if n < MIN_ELIGIBLE:
            self.last = {}
            return self.last
        idx = np.flatnonzero(ok)
        m = max(1, int(Q * n))
        order = idx[np.argsort(s[idx], kind="stable")]
        short, long_ = order[:m], order[-m:]
        w = {self.names[j]: SHORT / m for j in short}
        w.update({self.names[j]: LONG / m for j in long_})
        self.last = w
        return w


def make_build(meta: dict, kind: str):
    """build(panel, params) -> strategy, for the evaluator (it slices/scrambles the panel; alignment is by timestamp, so that is safe)."""
    return lambda panel, params: SwingStrategy(panel, meta, kind, params)
