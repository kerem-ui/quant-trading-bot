"""Cash and signed quantities for ETF research accounting.

Adjusted research units remain the default. Raw-share mode requires an explicit
action book. Only executed fills or validated splits change quantities.
Weights and equity are derived from marks, never target weights.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite, isclose

import pandas as pd

from .order import Order, OrderStatus


def required_mark(value: float | None, symbol: str, date: pd.Timestamp) -> float:
    """Validate a required economic price, including its instrument and date."""
    if value is None or pd.isna(value) or not isfinite(value) or value <= 0:
        raise ValueError(f"Invalid valuation price for {symbol} on {pd.Timestamp(date).date()}: {value}")
    return float(value)


@dataclass
class Portfolio:
    initial_capital: float = 1_000_000.0
    cash: float = field(init=False)
    quantities: dict[str, float] = field(default_factory=dict, init=False)
    marks: dict[str, float] = field(default_factory=dict, init=False)
    cumulative_cost: float = field(default=0.0, init=False)

    def __post_init__(self) -> None:
        if not isfinite(self.initial_capital) or self.initial_capital <= 0:
            raise ValueError("initial_capital must be finite and positive")
        self.cash = float(self.initial_capital)

    @property
    def equity(self) -> float:
        """Cash plus signed positions valued at their most recent valid marks."""
        return self.cash + sum(q * self.marks[s] for s, q in self.quantities.items())

    @property
    def weights(self) -> pd.Series:
        """Actual marked exposures, including natural drift between fills."""
        eq = self.equity
        if eq <= 0 or not isfinite(eq):
            raise ValueError("Cannot calculate portfolio weights with non-positive/non-finite equity")
        return pd.Series({s: q * self.marks[s] / eq for s, q in self.quantities.items()},
                         dtype=float)

    def mark(self, prices: dict[str, float], date: pd.Timestamp) -> dict[str, float]:
        """Mark all held units atomically; return per-symbol dollar market P&L."""
        validated = {s: required_mark(prices.get(s), s, date) for s in self.quantities}
        pnl = {s: q * (validated[s] - self.marks[s]) for s, q in self.quantities.items()}
        self.marks.update(validated)
        return pnl

    def apply_fill(self, order: Order) -> None:
        """Book one successful fill's signed notional and fee; ignore rejections."""
        if order.status != OrderStatus.FILLED:
            return
        price = required_mark(order.fill_price, order.symbol, order.execution_date)
        q = order.executed_quantity
        before = self.quantities.get(order.symbol, 0.0)
        if (not isfinite(q) or not isfinite(order.cost) or order.cost < 0
                or not isclose(order.notional, abs(q * price), rel_tol=1e-12, abs_tol=1e-10)
                or not isclose(before, order.quantity_before, rel_tol=1e-12, abs_tol=1e-12)):
            raise ValueError(f"Invalid/stale fill for {order.symbol} on {order.execution_date}")
        self.cash -= q * price + order.cost
        self.cumulative_cost += order.cost
        after = before + q
        if after == 0:
            self.quantities.pop(order.symbol, None)
        else:
            self.quantities[order.symbol] = after
        self.marks[order.symbol] = price

    def charge_cost(self, amount: float) -> None:
        """Deduct a dollar borrow/financing charge without resizing positions."""
        if not isfinite(amount) or amount < 0:
            raise ValueError("Cost must be finite and non-negative")
        self.cash -= amount
        self.cumulative_cost += amount

    def cash_flow(self, amount: float) -> None:
        """Book a signed dividend/interest flow without treating it as a trade."""
        if not isfinite(amount):
            raise ValueError('Non-finite cash flow')
        self.cash += amount

    def split(self, symbol: str, ratio: float) -> None:
        """Convert held raw shares and their prior mark without changing value."""
        if not isfinite(ratio) or ratio <= 0:
            raise ValueError('Split ratio must be finite and positive')
        if symbol in self.quantities:
            self.quantities[symbol] *= ratio
            self.marks[symbol] /= ratio

    def snapshot(self, date: pd.Timestamp, event: str, *, symbol: str | None = None,
                 quantity: float = 0.0, cost: float = 0.0) -> dict:
        """Copy the reconciled state after an event for independent replay."""
        return {"date": date, "event": event, "symbol": symbol, "quantity": quantity,
                "cost": cost, "cash": self.cash, "quantities": self.quantities.copy(),
                "marks": self.marks.copy(), "equity": self.equity,
                "cumulative_cost": self.cumulative_cost}
