"""Transaction cost models.

Every simulated trade is charged. Costs reduce returns - this is enforced by
the backtest engine and asserted by tests.

v1 models (intentionally simple and robust):
  - Equities/ETFs: (commission + half-spread + slippage) bps * traded notional
  - Options:       per-contract fee + fraction of bid/ask width + multi-leg
                   penalty, per leg

Cost filter: a trade is only worthwhile if
    expected_edge_bps > cost_multiplier * round_trip_cost_bps
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite

from .slippage import SlippageModel


@dataclass
class EquityCostModel:
    """Per-side cost in basis points of traded notional.

    Defaults mirror strategy_configs.json ``global`` (commission 1bp,
    slippage 2bp) plus a conservative 2bp half-spread for liquid ETFs.
    """

    commission_bps: float = 1.0
    half_spread_bps: float = 2.0
    slippage: SlippageModel = field(default_factory=lambda: SlippageModel(fixed_bps=2.0))
    min_commission: float = 0.0

    def one_way_bps(self, participation: float = 0.0) -> float:
        return (
            self.commission_bps
            + self.half_spread_bps
            + self.slippage.slippage_bps(participation)
        )

    def round_trip_bps(self, participation: float = 0.0) -> float:
        return 2.0 * self.one_way_bps(participation)

    def cost(self, trade_value: float, participation: float = 0.0) -> float:
        """Dollar cost for a single trade of ``abs(trade_value)`` notional."""
        tv = abs(float(trade_value))
        c = tv * self.one_way_bps(participation) / 1e4
        return max(self.min_commission, c) if tv > 0 else 0.0

    def passes_cost_filter(
        self, expected_edge_bps: float, cost_multiplier: float = 3.0
    ) -> bool:
        """True if expected edge clears the round-trip cost hurdle."""
        return expected_edge_bps > cost_multiplier * self.round_trip_bps()


@dataclass
class OptionsCostModel:
    """Defined-risk options structures only (no naked shorts in v1).

    ``structure_cost`` estimates costs relative to midpoint (used by parity
    research). Bid/ask executions use ``execution_costs`` instead: crossing
    is already in their premium cash flow and must not be charged again.
    The existing multi-leg penalty is explicit additional dollar slippage.
    """

    per_contract_fee: float = 0.65
    bid_ask_fraction: float = 0.5  # fraction of the spread crossed per leg
    multi_leg_penalty: float = 1.0  # flat $ added once per multi-leg structure
    contract_multiplier: int = 100

    def leg_cost(self, contracts: int, bid: float, ask: float) -> float:
        contracts = abs(int(contracts))
        spread = max(0.0, ask - bid)
        fee = self.per_contract_fee * contracts
        spread_cost = self.bid_ask_fraction * spread * contracts * self.contract_multiplier
        return fee + spread_cost

    def structure_cost(self, legs: list[dict]) -> float:
        """``legs``: list of {contracts, bid, ask}. Penalty applied if >1 leg."""
        total = sum(self.leg_cost(l["contracts"], l["bid"], l["ask"]) for l in legs)
        if len(legs) > 1:
            total += self.multi_leg_penalty
        return total

    def execution_costs(self, legs: list[dict]) -> dict[str, float]:
        """Separate fees and extra slippage for fills already crossing bid/ask."""
        if any(not isfinite(v) or v < 0
               for v in (self.per_contract_fee, self.multi_leg_penalty)):
            raise ValueError("execution costs must be finite and nonnegative")
        commission = self.per_contract_fee * sum(abs(l["contracts"]) for l in legs)
        slippage = self.multi_leg_penalty if len(legs) > 1 else 0.0
        return {"commission": float(commission), "slippage": float(slippage),
                "spread_cost": 0.0, "total": float(commission + slippage)}


@dataclass
class FuturesCostModel:
    """Placeholder for S04. Per-contract fee + tick slippage."""

    per_contract_fee: float = 2.0
    tick_value: float = 12.5
    ticks_slippage: float = 1.0

    def cost(self, contracts: int) -> float:
        c = abs(int(contracts))
        return c * (self.per_contract_fee + self.ticks_slippage * self.tick_value)


def equity_cost_model_from_config(cfg: dict) -> EquityCostModel:
    """Build an EquityCostModel from the ``global`` block of strategy config."""
    g = cfg.get("global", cfg)
    return EquityCostModel(
        commission_bps=float(g.get("default_commission_bps", 1.0)),
        half_spread_bps=2.0,
        slippage=SlippageModel(fixed_bps=float(g.get("default_slippage_bps", 2.0))),
    )
