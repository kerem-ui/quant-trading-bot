"""V6.7 — Build / append the company signal ledger from existing catalyst CSVs.

Reads the per-sector thesis-tracker CSVs that the V6.2.1 / V6.3 / V6.4 drivers
produce, derives one categorical company read per ticker in the pre-declared
universe, and APPENDS the result to:

    data/research/sector_tracker/company_signal_ledger.csv

Run manually:

    python scripts/build_company_signal_ledger.py

The script does NOT:
  * fetch from the network
  * connect to a broker / send an order
  * mutate any per-sector catalyst CSV
  * affect the sector signal / score (V6.7 is read-only; V6.8 may aggregate)
  * delete or overwrite prior ledger rows

It DOES:
  * read the three per-sector ``*_thesis_tracker.csv`` files (skips missing)
  * derive a categorical ``read`` per company from the loaded catalysts only
  * APPEND new rows in idempotent mode (re-running with the same ``run_id``
    is a no-op for already-written ``(run_id, sector, ticker)`` tuples)

``quantbot.LIVE_TRADING_ENABLED`` stays ``False``.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

import quantbot
from quantbot.research.sector_tracker import (
    append_company_ledger_rows,
    build_company_ledger_rows,
    ensure_company_ledger_header,
    load_catalysts,
)

DEFAULT_DATA_DIR = ROOT / "data" / "research" / "sector_tracker"
DEFAULT_LEDGER_NAME = "company_signal_ledger.csv"

# Per-sector catalyst CSV names — must stay in sync with the drivers.
SECTOR_CATALYST_FILES: dict[str, str] = {
    "SEMICONDUCTOR": "semiconductor_thesis_tracker.csv",
    "AI": "ai_thesis_tracker.csv",
    "ENERGY": "energy_thesis_tracker.csv",
}


def _load_catalysts_by_sector(data_dir: Path) -> dict[str, list]:
    """Read each per-sector catalyst CSV. Missing files yield an empty list."""
    out: dict[str, list] = {}
    for sec, name in SECTOR_CATALYST_FILES.items():
        p = data_dir / name
        out[sec] = load_catalysts(p) if p.is_file() else []
    return out


def main(data_dir: Path | str | None = None,
         ledger_path: Path | str | None = None,
         run_id: str | None = None,
         mode: str = "idempotent",
         notes: str = "",
         *, as_of_date: str | None = None,
         timestamp: str | None = None) -> dict:
    """Build the company ledger from disk and append it.

    Parameters
    ----------
    data_dir
        Override ``data/research/sector_tracker/``.
    ledger_path
        Override the ledger CSV path. Default is
        ``<data_dir>/company_signal_ledger.csv``.
    run_id
        Caller-supplied run identifier. Defaults to the UTC ISO timestamp
        (``YYYY-MM-DDTHH-MM-SSZ``) matching the V6.6 refresh script style.
    mode
        ``"idempotent"`` / ``"append"`` / ``"strict"`` — passed to
        :func:`append_company_ledger_rows`.
    notes
        Free-text note copied onto every emitted row.
    as_of_date, timestamp
        Test hooks for deterministic builds.
    """
    assert quantbot.LIVE_TRADING_ENABLED is False, \
        "V6.7 company-ledger build is RESEARCH only."

    ddir = Path(data_dir) if data_dir else DEFAULT_DATA_DIR
    lpath = Path(ledger_path) if ledger_path else ddir / DEFAULT_LEDGER_NAME

    now = datetime.now(timezone.utc)
    ts = timestamp or now.isoformat(timespec="seconds")
    rid = run_id or now.strftime("%Y-%m-%dT%H-%M-%SZ")
    asof = as_of_date or now.strftime("%Y-%m-%d")

    cats_by_sec = _load_catalysts_by_sector(ddir)
    rows = build_company_ledger_rows(
        cats_by_sec,
        run_id=rid, timestamp=ts, as_of_date=asof, notes=notes,
    )

    ensure_company_ledger_header(lpath)
    result = append_company_ledger_rows(rows, lpath, mode=mode)

    n_sectors_loaded = sum(1 for v in cats_by_sec.values() if v)
    summary = {
        "run_id": rid,
        "timestamp": ts,
        "as_of_date": asof,
        "mode": mode,
        "ledger_path": str(lpath),
        "n_sectors_loaded": n_sectors_loaded,
        "n_rows_built": len(rows),
        **result,
    }
    print(f"Company ledger {rid}: built {len(rows)} rows from "
          f"{n_sectors_loaded}/3 sectors, "
          f"appended {result['n_appended']} (skipped {result['n_skipped']}) "
          f"to {lpath.name} [mode={mode}].")
    return summary


def cli() -> int:
    ap = argparse.ArgumentParser(
        description=("V6.7 company signal ledger build — append-only, "
                     "read-only sources, no trading."),
    )
    ap.add_argument("--data-dir", default=None,
                    help="Override data/research/sector_tracker/")
    ap.add_argument("--ledger", default=None,
                    help="Override path to company_signal_ledger.csv")
    ap.add_argument("--run-id", default=None,
                    help="Override the run_id (default: UTC timestamp)")
    ap.add_argument("--mode",
                    choices=("idempotent", "append", "strict"),
                    default="idempotent",
                    help="Write mode (default: idempotent)")
    ap.add_argument("--notes", default="",
                    help="Optional free-text note copied onto every row")
    args = ap.parse_args()
    main(data_dir=args.data_dir, ledger_path=args.ledger,
         run_id=args.run_id, mode=args.mode, notes=args.notes)
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
