"""Portfolio-level options Greek aggregation.

Used by options strategies (S05+) to enforce defined-risk limits. Single-option
Greeks live in :mod:`quantbot.options.greeks`; this aggregates a book.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


def defined_loss_magnitude(signed_max_loss: float) -> float:
    """Convert nonpositive worst-case dollar P&L to a nonnegative dollar loss.

    Unknown/unbounded values are not zero risk; reject them explicitly.
    """
    if signed_max_loss is None or not isfinite(signed_max_loss) or signed_max_loss > 0:
        raise ValueError("defined maximum loss must be finite signed P&L <= 0")
    return -float(signed_max_loss)


@dataclass
class PortfolioGreeks:
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0
    max_loss: float = 0.0  # total defined max loss across structures (>= 0)

    def __post_init__(self) -> None:
        if not isfinite(self.max_loss) or self.max_loss < 0:
            raise ValueError("portfolio max_loss must be a finite nonnegative dollar loss amount")

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
                (g["delta"] if g.get("delta") is not None and isfinite(g["delta"]) else float("nan")),
                (g["gamma"] if g.get("gamma") is not None and isfinite(g["gamma"]) else float("nan")),
                (g["theta"] if g.get("theta") is not None and isfinite(g["theta"]) else float("nan")),
                (g["vega"] if g.get("vega") is not None and isfinite(g["vega"]) else float("nan")),
                defined_loss_magnitude(ml),
            )
        )
    return agg


def options_loss_within_limit(
    total_defined_loss: float, equity: float, max_fraction: float
) -> bool:
    """True if aggregate defined options loss is within the equity fraction cap."""
    if (not all(isfinite(v) for v in (total_defined_loss, equity, max_fraction))
            or equity <= 0 or total_defined_loss < 0 or not 0 <= max_fraction <= 1):
        return False
    return (total_defined_loss / equity) <= max_fraction
