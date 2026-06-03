"""V7.5 Company Detail schema — single dataclass, no enums.

The view is a *composition* of existing typed records — it holds lists of
``Catalyst`` / ``Change`` / ``EventAnnotation`` / ``CompanyLedgerRow``
straight through without re-wrapping. Every label field is a free string
because the source enums are already validated by the producing modules.

No I/O, no scoring, no network. ``quantbot.LIVE_TRADING_ENABLED`` stays
``False``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from ..sector_tracker.change_log import Change, EventAnnotation
from ..sector_tracker.company_ledger import CompanyLedgerRow
from ..sector_tracker.schema import Catalyst

COMPANY_DETAIL_FIELDS: tuple[str, ...] = (
    "ticker", "company_or_label", "sector", "theme",
    "current_company_read", "why_short", "main_risk_short",
    "linked_catalysts",
    "canonical_sector_signal", "company_derived_sector_read",
    "position_present", "quantity", "market_value",
    "portfolio_weight_pct", "average_cost", "unrealized_pnl",
    "protection_label", "porttech_label",
    "historical_company_reads", "current_catalysts",
    "recent_changes", "event_annotations",
    "data_gap_notes",
    "as_of",
)


class CompanyDetailSchemaError(ValueError):
    """Raised when a CompanyDetailView fails validation."""


@dataclass
class CompanyDetailView:
    """A complete read-only drill-down view of one ticker.

    Composition of existing surfaces. Constructor enforces only that the
    ticker is non-empty and the four list-typed collections are actually
    lists — every other field is free-text.
    """

    ticker: str
    company_or_label: str = ""
    sector: str = ""
    theme: str = ""
    current_company_read: str = ""
    why_short: str = ""
    main_risk_short: str = ""
    linked_catalysts: list[str] = field(default_factory=list)
    canonical_sector_signal: str = ""
    company_derived_sector_read: str = ""
    position_present: bool = False
    quantity: str = ""
    market_value: str = ""
    portfolio_weight_pct: str = ""
    average_cost: str = ""
    unrealized_pnl: str = ""
    protection_label: str = ""
    porttech_label: str = ""
    historical_company_reads: list[CompanyLedgerRow] = field(
        default_factory=list,
    )
    current_catalysts: list[Catalyst] = field(default_factory=list)
    recent_changes: list[Change] = field(default_factory=list)
    event_annotations: list[EventAnnotation] = field(
        default_factory=list,
    )
    data_gap_notes: list[str] = field(default_factory=list)
    as_of: str = ""

    def __post_init__(self) -> None:
        if not self.ticker:
            raise CompanyDetailSchemaError(
                "ticker is required (non-empty)"
            )
        for fld in ("linked_catalysts", "historical_company_reads",
                    "current_catalysts", "recent_changes",
                    "event_annotations", "data_gap_notes"):
            v = getattr(self, fld)
            if not isinstance(v, list):
                raise CompanyDetailSchemaError(
                    f"{fld} must be a list, got {type(v).__name__}"
                )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = [
    "COMPANY_DETAIL_FIELDS",
    "CompanyDetailView", "CompanyDetailSchemaError",
]
