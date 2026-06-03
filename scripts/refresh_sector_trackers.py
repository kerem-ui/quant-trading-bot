"""V6.6 sector-tracker refresh script (manual trigger only, read-only sources).

Snapshots each sector's current CSVs, re-runs the V6.2.1 / V6.3 / V6.4 sector
drivers (which read EXISTING local caches and overwrite the per-sector CSVs +
markdown reports), then computes a per-(record, field) diff between the prior
and new state and APPENDS the diff to an append-only change log at:

    data/research/sector_tracker/change_log.csv

It also ensures an empty operator-curated annotation CSV exists at:

    data/research/sector_tracker/event_annotations.csv

Run manually:

    python scripts/refresh_sector_trackers.py

The script does NOT:
  * fetch new ThetaData
  * scrape the web
  * connect to a broker / send an order
  * mutate V6.1 schema/scoring/builder/report_writer
  * delete or overwrite the change-log's prior rows
  * run continuously / start a daemon

It DOES:
  * import + call the three sector driver ``main()`` functions
  * read existing local SEC + FRED + VIX caches (cache-only)
  * write the per-sector CSVs / markdown that the drivers regenerate
  * APPEND diff rows (and possibly a single baseline row per sector on the
    very first refresh) to ``change_log.csv``
  * create ``event_annotations.csv`` with a header row if missing
"""

from __future__ import annotations

import argparse
import importlib
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import quantbot
from quantbot.research.sector_tracker import (
    Change,
    append_changes,
    append_sector_signal_log_rows,
    baseline_change,
    build_sector_signal_log_rows,
    compute_catalyst_diff,
    compute_exit_diff,
    ensure_change_log_header,
    ensure_event_annotations_header,
    ensure_sector_signal_log_header,
    load_catalysts,
    load_exits,
)

DEFAULT_DATA_DIR = ROOT / "data" / "research" / "sector_tracker"
DEFAULT_REPORT_DIR = ROOT / "reports" / "research" / "sector_tracker"

# (driver_module_name, catalyst_csv_name, exits_csv_name)
SECTOR_DRIVERS: dict[str, tuple[str, str, str]] = {
    "SEMICONDUCTOR": (
        "run_sector_tracker_semi",
        "semiconductor_thesis_tracker.csv",
        "semiconductor_emergency_exits.csv",
    ),
    "AI": (
        "run_sector_tracker_ai",
        "ai_thesis_tracker.csv",
        "ai_emergency_exits.csv",
    ),
    "ENERGY": (
        "run_sector_tracker_energy",
        "energy_thesis_tracker.csv",
        "energy_emergency_exits.csv",
    ),
}


# --------------------------------------------------------------------------- #
# Pure-ish helpers
# --------------------------------------------------------------------------- #
def _snapshot_sector(data_dir: Path, sector: str):
    """Return (catalysts_or_None, exits_or_None) reading existing CSVs only.

    ``None`` means "no prior CSV existed for that record type". An empty list
    means "the CSV existed but had zero rows" (still treated as a prior).
    """
    _, cat_name, exit_name = SECTOR_DRIVERS[sector]
    cat_path = data_dir / cat_name
    exit_path = data_dir / exit_name
    cats = load_catalysts(cat_path) if cat_path.is_file() else None
    exits = load_exits(exit_path) if exit_path.is_file() else None
    return cats, exits


def _run_driver(driver_name: str, data_dir: Path, report_dir: Path) -> Any:
    """Import the sector driver module and call its ``main()`` with overrides.

    The drivers are deterministic given a fixed cache state and a fixed
    ``REPORT_DATE`` constant, so re-running here produces byte-identical CSVs
    when nothing in the underlying caches has changed.

    ``scripts/`` is re-added to ``sys.path`` here at call-time so this function
    works regardless of how this refresh module was imported (e.g. tests may
    legitimately clean ``sys.path`` between fixtures).
    """
    scripts_dir = str(ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    mod = importlib.import_module(driver_name)
    return mod.main(data_dir=data_dir, report_dir=report_dir)


# --------------------------------------------------------------------------- #
# Orchestrator
# --------------------------------------------------------------------------- #
def main(data_dir: Path | str | None = None,
         report_dir: Path | str | None = None,
         change_log_path: Path | str | None = None,
         annotations_path: Path | str | None = None,
         run_id: str | None = None,
         *, skip_driver_run: bool = False,
         with_company_ledger: bool = False,
         company_ledger_path: Path | str | None = None,
         with_sector_signal_log: bool = True,
         sector_signal_log_path: Path | str | None = None) -> dict:
    """Snapshot prior → run drivers → snapshot new → diff → append.

    Parameters
    ----------
    skip_driver_run
        Internal test hook — when ``True``, the drivers are NOT invoked. The
        function still snapshots prior + new (which will be identical) and
        appends the resulting diff (empty under steady state). Useful when
        a test has its own way of mutating the CSVs to exercise the diff
        machinery without paying the driver runtime.
    with_sector_signal_log
        V6.6.2 — when ``True`` (default), append one canonical-signal row
        per sector to ``sector_signal_log.csv`` using the post-driver state.
        Idempotent by ``(run_id, sector)``, so re-running with the same
        ``run_id`` is a silent no-op for already-logged sectors.
    """
    assert quantbot.LIVE_TRADING_ENABLED is False, \
        "V6.6 refresh script is RESEARCH only."

    ddir = Path(data_dir) if data_dir else DEFAULT_DATA_DIR
    rdir = Path(report_dir) if report_dir else DEFAULT_REPORT_DIR
    clog = Path(change_log_path) if change_log_path \
        else ddir / "change_log.csv"
    annp = Path(annotations_path) if annotations_path \
        else ddir / "event_annotations.csv"

    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    run_id = run_id or datetime.now(timezone.utc).strftime(
        "%Y-%m-%dT%H-%M-%SZ"
    )

    # 1. Snapshot prior state BEFORE running any driver.
    prior: dict[str, tuple] = {}
    for sec in SECTOR_DRIVERS:
        prior[sec] = _snapshot_sector(ddir, sec)

    # 2. Run drivers (unless test-skipped). Each driver writes its CSVs +
    #    markdown report into ddir / rdir.
    driver_summaries: dict[str, Any] = {}
    if not skip_driver_run:
        for sec, (drv_mod, _, _) in SECTOR_DRIVERS.items():
            driver_summaries[sec] = _run_driver(drv_mod, ddir, rdir)

    # 3. Snapshot new state AFTER drivers wrote.
    new: dict[str, tuple] = {}
    for sec in SECTOR_DRIVERS:
        new[sec] = _snapshot_sector(ddir, sec)

    # 4. Compute changes.
    changes: list[Change] = []
    n_baseline = 0
    for sec in SECTOR_DRIVERS:
        prior_cats, prior_exits = prior[sec]
        new_cats, new_exits = new[sec]

        # Baseline path: no prior CSV existed for either record type.
        if prior_cats is None and prior_exits is None:
            changes.append(baseline_change(
                sec,
                n_catalysts=len(new_cats or []),
                n_exits=len(new_exits or []),
                timestamp=ts, run_id=run_id,
            ))
            n_baseline += 1
            continue

        # Normal diff (independently for catalysts + exits).
        if prior_cats is not None and new_cats is not None:
            changes.extend(compute_catalyst_diff(
                prior_cats, new_cats, sector=sec,
                run_id=run_id, timestamp=ts,
                source_file=SECTOR_DRIVERS[sec][1],
            ))
        if prior_exits is not None and new_exits is not None:
            changes.extend(compute_exit_diff(
                prior_exits, new_exits, sector=sec,
                run_id=run_id, timestamp=ts,
                source_file=SECTOR_DRIVERS[sec][2],
            ))

    # 5. Ensure file headers exist and append.
    ensure_change_log_header(clog)
    n_appended = append_changes(changes, clog) if changes else 0

    # 6. Ensure annotations file exists with header (does not write data).
    ensure_event_annotations_header(annp)

    n_catalyst_changes = sum(1 for c in changes if c.record_type == "CATALYST"
                              and c.field_changed != "BASELINE")
    n_exit_changes = sum(1 for c in changes
                         if c.record_type == "EMERGENCY_EXIT")
    print(f"Refresh {run_id}: {len(changes)} changes "
          f"({n_baseline} baseline, {n_catalyst_changes} catalyst, "
          f"{n_exit_changes} exit) — {n_appended} appended to {clog.name}.")

    # 7. V6.7 — Optionally append company-ledger rows. Opt-in (default False)
    #    so existing manual-refresh behaviour is unchanged. Reuses the same
    #    run_id / timestamp for traceability and is itself idempotent: a
    #    second refresh with the same run_id is a no-op on the ledger.
    company_ledger_summary: dict | None = None
    if with_company_ledger:
        import build_company_signal_ledger as _ledger_mod
        lpath = Path(company_ledger_path) if company_ledger_path \
            else ddir / "company_signal_ledger.csv"
        company_ledger_summary = _ledger_mod.main(
            data_dir=ddir, ledger_path=lpath,
            run_id=run_id, timestamp=ts,
            as_of_date=ts[:10],
            mode="idempotent",
            notes="appended via refresh_sector_trackers",
        )

    # 8. V6.6.2 — Append canonical sector signal log rows. DEFAULT-ON: this
    #    is the audit substrate the V6.9 plan needs and there is no reason
    #    not to record it on every refresh. Idempotent by (run_id, sector).
    #    Sectors whose catalyst CSV was missing post-driver are skipped.
    sector_signal_log_summary: dict | None = None
    if with_sector_signal_log:
        slpath = Path(sector_signal_log_path) if sector_signal_log_path \
            else ddir / "sector_signal_log.csv"
        payloads: dict[str, dict] = {}
        for sec, (cat_name, exit_name) in (
            (s, (SECTOR_DRIVERS[s][1], SECTOR_DRIVERS[s][2]))
            for s in SECTOR_DRIVERS
        ):
            new_cats, new_exits = new[sec]
            payloads[sec] = {
                "catalysts": new_cats or [],
                "exits": new_exits or [],
                "catalyst_file": cat_name,
                "exit_file": exit_name,
            }
        sig_rows = build_sector_signal_log_rows(
            payloads, run_id=run_id, timestamp=ts, date=ts[:10],
            notes="appended via refresh_sector_trackers",
        )
        ensure_sector_signal_log_header(slpath)
        sl_result = append_sector_signal_log_rows(sig_rows, slpath)
        sector_signal_log_summary = {
            "sector_signal_log_path": str(slpath),
            "n_rows_built": len(sig_rows),
            **sl_result,
        }
        print(
            f"Sector signal log: built {len(sig_rows)} row(s), "
            f"appended {sl_result['n_appended']} "
            f"(skipped {sl_result['n_skipped']}) "
            f"to {slpath.name}."
        )

    return {
        "run_id": run_id,
        "timestamp": ts,
        "n_changes": len(changes),
        "n_appended": n_appended,
        "n_baseline": n_baseline,
        "n_catalyst_changes": n_catalyst_changes,
        "n_exit_changes": n_exit_changes,
        "change_log_path": str(clog),
        "annotations_path": str(annp),
        "driver_summaries": driver_summaries,
        "company_ledger_summary": company_ledger_summary,
        "sector_signal_log_summary": sector_signal_log_summary,
    }


def cli() -> int:
    ap = argparse.ArgumentParser(
        description="V6.6 sector-tracker refresh (manual trigger, read-only).",
    )
    ap.add_argument("--data-dir", default=None,
                    help="Override data/research/sector_tracker/")
    ap.add_argument("--report-dir", default=None,
                    help="Override reports/research/sector_tracker/")
    ap.add_argument("--change-log", default=None,
                    help="Override path to change_log.csv")
    ap.add_argument("--annotations", default=None,
                    help="Override path to event_annotations.csv")
    ap.add_argument("--with-company-ledger", action="store_true",
                    help=("V6.7 opt-in: also append a company-signal-ledger "
                          "snapshot after the diff is appended."))
    ap.add_argument("--company-ledger", default=None,
                    help="Override path to company_signal_ledger.csv")
    ap.add_argument("--no-sector-signal-log", action="store_true",
                    help=("V6.6.2 opt-out: skip the canonical sector signal "
                          "log append (default is ON — recording history is "
                          "the V6.9 substrate the audit needs)."))
    ap.add_argument("--sector-signal-log", default=None,
                    help="Override path to sector_signal_log.csv")
    args = ap.parse_args()
    main(data_dir=args.data_dir, report_dir=args.report_dir,
         change_log_path=args.change_log,
         annotations_path=args.annotations,
         with_company_ledger=args.with_company_ledger,
         company_ledger_path=args.company_ledger,
         with_sector_signal_log=(not args.no_sector_signal_log),
         sector_signal_log_path=args.sector_signal_log)
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
