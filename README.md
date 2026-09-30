# reserchhh — autonomous trading-edge discovery lab (infrastructure phase)

Status: **infrastructure built and self-tested; strategy discovery is NOT started** (discovery gate BLOCKED — see
`docs/DATA_INTEGRITY_REPORT.md`).

* `edgelab/registry.py` immutable hash-chained experiment registry (pre-registration, trial counting, contamination)
* `edgelab/engine.py` causal bar-by-bar backtester, three execution regimes, break-even cost, no silent zero/ffill
* `edgelab/stats.py` DSR, PBO, White RC, Hansen SPA, BH-FDR, permutation, power
* `edgelab/leakage.py` truncation-invariance + future-scramble detectors
* `edgelab/sandbox.py` AST checks + restricted builtins + unprivileged uid + no network + streaming bars
* `edgelab/evaluator.py` frozen-threshold evaluator, single-shot locked OOS, public-verdict-only output
* `edgelab/integrity.py` calendar-aware integrity checks, gap ledger, discovery gate
* `selftest/` intentionally flawed strategies; `tests/` 69+ tests (`python -m pytest`)
* `edgelab/alpaca.py` primary price source (Alpaca free SIP, raw, historical-only, refuses windows newer than 15 min); `edgelab/massive.py` free-tier reference/splits/cross-validation;
  `edgelab/providers.py` env-only credentials + redaction. `scripts/ingest_*.py` and `scripts/build_integrity_report.py` reproduce the audit (raw data is git-ignored).
* Integrity checks added: ticker renames / symbol re-use, rename-feed quality, delisted-name coverage, cross-provider daily/minute/splits, OHLC validity, zero-volume placeholders, tick sanity.
* **DAILY_SWING_V1** (second, separate gate; the first gate is untouched): `docs/DAILY_SWING_V1_REQUIREMENTS.md` (frozen, hash in the registry), `docs/DAILY_SWING_V1_AUDIT.md` (result),
  `edgelab/daily_swing*.py`, `scripts/audit_daily_swing_v1.py`. Status: **BLOCKED** (see the audit). Strategy discovery has NOT been started.
* No real-money execution exists anywhere in this code.
