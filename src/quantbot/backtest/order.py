"""Order records.

An Order always has ``signal_date < execution_date``. The engine constructs
orders on the signal date but they only fill on the next bar - this invariant
is what prevents look-ahead, and it is asserted by the engine and tested.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import pandas as pd


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    REJECTED = "REJECTED"


@dataclass
class Order:
    symbol: str
    signal_date: pd.Timestamp
    execution_date: pd.Timestamp
    prev_weight: float
    target_weight: float
    status: OrderStatus = OrderStatus.PENDING
    fill_price: float | None = None
    cost: float = 0.0
    note: str = ""
    executed_quantity: float = 0.0  # signed quantities in the run's declared price basis
    notional: float = 0.0  # absolute executed dollar notional
    quantity_before: float = 0.0
    allocation_equity: float = 0.0  # common pre-cost execution-batch equity
    target_quantity: float | None = None  # off-cycle exits/reductions freeze held units
    intended_quantity: float = 0.0
    execution_outcome: str = 'pending'
    cost_components: dict[str,float] = field(default_factory=dict)
    liquidity_notional: float | None = None

    def __post_init__(self) -> None:
        if pd.Timestamp(self.execution_date) <= pd.Timestamp(self.signal_date):
            raise ValueError(
                f"Look-ahead violation: execution_date {self.execution_date} "
                f"must be strictly after signal_date {self.signal_date} "
                f"({self.symbol})."
            )

    @property
    def delta_weight(self) -> float:
        return self.target_weight - self.prev_weight

    @property
    def side(self) -> OrderSide:
        direction = self.executed_quantity if self.status == OrderStatus.FILLED else self.delta_weight
        return OrderSide.BUY if direction >= 0 else OrderSide.SELL
