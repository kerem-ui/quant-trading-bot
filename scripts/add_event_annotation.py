"""V6.6.1 — Append one operator-curated event annotation (context only).

Adds a single validated row to:

    data/research/sector_tracker/event_annotations.csv

This is **context only** — annotations never affect sector scoring, the V6.7
company-signal ledger, or any downstream backtest. The file is the same V6.6
schema; V6.6.1 only adds the ``COMPANY_SIGNAL`` ``related_type`` so operators
can attach a note to a company-ledger row.

Run manually:

    # Annotate a catalyst (e.g. a SEC filing landed)
    python scripts/add_event_annotation.py \\
        --sector AI --related-id AI-MSFT-REV-T1 --related-type CATALYST \\
        --ticker MSFT --event-type SEC_FILING \\
        --title "Q3 FY26 10-Q filed" \\
        --note "Azure +30% YoY; cloud capex guide raised." \\
        --source SEC_EDGAR --source-url-or-file "edgar:0001234-26-000045" \\
        --added-by kerem --confidence HIGH

    # Annotate a company-signal row (V6.6.1 new related_type)
    python scripts/add_event_annotation.py \\
        --sector SEMICONDUCTOR --related-id NVDA --related-type COMPANY_SIGNAL \\
        --ticker NVDA --event-type EARNINGS \\
        --title "FY27Q1 print" \\
        --note "DC revenue +110% YoY; inventory days +18%." \\
        --source PRESS_RELEASE \\
        --source-url-or-file "https://investor.nvidia.com/2026-05-29" \\
        --added-by kerem --confidence MEDIUM

The script does NOT:
  * fetch from the network
  * scrape news / web pages
  * connect to a broker / send an order
  * mutate catalysts, exits, the change log, or the company-signal ledger
  * affect scoring or the sector signal label

It DOES:
  * validate every field via the V6.6 ``EventAnnotation`` dataclass + a few
    extra non-empty checks the operator workflow needs (title / note /
    source / related_id must all be non-empty)
  * APPEND one row in append-mode — prior rows are never rewritten
  * create the CSV with the V6.6 header if it doesn't yet exist

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
    ALLOWED_SECTORS,
    ChangeLogSchemaError,
    EventAnnotation,
    append_event_annotations,
    ensure_event_annotations_header,
)
from quantbot.research.sector_tracker.change_log import (
    ALLOWED_CONFIDENCE,
    ALLOWED_EVENT_TYPE,
    ALLOWED_RELATED_TYPE,
)

DEFAULT_ANNOTATIONS_PATH = (
    ROOT / "data" / "research" / "sector_tracker" / "event_annotations.csv"
)


class AnnotationValidationError(ValueError):
    """Raised when the operator-supplied annotation fails CLI-level checks
    that go beyond the V6.6 dataclass schema (e.g. empty title / source)."""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _require_non_empty(value: str, name: str) -> None:
    if not value or not value.strip():
        raise AnnotationValidationError(f"{name} must be non-empty")


def add_event_annotation(
    *,
    sector: str,
    related_id: str,
    related_type: str,
    event_type: str,
    title: str,
    note: str,
    source: str,
    ticker: str = "",
    source_url_or_file: str = "",
    added_by: str = "",
    confidence: str = "",
    timestamp: str | None = None,
    annotations_path: Path | str | None = None,
) -> dict:
    """Validate and append one annotation. Returns a small summary dict.

    The function is pure-ish: only I/O is the single append + (possibly)
    header creation on the annotation CSV. Defaults to the standard path
    under ``data/research/sector_tracker/event_annotations.csv``.

    Required operator-level non-empty fields: ``related_id``, ``title``,
    ``note``, ``source``. These go beyond the V6.6 dataclass (which allows
    blank title / note / source for backwards-compat with the empty
    placeholder CSV emitted on first refresh).
    """
    assert quantbot.LIVE_TRADING_ENABLED is False, \
        "V6.6.1 annotation helper is RESEARCH only."

    # CLI-level non-empty checks beyond the schema.
    _require_non_empty(related_id, "related_id")
    _require_non_empty(title, "title")
    _require_non_empty(note, "note")
    _require_non_empty(source, "source")

    # Enum sanity (the dataclass will also re-check, but we surface a friendlier
    # error here before construction).
    if sector and sector not in ALLOWED_SECTORS:
        raise AnnotationValidationError(
            f"sector must be empty or in {sorted(ALLOWED_SECTORS)}, "
            f"got {sector!r}"
        )
    if related_type not in ALLOWED_RELATED_TYPE:
        raise AnnotationValidationError(
            f"related_type must be in {sorted(ALLOWED_RELATED_TYPE)}, "
            f"got {related_type!r}"
        )
    if event_type not in ALLOWED_EVENT_TYPE:
        raise AnnotationValidationError(
            f"event_type must be in {sorted(ALLOWED_EVENT_TYPE)}, "
            f"got {event_type!r}"
        )
    if confidence and confidence not in ALLOWED_CONFIDENCE:
        raise AnnotationValidationError(
            f"confidence must be empty or in {sorted(ALLOWED_CONFIDENCE)}, "
            f"got {confidence!r}"
        )

    ts = timestamp or _utc_now_iso()
    apath = Path(annotations_path) if annotations_path \
        else DEFAULT_ANNOTATIONS_PATH

    # Defensive: dataclass __post_init__ re-validates everything.
    try:
        ann = EventAnnotation(
            timestamp=ts, sector=sector, related_id=related_id,
            related_type=related_type, ticker=ticker,
            event_type=event_type, title=title, note=note,
            source=source, source_url_or_file=source_url_or_file,
            added_by=added_by, confidence=confidence,
        )
    except ChangeLogSchemaError:
        # Re-raise as the CLI's error type so callers can catch one class.
        raise

    ensure_event_annotations_header(apath)
    n_appended = append_event_annotations([ann], apath)

    return {
        "timestamp": ts,
        "annotations_path": str(apath),
        "n_appended": n_appended,
        "related_id": related_id,
        "related_type": related_type,
        "event_type": event_type,
    }


def cli(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=("V6.6.1 — append ONE operator-curated event annotation "
                     "to event_annotations.csv. Context only — never affects "
                     "scoring or the company-signal ledger."),
    )
    ap.add_argument("--sector", default="",
                    help=("Sector tag. Empty allowed; if set, must be in "
                          f"{sorted(ALLOWED_SECTORS)}."))
    ap.add_argument("--related-id", required=True,
                    help="The catalyst_id / exit_id / ticker being annotated.")
    ap.add_argument("--related-type", required=True,
                    choices=sorted(ALLOWED_RELATED_TYPE),
                    help="What the related_id refers to.")
    ap.add_argument("--ticker", default="",
                    help="Optional ticker tag (e.g. MSFT). May be blank.")
    ap.add_argument("--event-type", required=True,
                    choices=sorted(ALLOWED_EVENT_TYPE),
                    help="Event category.")
    ap.add_argument("--title", required=True,
                    help="Short headline (non-empty).")
    ap.add_argument("--note", required=True,
                    help="Free-text note (non-empty).")
    ap.add_argument("--source", required=True,
                    help="Source label, e.g. SEC_EDGAR, PRESS_RELEASE.")
    ap.add_argument("--source-url-or-file", default="",
                    help="Optional URL / file reference.")
    ap.add_argument("--added-by", default="",
                    help="Optional operator name / handle.")
    ap.add_argument("--confidence", default="",
                    choices=("", *sorted(ALLOWED_CONFIDENCE)),
                    help="Optional LOW / MEDIUM / HIGH confidence tag.")
    ap.add_argument("--timestamp", default=None,
                    help=("Optional ISO timestamp. Defaults to UTC now "
                          "(``YYYY-MM-DDTHH:MM:SS+00:00``)."))
    ap.add_argument("--annotations", default=None,
                    help="Override path to event_annotations.csv.")

    args = ap.parse_args(argv)

    try:
        summary = add_event_annotation(
            sector=args.sector,
            related_id=args.related_id,
            related_type=args.related_type,
            ticker=args.ticker,
            event_type=args.event_type,
            title=args.title,
            note=args.note,
            source=args.source,
            source_url_or_file=args.source_url_or_file,
            added_by=args.added_by,
            confidence=args.confidence,
            timestamp=args.timestamp,
            annotations_path=args.annotations,
        )
    except (AnnotationValidationError, ChangeLogSchemaError) as exc:
        print(f"annotation rejected: {exc}", file=sys.stderr)
        return 2

    print(f"Appended 1 annotation [{summary['related_type']}/"
          f"{summary['related_id']}] to "
          f"{Path(summary['annotations_path']).name}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
