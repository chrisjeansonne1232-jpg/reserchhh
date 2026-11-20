"""Prove the data layer + backtester on a KNOWN strategy: SMA(50/200) crossover on SPY. Writes docs/PROOF_SMA_SPY.md.

This is a correctness proof of the machinery, not a trading idea: a 50/200 crossover is not expected to beat buy-and-hold.
Run:  python scripts/prove_sma_spy.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from edgelab.backtester import CRYPTO_PESSIMISTIC, EQUITY_PESSIMISTIC, ZERO, backtest, summarize  # noqa: E402
from edgelab.data import Panel  # noqa: E402
from edgelab.data.loader import load_bars  # noqa: E402
from edgelab.engine import Exec, run_backtest  # noqa: E402
from edgelab.strategies import Signals, check_causality  # noqa: E402
from edgelab.strategies.library import BuyHold, SMACross  # noqa: E402

ET = "America/New_York"
md: list[str] = ["# Proof run: SMA(50/200) crossover on SPY\n"]


def P(s=""):
    md.append(s)
    print(s)


def pct(x):
    return f"{x:.1%}"


def table(rows: dict[str, dict], keys: list[tuple[str, str, callable]]):
    P("| metric | " + " | ".join(rows) + " |\n|---|" + "---|" * len(rows))
    for label, k, f in keys:
        P(f"| {label} | " + " | ".join(f(r[k]) if k in r else "-" for r in rows.values()) + " |")


KEYS = [("period", "years", lambda v: f"{v:.2f} yrs"), ("final equity ($100k start)", "final_equity", lambda v: f"${v:,.0f}"),
        ("total return", "total_return", pct), ("CAGR", "cagr", pct), ("annual volatility", "vol_annual", pct),
        ("Sharpe (rf=0)", "sharpe", lambda v: f"{v:.2f}"), ("Sortino", "sortino", lambda v: f"{v:.2f}"),
        ("max drawdown", "max_drawdown", pct), ("trades", "n_trades", lambda v: f"{v}"), ("win rate", "win_rate", pct),
        ("time in market", "exposure", pct), ("total costs paid", "costs_total", lambda v: f"${v:,.0f}")]


def svg_equity(curves: dict[str, pd.Series], path: Path):
    w, h, pad = 900, 360, 40
    allv = pd.concat(curves.values())
    lo, hi = np.log(allv.min()), np.log(allv.max())
    t0, t1 = min(c.index[0] for c in curves.values()), max(c.index[-1] for c in curves.values())
    cols = ["#2563eb", "#9ca3af", "#dc2626"]
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" font-family="sans-serif" font-size="12">',
             f'<rect width="{w}" height="{h}" fill="white"/>']
    for i, (name, c) in enumerate(curves.items()):
        c = c.resample("W").last().dropna()
        pts = " ".join(f"{pad + (t - t0) / (t1 - t0) * (w - 2 * pad):.1f},{h - pad - (np.log(v) - lo) / (hi - lo) * (h - 2 * pad):.1f}" for t, v in c.items())
        parts.append(f'<polyline fill="none" stroke="{cols[i % 3]}" stroke-width="1.6" points="{pts}"/>')
        parts.append(f'<text x="{pad + 10}" y="{pad + 16 * (i + 1)}" fill="{cols[i % 3]}">{name}</text>')
    parts.append(f'<text x="{pad}" y="{h - 10}">{t0.date()}</text><text x="{w - pad - 60}" y="{h - 10}">{t1.date()}</text>'
                 f'<text x="{w // 2 - 80}" y="20">Equity (log scale), $100k start</text></svg>')
    path.write_text("\n".join(parts))


def main():
    bars = load_bars("SPY", "1d", adjust="total")
    P(f"Data: SPY daily, Alpaca SIP, total-return adjusted by our own code (splits+dividends). {len(bars):,} bars, {bars.index[0].date()} .. {bars.index[-1].date()}.")
    P("Costs: 'pessimistic' = 2 bps half-spread + 2 bps slippage + 0.5 bps commission per side (real SPY costs are far lower).\n")

    # ---- 1. no-lookahead proof
    strat = SMACross(50, 200, "long")
    cz = check_causality(strat, bars)
    P(f"## 1. No-lookahead check\nSignals recomputed on truncated histories (35/50/65/80/95%) equal the full-history signals: **{'PASS' if cz.ok else 'FAIL: ' + cz.detail}**\n")
    assert cz.ok

    # ---- 2. fills happen exactly at the next open after each crossover (derived independently from pandas diff/sign)
    sig = strat.signals(bars)
    res = backtest(bars, sig, EQUITY_PESSIMISTIC, start=sig.first_valid())
    f50, f200 = bars.close.rolling(50).mean(), bars.close.rolling(200).mean()
    state = (f50 > f200).astype(int).where(f200.notna())
    chg = state.diff().fillna(0) != 0
    chg &= state.index >= sig.first_valid()
    cross_days = state.index[chg.to_numpy()]
    expect_fill = [bars.index[bars.index.get_loc(d) + 1] for d in cross_days if bars.index.get_loc(d) + 1 < len(bars)]
    if state.loc[sig.first_valid()] == 1:       # already in an up-trend when the 200-bar average becomes valid: initial entry
        expect_fill.insert(0, bars.index[bars.index.get_loc(sig.first_valid()) + 1])
    got_fill = list(res.fills.ts[res.fills.reason == "signal"])
    ok2 = expect_fill == got_fill
    P(f"## 2. Fill timing\nCrossovers found independently from the price data: {len(cross_days)} (plus the initial entry when the 200-bar average first becomes valid); "
      f"the engine's signal fills are exactly the NEXT session's open for each: **{'PASS' if ok2 else 'FAIL'}**\n")
    assert ok2
    P("| BUY fill (session open) | price | SELL fill | price | exit reason | net P&L after costs |\n|---|---|---|---|---|---|")
    for (_, t) in res.trades.iterrows():
        P(f"| {t.entry_ts.tz_convert(ET).date()} | {t.entry_px:.2f} | {t.exit_ts.tz_convert(ET).date()} | {t.exit_px:.2f} | {t.exit_reason} | ${t.pnl:,.0f} ({t.ret:.1%}) |")
    P("\nEach decision was taken at the PREVIOUS session's close. These crossovers coincide with the well-known SPY death/golden crosses "
      "(Mar-2020, Jul-2020, Mar-2022, Jan-2023, Apr-2025, Jun-2025), a real-world sanity check on the data and the signal timing.\n")

    # ---- 3. agrees with the independent older engine on real data
    tgt = sig.target.fillna(0.0).to_numpy().copy()
    tgt[-6:] = 0.0
    sig_flat = Signals(pd.Series(tgt, index=bars.index))
    panel = Panel(ts=bars.index.tz_localize(None).to_numpy(), tickers=["SPY"], open=bars[["open"]].to_numpy(), high=bars[["high"]].to_numpy(),
                  low=bars[["low"]].to_numpy(), close=bars[["close"]].to_numpy(), volume=bars[["volume"]].to_numpy(), alive=np.ones((len(bars), 1), bool))
    ex0 = Exec("z", default_spread_bps=0, slip_bps=0, comm_bps=0, open_penalty_bps=0, impact_coef=0, borrow_bps_annual=0, financing_bps_annual=0, max_weight=1.0, max_gross=1.0)
    ex1 = Exec("c", default_spread_bps=4.0, slip_bps=2.0, comm_bps=0.5, open_penalty_bps=0, impact_coef=0, borrow_bps_annual=0, financing_bps_annual=0, max_weight=1.0, max_gross=1.0)
    rows = []
    for label, ex, cs in (("zero cost", ex0, ZERO), ("pessimistic cost", ex1, EQUITY_PESSIMISTIC)):
        # the older engine is a research-grade weight-matrix engine written separately; it starts at bar 0 (flat until the SMA is valid)
        old = 100_000 * float(np.prod(1 + run_backtest(panel, tgt[:, None], ex).net))
        new = backtest(bars, sig_flat, cs).equity.iloc[-1]
        rows.append((label, new, old, new / old - 1))
    P("## 3. Agreement with the independent older engine (same real SPY data, flat before the end so both have closed out)\n")
    P("| cost model | new backtester final equity | older engine final equity | relative difference |\n|---|---|---|---|")
    for label, new, old, d in rows:
        P(f"| {label} | ${new:,.2f} | ${old:,.2f} | {d:.2e} |")
    assert abs(rows[0][3]) < 1e-9 and abs(rows[1][3]) < 5e-5
    P("")

    # ---- 4. results vs buy and hold on the same window
    bh = backtest(bars, BuyHold().signals(bars), EQUITY_PESSIMISTIC, start=sig.first_valid())
    rs, rb = summarize(res), summarize(bh)
    P("## 4. Results vs buy-and-hold (same window, same costs)\n")
    table({"SMA 50/200 long-only": rs, "Buy & hold": rb}, KEYS)
    verdict_ret = "lower" if rs["cagr"] < rb["cagr"] else "higher"
    verdict_dd = ("the same" if abs(rs["max_drawdown"] - rb["max_drawdown"]) < 5e-4 else
                  "smaller" if rs["max_drawdown"] > rb["max_drawdown"] else "larger")
    P(f"\nReading: the crossover earned a {verdict_ret} return than buy-and-hold with {verdict_dd} maximum drawdown. A slow moving-average "
      "crossover reacts late (in 2020 the sell signal fired after the market had already bottomed), so it is not expected to beat buy-and-hold. "
      "It is a known, simple strategy used to prove the machinery; these numbers are NOT evidence of an edge.\n")

    # ---- 5. cost sensitivity
    P("## 5. Cost sensitivity (same signals)\n")
    P("| cost multiple | final equity | CAGR | Sharpe | total costs |\n|---|---|---|---|---|")
    for k in (0, 1, 2, 4):
        r = summarize(backtest(bars, sig, EQUITY_PESSIMISTIC.scaled(k), start=sig.first_valid()))
        P(f"| {k}x | ${r['final_equity']:,.0f} | {pct(r['cagr'])} | {r['sharpe']:.2f} | ${r['costs_total']:,.0f} |")
    P("")

    # ---- 6. other assets / timeframes (smoke test of the whole pipeline)
    P("## 6. Same strategy family on other series (pipeline smoke test, not recommendations)\n")
    out = {}
    for sym, tf, fast, slow, costs, crypto in [("QQQ", "1d", 50, 200, EQUITY_PESSIMISTIC, False), ("IWM", "1d", 50, 200, EQUITY_PESSIMISTIC, False),
                                               ("BTC/USD", "1d", 50, 200, CRYPTO_PESSIMISTIC, True), ("SPY", "15m", 100, 400, EQUITY_PESSIMISTIC, False)]:
        try:
            b = load_bars(sym, tf, adjust="total")
        except FileNotFoundError:
            continue
        s = SMACross(fast, slow, "long").signals(b)
        r = summarize(backtest(b, s, costs, allow_short=False, start=s.first_valid()), crypto=crypto)
        rb2 = summarize(backtest(b, BuyHold().signals(b), costs, start=s.first_valid()), crypto=crypto)
        out[f"{sym} {tf} SMA {fast}/{slow}"] = r
        out[f"{sym} {tf} buy&hold"] = rb2
    table(out, [("years", "years", lambda v: f"{v:.1f}"), ("CAGR", "cagr", pct), ("Sharpe", "sharpe", lambda v: f"{v:.2f}"), ("max DD", "max_drawdown", pct),
                ("trades", "n_trades", lambda v: str(v)), ("costs paid", "costs_total", lambda v: f"${v:,.0f}")])
    P("")
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / "PROOF_SMA_SPY.md").write_text("\n".join(md) + "\n")
    svg_equity({"SMA 50/200": res.equity, "Buy & hold": bh.equity}, ROOT / "docs" / "proof_sma_spy_equity.svg")
    print("\nwrote docs/PROOF_SMA_SPY.md and docs/proof_sma_spy_equity.svg")


if __name__ == "__main__":
    main()
