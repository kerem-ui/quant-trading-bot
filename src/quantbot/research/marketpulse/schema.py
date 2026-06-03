"""V7.8 MarketPulse schema — three dataclasses, pre-declared enums.

All fields are typed strings (except where enumerated). The operator edits
the CSVs by hand or via a future V7.8.1 helper; the platform reads only.

No I/O, no scoring, no network. ``quantbot.LIVE_TRADING_ENABLED`` stays
``False``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

# --------------------------------------------------------------------------- #
# Enumerations
# --------------------------------------------------------------------------- #
ALLOWED_REGIME_PANELS: frozenset[str] = frozenset({
    "RATES", "INFLATION", "LABOR", "GROWTH",
    "VOLATILITY", "CREDIT_RISK", "RISK_ON_OFF",
})

# Small enum so the operator can label a row with a directional sentiment
# without inventing new labels. N_A is the "no read yet" placeholder.
ALLOWED_REGIME_STATUS: frozenset[str] = frozenset({
    "BULLISH", "NEUTRAL", "BEARISH", "MIXED", "N_A",
})

ALLOWED_TREND_STATUS: frozenset[str] = frozenset({
    "UPTREND", "DOWNTREND", "SIDEWAYS", "N_A",
})

ALLOWED_EVENT_IMPACT: frozenset[str] = frozenset({
    "LOW", "MEDIUM", "HIGH", "N_A",
})

# Canonical CSV column orders.
REGIME_DASHBOARD_FIELDS: tuple[str, ...] = (
    "panel", "indicator", "value", "status", "interpretation",
    "source", "source_file", "last_updated",
)

SECTOR_ETF_FIELDS: tuple[str, ...] = (
    "ticker", "sector", "theme", "price",
    "return_1d", "return_1w", "return_1m",
    "trend_status", "risk_note", "source", "last_updated",
)

EVENT_CALENDAR_FIELDS: tuple[str, ...] = (
    "date", "time", "country", "event",
    "expected", "actual", "prior", "impact",
    "notes", "source", "last_updated",
)


class MarketPulseSchemaError(ValueError):
    """Raised when a MarketPulse row fails validation."""


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _validate_iso_date_loose(value: str, field_name: str) -> None:
    """Validate an ISO date string. Empty values are allowed (the platform
    surfaces empty cells as ``"—"``); a non-empty value MUST parse."""
    if not value:
        return
    try:
        date.fromisoformat(value)
    except Exception as exc:
        raise MarketPulseSchemaError(
            f"{field_name} must be ISO YYYY-MM-DD or empty, got {value!r}"
        ) from exc


# --------------------------------------------------------------------------- #
# Dataclasses
# --------------------------------------------------------------------------- #
@dataclass
class RegimeRow:
    """One row of the macro regime dashboard.

    ``value`` is a string so the operator can hold either numeric values
    (``"4.45"``) or qualitative ones (``"firm"``). ``status`` is the only
    enumerated read field.
    """

    panel: str
    indicator: str
    value: str
    status: str
    interpretation: str = ""
    source: str = ""
    source_file: str = ""
    last_updated: str = ""

    def __post_init__(self) -> None:
        if not self.panel:
            raise MarketPulseSchemaError("panel is required (non-empty)")
        if self.panel not in ALLOWED_REGIME_PANELS:
            raise MarketPulseSchemaError(
                f"panel must be in {sorted(ALLOWED_REGIME_PANELS)}, "
                f"got {self.panel!r}"
            )
        if not self.indicator:
            raise MarketPulseSchemaError("indicator is required (non-empty)")
        if not self.status:
            raise MarketPulseSchemaError("status is required (non-empty)")
        if self.status not in ALLOWED_REGIME_STATUS:
            raise MarketPulseSchemaError(
                f"status must be in {sorted(ALLOWED_REGIME_STATUS)}, "
                f"got {self.status!r}"
            )
        _validate_iso_date_loose(self.last_updated, "last_updated")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SectorETFRow:
    """One row of the sector ETF scoreboard.

    Returns and price are kept as strings so the operator can hold
    formatted values (``"+1.2%"``, ``"435.50"``) without forcing a type
    cast at edit time. ``trend_status`` is the only enumerated read field.
    """

    ticker: str
    sector: str
    theme: str = ""
    price: str = ""
    return_1d: str = ""
    return_1w: str = ""
    return_1m: str = ""
    trend_status: str = "N_A"
    risk_note: str = ""
    source: str = ""
    last_updated: str = ""

    def __post_init__(self) -> None:
        if not self.ticker:
            raise MarketPulseSchemaError("ticker is required (non-empty)")
        if not self.sector:
            raise MarketPulseSchemaError("sector is required (non-empty)")
        if self.trend_status not in ALLOWED_TREND_STATUS:
            raise MarketPulseSchemaError(
                f"trend_status must be in {sorted(ALLOWED_TREND_STATUS)}, "
                f"got {self.trend_status!r}"
            )
        _validate_iso_date_loose(self.last_updated, "last_updated")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EventCalendarRow:
    """One row of the economic event calendar.

    Context only — the platform never alerts on these and never auto-loads
    them. ``date`` is required (and must be ISO if non-empty); everything
    else can be blank until the print lands.
    """

    date: str
    event: str
    time: str = ""
    country: str = ""
    expected: str = ""
    actual: str = ""
    prior: str = ""
    impact: str = "N_A"
    notes: str = ""
    source: str = ""
    last_updated: str = ""

    def __post_init__(self) -> None:
        if not self.date:
            raise MarketPulseSchemaError("date is required (non-empty)")
        if not self.event:
            raise MarketPulseSchemaError("event is required (non-empty)")
        if self.impact not in ALLOWED_EVENT_IMPACT:
            raise MarketPulseSchemaError(
                f"impact must be in {sorted(ALLOWED_EVENT_IMPACT)}, "
                f"got {self.impact!r}"
            )
        _validate_iso_date_loose(self.date, "date")
        _validate_iso_date_loose(self.last_updated, "last_updated")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = [
    "ALLOWED_REGIME_PANELS", "ALLOWED_REGIME_STATUS",
    "ALLOWED_TREND_STATUS", "ALLOWED_EVENT_IMPACT",
    "REGIME_DASHBOARD_FIELDS", "SECTOR_ETF_FIELDS",
    "EVENT_CALENDAR_FIELDS",
    "RegimeRow", "SectorETFRow", "EventCalendarRow",
    "MarketPulseSchemaError",
]
