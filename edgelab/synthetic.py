"""Synthetic markets with KNOWN ground truth, used to self-test the research system.

edge_sd = 0 -> pure noise (no strategy can have a true edge). edge_sd > 0 -> persistent latent alpha
mu_i,t (AR(1), half-life ~ 23 days) added to returns, so slow trailing-return signals have a real edge.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .data import Panel


def make_market(T=1000, N=80, seed=0, edge_sd=0.0, phi=0.97, delist_frac=0.15, late_list_frac=0.1,
                start="2018-01-02", intraday_share=0.65, distress_drift=0.0, reversal_phi=0.0) -> Panel:
    rng = np.random.default_rng(seed)
    days = pd.bdate_range(start, periods=T)
    ts = (days + pd.Timedelta(hours=21)).to_numpy().astype("datetime64[ns]")  # 16:00 ET close ~ 21:00 UTC
    m = rng.normal(0.0003, 0.010, T) * np.exp(0.5 * np.sin(np.arange(T) / 90.0))
    beta = rng.normal(1.0, 0.3, N)
    sd_i = rng.uniform(0.012, 0.022, N)
    e = rng.standard_t(5, (T, N)) / np.sqrt(5 / 3) * sd_i
    mu = np.zeros((T, N))
    if edge_sd > 0:
        inn = edge_sd * np.sqrt(1 - phi ** 2)
        mu[0] = rng.normal(0, edge_sd, N)
        for t in range(1, T):
            mu[t] = phi * mu[t - 1] + rng.normal(0, inn, N)
    if reversal_phi:
        for t in range(1, T):
            e[t] -= reversal_phi * e[t - 1]
    r_total = beta * m[:, None] + mu + e
    gap = (1 - intraday_share) * r_total + rng.normal(0, 0.004, (T, N))
    intra = intraday_share * r_total + rng.normal(0, 0.004, (T, N))
    # lifecycle
    alive = np.ones((T, N), bool)
    delist_ret = np.zeros(N)
    n_del = int(delist_frac * N)
    dead = rng.choice(N, n_del, replace=False)
    for i in dead:
        d = int(rng.integers(int(0.2 * T), T - 5))
        alive[d:, i] = False
        kind = rng.random()
        delist_ret[i] = -rng.uniform(0.3, 1.0) if kind < 0.6 else 0.0   # bankruptcy vs cash acquisition
        if kind < 0.6:  # distress drift before delisting
            span = min(60, d)
            intra[d - span:d, i] -= distress_drift
    late = rng.choice([i for i in range(N) if i not in set(dead)], int(late_list_frac * N), replace=False)
    for i in late:
        alive[: int(rng.integers(10, int(0.5 * T))), i] = False
    p0 = rng.uniform(20, 200, N)
    close = np.empty((T, N)); open_ = np.empty((T, N))
    prev = p0.copy()
    for t in range(T):
        open_[t] = prev * (1 + gap[t])
        close[t] = open_[t] * (1 + intra[t])
        prev = close[t]
    hi = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.004, (T, N))))
    lo = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.004, (T, N))))
    scale = np.exp(rng.normal(np.log(2e6), 0.8, N))
    vol = scale * np.exp(rng.normal(0, 0.3, (T, N)))
    spread = np.clip(rng.normal(6, 2, N)[None, :] + rng.normal(0, 0.5, (T, N)), 1.0, None)
    for a in (open_, close, hi, lo, vol, spread):
        a[~alive] = np.nan
    tick = [f"S{i:03d}" for i in range(N)]
    return Panel(ts, tick, open_, hi, lo, close, vol, alive, spread, delist_ret,
                 meta={"synthetic": True, "edge_sd": edge_sd, "seed": seed,
                       "master_tickers": list(tick), "delisted_in_master": [tick[i] for i in dead],
                       "market_returns": None})


def market_return_series(panel: Panel) -> np.ndarray:
    """Equal-weight next-open-to-open market proxy over alive names (benchmark for factor tests)."""
    o = panel.open
    nxt = np.vstack([o[1:], np.full((1, panel.N), np.nan)])
    r = nxt / o - 1
    r = np.where(panel.alive, r, np.nan)
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return np.nan_to_num(np.nanmean(r, axis=1), nan=0.0)


def survivors_only(panel: Panel) -> Panel:
    """The classic survivorship-biased dataset: drop everything not alive at the end."""
    keep = [i for i in range(panel.N) if panel.alive[-1, i]]
    p = Panel(panel.ts, [panel.tickers[i] for i in keep], panel.open[:, keep], panel.high[:, keep], panel.low[:, keep],
              panel.close[:, keep], panel.volume[:, keep], panel.alive[:, keep],
              None if panel.spread_bps is None else panel.spread_bps[:, keep],
              None if panel.delist_ret is None else panel.delist_ret[keep], dict(panel.meta))
    p.meta["master_tickers"] = list(panel.meta.get("master_tickers", panel.tickers))
    p.meta["delisted_in_master"] = list(panel.meta.get("delisted_in_master", []))
    return p
