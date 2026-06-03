"""V7.4 PortTech schema — single dataclass, one enum.

Pure dataclass. No I/O, no scoring, no network. The engine that constructs
these rows is in ``engine.py``.

``quantbot.LIVE_TRADING_ENABLED`` stays ``False``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

# --------------------------------------------------------------------------- #
# Enumeration
# --------------------------------------------------------------------------- #
ALLOWED_PORTTECH_LABEL: frozenset[str] = frozenset({
    "ADD",
    "HOLD",
    "TRIM",
    "WATCH",
    "EXIT_WATCH",
    "DATA_GAP",
})

PORTTECH_ROW_FIELDS: tuple[str, ...] = (
    "as_of", "ticker", "sector", "theme",
    "market_value", "portfolio_weight_pct",
    "company_read", "canonical_sector_signal",
    "company_derived_sector_read",
    "protection_label", "porttech_label",
    "why_short", "action_short", "data_gap_note",
)


class PortTechSchemaError(ValueError):
    """Raised when a PortTechRow fails validation."""


@dataclass
class PortTechRow:
    """One per-position PortTech roll-up.

    All numeric-looking fields (``market_value``,
    ``portfolio_weight_pct``) stay typed as strings so the row can carry
    blanks cleanly when the source position lacked a number.
    ``porttech_label`` is the only field whose enum is validated.
    """

    as_of: str
    ticker: str
    sector: str = ""
    theme: str = ""
    market_value: str = ""
    portfolio_weight_pct: str = ""
    company_read: str = ""
    canonical_sector_signal: str = ""
    company_derived_sector_read: str = ""
    protection_label: str = ""
    porttech_label: str = "HOLD"
    why_short: str = ""
    action_short: str = ""
    data_gap_note: str = ""

    def __post_init__(self) -> None:
        if not self.ticker:
            raise PortTechSchemaError("ticker is required (non-empty)")
        if self.porttech_label not in ALLOWED_PORTTECH_LABEL:
            raise PortTechSchemaError(
                f"porttech_label must be in {sorted(ALLOWED_PORTTECH_LABEL)}, "
                f"got {self.porttech_label!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = [
    "ALLOWED_PORTTECH_LABEL", "PORTTECH_ROW_FIELDS",
    "PortTechRow", "PortTechSchemaError",
]
