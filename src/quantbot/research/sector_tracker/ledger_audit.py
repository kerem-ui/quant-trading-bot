"""V6.9 — Ledger / aggregation substrate audit (planning-only).

Pure, read-only descriptive statistics over the V6.7 company signal ledger
and the V6.8 company-derived sector aggregation. The audit asks a single
question: *do we have enough substrate to even attempt the V6.9.1 backtest?*

It is NOT a backtest. It does not consume future prices, forward returns,
ETF mappings, or canonical-vs-company-derived edge measurements — those
belong to V6.9.1 only if this audit clears the go/no-go bar in
``reports/research/V6_9_BACKTEST_PLAN.md``.

What this module produces:

  * :class:`LedgerAuditSummary` — counts, time span, per-sector read
    distributions, per-(sector, run) divergence frequencies derived strictly
    from already-present ledger + aggregation rows. No simulated signals.
  * :func:`audit_ledger_substrate` — pure function: takes the two lists,
    returns the summary.
  * :func:`render_audit_markdown` — turns the summary into a deterministic
    Markdown report.

What this module deliberately does NOT do:

  * Fetch prices / ETF data / fundamentals.
  * Compute or assume any "canonical signal at run_id T" — the canonical
    V6.1 sector score is re-derived live from catalysts and there is no
    historical snapshot on disk. The audit reports this **substrate gap**
    rather than papering over it.
  * Touch the broker, the IBKR API, a live options data feed, or any
    network resource.
  * Mutate the ledger, aggregation, or any scoring path.

``quantbot.LIVE_TRADING_ENABLED`` stays ``False``.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Mapping

from .company_aggregation import (
    ALLOWED_COMPANY_DERIVED_READ,
    SectorAggregationRow,
)
from .company_ledger import ALLOWED_READ, CompanyLedgerRow
from .schema import ALLOWED_SECTORS

# Minimum substrate to even consider a V6.9.1 backtest. These thresholds are
# deliberately conservative; the planning doc cites the rationale. They are
# constants here so the audit's go/no-go is reproducible by inspection.
MIN_RUNS_PER_SECTOR_FOR_BACKTEST: int = 30
MIN_AGG_RUNS_FOR_BACKTEST: int = 30
MIN_CALENDAR_DAYS_FOR_BACKTEST: int = 90


class LedgerAuditSchemaError(ValueError):
    """Raised when an audit summary fails validation."""


@dataclass(frozen=True)
class LedgerAuditSummary:
    """Substrate snapshot used to decide whether V6.9.1 can run.

    All counts are integers; all strings are deterministic. Designed to
    round-trip via ``to_dict()`` for JSON / CSV serialisation if a future
    audit history becomes useful.
    """

    # Ledger side.
    n_ledger_rows: int
    n_distinct_runs: int
    n_distinct_dates: int
    earliest_run_id: str
    latest_run_id: str
    earliest_date: str
    latest_date: str
    n_sectors_seen: int
    per_sector_run_counts: dict[str, int] = field(default_factory=dict)
    per_sector_ticker_counts: dict[str, int] = field(default_factory=dict)
    per_sector_read_distribution: dict[str, dict[str, int]] = field(
        default_factory=dict
    )
    # Aggregation side.
    n_aggregation_rows: int = 0
    n_distinct_agg_runs: int = 0
    per_sector_agg_run_counts: dict[str, int] = field(default_factory=dict)
    per_sector_company_derived_distribution: dict[str, dict[str, int]] = field(
        default_factory=dict
    )
    # Substrate-gap diagnostics.
    has_canonical_signal_history: bool = False
    # Go/no-go.
    backtest_viable: bool = False
    backtest_blockers: list[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- #
# Pure helpers (testable in isolation).
# --------------------------------------------------------------------------- #
def _unique_sorted(values) -> list[str]:
    return sorted(set(values))


def _per_sector_read_distribution(
    rows: list[CompanyLedgerRow],
) -> dict[str, dict[str, int]]:
    """Return ``{sector: {read: count}}`` over the supplied ledger rows.

    Sectors not appearing in ``rows`` are omitted. Reads must be in
    :data:`ALLOWED_READ`; an unknown read raises :class:`LedgerAuditSchemaError`
    so a corrupted CSV fails fast rather than producing silent zeros.
    """
    out: dict[str, dict[str, int]] = {}
    for r in rows:
        if r.read not in ALLOWED_READ:
            raise LedgerAuditSchemaError(
                f"ledger row {r.ticker!r}/{r.run_id!r} has unknown "
                f"read={r.read!r}; expected one of {sorted(ALLOWED_READ)}"
            )
        out.setdefault(r.sector, Counter())[r.read] += 1
    return {sec: dict(c) for sec, c in out.items()}


def _per_sector_company_derived_distribution(
    rows: list[SectorAggregationRow],
) -> dict[str, dict[str, int]]:
    """Return ``{sector: {company_derived_read: count}}`` over aggregations."""
    out: dict[str, dict[str, int]] = {}
    for r in rows:
        if r.company_derived_read not in ALLOWED_COMPANY_DERIVED_READ:
            raise LedgerAuditSchemaError(
                f"aggregation row {r.sector!r}/{r.run_id!r} has unknown "
                f"company_derived_read={r.company_derived_read!r}"
            )
        out.setdefault(r.sector, Counter())[r.company_derived_read] += 1
    return {sec: dict(c) for sec, c in out.items()}


def _evaluate_go_no_go(
    *, n_distinct_runs: int,
    n_distinct_dates: int,
    per_sector_run_counts: Mapping[str, int],
    n_distinct_agg_runs: int,
    has_canonical_signal_history: bool,
) -> tuple[bool, list[str]]:
    """Return ``(viable, blockers)`` per the planning-doc thresholds.

    Blockers are surfaced as plain-English strings the operator can read in
    the generated Markdown report without re-reading the source code.
    """
    blockers: list[str] = []

    if n_distinct_runs < MIN_AGG_RUNS_FOR_BACKTEST:
        blockers.append(
            f"only {n_distinct_runs} distinct ledger run_id(s) — backtest "
            f"plan requires at least {MIN_AGG_RUNS_FOR_BACKTEST}."
        )
    if n_distinct_agg_runs < MIN_AGG_RUNS_FOR_BACKTEST:
        blockers.append(
            f"only {n_distinct_agg_runs} distinct aggregation run_id(s); "
            f"need at least {MIN_AGG_RUNS_FOR_BACKTEST}."
        )
    if n_distinct_dates < MIN_CALENDAR_DAYS_FOR_BACKTEST:
        blockers.append(
            f"ledger spans only {n_distinct_dates} distinct calendar date(s); "
            f"need at least {MIN_CALENDAR_DAYS_FOR_BACKTEST} to model 5d / "
            f"20d / 60d forward horizons without near-total overlap."
        )

    short_sectors = [
        s for s in sorted(ALLOWED_SECTORS)
        if per_sector_run_counts.get(s, 0) < MIN_RUNS_PER_SECTOR_FOR_BACKTEST
    ]
    if short_sectors:
        blockers.append(
            "per-sector ledger run counts below the "
            f"{MIN_RUNS_PER_SECTOR_FOR_BACKTEST}-run minimum: "
            + ", ".join(
                f"{s}={per_sector_run_counts.get(s, 0)}"
                for s in short_sectors
            )
        )

    if not has_canonical_signal_history:
        blockers.append(
            "no historical canonical-sector-signal log on disk (the V6.1 "
            "score is recomputed live from the latest catalyst CSVs). The "
            "backtest needs a per-(run_id, sector) snapshot of the canonical "
            "signal to measure divergence over time. Recommend a small "
            "V6.6.2 sector_signal_log.csv emitter BEFORE V6.9.1 starts."
        )

    return (len(blockers) == 0), blockers


def audit_ledger_substrate(
    ledger_rows: list[CompanyLedgerRow],
    aggregation_rows: list[SectorAggregationRow],
    *,
    has_canonical_signal_history: bool = False,
) -> LedgerAuditSummary:
    """Compute a deterministic substrate snapshot from the two lists.

    Pure: no I/O, no globals besides the pre-declared constants. Callers
    (the script + the tests) supply already-loaded lists so this is testable
    in isolation.

    ``has_canonical_signal_history`` is a caller-supplied flag; the audit
    cannot detect this on its own (the file simply does not exist today)
    and the planning doc tracks it as a substrate gap until V6.6.2.
    """
    # --- ledger side ------------------------------------------------------ #
    n_ledger_rows = len(ledger_rows)
    run_ids = _unique_sorted(r.run_id for r in ledger_rows)
    dates = _unique_sorted(r.date for r in ledger_rows)
    sectors_seen = _unique_sorted(r.sector for r in ledger_rows)

    per_sector_run_counts: dict[str, int] = {}
    per_sector_ticker_counts: dict[str, int] = {}
    for sec in sectors_seen:
        sec_rows = [r for r in ledger_rows if r.sector == sec]
        per_sector_run_counts[sec] = len({r.run_id for r in sec_rows})
        per_sector_ticker_counts[sec] = len({r.ticker for r in sec_rows})

    per_sector_read_distribution = _per_sector_read_distribution(ledger_rows)

    # --- aggregation side ------------------------------------------------- #
    n_aggregation_rows = len(aggregation_rows)
    agg_run_ids = _unique_sorted(r.run_id for r in aggregation_rows)

    per_sector_agg_run_counts: dict[str, int] = {}
    for sec in _unique_sorted(r.sector for r in aggregation_rows):
        per_sector_agg_run_counts[sec] = len(
            {r.run_id for r in aggregation_rows if r.sector == sec}
        )

    per_sector_company_derived_distribution = (
        _per_sector_company_derived_distribution(aggregation_rows)
    )

    # --- go/no-go --------------------------------------------------------- #
    viable, blockers = _evaluate_go_no_go(
        n_distinct_runs=len(run_ids),
        n_distinct_dates=len(dates),
        per_sector_run_counts=per_sector_run_counts,
        n_distinct_agg_runs=len(agg_run_ids),
        has_canonical_signal_history=has_canonical_signal_history,
    )
    notes = ("backtest substrate OK; proceed to V6.9.1 design review."
             if viable else
             f"backtest substrate insufficient — {len(blockers)} blocker(s) "
             "documented; recommend deferring V6.9.1.")

    return LedgerAuditSummary(
        n_ledger_rows=n_ledger_rows,
        n_distinct_runs=len(run_ids),
        n_distinct_dates=len(dates),
        earliest_run_id=run_ids[0] if run_ids else "",
        latest_run_id=run_ids[-1] if run_ids else "",
        earliest_date=dates[0] if dates else "",
        latest_date=dates[-1] if dates else "",
        n_sectors_seen=len(sectors_seen),
        per_sector_run_counts=per_sector_run_counts,
        per_sector_ticker_counts=per_sector_ticker_counts,
        per_sector_read_distribution=per_sector_read_distribution,
        n_aggregation_rows=n_aggregation_rows,
        n_distinct_agg_runs=len(agg_run_ids),
        per_sector_agg_run_counts=per_sector_agg_run_counts,
        per_sector_company_derived_distribution=(
            per_sector_company_derived_distribution
        ),
        has_canonical_signal_history=has_canonical_signal_history,
        backtest_viable=viable,
        backtest_blockers=blockers,
        notes=notes,
    )


# --------------------------------------------------------------------------- #
# Markdown rendering — deterministic; suitable for committing to reports/.
# --------------------------------------------------------------------------- #
def _format_count_dict(d: Mapping[str, int]) -> str:
    if not d:
        return "_(none)_"
    return ", ".join(f"`{k}`: {v}" for k, v in sorted(d.items()))


def _format_nested_count(d: Mapping[str, Mapping[str, int]]) -> str:
    if not d:
        return "_(none)_"
    lines = []
    for sec in sorted(d):
        inner = ", ".join(f"`{k}`: {v}" for k, v in sorted(d[sec].items()))
        lines.append(f"- **{sec}** — {inner}")
    return "\n".join(lines)


def render_audit_markdown(summary: LedgerAuditSummary) -> str:
    """Return a deterministic Markdown report for the audit summary.

    The output is suitable for committing to ``reports/research/`` and
    stable enough for a goldens-style test (same input → byte-identical
    output).
    """
    blockers = (
        "\n".join(f"- {b}" for b in summary.backtest_blockers)
        if summary.backtest_blockers else "_(none — substrate clears the bar)_"
    )
    viability = ("✅ **GO** — substrate clears every gate"
                 if summary.backtest_viable else
                 "🛑 **NO-GO** — defer V6.9.1 until blockers are resolved")
    canon_flag = ("✅ historical canonical-sector-signal log present"
                  if summary.has_canonical_signal_history else
                  "⚠ no historical canonical-sector-signal log on disk")

    parts = [
        "# V6.9 — Ledger / aggregation substrate audit",
        "",
        "_Auto-generated by `scripts/audit_ledger_history.py` — "
        "do not hand-edit; re-run the script to refresh._",
        "",
        ("**Purpose.** Decide whether the V6.7 company signal ledger and "
         "V6.8 company-derived sector aggregation contain enough substrate "
         "to attempt the V6.9.1 backtest described in "
         "`V6_9_BACKTEST_PLAN.md`. **This file does NOT run a backtest** — "
         "it counts what we have."),
        "",
        f"**Verdict:** {viability}",
        "",
        "## Headline counts",
        "",
        f"- Ledger rows: **{summary.n_ledger_rows}**",
        f"- Distinct ledger run_ids: **{summary.n_distinct_runs}**",
        f"- Distinct calendar dates: **{summary.n_distinct_dates}**",
        f"- Earliest run_id: `{summary.earliest_run_id or 'n/a'}` "
        f"({summary.earliest_date or 'n/a'})",
        f"- Latest run_id: `{summary.latest_run_id or 'n/a'}` "
        f"({summary.latest_date or 'n/a'})",
        f"- Sectors observed in the ledger: **{summary.n_sectors_seen}**",
        f"- Aggregation rows: **{summary.n_aggregation_rows}**",
        f"- Distinct aggregation run_ids: **{summary.n_distinct_agg_runs}**",
        "",
        "## Per-sector ledger run counts",
        "",
        _format_count_dict(summary.per_sector_run_counts),
        "",
        "## Per-sector unique tickers in the ledger",
        "",
        _format_count_dict(summary.per_sector_ticker_counts),
        "",
        "## Per-sector ledger read distribution",
        "",
        _format_nested_count(summary.per_sector_read_distribution),
        "",
        "## Per-sector aggregation run counts",
        "",
        _format_count_dict(summary.per_sector_agg_run_counts),
        "",
        "## Per-sector company-derived read distribution",
        "",
        _format_nested_count(
            summary.per_sector_company_derived_distribution
        ),
        "",
        "## Substrate gaps",
        "",
        f"- {canon_flag}.",
        "",
        "## Backtest go/no-go blockers",
        "",
        blockers,
        "",
        "## Notes",
        "",
        summary.notes or "_(none)_",
        "",
        "---",
        "",
        ("Thresholds applied (see "
         "`src/quantbot/research/sector_tracker/ledger_audit.py`):"),
        "",
        f"- `MIN_RUNS_PER_SECTOR_FOR_BACKTEST = "
        f"{MIN_RUNS_PER_SECTOR_FOR_BACKTEST}`",
        f"- `MIN_AGG_RUNS_FOR_BACKTEST = {MIN_AGG_RUNS_FOR_BACKTEST}`",
        f"- `MIN_CALENDAR_DAYS_FOR_BACKTEST = "
        f"{MIN_CALENDAR_DAYS_FOR_BACKTEST}`",
        "",
        ("Guardrails: `LIVE_TRADING_ENABLED = False`. This audit is "
         "research-only and never executes orders, fetches market data, or "
         "scrapes news."),
        "",
    ]
    return "\n".join(parts)


__all__ = [
    # constants
    "MIN_RUNS_PER_SECTOR_FOR_BACKTEST",
    "MIN_AGG_RUNS_FOR_BACKTEST",
    "MIN_CALENDAR_DAYS_FOR_BACKTEST",
    # schema
    "LedgerAuditSummary", "LedgerAuditSchemaError",
    # functions
    "audit_ledger_substrate", "render_audit_markdown",
]
