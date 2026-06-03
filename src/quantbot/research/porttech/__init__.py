"""V7.4 — PortTech portfolio brain (read-only, research-only).

Categorical join of V7.1 positions × V6.7 company ledger × V6.6.2 canonical
sector signal × V6.8 company-derived aggregation × V7.7 protection labels
into one :class:`PortTechRow` per investable position.

Each row carries a categorical ``porttech_label`` from a small enum
(``ADD / HOLD / TRIM / WATCH / EXIT_WATCH / DATA_GAP``). The label is a
**research prompt** the operator reads, not an order instruction.

**Never a trading signal. Never a buy/sell instruction. Never an order
placement.** Nothing here imports a broker, an IBKR API, a ThetaData feed,
or any live-market resource. ``quantbot.LIVE_TRADING_ENABLED`` stays
``False``.
"""

from .engine import (
    BASE_RECOMMENDATION,
    CONCENTRATION_CAP_PCT,
    LABEL_PRIORITY,
    derive_porttech_rows,
)
from .schema import (
    ALLOWED_PORTTECH_LABEL,
    PORTTECH_ROW_FIELDS,
    PortTechRow,
    PortTechSchemaError,
)

__all__ = [
    # enums + fields
    "ALLOWED_PORTTECH_LABEL", "PORTTECH_ROW_FIELDS",
    # schema
    "PortTechRow", "PortTechSchemaError",
    # engine + constants
    "BASE_RECOMMENDATION",
    "CONCENTRATION_CAP_PCT",
    "LABEL_PRIORITY",
    "derive_porttech_rows",
]
