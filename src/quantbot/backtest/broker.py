"""Simulated broker.

RESEARCH ONLY. This class never connects anywhere. It refuses to operate if
``quantbot.LIVE_TRADING_ENABLED`` is ever flipped to True, as a hard guard
against accidental live-trading code paths.

The broker turns pending orders into fills at the *next bar's* execution price
(open or close per config) and charges the transaction-cost model on the
traded notional.
"""

from __future__ import annotations

import pandas as pd

from .. import LIVE_TRADING_ENABLED
from ..costs.transaction_costs import EquityCostModel
from .order import Order, OrderStatus


class SimulatedBroker:
    def __init__(
        self,
        panel: dict[str, pd.DataFrame],
        cost_model: EquityCostModel,
        execution: str = "next_open",
    ):
        if LIVE_TRADING_ENABLED:  # pragma: no cover - safety guard
            raise RuntimeError(
                "LIVE_TRADING_ENABLED is True. This is a research/backtest-only "
                "system; live execution is not implemented and not permitted."
            )
        if execution not in ("next_open", "next_close"):
            raise ValueError("execution must be 'next_open' or 'next_close'")
        self.panel = panel
        self.cost_model = cost_model
        self.execution = execution
        self._price_col = "open" if execution == "next_open" else "close"

    def execution_price(self, symbol: str, execution_date: pd.Timestamp) -> float | None:
        df = self.panel.get(symbol)
        if df is None or execution_date not in df.index:
            return None
        px = df.at[execution_date, self._price_col]
        return float(px) if pd.notna(px) else None

    def fill(self, order: Order, equity: float) -> Order:
        """Fill one order at the next-bar price and compute its cost.

        Cost is charged on the *notional traded* = |Δweight| * equity, using
        the round-trip-aware one-way cost model (each rebalance is one way).
        """
        price = self.execution_price(order.symbol, order.execution_date)
        if price is None or price <= 0:
            order.status = OrderStatus.REJECTED
            order.note = "no execution price (missing bar / halted)"
            return order
        traded_notional = abs(order.delta_weight) * equity
        order.cost = self.cost_model.cost(traded_notional)
        order.fill_price = price
        order.status = OrderStatus.FILLED
        return order
