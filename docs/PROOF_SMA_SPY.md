# Proof run: SMA(50/200) crossover on SPY

Data: SPY daily, Alpaca SIP, total-return adjusted by our own code (splits+dividends). 2,737 bars, 2016-01-04 .. 2026-11-19.
Costs: 'pessimistic' = 2 bps half-spread + 2 bps slippage + 0.5 bps commission per side (real SPY costs are far lower).

## 1. No-lookahead check
Signals recomputed on truncated histories (35/50/65/80/95%) equal the full-history signals: **PASS**

## 2. Fill timing
Crossovers found independently from the price data: 8 (plus the initial entry when the 200-bar average first becomes valid); the engine's signal fills are exactly the NEXT session's open for each: **PASS**

| BUY fill (session open) | price | SELL fill | price | exit reason | net P&L after costs |
|---|---|---|---|---|---|
| 2016-10-18 | 183.85 | 2018-12-12 | 237.20 | signal | $29,002 (29.0%) |
| 2019-03-27 | 252.06 | 2020-04-01 | 226.71 | signal | $-12,983 (-10.1%) |
| 2020-07-07 | 289.83 | 2022-03-17 | 406.80 | signal | $46,805 (40.3%) |
| 2023-01-27 | 385.17 | 2025-04-17 | 518.82 | signal | $56,479 (34.7%) |
| 2025-06-30 | 609.35 | 2026-11-19 | 715.58 | end | $38,209 (17.4%) |

Each decision was taken at the PREVIOUS session's close. These crossovers coincide with the well-known SPY death/golden crosses (Mar-2020, Jul-2020, Mar-2022, Jan-2023, Apr-2025, Jun-2025), a real-world sanity check on the data and the signal timing.

## 3. Agreement with the independent older engine (same real SPY data, flat before the end so both have closed out)

| cost model | new backtester final equity | older engine final equity | relative difference |
|---|---|---|---|
| zero cost | $274,644.91 | $274,644.91 | 4.22e-15 |
| pessimistic cost | $273,411.78 | $273,410.28 | 5.50e-06 |

## 4. Results vs buy-and-hold (same window, same costs)

| metric | SMA 50/200 long-only | Buy & hold |
|---|---|---|
| period | 10.09 yrs | 10.09 yrs |
| final equity ($100k start) | $257,512 | $389,174 |
| total return | 157.5% | 289.2% |
| CAGR | 9.8% | 14.4% |
| annual volatility | 15.1% | 17.7% |
| Sharpe (rf=0) | 0.70 | 0.85 |
| Sortino | 0.96 | 1.19 |
| max drawdown | -33.8% | -33.8% |
| trades | 5 | 1 |
| win rate | 80.0% | 100.0% |
| time in market | 84.0% | 99.9% |
| total costs paid | $725 | $220 |

Reading: the crossover earned a lower return than buy-and-hold with the same maximum drawdown. A slow moving-average crossover reacts late (in 2020 the sell signal fired after the market had already bottomed), so it is not expected to beat buy-and-hold. It is a known, simple strategy used to prove the machinery; these numbers are NOT evidence of an edge.

## 5. Cost sensitivity (same signals)

| cost multiple | final equity | CAGR | Sharpe | total costs |
|---|---|---|---|---|
| 0x | $258,674 | 9.9% | 0.70 | $0 |
| 1x | $257,512 | 9.8% | 0.70 | $725 |
| 2x | $256,356 | 9.8% | 0.70 | $1,447 |
| 4x | $254,059 | 9.7% | 0.69 | $2,879 |

## 6. Same strategy family on other series (pipeline smoke test, not recommendations)

| metric | QQQ 1d SMA 50/200 | QQQ 1d buy&hold | IWM 1d SMA 50/200 | IWM 1d buy&hold | BTC/USD 1d SMA 50/200 | BTC/USD 1d buy&hold | SPY 15m SMA 100/400 | SPY 15m buy&hold |
|---|---|---|---|---|---|---|---|---|
| years | 10.1 | 10.1 | 10.1 | 10.1 | 5.3 | 5.3 | 10.8 | 10.8 |
| CAGR | 17.1% | 19.1% | 1.1% | 9.3% | 4.1% | 13.8% | 8.2% | 15.0% |
| Sharpe | 0.90 | 0.89 | 0.15 | 0.51 | 0.29 | 0.51 | 0.81 | 0.88 |
| max DD | -28.6% | -35.1% | -50.5% | -41.3% | -51.2% | -76.7% | -16.8% | -35.1% |
| trades | 5 | 1 | 8 | 1 | 6 | 1 | 99 | 1 |
| costs paid | $1,133 | $308 | $725 | $156 | $5,351 | $989 | $14,333 | $249 |

