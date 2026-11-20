# Edge Lab research journal

Newest entries at the bottom. Every dead end is recorded here so the search does not repeat it.

## 2026-11-20  Build phase 1: data layer + backtester

**Done**
- Data: Alpaca SIP raw bars cached as Parquet (SPY, QQQ, IWM, BTC/USD, ETH/USD at 1d/15m/5m; 1h built from 15m for
  equities, native for crypto). Corporate actions cached; split and dividend adjustment done by our own code at load time
  (not the provider's), verified against the provider's adjusted bars.
- Backtester: next-bar-open fills, pessimistic costs (4.5 bps per side equities, 33 bps crypto), intrabar stops with
  pessimistic tie-breaks, gap-through-stop fills at the open, P&L ledger that reconciles to the cent.
- Proof: SMA 50/200 on SPY. Fill dates equal the session after each independently-derived crossover; matches the older
  independent engine to 4e-15 at zero cost. See `docs/PROOF_SMA_SPY.md`.
- Sealed holdout enforced in code (`edgelab/data/holdout.py`).

**Findings**
- SMA 50/200 long-only on SPY (2016-10..2026-11): CAGR 9.8% vs buy-and-hold 14.4%; max drawdown identical (-33.8%)
  because the death cross fired after the March-2020 bottom. A known, expected result: nothing here is an edge.
- Bugs found by the tests while building (kept here as lessons): pandas 3 stores timestamps in microseconds, which made
  holding-cost accrual 1000x too small until forced to nanoseconds; an operator-precedence error in the date filter.

**Dead ends**: none yet (no strategy search has run).

**Next**: validator, proven against known-bad strategies, then the generator.
