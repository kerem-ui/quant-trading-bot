"""Sector thesis scoring (V6.1, pure functions).

Transparent tier-weighted, status-scored aggregation that maps a list of
``Catalyst`` records (and optional ``EmergencyExit`` records) into a sector
``SectorScore`` with a single signal label.

Design rules:
  - Pre-declared weights and thresholds. NO parameter tuning, NO ML.
  - Emergency-exit triggers OVERRIDE the score (force ``EXIT_WATCH``).
  - Decision-support only. The framework never emits a broker order.
    ``LIVE_TRADING_ENABLED`` stays ``False``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .schema import Catalyst, EmergencyExit

# Tier weight (Tier 1 catalysts have higher weight than Tier 2).
TIER_WEIGHT: dict[int, int] = {1: 2, 2: 1}

# Per-catalyst contribution by status. BULL positive, NEUTRAL zero,
# NEAR_THRESHOLD modest negative, BROKEN strong negative.
STATUS_VALUE: dict[str, int] = {
    "BULL": 1,
    "NEUTRAL": 0,
    "NEAR_THRESHOLD": -1,
    "BROKEN": -2,
}

# Normalized-score thresholds (raw / total_weight). Pre-declared and fixed.
# Range is roughly [-2.0, +1.0] (all-Tier-1-BROKEN to all-BULL).
SIGNAL_THRESHOLDS: list[tuple[float, str]] = [
    (0.50, "ACCUMULATE"),
    (0.20, "SELECTIVE_BUY"),
    (-0.10, "HOLD"),
    (-0.30, "AVOID_NEW_BUY"),
    (-0.60, "REDUCE"),
    # < -0.60  ->  EXIT_WATCH
]


@dataclass(frozen=True)
class SectorScore:
    sector: str
    raw_score: float
    total_weight: int
    normalized_score: float
    n_total: int
    n_bull: int
    n_neutral: int
    n_near_threshold: int
    n_broken: int
    top_bull_drivers: list[str] = field(default_factory=list)
    top_risks: list[str] = field(default_factory=list)
    emergency_triggered: bool = False
    triggered_exits: list[str] = field(default_factory=list)
    signal: str = "HOLD"


def _normalize(raw: float, total_weight: int) -> float:
    if total_weight <= 0:
        return 0.0
    return float(raw) / float(total_weight)


def signal_from_normalized(norm: float) -> str:
    """Map a normalized score to a sector signal label (pre-declared bands)."""
    for cutoff, label in SIGNAL_THRESHOLDS:
        if norm >= cutoff:
            return label
    return "EXIT_WATCH"


def score_sector(
    catalysts: list[Catalyst],
    exits: list[EmergencyExit] | None = None,
    *,
    sector: str | None = None,
) -> SectorScore:
    """Aggregate ``catalysts`` (optionally filtered to ``sector``) into a score.

    If any emergency exit has ``current_status == "TRIGGERED"`` the signal is
    forced to ``EXIT_WATCH`` regardless of the catalyst score. This is still
    a research recommendation, NOT a broker order.
    """
    exits = exits or []
    cats = (
        [c for c in catalysts if c.sector == sector]
        if sector is not None else list(catalysts)
    )
    exs = (
        [e for e in exits if e.sector == sector]
        if sector is not None else list(exits)
    )

    raw = 0.0
    total_w = 0
    n_bull = n_neu = n_near = n_brk = 0
    for c in cats:
        w = TIER_WEIGHT[c.tier]
        v = STATUS_VALUE[c.status]
        raw += w * v
        total_w += w
        if c.status == "BULL":
            n_bull += 1
        elif c.status == "NEUTRAL":
            n_neu += 1
        elif c.status == "NEAR_THRESHOLD":
            n_near += 1
        elif c.status == "BROKEN":
            n_brk += 1

    norm = _normalize(raw, total_w)

    bulls = sorted(
        [c for c in cats if c.status == "BULL"],
        key=lambda c: (-TIER_WEIGHT[c.tier], c.catalyst_name),
    )
    risks = sorted(
        [c for c in cats if c.status in {"BROKEN", "NEAR_THRESHOLD"}],
        key=lambda c: (STATUS_VALUE[c.status], -TIER_WEIGHT[c.tier], c.catalyst_name),
    )
    top_bull = [c.catalyst_name for c in bulls[:5]]
    top_risk = [c.catalyst_name for c in risks[:5]]

    triggered = [e.exit_id for e in exs if e.current_status == "TRIGGERED"]
    emergency = bool(triggered)

    signal = "EXIT_WATCH" if emergency else signal_from_normalized(norm)

    return SectorScore(
        sector=sector or "",
        raw_score=raw,
        total_weight=total_w,
        normalized_score=norm,
        n_total=len(cats),
        n_bull=n_bull,
        n_neutral=n_neu,
        n_near_threshold=n_near,
        n_broken=n_brk,
        top_bull_drivers=top_bull,
        top_risks=top_risk,
        emergency_triggered=emergency,
        triggered_exits=triggered,
        signal=signal,
    )


__all__ = [
    "TIER_WEIGHT", "STATUS_VALUE", "SIGNAL_THRESHOLDS",
    "SectorScore", "signal_from_normalized", "score_sector",
]
