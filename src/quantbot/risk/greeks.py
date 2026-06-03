"""Portfolio-level options Greek aggregation.

Used by options strategies (S05+) to enforce defined-risk limits. Single-option
Greeks live in :mod:`quantbot.options.greeks`; this aggregates a book.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PortfolioGreeks:
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0
    max_loss: float = 0.0  # total defined max loss across structures (>= 0)

    def add(self, other: "PortfolioGreeks") -> "PortfolioGreeks":
        return PortfolioGreeks(
            self.delta + other.delta,
            self.gamma + other.gamma,
            self.theta + other.theta,
            self.vega + other.vega,
            self.max_loss + other.max_loss,
        )


def aggregate_structure_greeks(structures: list) -> PortfolioGreeks:
    """Sum net Greeks across OptionStructure-like objects.

    Each structure must expose ``net_greeks()`` -> dict and ``max_loss()``.
    """
    agg = PortfolioGreeks()
    for s in structures:
        g = s.net_greeks()
        ml = s.max_loss()
        agg = agg.add(
            PortfolioGreeks(
                g.get("delta", 0.0),
                g.get("gamma", 0.0),
                g.get("theta", 0.0),
                g.get("vega", 0.0),
                float(ml) if ml is not None and ml == ml else 0.0,
            )
        )
    return agg


def options_loss_within_limit(
    total_defined_loss: float, equity: float, max_fraction: float
) -> bool:
    """True if aggregate defined options loss is within the equity fraction cap."""
    if equity <= 0:
        return False
    return (total_defined_loss / equity) <= max_fraction
