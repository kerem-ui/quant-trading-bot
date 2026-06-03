"""V7.7 protection schema — single dataclass, one enum.

Every field is a typed string (or int for counts) so the row round-trips
cleanly even if the operator ever wants to serialise the derived view.
The engine that constructs these rows is pure and lives in ``engine.py``.

No I/O, no scoring, no network. ``quantbot.LIVE_TRADING_ENABLED`` stays
``False``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

# --------------------------------------------------------------------------- #
# Enumeration
# --------------------------------------------------------------------------- #
ALLOWED_PROTECTION_LABEL: frozenset[str] = frozenset({
    "OK",
    "WATCH",
    "CONCENTRATION",
    "SECTOR_AT_RISK",
    "SHARED_RISK_EXPOSED",
    "DATA_GAP",
})

PROTECTION_ROW_FIELDS: tuple[str, ...] = (
    "as_of", "ticker", "sector", "theme",
    "market_value", "portfolio_weight_pct",
    "company_read", "canonical_sector_signal",
    "company_derived_sector_read",
    "concentration_label", "sector_risk_label", "company_risk_label",
    "protection_label",
    "why_short", "action_short",
)


class ProtectionSchemaError(ValueError):
    """Raised when a ProtectionRow fails validation."""


@dataclass
class ProtectionRow:
    """One per-position protection roll-up.

    ``portfolio_weight_pct`` and ``market_value`` are kept as strings so
    the row can carry ``""`` / ``"n/a"`` cleanly when the source position
    lacked a numeric value. All four label fields share the same
    :data:`ALLOWED_PROTECTION_LABEL` enum.
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
    concentration_label: str = "OK"
    sector_risk_label: str = "OK"
    company_risk_label: str = "OK"
    protection_label: str = "OK"
    why_short: str = ""
    action_short: str = ""

    def __post_init__(self) -> None:
        if not self.ticker:
            raise ProtectionSchemaError("ticker is required (non-empty)")
        for label_field in ("concentration_label", "sector_risk_label",
                             "company_risk_label", "protection_label"):
            value = getattr(self, label_field)
            if value not in ALLOWED_PROTECTION_LABEL:
                raise ProtectionSchemaError(
                    f"{label_field} must be in "
                    f"{sorted(ALLOWED_PROTECTION_LABEL)}, got {value!r}"
                )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = [
    "ALLOWED_PROTECTION_LABEL", "PROTECTION_ROW_FIELDS",
    "ProtectionRow", "ProtectionSchemaError",
]
