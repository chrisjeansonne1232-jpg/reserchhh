# Edge Lab: folder structure and build plan

Paper money only. Nothing in this repository can place a real-money order: the data clients contain no order endpoints,
and `edgelab.data.config.assert_paper_url` refuses every trading host except `paper-api.alpaca.markets`.

## Folder structure

```
reserchhh/
├─ SETUP_WINDOWS.bat            one-time setup (creates .venv, installs, runs self-tests)          [built]
├─ START_EDGE_LAB.bat           the single double-click start command for the whole loop           [step 8]
├─ config/holdout.json          the frozen cut-off date of the sealed 20% holdout                   [built]
├─ data/cache/                  Parquet cache (git-ignored): provider/feed/timeframe/SYMBOL.parquet [built]
├─ registry/                    tamper-evident ledger: every trial, every holdout opening          [reused]
├─ journal/RESEARCH_JOURNAL.md  what was tried, what failed and why, what is next                   [started]
├─ reports/                     promotion reports (written only after validation + 4 weeks paper)  [step 6]
├─ docs/                        plan, proofs, data verification, audit
├─ scripts/                     verification / proof scripts
├─ tests/                       automated tests (python -m pytest)
└─ edgelab/
   ├─ data/          downloader, Parquet cache, corporate actions, quality checks, universe, holdout  [built]
   ├─ strategies/    Strategy interface, causal indicators, no-lookahead checker, reference strategies [built]
   ├─ backtester/    bar-by-bar engine, pessimistic costs, intrabar stops, metrics                     [built]
   ├─ validator/     the gatekeeper (walk-forward, holdout, costs x2, robustness, Monte Carlo, DSR...) [step 5]
   ├─ generator/     strategy families + mutation + Optuna/evolutionary search, logs every trial       [step 3]
   ├─ forward_tester/ Alpaca PAPER trading, live-vs-backtest tracking, auto-demotion                    [step 6]
   ├─ dashboard/     local web dashboard (Streamlit)                                                   [step 7]
   ├─ orchestrator/  the resumable generate -> backtest -> validate -> paper -> monitor -> retire loop  [step 8]
   └─ registry.py stats.py leakage.py integrity.py engine.py ...   earlier infrastructure we reuse
        (stats.py already has Deflated Sharpe, PBO, White's Reality Check, Hansen SPA, BH-FDR)
```

## Build order (and why it differs slightly from the numbering in the brief)

| # | Step | Status |
|---|---|---|
| 1 | Data layer: download, cache, adjust, quality-check, universe, sealed holdout | **done and verified on real data** |
| 2 | Strategy interface | **done** |
| 4 | Backtester + proof on a known strategy (SMA crossover on SPY) | **done** (`docs/PROOF_SMA_SPY.md`) |
| 5 | **Validator** before the generator | next |
| 3 | Generator | after the validator |
| 6 | Forward tester (Alpaca paper) | |
| 7 | Dashboard + leaderboard | |
| 8 | Orchestrator + `START_EDGE_LAB.bat` | |

**Why the validator comes before the generator.** A generator that runs before its gatekeeper is proven will produce
"winners" that nobody can trust. The validator is first tested against strategies that are *known* to be bad (pure
noise, a look-ahead cheat, an over-fit parameter spike, a cost-sensitive scalper) and must reject every one of them;
only then is the generator switched on.

## Things you should know now (they shape what can pass)

1. **100 out-of-sample trades is a hard filter.** A daily strategy on one ETF makes a handful of trades per year, so it
   cannot reach 100 OOS trades in ~2 years of OOS data. Passing strategies will mostly be intraday (1h/15m/5m), or
   multi-asset (trades pooled across many stocks). That is the intended effect of the rule, but it means the search will
   concentrate there.
2. **Data depth.** Alpaca SIP (consolidated) history on the free plan reaches back to 2016 for daily/1h/15m/5m. Crypto
   starts 2021. Massive's free tier only reaches back ~2 years, so it is used as an independent cross-check, not as the
   main source. No historical bid/ask is available, so spreads are assumed (deliberately pessimistic).
3. **Survivorship bias** in the S&P 500 / Nasdaq-100 component universe: current membership is applied to all history.
   Results on components are optimistic; SPY/QQQ/IWM/BTC/ETH are not affected.
4. **Sealed holdout.** The most recent 20% (from the cut-off in `config/holdout.json`) is invisible to the research
   loader and can be opened once per strategy, with the opening recorded in the ledger.
5. **Free-plan live data lag.** Alpaca's free plan blocks the most recent ~15 minutes of consolidated data. Forward
   testing will therefore act on data that is at least 15 minutes old; strategies faster than that will be modelled
   with that delay, not with an unrealistic zero.
