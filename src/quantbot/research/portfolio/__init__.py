"""V7.1 — Read-only portfolio CSV format (research-only, local-only).

Manually-curated portfolio substrate:

  * ``data/portfolio/positions.csv``  — one row per (as_of, account, ticker)
  * ``data/portfolio/transactions.csv`` — one row per executed trade

Both files are **stale-as-entered**. The platform never fetches a live
price, never connects to a broker, never executes an order. V7.1 is the
schema + reader + populate-helper substrate; future V7.2 may layer a
strictly read-only IBKR pull on top of the same schema (write-only by the
sync script, read-only from the platform's perspective).

``quantbot.LIVE_TRADING_ENABLED`` stays ``False``.
"""

from .readers import (
    DEFAULT_PORTFOLIO_DIR,
    DEFAULT_POSITIONS_FILE,
    DEFAULT_TRANSACTIONS_FILE,
    POSITIONS_IDEMPOTENCE_KEY,
    TRANSACTIONS_IDEMPOTENCE_KEY,
    append_position_rows,
    append_transaction_rows,
    ensure_positions_header,
    ensure_transactions_header,
    load_positions,
    load_transactions,
)
from .schema import (
    ALLOWED_ASSET_TYPE,
    ALLOWED_TRANSACTION_SIDE,
    POSITION_FIELDS,
    PortfolioSchemaError,
    PositionRow,
    TRANSACTION_FIELDS,
    TransactionRow,
)

__all__ = [
    # enums + fields
    "ALLOWED_ASSET_TYPE", "ALLOWED_TRANSACTION_SIDE",
    "POSITION_FIELDS", "TRANSACTION_FIELDS",
    # schema
    "PositionRow", "TransactionRow", "PortfolioSchemaError",
    # I/O
    "load_positions", "load_transactions",
    "ensure_positions_header", "ensure_transactions_header",
    "append_position_rows", "append_transaction_rows",
    "POSITIONS_IDEMPOTENCE_KEY", "TRANSACTIONS_IDEMPOTENCE_KEY",
    # default paths
    "DEFAULT_PORTFOLIO_DIR",
    "DEFAULT_POSITIONS_FILE", "DEFAULT_TRANSACTIONS_FILE",
]
