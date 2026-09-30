"""Reference (leak-free) strategies. Source strings double as sandbox-compatible code."""
from __future__ import annotations

import numpy as np

MOMENTUM_SRC = '''
import numpy as np
from collections import deque

class XSMomentum:
    """Cross-sectional trailing-return momentum; long top quantile, short bottom quantile."""
    def __init__(self, window=40, quantile=0.2, rebalance=5, gross=1.0):
        self.window, self.q, self.k, self.gross = int(window), float(quantile), int(rebalance), float(gross)
        self.hist = {}
        self.n = 0
        self.w = {}
    def on_bar(self, ts, bars):
        self.n += 1
        for t, b in bars.items():
            self.hist.setdefault(t, deque(maxlen=self.window + 1)).append(b[3])
        if self.n % self.k != 0:
            return {t: w for t, w in self.w.items() if t in bars}
        sc = {t: h[-1] / h[0] - 1 for t, h in self.hist.items() if t in bars and len(h) == self.window + 1}
        if len(sc) < 10:
            return {}
        ranked = sorted(sc, key=sc.get)
        m = max(1, int(len(ranked) * self.q))
        longs, shorts = ranked[-m:], ranked[:m]
        self.w = {}
        for t in longs: self.w[t] = self.gross / 2 / m
        for t in shorts: self.w[t] = -self.gross / 2 / m
        return dict(self.w)
'''

REVERSAL_SRC = '''
class XSReversal:
    """1-day cross-sectional reversal (high turnover)."""
    def __init__(self, quantile=0.2, gross=1.0):
        self.q, self.gross, self.prev = float(quantile), float(gross), {}
    def on_bar(self, ts, bars):
        sc = {t: b[3] / self.prev[t] - 1 for t, b in bars.items() if t in self.prev}
        self.prev = {t: b[3] for t, b in bars.items()}
        if len(sc) < 10:
            return {}
        r = sorted(sc, key=sc.get)
        m = max(1, int(len(r) * self.q))
        w = {t: self.gross / 2 / m for t in r[:m]}
        w.update({t: -self.gross / 2 / m for t in r[-m:]})
        return w
'''


def exec_source(src: str, cls: str):
    ns: dict = {}
    exec(compile(src, "ref", "exec"), ns)
    return ns[cls]


def momentum_build(panel, params):
    return exec_source(MOMENTUM_SRC, "XSMomentum")(**params)


def reversal_build(panel, params):
    return exec_source(REVERSAL_SRC, "XSReversal")(**params)
