"""Sector thesis tracker schema (V6.1, read-only decision support).

Defines the ``Catalyst`` and ``EmergencyExit`` records, the allowed
enumerations, and the schema validators. Pure dataclasses — no I/O, no
network, no broker, no order execution.

The framework outputs a sector SIGNAL LABEL only (research recommendation,
e.g. ``ACCUMULATE`` / ``HOLD`` / ``REDUCE`` / ``EXIT_WATCH``). It never emits
a broker order. ``quantbot.LIVE_TRADING_ENABLED`` stays ``False``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Iterable

# --- enumerations ---------------------------------------------------------- #
ALLOWED_SECTORS: frozenset[str] = frozenset({"AI", "SEMICONDUCTOR", "ENERGY"})
ALLOWED_STATUS: frozenset[str] = frozenset(
    {"BULL", "NEUTRAL", "NEAR_THRESHOLD", "BROKEN"}
)
ALLOWED_DIRECTION: frozenset[str] = frozenset({"ABOVE", "BELOW", "QUALITATIVE"})
ALLOWED_SOURCE_TYPE: frozenset[str] = frozenset(
    {"FRED", "SEC_EDGAR", "OPTIONS_FEATURE",
     "IBKR_READONLY", "YFINANCE", "MANUAL"}
)
ALLOWED_TIER: frozenset[int] = frozenset({1, 2})
ALLOWED_EXIT_STATUS: frozenset[str] = frozenset(
    {"INACTIVE", "MONITORING", "TRIGGERED"}
)

# Decision-support signal labels (NOT broker orders).
SIGNAL_LABELS: tuple[str, ...] = (
    "ACCUMULATE", "SELECTIVE_BUY", "HOLD",
    "AVOID_NEW_BUY", "REDUCE", "EXIT_WATCH",
)

CATALYST_FIELDS: tuple[str, ...] = (
    "catalyst_id", "sector", "subsector", "catalyst_name", "tier",
    "direction", "threshold", "current_value", "status",
    "source_type", "source_detail", "last_updated",
    "action_if_broken", "notes",
)
EXIT_FIELDS: tuple[str, ...] = (
    "exit_id", "sector", "scenario", "trigger_condition",
    "current_status", "action", "source", "last_updated",
)


class SchemaError(ValueError):
    """Raised when a Catalyst or EmergencyExit record fails validation."""


# --- dataclasses ----------------------------------------------------------- #
@dataclass
class Catalyst:
    """A single sector-thesis catalyst (manually maintained or derived).

    ``threshold`` and ``current_value`` are stored as strings to support both
    numeric thresholds (e.g. ``"4.50"`` for 10y yield) and qualitative ones
    (e.g. ``"clear progress"``). The operator / upstream driver sets
    ``status`` explicitly — V6.1 does not auto-classify; that lives in the
    per-sector drivers (V6.2+).
    """

    catalyst_id: str
    sector: str
    subsector: str
    catalyst_name: str
    tier: int
    direction: str
    threshold: str
    current_value: str
    status: str
    source_type: str
    source_detail: str
    last_updated: str
    action_if_broken: str
    notes: str = ""

    def __post_init__(self) -> None:
        _validate_catalyst(self)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EmergencyExit:
    """A separately-tracked emergency-exit scenario for a sector.

    A ``TRIGGERED`` exit forces the sector signal to ``EXIT_WATCH`` regardless
    of catalyst score. This is still decision-support — NOT a broker order.
    """

    exit_id: str
    sector: str
    scenario: str
    trigger_condition: str
    current_status: str
    action: str
    source: str
    last_updated: str

    def __post_init__(self) -> None:
        _validate_exit(self)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# --- validators ------------------------------------------------------------ #
def _validate_iso_date(value: str, field_name: str) -> None:
    try:
        date.fromisoformat(value)
    except Exception as exc:
        raise SchemaError(
            f"{field_name} must be ISO YYYY-MM-DD, got {value!r}"
        ) from exc


def _validate_catalyst(c: Catalyst) -> None:
    if not c.catalyst_id:
        raise SchemaError("catalyst_id is required (non-empty)")
    if c.sector not in ALLOWED_SECTORS:
        raise SchemaError(
            f"sector must be in {sorted(ALLOWED_SECTORS)}, got {c.sector!r}"
        )
    if not c.catalyst_name:
        raise SchemaError("catalyst_name is required (non-empty)")
    if c.tier not in ALLOWED_TIER:
        raise SchemaError(f"tier must be 1 or 2, got {c.tier!r}")
    if c.direction not in ALLOWED_DIRECTION:
        raise SchemaError(
            f"direction must be in {sorted(ALLOWED_DIRECTION)}, got {c.direction!r}"
        )
    if c.status not in ALLOWED_STATUS:
        raise SchemaError(
            f"status must be in {sorted(ALLOWED_STATUS)}, got {c.status!r}"
        )
    if c.source_type not in ALLOWED_SOURCE_TYPE:
        raise SchemaError(
            f"source_type must be in {sorted(ALLOWED_SOURCE_TYPE)}, "
            f"got {c.source_type!r}"
        )
    _validate_iso_date(c.last_updated, "last_updated")


def _validate_exit(e: EmergencyExit) -> None:
    if not e.exit_id:
        raise SchemaError("exit_id is required (non-empty)")
    if e.sector not in ALLOWED_SECTORS:
        raise SchemaError(
            f"sector must be in {sorted(ALLOWED_SECTORS)}, got {e.sector!r}"
        )
    if not e.scenario:
        raise SchemaError("scenario is required (non-empty)")
    if e.current_status not in ALLOWED_EXIT_STATUS:
        raise SchemaError(
            f"current_status must be in {sorted(ALLOWED_EXIT_STATUS)}, "
            f"got {e.current_status!r}"
        )
    _validate_iso_date(e.last_updated, "last_updated")


def validate_records(
    catalysts: Iterable[Catalyst],
    exits: Iterable[EmergencyExit],
) -> None:
    """Re-validate a collection (defensive — constructor already validates)."""
    for c in catalysts:
        _validate_catalyst(c)
    for e in exits:
        _validate_exit(e)


__all__ = [
    "Catalyst", "EmergencyExit", "SchemaError",
    "ALLOWED_SECTORS", "ALLOWED_STATUS", "ALLOWED_DIRECTION",
    "ALLOWED_SOURCE_TYPE", "ALLOWED_TIER", "ALLOWED_EXIT_STATUS",
    "SIGNAL_LABELS", "CATALYST_FIELDS", "EXIT_FIELDS",
    "validate_records",
]
