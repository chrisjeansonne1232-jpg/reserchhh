# Research-environment audit (2026-09-30)

| # | Question | Finding (measured, not assumed) |
|---|---|---|
| 1 | Data available | Massive via MCP connector: stocks aggregates (daily/minute), reference tickers (incl. delisted), splits, dividends, news, analyst ratings (partner), corporate events (partner), treasury yields, options/crypto/FX/futures/indices endpoints. Plus reachable from sandbox: SEC EDGAR, FRED, Nasdaq Trader symbol directory, Yahoo chart API (unofficial). |
| 2 | Historical periods | **Prices: ~2 years only** (2024-12 OK, 2024-09 / 2022 / 2010 / 2000 → NOT_ENTITLED). News: back to 2016 (first article seen 2016-06-22) but there are no entitled prices to test pre-2024 news against. |
| 3 | Markets | US equities (calendar XNYS). Other markets are refused by `MarketCalendar` until a calendar is registered. |
| 4 | Securities | Reference list includes delisted names with `delisted_utc` (e.g. AABA 2019-10-07, LEHMAN WTS 2008-02-11). |
| 5 | Timestamps | Daily bar `t` = midnight America/New_York (verified 56/56). Minute bar `t` = window start, ms, UTC. News `published_utc` minute resolution only; no vendor/system receipt time. |
| 6 | Corporate actions | Splits (with `historical_adjustment_factor`) and dividends endpoints. `adjusted=false` verified truly unadjusted (ORLY 15:1). Splits table includes future-dated actions (not PIT as returned). |
| 7 | Delisted securities | Present in reference list. Terminal/bankruptcy returns NOT provided → engine raises `DataGapError` rather than assume 0. |
| 8 | Historical news | Yes (`/v2/reference/news`), multi-publisher, syndication present; no revision history. |
| 9 | PIT fundamentals | **Not available from Massive** (`/vX/reference/financials` → 410; replacements NOT_ENTITLED). SEC EDGAR is reachable (acceptance timestamps) — a different provider, must be declared per experiment. |
| 10 | Bid/ask / depth | **Not entitled** (`/v3/quotes`, NBBO ticks). Spreads must be assumed. |
| 11 | Storage | Local disk ~250 GB nominal (30 GB free), DuckDB/pyarrow/SQLite installed. Registry: append-only, hash-chained SQLite + JSONL mirror. |
| 12 | Compute | 4 vCPU, 15 GB RAM, Python 3.11, no GPU. Ample for daily-bar research; not for tick-level. |
| 13 | Connectors | Massive (data), Robinhood (read tools exist; **not used**, no execution), SEC/FRED via HTTPS. No Massive API key in the environment. |
| 14 | Missing | Bulk export path for Massive; NBBO; PIT fundamentals; long price history; news receipt timestamps; delisting terminal returns; halts/LULD list. |
| 15 | Cannot be used | Real-money execution (forbidden by protocol). Yahoo/other providers may not silently substitute for Massive. Massive data licence terms not reviewed here — confirm before redistributing samples. |

Isolation capability verified here: root + `unshare(CLONE_NEWNET)` + uid drop to `nobody` work; a container/VM would be stronger (residual risk documented in `edgelab/sandbox.py`).
