"""Sector thesis tracker orchestrator (V6.1, pure functions).

Builds a ``SectorReport`` for one sector from loaded catalysts + exits. No
network, no broker, no order. Outputs a research signal LABEL only.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .schema import Catalyst, EmergencyExit
from .scoring import SectorScore, score_sector


@dataclass(frozen=True)
class SectorReport:
    sector: str
    score: SectorScore
    catalysts: list[Catalyst] = field(default_factory=list)
    exits: list[EmergencyExit] = field(default_factory=list)


def build_sector_report(
    sector: str,
    catalysts: list[Catalyst],
    exits: list[EmergencyExit] | None = None,
) -> SectorReport:
    """Filter catalysts/exits to ``sector`` and score them."""
    cats = [c for c in catalysts if c.sector == sector]
    exs = [e for e in (exits or []) if e.sector == sector]
    score = score_sector(cats, exs, sector=sector)
    return SectorReport(sector=sector, score=score, catalysts=cats, exits=exs)


def build_all_sectors(
    catalysts: list[Catalyst],
    exits: list[EmergencyExit] | None = None,
    sectors: list[str] | None = None,
) -> dict[str, SectorReport]:
    """Return ``{sector: SectorReport}`` for every sector present (or given)."""
    if sectors is None:
        sectors = sorted(
            {c.sector for c in catalysts}
            | {e.sector for e in (exits or [])}
        )
    return {s: build_sector_report(s, catalysts, exits) for s in sectors}


__all__ = ["SectorReport", "build_sector_report", "build_all_sectors"]
