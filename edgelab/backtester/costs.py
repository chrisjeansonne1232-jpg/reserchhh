"""Transaction-cost model. Defaults are deliberately PESSIMISTIC (real SPY spreads are < 1 bp; these are not)."""
from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Costs:
    half_spread_bps: float          # cost of crossing half the bid/ask spread, per side
    slippage_bps: float             # extra adverse price movement between decision and fill, per side
    commission_bps: float           # commissions + regulatory/exchange fees, per side, on notional
    borrow_bps_annual: float = 100.0      # short-borrow fee, charged on short notional by calendar time
    financing_bps_annual: float = 500.0   # interest on borrowed cash if leverage > 1

    def per_side_bps(self) -> float:
        return self.half_spread_bps + self.slippage_bps + self.commission_bps

    def scaled(self, k: float) -> "Costs":
        """Cost stress test: multiply every cost by k (validator uses k=2)."""
        return replace(self, half_spread_bps=self.half_spread_bps * k, slippage_bps=self.slippage_bps * k,
                       commission_bps=self.commission_bps * k, borrow_bps_annual=self.borrow_bps_annual * k,
                       financing_bps_annual=self.financing_bps_annual * k)


ZERO = Costs(0, 0, 0, 0, 0)
EQUITY_PESSIMISTIC = Costs(half_spread_bps=2.0, slippage_bps=2.0, commission_bps=0.5)           # 4.5 bps per side
CRYPTO_PESSIMISTIC = Costs(half_spread_bps=3.0, slippage_bps=5.0, commission_bps=25.0,           # Alpaca crypto taker fee ~0.25%
                           borrow_bps_annual=0.0, financing_bps_annual=0.0)
