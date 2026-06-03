"""V7.5 — Company Detail / Stock Intelligence (read-only, research-only).

A pure-derivation join page that explains why a given ticker has its
current research read, PortTech label, and Protection label. It composes
every V6 / V7 surface that already knows something about the company:

  * V6.7 company signal ledger (current and historical reads)
  * V6.6.2 canonical sector signal log
  * V6.8 company-derived sector aggregation
  * V7.1 portfolio positions
  * V7.7 protection labels (per-position)
  * V7.4 PortTech labels (per-position)
  * V6.6 change log (filtered by linked catalysts / ticker)
  * V6.6.1 event annotations (filtered by ticker / linked catalysts)
  * Per-sector catalyst CSVs (linked catalysts' current values)

The output is a single :class:`CompanyDetailView` dataclass surface that
the Streamlit page renders in nine sections (ticker header → position →
why/risk → catalysts → history → recent changes → annotations → data
gaps → footer).

**Never a trading signal. Never a buy/sell instruction. Never an order
placement.** No broker, no IBKR, no live market feed. The page reads
existing CSVs and renders categorical labels.
``quantbot.LIVE_TRADING_ENABLED`` stays ``False``.
"""

from .engine import (
    build_company_detail_view,
    ticker_universe,
)
from .fundamentals import (
    DEFAULT_COMPANYFACTS_DIR,
    DEFAULT_SEC_CACHE_DIR,
    DEFAULT_TICKER_MAP_FILE,
    DEI_CANDIDATES,
    FUNDAMENTALS_FIELDS,
    FundamentalsSnapshot,
    GAAP_CANDIDATES,
    companyfacts_path_for_ticker,
    compute_fundamentals_snapshot,
    load_companyfacts_json,
    load_ticker_to_cik_map,
)
from .price_cache import (
    DEFAULT_PRICE_CACHE_DIR,
    PriceSeries,
    load_price_series,
)
from .schema import (
    COMPANY_DETAIL_FIELDS,
    CompanyDetailSchemaError,
    CompanyDetailView,
)
from .technicals import (
    DRAWDOWN_LOOKBACK,
    RETURN_1M_DAYS,
    RETURN_1W_DAYS,
    RETURN_1Y_DAYS,
    RETURN_3M_DAYS,
    RSI_PERIOD,
    SMA_LONG_PERIOD,
    SMA_SHORT_PERIOD,
    TECHNICAL_SNAPSHOT_FIELDS,
    TechnicalSnapshot,
    compute_distance_to_sma_pct,
    compute_drawdown_from_high_pct,
    compute_return_pct,
    compute_rsi,
    compute_sma,
    compute_technical_snapshot,
)

__all__ = [
    # schema
    "CompanyDetailView", "CompanyDetailSchemaError",
    "COMPANY_DETAIL_FIELDS",
    # engine
    "build_company_detail_view", "ticker_universe",
    # V7.5.1 price cache
    "DEFAULT_PRICE_CACHE_DIR",
    "PriceSeries", "load_price_series",
    # V7.5.1 technicals
    "TechnicalSnapshot", "TECHNICAL_SNAPSHOT_FIELDS",
    "RSI_PERIOD", "SMA_SHORT_PERIOD", "SMA_LONG_PERIOD",
    "RETURN_1W_DAYS", "RETURN_1M_DAYS", "RETURN_3M_DAYS",
    "RETURN_1Y_DAYS", "DRAWDOWN_LOOKBACK",
    "compute_rsi", "compute_sma", "compute_return_pct",
    "compute_drawdown_from_high_pct", "compute_distance_to_sma_pct",
    "compute_technical_snapshot",
    # V7.5.2 fundamentals
    "DEFAULT_SEC_CACHE_DIR", "DEFAULT_COMPANYFACTS_DIR",
    "DEFAULT_TICKER_MAP_FILE",
    "GAAP_CANDIDATES", "DEI_CANDIDATES", "FUNDAMENTALS_FIELDS",
    "FundamentalsSnapshot",
    "load_ticker_to_cik_map", "load_companyfacts_json",
    "companyfacts_path_for_ticker",
    "compute_fundamentals_snapshot",
]
