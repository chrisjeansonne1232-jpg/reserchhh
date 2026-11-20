# Edge Lab: autonomous trading-strategy research lab (PAPER MONEY ONLY)

It generates strategy candidates, tests them hard, and promotes only the ones that survive. No real-money order can be
placed by this code.

Status: **data layer, strategy interface and backtester are built and proven** (see `docs/PLAN.md`,
`docs/PROOF_SMA_SPY.md`, `docs/DATA_VERIFICATION.md`). Validator, generator, forward tester, dashboard and orchestrator
come next, in that order.

## First steps (Windows)

1. Double-click `SETUP_WINDOWS.bat` (creates a private Python environment and runs the self-tests).
2. Open **Command Prompt** in this folder and activate it:  `.venv\Scripts\activate`
3. Check your keys are visible (shows names only):  `python -m edgelab.data keys`
4. See what your free plans allow:  `python -m edgelab.data probe`
5. Download the core data (a few minutes; safe to stop and re-run, it only fetches what is missing):
   `python -m edgelab.data download --tier core --tf 1d 15m 5m`
6. Prove it works:  `python scripts/prove_sma_spy.py`
7. Seal the final holdout (ONE time, cannot be undone):  `python -m edgelab.data freeze-holdout`
   (already done in this repository: see `config/holdout.json`; do not run it again)

## Layout
See `docs/PLAN.md`. Research diary: `journal/RESEARCH_JOURNAL.md`.

## Earlier infrastructure (reused)
`edgelab/registry.py` hash-chained ledger, `edgelab/stats.py` (Deflated Sharpe, PBO, White RC, Hansen SPA), `edgelab/leakage.py`,
`edgelab/integrity.py`, `edgelab/engine.py` (multi-asset weight-matrix engine, used as an independent cross-check).
`edgelab/sandbox.py` is Linux-only and is not used on Windows.
