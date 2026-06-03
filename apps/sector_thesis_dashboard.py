"""V6.5 Sector Thesis Tracker dashboard (local browser app, READ-ONLY).

Run with:
    python -m streamlit run apps/sector_thesis_dashboard.py

This is a **local browser application**, not a public website. It reads the
EXISTING CSV / Markdown artefacts produced by the V6.2 / V6.3 / V6.4 sector
trackers and renders them as a unified, card-based decision-support surface.

The dashboard:
  - reads files only — NEVER writes any data, NEVER fetches the network, NEVER
    sends a broker order, NEVER mutates state on disk
  - imports nothing from ``quantbot.backtest.broker`` / engine / IBKR / order
    modules
  - displays a persistent disclaimer that the output is a research signal —
    NOT a trading signal, NOT investment advice, NOT order execution
  - ``LIVE_TRADING_ENABLED`` stays ``False``

The pure helpers (``load_sector``, ``filter_catalysts``, ``top_bull_drivers``,
``top_risks``, ``manual_gaps``, ``cross_sector_links``, ``signal_color``,
``status_color``) live at the top of the module and are testable without
running streamlit.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

# Make the project's package importable when the script is run from anywhere.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from quantbot.research.sector_tracker import (
    Catalyst,
    Change,
    EmergencyExit,
    EventAnnotation,
    SectorAggregationRow,
    SectorScore,
    load_catalysts,
    load_change_log,
    load_event_annotations,
    load_exits,
    load_latest_aggregation_per_sector,
    score_sector,
)

DEFAULT_DATA_DIR = ROOT / "data" / "research" / "sector_tracker"
DEFAULT_REPORT_DIR = ROOT / "reports" / "research" / "sector_tracker"
DEFAULT_CHANGE_LOG_PATH = DEFAULT_DATA_DIR / "change_log.csv"
DEFAULT_ANNOTATIONS_PATH = DEFAULT_DATA_DIR / "event_annotations.csv"
# V6.8.1 — Optional read-only audit view; missing file is a friendly empty state.
DEFAULT_AGGREGATION_PATH = DEFAULT_DATA_DIR / "company_sector_aggregation.csv"

SECTORS: tuple[str, ...] = ("SEMICONDUCTOR", "AI", "ENERGY")

# Per-sector file conventions (mirror what the driver scripts produce).
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

# Pre-declared cross-sector links (catalysts / exits that describe the same
# scenario across two trackers). Adding a new link here is a documentation
# change, not a behaviour change.
CROSS_SECTOR_LINKS: list[dict[str, str]] = [
    {
        "left_sector": "AI", "left_id": "AI-EXIT-HYPERSCALER-CAPEX-CUT",
        "right_sector": "ENERGY",
        "right_id": "ENER-EXIT-DATACENTER-CAPEX-CUT",
        "note": ("Hyperscaler capex pullback propagates from the AI tracker "
                 "into the Energy data-center-power demand thesis."),
    },
    {
        "left_sector": "AI", "left_id": "AI-EXIT-HYPERSCALER-CAPEX-CUT",
        "right_sector": "ENERGY",
        "right_id": "ENER-EXIT-AI-POWER-NARRATIVE-REVERSAL",
        "note": ("If hyperscaler capex narrative reverses, the energy "
                 "tracker's AI-power narrative exit follows."),
    },
    {
        "left_sector": "SEMICONDUCTOR", "left_id": "SEMI-CUSTOM-SILICON-T2",
        "right_sector": "AI", "right_id": "AI-CUSTOM-SILICON-T2",
        "note": ("Same scenario: hyperscaler custom-silicon displacement of "
                 "merchant accelerators — tracked in both sectors."),
    },
]

# Signal label -> hex colour for the top summary cards.
SIGNAL_COLOURS: dict[str, str] = {
    "ACCUMULATE": "#2ECC71",
    "SELECTIVE_BUY": "#58D68D",
    "HOLD": "#95A5A6",
    "AVOID_NEW_BUY": "#F39C12",
    "REDUCE": "#E67E22",
    "EXIT_WATCH": "#E74C3C",
}

# Catalyst status -> hex colour for the per-card status pill.
STATUS_COLOURS: dict[str, str] = {
    "BULL": "#2ECC71",
    "NEUTRAL": "#7F8C8D",
    "NEAR_THRESHOLD": "#F39C12",
    "BROKEN": "#E74C3C",
}

# Exit current_status -> hex colour.
EXIT_COLOURS: dict[str, str] = {
    "INACTIVE": "#7F8C8D",
    "MONITORING": "#F39C12",
    "TRIGGERED": "#E74C3C",
}

DISCLAIMER = (
    "**This is a research signal, not a trading signal, not investment "
    "advice, and not order execution. No live trading is performed. "
    "`LIVE_TRADING_ENABLED` remains `False`.**"
)


# --------------------------------------------------------------------------- #
# Pure helpers (no streamlit calls — fully testable)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class SectorData:
    """Loaded view of one sector's artefacts.

    ``missing_files`` lists any artefact that wasn't found on disk; the
    dashboard renders a warning for that sector instead of crashing.
    """

    sector: str
    catalysts: list[Catalyst] = field(default_factory=list)
    exits: list[EmergencyExit] = field(default_factory=list)
    score: SectorScore | None = None
    report_md: str = ""
    missing_files: list[str] = field(default_factory=list)


def load_sector(sector: str,
                data_dir: str | Path | None = None,
                report_dir: str | Path | None = None) -> SectorData:
    """Read one sector's CSVs + MD report from disk. Never raises on missing
    files — returns a degraded ``SectorData`` instead so the UI can warn."""
    ddir = Path(data_dir) if data_dir else DEFAULT_DATA_DIR
    rdir = Path(report_dir) if report_dir else DEFAULT_REPORT_DIR
    cfg = SECTOR_FILES.get(sector)
    if cfg is None:
        return SectorData(sector=sector, missing_files=["<unknown sector>"])

    missing: list[str] = []
    cat_path = ddir / cfg["catalysts"]
    exit_path = ddir / cfg["exits"]
    rpt_path = rdir / cfg["report"]

    catalysts: list[Catalyst] = []
    exits: list[EmergencyExit] = []
    report_md = ""

    if cat_path.is_file():
        catalysts = load_catalysts(cat_path)
    else:
        missing.append(str(cat_path))
    if exit_path.is_file():
        exits = load_exits(exit_path)
    else:
        missing.append(str(exit_path))
    if rpt_path.is_file():
        report_md = rpt_path.read_text(encoding="utf-8")
    else:
        missing.append(str(rpt_path))

    score: SectorScore | None = None
    if catalysts or exits:
        # Recompute the score from the loaded artefacts — independent of any
        # stale value embedded in the markdown report.
        score = score_sector(catalysts, exits, sector=sector)

    return SectorData(sector=sector, catalysts=catalysts, exits=exits,
                       score=score, report_md=report_md,
                       missing_files=missing)


def load_all_sectors(data_dir: str | Path | None = None,
                     report_dir: str | Path | None = None
                     ) -> dict[str, SectorData]:
    """Load every known sector. Missing artefacts surface as
    ``SectorData.missing_files`` entries."""
    return {s: load_sector(s, data_dir, report_dir) for s in SECTORS}


def filter_catalysts(catalysts: list[Catalyst], *,
                     sectors: set[str] | None = None,
                     subsectors: set[str] | None = None,
                     tiers: set[int] | None = None,
                     statuses: set[str] | None = None,
                     source_types: set[str] | None = None,
                     ) -> list[Catalyst]:
    """Apply each non-None filter as an inclusive set match."""
    out = list(catalysts)
    if sectors:
        out = [c for c in out if c.sector in sectors]
    if subsectors:
        out = [c for c in out if c.subsector in subsectors]
    if tiers:
        out = [c for c in out if c.tier in tiers]
    if statuses:
        out = [c for c in out if c.status in statuses]
    if source_types:
        out = [c for c in out if c.source_type in source_types]
    return out


def top_bull_drivers(catalysts: list[Catalyst], top_k: int = 8
                     ) -> list[Catalyst]:
    """Most-important BULL catalysts across the supplied set: Tier 1 first,
    then by sector/name for stable ordering."""
    bulls = [c for c in catalysts if c.status == "BULL"]
    bulls.sort(key=lambda c: (c.tier, c.sector, c.catalyst_name))
    return bulls[:top_k]


def top_risks(catalysts: list[Catalyst], top_k: int = 8) -> list[Catalyst]:
    """BROKEN catalysts first, then NEAR_THRESHOLD, Tier 1 within each."""
    rank = {"BROKEN": 0, "NEAR_THRESHOLD": 1}
    risks = [c for c in catalysts if c.status in rank]
    risks.sort(key=lambda c: (rank[c.status], c.tier, c.sector, c.catalyst_name))
    return risks[:top_k]


def manual_gaps(catalysts: list[Catalyst]) -> list[Catalyst]:
    """Every catalyst whose source is MANUAL or carries a stale-data note."""
    return [c for c in catalysts
            if c.source_type == "MANUAL"
            or "NOT FOUND" in c.source_detail
            or "(NOT cached" in c.source_detail
            or "stale" in c.source_detail.lower()]


def cross_sector_links() -> list[dict[str, str]]:
    """Pre-declared scenario links between trackers (read-only constant)."""
    return list(CROSS_SECTOR_LINKS)


def signal_color(signal: str) -> str:
    return SIGNAL_COLOURS.get(signal, "#95A5A6")


def status_color(status: str) -> str:
    return STATUS_COLOURS.get(status, "#7F8C8D")


def exit_color(status: str) -> str:
    return EXIT_COLOURS.get(status, "#7F8C8D")


def aggregate_status_counts(catalysts: list[Catalyst]) -> dict[str, int]:
    """Per-status counts (BULL/NEUTRAL/NEAR_THRESHOLD/BROKEN) across a set."""
    return {
        "BULL": sum(1 for c in catalysts if c.status == "BULL"),
        "NEUTRAL": sum(1 for c in catalysts if c.status == "NEUTRAL"),
        "NEAR_THRESHOLD": sum(1 for c in catalysts
                              if c.status == "NEAR_THRESHOLD"),
        "BROKEN": sum(1 for c in catalysts if c.status == "BROKEN"),
    }


# --------------------------------------------------------------------------- #
# V6.6 — change log + event annotations (read-only loaders + filters)
# --------------------------------------------------------------------------- #
def load_change_log_safe(path: str | Path | None = None) -> list[Change]:
    """Read the change log if present. Never raises — returns ``[]`` on
    missing file or invalid schema (so a corrupted CSV doesn't crash the UI)."""
    p = Path(path) if path else DEFAULT_CHANGE_LOG_PATH
    try:
        return load_change_log(p) if p.is_file() else []
    except Exception:
        return []


def load_event_annotations_safe(
    path: str | Path | None = None,
) -> list[EventAnnotation]:
    """Read the annotation file if present. Never raises."""
    p = Path(path) if path else DEFAULT_ANNOTATIONS_PATH
    try:
        return load_event_annotations(p) if p.is_file() else []
    except Exception:
        return []


def recent_changes(changes: list[Change], *,
                   sectors: set[str] | None = None,
                   top_k: int = 20) -> list[Change]:
    """Sort changes newest-first; optionally filter by sector; cap at top_k."""
    out = list(changes)
    if sectors:
        out = [c for c in out if c.sector in sectors]
    # Sort by timestamp descending; ties broken by record_id for stable order.
    out.sort(key=lambda c: (c.timestamp, c.record_id), reverse=True)
    return out[:top_k]


def annotations_for(annotations: list[EventAnnotation],
                    related_id: str) -> list[EventAnnotation]:
    """All annotations attached to ``related_id``, newest-first."""
    return sorted(
        [a for a in annotations if a.related_id == related_id],
        key=lambda a: a.timestamp, reverse=True,
    )


def is_degradation(change: Change) -> bool:
    """True if the change moved a status to a worse bucket
    (NEAR_THRESHOLD or BROKEN) — used for visual highlighting."""
    if change.field_changed not in {"status", "current_status"}:
        return False
    return change.new_status in {"NEAR_THRESHOLD", "BROKEN"} \
        and change.prior_status not in {"NEAR_THRESHOLD", "BROKEN"}


# --------------------------------------------------------------------------- #
# V6.5.1 — Executive view + Company lens (pure helpers)
# --------------------------------------------------------------------------- #
# Plain-English interpretation per signal label. Pre-declared text, not
# generated; matches the V6.1 scoring bands.
SIGNAL_INTERPRETATION: dict[str, str] = {
    "ACCUMULATE": "Strong bullish across catalysts — sector thesis on track.",
    "SELECTIVE_BUY": ("Constructive but mixed — adds warranted on selective "
                       "evidence."),
    "HOLD": "Balanced picture; no strong directional signal.",
    "AVOID_NEW_BUY": "Soft picture; pause new adds; monitor closely.",
    "REDUCE": "Negative drivers dominate; reduce sleeve weight.",
    "EXIT_WATCH": "Multiple major risks active; defensive posture.",
}

# Pre-declared company → catalyst-ID mapping. Adding or removing an entry is
# a configuration change, not a behaviour change. NEVER invents a company
# score — the read is derived from the linked catalysts' existing statuses.
COMPANY_CATALYSTS: dict[str, list[dict]] = {
    "SEMICONDUCTOR": [
        {"ticker": "NVDA", "subsector_theme": "AI accelerator",
         "catalysts": ["SEMI-NVDA-REV-T1", "SEMI-NVDA-GM-T1",
                       "SEMI-NVDA-DC-REV-T1", "SEMI-INVENTORY-CYCLE-T2"]},
        {"ticker": "AMD", "subsector_theme": "AI accelerator",
         "catalysts": ["SEMI-AMD-REV-T2", "SEMI-INVENTORY-CYCLE-T2"]},
        {"ticker": "AVGO", "subsector_theme": "AI custom silicon / networking",
         "catalysts": ["SEMI-AVGO-REV-T2", "SEMI-INVENTORY-CYCLE-T2"]},
        {"ticker": "MU", "subsector_theme": "memory / HBM",
         "catalysts": ["SEMI-MU-HBM-REV-T1", "SEMI-MU-MEMCYCLE-NI-T1",
                       "SEMI-INVENTORY-CYCLE-T2"]},
        {"ticker": "AMAT", "subsector_theme": "wafer-fab equipment",
         "catalysts": ["SEMI-EQUIPMENT-DEMAND-T2"]},
        {"ticker": "LRCX", "subsector_theme": "wafer-fab equipment",
         "catalysts": ["SEMI-EQUIPMENT-DEMAND-T2"]},
        {"ticker": "KLAC", "subsector_theme": "wafer-fab equipment",
         "catalysts": ["SEMI-EQUIPMENT-DEMAND-T2"]},
        {"ticker": "TSM", "subsector_theme": "foundry",
         "catalysts": ["SEMI-TSM-N3-DEMAND-T1"]},
        {"ticker": "ASML", "subsector_theme": "lithography / EUV",
         "catalysts": ["SEMI-ASML-BOOKINGS-T1"]},
    ],
    "AI": [
        {"ticker": "MSFT", "subsector_theme": "hyperscaler",
         "catalysts": ["AI-MSFT-REV-T1", "AI-MSFT-OPMARGIN-T2",
                       "AI-HYPERSCALER-CAPEX-T1"]},
        {"ticker": "GOOGL", "subsector_theme": "hyperscaler",
         "catalysts": ["AI-GOOGL-REV-T1", "AI-GOOGL-OPMARGIN-T2",
                       "AI-HYPERSCALER-CAPEX-T1"]},
        {"ticker": "AMZN", "subsector_theme": "hyperscaler",
         "catalysts": ["AI-AMZN-REV-T1", "AI-HYPERSCALER-CAPEX-T1"]},
        {"ticker": "META", "subsector_theme": "hyperscaler",
         "catalysts": ["AI-META-REV-T1", "AI-HYPERSCALER-CAPEX-T1"]},
        {"ticker": "ORCL", "subsector_theme": "cloud infrastructure",
         "catalysts": ["AI-ORCL-REV-T1"]},
        {"ticker": "PLTR", "subsector_theme": "enterprise AI",
         "catalysts": ["AI-PLTR-REV-T2"]},
        {"ticker": "OpenAI",  "subsector_theme": "frontier AI lab (private)",
         "catalysts": ["AI-OPENAI-ARR-T1"]},
        {"ticker": "Anthropic", "subsector_theme": "frontier AI lab (private)",
         "catalysts": ["AI-ANTHROPIC-ARR-T1"]},
    ],
    "ENERGY": [
        {"ticker": "GEV", "subsector_theme": "AI power / turbines",
         "catalysts": ["ENER-GEV-REV-T1"]},
        {"ticker": "ETN", "subsector_theme": "AI power / electrical",
         "catalysts": ["ENER-ETN-REV-T1"]},
        {"ticker": "VRT", "subsector_theme": "AI power / data-center",
         "catalysts": ["ENER-VRT-REV-T1"]},
        {"ticker": "PWR", "subsector_theme": "AI power / grid construction",
         "catalysts": ["ENER-PWR-REV-T1"]},
        {"ticker": "CEG", "subsector_theme": "AI power / nuclear",
         "catalysts": ["ENER-CEG-REV-T1"]},
        {"ticker": "NEE", "subsector_theme": "utility / renewables",
         "catalysts": ["ENER-NEE-REV-T2"]},
        {"ticker": "SO",  "subsector_theme": "utility",
         "catalysts": ["ENER-SO-REV-T2"]},
        {"ticker": "XOM", "subsector_theme": "integrated oil & gas",
         "catalysts": ["ENER-XOM-REV-T1", "ENER-OILGAS-OCF-T2"]},
        {"ticker": "CVX", "subsector_theme": "integrated oil & gas",
         "catalysts": ["ENER-CVX-REV-T1", "ENER-OILGAS-OCF-T2"]},
        {"ticker": "COP", "subsector_theme": "US shale / upstream",
         "catalysts": ["ENER-COP-REV-T2", "ENER-OILGAS-OCF-T2"]},
    ],
}


@dataclass(frozen=True)
class ExecutiveSummary:
    """Plain-English roll-up of one sector's signal. Composed entirely from
    existing ``SectorScore`` data — NEVER invents new scores."""

    sector: str
    signal: str
    normalized_score: float
    interpretation: str
    top_bull_drivers: list[str] = field(default_factory=list)  # up to 2 names
    top_risks: list[str] = field(default_factory=list)        # up to 2 names
    what_to_watch: str = ""


@dataclass(frozen=True)
class CompanyLensRow:
    """One row of the company-lens table.

    ``current_read`` is a string in ``{BULL, NEUTRAL, NEAR_THRESHOLD, BROKEN,
    MIXED, TRACKED, N/A}``. It is derived from the company's linked catalysts'
    current statuses via :func:`derive_company_read` — not from any
    company-level score.

    ``why_short`` and ``main_risk_short`` are short investor-readable phrases
    surfaced to the V6.5.2 visible table; the full linked catalyst IDs and
    the longer composed ``reason`` stay available via a per-row expander.
    """

    ticker: str
    sector: str
    subsector_theme: str
    linked_catalyst_ids: list[str]
    n_linked_present: int     # how many linked IDs were actually loaded
    current_read: str
    reason: str
    why_short: str = ""        # V6.5.2 — short "why it matters" phrase
    main_risk_short: str = ""  # V6.5.2 — short "main risk / note" phrase


# Order in which "current_read" labels render from worst to best.
READ_ORDER: list[str] = [
    "BROKEN", "NEAR_THRESHOLD", "MIXED", "NEUTRAL", "TRACKED", "BULL", "N/A",
]
READ_COLOURS: dict[str, str] = {
    "BULL": "#2ECC71",
    "NEUTRAL": "#7F8C8D",
    "NEAR_THRESHOLD": "#F39C12",
    "BROKEN": "#E74C3C",
    "MIXED": "#3498DB",
    "TRACKED": "#9B59B6",
    "N/A": "#34495E",
}


def make_executive_summary(sd: SectorData) -> ExecutiveSummary:
    """Compose an :class:`ExecutiveSummary` from a loaded :class:`SectorData`.

    If the sector has no score (artefacts missing), the summary's
    ``interpretation`` is a friendly placeholder rather than fabricated text.
    """
    if sd.score is None:
        return ExecutiveSummary(
            sector=sd.sector, signal="N/A", normalized_score=0.0,
            interpretation="Sector artefacts not loaded — run the driver to "
                            "populate this view.",
            top_bull_drivers=[], top_risks=[],
            what_to_watch="No data yet.",
        )
    bulls = top_bull_drivers(sd.catalysts, top_k=2)
    risks = top_risks(sd.catalysts, top_k=2)
    interp = SIGNAL_INTERPRETATION.get(
        sd.score.signal, "Signal not recognised."
    )
    # What to watch: prefer the worst-bucketed catalyst still in play.
    if sd.score.emergency_triggered:
        what = ("Emergency exit triggered: "
                f"{', '.join(sd.score.triggered_exits)} — review sleeve.")
    elif sd.score.n_broken:
        worst = next((c for c in sd.catalysts if c.status == "BROKEN"), None)
        what = (f"Watch `{worst.catalyst_id}` (currently BROKEN) for further "
                "deterioration."
                if worst else "Multiple catalysts broken — watch monthly refresh.")
    elif sd.score.n_near_threshold:
        near = next((c for c in sd.catalysts if c.status == "NEAR_THRESHOLD"),
                    None)
        what = (f"Watch `{near.catalyst_id}` (NEAR_THRESHOLD) — small further "
                "deterioration would push it BROKEN."
                if near else "Watch near-threshold catalysts for status moves.")
    else:
        what = ("No near-threshold or broken catalysts — watch next monthly "
                "refresh for early signs of deterioration.")
    return ExecutiveSummary(
        sector=sd.sector, signal=sd.score.signal,
        normalized_score=sd.score.normalized_score,
        interpretation=interp,
        top_bull_drivers=[c.catalyst_name for c in bulls],
        top_risks=[c.catalyst_name for c in risks],
        what_to_watch=what,
    )


def _short_reason(focus: list[Catalyst], status_counts: dict[str, int]) -> str:
    """Build a short readable reason for a company-lens row.

    Mentions up to 2 focal catalysts with their current_value, plus a count
    summary like ``(2 BULL, 1 NEUTRAL)``. Truncates long current_value strings.
    """
    parts: list[str] = []
    for c in focus[:2]:
        cv = (c.current_value or "n/a").strip()
        if len(cv) > 32:
            cv = cv[:29] + "..."
        # Compact label from the catalyst_id tail (drops sector prefix).
        bits = c.catalyst_id.split("-", 2)
        label = bits[-1] if len(bits) > 1 else c.catalyst_id
        parts.append(f"{label} {cv}")
    summary = " · ".join(
        f"{n} {s}" for s, n in sorted(status_counts.items())
    )
    return "; ".join(parts) + f" ({summary})" if parts else summary


def derive_company_read(
    catalysts_by_id: dict[str, Catalyst],
    linked_ids: list[str],
) -> tuple[str, str, int]:
    """Return ``(current_read, reason, n_present)`` for one company.

    V6.5.2 rules — derived ENTIRELY from existing catalysts' statuses; no new
    scoring. **Key change vs V6.5.1**: when BULL coexists with BROKEN or
    NEAR_THRESHOLD, the read is ``MIXED`` (not ``BROKEN``/``NEAR_THRESHOLD``
    only). The user's directive: *"Do not hide bullish evidence just because
    one shared risk is broken."* The reason text surfaces both sides.

    Order of evaluation:

    1. No linked catalyst found in the loaded data → ``"N/A"``.
    2. All present catalysts are MANUAL/NEUTRAL (placeholder default)
       → ``"TRACKED"``.
    3. BULL + BROKEN coexist → ``"MIXED"`` (with BULL+BROKEN reason).
    4. BROKEN only (no BULL counterweight) → ``"BROKEN"``.
    5. BULL + NEAR_THRESHOLD coexist → ``"MIXED"``.
    6. NEAR_THRESHOLD only → ``"NEAR_THRESHOLD"``.
    7. All BULL → ``"BULL"``.
    8. All NEUTRAL → ``"NEUTRAL"``.
    9. BULL + NEUTRAL (no negatives) → ``"MIXED"``.
    """
    found = [catalysts_by_id[i] for i in linked_ids if i in catalysts_by_id]
    if not found:
        return "N/A", "no linked catalysts loaded — check driver output", 0
    n_present = len(found)
    if all(c.source_type == "MANUAL" and c.status == "NEUTRAL" for c in found):
        return ("TRACKED", "tracked context / no direct signal yet "
                "(manual placeholders only)", n_present)
    statuses = [c.status for c in found]
    status_counts = {s: statuses.count(s) for s in set(statuses)}
    has_bull = "BULL" in statuses
    has_broken = "BROKEN" in statuses
    has_near = "NEAR_THRESHOLD" in statuses
    has_neutral = "NEUTRAL" in statuses

    # V6.5.2: BULL + BROKEN → MIXED (surface both sides, never hide bull).
    if has_bull and has_broken:
        return "MIXED", _mixed_reason(found, status_counts), n_present
    if has_broken:
        focus = [c for c in found if c.status == "BROKEN"]
        return "BROKEN", _short_reason(focus, status_counts), n_present
    # V6.5.2: BULL + NEAR_THRESHOLD → MIXED.
    if has_bull and has_near:
        return "MIXED", _mixed_reason(found, status_counts), n_present
    if has_near:
        focus = [c for c in found if c.status == "NEAR_THRESHOLD"]
        return "NEAR_THRESHOLD", _short_reason(focus, status_counts), n_present
    if has_bull and not has_neutral:
        focus = [c for c in found if c.status == "BULL"]
        return "BULL", _short_reason(focus, status_counts), n_present
    if not has_bull and has_neutral and not has_broken and not has_near:
        return "NEUTRAL", _short_reason(found, status_counts), n_present
    # Mixed BULL + NEUTRAL (no negatives) — V6.5.1 already returned MIXED.
    return "MIXED", _mixed_reason(found, status_counts), n_present


def _mixed_reason(found: list[Catalyst],
                   status_counts: dict[str, int]) -> str:
    """V6.5.2 — for MIXED reads, surface a BULL focal AND a risk focal so
    bullish evidence isn't hidden by the worst-bucket headline."""
    bulls = [c for c in found if c.status == "BULL"]
    brokens = [c for c in found if c.status == "BROKEN"]
    nears = [c for c in found if c.status == "NEAR_THRESHOLD"]
    parts: list[str] = []
    if bulls:
        b = bulls[0]
        parts.append(
            f"{_compact_label(b)} {(b.current_value or '').strip()} BULL"
        )
    if brokens:
        x = brokens[0]
        parts.append(
            f"but {_compact_label(x)} "
            f"{(x.current_value or '').strip()} BROKEN"
        )
    elif nears:
        n = nears[0]
        parts.append(
            f"but {_compact_label(n)} "
            f"{(n.current_value or '').strip()} NEAR_THRESHOLD"
        )
    summary = " · ".join(
        f"{n_count} {s}" for s, n_count in sorted(status_counts.items())
    )
    return ("; ".join(parts) + f" ({summary})") if parts else summary


def _compact_label(c: Catalyst) -> str:
    """Best-effort short human-readable label derived from the catalyst.

    Strips sector prefix + tier suffix from the catalyst_id and uses a small
    pre-declared lookup; falls back to a title-cased version of the tail.
    Visible in the company table's `why` / `main risk` columns so the reader
    sees `"Revenue +65.5%"` instead of `"AI-MSFT-REV-T1 +65.5%"`.
    """
    parts = c.catalyst_id.split("-")
    if parts and parts[0] in {"SEMI", "AI", "ENER"}:
        parts = parts[1:]
    if parts and parts[-1].startswith("T") and parts[-1][1:].isdigit():
        parts = parts[:-1]
    key = "-".join(parts)
    lookup = {
        # Headline labels used in the V6.5.2 visible table
        "NVDA-REV": "Revenue",
        "NVDA-GM": "Gross margin",
        "NVDA-DC-REV": "DC revenue",
        "AMD-REV": "Revenue",
        "AVGO-REV": "Revenue",
        "MU-HBM-REV": "HBM revenue",
        "MU-MEMCYCLE-NI": "Memory NI",
        "INVENTORY-CYCLE": "Inventory cycle",
        "EQUIPMENT-DEMAND": "Equipment demand",
        "TSM-N3-DEMAND": "Advanced-node demand",
        "ASML-BOOKINGS": "EUV bookings",
        "MSFT-REV": "Revenue",
        "GOOGL-REV": "Revenue",
        "AMZN-REV": "Revenue",
        "META-REV": "Revenue",
        "ORCL-REV": "Revenue",
        "PLTR-REV": "Revenue",
        "MSFT-OPMARGIN": "Op margin",
        "GOOGL-OPMARGIN": "Op margin",
        "HYPERSCALER-CAPEX": "Hyperscaler capex",
        "RD-GROWTH": "R&D growth",
        "OPENAI-ARR": "OpenAI ARR",
        "ANTHROPIC-ARR": "Anthropic ARR",
        "REGULATION-RISK": "Regulation risk",
        "MODEL-PRICING": "Model pricing",
        "ENTERPRISE-ROI": "Enterprise AI ROI",
        "CUSTOM-SILICON": "Custom-silicon risk",
        "GEV-REV": "Revenue",
        "ETN-REV": "Revenue",
        "VRT-REV": "Revenue",
        "PWR-REV": "Revenue",
        "CEG-REV": "Revenue",
        "NEE-REV": "Revenue",
        "SO-REV": "Revenue",
        "XOM-REV": "Revenue",
        "CVX-REV": "Revenue",
        "COP-REV": "Revenue",
        "OILGAS-OCF": "Oil & gas OCF",
        "DATACENTER-POWER-DEMAND": "Data-center power",
        "NUCLEAR-SMR": "Nuclear/SMR",
        "REGULATORY-RATECASE": "Rate-case risk",
        "COMMODITY-OIL": "Crude oil",
        "LNG-CONTRACTS": "LNG contracts",
        "MACRO-RATES": "Long-end rates",
        "MACRO-VOL": "VIX",
        "MACRO-CURVE": "2s10s curve",
        "CHINA-EXPORT-RISK": "China export risk",
        "OPTIONS-RISK": "Options-market risk",
    }
    if key in lookup:
        return lookup[key]
    # Fallback: title-case last 1-2 parts
    return " ".join(p.title().replace("_", " ") for p in parts[-2:]) \
        if parts else c.catalyst_id


def company_view_strings(found: list[Catalyst]) -> tuple[str, str]:
    """Return ``(why_short, main_risk_short)`` for the V6.5.2 company table.

    Pure — derived from the company's loaded catalysts. ``"—"`` is the
    placeholder for "no main risk currently".
    """
    if not found:
        return "no linked catalysts loaded", "—"
    if all(c.source_type == "MANUAL" and c.status == "NEUTRAL" for c in found):
        return "tracked context only", "—"

    bulls = [c for c in found if c.status == "BULL"]
    brokens = [c for c in found if c.status == "BROKEN"]
    nears = [c for c in found if c.status == "NEAR_THRESHOLD"]
    neutrals = [c for c in found if c.status == "NEUTRAL"]

    if bulls:
        b = bulls[0]
        why_short = f"{_compact_label(b)} {(b.current_value or '').strip()}"
    elif neutrals and any(c.source_type != "MANUAL" for c in neutrals):
        c = next(c for c in neutrals if c.source_type != "MANUAL")
        why_short = (f"{_compact_label(c)} "
                     f"{(c.current_value or '').strip()} (in-band)")
    else:
        why_short = "—"

    if brokens:
        x = brokens[0]
        main_risk_short = (f"{_compact_label(x)} "
                            f"{(x.current_value or '').strip()} BROKEN")
    elif nears:
        n = nears[0]
        main_risk_short = (f"{_compact_label(n)} "
                            f"{(n.current_value or '').strip()} NEAR")
    else:
        main_risk_short = "—"
    return why_short, main_risk_short


@dataclass(frozen=True)
class WatchItem:
    """One row of the V6.5.2 "Things worth watching" curated list.

    ``level`` is one of ``"broken"`` / ``"near"`` / ``"bull"`` /
    ``"linkage"`` — drives the colour pip in the renderer. Derived strictly
    from the loaded catalysts; never invents values.
    """

    sector: str
    level: str
    text: str


def things_worth_watching(
    sectors_data: dict[str, SectorData], *,
    sectors: set[str] | None = None,
) -> list[WatchItem]:
    """Curated list of headline observations across the loaded sectors.

    Strict derivation rules:

    * BROKEN catalysts first (worst-bucket priority).
    * NEAR_THRESHOLD next.
    * Top 2 BULL auto-derived catalysts per sector (manual catalysts skipped —
      they can't be a headline).
    * One cross-sector linkage when SEMI inventory is BROKEN AND there's a
      bullish AI catalyst — this matches the user's example: "NVDA revenue
      strong but inventory cycle risk affects semi names".

    The function NEVER invents numbers — every text snippet is composed from
    a loaded catalyst's ``catalyst_name`` and ``current_value``.
    """
    items: list[WatchItem] = []
    sec_iter = sectors if sectors is not None else set(SECTORS)
    for sec in SECTORS:
        if sec not in sec_iter:
            continue
        sd = sectors_data.get(sec)
        if not sd or not sd.catalysts:
            continue
        # Broken first (worst bucket).
        for c in sd.catalysts:
            if c.status == "BROKEN":
                items.append(WatchItem(
                    sector=sec, level="broken",
                    text=(f"{c.catalyst_name} is BROKEN at "
                          f"{(c.current_value or 'n/a').strip()}"),
                ))
        # NEAR_THRESHOLD second.
        for c in sd.catalysts:
            if c.status == "NEAR_THRESHOLD":
                items.append(WatchItem(
                    sector=sec, level="near",
                    text=(f"{c.catalyst_name} is NEAR_THRESHOLD at "
                          f"{(c.current_value or 'n/a').strip()}"),
                ))
        # Top BULL drivers (auto-derived only — manual is not a headline).
        bulls = [c for c in sd.catalysts
                 if c.status == "BULL"
                 and c.source_type in {"SEC_EDGAR", "FRED", "YFINANCE"}
                 and "stale" not in c.source_detail.lower()]
        bulls.sort(key=lambda c: (c.tier, c.catalyst_name))
        for c in bulls[:2]:
            items.append(WatchItem(
                sector=sec, level="bull",
                text=(f"{c.catalyst_name} is BULL at "
                      f"{(c.current_value or 'n/a').strip()}"),
            ))

    # Cross-sector linkage: SEMI inventory BROKEN with AI signals → flag it.
    if sec_iter == set(SECTORS):
        semi = sectors_data.get("SEMICONDUCTOR")
        ai = sectors_data.get("AI")
        if semi and ai:
            semi_inv = next(
                (c for c in semi.catalysts
                 if c.catalyst_id == "SEMI-INVENTORY-CYCLE-T2"
                 and c.status == "BROKEN"),
                None,
            )
            ai_capex = next(
                (c for c in ai.catalysts
                 if c.catalyst_id == "AI-HYPERSCALER-CAPEX-T1"
                 and c.status == "BULL"),
                None,
            )
            if semi_inv and ai_capex:
                items.append(WatchItem(
                    sector="CROSS",
                    level="linkage",
                    text=("Cross-sector tension: hyperscaler capex strong "
                          f"({ai_capex.current_value}) but semi inventory "
                          f"cycle BROKEN ({semi_inv.current_value}) — semi "
                          "names with strong revenue still carry shared "
                          "inventory risk."),
                ))
    return items


# --- V6.5.3 — Exit-watch summary (compact safety-valves view) ----------- #
EXIT_STATUS_RANK: dict[str, int] = {"TRIGGERED": 0, "MONITORING": 1, "INACTIVE": 2}


@dataclass(frozen=True)
class ExitWatchSummary:
    """Compact roll-up of one sector's (or the entire ALL view's) emergency
    exits — the V6.5.3 "safety valves" panel.

    Pure data composed from already-loaded :class:`EmergencyExit` records.
    NEVER triggers an exit by itself, NEVER places an order, NEVER mutates
    the underlying CSV; it just renders the status counts + a short
    plain-English interpretation + the top N most-important scenarios.
    """

    scope: str  # "ALL" or a sector name
    n_total: int
    n_triggered: int
    n_monitoring: int
    n_inactive: int
    # For the "ALL" view only — empty dict when scope is a single sector
    per_sector_triggered: dict[str, int]
    per_sector_monitoring: dict[str, int]
    top_exits: list[EmergencyExit]
    interpretation: str


def exit_short_trigger(e: EmergencyExit, *, max_chars: int = 100) -> str:
    """Truncate ``trigger_condition`` to a short phrase for the compact view.

    Splits on first ' OR ' to surface the leading clause when present;
    otherwise truncates by character count with an ellipsis. Long original
    text remains available in the detail expander.
    """
    text = (e.trigger_condition or "").strip()
    if not text:
        return "—"
    # Prefer the first OR-clause when present (V6.4 trigger conditions often
    # use "X OR Y" as compound conditions).
    if " OR " in text and len(text) > max_chars:
        head = text.split(" OR ", 1)[0].rstrip()
        if len(head) <= max_chars:
            return head + " …"
    if len(text) <= max_chars:
        return text
    return text[:max_chars - 1].rstrip() + "…"


def exit_short_action(e: EmergencyExit, *, max_chars: int = 80) -> str:
    """Truncate ``action`` to a short sentence for the compact view.

    The standard V6.4 action starts ``"research-only: ..."``; we surface the
    first semicolon-delimited clause when present, otherwise truncate.
    """
    text = (e.action or "").strip()
    if not text:
        return "—"
    if ";" in text:
        first = text.split(";", 1)[0].strip()
        if first and len(first) <= max_chars:
            return first
    if len(text) <= max_chars:
        return text
    return text[:max_chars - 1].rstrip() + "…"


def exit_summary_visible_fields(e: EmergencyExit) -> dict[str, object]:
    """The fields the V6.5.3 compact exit row shows. Long trigger / action /
    source / last_updated stay in the detail expander."""
    return {
        "exit_id": e.exit_id,
        "scenario": e.scenario,
        "current_status": e.current_status,
        "short_trigger": exit_short_trigger(e),
        "short_action": exit_short_action(e),
    }


def exit_summary_detail_fields(e: EmergencyExit) -> dict[str, object]:
    """Detail fields surfaced only inside the per-exit expander."""
    return {
        "trigger_condition": e.trigger_condition,
        "action": e.action,
        "source": e.source,
        "last_updated": e.last_updated,
    }


def _exit_sort_key(e: EmergencyExit) -> tuple[int, str]:
    """Worst-first ordering: TRIGGERED, MONITORING, INACTIVE; ties by id."""
    return (EXIT_STATUS_RANK.get(e.current_status, 99), e.exit_id)


def make_exit_watch_summary(
    sectors_data: dict[str, SectorData],
    *, sector: str | None = None,
    top_k: int = 5,
) -> ExitWatchSummary:
    """Compose an :class:`ExitWatchSummary` for one sector (when ``sector``
    is given) or for the union across every loaded sector (when ``sector``
    is ``None``).

    Plain-English interpretation rules (pre-declared, not synthesised):

    * No exits in scope → ``"No emergency exits defined for this scope."``
    * Any TRIGGERED → ``"N exit(s) triggered. Review sector exposure
      immediately."``
    * Otherwise all MONITORING → ``"No exits triggered. Continue monitoring."``
    * Otherwise all INACTIVE → ``"All exits inactive. No active monitoring."``
    * Mixed MONITORING + INACTIVE → ``"No exits triggered. Monitoring only —
      no forced exit condition is active."``
    """
    scope = sector or "ALL"
    if sector is None:
        all_exits: list[EmergencyExit] = []
        for sd in sectors_data.values():
            all_exits.extend(sd.exits)
        per_trig: dict[str, int] = {}
        per_mon: dict[str, int] = {}
        for s_name, sd in sectors_data.items():
            per_trig[s_name] = sum(1 for e in sd.exits
                                    if e.current_status == "TRIGGERED")
            per_mon[s_name] = sum(1 for e in sd.exits
                                   if e.current_status == "MONITORING")
    else:
        sd = sectors_data.get(sector)
        all_exits = list(sd.exits) if sd is not None else []
        per_trig = {}
        per_mon = {}

    n_total = len(all_exits)
    n_triggered = sum(1 for e in all_exits if e.current_status == "TRIGGERED")
    n_monitoring = sum(1 for e in all_exits
                       if e.current_status == "MONITORING")
    n_inactive = sum(1 for e in all_exits if e.current_status == "INACTIVE")

    if n_total == 0:
        interp = "No emergency exits defined for this scope."
    elif n_triggered > 0:
        plural = "s" if n_triggered != 1 else ""
        interp = (f"{n_triggered} exit{plural} triggered. Review sector "
                  "exposure immediately.")
    elif n_monitoring == n_total:
        interp = "No exits triggered. Continue monitoring."
    elif n_inactive == n_total:
        interp = "All exits inactive. No active monitoring."
    else:
        interp = ("No exits triggered. Monitoring only — no forced exit "
                  "condition is active.")

    top_exits = sorted(all_exits, key=_exit_sort_key)[:top_k]

    return ExitWatchSummary(
        scope=scope, n_total=n_total,
        n_triggered=n_triggered, n_monitoring=n_monitoring,
        n_inactive=n_inactive,
        per_sector_triggered=per_trig,
        per_sector_monitoring=per_mon,
        top_exits=top_exits,
        interpretation=interp,
    )


# --- visible vs. detail field shapers (V6.5.2) -------------------------- #
def catalyst_card_visible_fields(c: Catalyst) -> dict[str, object]:
    """Dict of the fields the simplified V6.5.2 catalyst card body shows.

    Intentionally **excludes** ``threshold`` / ``source_detail`` /
    ``action_if_broken`` / ``notes`` — those move into the Details expander.
    """
    return {
        "catalyst_id": c.catalyst_id,
        "catalyst_name": c.catalyst_name,
        "subsector": c.subsector,
        "tier": c.tier,
        "status": c.status,
        "source_type": c.source_type,
        "current_value": c.current_value,
    }


def catalyst_card_detail_fields(c: Catalyst) -> dict[str, object]:
    """Dict of the fields the catalyst Details expander adds on top of the
    visible body. Threshold lives here in V6.5.2."""
    return {
        "threshold": c.threshold,
        "source_detail": c.source_detail,
        "action_if_broken": c.action_if_broken,
        "notes": c.notes,
        "last_updated": c.last_updated,
    }


def company_row_visible_columns(r: CompanyLensRow) -> list[tuple[str, str]]:
    """Ordered (label, value) tuples for the V6.5.2 visible company row.

    The visible row deliberately does NOT include the linked catalyst IDs —
    those move into the per-company expander surfaced by
    :func:`company_row_detail_columns`.
    """
    return [
        ("Ticker", r.ticker),
        ("Sector", r.sector),
        ("Theme", r.subsector_theme),
        ("Read", r.current_read),
        ("Why it matters", r.why_short or "—"),
        ("Main risk / note", r.main_risk_short or "—"),
    ]


def company_row_detail_columns(r: CompanyLensRow) -> list[tuple[str, str]]:
    """Detail (expander) columns for one company row — surfaces the linked
    catalyst IDs and the long composed reason that the visible row hides."""
    linked = ", ".join(r.linked_catalyst_ids) if r.linked_catalyst_ids else "—"
    return [
        ("Linked catalysts",
         f"{linked}  ({r.n_linked_present}/"
         f"{len(r.linked_catalyst_ids)} loaded)"),
        ("Composed reason", r.reason),
    ]


def build_company_lens(
    sectors_data: dict[str, SectorData],
    *, sectors: set[str] | None = None,
) -> list[CompanyLensRow]:
    """Build the company-lens table from loaded sector data.

    Walks :data:`COMPANY_CATALYSTS` and derives each row via
    :func:`derive_company_read`. Reads only the **existing** catalysts and
    NEVER invents a per-company score. Sectors not loaded are skipped silently.
    """
    out: list[CompanyLensRow] = []
    for sector, companies in COMPANY_CATALYSTS.items():
        if sectors is not None and sector not in sectors:
            continue
        sd = sectors_data.get(sector)
        if sd is None:
            continue
        by_id = {c.catalyst_id: c for c in sd.catalysts}
        for comp in companies:
            read, reason, n_present = derive_company_read(
                by_id, comp["catalysts"]
            )
            found = [by_id[i] for i in comp["catalysts"] if i in by_id]
            why_short, main_risk_short = company_view_strings(found)
            out.append(CompanyLensRow(
                ticker=comp["ticker"], sector=sector,
                subsector_theme=comp["subsector_theme"],
                linked_catalyst_ids=list(comp["catalysts"]),
                n_linked_present=n_present,
                current_read=read, reason=reason,
                why_short=why_short, main_risk_short=main_risk_short,
            ))
    # Stable order: by sector, then by worst-to-best read, then by ticker.
    read_rank = {r: i for i, r in enumerate(READ_ORDER)}
    out.sort(key=lambda r: (r.sector, read_rank.get(r.current_read, 99),
                             r.ticker))
    return out


def company_lens_companies_in_universe() -> list[tuple[str, str]]:
    """Return [(sector, ticker)] from the pre-declared mapping (test helper)."""
    return [(sec, comp["ticker"])
            for sec, comps in COMPANY_CATALYSTS.items() for comp in comps]


def read_color(read: str) -> str:
    return READ_COLOURS.get(read, "#7F8C8D")


# --------------------------------------------------------------------------- #
# V6.8.1 — Company-derived sector roll-up (collapsed audit view).
# Reads the V6.8 aggregation CSV and compares it side-by-side with the V6.1
# canonical sector signal. The block is rendered inside a collapsed expander
# so the dashboard's reading order is unchanged.
#
# Divergence is a categorical comparison ONLY — never a trading signal,
# never feeds canonical scoring, never mutates any file.
# --------------------------------------------------------------------------- #
# Ordinal sentiment maps. Higher = more bullish. The maps are pre-declared
# constants so a future schema change requires a code change (not a silent
# behaviour shift).
_CANONICAL_RANK: dict[str, int] = {
    "ACCUMULATE": 2,
    "SELECTIVE_BUY": 1,
    "HOLD": 0,
    "AVOID_NEW_BUY": -1,
    "REDUCE": -2,
    "EXIT_WATCH": -3,
}
_COMPANY_DERIVED_RANK: dict[str, int] = {
    "BULL": 2,
    "MIXED": 0,
    "NEUTRAL": 0,
    "TRACKED_HEAVY": 0,
    "CAUTION": -1,
    "BROKEN": -2,
    # "N_A" is intentionally absent so callers fall into the N/A branch.
}

# Markers exposed verbatim in the dashboard table — small, plain-English,
# no emoji except the ⚠ glyph mandated by the V6.8.1 spec.
DIVERGENCE_ALIGNED = "aligned"
DIVERGENCE_MORE_CAUTIOUS = "⚠ company roll-up more cautious"
DIVERGENCE_MORE_BULLISH = "⚠ company roll-up more bullish"
DIVERGENCE_NA_AGG = "N/A — no aggregation available"
DIVERGENCE_NA_CANONICAL = "N/A — sector not loaded"


def aggregation_divergence(canonical_signal: str | None,
                            company_derived_read: str | None) -> str:
    """Return the categorical divergence marker for one sector.

    Pure: no I/O, no globals besides the pre-declared rank tables.

    Rules:

    * ``canonical_signal`` is ``None`` (sector artefacts not loaded)
      → :data:`DIVERGENCE_NA_CANONICAL`
    * ``company_derived_read`` is ``None``, ``""``, or ``"N_A"``
      → :data:`DIVERGENCE_NA_AGG`
    * Unknown labels on either side
      → ``DIVERGENCE_NA_AGG`` (defensive — never crash the render)
    * Otherwise compare ranks:
        - ``diff >= 2``  → ``"⚠ company roll-up more cautious"``
        - ``diff <= -2`` → ``"⚠ company roll-up more bullish"``
        - else           → ``"aligned"``
    """
    if canonical_signal is None:
        return DIVERGENCE_NA_CANONICAL
    if not company_derived_read or company_derived_read == "N_A":
        return DIVERGENCE_NA_AGG
    if canonical_signal not in _CANONICAL_RANK:
        return DIVERGENCE_NA_AGG
    if company_derived_read not in _COMPANY_DERIVED_RANK:
        return DIVERGENCE_NA_AGG
    diff = _CANONICAL_RANK[canonical_signal] \
        - _COMPANY_DERIVED_RANK[company_derived_read]
    if diff >= 2:
        return DIVERGENCE_MORE_CAUTIOUS
    if diff <= -2:
        return DIVERGENCE_MORE_BULLISH
    return DIVERGENCE_ALIGNED


@dataclass(frozen=True)
class AggregationRollUpRow:
    """One row of the V6.8.1 collapsed roll-up table.

    Composed purely from already-loaded :class:`SectorData` (canonical) and
    :class:`SectorAggregationRow` (company-derived). No re-scoring; no
    derived numeric fields beyond what the underlying records already
    expose.
    """

    sector: str
    canonical_signal: str           # e.g. "SELECTIVE_BUY" or "N/A"
    canonical_score: str            # e.g. "+0.280" or "n/a"
    company_derived_read: str       # e.g. "CAUTION" or "N/A"
    distribution_summary: str       # the aggregation row's notes field
    top_bull_companies: str
    top_mixed_or_risk_companies: str
    tracked_only_companies: str
    divergence: str


def build_aggregation_roll_up_rows(
    sectors_data: dict[str, "SectorData"],
    aggregations: dict[str, SectorAggregationRow],
) -> list[AggregationRollUpRow]:
    """Compose the roll-up table — one row per sector, in :data:`SECTORS` order.

    Missing canonical data and missing aggregation rows are both handled
    gracefully: their fields surface as ``"N/A"`` / ``"—"`` and the
    divergence marker explains which side is absent.
    """
    out: list[AggregationRollUpRow] = []
    for sec in SECTORS:
        sd = sectors_data.get(sec)
        agg = aggregations.get(sec)

        if sd is not None and sd.score is not None:
            canonical_signal = sd.score.signal
            canonical_score = f"{sd.score.normalized_score:+.3f}"
        else:
            canonical_signal = "N/A"
            canonical_score = "n/a"

        if agg is not None:
            company_read = agg.company_derived_read
            distribution = agg.notes or "—"
            bull = agg.top_bull_companies or "—"
            risk = agg.top_mixed_or_risk_companies or "—"
            tracked = agg.tracked_only_companies or "—"
        else:
            company_read = "N/A"
            distribution = "—"
            bull = "—"
            risk = "—"
            tracked = "—"

        # Divergence needs the *typed* canonical/company values, so pass
        # them through the pure helper rather than re-deriving here.
        divergence = aggregation_divergence(
            canonical_signal=(sd.score.signal
                              if (sd is not None and sd.score is not None)
                              else None),
            company_derived_read=(agg.company_derived_read
                                   if agg is not None else None),
        )

        out.append(AggregationRollUpRow(
            sector=sec,
            canonical_signal=canonical_signal,
            canonical_score=canonical_score,
            company_derived_read=company_read,
            distribution_summary=distribution,
            top_bull_companies=bull,
            top_mixed_or_risk_companies=risk,
            tracked_only_companies=tracked,
            divergence=divergence,
        ))
    return out


# --------------------------------------------------------------------------- #
# Streamlit rendering — only imported when the script is actually run by
# `streamlit run`. Importing this module for tests does NOT call render().
# --------------------------------------------------------------------------- #
def render() -> None:  # pragma: no cover - exercised by streamlit run
    import streamlit as st

    st.set_page_config(
        page_title="Sector Thesis Tracker — V6.5",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # Dark theme + card CSS injection. Streamlit's default theme renders
    # cleanly with these overrides; a user can also set their own theme.
    st.markdown(
        """
        <style>
        .stApp { background-color: #0e1117; color: #fafafa; }
        section[data-testid="stSidebar"] { background-color: #161a23; }
        .signal-card {
            border-radius: 8px; padding: 14px 16px; margin: 4px 0 10px 0;
            background-color: #1c2230; border: 1px solid #2a3142;
        }
        .signal-card h3 { margin: 0 0 8px 0; font-size: 14px; opacity: 0.7; }
        .signal-card .big { font-size: 26px; font-weight: 700; }
        .catalyst-card {
            border-radius: 8px; padding: 12px 14px; margin: 6px 0;
            background-color: #1c2230; border-left: 4px solid #95A5A6;
        }
        .pill {
            display: inline-block; padding: 2px 8px; border-radius: 999px;
            font-size: 11px; font-weight: 700; color: #0e1117;
        }
        .meta { color: #8a93a6; font-size: 12px; }
        .disclaimer {
            background-color: #2a1f1f; border: 1px solid #5c2a2a;
            padding: 10px 14px; border-radius: 6px; margin: 4px 0 14px 0;
            color: #f5d3d3;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # V6.5.2 — single compact disclaimer line instead of the prior banner.
    st.markdown(
        f"### Sector Thesis Tracker  &nbsp;&nbsp; "
        f"<span class='meta'>{DISCLAIMER}</span>",
        unsafe_allow_html=True,
    )

    sectors_data = load_all_sectors()
    changes_all = load_change_log_safe()
    annotations_all = load_event_annotations_safe()
    # The prior top "summary cards" row was removed in V6.5.2 — the Executive
    # view inside the All tab carries the same signal info in plain English.

    # --- sidebar filters --- #
    all_catalysts: list[Catalyst] = []
    for sd in sectors_data.values():
        all_catalysts.extend(sd.catalysts)

    st.sidebar.header("Filters")
    sec_filter = set(st.sidebar.multiselect(
        "Sector",
        options=sorted({c.sector for c in all_catalysts}) or list(SECTORS),
        default=[]))
    sub_filter = set(st.sidebar.multiselect(
        "Subsector",
        options=sorted({c.subsector for c in all_catalysts if c.subsector}),
        default=[]))
    tier_filter = set(st.sidebar.multiselect(
        "Tier",
        options=[1, 2],
        default=[]))
    status_filter = set(st.sidebar.multiselect(
        "Status",
        options=["BULL", "NEUTRAL", "NEAR_THRESHOLD", "BROKEN"],
        default=[]))
    src_filter = set(st.sidebar.multiselect(
        "Source type",
        options=sorted({c.source_type for c in all_catalysts}),
        default=[]))

    def _apply_filters(cats: list[Catalyst]) -> list[Catalyst]:
        return filter_catalysts(
            cats, sectors=sec_filter or None,
            subsectors=sub_filter or None, tiers=tier_filter or None,
            statuses=status_filter or None,
            source_types=src_filter or None,
        )

    # --- tabs --- #
    tab_labels = ["All", "Semiconductor", "AI", "Energy"]
    tabs = st.tabs(tab_labels)

    # Tab 0: All — V6.5.2 simplified investor-first layout.
    with tabs[0]:
        # 1. "Today's sector read" — 3 plain-English cards.
        st.subheader("Today's sector read")
        exec_cols = st.columns(len(SECTORS))
        for i, sec in enumerate(SECTORS):
            with exec_cols[i]:
                _render_executive_card(
                    st, make_executive_summary(sectors_data[sec])
                )

        # 2. "Simple company view" — slim table per sector + per-row expander.
        st.markdown("---")
        st.subheader("Simple company view")
        st.caption(
            "One row per company. Read derived from existing catalysts only — "
            "NOT a per-company score. Linked catalyst IDs are in each row's "
            "expander."
        )
        _render_simple_company_table(st, build_company_lens(sectors_data))

        # 3. "Things worth watching" — curated headline list.
        st.markdown("---")
        st.subheader("Things worth watching")
        st.caption(
            "Headline observations derived strictly from the existing "
            "catalyst CSVs. Nothing here is a trade recommendation."
        )
        _render_things_worth_watching(
            st, things_worth_watching(sectors_data)
        )

        # 4. V6.5.3 — Exit watch / safety valves (compact, prominent).
        st.markdown("---")
        st.subheader("Exit watch / safety valves")
        st.caption(
            "Triggered / monitoring state across every sector's emergency-"
            "exit scenarios. Triggered exits show prominently. Full per-exit "
            "trigger / action / source detail lives inside the per-sector "
            "tab's collapsed Emergency-exits expander."
        )
        _render_exit_watch_summary(
            st, make_exit_watch_summary(sectors_data, top_k=5)
        )

        # 5–9. Technical sections — collapsed by default.
        st.markdown("---")
        n_changes = len(changes_all)
        n_anns = len(annotations_all)
        with st.expander(
            f"Recent changes ({n_changes})",
            expanded=False,
        ):
            _render_recent_changes(
                st, recent_changes(changes_all, top_k=20),
                heading="",
            )
        with st.expander(
            f"Event annotations ({n_anns})",
            expanded=False,
        ):
            _render_event_annotations(
                st, annotations_all[:10],
                heading="",
            )
        with st.expander("Cross-sector scenario links", expanded=False):
            for link in cross_sector_links():
                st.markdown(
                    f"- **{link['left_sector']}** "
                    f"`{link['left_id']}` ↔ "
                    f"**{link['right_sector']}** "
                    f"`{link['right_id']}` — {link['note']}"
                )
        with st.expander("Cross-sector detailed breakdown "
                          "(top drivers / risks / data gaps)",
                          expanded=False):
            filtered = _apply_filters(all_catalysts)
            c1, c2, c3 = st.columns(3)
            with c1:
                st.markdown("### Top bull drivers")
                for c in top_bull_drivers(filtered, top_k=8):
                    _render_catalyst_compact(st, c)
                if not top_bull_drivers(filtered):
                    st.caption("_(none under current filters)_")
            with c2:
                st.markdown("### Top risks")
                for c in top_risks(filtered, top_k=8):
                    _render_catalyst_compact(st, c)
                if not top_risks(filtered):
                    st.caption("_(none under current filters)_")
            with c3:
                st.markdown("### Manual / data gaps")
                for c in manual_gaps(filtered)[:8]:
                    _render_catalyst_compact(st, c)
                if not manual_gaps(filtered):
                    st.caption("_(none under current filters)_")

        # V6.8.1 — Company-derived sector roll-up (collapsed audit view).
        # Reads the V6.8 aggregation CSV alongside the canonical V6.1
        # signals. Categorical comparison only; never feeds canonical
        # scoring, never emits a trading signal, never mutates files.
        with st.expander("Company-derived sector roll-up",
                          expanded=False):
            aggregations = load_latest_aggregation_per_sector(
                DEFAULT_AGGREGATION_PATH,
            )
            if not aggregations:
                st.caption(
                    "_No company-derived aggregation yet. Build it with "
                    "`python scripts/build_company_sector_aggregation.py` "
                    "after the V6.7 ledger has at least one run. "
                    "The canonical sector signals above are unaffected._"
                )
            else:
                st.caption(
                    "Side-by-side: canonical V6.1 sector signal vs. the V6.8 "
                    "company-derived read. **Audit / research view only — "
                    "never a trading signal, never alters scoring.** "
                    "Divergence is categorical and based on pre-declared "
                    "ordinal sentiment maps."
                )
                _render_aggregation_roll_up_table(
                    st,
                    build_aggregation_roll_up_rows(sectors_data, aggregations),
                )

    # Tabs 1-3: per-sector — same simplified order.
    for i, sec in enumerate(SECTORS):
        with tabs[i + 1]:
            sd = sectors_data[sec]
            if sd.missing_files:
                for f in sd.missing_files:
                    st.warning(f"Missing artefact: `{f}` — run the "
                               f"corresponding driver to regenerate.")
            _render_sector_tab(
                st, sd, _apply_filters(sd.catalysts),
                changes=recent_changes(changes_all, sectors={sec}, top_k=15),
                annotations=annotations_all,
                exec_summary=make_executive_summary(sd),
                lens_rows=build_company_lens(sectors_data, sectors={sec}),
                watch_items=things_worth_watching(sectors_data,
                                                    sectors={sec}),
            )


def _render_catalyst_compact(st, c: Catalyst) -> None:  # pragma: no cover
    col = status_color(c.status)
    st.markdown(
        f'<div class="catalyst-card" style="border-left-color:{col}">'
        f'<div><span class="pill" style="background-color:{col}">'
        f'{c.status}</span> &nbsp; <strong>{c.catalyst_id}</strong></div>'
        f'<div>{c.catalyst_name}</div>'
        f'<div class="meta">{c.sector} · {c.subsector} · Tier {c.tier} · '
        f'{c.source_type} · {c.current_value or "n/a"}</div>'
        f'</div>',
        unsafe_allow_html=True)


def _render_sector_tab(st, sd: SectorData,
                       filtered: list[Catalyst],
                       *, changes: list[Change] | None = None,
                       annotations: list[EventAnnotation] | None = None,
                       exec_summary: ExecutiveSummary | None = None,
                       lens_rows: list[CompanyLensRow] | None = None,
                       watch_items: list[WatchItem] | None = None,
                       ) -> None:  # pragma: no cover
    changes = changes or []
    annotations = annotations or []
    watch_items = watch_items or []
    if sd.score is None:
        st.info(f"No catalysts loaded for {sd.sector}.")
        return

    # 1. Executive summary card (compact).
    if exec_summary is not None:
        _render_executive_card(st, exec_summary, compact=True)

    # 2. Company lens (this sector).
    if lens_rows:
        st.subheader("Company lens (this sector)")
        _render_simple_company_table(st, lens_rows)

    # 3. Things worth watching (this sector).
    st.subheader("Things worth watching")
    _render_things_worth_watching(st, watch_items)

    # 4. V6.5.3 — Exit watch (this sector). Compact summary above the full
    # collapsed exits list. Triggered scenarios get visual prominence.
    st.subheader("Exit watch — this sector")
    _render_exit_watch_summary(
        st,
        make_exit_watch_summary({sd.sector: sd},
                                 sector=sd.sector, top_k=3),
    )

    # 5. Catalyst details — collapsed by default.
    with st.expander(f"Catalyst details ({len(filtered)})",
                      expanded=False):
        if not filtered:
            st.caption("_(no catalysts match the current filters)_")
        else:
            cols = st.columns(2)
            for idx, c in enumerate(filtered):
                with cols[idx % 2]:
                    _render_catalyst_card(st, c, annotations)

    # 5. Emergency exits — collapsed by default.
    n_exits_triggered = sum(1 for e in sd.exits
                            if e.current_status == "TRIGGERED")
    exit_label = (f"Emergency exits ({len(sd.exits)} — "
                  f"{n_exits_triggered} triggered)")
    with st.expander(exit_label, expanded=False):
        if not sd.exits:
            st.caption("_(none)_")
        else:
            for e in sd.exits:
                _render_exit_card(st, e, annotations)

    # 6. Recent changes — collapsed (the V6.5.2 spec says collapse if empty;
    # also collapse if non-empty for consistency, so the All tab matches).
    with st.expander(f"Recent changes ({len(changes)})",
                      expanded=False):
        _render_recent_changes(st, changes, heading="")

    # 7. Raw report markdown — collapsed.
    if sd.report_md:
        with st.expander(f"View raw {sd.sector} report markdown",
                          expanded=False):
            st.markdown(sd.report_md)


def _render_catalyst_card(st, c: Catalyst,
                           annotations: list[EventAnnotation],
                           ) -> None:  # pragma: no cover
    """V6.5.2 — visible body is slim (status, ID, tier, name, current_value);
    threshold / source_detail / action / notes / last_updated go in the
    Details expander."""
    visible = catalyst_card_visible_fields(c)
    col = status_color(c.status)
    st.markdown(
        f'<div class="catalyst-card" style="border-left-color:{col}">'
        f'<div><span class="pill" style="background-color:{col}">'
        f'{visible["status"]}</span> &nbsp; '
        f'<strong>{visible["catalyst_id"]}</strong> &nbsp; '
        f'<span class="meta">Tier {visible["tier"]}</span></div>'
        f'<div style="margin-top:6px"><strong>'
        f'{visible["catalyst_name"]}</strong></div>'
        f'<div class="meta">{visible["subsector"]} · '
        f'{visible["source_type"]}</div>'
        f'<div style="margin-top:6px">current: '
        f'<code>{visible["current_value"] or "n/a"}</code></div>'
        f'</div>',
        unsafe_allow_html=True,
    )
    with st.expander("Details"):
        det = catalyst_card_detail_fields(c)
        st.markdown(f"- **threshold:** `{det['threshold']}`")
        st.markdown(f"- **source_detail:** {det['source_detail']}")
        st.markdown(f"- **action_if_broken:** {det['action_if_broken']}")
        st.markdown(f"- **notes:** {det['notes'] or '_(none)_'}")
        st.markdown(f"- **last_updated:** {det['last_updated']}")
        cat_anns = annotations_for(annotations, c.catalyst_id)
        if cat_anns:
            st.markdown("- **Related annotations:**")
            for a in cat_anns:
                st.markdown(
                    f"  - `{a.timestamp}` _{a.event_type}_ · "
                    f"**{a.title}** — {a.note} "
                    f"(source: {a.source})")
        else:
            st.markdown("- **Related annotations:** _(none)_")


def _render_exit_card(st, e: EmergencyExit,
                       annotations: list[EventAnnotation],
                       ) -> None:  # pragma: no cover
    col = exit_color(e.current_status)
    st.markdown(
        f'<div class="catalyst-card" style="border-left-color:{col}">'
        f'<div><span class="pill" style="background-color:{col}">'
        f'{e.current_status}</span> &nbsp; <strong>{e.exit_id}</strong></div>'
        f'<div style="margin-top:6px">{e.scenario}</div>'
        f'<div class="meta">trigger: {e.trigger_condition}</div>'
        f'<div class="meta">action: {e.action}</div>'
        f'<div class="meta">source: {e.source} · last_updated '
        f'{e.last_updated}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )
    exit_anns = annotations_for(annotations, e.exit_id)
    if exit_anns:
        with st.expander(f"Related annotations ({len(exit_anns)})"):
            for a in exit_anns:
                st.markdown(
                    f"- `{a.timestamp}` _{a.event_type}_ · "
                    f"**{a.title}** — {a.note} (source: {a.source})")


def _render_recent_changes(st, changes: list[Change], *,
                            heading: str) -> None:  # pragma: no cover
    st.subheader(heading)
    if not changes:
        st.caption(
            "_No changes recorded yet. Run "
            "`python scripts/refresh_sector_trackers.py` to capture new "
            "deltas; the change log is append-only._")
        return
    for ch in changes:
        # Highlight degradations (status moved to NEAR_THRESHOLD or BROKEN).
        if is_degradation(ch):
            border = STATUS_COLOURS["BROKEN"]
        elif ch.field_changed == "BASELINE":
            border = "#7F8C8D"
        else:
            border = "#3498DB"
        st.markdown(
            f'<div class="catalyst-card" '
            f'style="border-left-color:{border}">'
            f'<div class="meta">{ch.timestamp} · {ch.sector} · '
            f'{ch.record_type} · run {ch.refresh_run_id}</div>'
            f'<div><strong>{ch.record_id}</strong> · '
            f'<code>{ch.field_changed}</code></div>'
            f'<div>prior: <code>{ch.prior_value or "—"}</code> → '
            f'new: <code>{ch.new_value or "—"}</code></div>'
            + (f'<div class="meta">status: {ch.prior_status or "—"} → '
               f'{ch.new_status or "—"}</div>'
               if ch.prior_status or ch.new_status else '')
            + (f'<div class="meta">notes: {ch.notes}</div>'
               if ch.notes else '')
            + '</div>',
            unsafe_allow_html=True)


def _render_event_annotations(st, annotations: list[EventAnnotation], *,
                               heading: str) -> None:  # pragma: no cover
    st.subheader(heading)
    if not annotations:
        st.caption(
            "_No event annotations have been added yet. Annotations are "
            "context only — never an autonomous trading signal. Add rows "
            "manually to `data/research/sector_tracker/event_annotations.csv`."
        )
        return
    for a in annotations:
        st.markdown(
            f'<div class="catalyst-card" style="border-left-color:#9B59B6">'
            f'<div class="meta">{a.timestamp} · {a.sector or "—"} · '
            f'{a.event_type} · confidence {a.confidence or "—"}</div>'
            f'<div><strong>{a.title}</strong></div>'
            f'<div>{a.note}</div>'
            f'<div class="meta">related: '
            f'<code>{a.related_type}:{a.related_id}</code> · '
            f'ticker {a.ticker or "—"} · source: {a.source or "—"} · '
            f'{a.source_url_or_file or ""} · added by {a.added_by or "—"}'
            f'</div></div>',
            unsafe_allow_html=True)


def _render_executive_card(st, es: ExecutiveSummary, *,
                            compact: bool = False) -> None:  # pragma: no cover
    """Render one Executive view card. Plain-English, no jargon."""
    sig_col = signal_color(es.signal)
    bull = ("<br>".join(f"• {n}" for n in es.top_bull_drivers)
            or "<span class='meta'>(none)</span>")
    risk = ("<br>".join(f"• {n}" for n in es.top_risks)
            or "<span class='meta'>(none)</span>")
    if compact:
        st.markdown(
            f'<div class="signal-card">'
            f'<h3>{es.sector} — Plain-English read</h3>'
            f'<div style="font-size:20px;font-weight:700;color:{sig_col}">'
            f'{es.signal}</div>'
            f'<div class="meta">normalized score {es.normalized_score:+.3f}</div>'
            f'<div style="margin-top:8px">{es.interpretation}</div>'
            f'<div style="margin-top:8px"><strong>Top bull drivers</strong>'
            f'<div>{bull}</div></div>'
            f'<div style="margin-top:6px"><strong>Top risks</strong>'
            f'<div>{risk}</div></div>'
            f'<div style="margin-top:8px"><strong>What to watch next</strong>'
            f'<br><span class="meta">{es.what_to_watch}</span></div>'
            f'</div>',
            unsafe_allow_html=True)
    else:
        st.markdown(
            f'<div class="signal-card">'
            f'<h3>{es.sector}</h3>'
            f'<div style="font-size:24px;font-weight:700;color:{sig_col}">'
            f'{es.signal}</div>'
            f'<div class="meta">normalized score {es.normalized_score:+.3f}</div>'
            f'<div style="margin-top:8px">{es.interpretation}</div>'
            f'<div style="margin-top:10px"><strong>Top bull drivers</strong>'
            f'<div>{bull}</div></div>'
            f'<div style="margin-top:6px"><strong>Top risks</strong>'
            f'<div>{risk}</div></div>'
            f'<div style="margin-top:10px"><strong>What to watch next</strong>'
            f'<br><span class="meta">{es.what_to_watch}</span></div>'
            f'</div>',
            unsafe_allow_html=True)


def _render_simple_company_table(
    st, rows: list[CompanyLensRow],
) -> None:  # pragma: no cover
    """V6.5.2 simple company table — slim visible columns, linked catalyst
    IDs only inside a per-company expander (not on the main row)."""
    if not rows:
        st.caption("_(no companies in current filter)_")
        return
    by_sector: dict[str, list[CompanyLensRow]] = {}
    for r in rows:
        by_sector.setdefault(r.sector, []).append(r)
    for sec, group in by_sector.items():
        st.markdown(f"#### {sec}")
        header = (
            '<table style="width:100%; border-collapse:collapse; '
            'background-color:#1c2230; border:1px solid #2a3142;">'
            '<thead><tr style="text-align:left; color:#8a93a6;">'
            '<th style="padding:8px">Ticker</th>'
            '<th style="padding:8px">Theme</th>'
            '<th style="padding:8px">Read</th>'
            '<th style="padding:8px">Why it matters</th>'
            '<th style="padding:8px">Main risk / note</th>'
            '</tr></thead><tbody>'
        )
        body_rows = []
        for r in group:
            pill_col = read_color(r.current_read)
            body_rows.append(
                f'<tr style="border-top:1px solid #2a3142;">'
                f'<td style="padding:8px"><strong>{r.ticker}</strong></td>'
                f'<td style="padding:8px">{r.subsector_theme}</td>'
                f'<td style="padding:8px">'
                f'<span class="pill" style="background-color:{pill_col}">'
                f'{r.current_read}</span></td>'
                f'<td style="padding:8px">{r.why_short or "—"}</td>'
                f'<td style="padding:8px">{r.main_risk_short or "—"}</td>'
                f'</tr>'
            )
        st.markdown(header + "".join(body_rows) + "</tbody></table>",
                    unsafe_allow_html=True)
        # Per-company linked-catalyst expanders below the table.
        with st.expander(
            f"Show linked catalyst IDs for the {sec} companies above",
            expanded=False,
        ):
            for r in group:
                linked = ", ".join(
                    f"`{cid}`" for cid in r.linked_catalyst_ids
                ) or "—"
                st.markdown(
                    f"- **{r.ticker}** — {linked} "
                    f"({r.n_linked_present}/"
                    f"{len(r.linked_catalyst_ids)} loaded)\n"
                    f"  &nbsp;&nbsp;<span class='meta'>{r.reason}</span>",
                    unsafe_allow_html=True,
                )


def _render_aggregation_roll_up_table(
    st, rows: list[AggregationRollUpRow],
) -> None:  # pragma: no cover
    """V6.8.1 — compact HTML table for the collapsed roll-up expander.

    Pure presentation: receives already-composed rows, never re-reads
    anything from disk, never derives a new value. Divergence marker
    rendered with the colour the worst-of-bull/cautious side suggests so
    the operator can scan the column quickly without re-reading the text.
    """
    if not rows:
        st.caption("_(no sectors available)_")
        return

    header = (
        '<table style="width:100%; border-collapse:collapse; '
        'background-color:#1c2230; border:1px solid #2a3142;">'
        '<thead><tr style="text-align:left; color:#8a93a6;">'
        '<th style="padding:8px">Sector</th>'
        '<th style="padding:8px">Canonical signal</th>'
        '<th style="padding:8px">Score</th>'
        '<th style="padding:8px">Company-derived read</th>'
        '<th style="padding:8px">Distribution</th>'
        '<th style="padding:8px">Top bull</th>'
        '<th style="padding:8px">Top mixed / risk</th>'
        '<th style="padding:8px">Tracked-only</th>'
        '<th style="padding:8px">Divergence</th>'
        '</tr></thead><tbody>'
    )
    body_rows: list[str] = []
    for r in rows:
        # Colour the divergence cell: cautious=red-ish, bullish=green-ish,
        # aligned=grey, N/A=neutral.
        if r.divergence == DIVERGENCE_MORE_CAUTIOUS:
            div_col = "#E74C3C"
        elif r.divergence == DIVERGENCE_MORE_BULLISH:
            div_col = "#2ECC71"
        elif r.divergence == DIVERGENCE_ALIGNED:
            div_col = "#7F8C8D"
        else:
            div_col = "#34495E"
        body_rows.append(
            f'<tr style="border-top:1px solid #2a3142;">'
            f'<td style="padding:8px"><strong>{r.sector}</strong></td>'
            f'<td style="padding:8px">{r.canonical_signal}</td>'
            f'<td style="padding:8px">{r.canonical_score}</td>'
            f'<td style="padding:8px">{r.company_derived_read}</td>'
            f'<td style="padding:8px">{r.distribution_summary}</td>'
            f'<td style="padding:8px">{r.top_bull_companies}</td>'
            f'<td style="padding:8px">{r.top_mixed_or_risk_companies}</td>'
            f'<td style="padding:8px">{r.tracked_only_companies}</td>'
            f'<td style="padding:8px; color:{div_col}">{r.divergence}</td>'
            f'</tr>'
        )
    st.markdown(header + "".join(body_rows) + "</tbody></table>",
                unsafe_allow_html=True)


def _render_exit_watch_summary(
    st, summary: ExitWatchSummary,
) -> None:  # pragma: no cover
    """V6.5.3 — compact "safety valves" panel rendered above the full
    emergency-exit expander. TRIGGERED state gets a prominent red banner;
    all-monitoring gets a calm yellow border."""
    if summary.n_total == 0:
        st.caption("_No emergency exits defined for this scope._")
        return
    # Headline border / banner colour reflects worst-bucket state.
    if summary.n_triggered > 0:
        banner_col = EXIT_COLOURS["TRIGGERED"]
        banner_label = "TRIGGERED"
    elif summary.n_monitoring > 0:
        banner_col = EXIT_COLOURS["MONITORING"]
        banner_label = "MONITORING"
    else:
        banner_col = EXIT_COLOURS["INACTIVE"]
        banner_label = "INACTIVE"

    # Per-sector breakdown line (only for the ALL scope).
    if summary.scope == "ALL":
        trig_color = EXIT_COLOURS["TRIGGERED"]
        per_sec_html = " · ".join(
            f"{sec} "
            f"<span style='color:{trig_color}'>"
            f"{summary.per_sector_triggered.get(sec, 0)}T</span>"
            f"/{summary.per_sector_monitoring.get(sec, 0)}M"
            for sec in SECTORS
        )
        per_sec_block = (f'<div class="meta" style="margin-top:6px">'
                         f'per-sector triggered/monitoring: {per_sec_html}</div>')
    else:
        per_sec_block = ""

    st.markdown(
        f'<div class="signal-card" style="border-left:6px solid {banner_col}">'
        f'<div><span class="pill" style="background-color:{banner_col}">'
        f'{banner_label}</span>'
        f'&nbsp;&nbsp;<strong>'
        f'{summary.n_triggered} triggered · '
        f'{summary.n_monitoring} monitoring · '
        f'{summary.n_inactive} inactive</strong>'
        f'&nbsp;&nbsp;<span class="meta">'
        f'(scope: {summary.scope}, {summary.n_total} total)</span></div>'
        f'<div style="margin-top:8px;font-size:14px">'
        f'{summary.interpretation}</div>'
        f'{per_sec_block}'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Compact "top N" exit rows. Visible columns only — full trigger/action/
    # source text remains in the existing collapsed expander below.
    if summary.top_exits:
        for e in summary.top_exits:
            vis = exit_summary_visible_fields(e)
            col = exit_color(vis["current_status"])
            st.markdown(
                f'<div class="catalyst-card" '
                f'style="border-left-color:{col}; padding:8px 12px;">'
                f'<div><span class="pill" style="background-color:{col}">'
                f'{vis["current_status"]}</span>'
                f'&nbsp;&nbsp;<strong>{vis["scenario"]}</strong></div>'
                f'<div class="meta" style="margin-top:4px">'
                f'trigger: {vis["short_trigger"]}</div>'
                f'<div class="meta">action: {vis["short_action"]}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )


def _render_things_worth_watching(
    st, items: list[WatchItem],
) -> None:  # pragma: no cover
    if not items:
        st.caption("_No headline observations at the moment._")
        return
    level_colors = {
        "broken": "#E74C3C",
        "near": "#F39C12",
        "bull": "#2ECC71",
        "linkage": "#9B59B6",
    }
    for w in items:
        col = level_colors.get(w.level, "#7F8C8D")
        st.markdown(
            f'<div class="catalyst-card" '
            f'style="border-left-color:{col}; padding:8px 12px;">'
            f'<span class="pill" style="background-color:{col}">'
            f'{w.level.upper()}</span>'
            f'&nbsp;&nbsp;<span class="meta">{w.sector}</span>'
            f'&nbsp;&nbsp;{w.text}'
            f'</div>',
            unsafe_allow_html=True,
        )


if __name__ == "__main__":  # pragma: no cover
    render()
