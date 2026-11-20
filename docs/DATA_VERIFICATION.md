# Data-layer verification (real data)

Generated 2026-11-20 03:07 UTC. Provider: Alpaca SIP (primary), Massive free tier (cross-check).

## 1. Quality checks on cached data

| series | rows | first | last | verdict | notes |
|---|---|---|---|---|---|
| SPY 1d | 2,737 | 2016-01-04 | 2026-11-19 | OK | none |
| QQQ 1d | 2,737 | 2016-01-04 | 2026-11-19 | OK | WARN possible_bad_ticks (n=2): one-bar spikes that reverse next bar, e.g. 2020-03-12 04:00:00+00:00 |
| IWM 1d | 2,737 | 2016-01-04 | 2026-11-19 | OK | WARN possible_bad_ticks (n=1): one-bar spikes that reverse next bar, e.g. 2020-03-12 04:00:00+00:00 |
| AAPL 1d | 2,737 | 2016-01-04 | 2026-11-19 | OK | WARN possible_bad_ticks (n=1): one-bar spikes that reverse next bar, e.g. 2020-03-13 04:00:00+00:00 |
| NVDA 1d | 2,737 | 2016-01-04 | 2026-11-19 | OK | none |
| BTC/USD 1d | 2,149 | 2021-01-01 | 2026-11-19 | OK | WARN possible_bad_ticks (n=1): one-bar spikes that reverse next bar, e.g. 2026-02-05 00:00:00+00:00 |
| ETH/USD 1d | 2,149 | 2021-01-01 | 2026-11-19 | OK | none |
| SPY 15m | 70,883 | 2016-01-04 | 2026-11-18 | OK | WARN possible_bad_ticks (n=2): one-bar spikes that reverse next bar, e.g. 2025-04-07 13:30:00+00:00 |
| QQQ 15m | 70,882 | 2016-01-04 | 2026-11-18 | OK | WARN possible_bad_ticks (n=2): one-bar spikes that reverse next bar, e.g. 2025-04-07 13:30:00+00:00 |
| IWM 15m | 70,883 | 2016-01-04 | 2026-11-18 | OK | WARN possible_bad_ticks (n=3): one-bar spikes that reverse next bar, e.g. 2022-06-15 18:30:00+00:00 |
| SPY 1h | 19,089 | 2016-01-04 | 2026-11-18 | OK | WARN possible_bad_ticks (n=1): one-bar spikes that reverse next bar, e.g. 2020-03-13 13:30:00+00:00 |
| SPY 5m | 212,638 | 2016-01-04 | 2026-11-18 | OK | WARN possible_bad_ticks (n=1): one-bar spikes that reverse next bar, e.g. 2020-03-12 13:55:00+00:00 |
| BTC/USD 1h | 51,538 | 2021-01-01 | 2026-11-19 | OK | WARN missing_bars (n=14): 0.03% of the 24/7 grid is missing (provider omits bars with no trades); WARN possible_bad_ticks (n=7): one-bar spikes that reverse next bar, e.g. 2022-05-09 23:00:00+00:00 |

## 2. Our split adjustment vs the provider's own split-adjusted bars (same dates)

Daily closes, 2016-01-01 .. last cached. Relative difference of OUR adjusted close vs ALPACA `adjustment=split`.

The provider rounds its adjusted prices to cents, so the correct test is: every difference is at most half a cent.

| symbol | splits in range | median rel diff | max rel diff | max abs diff ($) | verdict |
|---|---|---|---|---|---|
| AAPL | 1 | 0.00e+00 | 2.21e-04 | 0.0050 | MATCH (within provider rounding) |
| NVDA | 2 | 4.63e-05 | 4.88e-04 | 0.0050 | MATCH (within provider rounding) |
| SPY | 0 | 0.00e+00 | 0.00e+00 | 0.0000 | MATCH (within provider rounding) |

## 3. Our total-return (splits + dividends) vs the provider's `adjustment=all`

| symbol | median abs diff (bps) | max abs diff (bps) | note |
|---|---|---|---|
| SPY | 0.46 | 0.78 | provider uses its own dividend convention; agreement within a few bps means the same method |
| AAPL | 0.20 | 2.19 | provider uses its own dividend convention; agreement within a few bps means the same method |

## 4. Independent second source: Alpaca SIP vs Massive (raw closes, last ~23 months = Massive free-tier window)

| symbol | overlap bars | median diff (bps) | p99 diff (bps) | max diff (bps) | share within 10 bps | median volume ratio Alpaca/Massive |
|---|---|---|---|---|---|---|
| SPY | 474 | 0.0 | 0.0 | 0.0 | 100.00% | 1.0 |
| QQQ | 474 | 0.0 | 0.0 | 0.0 | 100.00% | 1.0 |
| IWM | 474 | 0.0 | 0.0 | 0.0 | 100.00% | 1.0 |

## 5. Cross-timeframe consistency (SPY)

5m bars aggregated to 15m vs the provider's own 15m bars: 70,883 overlapping bars
- open: share of bars identical (<0.5 bp) = 100.00%, max diff = 0.0 bps
- high: share of bars identical (<0.5 bp) = 100.00%, max diff = 0.0 bps
- low: share of bars identical (<0.5 bp) = 100.00%, max diff = 0.0 bps
- close: share of bars identical (<0.5 bp) = 100.00%, max diff = 0.0 bps
- volume: median ratio 15m/aggregated-5m = 1.0000
daily bar vs RTH-15m aggregation: 2,736 sessions; close identical (<1bp) 59.65%; open identical 97.62%; median volume ratio daily/RTH-15m = 1.196

## Interpretation (read this)

- Alpaca SIP and Massive agree exactly because both report the same consolidated tape. That confirms our ingestion, cache and alignment are correct; it is NOT two independent views of the market. No truly independent price source is available on free plans.
- Our split adjustment equals the provider's to within cent-rounding. Total-return adjustment agrees within ~2 bps (different dividend rounding).
- 5m bars aggregate to the provider's 15m bars exactly, so the intraday timeline and session handling are internally consistent.
- The official daily close/open come from the closing/opening auctions, while the last/first 15-minute bar reflects regular-session trades. They differ on some days (see the close/open percentages above) and the daily volume is ~20% higher than the regular-hours 15m sum. Consequence: never mix daily-bar and intraday-bar prices inside one strategy's signals; each strategy uses ONE timeframe.
- Quality WARNs (one-bar spikes) fall on genuine extreme days (Mar-2020 circuit breakers, Apr-2025 tariff crash). They are reported, not removed.
