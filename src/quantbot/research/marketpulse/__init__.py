"""V7.8 — MarketPulse macro shell (read-only, research-only).

A small typed substrate for a manually-curated macro / market-pulse view.
Three CSV-backed surfaces:

  * regime dashboard — rates / inflation / labor / growth / volatility /
    credit / risk-on-off panels
  * sector ETF scoreboard — compact static snapshot (no live price fetch)
  * economic event calendar — context only, no scheduler

The schema is deliberately *strings + small enums* so the operator can edit
the CSVs by hand. Nothing here fetches the network. Nothing imports a
broker, an IBKR API, a ThetaData feed, or any live-market resource. The V6
sector tracker / company ledger / aggregation / signal-log stack is not
touched.

``quantbot.LIVE_TRADING_ENABLED`` stays ``False``.
"""

from .readers import (
    DEFAULT_EVENT_CALENDAR_FILE,
    DEFAULT_MARKETPULSE_DIR,
    DEFAULT_REGIME_DASHBOARD_FILE,
    DEFAULT_SECTOR_ETF_SCOREBOARD_FILE,
    EVENT_CALENDAR_IDEMPOTENCE_KEY,
    REGIME_IDEMPOTENCE_KEY,
    SECTOR_ETF_IDEMPOTENCE_KEY,
    append_event_calendar_rows,
    append_regime_rows,
    append_sector_etf_rows,
    ensure_event_calendar_header,
    ensure_regime_dashboard_header,
    ensure_sector_etf_scoreboard_header,
    load_event_calendar,
    load_regime_dashboard,
    load_sector_etf_scoreboard,
)
from .schema import (
    ALLOWED_EVENT_IMPACT,
    ALLOWED_REGIME_PANELS,
    ALLOWED_REGIME_STATUS,
    ALLOWED_TREND_STATUS,
    EVENT_CALENDAR_FIELDS,
    EventCalendarRow,
    MarketPulseSchemaError,
    REGIME_DASHBOARD_FIELDS,
    RegimeRow,
    SECTOR_ETF_FIELDS,
    SectorETFRow,
)

__all__ = [
    # enums + field tuples
    "ALLOWED_REGIME_PANELS", "ALLOWED_REGIME_STATUS",
    "ALLOWED_TREND_STATUS", "ALLOWED_EVENT_IMPACT",
    "REGIME_DASHBOARD_FIELDS", "SECTOR_ETF_FIELDS",
    "EVENT_CALENDAR_FIELDS",
    # schema
    "RegimeRow", "SectorETFRow", "EventCalendarRow",
    "MarketPulseSchemaError",
    # I/O
    "load_regime_dashboard", "load_sector_etf_scoreboard",
    "load_event_calendar",
    "ensure_regime_dashboard_header", "ensure_sector_etf_scoreboard_header",
    "ensure_event_calendar_header",
    # V7.8.1 append helpers
    "append_regime_rows", "append_sector_etf_rows",
    "append_event_calendar_rows",
    "REGIME_IDEMPOTENCE_KEY", "SECTOR_ETF_IDEMPOTENCE_KEY",
    "EVENT_CALENDAR_IDEMPOTENCE_KEY",
    # default paths
    "DEFAULT_MARKETPULSE_DIR",
    "DEFAULT_REGIME_DASHBOARD_FILE", "DEFAULT_SECTOR_ETF_SCOREBOARD_FILE",
    "DEFAULT_EVENT_CALENDAR_FILE",
]
