"""V6.9 — Audit the ledger / aggregation substrate (planning-only).

Reads:
  * ``data/research/sector_tracker/company_signal_ledger.csv`` (V6.7)
  * ``data/research/sector_tracker/company_sector_aggregation.csv`` (V6.8)

Writes:
  * ``reports/research/V6_9_LEDGER_AUDIT.md``

The script answers a single planning question: *do we have enough substrate
to attempt the V6.9.1 backtest?* The answer (GO / NO-GO + blockers) is the
last section of the generated Markdown report.

This script does NOT:
  * fetch prices, ETF data, or any market datapoint
  * run a backtest
  * mutate the ledger or the aggregation
  * connect to a broker / send an order
  * connect to a live options data feed or any live market feed

It DOES:
  * read the two CSVs cache-only
  * detect whether a historical canonical-sector-signal log exists
    (today: it does not — V6.6.2 would add one)
  * write a deterministic Markdown audit report

Run manually:

    python scripts/audit_ledger_history.py

``quantbot.LIVE_TRADING_ENABLED`` stays ``False``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

import quantbot
from quantbot.research.sector_tracker import (
    audit_ledger_substrate,
    load_company_ledger,
    load_sector_aggregation,
    render_audit_markdown,
)

DEFAULT_DATA_DIR = ROOT / "data" / "research" / "sector_tracker"
DEFAULT_REPORT_DIR = ROOT / "reports" / "research"
DEFAULT_LEDGER_NAME = "company_signal_ledger.csv"
DEFAULT_AGGREGATION_NAME = "company_sector_aggregation.csv"
DEFAULT_REPORT_NAME = "V6_9_LEDGER_AUDIT.md"

# V6.6.2 — the canonical-sector-signal log path. The refresh script writes
# this on every run (default-on). The audit considers the substrate gap
# resolved once the file exists AND has at least one data row past the
# header (so an empty header-only file does not falsely flip the gate).
DEFAULT_CANONICAL_LOG_NAME = "sector_signal_log.csv"


def _detect_canonical_signal_log(data_dir: Path) -> bool:
    """Return True iff a non-empty canonical-sector-signal log exists.

    "Non-empty" means at least one data row past the header. Before V6.6.2
    landed this always returned False; after V6.6.2 it flips once the
    refresh script has emitted at least one (run_id, sector) row.
    """
    from quantbot.research.sector_tracker import load_sector_signal_log
    p = data_dir / DEFAULT_CANONICAL_LOG_NAME
    if not p.is_file() or p.stat().st_size == 0:
        return False
    # Header-only file (size > 0 but no data rows) does not count.
    return len(load_sector_signal_log(p)) > 0


def main(data_dir: Path | str | None = None,
         report_dir: Path | str | None = None,
         ledger_path: Path | str | None = None,
         aggregation_path: Path | str | None = None,
         report_path: Path | str | None = None) -> dict:
    """Run the audit and write the Markdown report.

    Returns a small summary dict suitable for printing / logging. Missing
    input CSVs are handled gracefully: the audit still runs against the
    (possibly empty) lists and the report's NO-GO section explains why.
    """
    assert quantbot.LIVE_TRADING_ENABLED is False, \
        "V6.9 ledger audit is RESEARCH only."

    ddir = Path(data_dir) if data_dir else DEFAULT_DATA_DIR
    rdir = Path(report_dir) if report_dir else DEFAULT_REPORT_DIR
    lpath = Path(ledger_path) if ledger_path else ddir / DEFAULT_LEDGER_NAME
    apath = (Path(aggregation_path) if aggregation_path
             else ddir / DEFAULT_AGGREGATION_NAME)
    rpath = Path(report_path) if report_path else rdir / DEFAULT_REPORT_NAME

    ledger_rows = load_company_ledger(lpath) if lpath.is_file() else []
    aggregation_rows = (load_sector_aggregation(apath)
                        if apath.is_file() else [])
    has_canonical_log = _detect_canonical_signal_log(ddir)

    summary = audit_ledger_substrate(
        ledger_rows, aggregation_rows,
        has_canonical_signal_history=has_canonical_log,
    )
    markdown = render_audit_markdown(summary)

    rpath.parent.mkdir(parents=True, exist_ok=True)
    rpath.write_text(markdown, encoding="utf-8")

    print(
        f"Audit: {summary.n_ledger_rows} ledger row(s) across "
        f"{summary.n_distinct_runs} run(s); "
        f"{summary.n_aggregation_rows} aggregation row(s). "
        f"backtest_viable={summary.backtest_viable}; "
        f"{len(summary.backtest_blockers)} blocker(s). "
        f"Report -> {rpath}"
    )
    return {
        "ledger_path": str(lpath),
        "aggregation_path": str(apath),
        "report_path": str(rpath),
        "n_ledger_rows": summary.n_ledger_rows,
        "n_distinct_runs": summary.n_distinct_runs,
        "n_aggregation_rows": summary.n_aggregation_rows,
        "n_distinct_agg_runs": summary.n_distinct_agg_runs,
        "backtest_viable": summary.backtest_viable,
        "n_blockers": len(summary.backtest_blockers),
        "has_canonical_signal_history": (
            summary.has_canonical_signal_history
        ),
    }


def cli(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=("V6.9 — Audit the ledger / aggregation substrate. "
                     "Planning-only; does not run a backtest."),
    )
    ap.add_argument("--data-dir", default=None,
                    help="Override data/research/sector_tracker/")
    ap.add_argument("--report-dir", default=None,
                    help="Override reports/research/")
    ap.add_argument("--ledger", default=None,
                    help="Override path to company_signal_ledger.csv")
    ap.add_argument("--aggregation", default=None,
                    help="Override path to company_sector_aggregation.csv")
    ap.add_argument("--report", default=None,
                    help="Override path to V6_9_LEDGER_AUDIT.md")
    args = ap.parse_args(argv)
    main(data_dir=args.data_dir, report_dir=args.report_dir,
         ledger_path=args.ledger, aggregation_path=args.aggregation,
         report_path=args.report)
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
