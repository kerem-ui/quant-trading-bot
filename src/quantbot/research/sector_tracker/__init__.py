"""V6.1 sector thesis tracker — read-only decision-support framework.

Combines catalysts (manual or driver-refreshed) and emergency-exit scenarios
into a transparent tier-weighted sector score that maps to a research signal
label (``ACCUMULATE`` / ``SELECTIVE_BUY`` / ``HOLD`` / ``AVOID_NEW_BUY`` /
``REDUCE`` / ``EXIT_WATCH``).

**This module is decision-support only.** It produces no broker orders, no
trading signals into a strategy, and no fills. ``quantbot.LIVE_TRADING_ENABLED``
stays ``False``; nothing here imports a broker, IBKR API, or order module.

V6.1 ships the framework only. Per-sector data drivers (semiconductor / AI /
energy) and the Streamlit dashboard arrive in V6.2 → V6.5. A separate
validation phase (V6.6) will test whether these signal labels carry any
forward-return / drawdown-discipline edge — until then nothing here is a
tradable signal.
"""

from .catalysts import load_catalysts, save_catalysts
from .company_aggregation import (
    AGGREGATION_FIELDS,
    ALLOWED_COMPANY_DERIVED_READ,
    CompanyAggregationSchemaError,
    SectorAggregationRow,
    TOP_TICKERS_CAP,
    aggregate_sector,
    append_sector_aggregation_rows,
    build_sector_aggregation_rows,
    derive_company_derived_read,
    ensure_sector_aggregation_header,
    load_latest_aggregation_per_sector,
    load_sector_aggregation,
)
from .company_ledger import (
    ALLOWED_READ,
    COMPANY_LEDGER_UNIVERSE,
    LEDGER_FIELDS,
    CompanyLedgerRow,
    CompanyLedgerSchemaError,
    append_company_ledger_rows,
    build_company_ledger_rows,
    derive_read_for_company,
    ensure_company_ledger_header,
    load_company_ledger,
    short_phrases_for_company,
)
from .change_log import (
    CHANGE_LOG_FIELDS,
    EVENT_ANNOTATION_FIELDS,
    Change,
    ChangeLogSchemaError,
    EventAnnotation,
    append_changes,
    append_event_annotations,
    baseline_change,
    compute_catalyst_diff,
    compute_exit_diff,
    ensure_change_log_header,
    ensure_event_annotations_header,
    load_change_log,
    load_event_annotations,
)
from .emergency_exits import load_exits, save_exits
from .ledger_audit import (
    MIN_AGG_RUNS_FOR_BACKTEST,
    MIN_CALENDAR_DAYS_FOR_BACKTEST,
    MIN_RUNS_PER_SECTOR_FOR_BACKTEST,
    LedgerAuditSchemaError,
    LedgerAuditSummary,
    audit_ledger_substrate,
    render_audit_markdown,
)
from .report_writer import render_markdown, write_markdown
from .sector_signal_log import (
    SECTOR_SIGNAL_LOG_FIELDS,
    SectorSignalLogRow,
    SectorSignalLogSchemaError,
    append_sector_signal_log_rows,
    build_sector_signal_log_rows,
    ensure_sector_signal_log_header,
    load_sector_signal_log,
    row_from_score,
)
from .schema import (
    ALLOWED_DIRECTION,
    ALLOWED_EXIT_STATUS,
    ALLOWED_SECTORS,
    ALLOWED_SOURCE_TYPE,
    ALLOWED_STATUS,
    ALLOWED_TIER,
    CATALYST_FIELDS,
    Catalyst,
    EXIT_FIELDS,
    EmergencyExit,
    SIGNAL_LABELS,
    SchemaError,
    validate_records,
)
from .scoring import (
    SIGNAL_THRESHOLDS,
    STATUS_VALUE,
    TIER_WEIGHT,
    SectorScore,
    score_sector,
    signal_from_normalized,
)
from .sector_builder import SectorReport, build_all_sectors, build_sector_report

__all__ = [
    # schema
    "Catalyst", "EmergencyExit", "SchemaError",
    "ALLOWED_SECTORS", "ALLOWED_STATUS", "ALLOWED_DIRECTION",
    "ALLOWED_SOURCE_TYPE", "ALLOWED_TIER", "ALLOWED_EXIT_STATUS",
    "SIGNAL_LABELS", "CATALYST_FIELDS", "EXIT_FIELDS", "validate_records",
    # scoring
    "score_sector", "SectorScore", "signal_from_normalized",
    "TIER_WEIGHT", "STATUS_VALUE", "SIGNAL_THRESHOLDS",
    # I/O
    "load_catalysts", "save_catalysts", "load_exits", "save_exits",
    # orchestrator + report
    "build_sector_report", "build_all_sectors", "SectorReport",
    "render_markdown", "write_markdown",
    # V6.6 change log + annotations
    "Change", "EventAnnotation", "ChangeLogSchemaError",
    "CHANGE_LOG_FIELDS", "EVENT_ANNOTATION_FIELDS",
    "load_change_log", "append_changes", "ensure_change_log_header",
    "load_event_annotations", "ensure_event_annotations_header",
    "append_event_annotations",
    "compute_catalyst_diff", "compute_exit_diff", "baseline_change",
    # V6.7 company signal ledger
    "CompanyLedgerRow", "CompanyLedgerSchemaError",
    "ALLOWED_READ", "LEDGER_FIELDS", "COMPANY_LEDGER_UNIVERSE",
    "derive_read_for_company", "short_phrases_for_company",
    "build_company_ledger_rows",
    "load_company_ledger", "ensure_company_ledger_header",
    "append_company_ledger_rows",
    # V6.8 company-derived sector aggregation
    "SectorAggregationRow", "CompanyAggregationSchemaError",
    "ALLOWED_COMPANY_DERIVED_READ", "AGGREGATION_FIELDS", "TOP_TICKERS_CAP",
    "derive_company_derived_read", "aggregate_sector",
    "build_sector_aggregation_rows",
    "load_sector_aggregation", "load_latest_aggregation_per_sector",
    "ensure_sector_aggregation_header",
    "append_sector_aggregation_rows",
    # V6.9 backtest substrate audit (planning-only)
    "LedgerAuditSummary", "LedgerAuditSchemaError",
    "MIN_RUNS_PER_SECTOR_FOR_BACKTEST", "MIN_AGG_RUNS_FOR_BACKTEST",
    "MIN_CALENDAR_DAYS_FOR_BACKTEST",
    "audit_ledger_substrate", "render_audit_markdown",
    # V6.6.2 canonical sector signal log
    "SECTOR_SIGNAL_LOG_FIELDS",
    "SectorSignalLogRow", "SectorSignalLogSchemaError",
    "row_from_score", "build_sector_signal_log_rows",
    "load_sector_signal_log", "ensure_sector_signal_log_header",
    "append_sector_signal_log_rows",
]
