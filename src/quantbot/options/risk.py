"""V5.0 options risk limits.

Defined-risk only. The risk model never permits an unlimited-loss structure.
The engine consults :func:`evaluate_candidate` before submitting any open
order; rejection is logged and the trade is skipped.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from ..risk.greeks import defined_loss_magnitude


@dataclass(frozen=True)
class OptionsRiskLimits:
    max_debit_per_trade: float = 500.0          # $ per spread
    max_credit_per_trade: float = 500.0         # $ per spread (for credit spreads)
    max_loss_per_trade: float = 1000.0          # $ defined max loss (width*100 - credit)
    max_width: float = 10.0                     # $ between long/short strikes
    max_concurrent_positions: int = 1           # tighten for proof-of-engine
    max_portfolio_defined_loss_pct: float = 0.05  # 5% of starting equity
    allow_naked: bool = False                   # HARD FALSE - never flip
    spread_max_pct: float = 0.25                # per-leg bid/ask gate

    def __post_init__(self) -> None:
        for name in ("max_debit_per_trade", "max_credit_per_trade", "max_loss_per_trade",
                     "max_width", "max_concurrent_positions", "max_portfolio_defined_loss_pct",
                     "spread_max_pct"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or not isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and nonnegative")
        if int(self.max_concurrent_positions) != self.max_concurrent_positions:
            raise ValueError("max_concurrent_positions must be an integer")
        if self.max_portfolio_defined_loss_pct > 1:
            raise ValueError("max_portfolio_defined_loss_pct must be a fraction in [0, 1]")
        if self.allow_naked is not False:
            raise ValueError("allow_naked must remain false in this research engine")


@dataclass(frozen=True)
class RiskDecision:
    accepted: bool
    reason: str = ""


def evaluate_candidate(
    candidate, limits: OptionsRiskLimits, *,
    current_open_positions: int,
    initial_capital: float,
    current_portfolio_defined_loss: float,
) -> RiskDecision:
    """Decide whether to allow opening ``candidate``.

    ``candidate`` must expose ``net_cash`` (signed; negative = debit),
    ``max_loss`` (signed; <=0), ``width`` (>=0), and ``is_naked: bool``.
    """
    try:
        loss = defined_loss_magnitude(candidate.max_loss)
        if (not all(isfinite(v) for v in (candidate.net_cash, candidate.width,
                 initial_capital, current_portfolio_defined_loss))
                or candidate.width < 0 or initial_capital <= 0
                or current_portfolio_defined_loss < 0):
            return RiskDecision(False, "invalid_risk_units")
    except (ValueError, TypeError):
        return RiskDecision(False, "invalid_defined_loss")
    if getattr(candidate, "is_naked", False) and not limits.allow_naked:
        return RiskDecision(False, "naked_not_allowed")
    if current_open_positions >= limits.max_concurrent_positions:
        return RiskDecision(False, "max_concurrent_positions")
    if candidate.width > limits.max_width:
        return RiskDecision(False, f"width_gt_{limits.max_width}")

    # Net cash: negative = debit paid out (we sent cash); positive = credit.
    net = float(candidate.net_cash)
    if net < 0 and abs(net) > limits.max_debit_per_trade:
        return RiskDecision(False, f"debit_gt_{limits.max_debit_per_trade}")
    if net > 0 and net > limits.max_credit_per_trade:
        return RiskDecision(False, f"credit_gt_{limits.max_credit_per_trade}")

    # max_loss is a non-positive number; |max_loss| must not exceed cap.
    if loss > limits.max_loss_per_trade:
        return RiskDecision(False, "max_loss_too_large")

    # Portfolio-level: would this push aggregate defined loss above cap?
    new_loss = current_portfolio_defined_loss + loss
    if new_loss > initial_capital * limits.max_portfolio_defined_loss_pct:
        return RiskDecision(False, "portfolio_loss_cap")

    return RiskDecision(True)
