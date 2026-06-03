"""V7.0 — Local Streamlit platform shell (research-only, read-only).

Run with:

    python -m streamlit run apps/portfolio_platform.py

This is a **local browser application**, not a public website. It re-uses
the V6 sector-tracker artefacts on disk and surfaces them inside a broader
platform shell with sidebar navigation. Pages that the project does not yet
implement (Portfolio, PortTech, MarketPulse, Daily Setup, Protection,
Transactions) render as **explicit empty-state skeletons** that document
the intended future structure without doing anything live.

Hard guarantees (asserted by tests):

  * The module imports cleanly without streamlit being touched at import
    time (streamlit is imported inside ``render()``).
  * Nothing here imports a broker, the IBKR API, an order module, a live
    market feed, or any network resource.
  * The module performs **zero writes** to disk. No write-mode file
    handles, no Path write helpers, no CSV writers — the V6 CSVs are
    read with the existing ``load_*`` helpers and never modified.
  * ``quantbot.LIVE_TRADING_ENABLED`` stays ``False``.

The existing V6 dashboard at ``apps/sector_thesis_dashboard.py`` is
**unchanged** and remains the canonical sector-research surface. This
platform's "Sector Thesis" page is a compact summary that links back to
the full dashboard.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from quantbot.research.marketpulse import (
    DEFAULT_EVENT_CALENDAR_FILE,
    DEFAULT_MARKETPULSE_DIR,
    DEFAULT_REGIME_DASHBOARD_FILE,
    DEFAULT_SECTOR_ETF_SCOREBOARD_FILE,
    EventCalendarRow,
    RegimeRow,
    SectorETFRow,
    load_event_calendar,
    load_regime_dashboard,
    load_sector_etf_scoreboard,
)
from quantbot.research.portfolio import (
    DEFAULT_PORTFOLIO_DIR,
    DEFAULT_POSITIONS_FILE,
    DEFAULT_TRANSACTIONS_FILE,
    PositionRow,
    TransactionRow,
    load_positions,
    load_transactions,
)
from quantbot.research.porttech import (
    ALLOWED_PORTTECH_LABEL,
    CONCENTRATION_CAP_PCT,
    PortTechRow,
    derive_porttech_rows,
)
from quantbot.research.protection import (
    ALLOWED_PROTECTION_LABEL,
    CONCENTRATION_THRESHOLD_PCT,
    LABEL_PRIORITY,
    ProtectionRow,
    WATCH_CONCENTRATION_THRESHOLD_PCT,
    derive_protection_rows,
)
from quantbot.research.company_detail import (
    CompanyDetailView,
    DEFAULT_COMPANYFACTS_DIR,
    DEFAULT_PRICE_CACHE_DIR,
    DEFAULT_TICKER_MAP_FILE,
    FundamentalsSnapshot,
    PriceSeries,
    TechnicalSnapshot,
    build_company_detail_view,
    companyfacts_path_for_ticker,
    compute_fundamentals_snapshot,
    compute_technical_snapshot,
    load_companyfacts_json,
    load_price_series,
    ticker_universe,
)
from quantbot.research.sector_tracker import (
    Catalyst,
    Change,
    CompanyLedgerRow,
    EmergencyExit,
    EventAnnotation,
    SectorAggregationRow,
    SectorScore,
    SectorSignalLogRow,
    load_catalysts,
    load_change_log,
    load_company_ledger,
    load_event_annotations,
    load_exits,
    load_sector_aggregation,
    load_sector_signal_log,
    score_sector,
)

# --------------------------------------------------------------------------- #
# Paths — all reads only. The platform never writes any of these.
# --------------------------------------------------------------------------- #
DATA_DIR = ROOT / "data" / "research" / "sector_tracker"
REPORT_ROOT = ROOT / "reports"
RESEARCH_REPORT_DIR = REPORT_ROOT / "research"

LEDGER_PATH = DATA_DIR / "company_signal_ledger.csv"
AGGREGATION_PATH = DATA_DIR / "company_sector_aggregation.csv"
SIGNAL_LOG_PATH = DATA_DIR / "sector_signal_log.csv"
CHANGE_LOG_PATH = DATA_DIR / "change_log.csv"
ANNOTATIONS_PATH = DATA_DIR / "event_annotations.csv"

# Optional transactions file. The platform never creates this; the page
# shows a friendly empty state when it is absent.
DEFAULT_TRANSACTIONS_PATH = ROOT / "data" / "portfolio" / "transactions.csv"

# Sector tracker layout (mirrors apps/sector_thesis_dashboard.SECTOR_FILES;
# duplicated here to keep this module's surface self-contained — copying a
# 3-entry dict is cheaper than depending on the dashboard module).
SECTORS: tuple[str, ...] = ("SEMICONDUCTOR", "AI", "ENERGY")
SECTOR_FILES: dict[str, dict[str, str]] = {
    "SEMICONDUCTOR": {
        "catalysts": "semiconductor_thesis_tracker.csv",
        "exits": "semiconductor_emergency_exits.csv",
        "report": "semiconductor_signal.md",
    },
    "AI": {
        "catalysts": "ai_thesis_tracker.csv",
        "exits": "ai_emergency_exits.csv",
        "report": "ai_signal.md",
    },
    "ENERGY": {
        "catalysts": "energy_thesis_tracker.csv",
        "exits": "energy_emergency_exits.csv",
        "report": "energy_signal.md",
    },
}

# --------------------------------------------------------------------------- #
# Public surface
# --------------------------------------------------------------------------- #
PAGES: tuple[str, ...] = (
    "Home",
    "Portfolio",
    "PortTech",
    "Sector Thesis",
    "Company Ledger",
    "Company Detail",
    "MarketPulse",
    "Daily Setup",
    "Protection",
    "Transactions",
    "Reports",
    "Glossary",
    "Settings / Guardrails",
)

DISCLAIMER = (
    "Research-only platform. Not a trading signal. Not investment advice. "
    "No order execution. LIVE_TRADING_ENABLED remains False."
)

# Static glossary — additive list; pre-declared so tests can assert that
# every required term is present without parsing rendered HTML.
GLOSSARY: tuple[dict[str, str], ...] = (
    {"term": "Canonical signal", "definition": (
        "The V6.1 sector-thesis signal label "
        "(ACCUMULATE / SELECTIVE_BUY / HOLD / AVOID_NEW_BUY / REDUCE / "
        "EXIT_WATCH) derived from tier-weighted catalyst statuses. Always "
        "a research label, never an order.")},
    {"term": "Company-derived read", "definition": (
        "The V6.8 categorical roll-up per sector (BULL / MIXED / NEUTRAL "
        "/ CAUTION / BROKEN / TRACKED_HEAVY / N_A) computed from the V6.7 "
        "company signal ledger. Audit view only.")},
    {"term": "Catalyst", "definition": (
        "A pre-declared sector-thesis driver (e.g. NVDA revenue YoY) "
        "tracked manually or via SEC EDGAR. Each catalyst carries a "
        "status (BULL / NEUTRAL / NEAR_THRESHOLD / BROKEN) and a tier "
        "weight.")},
    {"term": "Emergency exit", "definition": (
        "A pre-declared scenario that, when TRIGGERED, forces the "
        "canonical sector signal to EXIT_WATCH irrespective of catalyst "
        "scoring. Decision-support only.")},
    {"term": "Change log", "definition": (
        "Append-only V6.6 record of every (record, field) difference "
        "between consecutive refresh snapshots. Used for audit and "
        "context — never as a trading signal.")},
    {"term": "Event annotation", "definition": (
        "Operator-curated free-text note attached to a catalyst, exit, "
        "sector, or company signal. Context only; never feeds scoring.")},
    {"term": "Sector aggregation", "definition": (
        "V6.8 company-derived sector roll-up — one row per (run_id, "
        "sector) summarising the distribution of company reads. Audit "
        "view, parallel to the canonical sector signal.")},
    {"term": "Drawdown", "definition": (
        "Peak-to-trough loss of a portfolio or strategy over a window. "
        "Used as a risk control input, not as a forecast.")},
    {"term": "Risk-on / Risk-off", "definition": (
        "Market-regime shorthand for periods favouring (or rejecting) "
        "growth / cyclical assets. The platform does not currently "
        "compute this; the MarketPulse page is a future skeleton.")},
    {"term": "Macro regime", "definition": (
        "Pre-declared classification of the prevailing growth / "
        "inflation / rates environment. V7.8 (planned) would expose a "
        "read-only macro dashboard; V7.0 ships a placeholder.")},
    {"term": "Exposure", "definition": (
        "Gross or net portfolio weight allocated to a sector, theme, or "
        "factor. The V7.0 Portfolio page is a placeholder; real exposure "
        "tracking is reserved for V7.1.")},
    {"term": "P&L", "definition": (
        "Profit and loss — realised (closed positions) and unrealised "
        "(open positions). Placeholder in V7.0; real P&L reporting is "
        "future work and remains research-only when it lands.")},
)


# --------------------------------------------------------------------------- #
# Pure helpers (testable without streamlit)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class PlatformStatus:
    """High-level platform state derived from on-disk artefact presence.

    Pure data: no rendering, no streamlit. Used by the Home page (and by
    tests) to decide which sections show "available" vs. "empty state".
    """

    has_ledger: bool
    has_aggregation: bool
    has_signal_log: bool
    has_change_log: bool
    has_annotations: bool
    has_reports_root: bool
    n_company_ledger_rows: int
    n_aggregation_rows: int
    n_signal_log_rows: int
    sectors_with_catalysts: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SectorSummary:
    """Compact per-sector roll-up used by the Sector Thesis page.

    Derived from already-loaded V6.1 ``SectorScore`` data; never re-scores.
    """

    sector: str
    signal: str
    normalized_score: float
    n_catalysts: int
    n_bull: int
    n_broken: int
    n_near_threshold: int
    triggered_exits: list[str] = field(default_factory=list)


def collect_platform_status(
    data_dir: Path | str = DATA_DIR,
    report_root: Path | str = REPORT_ROOT,
) -> PlatformStatus:
    """Inspect the read-only artefact tree and return a status snapshot.

    Pure: no writes, no network. Sectors missing their catalyst CSV are
    silently omitted from ``sectors_with_catalysts``.
    """
    ddir = Path(data_dir)
    rroot = Path(report_root)

    sectors_with_cats: list[str] = []
    for sec in SECTORS:
        if (ddir / SECTOR_FILES[sec]["catalysts"]).is_file():
            sectors_with_cats.append(sec)

    n_ledger = (len(load_company_ledger(ddir / "company_signal_ledger.csv"))
                if (ddir / "company_signal_ledger.csv").is_file() else 0)
    n_agg = (len(load_sector_aggregation(
        ddir / "company_sector_aggregation.csv"))
        if (ddir / "company_sector_aggregation.csv").is_file() else 0)
    n_sl = (len(load_sector_signal_log(ddir / "sector_signal_log.csv"))
            if (ddir / "sector_signal_log.csv").is_file() else 0)

    return PlatformStatus(
        has_ledger=(ddir / "company_signal_ledger.csv").is_file(),
        has_aggregation=(
            ddir / "company_sector_aggregation.csv"
        ).is_file(),
        has_signal_log=(ddir / "sector_signal_log.csv").is_file(),
        has_change_log=(ddir / "change_log.csv").is_file(),
        has_annotations=(ddir / "event_annotations.csv").is_file(),
        has_reports_root=rroot.is_dir(),
        n_company_ledger_rows=n_ledger,
        n_aggregation_rows=n_agg,
        n_signal_log_rows=n_sl,
        sectors_with_catalysts=sectors_with_cats,
    )


def collect_sector_summaries(
    data_dir: Path | str = DATA_DIR,
) -> list[SectorSummary]:
    """Build a compact list of :class:`SectorSummary` from the on-disk CSVs.

    Sectors without a catalyst file are skipped. Re-uses the canonical V6.1
    ``score_sector`` so the platform never invents its own signal.
    """
    ddir = Path(data_dir)
    out: list[SectorSummary] = []
    for sec in SECTORS:
        cat_path = ddir / SECTOR_FILES[sec]["catalysts"]
        exit_path = ddir / SECTOR_FILES[sec]["exits"]
        if not cat_path.is_file():
            continue
        cats: list[Catalyst] = load_catalysts(cat_path)
        exits: list[EmergencyExit] = (load_exits(exit_path)
                                       if exit_path.is_file() else [])
        score: SectorScore = score_sector(cats, exits, sector=sec)
        out.append(SectorSummary(
            sector=sec,
            signal=score.signal,
            normalized_score=float(score.normalized_score),
            n_catalysts=int(score.n_total),
            n_bull=int(score.n_bull),
            n_broken=int(score.n_broken),
            n_near_threshold=int(score.n_near_threshold),
            triggered_exits=list(score.triggered_exits),
        ))
    return out


def latest_ledger_rows_per_company(
    ledger_path: Path | str = LEDGER_PATH,
) -> list[CompanyLedgerRow]:
    """Return the most-recent :class:`CompanyLedgerRow` per (sector, ticker).

    "Most-recent" means the largest ``run_id`` per (sector, ticker) — run-ids
    are timestamp-formatted so plain string compare sorts chronologically.
    Missing file -> empty list (friendly empty state).
    """
    p = Path(ledger_path)
    if not p.is_file():
        return []
    rows = load_company_ledger(p)
    latest: dict[tuple[str, str], CompanyLedgerRow] = {}
    for r in rows:
        key = (r.sector, r.ticker)
        prev = latest.get(key)
        if prev is None or r.run_id > prev.run_id:
            latest[key] = r
    # Stable order: sector, then ticker.
    return sorted(latest.values(), key=lambda r: (r.sector, r.ticker))


def latest_aggregation_rows(
    aggregation_path: Path | str = AGGREGATION_PATH,
) -> list[SectorAggregationRow]:
    """Latest aggregation row per sector. Missing file -> empty list."""
    p = Path(aggregation_path)
    if not p.is_file():
        return []
    rows = load_sector_aggregation(p)
    latest: dict[str, SectorAggregationRow] = {}
    for r in rows:
        prev = latest.get(r.sector)
        if prev is None or r.run_id > prev.run_id:
            latest[r.sector] = r
    return sorted(latest.values(), key=lambda r: r.sector)


def latest_signal_log_rows(
    signal_log_path: Path | str = SIGNAL_LOG_PATH,
) -> list[SectorSignalLogRow]:
    """Latest canonical-signal row per sector. Missing file -> empty list."""
    p = Path(signal_log_path)
    if not p.is_file():
        return []
    rows = load_sector_signal_log(p)
    latest: dict[str, SectorSignalLogRow] = {}
    for r in rows:
        prev = latest.get(r.sector)
        if prev is None or r.run_id > prev.run_id:
            latest[r.sector] = r
    return sorted(latest.values(), key=lambda r: r.sector)


@dataclass(frozen=True)
class ReportFile:
    """One row in the Reports page listing."""

    relative_path: str   # relative to repo root
    name: str
    size_bytes: int
    kind: str            # "report" / "research" / "other"


REPORT_EXTENSIONS: frozenset[str] = frozenset({".md", ".csv", ".txt"})


def list_reports(
    report_root: Path | str = REPORT_ROOT,
    *, max_files: int = 200,
) -> list[ReportFile]:
    """Recursively list known report-style files under ``report_root``.

    Pure: only reads the directory tree (no file content reads). Returns
    files sorted by relative path for deterministic display. Capped at
    ``max_files`` so a future explosion in report count cannot bloat the
    page beyond reason.
    """
    root = Path(report_root)
    if not root.is_dir():
        return []
    out: list[ReportFile] = []
    for p in sorted(root.rglob("*")):
        if len(out) >= max_files:
            break
        if not p.is_file():
            continue
        if p.suffix.lower() not in REPORT_EXTENSIONS:
            continue
        try:
            size = p.stat().st_size
        except OSError:
            continue
        # Classify by location.
        rel = p.relative_to(ROOT) if ROOT in p.parents else p
        rel_str = str(rel).replace("\\", "/")
        kind = "research" if "research" in rel_str.split("/") else "report"
        out.append(ReportFile(
            relative_path=rel_str,
            name=p.name,
            size_bytes=size,
            kind=kind,
        ))
    return out


def glossary_terms() -> list[dict[str, str]]:
    """Return the static glossary as a list of ``{term, definition}`` dicts."""
    return [dict(g) for g in GLOSSARY]


def find_transactions_file(
    path: Path | str = DEFAULT_TRANSACTIONS_PATH,
) -> Path | None:
    """Return the transactions CSV path iff it exists. Empty state otherwise."""
    p = Path(path)
    return p if p.is_file() else None


# --------------------------------------------------------------------------- #
# V7.1 — Portfolio pure helpers (testable without streamlit).
# Strictly read-only. The Portfolio page reads two CSVs and parses each
# numeric string at render time; an unparseable field surfaces as "n/a"
# rather than as a fabricated number. There is no broker, no IBKR pull, no
# live price fetch. All values are STALE-AS-ENTERED.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class PortfolioSnapshot:
    """Aggregate of positions + transactions at a single point in time."""

    positions: list[PositionRow] = field(default_factory=list)
    transactions: list[TransactionRow] = field(default_factory=list)
    positions_path_exists: bool = False
    transactions_path_exists: bool = False
    latest_as_of: str = ""


@dataclass(frozen=True)
class PortfolioTotals:
    """Categorical + numeric roll-up. Numeric fields are *strings* so the
    platform can show ``"n/a"`` when the source CSV had non-numeric data
    in even one row. Pre-aggregation, parsing-aware, and never invents
    numbers."""

    total_market_value: str       # formatted, e.g. "$1,234.56" or "n/a"
    total_unrealized_pnl: str
    total_realized_pnl: str
    cash: str
    n_positions: int
    n_non_cash_positions: int
    n_transactions: int
    latest_as_of: str
    currency_hint: str            # canonical currency if all match; "" otherwise


def _try_parse_float(s: str) -> float | None:
    """Best-effort parse of a CSV string into a float.

    Strips commas, ``$``, ``%``, leading/trailing whitespace. Returns None
    when the value is empty or unparseable. Never raises.
    """
    if s is None:
        return None
    txt = str(s).strip()
    if not txt:
        return None
    cleaned = txt.replace(",", "").replace("$", "").replace("%", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def _format_money(value: float | None, currency: str = "USD") -> str:
    if value is None:
        return "n/a"
    sign = "-" if value < 0 else ""
    return f"{sign}{currency} {abs(value):,.2f}"


def load_portfolio_snapshot(
    positions_path: Path | str = DEFAULT_POSITIONS_FILE,
    transactions_path: Path | str = DEFAULT_TRANSACTIONS_FILE,
) -> PortfolioSnapshot:
    """Read positions + transactions into a typed snapshot.

    Missing files yield empty lists; the boolean ``*_path_exists`` flags
    tell the Home card "not seeded yet" vs. "seeded but empty".
    ``latest_as_of`` is the maximum ``as_of`` across positions (or empty).
    """
    pp = Path(positions_path)
    tp = Path(transactions_path)
    positions = load_positions(pp)
    transactions = load_transactions(tp)
    latest = max((p.as_of for p in positions if p.as_of), default="")
    return PortfolioSnapshot(
        positions=positions,
        transactions=transactions,
        positions_path_exists=pp.is_file(),
        transactions_path_exists=tp.is_file(),
        latest_as_of=latest,
    )


def latest_positions(snapshot: PortfolioSnapshot) -> list[PositionRow]:
    """Return positions filtered to the snapshot's most-recent ``as_of``.

    If multiple rows exist for the same ``(account, ticker)`` on that date
    (operator error), keep the *first* occurrence — the file is the
    record of truth.
    """
    if not snapshot.latest_as_of:
        return list(snapshot.positions)
    keep: list[PositionRow] = []
    seen: set[tuple[str, str]] = set()
    for p in snapshot.positions:
        if p.as_of != snapshot.latest_as_of:
            continue
        key = (p.account, p.ticker)
        if key in seen:
            continue
        seen.add(key)
        keep.append(p)
    return keep


def compute_portfolio_totals(snapshot: PortfolioSnapshot) -> PortfolioTotals:
    """Aggregate the latest-as-of positions into a totals card.

    Numeric fields are computed only when **every** contributing row's
    relevant field parses cleanly. A single bad row yields ``"n/a"`` for
    that aggregate — we deliberately do not silently skip rows.
    """
    latest = latest_positions(snapshot)
    non_cash = [p for p in latest if p.asset_type != "CASH"]
    cash_rows = [p for p in latest if p.asset_type == "CASH"]

    # Canonical currency (only set when every position agrees).
    currencies = {p.currency for p in latest if p.currency}
    currency_hint = list(currencies)[0] if len(currencies) == 1 else ""
    fmt_ccy = currency_hint or "USD"

    def _sum_field(rows: list[PositionRow], attr: str) -> str:
        if not rows:
            return "n/a"
        vals = [_try_parse_float(getattr(r, attr)) for r in rows]
        if any(v is None for v in vals):
            return "n/a"
        return _format_money(sum(vals), fmt_ccy)

    return PortfolioTotals(
        total_market_value=_sum_field(non_cash, "market_value"),
        total_unrealized_pnl=_sum_field(non_cash, "unrealized_pnl"),
        total_realized_pnl=_sum_field(non_cash, "realized_pnl"),
        cash=_sum_field(cash_rows, "market_value")
            if cash_rows else "n/a",
        n_positions=len(latest),
        n_non_cash_positions=len(non_cash),
        n_transactions=len(snapshot.transactions),
        latest_as_of=snapshot.latest_as_of,
        currency_hint=currency_hint,
    )


def compute_allocations(
    snapshot: PortfolioSnapshot,
) -> dict[str, dict[str, float]]:
    """Return ``{"by_sector": {...}, "by_theme": {...}}`` weights in [0, 1].

    Computed only when every contributing position has a numeric
    ``market_value``; otherwise the relevant inner dict is empty. Cash is
    excluded from sector / theme allocation. Unlabelled rows go to a
    pre-declared ``"(unlabelled)"`` bucket so the operator can spot gaps.
    """
    latest = latest_positions(snapshot)
    non_cash = [p for p in latest if p.asset_type != "CASH"]
    if not non_cash:
        return {"by_sector": {}, "by_theme": {}}

    mvs = [_try_parse_float(p.market_value) for p in non_cash]
    if any(v is None for v in mvs):
        return {"by_sector": {}, "by_theme": {}}
    total = sum(mvs)
    if total <= 0:
        return {"by_sector": {}, "by_theme": {}}

    by_sector: dict[str, float] = {}
    by_theme: dict[str, float] = {}
    for p, v in zip(non_cash, mvs):
        sector = (p.sector or "(unlabelled)").strip() or "(unlabelled)"
        theme = (p.theme or "(unlabelled)").strip() or "(unlabelled)"
        by_sector[sector] = by_sector.get(sector, 0.0) + (v or 0.0)
        by_theme[theme] = by_theme.get(theme, 0.0) + (v or 0.0)

    return {
        "by_sector": {k: v / total for k, v in by_sector.items()},
        "by_theme": {k: v / total for k, v in by_theme.items()},
    }


def portfolio_data_gaps(snapshot: PortfolioSnapshot) -> list[str]:
    """Plain-English notes for the Portfolio page's freshness / gaps line."""
    gaps: list[str] = []
    if not snapshot.positions_path_exists:
        gaps.append("positions.csv missing — see scripts/populate_portfolio.py")
    elif not snapshot.positions:
        gaps.append("positions.csv is header-only (no rows yet)")
    if not snapshot.transactions_path_exists:
        gaps.append("transactions.csv missing")
    elif not snapshot.transactions:
        gaps.append("transactions.csv is header-only (no rows yet)")
    return gaps


# --------------------------------------------------------------------------- #
# V7.7 — Protection pure helpers (testable without streamlit).
# Joins positions + V6 sector signals + V6.7 ledger + V6.8 aggregation into
# per-position categorical labels. No live data, no order, no hedge.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ProtectionSnapshot:
    """Aggregate of every input the Protection engine needs.

    Built by :func:`load_protection_snapshot`. Pure data — no rendering,
    no live fetch, no derived numbers beyond the engine's categorical
    output.
    """

    latest_as_of: str
    positions: list[PositionRow] = field(default_factory=list)
    company_ledger_by_ticker: dict[str, "CompanyLedgerRow"] = field(
        default_factory=dict,
    )
    sector_signals_by_sector: dict[str, "SectorSignalLogRow"] = field(
        default_factory=dict,
    )
    company_aggregations_by_sector: dict[
        str, "SectorAggregationRow"
    ] = field(default_factory=dict)
    # Boolean flags for the Data Gaps section.
    positions_present: bool = False
    ledger_present: bool = False
    signal_log_present: bool = False
    aggregation_present: bool = False


@dataclass(frozen=True)
class ProtectionSummary:
    """Compact counts displayed on the Protection page header cards."""

    n_positions: int
    total_market_value: str   # formatted str, mirrors PortfolioTotals
    n_ok: int
    n_watch: int
    n_concentration: int
    n_sector_at_risk: int
    n_shared_risk_exposed: int
    n_data_gap: int


def _latest_signal_log_dict() -> dict[str, "SectorSignalLogRow"]:
    """Pure helper — latest canonical-signal row per sector."""
    p = SIGNAL_LOG_PATH
    if not p.is_file():
        return {}
    rows = load_sector_signal_log(p)
    latest: dict[str, "SectorSignalLogRow"] = {}
    for r in rows:
        prev = latest.get(r.sector)
        if prev is None or r.run_id > prev.run_id:
            latest[r.sector] = r
    return latest


def _latest_aggregation_dict() -> dict[str, "SectorAggregationRow"]:
    p = AGGREGATION_PATH
    if not p.is_file():
        return {}
    rows = load_sector_aggregation(p)
    latest: dict[str, "SectorAggregationRow"] = {}
    for r in rows:
        prev = latest.get(r.sector)
        if prev is None or r.run_id > prev.run_id:
            latest[r.sector] = r
    return latest


def _latest_ledger_dict() -> dict[str, "CompanyLedgerRow"]:
    p = LEDGER_PATH
    if not p.is_file():
        return {}
    rows = load_company_ledger(p)
    # Latest run per (sector, ticker); keyed by ticker for the engine.
    latest: dict[tuple[str, str], "CompanyLedgerRow"] = {}
    for r in rows:
        key = (r.sector, r.ticker)
        prev = latest.get(key)
        if prev is None or r.run_id > prev.run_id:
            latest[key] = r
    return {ticker: row for (_sector, ticker), row in latest.items()}


def load_protection_snapshot(
    positions_path: Path | str = DEFAULT_POSITIONS_FILE,
    ledger_path: Path | str = LEDGER_PATH,
    signal_log_path: Path | str = SIGNAL_LOG_PATH,
    aggregation_path: Path | str = AGGREGATION_PATH,
) -> ProtectionSnapshot:
    """Compose a :class:`ProtectionSnapshot` from local CSVs only.

    Strictly read-only. Every loader returns ``[]`` or ``{}`` on missing
    files so the snapshot is always valid; missing surfaces propagate
    through the engine as ``DATA_GAP`` labels on the relevant rows.
    """
    pp = Path(positions_path)
    lp = Path(ledger_path)
    sp = Path(signal_log_path)
    ap = Path(aggregation_path)

    positions = load_positions(pp)
    latest = max((p.as_of for p in positions if p.as_of), default="")
    investable = []
    if latest:
        seen: set[tuple[str, str]] = set()
        for p in positions:
            if p.as_of != latest:
                continue
            key = (p.account, p.ticker)
            if key in seen:
                continue
            seen.add(key)
            investable.append(p)
    else:
        investable = list(positions)

    # Latest-only ledger / signal / aggregation dictionaries.
    ledger_d: dict[str, "CompanyLedgerRow"] = {}
    if lp.is_file():
        rows = load_company_ledger(lp)
        latest_lr: dict[tuple[str, str], "CompanyLedgerRow"] = {}
        for r in rows:
            key = (r.sector, r.ticker)
            prev = latest_lr.get(key)
            if prev is None or r.run_id > prev.run_id:
                latest_lr[key] = r
        ledger_d = {tk: row for (_sec, tk), row in latest_lr.items()}

    signal_d: dict[str, "SectorSignalLogRow"] = {}
    if sp.is_file():
        rows = load_sector_signal_log(sp)
        latest_s: dict[str, "SectorSignalLogRow"] = {}
        for r in rows:
            prev = latest_s.get(r.sector)
            if prev is None or r.run_id > prev.run_id:
                latest_s[r.sector] = r
        signal_d = latest_s

    agg_d: dict[str, "SectorAggregationRow"] = {}
    if ap.is_file():
        rows = load_sector_aggregation(ap)
        latest_a: dict[str, "SectorAggregationRow"] = {}
        for r in rows:
            prev = latest_a.get(r.sector)
            if prev is None or r.run_id > prev.run_id:
                latest_a[r.sector] = r
        agg_d = latest_a

    return ProtectionSnapshot(
        latest_as_of=latest,
        positions=investable,
        company_ledger_by_ticker=ledger_d,
        sector_signals_by_sector=signal_d,
        company_aggregations_by_sector=agg_d,
        positions_present=bool(investable),
        ledger_present=bool(ledger_d),
        signal_log_present=bool(signal_d),
        aggregation_present=bool(agg_d),
    )


def derive_protection_rows_from_snapshot(
    snapshot: ProtectionSnapshot,
) -> list[ProtectionRow]:
    """Adapter — calls :func:`derive_protection_rows` against the snapshot."""
    return derive_protection_rows(
        snapshot.positions,
        company_ledger_by_ticker=snapshot.company_ledger_by_ticker,
        sector_signals_by_sector=snapshot.sector_signals_by_sector,
        company_aggregations_by_sector=(
            snapshot.company_aggregations_by_sector
        ),
        as_of=snapshot.latest_as_of,
    )


def compute_protection_summary(
    snapshot: ProtectionSnapshot,
    rows: list[ProtectionRow],
) -> ProtectionSummary:
    """Pre-aggregated counts for the page-header cards.

    ``total_market_value`` is computed via the same parsing helper the
    Portfolio page uses — never a fabricated number when any row's
    ``market_value`` is missing / unparseable.
    """
    n = len(rows)

    def _count(label: str) -> int:
        return sum(1 for r in rows if r.protection_label == label)

    mvs = [_try_parse_float(p.market_value) for p in snapshot.positions
           if p.asset_type != "CASH"]
    if mvs and not any(v is None for v in mvs):
        total = sum(mvs)
        currencies = {p.currency for p in snapshot.positions if p.currency}
        ccy = list(currencies)[0] if len(currencies) == 1 else "USD"
        total_mv = _format_money(total, ccy)
    else:
        total_mv = "n/a"

    return ProtectionSummary(
        n_positions=n,
        total_market_value=total_mv,
        n_ok=_count("OK"),
        n_watch=_count("WATCH"),
        n_concentration=_count("CONCENTRATION"),
        n_sector_at_risk=_count("SECTOR_AT_RISK"),
        n_shared_risk_exposed=_count("SHARED_RISK_EXPOSED"),
        n_data_gap=_count("DATA_GAP"),
    )


def protection_concentration_panel(
    rows: list[ProtectionRow],
    *, top_n_positions: int = 5, top_n_sectors: int = 3,
) -> dict[str, list[tuple[str, float]]]:
    """Top-N positions by weight + top-N sectors by aggregated weight.

    Returns ``{"top_positions": [(ticker, weight_pct)], "top_sectors":
    [(sector, weight_pct)]}``. Rows whose weight string does not parse
    are silently excluded from the ranking (they already surface as
    DATA_GAP elsewhere on the page).
    """
    parsed = []
    for r in rows:
        w = _try_parse_float(r.portfolio_weight_pct)
        if w is None:
            continue
        parsed.append((r.ticker, r.sector or "(unlabelled)", w))

    parsed.sort(key=lambda x: -x[2])
    top_positions = [(t, w) for (t, _s, w) in parsed[:top_n_positions]]

    by_sector: dict[str, float] = {}
    for _t, s, w in parsed:
        by_sector[s] = by_sector.get(s, 0.0) + w
    top_sectors = sorted(
        by_sector.items(), key=lambda kv: -kv[1],
    )[:top_n_sectors]

    return {
        "top_positions": top_positions,
        "top_sectors": [(s, w) for (s, w) in top_sectors],
    }


def protection_data_gaps(snapshot: ProtectionSnapshot) -> list[str]:
    """Per-source presence checks for the page's Data Gaps section."""
    gaps: list[str] = []
    if not snapshot.positions_present:
        gaps.append(
            "no positions loaded — run "
            "`python scripts/populate_portfolio.py add-position …`"
        )
    if not snapshot.ledger_present:
        gaps.append(
            "company signal ledger empty — run "
            "`python scripts/build_company_signal_ledger.py`"
        )
    if not snapshot.signal_log_present:
        gaps.append(
            "canonical sector signal log empty — run "
            "`python scripts/refresh_sector_trackers.py`"
        )
    if not snapshot.aggregation_present:
        gaps.append(
            "company-derived sector aggregation empty — run "
            "`python scripts/build_company_sector_aggregation.py`"
        )
    return gaps


# --------------------------------------------------------------------------- #
# V7.4 — PortTech pure helpers (testable without streamlit).
# Strictly read-only join of positions × V6 signals × V7.7 protection. Never
# emits an order, never recommends a trade — the labels are research
# prompts for the operator.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class PortTechSummary:
    """Counts displayed on the PortTech page header cards."""

    n_positions: int
    n_add: int
    n_hold: int
    n_trim: int
    n_watch: int
    n_exit_watch: int
    n_data_gap: int
    n_concentration_capped: int


def derive_porttech_rows_from_snapshot(
    snapshot: ProtectionSnapshot,
    protection_rows: list[ProtectionRow] | None = None,
) -> list[PortTechRow]:
    """Adapter — call :func:`derive_porttech_rows` against the protection
    snapshot. ``protection_rows`` is optional; when supplied it is keyed by
    ticker and feeds the V7.4 engine's protection-override step.
    """
    prot_by_ticker: dict[str, ProtectionRow] = {}
    if protection_rows:
        for r in protection_rows:
            prot_by_ticker[r.ticker] = r
    return derive_porttech_rows(
        snapshot.positions,
        company_ledger_by_ticker=snapshot.company_ledger_by_ticker,
        sector_signals_by_sector=snapshot.sector_signals_by_sector,
        company_aggregations_by_sector=(
            snapshot.company_aggregations_by_sector
        ),
        protection_rows_by_ticker=prot_by_ticker,
        as_of=snapshot.latest_as_of,
    )


def compute_porttech_summary(
    rows: list[PortTechRow],
) -> PortTechSummary:
    """Pre-aggregated counts for the PortTech page header cards.

    ``n_concentration_capped`` counts rows whose ``why_short`` mentions the
    explicit concentration cap, which is visible to the operator and asserts
    that the cap fired (vs being naturally HOLD).
    """
    def _count(label: str) -> int:
        return sum(1 for r in rows if r.porttech_label == label)

    capped = sum(
        1 for r in rows if "caps ADD to HOLD" in r.why_short
    )

    return PortTechSummary(
        n_positions=len(rows),
        n_add=_count("ADD"),
        n_hold=_count("HOLD"),
        n_trim=_count("TRIM"),
        n_watch=_count("WATCH"),
        n_exit_watch=_count("EXIT_WATCH"),
        n_data_gap=_count("DATA_GAP"),
        n_concentration_capped=capped,
    )


def porttech_divergences(
    rows: list[PortTechRow],
) -> dict[str, list[PortTechRow]]:
    """Surface the two divergence cases the V7.4 page documents.

    * ``constructive_canonical_cautious_company_derived`` — canonical
      signal is ACCUMULATE / SELECTIVE_BUY but the V6.8 aggregation is
      CAUTION / BROKEN.
    * ``company_disagrees_with_sector`` — the V6.7 ledger read disagrees
      with the canonical sector signal (e.g. BROKEN company in a
      SELECTIVE_BUY sector).
    """
    constructive_canonical = {"ACCUMULATE", "SELECTIVE_BUY"}
    cautious_agg = {"CAUTION", "BROKEN"}
    case_a = [
        r for r in rows
        if r.canonical_sector_signal in constructive_canonical
        and r.company_derived_sector_read in cautious_agg
    ]
    case_b = [
        r for r in rows
        if (r.company_read == "BROKEN"
            and r.canonical_sector_signal
            in constructive_canonical | {"HOLD", "AVOID_NEW_BUY"})
    ]
    return {
        "constructive_canonical_cautious_company_derived": case_a,
        "company_disagrees_with_sector": case_b,
    }


def porttech_data_gaps(rows: list[PortTechRow]) -> list[str]:
    """Plain-English summary of which inputs are missing across rows."""
    gap_rows = [r for r in rows if r.porttech_label == "DATA_GAP"]
    if not gap_rows:
        return []
    notes = sorted({r.data_gap_note for r in gap_rows if r.data_gap_note})
    return [
        f"{len(gap_rows)} position(s) carry DATA_GAP",
        *[f"- {note}" for note in notes],
    ]


# --------------------------------------------------------------------------- #
# V7.5 — Company Detail pure helpers (testable without streamlit).
# Strictly read-only. Loads every input from disk and joins via the
# pure V7.5 engine.
# --------------------------------------------------------------------------- #
def load_ticker_universe_from_disk(
    positions_path: Path | str = DEFAULT_POSITIONS_FILE,
    ledger_path: Path | str = LEDGER_PATH,
) -> list[str]:
    """Return sorted unique tickers across the V6.7 ledger and V7.1 positions."""
    rows = (load_company_ledger(Path(ledger_path))
            if Path(ledger_path).is_file() else [])
    poss = (load_positions(Path(positions_path))
            if Path(positions_path).is_file() else [])
    return ticker_universe(rows, poss)


def _load_all_catalysts() -> list[Catalyst]:
    """Read every per-sector catalyst CSV (V6.2.1 / V6.3 / V6.4 outputs)."""
    out: list[Catalyst] = []
    for sec in SECTORS:
        path = DATA_DIR / SECTOR_FILES[sec]["catalysts"]
        if path.is_file():
            out.extend(load_catalysts(path))
    return out


def build_company_detail_view_from_disk(
    ticker: str,
    *,
    positions_path: Path | str = DEFAULT_POSITIONS_FILE,
    ledger_path: Path | str = LEDGER_PATH,
    signal_log_path: Path | str = SIGNAL_LOG_PATH,
    aggregation_path: Path | str = AGGREGATION_PATH,
    change_log_path: Path | str = CHANGE_LOG_PATH,
    annotations_path: Path | str = ANNOTATIONS_PATH,
) -> CompanyDetailView:
    """Compose every input from disk and call the pure V7.5 engine.

    Missing CSVs propagate as empty lists into the engine; the engine
    handles them by populating ``data_gap_notes`` rather than raising.
    Protection and PortTech labels are derived in-process from the same
    snapshot, so the view always carries consistent labels.
    """
    pp = Path(positions_path)
    lp = Path(ledger_path)
    sp = Path(signal_log_path)
    ap = Path(aggregation_path)
    cp = Path(change_log_path)
    annp = Path(annotations_path)

    ledger_rows = load_company_ledger(lp) if lp.is_file() else []
    signal_rows = load_sector_signal_log(sp) if sp.is_file() else []
    agg_rows = load_sector_aggregation(ap) if ap.is_file() else []
    positions = load_positions(pp) if pp.is_file() else []
    catalysts = _load_all_catalysts()
    cl_rows = load_change_log(cp) if cp.is_file() else []
    ann_rows = load_event_annotations(annp) if annp.is_file() else []

    # Derive Protection and PortTech rows fresh so the Company Detail
    # view always reflects the current data on disk.
    snapshot = load_protection_snapshot(
        positions_path=pp, ledger_path=lp,
        signal_log_path=sp, aggregation_path=ap,
    )
    prot_rows = derive_protection_rows_from_snapshot(snapshot)
    pt_rows = derive_porttech_rows_from_snapshot(snapshot, prot_rows)

    as_of = snapshot.latest_as_of

    return build_company_detail_view(
        ticker,
        company_ledger_rows=ledger_rows,
        sector_signal_log_rows=signal_rows,
        sector_aggregation_rows=agg_rows,
        positions=positions,
        protection_rows=prot_rows,
        porttech_rows=pt_rows,
        catalysts=catalysts,
        change_log_rows=cl_rows,
        event_annotations=ann_rows,
        as_of=as_of,
    )


def group_catalysts_by_status(
    catalysts: list[Catalyst],
) -> dict[str, list[Catalyst]]:
    """Group resolved catalysts by status, preserving the V6.1 status order."""
    order = ("BROKEN", "NEAR_THRESHOLD", "MIXED", "NEUTRAL", "BULL")
    out: dict[str, list[Catalyst]] = {s: [] for s in order}
    for c in catalysts:
        out.setdefault(c.status, []).append(c)
    # Drop empty buckets so the renderer doesn't show empty headers.
    return {k: v for k, v in out.items() if v}


def load_technical_snapshot_from_disk(
    ticker: str,
    *,
    cache_dir: Path | str = DEFAULT_PRICE_CACHE_DIR,
) -> TechnicalSnapshot:
    """V7.5.1 — read the local price cache for ``ticker`` and compute the
    deterministic technical snapshot.

    Strictly cache-only. If no cache file exists (the common case for
    most V7.5 universe tickers today), returns a snapshot whose
    ``data_gap_note`` says ``"Price cache not available. No live fetch
    performed."`` exactly as the spec mandates.
    """
    series: PriceSeries | None = load_price_series(
        ticker, cache_dir=cache_dir,
    )
    cache_path = series.cache_path if series else ""
    return compute_technical_snapshot(
        series, ticker=ticker, cache_path=cache_path,
    )


def load_fundamentals_snapshot_from_disk(
    ticker: str,
    *,
    ticker_map_path: Path | str = DEFAULT_TICKER_MAP_FILE,
    companyfacts_dir: Path | str = DEFAULT_COMPANYFACTS_DIR,
    price_cache_dir: Path | str = DEFAULT_PRICE_CACHE_DIR,
) -> FundamentalsSnapshot:
    """V7.5.2 — read the local SEC company-facts cache for ``ticker`` and
    compute the deterministic fundamentals snapshot.

    Strictly cache-only. **No live SEC fetch.** When the local price
    cache also has a row for ``ticker`` and the SEC cache supplies a
    shares-outstanding tag, the valuation fields are populated as well;
    otherwise they stay ``"n/a"`` with an explicit ``valuation_note``.

    For tickers without a CIK mapping (foreign filers such as TSM / ASML
    that do not file with the US SEC), the returned snapshot's
    ``data_gap_note`` says ``"Fundamentals cache not available. No live
    SEC fetch performed."`` exactly as the spec mandates.
    """
    cik, cache_path = companyfacts_path_for_ticker(
        ticker,
        ticker_map_path=ticker_map_path,
        companyfacts_dir=companyfacts_dir,
    )
    facts = (load_companyfacts_json(cik, companyfacts_dir=companyfacts_dir)
             if cik else None)
    # Best-effort latest close for valuation; None when the price cache
    # is missing (the V7.5 universe default today).
    price_series = load_price_series(ticker, cache_dir=price_cache_dir)
    latest_close = (price_series.latest_close
                    if price_series is not None else None)
    return compute_fundamentals_snapshot(
        facts, ticker=ticker, cik=cik,
        cache_path=str(cache_path) if cache_path else "",
        latest_close=latest_close,
    )


# --------------------------------------------------------------------------- #
# V7.8 — MarketPulse pure helpers (testable without streamlit).
# Strictly read-only. The MarketPulse page reads three CSVs and surfaces them
# verbatim; it never writes, fetches, scores, or alerts.
# --------------------------------------------------------------------------- #
# Panels rendered in this fixed order so the dashboard is reproducible.
MARKETPULSE_PANEL_ORDER: tuple[str, ...] = (
    "RATES", "INFLATION", "LABOR", "GROWTH",
    "VOLATILITY", "CREDIT_RISK", "RISK_ON_OFF",
)


@dataclass(frozen=True)
class MarketPulseSnapshot:
    """Aggregate of the three MarketPulse CSVs at a single instant.

    Pure data: no rendering, no derived numeric scoring. Each list is the
    output of its respective ``load_*`` call (so missing CSVs surface as
    empty lists, never as crashes).
    """

    regime_rows: list[RegimeRow] = field(default_factory=list)
    sector_etf_rows: list[SectorETFRow] = field(default_factory=list)
    event_calendar_rows: list[EventCalendarRow] = field(default_factory=list)
    regime_path_exists: bool = False
    sector_etf_path_exists: bool = False
    event_calendar_path_exists: bool = False


@dataclass(frozen=True)
class MarketPulseOverview:
    """Compact, categorical overview the Home card and MarketPulse top panel
    both share. NO hidden numeric score; counts only."""

    panels_populated: int       # distinct panels with at least one row
    panels_total: int           # always len(MARKETPULSE_PANEL_ORDER)
    n_regime_rows: int
    n_sector_etf_rows: int
    n_event_calendar_rows: int
    label: str                  # plain English, e.g. "no data yet" / "partial"
    interpretation: str         # one-line explanation


def load_marketpulse_snapshot(
    regime_path: Path | str = DEFAULT_REGIME_DASHBOARD_FILE,
    sector_etf_path: Path | str = DEFAULT_SECTOR_ETF_SCOREBOARD_FILE,
    event_calendar_path: Path | str = DEFAULT_EVENT_CALENDAR_FILE,
) -> MarketPulseSnapshot:
    """Read the three MarketPulse CSVs into a single typed snapshot.

    Missing files yield empty lists; the boolean ``*_path_exists`` flags
    let the Home card distinguish "file not seeded yet" from "file
    populated".
    """
    rp = Path(regime_path)
    sp = Path(sector_etf_path)
    ep = Path(event_calendar_path)
    return MarketPulseSnapshot(
        regime_rows=load_regime_dashboard(rp),
        sector_etf_rows=load_sector_etf_scoreboard(sp),
        event_calendar_rows=load_event_calendar(ep),
        regime_path_exists=rp.is_file(),
        sector_etf_path_exists=sp.is_file(),
        event_calendar_path_exists=ep.is_file(),
    )


def compute_pulse_overview(
    snapshot: MarketPulseSnapshot,
) -> MarketPulseOverview:
    """Return a categorical overview of the snapshot.

    Never produces a numeric "market score"; only counts how many of the
    expected panels have at least one row. Aligns with the V6.8.1
    philosophy: categorical labels only, no hidden derived signal.
    """
    panels_with_rows = {r.panel for r in snapshot.regime_rows
                        if r.panel in set(MARKETPULSE_PANEL_ORDER)}
    n_panels = len(panels_with_rows)
    n_total = len(MARKETPULSE_PANEL_ORDER)
    n_reg = len(snapshot.regime_rows)
    n_etf = len(snapshot.sector_etf_rows)
    n_cal = len(snapshot.event_calendar_rows)

    if n_reg == 0 and n_etf == 0 and n_cal == 0:
        label = "no data yet"
        interpretation = (
            "MarketPulse CSVs are header-only or absent — populate them "
            "manually (a V7.8.1 helper is planned)."
        )
    elif n_panels == n_total and n_etf > 0:
        label = "fully populated"
        interpretation = (
            f"All {n_total} regime panels + sector ETF scoreboard have "
            "at least one row. No live data fetched."
        )
    else:
        label = "partial"
        interpretation = (
            f"{n_panels}/{n_total} regime panels populated, "
            f"{n_etf} ETF row(s), {n_cal} calendar row(s). "
            "No live data fetched."
        )
    return MarketPulseOverview(
        panels_populated=n_panels,
        panels_total=n_total,
        n_regime_rows=n_reg,
        n_sector_etf_rows=n_etf,
        n_event_calendar_rows=n_cal,
        label=label,
        interpretation=interpretation,
    )


def group_regime_by_panel(
    rows: list[RegimeRow],
) -> dict[str, list[RegimeRow]]:
    """Group regime rows by ``panel``. Pure; preserves input order."""
    out: dict[str, list[RegimeRow]] = {}
    for r in rows:
        out.setdefault(r.panel, []).append(r)
    return out


def data_gaps(snapshot: MarketPulseSnapshot) -> list[str]:
    """Return plain-English notes for every empty surface in ``snapshot``.

    Used by the MarketPulse "Data gaps" section to make the no-live-fetch
    contract obvious to the operator.
    """
    gaps: list[str] = []
    by_panel = group_regime_by_panel(snapshot.regime_rows)
    for panel in MARKETPULSE_PANEL_ORDER:
        if not by_panel.get(panel):
            gaps.append(f"regime panel `{panel}` has no rows")
    if not snapshot.sector_etf_rows:
        gaps.append("sector ETF scoreboard has no rows")
    if not snapshot.event_calendar_rows:
        gaps.append("economic event calendar has no rows")
    return gaps


# --------------------------------------------------------------------------- #
# Streamlit rendering — only imported when actually run by streamlit. Tests
# import this module without invoking render() and exercise the pure helpers.
# --------------------------------------------------------------------------- #
def render() -> None:  # pragma: no cover - exercised by streamlit run
    import streamlit as st

    st.set_page_config(
        page_title="Quant Research Platform — V7.0",
        page_icon="🧪",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    st.markdown(
        """
        <style>
        .stApp { background-color: #0e1117; color: #fafafa; }
        section[data-testid="stSidebar"] { background-color: #161a23; }
        .platform-card {
            border-radius: 8px; padding: 14px 16px; margin: 4px 0 10px 0;
            background-color: #1c2230; border: 1px solid #2a3142;
        }
        .platform-card h3 { margin: 0 0 8px 0; font-size: 14px;
                             opacity: 0.7; }
        .platform-card .big { font-size: 22px; font-weight: 700; }
        .placeholder-banner {
            border-radius: 8px; padding: 10px 14px; margin: 8px 0;
            background-color: #2a2235; border-left: 4px solid #9B59B6;
            color: #f0e0ff;
        }
        .disclaimer-banner {
            border-radius: 6px; padding: 8px 12px; margin: 6px 0;
            background-color: #2a1a1a; border-left: 4px solid #E74C3C;
            color: #ffe0e0; font-size: 12px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # Persistent disclaimer banner at the very top.
    st.markdown(
        f'<div class="disclaimer-banner">{DISCLAIMER}</div>',
        unsafe_allow_html=True,
    )

    st.sidebar.title("Platform")
    st.sidebar.caption("V7.0 shell — local, read-only")
    page = st.sidebar.radio("Navigate", PAGES, index=0)
    st.sidebar.markdown("---")
    st.sidebar.caption(
        "Existing V6 sector dashboard:\n"
        "`python -m streamlit run apps/sector_thesis_dashboard.py`"
    )

    if page == "Home":
        _render_home(st)
    elif page == "Portfolio":
        _render_portfolio(st)
    elif page == "PortTech":
        _render_porttech(st)
    elif page == "Sector Thesis":
        _render_sector_thesis(st)
    elif page == "Company Ledger":
        _render_company_ledger(st)
    elif page == "Company Detail":
        _render_company_detail(st)
    elif page == "MarketPulse":
        _render_marketpulse(st)
    elif page == "Daily Setup":
        _render_daily_setup(st)
    elif page == "Protection":
        _render_protection(st)
    elif page == "Transactions":
        _render_transactions(st)
    elif page == "Reports":
        _render_reports(st)
    elif page == "Glossary":
        _render_glossary(st)
    elif page == "Settings / Guardrails":
        _render_settings(st)

    # Footer disclaimer (visible on every page).
    st.markdown("---")
    st.caption(DISCLAIMER)


def _placeholder(st, title: str, future_role: str,
                  fields: list[str]) -> None:  # pragma: no cover
    """Render a uniform placeholder block used by future-page skeletons."""
    st.markdown(
        f'<div class="placeholder-banner"><strong>{title}</strong> — '
        f'placeholder skeleton in V7.0. {future_role}</div>',
        unsafe_allow_html=True,
    )
    st.markdown("**Intended future fields:**")
    for f in fields:
        st.markdown(f"- {f}")
    st.caption(
        "Nothing on this page reads live data, executes a trade, or "
        "connects to a broker. V7.0 ships the navigation surface only."
    )


def _render_home(st) -> None:  # pragma: no cover
    status = collect_platform_status()
    st.title("🧪 Quant Research Platform — Home")
    st.caption("Local research workbench. Read-only. No live trading.")

    cols = st.columns(3)
    with cols[0]:
        st.markdown(
            f'<div class="platform-card"><h3>Portfolio</h3>'
            f'<div class="big">placeholder</div>'
            f'<div>IBKR read-only integration deferred to V7.1.</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    with cols[1]:
        st.markdown(
            f'<div class="platform-card"><h3>Sector thesis</h3>'
            f'<div class="big">'
            f'{len(status.sectors_with_catalysts)}/3 sectors</div>'
            f'<div>{", ".join(status.sectors_with_catalysts) or "no sector data loaded"}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    with cols[2]:
        st.markdown(
            f'<div class="platform-card"><h3>Company ledger</h3>'
            f'<div class="big">{status.n_company_ledger_rows} rows</div>'
            f'<div>'
            f'{"available" if status.has_ledger else "not built yet"}'
            f'</div></div>',
            unsafe_allow_html=True,
        )

    cols = st.columns(3)
    with cols[0]:
        st.markdown(
            f'<div class="platform-card"><h3>MarketPulse</h3>'
            f'<div class="big">placeholder</div>'
            f'<div>V7.8 will introduce a read-only macro panel.</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    with cols[1]:
        st.markdown(
            f'<div class="platform-card"><h3>Protection</h3>'
            f'<div class="big">placeholder</div>'
            f'<div>Hedge / drawdown surfaces are future work.</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    with cols[2]:
        st.markdown(
            f'<div class="platform-card"><h3>Reports</h3>'
            f'<div class="big">'
            f'{"available" if status.has_reports_root else "empty"}</div>'
            f'<div>See the Reports page for a file listing.</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    st.markdown("---")
    st.subheader("Next safe actions")
    st.markdown(
        "- Build a fresh sector signal log row: "
        "`python scripts/refresh_sector_trackers.py`\n"
        "- Rebuild the V6.7 company signal ledger: "
        "`python scripts/build_company_signal_ledger.py`\n"
        "- Re-run the V6.8 company-derived sector aggregation: "
        "`python scripts/build_company_sector_aggregation.py`\n"
        "- Re-run the V6.9 substrate audit: "
        "`python scripts/audit_ledger_history.py`\n"
        "- Add an operator event annotation: "
        "`python scripts/add_event_annotation.py …`"
    )


def _render_portfolio(st) -> None:  # pragma: no cover
    st.title("Portfolio")
    snapshot = load_portfolio_snapshot()
    totals = compute_portfolio_totals(snapshot)
    allocations = compute_allocations(snapshot)

    # 0. Freshness / source banner — make stale-as-entered explicit.
    if snapshot.latest_as_of:
        st.caption(
            f"Latest snapshot date in CSV: **{snapshot.latest_as_of}** "
            "(manually entered, stale-as-entered). No live broker / no "
            "live price fetch. Re-populate via "
            "`python scripts/populate_portfolio.py add-position …`."
        )
    else:
        st.info(
            "No positions on file. Populate "
            f"`{DEFAULT_POSITIONS_FILE.relative_to(ROOT)}` via "
            "`python scripts/populate_portfolio.py add-position …`. "
            "**V7.1 does not connect to any broker.**"
        )

    # 1. Top totals cards.
    cols = st.columns(4)
    with cols[0]:
        st.markdown(
            f'<div class="platform-card"><h3>Total market value</h3>'
            f'<div class="big">{totals.total_market_value}</div>'
            f'<div>excl. cash; stale-as-entered</div></div>',
            unsafe_allow_html=True,
        )
    with cols[1]:
        st.markdown(
            f'<div class="platform-card"><h3>Cash</h3>'
            f'<div class="big">{totals.cash}</div>'
            f'<div>sum of CASH-typed positions</div></div>',
            unsafe_allow_html=True,
        )
    with cols[2]:
        st.markdown(
            f'<div class="platform-card"><h3>Unrealized P&amp;L</h3>'
            f'<div class="big">{totals.total_unrealized_pnl}</div>'
            f'<div>per CSV; not recomputed</div></div>',
            unsafe_allow_html=True,
        )
    with cols[3]:
        st.markdown(
            f'<div class="platform-card"><h3>Positions</h3>'
            f'<div class="big">{totals.n_positions}</div>'
            f'<div>{totals.n_non_cash_positions} non-cash, '
            f'{totals.n_transactions} transactions on file</div></div>',
            unsafe_allow_html=True,
        )

    # 2. Allocation by sector / theme.
    st.subheader("Allocation")
    sector_alloc = allocations["by_sector"]
    theme_alloc = allocations["by_theme"]
    cols = st.columns(2)
    with cols[0]:
        st.markdown("**By sector**")
        if not sector_alloc:
            st.caption(
                "_(allocation requires a numeric `market_value` on every "
                "non-cash position)_"
            )
        else:
            for k in sorted(sector_alloc, key=lambda x: -sector_alloc[x]):
                st.markdown(f"- {k}: {sector_alloc[k] * 100:.1f}%")
    with cols[1]:
        st.markdown("**By theme**")
        if not theme_alloc:
            st.caption(
                "_(allocation requires a numeric `market_value` on every "
                "non-cash position)_"
            )
        else:
            for k in sorted(theme_alloc, key=lambda x: -theme_alloc[x]):
                st.markdown(f"- {k}: {theme_alloc[k] * 100:.1f}%")

    # 3. Positions table.
    st.subheader("Positions (latest snapshot)")
    latest = latest_positions(snapshot)
    if not latest:
        st.caption("_(no positions in the latest snapshot)_")
    else:
        _render_positions_table(st, latest, allocations["by_sector"])

    # 4. Transactions section.
    st.subheader("Transactions")
    if not snapshot.transactions:
        st.info(
            "No transactions yet. Populate "
            f"`{DEFAULT_TRANSACTIONS_FILE.relative_to(ROOT)}` via "
            "`python scripts/populate_portfolio.py add-transaction …`."
        )
    else:
        _render_transactions_table(st, snapshot.transactions[-25:])
        if len(snapshot.transactions) > 25:
            st.caption(
                f"showing latest 25 of {len(snapshot.transactions)} "
                "transactions"
            )

    # 5. Data freshness / source note + gaps.
    st.markdown("---")
    st.subheader("Data freshness / gaps")
    st.caption(
        "All values are manually entered. The platform never fetches a "
        "live price. **No broker / no IBKR / no order execution in V7.1.**"
    )
    gaps = portfolio_data_gaps(snapshot)
    if not gaps:
        st.success("All portfolio CSVs are populated. (Still no live data.)")
    else:
        for g in gaps:
            st.markdown(f"- {g}")


def _render_positions_table(
    st, rows: list[PositionRow],
    by_sector_weights: dict[str, float],
) -> None:  # pragma: no cover
    # Pre-compute per-row weight when possible.
    total_mv = sum(
        _try_parse_float(r.market_value) or 0.0 for r in rows
        if r.asset_type != "CASH"
    )

    header = (
        '<table style="width:100%; border-collapse:collapse; '
        'background-color:#1c2230; border:1px solid #2a3142;">'
        '<thead><tr style="text-align:left; color:#8a93a6;">'
        '<th style="padding:8px">Ticker</th>'
        '<th style="padding:8px">Company</th>'
        '<th style="padding:8px">Qty</th>'
        '<th style="padding:8px">Last price</th>'
        '<th style="padding:8px">Market value</th>'
        '<th style="padding:8px">Weight</th>'
        '<th style="padding:8px">Unrealized P&amp;L</th>'
        '<th style="padding:8px">Sector / theme</th>'
        '</tr></thead><tbody>'
    )
    body = []
    for r in rows:
        mv = _try_parse_float(r.market_value)
        if mv is None or total_mv <= 0 or r.asset_type == "CASH":
            weight = "—"
        else:
            weight = f"{(mv / total_mv) * 100:.1f}%"
        body.append(
            f'<tr style="border-top:1px solid #2a3142;">'
            f'<td style="padding:8px"><strong>{r.ticker}</strong></td>'
            f'<td style="padding:8px">{r.company_name or "—"}</td>'
            f'<td style="padding:8px">{r.quantity or "—"}</td>'
            f'<td style="padding:8px">{r.last_price or "—"}</td>'
            f'<td style="padding:8px">{r.market_value or "—"}</td>'
            f'<td style="padding:8px">{weight}</td>'
            f'<td style="padding:8px">{r.unrealized_pnl or "—"}</td>'
            f'<td style="padding:8px">{r.sector or "—"} / '
            f'{r.theme or "—"}</td>'
            f'</tr>'
        )
    st.markdown(header + "".join(body) + "</tbody></table>",
                 unsafe_allow_html=True)


def _render_transactions_table(
    st, rows: list[TransactionRow],
) -> None:  # pragma: no cover
    header = (
        '<table style="width:100%; border-collapse:collapse; '
        'background-color:#1c2230; border:1px solid #2a3142;">'
        '<thead><tr style="text-align:left; color:#8a93a6;">'
        '<th style="padding:8px">Date</th>'
        '<th style="padding:8px">Account</th>'
        '<th style="padding:8px">Ticker</th>'
        '<th style="padding:8px">Side</th>'
        '<th style="padding:8px">Qty</th>'
        '<th style="padding:8px">Price</th>'
        '<th style="padding:8px">Fees</th>'
        '<th style="padding:8px">Linked thesis</th>'
        '<th style="padding:8px">Reason</th>'
        '</tr></thead><tbody>'
    )
    body = []
    for r in rows:
        body.append(
            f'<tr style="border-top:1px solid #2a3142;">'
            f'<td style="padding:8px">{r.date}</td>'
            f'<td style="padding:8px">{r.account}</td>'
            f'<td style="padding:8px"><strong>{r.ticker}</strong></td>'
            f'<td style="padding:8px">{r.side}</td>'
            f'<td style="padding:8px">{r.quantity or "—"}</td>'
            f'<td style="padding:8px">{r.price or "—"}</td>'
            f'<td style="padding:8px">{r.fees or "—"}</td>'
            f'<td style="padding:8px">{r.linked_thesis or "—"}</td>'
            f'<td style="padding:8px">{r.reason or "—"}</td>'
            f'</tr>'
        )
    st.markdown(header + "".join(body) + "</tbody></table>",
                 unsafe_allow_html=True)


_PORTTECH_LABEL_COLOURS: dict[str, str] = {
    "ADD":        "#2ECC71",
    "HOLD":       "#7F8C8D",
    "WATCH":      "#F39C12",
    "TRIM":       "#E67E22",
    "EXIT_WATCH": "#E74C3C",
    "DATA_GAP":   "#34495E",
}


def _render_porttech(st) -> None:  # pragma: no cover
    st.title("PortTech")
    # PortTech re-uses the Protection snapshot exactly — same four inputs.
    snapshot = load_protection_snapshot()
    protection_rows = derive_protection_rows_from_snapshot(snapshot)
    rows = derive_porttech_rows_from_snapshot(snapshot, protection_rows)
    summary = compute_porttech_summary(rows)
    divergences = porttech_divergences(rows)
    gaps = porttech_data_gaps(rows)

    # 0. Stale-as-entered banner.
    if snapshot.latest_as_of:
        st.caption(
            f"Latest position snapshot: **{snapshot.latest_as_of}**. "
            "**Research-only. No order execution. No buy/sell "
            "instruction. No trade placement.** PortTech labels are "
            "derived deterministically from already-loaded V6 / V7 "
            "artefacts and the V7.7 Protection labels."
        )
    else:
        st.info(
            "No positions on file. PortTech is a join across positions "
            "× V6 signals × V7.7 Protection — it needs positions to "
            "render anything. Use "
            "`python scripts/populate_portfolio.py add-position …` first."
        )

    # 1. Top summary cards.
    cols = st.columns(4)
    with cols[0]:
        st.markdown(
            f'<div class="platform-card"><h3>Positions</h3>'
            f'<div class="big">{summary.n_positions}</div>'
            f'<div>{summary.n_add} ADD · {summary.n_hold} HOLD</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    with cols[1]:
        st.markdown(
            f'<div class="platform-card" '
            f'style="border-left:4px solid #F39C12;">'
            f'<h3>Watch / Trim</h3>'
            f'<div class="big">{summary.n_watch + summary.n_trim}</div>'
            f'<div>{summary.n_watch} WATCH · {summary.n_trim} TRIM'
            f'</div></div>',
            unsafe_allow_html=True,
        )
    with cols[2]:
        st.markdown(
            f'<div class="platform-card" '
            f'style="border-left:4px solid #E74C3C;">'
            f'<h3>Exit watch</h3>'
            f'<div class="big">{summary.n_exit_watch}</div>'
            f'<div>thesis-broken or sector EXIT_WATCH</div></div>',
            unsafe_allow_html=True,
        )
    with cols[3]:
        st.markdown(
            f'<div class="platform-card"><h3>Data gaps / capped</h3>'
            f'<div class="big">{summary.n_data_gap}</div>'
            f'<div>{summary.n_concentration_capped} '
            f'concentration-capped</div></div>',
            unsafe_allow_html=True,
        )

    # 2. Position action table.
    st.subheader("PortTech labels by position")
    if not rows:
        st.caption("_(no positions to evaluate)_")
    else:
        _render_porttech_table(st, rows)

    # 3. Divergence panel.
    st.subheader("Divergence panel")
    case_a = divergences["constructive_canonical_cautious_company_derived"]
    case_b = divergences["company_disagrees_with_sector"]
    dp_left, dp_right = st.columns(2)
    with dp_left:
        st.markdown(
            "**Canonical constructive but company-derived cautious**"
        )
        if not case_a:
            st.caption("_(none — canonical and company-derived agree)_")
        else:
            for r in case_a:
                st.markdown(
                    f"- **{r.ticker}** ({r.sector}) — canonical "
                    f"`{r.canonical_sector_signal}` vs company-derived "
                    f"`{r.company_derived_sector_read}` → "
                    f"**{r.porttech_label}**"
                )
    with dp_right:
        st.markdown("**Company BROKEN despite a healthy-ish sector**")
        if not case_b:
            st.caption("_(none — company reads agree with sector reads)_")
        else:
            for r in case_b:
                st.markdown(
                    f"- **{r.ticker}** ({r.sector}) — company "
                    f"`BROKEN` while canonical "
                    f"`{r.canonical_sector_signal}` → "
                    f"**{r.porttech_label}**"
                )

    # 4. Data gaps section.
    st.markdown("---")
    st.subheader("Data gaps")
    snap_gaps = protection_data_gaps(snapshot)
    if not snap_gaps and not gaps:
        st.success(
            "All PortTech inputs present. Labels reflect today's "
            "stale-as-entered values."
        )
    else:
        for g in snap_gaps:
            st.markdown(f"- {g}")
        for g in gaps:
            st.markdown(f"- {g}")

    # 5. Hard disclaimer footer (page-level, on top of the global one).
    st.markdown("---")
    st.error(
        "**Research-only.** No order execution. No buy/sell instruction. "
        "No trade placement. PortTech labels are categorical research "
        "prompts — the operator is the only decision-maker. The platform "
        "does NOT place orders."
    )


def _render_porttech_table(
    st, rows: list[PortTechRow],
) -> None:  # pragma: no cover
    header = (
        '<table style="width:100%; border-collapse:collapse; '
        'background-color:#1c2230; border:1px solid #2a3142;">'
        '<thead><tr style="text-align:left; color:#8a93a6;">'
        '<th style="padding:8px">Ticker</th>'
        '<th style="padding:8px">Weight</th>'
        '<th style="padding:8px">Company read</th>'
        '<th style="padding:8px">Canonical signal</th>'
        '<th style="padding:8px">Company-derived</th>'
        '<th style="padding:8px">Protection</th>'
        '<th style="padding:8px">PortTech</th>'
        '<th style="padding:8px">Why</th>'
        '<th style="padding:8px">Action</th>'
        '</tr></thead><tbody>'
    )
    body = []
    for r in rows:
        col = _PORTTECH_LABEL_COLOURS.get(r.porttech_label, "#34495E")
        weight = (f"{float(r.portfolio_weight_pct):.1f}%"
                   if r.portfolio_weight_pct else "—")
        body.append(
            f'<tr style="border-top:1px solid #2a3142;">'
            f'<td style="padding:8px"><strong>{r.ticker}</strong></td>'
            f'<td style="padding:8px">{weight}</td>'
            f'<td style="padding:8px">{r.company_read or "—"}</td>'
            f'<td style="padding:8px">{r.canonical_sector_signal or "—"}</td>'
            f'<td style="padding:8px">'
            f'{r.company_derived_sector_read or "—"}</td>'
            f'<td style="padding:8px">{r.protection_label or "—"}</td>'
            f'<td style="padding:8px">'
            f'<span class="pill" style="background-color:{col}; '
            f'color:#0e1117; padding:2px 8px; border-radius:999px; '
            f'font-size:11px; font-weight:700">{r.porttech_label}'
            f'</span></td>'
            f'<td style="padding:8px">{r.why_short or "—"}</td>'
            f'<td style="padding:8px">{r.action_short or "—"}</td>'
            f'</tr>'
        )
    st.markdown(header + "".join(body) + "</tbody></table>",
                 unsafe_allow_html=True)


def _render_sector_thesis(st) -> None:  # pragma: no cover
    st.title("Sector Thesis (summary)")
    st.caption(
        "Compact summary of the V6 sector tracker. For the full V6.5.x "
        "dashboard run:\n"
        "`python -m streamlit run apps/sector_thesis_dashboard.py`"
    )
    summaries = collect_sector_summaries()
    if not summaries:
        st.info("No sector catalyst CSVs found yet — run "
                 "`python scripts/refresh_sector_trackers.py` first.")
        return
    for s in summaries:
        st.markdown(
            f'<div class="platform-card"><h3>{s.sector}</h3>'
            f'<div class="big">{s.signal} '
            f'({s.normalized_score:+.3f})</div>'
            f'<div>{s.n_catalysts} catalysts — '
            f'{s.n_bull} bull / '
            f'{s.n_near_threshold} near-threshold / '
            f'{s.n_broken} broken</div></div>',
            unsafe_allow_html=True,
        )
        if s.triggered_exits:
            st.error(f"Triggered exits: {', '.join(s.triggered_exits)}")

    with st.expander("Latest canonical signal log entries", expanded=False):
        log_rows = latest_signal_log_rows()
        if not log_rows:
            st.caption("_(no signal log entries yet)_")
        for r in log_rows:
            st.markdown(
                f"- **{r.sector}** — `{r.canonical_signal}` "
                f"({r.normalized_score:+.3f}) at `{r.run_id}` "
                f"({r.n_bull}B / {r.n_broken}X)"
            )


def _render_company_ledger(st) -> None:  # pragma: no cover
    st.title("Company Ledger")
    rows = latest_ledger_rows_per_company()
    if not rows:
        st.info(
            "No company ledger found at "
            f"`{LEDGER_PATH.relative_to(ROOT)}`.\n\n"
            "Run `python scripts/build_company_signal_ledger.py` first."
        )
        return
    st.caption(
        f"Showing the latest ledger row per (sector, ticker) — "
        f"{len(rows)} companies. Read-only view; ledger is not mutated."
    )
    # Compact HTML table that matches the V6.5.2 styling.
    header = (
        '<table style="width:100%; border-collapse:collapse; '
        'background-color:#1c2230; border:1px solid #2a3142;">'
        '<thead><tr style="text-align:left; color:#8a93a6;">'
        '<th style="padding:8px">Sector</th>'
        '<th style="padding:8px">Ticker</th>'
        '<th style="padding:8px">Theme</th>'
        '<th style="padding:8px">Read</th>'
        '<th style="padding:8px">Why</th>'
        '<th style="padding:8px">Main risk</th>'
        '<th style="padding:8px">Run</th>'
        '</tr></thead><tbody>'
    )
    body = []
    for r in rows:
        body.append(
            f'<tr style="border-top:1px solid #2a3142;">'
            f'<td style="padding:8px">{r.sector}</td>'
            f'<td style="padding:8px"><strong>{r.ticker}</strong></td>'
            f'<td style="padding:8px">{r.theme}</td>'
            f'<td style="padding:8px">{r.read}</td>'
            f'<td style="padding:8px">{r.why_short or "—"}</td>'
            f'<td style="padding:8px">{r.main_risk_short or "—"}</td>'
            f'<td style="padding:8px">'
            f'<code style="font-size:11px">{r.run_id}</code></td>'
            f'</tr>'
        )
    st.markdown(header + "".join(body) + "</tbody></table>",
                unsafe_allow_html=True)


# --------------------------------------------------------------------------- #
# V7.5 — Company Detail renderer
# --------------------------------------------------------------------------- #
_COMPANY_READ_COLOURS: dict[str, str] = {
    "BULL": "#2ECC71",
    "NEUTRAL": "#7F8C8D",
    "NEAR_THRESHOLD": "#F39C12",
    "BROKEN": "#E74C3C",
    "MIXED": "#3498DB",
    "TRACKED": "#9B59B6",
    "N/A": "#34495E",
}

_CATALYST_STATUS_COLOURS: dict[str, str] = {
    "BULL": "#2ECC71",
    "NEUTRAL": "#7F8C8D",
    "NEAR_THRESHOLD": "#F39C12",
    "BROKEN": "#E74C3C",
}


def _render_company_detail(st) -> None:  # pragma: no cover
    st.title("Company Detail")
    tickers = load_ticker_universe_from_disk()
    if not tickers:
        st.info(
            "No tickers found in the V6.7 company ledger or V7.1 "
            "positions. Run `python scripts/build_company_signal_ledger.py` "
            "or `python scripts/populate_portfolio.py add-position …` first."
        )
        return

    selected = st.selectbox(
        "Select ticker",
        options=tickers,
        index=0,
        help=("Universe = union of tickers in company_signal_ledger.csv "
              "and positions.csv."),
    )
    if not selected:
        return

    view = build_company_detail_view_from_disk(selected)

    # 1. Header card.
    read_col = _COMPANY_READ_COLOURS.get(view.current_company_read,
                                            "#34495E")
    st.markdown(
        f'<div class="platform-card" '
        f'style="border-left:4px solid {read_col};">'
        f'<h3>{view.ticker}</h3>'
        f'<div class="big">{view.company_or_label or view.ticker}</div>'
        f'<div><strong>Sector:</strong> {view.sector or "—"} · '
        f'<strong>Theme:</strong> {view.theme or "—"}</div>'
        f'<div style="margin-top:6px">'
        f'<strong>Company read:</strong> '
        f'<span class="pill" style="background-color:{read_col}; '
        f'color:#0e1117; padding:2px 8px; border-radius:999px; '
        f'font-size:11px; font-weight:700">'
        f'{view.current_company_read or "—"}</span> · '
        f'<strong>Canonical signal:</strong> '
        f'{view.canonical_sector_signal or "—"} · '
        f'<strong>Company-derived sector:</strong> '
        f'{view.company_derived_sector_read or "—"}</div>'
        f'<div style="margin-top:6px">'
        f'<strong>Protection:</strong> {view.protection_label or "—"} · '
        f'<strong>PortTech:</strong> {view.porttech_label or "—"}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # 2. Position card (if held).
    st.subheader("Position")
    if view.position_present:
        cols = st.columns(4)
        with cols[0]:
            st.metric("Quantity", view.quantity or "—")
        with cols[1]:
            st.metric("Market value", view.market_value or "—")
        with cols[2]:
            weight = (f"{float(view.portfolio_weight_pct):.2f}%"
                      if view.portfolio_weight_pct else "—")
            st.metric("Weight", weight)
        with cols[3]:
            st.metric("Unrealized P&L", view.unrealized_pnl or "—")
        if view.average_cost:
            st.caption(f"Average cost: {view.average_cost}")
    else:
        st.info("Tracked, not currently held.")

    # 2.5. V7.5.1 — Price / technicals (collapsed by default).
    tech = load_technical_snapshot_from_disk(view.ticker)
    with st.expander("Price / technicals", expanded=False):
        st.caption(
            "**Context only — research signal, never a trading "
            "instruction.** Values are computed from the local price "
            "cache; **no live fetch performed**. "
            "RSI / SMA / returns / drawdown are pre-declared at fixed "
            "periods (no parameter optimisation)."
        )
        if tech.latest_date:
            st.caption(
                f"Latest cache date: **{tech.latest_date}** "
                f"(stale-as-cached). Source: "
                f"`{tech.cache_path}`"
            )
        else:
            st.info(
                "**Price cache not available. No live fetch performed.** "
                "Drop a `<TICKER>.csv` with `date,close` columns under "
                f"`{DEFAULT_PRICE_CACHE_DIR.relative_to(ROOT)}` to "
                "enable this section."
            )
        if tech.latest_date:
            cols = st.columns(4)
            with cols[0]:
                st.metric("Latest close", tech.latest_close)
            with cols[1]:
                st.metric("1W", tech.return_1w)
            with cols[2]:
                st.metric("1M", tech.return_1m)
            with cols[3]:
                st.metric("3M", tech.return_3m)
            cols = st.columns(4)
            with cols[0]:
                st.metric("1Y", tech.return_1y)
            with cols[1]:
                st.metric("RSI(14)", tech.rsi_14)
            with cols[2]:
                st.metric("SMA(50)", tech.sma_50)
            with cols[3]:
                st.metric("SMA(200)", tech.sma_200)
            cols = st.columns(3)
            with cols[0]:
                st.metric(
                    "vs SMA(50)", tech.distance_to_sma_50_pct,
                )
            with cols[1]:
                st.metric(
                    "vs SMA(200)", tech.distance_to_sma_200_pct,
                )
            with cols[2]:
                st.metric(
                    "DD from 1Y high",
                    tech.drawdown_from_1y_high_pct,
                )
            if tech.data_gap_note:
                st.caption(
                    "_Indicator gaps: " + tech.data_gap_note + "_"
                )

    # 2.6. V7.5.2 — Fundamentals / valuation (collapsed by default).
    fund = load_fundamentals_snapshot_from_disk(view.ticker)
    with st.expander("Fundamentals / valuation", expanded=False):
        st.caption(
            "**Context only — research signal, never a trading "
            "instruction.** Values are extracted from the local SEC "
            "company-facts cache; **no live SEC fetch performed**. "
            "Field tags are pre-declared US-GAAP / DEI concepts and the "
            "extraction policy is first-match-wins with freshness "
            "tie-break (mirrors the V6.2.1 selection rule)."
        )
        if fund.latest_report_date:
            st.caption(
                f"Latest fiscal period: **{fund.latest_fiscal_period}** "
                f"(ended **{fund.latest_report_date}**, stale-as-cached). "
                f"Source: `{fund.cache_path}`"
            )
        if not fund.latest_report_date and (
            fund.data_gap_note.startswith("Fundamentals cache not available")
            or not fund.cik
        ):
            st.info(
                "**Fundamentals cache not available. No live SEC fetch "
                "performed.** This usually means the ticker is a foreign "
                "filer (no US SEC submissions), private, or simply not "
                "in the local cache yet."
            )
        else:
            # Headline P&L row.
            cols = st.columns(4)
            with cols[0]:
                st.metric("Revenue", fund.revenue, fund.revenue_yoy_pct)
            with cols[1]:
                st.metric("Gross margin", fund.gross_margin_pct)
            with cols[2]:
                st.metric("Operating margin", fund.operating_margin_pct)
            with cols[3]:
                st.metric("Net income", fund.net_income)
            # Cash-flow row.
            cols = st.columns(4)
            with cols[0]:
                st.metric("Op cash flow", fund.operating_cash_flow)
            with cols[1]:
                st.metric("Capex", fund.capex)
            with cols[2]:
                st.metric("Free cash flow", fund.free_cash_flow)
            with cols[3]:
                st.metric("Shares out", fund.shares_outstanding)
            # Balance-sheet row.
            cols = st.columns(4)
            with cols[0]:
                st.metric("Inventory", fund.inventory,
                          fund.inventory_yoy_pct)
            with cols[1]:
                st.metric("Cash", fund.cash)
            with cols[2]:
                st.metric("Debt", fund.debt)
            with cols[3]:
                st.metric("Gross profit", fund.gross_profit)
            if fund.data_gap_note:
                st.caption(
                    "_Tag gaps: " + fund.data_gap_note + "_"
                )

            # Valuation sub-section.
            st.markdown("**Valuation**")
            if fund.valuation_note:
                st.caption(f"_{fund.valuation_note}_")
            else:
                cols = st.columns(3)
                with cols[0]:
                    st.metric("Market cap", fund.market_cap)
                with cols[1]:
                    st.metric("Enterprise value", fund.enterprise_value)
                with cols[2]:
                    st.metric("P/S", fund.price_to_sales)
                cols = st.columns(3)
                with cols[0]:
                    st.metric("P/E", fund.price_to_earnings)
                with cols[1]:
                    st.metric("P/FCF", fund.price_to_free_cash_flow)
                with cols[2]:
                    st.metric("EV / Sales", fund.ev_to_sales)

    # 3. Why / risk section.
    st.subheader("Why this read")
    st.markdown(
        f"- **Why short:** {view.why_short or '—'}\n"
        f"- **Main risk short:** {view.main_risk_short or '—'}"
    )
    if view.linked_catalysts:
        st.caption(
            "Linked catalysts: " + ", ".join(
                f"`{cid}`" for cid in view.linked_catalysts
            )
        )

    # 4. Catalyst section.
    st.subheader("Current catalysts")
    if not view.current_catalysts:
        st.caption(
            "_(no linked catalysts resolved — see Data gaps below if "
            "this is unexpected)_"
        )
    else:
        grouped = group_catalysts_by_status(view.current_catalysts)
        for status, group in grouped.items():
            col = _CATALYST_STATUS_COLOURS.get(status, "#7F8C8D")
            st.markdown(
                f'<div style="margin: 8px 0;">'
                f'<span class="pill" style="background-color:{col}; '
                f'color:#0e1117; padding:2px 8px; border-radius:999px; '
                f'font-size:11px; font-weight:700">{status}</span> '
                f'<strong>({len(group)})</strong></div>',
                unsafe_allow_html=True,
            )
            for c in group:
                st.markdown(
                    f"- **{c.catalyst_name}** "
                    f"(`{c.catalyst_id}`, tier {c.tier}) — "
                    f"current value `{c.current_value or '—'}`"
                )
                with st.expander(
                    f"Technical detail for {c.catalyst_id}",
                    expanded=False,
                ):
                    st.markdown(
                        f"- Threshold: `{c.threshold}`\n"
                        f"- Direction: `{c.direction}`\n"
                        f"- Source type: `{c.source_type}`\n"
                        f"- Source detail: {c.source_detail or '—'}\n"
                        f"- Last updated: `{c.last_updated}`\n"
                        f"- Action if broken: {c.action_if_broken or '—'}\n"
                        f"- Notes: {c.notes or '—'}"
                    )

    # 5. History section.
    st.subheader("Historical company reads")
    if not view.historical_company_reads:
        st.caption("_(no ledger history — first run not yet persisted)_")
    else:
        header = (
            '<table style="width:100%; border-collapse:collapse; '
            'background-color:#1c2230; border:1px solid #2a3142;">'
            '<thead><tr style="text-align:left; color:#8a93a6;">'
            '<th style="padding:8px">Run</th>'
            '<th style="padding:8px">Date</th>'
            '<th style="padding:8px">Read</th>'
            '<th style="padding:8px">Why</th>'
            '</tr></thead><tbody>'
        )
        body = []
        for r in view.historical_company_reads[:20]:
            col = _COMPANY_READ_COLOURS.get(r.read, "#34495E")
            body.append(
                f'<tr style="border-top:1px solid #2a3142;">'
                f'<td style="padding:8px">'
                f'<code style="font-size:11px">{r.run_id}</code></td>'
                f'<td style="padding:8px">{r.date}</td>'
                f'<td style="padding:8px">'
                f'<span class="pill" style="background-color:{col}; '
                f'color:#0e1117; padding:2px 8px; border-radius:999px; '
                f'font-size:11px; font-weight:700">{r.read}</span></td>'
                f'<td style="padding:8px">{r.why_short or "—"}</td>'
                f'</tr>'
            )
        st.markdown(header + "".join(body) + "</tbody></table>",
                     unsafe_allow_html=True)
        if len(view.historical_company_reads) > 20:
            st.caption(
                f"showing latest 20 of "
                f"{len(view.historical_company_reads)} historical reads"
            )

    # 6. Recent changes.
    st.subheader("Recent changes")
    if not view.recent_changes:
        st.caption("_(no change-log rows touching this ticker / its "
                    "catalysts)_")
    else:
        for c in view.recent_changes[:10]:
            st.markdown(
                f"- `{c.timestamp}` — **{c.record_type}/{c.record_id}** "
                f"field `{c.field_changed}`: "
                f"{c.prior_value or '—'} → {c.new_value or '—'}"
            )
        if len(view.recent_changes) > 10:
            st.caption(
                f"showing latest 10 of {len(view.recent_changes)} "
                "change-log rows"
            )

    # 7. Event annotations.
    st.subheader("Event annotations")
    if not view.event_annotations:
        st.caption("_(no operator annotations for this ticker / catalysts)_")
    else:
        for a in view.event_annotations[:10]:
            st.markdown(
                f"- `{a.timestamp}` — **{a.event_type}** "
                f"(`{a.related_type}/{a.related_id}`): "
                f"{a.title or '—'}. {a.note or ''}"
            )

    # 8. Data gaps.
    st.markdown("---")
    st.subheader("Data gaps")
    if not view.data_gap_notes:
        st.success(
            "All Company Detail inputs present for this ticker."
        )
    else:
        for g in view.data_gap_notes:
            st.markdown(f"- {g}")

    # 9. Hard disclaimer footer (page-level).
    st.markdown("---")
    st.error(
        "**Explanatory page — research only.** No order, no buy/sell "
        "instruction, no trade execution. The platform reads existing "
        "local CSVs and renders pre-declared categorical labels. The "
        "operator is the only decision-maker."
    )


_REGIME_STATUS_COLOURS: dict[str, str] = {
    "BULLISH": "#2ECC71",
    "NEUTRAL": "#7F8C8D",
    "BEARISH": "#E74C3C",
    "MIXED": "#3498DB",
    "N_A": "#34495E",
}
_TREND_STATUS_COLOURS: dict[str, str] = {
    "UPTREND": "#2ECC71",
    "DOWNTREND": "#E74C3C",
    "SIDEWAYS": "#7F8C8D",
    "N_A": "#34495E",
}
_IMPACT_COLOURS: dict[str, str] = {
    "LOW": "#7F8C8D",
    "MEDIUM": "#F39C12",
    "HIGH": "#E74C3C",
    "N_A": "#34495E",
}


def _render_marketpulse(st) -> None:  # pragma: no cover
    st.title("MarketPulse")
    snapshot = load_marketpulse_snapshot()
    overview = compute_pulse_overview(snapshot)

    # 1. Top section — categorical label, interpretation, freshness note.
    st.markdown(
        f'<div class="platform-card"><h3>MarketPulse</h3>'
        f'<div class="big">{overview.label}</div>'
        f'<div>{overview.interpretation}</div></div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "MarketPulse is **context only**. No live data is fetched. No "
        "broker is contacted. No order is ever placed. The values shown "
        "are read verbatim from local CSVs under "
        f"`{DEFAULT_MARKETPULSE_DIR.relative_to(ROOT)}/`."
    )

    # 2. Macro regime cards (one card per panel, including RISK_ON_OFF).
    st.subheader("Macro regime")
    by_panel = group_regime_by_panel(snapshot.regime_rows)
    if not snapshot.regime_rows:
        st.info(
            "Regime dashboard CSV is empty. Populate "
            f"`{DEFAULT_REGIME_DASHBOARD_FILE.relative_to(ROOT)}` "
            "manually; a V7.8.1 helper is planned."
        )
    else:
        # Skip RISK_ON_OFF here — it gets its own section below to honour
        # the spec's "Risk-on / risk-off panel" item.
        panels_to_render = [p for p in MARKETPULSE_PANEL_ORDER
                            if p != "RISK_ON_OFF"]
        cols_per_row = 3
        for chunk_start in range(0, len(panels_to_render), cols_per_row):
            cols = st.columns(cols_per_row)
            for i, panel in enumerate(
                panels_to_render[chunk_start:chunk_start + cols_per_row]
            ):
                with cols[i]:
                    _render_regime_panel_card(st, panel,
                                                by_panel.get(panel) or [])

    # 3. Risk-on / risk-off panel — its own block per the spec.
    st.subheader("Risk-on / risk-off")
    risk_rows = by_panel.get("RISK_ON_OFF") or []
    if not risk_rows:
        st.info(
            "No `RISK_ON_OFF` rows in the regime CSV yet. Expected future "
            "inputs: VIX regime, credit spreads (HY-IG), equity-bond "
            "correlation, breadth indicators, defensives vs cyclicals."
        )
    else:
        for r in risk_rows:
            col = _REGIME_STATUS_COLOURS.get(r.status, "#34495E")
            st.markdown(
                f'<div class="platform-card" '
                f'style="border-left: 4px solid {col};">'
                f'<strong>{r.indicator}</strong> '
                f'<span class="pill" style="background-color:{col}; '
                f'color:#0e1117; padding:2px 8px; border-radius:999px; '
                f'font-size:11px; font-weight:700">{r.status}</span><br>'
                f'<span>{r.value}</span><br>'
                f'<span style="opacity:0.7; font-size:12px">'
                f'{r.interpretation}</span></div>',
                unsafe_allow_html=True,
            )

    # 4. Sector ETF scoreboard.
    st.subheader("Sector ETF scoreboard")
    if not snapshot.sector_etf_rows:
        st.info(
            "Sector ETF scoreboard CSV is empty. Populate "
            f"`{DEFAULT_SECTOR_ETF_SCOREBOARD_FILE.relative_to(ROOT)}` "
            "manually — V7.8 deliberately does NOT fetch live prices."
        )
    else:
        _render_sector_etf_scoreboard_table(st, snapshot.sector_etf_rows)

    # 5. Economic event calendar.
    st.subheader("Economic event calendar")
    if not snapshot.event_calendar_rows:
        st.info(
            "Event calendar CSV is empty. Populate "
            f"`{DEFAULT_EVENT_CALENDAR_FILE.relative_to(ROOT)}` "
            "manually. The platform does not scrape any calendar."
        )
    else:
        _render_event_calendar_table(st, snapshot.event_calendar_rows)

    # 6. Data gaps — make the no-live-fetch contract explicit.
    st.markdown("---")
    st.subheader("Data gaps")
    gaps = data_gaps(snapshot)
    if not gaps:
        st.success("No empty panels. (Still no live data was fetched.)")
    else:
        for g in gaps:
            st.markdown(f"- {g}")
        st.caption(
            "**No live data fetch occurred during this render.** All "
            "values are read verbatim from local CSVs. Empty surfaces "
            "stay empty until the operator populates them."
        )

    # 7. Collapsed future-options-risk note.
    with st.expander(
        "Future options-risk overlay (deferred)",
        expanded=False,
    ):
        st.markdown(
            "The ThetaData options-risk overlay (skew, term structure, "
            "implied vs realised) is **deferred** to a later "
            "pre-registered phase (tentatively V7.8.2 or V7.7). **No "
            "options data is fetched in V7.8.** This note is here so the "
            "operator knows where it would live, not to imply imminent "
            "work."
        )


def _render_regime_panel_card(
    st, panel: str, rows: list[RegimeRow],
) -> None:  # pragma: no cover
    if not rows:
        st.markdown(
            f'<div class="platform-card"><h3>{panel}</h3>'
            f'<div class="big">—</div>'
            f'<div style="opacity:0.7">(empty panel)</div></div>',
            unsafe_allow_html=True,
        )
        return
    # Headline = first row's status + indicator; rest in a tiny list.
    head = rows[0]
    head_col = _REGIME_STATUS_COLOURS.get(head.status, "#34495E")
    extras = "".join(
        f'<li>{r.indicator}: {r.value} '
        f'<span style="opacity:0.6">[{r.status}]</span></li>'
        for r in rows[1:]
    )
    extras_block = (
        f'<ul style="margin:6px 0 0 14px; padding:0; opacity:0.85; '
        f'font-size:12px">{extras}</ul>' if extras else ""
    )
    st.markdown(
        f'<div class="platform-card" '
        f'style="border-left: 4px solid {head_col};">'
        f'<h3>{panel}</h3>'
        f'<div class="big">{head.value}</div>'
        f'<div><strong>{head.indicator}</strong> '
        f'<span class="pill" style="background-color:{head_col}; '
        f'color:#0e1117; padding:2px 8px; border-radius:999px; '
        f'font-size:11px; font-weight:700">{head.status}</span></div>'
        f'<div style="opacity:0.7; font-size:12px; margin-top:4px">'
        f'{head.interpretation}</div>'
        f'{extras_block}'
        f'</div>',
        unsafe_allow_html=True,
    )


def _render_sector_etf_scoreboard_table(
    st, rows: list[SectorETFRow],
) -> None:  # pragma: no cover
    header = (
        '<table style="width:100%; border-collapse:collapse; '
        'background-color:#1c2230; border:1px solid #2a3142;">'
        '<thead><tr style="text-align:left; color:#8a93a6;">'
        '<th style="padding:8px">Ticker</th>'
        '<th style="padding:8px">Sector</th>'
        '<th style="padding:8px">Theme</th>'
        '<th style="padding:8px">Price</th>'
        '<th style="padding:8px">1D</th>'
        '<th style="padding:8px">1W</th>'
        '<th style="padding:8px">1M</th>'
        '<th style="padding:8px">Trend</th>'
        '<th style="padding:8px">Note</th>'
        '</tr></thead><tbody>'
    )
    body = []
    for r in rows:
        col = _TREND_STATUS_COLOURS.get(r.trend_status, "#34495E")
        body.append(
            f'<tr style="border-top:1px solid #2a3142;">'
            f'<td style="padding:8px"><strong>{r.ticker}</strong></td>'
            f'<td style="padding:8px">{r.sector}</td>'
            f'<td style="padding:8px">{r.theme or "—"}</td>'
            f'<td style="padding:8px">{r.price or "—"}</td>'
            f'<td style="padding:8px">{r.return_1d or "—"}</td>'
            f'<td style="padding:8px">{r.return_1w or "—"}</td>'
            f'<td style="padding:8px">{r.return_1m or "—"}</td>'
            f'<td style="padding:8px; color:{col}">{r.trend_status}</td>'
            f'<td style="padding:8px">{r.risk_note or "—"}</td>'
            f'</tr>'
        )
    st.markdown(header + "".join(body) + "</tbody></table>",
                 unsafe_allow_html=True)


def _render_event_calendar_table(
    st, rows: list[EventCalendarRow],
) -> None:  # pragma: no cover
    header = (
        '<table style="width:100%; border-collapse:collapse; '
        'background-color:#1c2230; border:1px solid #2a3142;">'
        '<thead><tr style="text-align:left; color:#8a93a6;">'
        '<th style="padding:8px">Date</th>'
        '<th style="padding:8px">Time</th>'
        '<th style="padding:8px">Country</th>'
        '<th style="padding:8px">Event</th>'
        '<th style="padding:8px">Expected</th>'
        '<th style="padding:8px">Actual</th>'
        '<th style="padding:8px">Prior</th>'
        '<th style="padding:8px">Impact</th>'
        '<th style="padding:8px">Notes</th>'
        '</tr></thead><tbody>'
    )
    body = []
    for r in rows:
        col = _IMPACT_COLOURS.get(r.impact, "#34495E")
        body.append(
            f'<tr style="border-top:1px solid #2a3142;">'
            f'<td style="padding:8px">{r.date}</td>'
            f'<td style="padding:8px">{r.time or "—"}</td>'
            f'<td style="padding:8px">{r.country or "—"}</td>'
            f'<td style="padding:8px"><strong>{r.event}</strong></td>'
            f'<td style="padding:8px">{r.expected or "—"}</td>'
            f'<td style="padding:8px">{r.actual or "—"}</td>'
            f'<td style="padding:8px">{r.prior or "—"}</td>'
            f'<td style="padding:8px; color:{col}">{r.impact}</td>'
            f'<td style="padding:8px">{r.notes or "—"}</td>'
            f'</tr>'
        )
    st.markdown(header + "".join(body) + "</tbody></table>",
                 unsafe_allow_html=True)


def _render_daily_setup(st) -> None:  # pragma: no cover
    st.title("Daily Setup")
    _placeholder(
        st, "Daily Setup",
        "Future versions will compose a daily research brief.",
        [
            "market context",
            "watchlist",
            "bull / base / bear scenarios",
            "levels to watch",
            "event calendar",
        ],
    )


_PROTECTION_LABEL_COLOURS: dict[str, str] = {
    "OK": "#2ECC71",
    "WATCH": "#F39C12",
    "CONCENTRATION": "#9B59B6",
    "SECTOR_AT_RISK": "#E67E22",
    "SHARED_RISK_EXPOSED": "#E74C3C",
    "DATA_GAP": "#34495E",
}


def _render_protection(st) -> None:  # pragma: no cover
    st.title("Protection")
    snapshot = load_protection_snapshot()
    rows = derive_protection_rows_from_snapshot(snapshot)
    summary = compute_protection_summary(snapshot, rows)
    concentration = protection_concentration_panel(rows)
    gaps = protection_data_gaps(snapshot)

    # 0. Stale-as-entered banner.
    if snapshot.latest_as_of:
        st.caption(
            f"Latest position snapshot: **{snapshot.latest_as_of}**. "
            "**Research-only. No hedge order. No trade execution.** "
            "Labels are categorical and derived deterministically from "
            "already-loaded V6 / V7 artefacts."
        )
    else:
        st.info(
            "No positions on file — populate via "
            "`python scripts/populate_portfolio.py add-position …` first. "
            "Protection is a join of positions × V6 sector / V6.7 ledger "
            "/ V6.8 aggregation, so it needs positions to render anything."
        )

    # 1. Top summary cards.
    cols = st.columns(4)
    with cols[0]:
        st.markdown(
            f'<div class="platform-card"><h3>Positions</h3>'
            f'<div class="big">{summary.n_positions}</div>'
            f'<div>investable book (excl. CASH)</div></div>',
            unsafe_allow_html=True,
        )
    with cols[1]:
        st.markdown(
            f'<div class="platform-card"><h3>Total market value</h3>'
            f'<div class="big">{summary.total_market_value}</div>'
            f'<div>stale-as-entered</div></div>',
            unsafe_allow_html=True,
        )
    with cols[2]:
        st.markdown(
            f'<div class="platform-card" '
            f'style="border-left:4px solid #E74C3C;">'
            f'<h3>Risk-flagged</h3>'
            f'<div class="big">'
            f'{summary.n_sector_at_risk + summary.n_shared_risk_exposed}'
            f'</div>'
            f'<div>'
            f'{summary.n_sector_at_risk} SECTOR_AT_RISK · '
            f'{summary.n_shared_risk_exposed} SHARED_RISK</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    with cols[3]:
        st.markdown(
            f'<div class="platform-card" '
            f'style="border-left:4px solid #F39C12;">'
            f'<h3>WATCH / CONC / GAP</h3>'
            f'<div class="big">'
            f'{summary.n_watch + summary.n_concentration + summary.n_data_gap}'
            f'</div>'
            f'<div>'
            f'{summary.n_watch}W · {summary.n_concentration}C · '
            f'{summary.n_data_gap} gap</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # 2. Protection table.
    st.subheader("Protection labels by position")
    if not rows:
        st.caption("_(no positions to evaluate)_")
    else:
        _render_protection_table(st, rows)

    # 3. Concentration panel.
    st.subheader("Concentration view")
    cp1, cp2 = st.columns(2)
    with cp1:
        st.markdown(
            f"**Top {len(concentration['top_positions'])} positions "
            f"by weight**"
        )
        if not concentration["top_positions"]:
            st.caption("_(weights unavailable — needs numeric market_value)_")
        else:
            for ticker, w in concentration["top_positions"]:
                st.markdown(f"- {ticker}: **{w:.1f}%**")
    with cp2:
        st.markdown(
            f"**Top {len(concentration['top_sectors'])} sectors "
            "by aggregate weight**"
        )
        if not concentration["top_sectors"]:
            st.caption("_(sector aggregation unavailable)_")
        else:
            for sector, w in concentration["top_sectors"]:
                st.markdown(f"- {sector}: **{w:.1f}%**")

    # 4. Data gaps.
    st.markdown("---")
    st.subheader("Data gaps")
    if not gaps:
        st.success(
            "All Protection inputs present. (Still research-only; still "
            "no live data fetched.)"
        )
    else:
        for g in gaps:
            st.markdown(f"- {g}")

    # 5. Hard disclaimer footer (page-level — appears above the global one).
    st.markdown("---")
    st.error(
        "**Research-only.** No hedge order, no option execution, no trade "
        "execution. Protection labels are categorical research signals "
        "for operator review only. The platform does NOT place orders."
    )


def _render_protection_table(
    st, rows: list[ProtectionRow],
) -> None:  # pragma: no cover
    header = (
        '<table style="width:100%; border-collapse:collapse; '
        'background-color:#1c2230; border:1px solid #2a3142;">'
        '<thead><tr style="text-align:left; color:#8a93a6;">'
        '<th style="padding:8px">Ticker</th>'
        '<th style="padding:8px">Sector</th>'
        '<th style="padding:8px">Weight</th>'
        '<th style="padding:8px">Company read</th>'
        '<th style="padding:8px">Canonical signal</th>'
        '<th style="padding:8px">Company-derived</th>'
        '<th style="padding:8px">Headline</th>'
        '<th style="padding:8px">Why</th>'
        '<th style="padding:8px">Action</th>'
        '</tr></thead><tbody>'
    )
    body = []
    for r in rows:
        col = _PROTECTION_LABEL_COLOURS.get(r.protection_label, "#34495E")
        weight = (f"{float(r.portfolio_weight_pct):.1f}%"
                   if r.portfolio_weight_pct else "—")
        body.append(
            f'<tr style="border-top:1px solid #2a3142;">'
            f'<td style="padding:8px"><strong>{r.ticker}</strong></td>'
            f'<td style="padding:8px">{r.sector or "—"}</td>'
            f'<td style="padding:8px">{weight}</td>'
            f'<td style="padding:8px">{r.company_read or "—"}</td>'
            f'<td style="padding:8px">{r.canonical_sector_signal or "—"}</td>'
            f'<td style="padding:8px">'
            f'{r.company_derived_sector_read or "—"}</td>'
            f'<td style="padding:8px">'
            f'<span class="pill" style="background-color:{col}; '
            f'color:#0e1117; padding:2px 8px; border-radius:999px; '
            f'font-size:11px; font-weight:700">{r.protection_label}'
            f'</span></td>'
            f'<td style="padding:8px">{r.why_short or "—"}</td>'
            f'<td style="padding:8px">{r.action_short or "—"}</td>'
            f'</tr>'
        )
    st.markdown(header + "".join(body) + "</tbody></table>",
                 unsafe_allow_html=True)


def _render_transactions(st) -> None:  # pragma: no cover
    st.title("Transactions")
    tpath = find_transactions_file()
    if tpath is None:
        st.info(
            "No transactions CSV found at "
            f"`{DEFAULT_TRANSACTIONS_PATH.relative_to(ROOT)}`.\n\n"
            "V7.0 ships the transaction page as a placeholder — no "
            "manual editing UI, no broker connection."
        )
        return
    st.warning(
        "Read-only view of "
        f"`{tpath.relative_to(ROOT)}`. The platform never edits this "
        "file."
    )
    # Best-effort: render the CSV as a static table. We don't import
    # pandas to keep this surface light; just dump the raw text.
    try:
        text = tpath.read_text(encoding="utf-8")
    except OSError as exc:
        st.error(f"Could not read transactions file: {exc}")
        return
    st.code(text, language="csv")


def _render_reports(st) -> None:  # pragma: no cover
    st.title("Reports")
    files = list_reports()
    if not files:
        st.info(
            f"No report files found under "
            f"`{REPORT_ROOT.relative_to(ROOT)}`. The Reports page lists "
            "*.md / *.csv / *.txt files; nothing is opened or rewritten."
        )
        return
    st.caption(
        f"{len(files)} file(s) under `{REPORT_ROOT.relative_to(ROOT)}`. "
        "Paths only — the platform never opens or rewrites a report."
    )
    by_kind: dict[str, list[ReportFile]] = {}
    for f in files:
        by_kind.setdefault(f.kind, []).append(f)
    for kind in sorted(by_kind):
        st.subheader(kind)
        for f in by_kind[kind]:
            kb = f.size_bytes / 1024.0
            st.markdown(
                f"- `{f.relative_path}` — {kb:.1f} KB"
            )


def _render_glossary(st) -> None:  # pragma: no cover
    st.title("Glossary")
    for g in glossary_terms():
        st.markdown(f"### {g['term']}")
        st.markdown(g["definition"])


def _render_settings(st) -> None:  # pragma: no cover
    st.title("Settings / Guardrails")
    st.markdown(
        "These guardrails are project-level invariants. They are not "
        "user-toggleable from the platform."
    )
    rows = [
        ("LIVE_TRADING_ENABLED", "False",
         "Hard-coded in `src/quantbot/__init__.py`. Never flipped in v1."),
        ("Broker order execution", "disabled",
         "No broker, no order, no fill. Source-tree-wide guarantee."),
        ("IBKR order execution", "disabled",
         "If/when IBKR is ever used (V7.1+) it will be read-only."),
        ("Local-only", "yes",
         "The platform serves only on localhost via streamlit."),
        ("Read-only artefacts", "yes",
         "The platform never writes any CSV or report."),
        ("Live market data fetch in V7.0", "disabled",
         "No price feed, no news scrape, no options feed."),
    ]
    header = (
        '<table style="width:100%; border-collapse:collapse; '
        'background-color:#1c2230; border:1px solid #2a3142;">'
        '<thead><tr style="text-align:left; color:#8a93a6;">'
        '<th style="padding:8px">Guardrail</th>'
        '<th style="padding:8px">Status</th>'
        '<th style="padding:8px">Notes</th>'
        '</tr></thead><tbody>'
    )
    body = "".join(
        f'<tr style="border-top:1px solid #2a3142;">'
        f'<td style="padding:8px"><strong>{name}</strong></td>'
        f'<td style="padding:8px">{status}</td>'
        f'<td style="padding:8px">{note}</td>'
        f'</tr>'
        for name, status, note in rows
    )
    st.markdown(header + body + "</tbody></table>",
                 unsafe_allow_html=True)


# Entry point when run by streamlit.
if __name__ == "__main__":  # pragma: no cover
    render()
else:
    # Module import: nothing should run.
    pass


__all__ = [
    "PAGES", "DISCLAIMER", "GLOSSARY",
    "PlatformStatus", "SectorSummary", "ReportFile",
    "REPORT_EXTENSIONS",
    "collect_platform_status", "collect_sector_summaries",
    "latest_ledger_rows_per_company", "latest_aggregation_rows",
    "latest_signal_log_rows",
    "list_reports", "glossary_terms", "find_transactions_file",
    "render",
]
