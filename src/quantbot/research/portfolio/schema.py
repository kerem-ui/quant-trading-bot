"""V7.1 portfolio schema — two dataclasses, two enums.

All fields are typed strings (except where enumerated) so the operator can
edit the CSV by hand. Numeric panels (market value, P&L, weights) parse
the string at *render* time — when any field is unparseable the platform
falls back to ``"n/a"`` rather than show a bad number.

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
ALLOWED_ASSET_TYPE: frozenset[str] = frozenset({
    "STOCK", "ETF", "OPTION", "FUTURE", "BOND",
    "CASH", "OTHER", "N_A",
})

# Operator-curated, deliberately small. Dividends and fees are tracked as
# their own "sides" so the transaction log captures every cash event.
ALLOWED_TRANSACTION_SIDE: frozenset[str] = frozenset({
    "BUY", "SELL", "DIVIDEND", "FEE", "TRANSFER_IN",
    "TRANSFER_OUT", "OTHER",
})

POSITION_FIELDS: tuple[str, ...] = (
    "as_of", "account", "ticker", "company_name", "asset_type",
    "quantity", "average_cost", "last_price", "market_value",
    "unrealized_pnl", "realized_pnl", "currency",
    "sector", "theme", "source", "notes",
)

TRANSACTION_FIELDS: tuple[str, ...] = (
    "date", "account", "ticker", "side",
    "quantity", "price", "fees", "currency",
    "reason", "linked_thesis", "source", "notes",
)


class PortfolioSchemaError(ValueError):
    """Raised when a portfolio row fails validation."""


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _validate_iso_date_loose(value: str, field_name: str) -> None:
    """Validate an ISO date string. Empty values are allowed."""
    if not value:
        return
    try:
        date.fromisoformat(value)
    except Exception as exc:
        raise PortfolioSchemaError(
            f"{field_name} must be ISO YYYY-MM-DD or empty, got {value!r}"
        ) from exc


# --------------------------------------------------------------------------- #
# Dataclasses
# --------------------------------------------------------------------------- #
@dataclass
class PositionRow:
    """One position snapshot as of a specific date / account / ticker.

    Numeric fields stay typed as strings so the operator can hold raw
    values, formatted values, or blanks. The platform parses them at
    render time and treats unparseable fields as ``"n/a"`` rather than
    inventing a number.
    """

    as_of: str
    account: str
    ticker: str
    company_name: str = ""
    asset_type: str = "N_A"
    quantity: str = ""
    average_cost: str = ""
    last_price: str = ""
    market_value: str = ""
    unrealized_pnl: str = ""
    realized_pnl: str = ""
    currency: str = "USD"
    sector: str = ""
    theme: str = ""
    source: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.as_of:
            raise PortfolioSchemaError("as_of is required (non-empty)")
        if not self.account:
            raise PortfolioSchemaError("account is required (non-empty)")
        if not self.ticker:
            raise PortfolioSchemaError("ticker is required (non-empty)")
        if self.asset_type not in ALLOWED_ASSET_TYPE:
            raise PortfolioSchemaError(
                f"asset_type must be in {sorted(ALLOWED_ASSET_TYPE)}, "
                f"got {self.asset_type!r}"
            )
        _validate_iso_date_loose(self.as_of, "as_of")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TransactionRow:
    """One executed trade / cash event.

    Includes BUY / SELL / DIVIDEND / FEE / TRANSFER_IN / TRANSFER_OUT /
    OTHER. The platform never *places* a transaction — it only reads what
    the operator has manually recorded. ``linked_thesis`` is free text so
    the operator can connect a trade to a V6 catalyst / sector signal /
    research note for audit purposes.
    """

    date: str
    account: str
    ticker: str
    side: str
    quantity: str = ""
    price: str = ""
    fees: str = ""
    currency: str = "USD"
    reason: str = ""
    linked_thesis: str = ""
    source: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.date:
            raise PortfolioSchemaError("date is required (non-empty)")
        if not self.account:
            raise PortfolioSchemaError("account is required (non-empty)")
        if not self.ticker:
            raise PortfolioSchemaError("ticker is required (non-empty)")
        if not self.side:
            raise PortfolioSchemaError("side is required (non-empty)")
        if self.side not in ALLOWED_TRANSACTION_SIDE:
            raise PortfolioSchemaError(
                f"side must be in {sorted(ALLOWED_TRANSACTION_SIDE)}, "
                f"got {self.side!r}"
            )
        _validate_iso_date_loose(self.date, "date")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = [
    "ALLOWED_ASSET_TYPE", "ALLOWED_TRANSACTION_SIDE",
    "POSITION_FIELDS", "TRANSACTION_FIELDS",
    "PositionRow", "TransactionRow", "PortfolioSchemaError",
]
