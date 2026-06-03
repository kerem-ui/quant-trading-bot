"""V7.7 — Protection risk surface (read-only, research-only).

Categorical join of the V7.1 portfolio positions with the V6 sector / V6.7
company-ledger / V6.6.2 sector-signal-log / V6.8 company-derived
aggregation surfaces. Produces one :class:`ProtectionRow` per position
with four pre-declared categorical labels:

  * ``concentration_label`` — position-weight-based
  * ``sector_risk_label``  — canonical V6.1 sector signal driven
  * ``company_risk_label`` — V6.7 company read driven
  * ``protection_label``   — worst-bucket headline across the three

**Never a trading signal. Never an order. Never a hedge execution.** This
module produces only research labels; nothing here imports a broker, an
IBKR API, a ThetaData feed, or any live-market resource.

``quantbot.LIVE_TRADING_ENABLED`` stays ``False``.
"""

from .engine import (
    CONCENTRATION_THRESHOLD_PCT,
    LABEL_PRIORITY,
    WATCH_CONCENTRATION_THRESHOLD_PCT,
    derive_protection_rows,
    worst_label,
)
from .schema import (
    ALLOWED_PROTECTION_LABEL,
    PROTECTION_ROW_FIELDS,
    ProtectionRow,
    ProtectionSchemaError,
)

__all__ = [
    # enums + fields
    "ALLOWED_PROTECTION_LABEL", "PROTECTION_ROW_FIELDS",
    # schema
    "ProtectionRow", "ProtectionSchemaError",
    # engine + constants
    "CONCENTRATION_THRESHOLD_PCT",
    "WATCH_CONCENTRATION_THRESHOLD_PCT",
    "LABEL_PRIORITY",
    "derive_protection_rows", "worst_label",
]
