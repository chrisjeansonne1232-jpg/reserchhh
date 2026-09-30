"""Statistical machinery: Sharpe inference, multiple-testing corrections, bootstraps, power."""
from __future__ import annotations

from math import comb
from itertools import combinations

import numpy as np
from scipy import stats as sps

EULER = 0.5772156649015329


def sharpe(r: np.ndarray, ppy: int = 252) -> float:
    r = np.asarray(r, float)
    sd = r.std(ddof=1)
    return float(r.mean() / sd * np.sqrt(ppy)) if sd > 0 else 0.0


def sortino(r, ppy=252):
    r = np.asarray(r, float)
    dd = np.sqrt(np.mean(np.minimum(r, 0) ** 2))
    return float(r.mean() / dd * np.sqrt(ppy)) if dd > 0 else 0.0


def max_drawdown(r) -> float:
    eq = np.cumprod(1 + np.asarray(r, float))
    peak = np.maximum.accumulate(eq)
    return float(((eq - peak) / peak).min())


def risk_summary(r, ppy=252) -> dict:
    r = np.asarray(r, float)
    n = len(r)
    mdd = max_drawdown(r)
    ann = float(np.prod(1 + r) ** (ppy / max(n, 1)) - 1)
    q = np.quantile(r, 0.05)
    wins, losses = r[r > 0], r[r < 0]
    return {
        "n": n, "ann_return": ann, "ann_vol": float(r.std(ddof=1) * np.sqrt(ppy)) if n > 1 else 0.0,
        "sharpe": sharpe(r, ppy), "sortino": sortino(r, ppy),
        "calmar": float(ann / abs(mdd)) if mdd < 0 else float("inf"), "max_drawdown": mdd,
        "win_rate": float((r > 0).mean()), "avg_win": float(wins.mean()) if len(wins) else 0.0,
        "avg_loss": float(losses.mean()) if len(losses) else 0.0, "expectancy": float(r.mean()),
        "profit_factor": float(wins.sum() / -losses.sum()) if losses.sum() < 0 else float("inf"),
        "skew": float(sps.skew(r)) if n > 2 else 0.0, "kurtosis": float(sps.kurtosis(r, fisher=False)) if n > 3 else 3.0,
        "var95": float(q), "es95": float(r[r <= q].mean()) if (r <= q).any() else float(q),
    }


# --------------------------------------------------------------------- Sharpe inference
def psr(sr: float, sr_bench: float, n: int, skew: float, kurt: float) -> float:
    """Probabilistic Sharpe Ratio; sr and sr_bench are per-period (NOT annualised)."""
    den = 1 - skew * sr + (kurt - 1) / 4 * sr ** 2
    if n < 3 or den <= 0:
        return 0.0
    return float(sps.norm.cdf((sr - sr_bench) * np.sqrt(n - 1) / np.sqrt(den)))


def expected_max_sr(n_trials: float, var_sr: float) -> float:
    """Expected maximum per-period Sharpe among n_trials null trials (Bailey & Lopez de Prado)."""
    n = max(float(n_trials), 1.0)
    if n <= 1:
        return 0.0
    return float(np.sqrt(var_sr) * ((1 - EULER) * sps.norm.ppf(1 - 1 / n) + EULER * sps.norm.ppf(1 - 1 / (n * np.e))))


def deflated_sharpe(r: np.ndarray, n_trials: float, var_sr_trials: float | None = None) -> dict:
    """Deflated Sharpe Ratio: probability true SR > 0 after selecting the best of n_trials."""
    r = np.asarray(r, float)
    n = len(r)
    sd = r.std(ddof=1)
    if sd == 0 or n < 10:
        return {"dsr": 0.0, "sr0": 0.0, "sr": 0.0}
    sr = r.mean() / sd
    v = var_sr_trials if var_sr_trials is not None else 1.0 / n
    sr0 = expected_max_sr(n_trials, v)
    d = psr(sr, sr0, n, float(sps.skew(r)), float(sps.kurtosis(r, fisher=False)))
    return {"dsr": d, "sr0_per_period": sr0, "sr_per_period": float(sr), "n_trials": float(n_trials)}


def sharpe_ci(r, ppy=252, B=2000, block=10, seed=0, level=0.95) -> tuple[float, float]:
    r = np.asarray(r, float)
    idx = stationary_bootstrap_idx(len(r), B, block, np.random.default_rng(seed))
    s = r[idx]
    srs = s.mean(1) / np.maximum(s.std(1, ddof=1), 1e-18) * np.sqrt(ppy)
    a = (1 - level) / 2
    return float(np.quantile(srs, a)), float(np.quantile(srs, 1 - a))


# ------------------------------------------------------------------------ bootstrap
def stationary_bootstrap_idx(T: int, B: int, mean_block: float, rng: np.random.Generator) -> np.ndarray:
    p = 1.0 / max(mean_block, 1.0)
    idx = np.empty((B, T), dtype=np.int64)
    idx[:, 0] = rng.integers(0, T, B)
    new = rng.random((B, T)) < p
    starts = rng.integers(0, T, (B, T))
    for t in range(1, T):
        idx[:, t] = np.where(new[:, t], starts[:, t], (idx[:, t - 1] + 1) % T)
    return idx


def white_reality_check(D: np.ndarray, B: int = 1000, block: float = 10, seed: int = 0) -> float:
    """White (2000). D: (T,K) performance differentials vs benchmark. H0: max_k E[D_k] <= 0."""
    T, K = D.shape
    rng = np.random.default_rng(seed)
    mu = D.mean(0)
    v = np.sqrt(T) * mu.max()
    idx = stationary_bootstrap_idx(T, B, block, rng)
    vb = np.empty(B)
    for b in range(B):
        vb[b] = (np.sqrt(T) * (D[idx[b]].mean(0) - mu)).max()
    return float((vb >= v).mean())


def hansen_spa(D: np.ndarray, B: int = 1000, block: float = 10, seed: int = 0) -> float:
    """Hansen (2005) SPA test with studentisation and recentring of poor models."""
    T, K = D.shape
    rng = np.random.default_rng(seed)
    mu = D.mean(0)
    idx = stationary_bootstrap_idx(T, B, block, rng)
    boots = np.stack([D[idx[b]].mean(0) for b in range(B)])
    om = np.maximum((np.sqrt(T) * (boots - mu)).std(0, ddof=1), 1e-12)
    tstat = np.sqrt(T) * mu / om
    v = max(tstat.max(), 0.0)
    g = mu * (tstat <= -np.sqrt(2 * np.log(np.log(max(T, 3)))))
    vb = (np.sqrt(T) * (boots - mu + g) / om).max(1)
    vb = np.maximum(vb, 0)
    return float((vb >= v).mean())


# ----------------------------------------------------------------------- FDR / PBO
def bh_fdr(pvals, q: float = 0.05) -> np.ndarray:
    p = np.asarray(pvals, float)
    m = len(p)
    order = np.argsort(p)
    thr = q * (np.arange(1, m + 1) / m)
    ok = p[order] <= thr
    keep = np.zeros(m, bool)
    if ok.any():
        keep[order[: np.flatnonzero(ok).max() + 1]] = True
    return keep


def bh_adjusted(pvals) -> np.ndarray:
    p = np.asarray(pvals, float)
    m = len(p)
    order = np.argsort(p)
    adj = np.empty(m)
    prev = 1.0
    for rank in range(m - 1, -1, -1):
        i = order[rank]
        prev = min(prev, p[i] * m / (rank + 1))
        adj[i] = prev
    return adj


def pbo_cscv(M: np.ndarray, S: int = 16, max_combos: int = 3000, seed: int = 0) -> dict:
    """Probability of Backtest Overfitting (Bailey et al.). M: (T,K) per-period returns of K variants."""
    T, K = M.shape
    if K < 2:
        return {"pbo": float("nan"), "n_combos": 0}
    S = min(S, (T // 2) * 2, 16)
    S -= S % 2
    slices = np.array_split(np.arange(T), S)
    combos = list(combinations(range(S), S // 2))
    if len(combos) > max_combos:
        rng = np.random.default_rng(seed)
        combos = [combos[i] for i in rng.choice(len(combos), max_combos, replace=False)]

    def sr(mat):
        sd = mat.std(0, ddof=1)
        return np.where(sd > 0, mat.mean(0) / np.where(sd > 0, sd, 1), 0.0)

    logits = []
    for c in combos:
        is_idx = np.concatenate([slices[i] for i in c])
        oos_idx = np.concatenate([slices[i] for i in range(S) if i not in c])
        best = int(np.argmax(sr(M[is_idx])))
        oos = sr(M[oos_idx])
        rank = (oos < oos[best]).sum() + 0.5 * ((oos == oos[best]).sum() - 1)
        w = (rank + 0.5) / K
        w = min(max(w, 1e-6), 1 - 1e-6)
        logits.append(np.log(w / (1 - w)))
    logits = np.array(logits)
    return {"pbo": float((logits <= 0).mean()), "n_combos": len(combos)}


def effective_trials(M: np.ndarray, corr_thresh: float = 0.7) -> int:
    """Greedy correlation clustering: number of clusters ~ independent hypotheses among K variants."""
    K = M.shape[1]
    if K == 1:
        return 1
    C = np.corrcoef(M, rowvar=False)
    C = np.nan_to_num(C, nan=0.0)
    left = list(range(K))
    n = 0
    while left:
        i = left.pop(0)
        left = [j for j in left if abs(C[i, j]) < corr_thresh]
        n += 1
    return n


# ---------------------------------------------------------------------- permutation
def circular_shift_null(W: np.ndarray, R: np.ndarray, n_perm: int = 1000, min_shift: int = 20, seed: int = 0) -> np.ndarray:
    """Null distribution of mean GROSS return when the signal timing is decoupled from returns.

    Circularly shifting the whole weight matrix preserves the signal's own autocorrelation, turnover
    and cross-sectional structure while breaking any alignment with future returns.
    """
    T = W.shape[0]
    rng = np.random.default_rng(seed)
    shifts = rng.integers(min_shift, max(T - min_shift, min_shift + 1), n_perm)
    out = np.empty(n_perm)
    for i, k in enumerate(shifts):
        out[i] = (np.roll(W, k, axis=0) * R).sum(1).mean()
    return out


def perm_pvalue(observed: float, null: np.ndarray) -> float:
    return float((1 + (null >= observed).sum()) / (1 + len(null)))


def sign_flip_pvalue(r: np.ndarray, n: int = 5000, seed: int = 0) -> float:
    """One-sided test that mean(r) > 0 under symmetric-around-zero null."""
    r = np.asarray(r, float)
    rng = np.random.default_rng(seed)
    obs = r.mean()
    signs = rng.choice([-1.0, 1.0], size=(n, len(r)))
    null = (signs * r).mean(1)
    return float((1 + (null >= obs).sum()) / (1 + n))


# ------------------------------------------------------------------------- power
def min_detectable_sharpe(n_periods: int, ppy: int = 252, alpha: float = 0.05, power: float = 0.8) -> float:
    """Smallest annualised Sharpe detectable (one-sided) with the given number of periods."""
    z = sps.norm.ppf(1 - alpha) + sps.norm.ppf(power)
    return float(z / np.sqrt(n_periods) * np.sqrt(ppy))


def power_at_sharpe(n_periods: int, ann_sharpe: float, ppy: int = 252, alpha: float = 0.05) -> float:
    z = sps.norm.ppf(1 - alpha)
    return float(sps.norm.cdf(ann_sharpe / np.sqrt(ppy) * np.sqrt(n_periods) - z))


# ------------------------------------------------------------------ trade structure
def concentration(pnl: np.ndarray) -> dict:
    p = np.asarray(pnl, float)
    if len(p) == 0:
        return {"n_trades": 0}
    tot = p.sum()
    srt = np.sort(p)[::-1]
    def share(k):
        k = max(int(k), 1)
        return float(srt[:k].sum() / tot) if tot > 0 else float("nan")
    n = len(p)
    def trimmed(frac_top=0.0, frac_bot=0.0):
        k_t, k_b = int(np.ceil(frac_top * n)), int(np.ceil(frac_bot * n))
        s = np.sort(p)
        s = s[k_b: n - k_t if k_t else n]
        return float(s.sum())
    return {
        "n_trades": n, "top1_share": share(1), "top5_share": share(5), "top10_share": share(10),
        "top1pct_share": share(np.ceil(0.01 * n)), "top5pct_share": share(np.ceil(0.05 * n)),
        "net_without_best": float(np.sort(p)[:-1].sum()), "net_without_worst": float(np.sort(p)[1:].sum()),
        "net_without_top1pct": trimmed(frac_top=0.01), "net_without_bottom1pct": trimmed(frac_bot=0.01),
        "net_without_top5pct": trimmed(frac_top=0.05), "net_without_bottom5pct": trimmed(frac_bot=0.05),
    }


def factor_regression(r: np.ndarray, factors: np.ndarray, names: list[str], ppy: int = 252) -> dict:
    """OLS with Newey-West errors. Returns annualised alpha, t-stat and betas."""
    import statsmodels.api as sm
    X = sm.add_constant(factors)
    m = sm.OLS(r, X).fit(cov_type="HAC", cov_kwds={"maxlags": 5})
    return {"alpha_ann": float(m.params[0] * ppy), "alpha_t": float(m.tvalues[0]), "r2": float(m.rsquared),
            "betas": {n: float(b) for n, b in zip(names, m.params[1:])},
            "beta_t": {n: float(b) for n, b in zip(names, m.tvalues[1:])}}
