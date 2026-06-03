"""V6.8 — Build / append company-derived sector aggregation from the ledger.

Reads the V6.7 company signal ledger at:

    data/research/sector_tracker/company_signal_ledger.csv

groups its rows by ``run_id``, computes the categorical
``company_derived_read`` per (sector, run_id), and APPENDS the result to:

    data/research/sector_tracker/company_sector_aggregation.csv

Run manually:

    # Aggregate only the most-recent run_id present in the ledger
    python scripts/build_company_sector_aggregation.py

    # Backfill the aggregation across every distinct run_id in the ledger
    python scripts/build_company_sector_aggregation.py --all-runs

The script does NOT:
  * mutate the ledger (read-only consumer)
  * change canonical sector scoring or any V6.1/V6.2-V6.4 driver output
  * fetch from the network
  * connect to a broker / send an order
  * emit a trading signal — the company-derived read is an audit / research
    view only

It DOES:
  * read the ledger CSV cache-only
  * pick the latest run_id (default) or every run_id (``--all-runs``)
  * append exactly one row per (run_id, sector) per build, idempotently by
    ``(run_id, sector)``: re-running with the same ledger snapshot is a
    silent no-op
  * create the aggregation CSV with its header on first run

If the ledger is missing the script prints a friendly message and exits 0
with a no-op summary — nothing is written.

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
    append_sector_aggregation_rows,
    build_sector_aggregation_rows,
    ensure_sector_aggregation_header,
    load_company_ledger,
)

DEFAULT_DATA_DIR = ROOT / "data" / "research" / "sector_tracker"
DEFAULT_LEDGER_NAME = "company_signal_ledger.csv"
DEFAULT_AGGREGATION_NAME = "company_sector_aggregation.csv"


def _runs_to_process(ledger_rows: list, *, all_runs: bool,
                     explicit_run_id: str | None) -> list[str]:
    """Decide which run_ids the aggregator should emit rows for.

    Preserves the original order of first appearance in the ledger (ledger
    is append-only, so order is stable across reads). If ``explicit_run_id``
    is supplied it must be present in the ledger or :class:`ValueError`
    is raised.
    """
    seen: list[str] = []
    seen_set: set[str] = set()
    for r in ledger_rows:
        if r.run_id not in seen_set:
            seen.append(r.run_id)
            seen_set.add(r.run_id)

    if explicit_run_id is not None:
        if explicit_run_id not in seen_set:
            raise ValueError(
                f"run_id {explicit_run_id!r} not present in the ledger"
            )
        return [explicit_run_id]

    if all_runs:
        return seen
    if not seen:
        return []
    return [seen[-1]]


def main(data_dir: Path | str | None = None,
         ledger_path: Path | str | None = None,
         aggregation_path: Path | str | None = None,
         *,
         all_runs: bool = False,
         run_id: str | None = None,
         mode: str = "idempotent") -> dict:
    """Build the company-derived sector aggregation rows and append them.

    Parameters
    ----------
    data_dir
        Override ``data/research/sector_tracker/``.
    ledger_path
        Override the company-signal-ledger CSV path.
    aggregation_path
        Override the aggregation CSV path.
    all_runs
        When ``True`` aggregate every distinct ``run_id`` in the ledger.
        Otherwise only the most-recent run is emitted.
    run_id
        Optional explicit run_id — must already be present in the ledger.
    mode
        ``"idempotent"`` / ``"append"`` / ``"strict"`` — passed to
        :func:`append_sector_aggregation_rows`.
    """
    assert quantbot.LIVE_TRADING_ENABLED is False, \
        "V6.8 aggregation build is RESEARCH only."

    ddir = Path(data_dir) if data_dir else DEFAULT_DATA_DIR
    lpath = Path(ledger_path) if ledger_path else ddir / DEFAULT_LEDGER_NAME
    apath = (Path(aggregation_path) if aggregation_path
             else ddir / DEFAULT_AGGREGATION_NAME)

    if not lpath.is_file():
        print(f"company-ledger not found at {lpath} — nothing to aggregate. "
              "Run scripts/build_company_signal_ledger.py first.")
        return {
            "ledger_path": str(lpath),
            "aggregation_path": str(apath),
            "n_runs_processed": 0,
            "n_rows_built": 0,
            "n_appended": 0,
            "n_skipped": 0,
            "ledger_missing": True,
        }

    ledger_rows = load_company_ledger(lpath)
    if not ledger_rows:
        print(f"company-ledger at {lpath} is empty — nothing to aggregate.")
        return {
            "ledger_path": str(lpath),
            "aggregation_path": str(apath),
            "n_runs_processed": 0,
            "n_rows_built": 0,
            "n_appended": 0,
            "n_skipped": 0,
            "ledger_missing": False,
        }

    runs = _runs_to_process(ledger_rows, all_runs=all_runs,
                             explicit_run_id=run_id)

    all_built = []
    for rid in runs:
        rows_for_run = [r for r in ledger_rows if r.run_id == rid]
        all_built.extend(build_sector_aggregation_rows(
            rows_for_run, run_id=rid, source_ledger=lpath.name,
        ))

    ensure_sector_aggregation_header(apath)
    result = append_sector_aggregation_rows(all_built, apath, mode=mode)

    summary = {
        "ledger_path": str(lpath),
        "aggregation_path": str(apath),
        "n_runs_processed": len(runs),
        "n_rows_built": len(all_built),
        "ledger_missing": False,
        **result,
    }
    print(f"Aggregation: processed {len(runs)} run(s), "
          f"built {len(all_built)} rows, "
          f"appended {result['n_appended']} "
          f"(skipped {result['n_skipped']}) "
          f"to {apath.name} [mode={mode}].")
    return summary


def cli(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=("V6.8 — Build company-derived sector aggregation from "
                     "the V6.7 company signal ledger. Audit / research view; "
                     "does NOT alter canonical sector scoring."),
    )
    ap.add_argument("--data-dir", default=None,
                    help="Override data/research/sector_tracker/")
    ap.add_argument("--ledger", default=None,
                    help="Override path to company_signal_ledger.csv")
    ap.add_argument("--aggregation", default=None,
                    help="Override path to company_sector_aggregation.csv")
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--all-runs", action="store_true",
                       help=("Aggregate every distinct run_id present in "
                             "the ledger (backfill mode)."))
    group.add_argument("--run-id", default=None,
                       help=("Aggregate only this specific run_id (must "
                             "already be present in the ledger)."))
    ap.add_argument("--mode",
                    choices=("idempotent", "append", "strict"),
                    default="idempotent",
                    help="Write mode (default: idempotent)")
    args = ap.parse_args(argv)

    main(data_dir=args.data_dir, ledger_path=args.ledger,
         aggregation_path=args.aggregation,
         all_runs=args.all_runs, run_id=args.run_id,
         mode=args.mode)
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
