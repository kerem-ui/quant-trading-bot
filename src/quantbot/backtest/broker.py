"""Simulated broker.

RESEARCH ONLY. This class never connects anywhere. It refuses to operate if
``quantbot.LIVE_TRADING_ENABLED`` is ever flipped to True, as a hard guard
against accidental live-trading code paths.

The broker turns pending orders into fills at the *next bar's* execution price
(open or close per config) and charges the transaction-cost model on the
traded notional.
"""

from __future__ import annotations

from math import isfinite

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
        price_mode: str = "adjusted",
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
        if price_mode not in ('adjusted','raw'):
            raise ValueError('price_mode must be adjusted or raw')
        self.price_mode = price_mode
        self._price_col = "open" if execution == "next_open" else "close"

    def execution_price(self, symbol: str, execution_date: pd.Timestamp) -> float | None:
        """Adjusted open = raw open * adjusted close / raw close; close = adjusted close.

        The factor is a research unit conversion, not an executable raw-share quote.
        Explicit raw mode uses the supplied unadjusted open/close directly.
        """
        df = self.panel.get(symbol)
        if df is None or execution_date not in df.index:
            return None
        raw_close = df.at[execution_date, "close"]
        if self.price_mode == 'raw':
            price = df.at[execution_date, self._price_col]
            return float(price) if pd.notna(price) and isfinite(price) and price > 0 else None
        adjusted_close = df.at[execution_date, "adjusted_close"]
        raw_price = df.at[execution_date, self._price_col]
        if any(pd.isna(p) or not isfinite(p) or p <= 0
               for p in (raw_close, adjusted_close, raw_price)):
            return None
        price = float(adjusted_close if self.execution == "next_close"
                      else raw_price * (adjusted_close / raw_close))
        return price if isfinite(price) and price > 0 else None

    def fill(self, order: Order, equity: float, current_quantity: float = 0.0) -> Order:
        """Convert a target into a signed fill using execution-time state.

        Every order in a rebalance uses the same pre-cost marked equity, so
        symbol ordering does not change allocations. Costs are cash charges.
        """
        if order.status != OrderStatus.PENDING:
            raise ValueError("Only a pending order can be filled")
        price = self.execution_price(order.symbol, order.execution_date)
        if price is None:
            order.status = OrderStatus.REJECTED
            order.note = "no execution price (missing bar / halted)"
            return order
        if (not isfinite(equity) or equity <= 0 or not isfinite(current_quantity)
                or not isfinite(order.target_weight)):
            raise ValueError("Fill sizing requires finite targets/quantities and positive equity")
        quantity = order.target_weight * equity / price - current_quantity
        notional = abs(quantity * price)
        cost = self.cost_model.cost(notional)
        if not isfinite(quantity) or not isfinite(notional) or not isfinite(cost) or cost < 0:
            raise ValueError("Non-finite fill or invalid transaction cost")
        order.executed_quantity = quantity
        order.quantity_before = current_quantity
        order.allocation_equity = equity
        order.notional = notional
        order.cost = cost
        order.fill_price = price
        order.status = OrderStatus.FILLED
        return order
