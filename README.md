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
* No real-money execution exists anywhere in this code.
