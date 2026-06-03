"""Slippage models.

Slippage is expressed in basis points of traded notional. A fixed component
captures average spread-crossing; an optional square-root term approximates
market impact as a function of participation (order size / ADV).

Used as the slippage component of the transaction cost model (composition),
and also directly by the broker to adjust fill price if desired.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class SlippageModel:
    fixed_bps: float = 2.0
    impact_coef_bps: float = 0.0  # bps at 100% participation; 0 disables impact

    def slippage_bps(self, participation: float = 0.0) -> float:
        """Total slippage in bps for a given participation fraction [0, 1]."""
        participation = float(np.clip(participation, 0.0, 1.0))
        return self.fixed_bps + self.impact_coef_bps * np.sqrt(participation)

    def adjust_fill_price(
        self, reference_price: float, side: int, participation: float = 0.0
    ) -> float:
        """Move the fill price against the trader.

        ``side`` is +1 for a buy (pay more) or -1 for a sell (receive less).
        """
        bps = self.slippage_bps(participation)
        return float(reference_price * (1.0 + side * bps / 1e4))
