"""Performance statistics. Sharpe/Sortino use DAILY returns (intraday bars are collapsed to the trading date)
with rf = 0; annualisation uses 252 (equities) or 365 (crypto)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .core import BacktestResult

ET = "America/New_York"


def daily_returns(equity: pd.Series, initial: float, crypto: bool = False) -> pd.Series:
    key = equity.index.tz_convert("UTC" if crypto else ET).tz_localize(None).normalize()
    d = equity.groupby(key).last()
    return pd.concat([pd.Series([initial]), d.reset_index(drop=True)]).pct_change().dropna().set_axis(d.index)


def max_drawdown(equity: pd.Series) -> float:
    peak = equity.cummax()
    return float((equity / peak - 1).min())


def summarize(res: BacktestResult, crypto: bool = False) -> dict:
    eq = res.equity.dropna()
    init = res.meta["initial_equity"]
    ppy = 365 if crypto else 252
    if len(eq) < 3:
        return {"n_trades": 0, "note": "too few bars"}
    r = daily_returns(eq, init, crypto)
    years = max((eq.index[-1] - eq.index[0]).total_seconds() / (365.25 * 86400), 1e-9)
    final = float(eq.iloc[-1])
    sd = float(r.std(ddof=1)) if len(r) > 2 else np.nan
    dn = float(np.sqrt(np.mean(np.minimum(r, 0) ** 2))) if len(r) else np.nan
    mdd = max_drawdown(pd.concat([pd.Series([init], index=[eq.index[0] - pd.Timedelta(seconds=1)]), eq]))
    cagr = (final / init) ** (1 / years) - 1 if final > 0 else -1.0
    t = res.trades[res.trades.exit_reason != "open"] if len(res.trades) else res.trades
    wins, losses = (t.pnl[t.pnl > 0], t.pnl[t.pnl <= 0]) if len(t) else (pd.Series(dtype=float),) * 2
    notional = float((res.fills.qty * res.fills.fill_px).sum()) if len(res.fills) else 0.0
    return {
        "start": str(eq.index[0]), "end": str(eq.index[-1]), "years": round(years, 3),
        "final_equity": round(final, 2), "total_return": final / init - 1, "cagr": cagr,
        "vol_annual": sd * np.sqrt(ppy), "sharpe": float(r.mean() / sd * np.sqrt(ppy)) if sd and sd > 0 else 0.0,
        "sortino": float(r.mean() / dn * np.sqrt(ppy)) if dn and dn > 0 else 0.0,
        "max_drawdown": mdd, "calmar": cagr / abs(mdd) if mdd < 0 else float("inf"),
        "n_trades": int(len(t)), "win_rate": float((t.pnl > 0).mean()) if len(t) else 0.0,
        "profit_factor": float(wins.sum() / -losses.sum()) if len(losses) and losses.sum() < 0 else float("inf") if len(wins) else 0.0,
        "avg_trade_pnl": float(t.pnl.mean()) if len(t) else 0.0, "avg_bars_held": float(t.bars_held.mean()) if len(t) else 0.0,
        "exposure": float((res.position.abs() > 1e-9).mean()), "annual_turnover_x": notional / init / years,
        "costs_total": res.costs_paid["total"], "costs_pct_initial": res.costs_paid["total"] / init,
        "max_bar_participation": res.meta["max_participation"],
    }
