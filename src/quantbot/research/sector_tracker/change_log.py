"""V6.6 — Append-only change log + operator-curated event annotations.

Pure schema + I/O for tracking what changes between sector-tracker refreshes
and for attaching CONTEXT-ONLY annotations to catalysts / exits.

Two record types live here:

  * :class:`Change` — one row per (record, field) that differed between a
    prior and a new snapshot of a sector-tracker CSV. Logged via the V6.6
    refresh script (``scripts/refresh_sector_trackers.py``) into an
    APPEND-ONLY CSV at ``data/research/sector_tracker/change_log.csv``.

  * :class:`EventAnnotation` — operator-curated context attached to a
    catalyst, emergency exit, or sector. Written manually into
    ``data/research/sector_tracker/event_annotations.csv``. **Annotations are
    context-only.** They never feed scoring, never act as a trading signal,
    and never trigger any automated decision.

The V6.5 dashboard imports only the LOAD helpers from this module — it never
writes. The refresh script is the only writer. No broker / IBKR / order
execution code lives here. ``quantbot.LIVE_TRADING_ENABLED`` stays ``False``.
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

from .schema import ALLOWED_SECTORS, Catalyst, EmergencyExit

# --------------------------------------------------------------------------- #
# Enumerations
# --------------------------------------------------------------------------- #
ALLOWED_RECORD_TYPE: frozenset[str] = frozenset({"CATALYST", "EMERGENCY_EXIT"})

# Sentinels (BASELINE / ADDED / REMOVED) plus the catalyst/exit fields we
# actually diff on. Adding a new diffable field requires extending this set
# AND the diff helpers below.
ALLOWED_FIELD_CHANGED: frozenset[str] = frozenset({
    "BASELINE", "ADDED", "REMOVED",
    "current_value", "status", "current_status",
    "source_type", "source_detail", "threshold", "tier",
})

ALLOWED_RELATED_TYPE: frozenset[str] = frozenset(
    # V6.6 launched with CATALYST / EMERGENCY_EXIT / SECTOR. V6.6.1 adds
    # COMPANY_SIGNAL so operators can annotate a ticker-level row in the
    # V6.7 company signal ledger. The new value extends the existing schema
    # additively — no existing rows or callers need to change.
    {"CATALYST", "EMERGENCY_EXIT", "SECTOR", "COMPANY_SIGNAL"}
)
ALLOWED_EVENT_TYPE: frozenset[str] = frozenset({
    "SEC_FILING", "EARNINGS", "MACRO", "NEWS", "MANUAL_NOTE", "OTHER",
})
ALLOWED_CONFIDENCE: frozenset[str] = frozenset({"LOW", "MEDIUM", "HIGH"})

# Frozen CSV column orders.
CHANGE_LOG_FIELDS: tuple[str, ...] = (
    "timestamp", "sector", "record_type", "record_id",
    "field_changed", "prior_value", "new_value",
    "prior_status", "new_status",
    "source_file", "source_date", "refresh_run_id", "notes",
)

EVENT_ANNOTATION_FIELDS: tuple[str, ...] = (
    "timestamp", "sector", "related_id", "related_type", "ticker",
    "event_type", "title", "note", "source", "source_url_or_file",
    "added_by", "confidence",
)


class ChangeLogSchemaError(ValueError):
    """Raised when a Change or EventAnnotation row fails schema validation."""


# --------------------------------------------------------------------------- #
# Dataclasses
# --------------------------------------------------------------------------- #
@dataclass
class Change:
    """One change-log row.

    A single (record_id, field_changed) pair → one row. Multiple changed
    fields on the same record become multiple rows with the same record_id and
    timestamp / refresh_run_id, which keeps the log fine-grained and filterable.
    """

    timestamp: str
    sector: str
    record_type: str
    record_id: str
    field_changed: str
    prior_value: str
    new_value: str
    prior_status: str
    new_status: str
    source_file: str
    source_date: str
    refresh_run_id: str
    notes: str = ""

    def __post_init__(self) -> None:
        if self.sector not in ALLOWED_SECTORS:
            raise ChangeLogSchemaError(
                f"sector must be in {sorted(ALLOWED_SECTORS)}, "
                f"got {self.sector!r}"
            )
        if self.record_type not in ALLOWED_RECORD_TYPE:
            raise ChangeLogSchemaError(
                f"record_type must be in {sorted(ALLOWED_RECORD_TYPE)}, "
                f"got {self.record_type!r}"
            )
        if self.field_changed not in ALLOWED_FIELD_CHANGED:
            raise ChangeLogSchemaError(
                f"field_changed must be in {sorted(ALLOWED_FIELD_CHANGED)}, "
                f"got {self.field_changed!r}"
            )
        if not self.record_id:
            raise ChangeLogSchemaError("record_id is required (non-empty)")
        if not self.timestamp:
            raise ChangeLogSchemaError("timestamp is required (non-empty)")
        if not self.refresh_run_id:
            raise ChangeLogSchemaError("refresh_run_id is required (non-empty)")

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class EventAnnotation:
    """One operator-curated annotation row.

    Context only — NEVER a trading signal. Validates the enumerations but
    leaves the free-text fields (``title``, ``note``, ``source_url_or_file``,
    ``added_by``) up to the operator.
    """

    timestamp: str
    sector: str
    related_id: str
    related_type: str
    ticker: str
    event_type: str
    title: str
    note: str
    source: str
    source_url_or_file: str
    added_by: str
    confidence: str

    def __post_init__(self) -> None:
        # sector may be blank when related_type == "SECTOR" but is then
        # required to match an allowed sector value.
        if self.sector and self.sector not in ALLOWED_SECTORS:
            raise ChangeLogSchemaError(
                f"sector must be empty or in {sorted(ALLOWED_SECTORS)}, "
                f"got {self.sector!r}"
            )
        if self.related_type not in ALLOWED_RELATED_TYPE:
            raise ChangeLogSchemaError(
                f"related_type must be in {sorted(ALLOWED_RELATED_TYPE)}, "
                f"got {self.related_type!r}"
            )
        if self.event_type not in ALLOWED_EVENT_TYPE:
            raise ChangeLogSchemaError(
                f"event_type must be in {sorted(ALLOWED_EVENT_TYPE)}, "
                f"got {self.event_type!r}"
            )
        if self.confidence and self.confidence not in ALLOWED_CONFIDENCE:
            raise ChangeLogSchemaError(
                f"confidence must be empty or in {sorted(ALLOWED_CONFIDENCE)}, "
                f"got {self.confidence!r}"
            )
        if not self.related_id:
            raise ChangeLogSchemaError("related_id is required (non-empty)")
        if not self.timestamp:
            raise ChangeLogSchemaError("timestamp is required (non-empty)")

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- #
# I/O helpers
# --------------------------------------------------------------------------- #
def load_change_log(path: str | Path) -> list[Change]:
    """Read the append-only change log. ``[]`` if the file is missing."""
    p = Path(path)
    if not p.is_file():
        return []
    out: list[Change] = []
    with p.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for r in reader:
            kwargs = {k: r.get(k, "") for k in CHANGE_LOG_FIELDS}
            out.append(Change(**kwargs))  # __post_init__ validates
    return out


def append_changes(changes: Iterable[Change], path: str | Path) -> int:
    """Append rows to ``path`` in append-mode. Creates the file + header if
    missing. **Never truncates** or rewrites existing rows."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    needs_header = not p.is_file() or p.stat().st_size == 0
    n = 0
    with p.open("a", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(CHANGE_LOG_FIELDS))
        if needs_header:
            writer.writeheader()
        for c in changes:
            writer.writerow(c.to_dict())
            n += 1
    return n


def ensure_change_log_header(path: str | Path) -> Path:
    """Write the header row if the file is missing or empty. Existing rows
    are NEVER touched."""
    p = Path(path)
    if p.is_file() and p.stat().st_size > 0:
        return p
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(CHANGE_LOG_FIELDS))
        writer.writeheader()
    return p


def load_event_annotations(path: str | Path) -> list[EventAnnotation]:
    """Read the operator-curated annotation CSV. ``[]`` if the file is missing."""
    p = Path(path)
    if not p.is_file():
        return []
    out: list[EventAnnotation] = []
    with p.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for r in reader:
            kwargs = {k: r.get(k, "") for k in EVENT_ANNOTATION_FIELDS}
            out.append(EventAnnotation(**kwargs))  # __post_init__ validates
    return out


def ensure_event_annotations_header(path: str | Path) -> Path:
    """Write the annotation header if the file is missing or empty."""
    p = Path(path)
    if p.is_file() and p.stat().st_size > 0:
        return p
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(EVENT_ANNOTATION_FIELDS))
        writer.writeheader()
    return p


def append_event_annotations(
    annotations: Iterable[EventAnnotation], path: str | Path,
) -> int:
    """V6.6.1 — Append rows to the event-annotations CSV.

    Sibling of :func:`append_changes`: creates the file + header if missing,
    appends in ``"a"`` mode, **never truncates** or rewrites existing rows.
    Returns the number of rows written.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    needs_header = not p.is_file() or p.stat().st_size == 0
    n = 0
    with p.open("a", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(EVENT_ANNOTATION_FIELDS))
        if needs_header:
            writer.writeheader()
        for a in annotations:
            writer.writerow(a.to_dict())
            n += 1
    return n


# --------------------------------------------------------------------------- #
# Pure diff helpers
# --------------------------------------------------------------------------- #
_DIFF_FIELDS_CATALYST: tuple[str, ...] = (
    "current_value", "status", "source_type", "source_detail", "threshold",
)


def compute_catalyst_diff(
    prior: list[Catalyst],
    new: list[Catalyst],
    *,
    sector: str,
    run_id: str,
    timestamp: str,
    source_file: str = "",
) -> list[Change]:
    """Return ``Change`` rows describing every (record, field) difference
    between ``prior`` and ``new`` catalyst sets for one sector.

    PURE — no I/O, no time-of-day, no global state. ``timestamp`` and
    ``run_id`` are caller-supplied so the same diff is reproducible.
    """
    prior_idx = {c.catalyst_id: c for c in prior}
    new_idx = {c.catalyst_id: c for c in new}
    out: list[Change] = []

    # ADDED
    for cid in sorted(set(new_idx) - set(prior_idx)):
        c = new_idx[cid]
        out.append(Change(
            timestamp=timestamp, sector=sector, record_type="CATALYST",
            record_id=cid, field_changed="ADDED",
            prior_value="", new_value=c.catalyst_name,
            prior_status="", new_status=c.status,
            source_file=source_file, source_date=c.last_updated,
            refresh_run_id=run_id,
            notes=f"source_type={c.source_type}",
        ))

    # REMOVED
    for cid in sorted(set(prior_idx) - set(new_idx)):
        c = prior_idx[cid]
        out.append(Change(
            timestamp=timestamp, sector=sector, record_type="CATALYST",
            record_id=cid, field_changed="REMOVED",
            prior_value=c.catalyst_name, new_value="",
            prior_status=c.status, new_status="",
            source_file=source_file, source_date=c.last_updated,
            refresh_run_id=run_id, notes="",
        ))

    # CHANGED (intersection)
    for cid in sorted(set(new_idx) & set(prior_idx)):
        po, ne = prior_idx[cid], new_idx[cid]
        for fld in _DIFF_FIELDS_CATALYST:
            pv = getattr(po, fld)
            nv = getattr(ne, fld)
            if pv != nv:
                out.append(Change(
                    timestamp=timestamp, sector=sector,
                    record_type="CATALYST", record_id=cid,
                    field_changed=fld,
                    prior_value=str(pv), new_value=str(nv),
                    prior_status=po.status, new_status=ne.status,
                    source_file=source_file, source_date=ne.last_updated,
                    refresh_run_id=run_id, notes="",
                ))
        if po.tier != ne.tier:
            out.append(Change(
                timestamp=timestamp, sector=sector,
                record_type="CATALYST", record_id=cid,
                field_changed="tier",
                prior_value=str(po.tier), new_value=str(ne.tier),
                prior_status=po.status, new_status=ne.status,
                source_file=source_file, source_date=ne.last_updated,
                refresh_run_id=run_id, notes="",
            ))
    return out


def compute_exit_diff(
    prior: list[EmergencyExit],
    new: list[EmergencyExit],
    *,
    sector: str,
    run_id: str,
    timestamp: str,
    source_file: str = "",
) -> list[Change]:
    """Diff helper for ``EmergencyExit`` rows. Only ``current_status`` is
    tracked as a per-field change (the rest is text-only)."""
    prior_idx = {e.exit_id: e for e in prior}
    new_idx = {e.exit_id: e for e in new}
    out: list[Change] = []

    for eid in sorted(set(new_idx) - set(prior_idx)):
        e = new_idx[eid]
        out.append(Change(
            timestamp=timestamp, sector=sector,
            record_type="EMERGENCY_EXIT", record_id=eid,
            field_changed="ADDED",
            prior_value="", new_value=e.scenario,
            prior_status="", new_status=e.current_status,
            source_file=source_file, source_date=e.last_updated,
            refresh_run_id=run_id, notes="",
        ))
    for eid in sorted(set(prior_idx) - set(new_idx)):
        e = prior_idx[eid]
        out.append(Change(
            timestamp=timestamp, sector=sector,
            record_type="EMERGENCY_EXIT", record_id=eid,
            field_changed="REMOVED",
            prior_value=e.scenario, new_value="",
            prior_status=e.current_status, new_status="",
            source_file=source_file, source_date=e.last_updated,
            refresh_run_id=run_id, notes="",
        ))
    for eid in sorted(set(new_idx) & set(prior_idx)):
        po, ne = prior_idx[eid], new_idx[eid]
        if po.current_status != ne.current_status:
            out.append(Change(
                timestamp=timestamp, sector=sector,
                record_type="EMERGENCY_EXIT", record_id=eid,
                field_changed="current_status",
                prior_value=po.current_status, new_value=ne.current_status,
                prior_status=po.current_status, new_status=ne.current_status,
                source_file=source_file, source_date=ne.last_updated,
                refresh_run_id=run_id, notes="",
            ))
    return out


def baseline_change(
    sector: str, *, n_catalysts: int, n_exits: int,
    timestamp: str, run_id: str,
) -> Change:
    """Single sentinel row emitted when a sector has no prior CSV at all.

    Avoids flooding the change log with N×ADDED rows for the founding state.
    """
    return Change(
        timestamp=timestamp, sector=sector, record_type="CATALYST",
        record_id="__BASELINE__", field_changed="BASELINE",
        prior_value="", new_value=f"{n_catalysts} catalysts, {n_exits} exits",
        prior_status="", new_status="",
        source_file="", source_date=str(date.fromisoformat(timestamp[:10])),
        refresh_run_id=run_id,
        notes="Initial baseline snapshot — no prior CSV existed.",
    )


__all__ = [
    # enumerations + schema
    "ALLOWED_RECORD_TYPE", "ALLOWED_FIELD_CHANGED",
    "ALLOWED_RELATED_TYPE", "ALLOWED_EVENT_TYPE", "ALLOWED_CONFIDENCE",
    "CHANGE_LOG_FIELDS", "EVENT_ANNOTATION_FIELDS",
    "ChangeLogSchemaError", "Change", "EventAnnotation",
    # I/O
    "load_change_log", "append_changes", "ensure_change_log_header",
    "load_event_annotations", "ensure_event_annotations_header",
    "append_event_annotations",
    # diff
    "compute_catalyst_diff", "compute_exit_diff", "baseline_change",
]
