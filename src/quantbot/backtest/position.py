"""Portfolio state for the weight-based backtester.

Simplification (documented): between rebalances, weights are held constant
(no intra-period drift rebalancing). Turnover cost is charged on the change in
target weights at each execution. This is a standard, transparent research
approximation; it slightly understates drift turnover and is conservative
enough for v1.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class Portfolio:
    initial_capital: float = 1_000_000.0
    equity: float = field(init=False)
    weights: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    cumulative_cost: float = 0.0

    def __post_init__(self) -> None:
        self.equity = float(self.initial_capital)

    def apply_market_return(self, asset_returns: pd.Series) -> float:
        """Apply one day of asset returns to the currently held weights.

        Returns the portfolio's daily return fraction (cash earns 0%).
        """
        if self.weights.empty:
            return 0.0
        w = self.weights
        r = asset_returns.reindex(w.index).fillna(0.0)
        day_ret = float((w * r).sum())
        self.equity *= 1.0 + day_ret
        return day_ret

    def charge_cost(self, cost_fraction: float) -> None:
        """Deduct transaction cost expressed as a fraction of equity."""
        cost_fraction = max(0.0, float(cost_fraction))
        self.cumulative_cost += cost_fraction * self.equity
        self.equity *= 1.0 - cost_fraction

    def set_weights(self, new_weights: pd.Series) -> None:
        self.weights = new_weights.astype(float).copy()
