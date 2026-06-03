"""V6.6.2 — Append-only canonical sector signal log (audit substrate).

Records one row per (run_id, sector) every time the refresh script runs.
Each row snapshots the V6.1 canonical sector signal label and its inputs
(catalyst counts, normalized score, raw score, total weight, emergency-exit
state) at that moment.

**Why this exists.** The V6.1 score is recomputed live from the latest
catalyst CSVs on every dashboard render. There is no historical record of
"what the canonical sector signal was at time *t*" — which the V6.9 audit
correctly flagged as a substrate blocker for any conditional backtest. This
log closes that gap by *passively* recording the signal at every refresh.

**What it is not.** The log is decision-support audit substrate only. It:

  * never affects scoring (it is downstream of ``score_sector``)
  * never emits a trading signal
  * never executes orders
  * never imports a broker, IBKR API, or live market feed
  * never fetches prices, ETFs, or news

Append-only with explicit idempotent mode keyed on ``(run_id, sector)``.
``quantbot.LIVE_TRADING_ENABLED`` stays ``False``.
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from .schema import ALLOWED_SECTORS, SIGNAL_LABELS, Catalyst, EmergencyExit
from .scoring import SectorScore, score_sector

# --------------------------------------------------------------------------- #
# Schema
# --------------------------------------------------------------------------- #
SECTOR_SIGNAL_LOG_FIELDS: tuple[str, ...] = (
    "run_id", "timestamp", "date", "sector",
    "canonical_signal", "normalized_score", "raw_score", "total_weight",
    "n_catalysts",
    "n_bull", "n_neutral", "n_near_threshold", "n_broken",
    "n_emergency_exits", "n_triggered_exits",
    "source_catalyst_file", "source_exit_file",
    "notes",
)


class SectorSignalLogSchemaError(ValueError):
    """Raised when a SectorSignalLogRow fails validation."""


@dataclass
class SectorSignalLogRow:
    """One per-sector canonical-signal snapshot.

    Float fields (``normalized_score`` / ``raw_score``) and int fields (every
    count) are typed so the dataclass catches CSV corruption on load. All
    sector / signal enums are validated against the V6.1 sets.
    """

    run_id: str
    timestamp: str
    date: str
    sector: str
    canonical_signal: str
    normalized_score: float
    raw_score: float
    total_weight: int
    n_catalysts: int
    n_bull: int
    n_neutral: int
    n_near_threshold: int
    n_broken: int
    n_emergency_exits: int
    n_triggered_exits: int
    source_catalyst_file: str = ""
    source_exit_file: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.run_id:
            raise SectorSignalLogSchemaError("run_id is required (non-empty)")
        if not self.timestamp:
            raise SectorSignalLogSchemaError(
                "timestamp is required (non-empty)"
            )
        if not self.sector:
            raise SectorSignalLogSchemaError("sector is required (non-empty)")
        if self.sector not in ALLOWED_SECTORS:
            raise SectorSignalLogSchemaError(
                f"sector must be in {sorted(ALLOWED_SECTORS)}, "
                f"got {self.sector!r}"
            )
        if self.canonical_signal not in SIGNAL_LABELS:
            raise SectorSignalLogSchemaError(
                f"canonical_signal must be in {sorted(SIGNAL_LABELS)}, "
                f"got {self.canonical_signal!r}"
            )
        if not isinstance(self.normalized_score, float):
            raise SectorSignalLogSchemaError(
                f"normalized_score must be float, got "
                f"{type(self.normalized_score).__name__}"
            )
        if not isinstance(self.raw_score, float):
            raise SectorSignalLogSchemaError(
                f"raw_score must be float, got {type(self.raw_score).__name__}"
            )
        for fld in ("total_weight", "n_catalysts", "n_bull", "n_neutral",
                    "n_near_threshold", "n_broken", "n_emergency_exits",
                    "n_triggered_exits"):
            val = getattr(self, fld)
            if not isinstance(val, int):
                raise SectorSignalLogSchemaError(
                    f"{fld} must be int, got {type(val).__name__}"
                )
            if val < 0:
                raise SectorSignalLogSchemaError(
                    f"{fld} must be non-negative, got {val}"
                )
        # Internal consistency: catalyst-status counts must sum to n_catalysts.
        bucket_sum = (self.n_bull + self.n_neutral
                       + self.n_near_threshold + self.n_broken)
        if bucket_sum != self.n_catalysts:
            raise SectorSignalLogSchemaError(
                f"catalyst-status counts sum to {bucket_sum} but "
                f"n_catalysts is {self.n_catalysts}"
            )

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- #
# Row construction
# --------------------------------------------------------------------------- #
def row_from_score(
    score: SectorScore,
    *,
    run_id: str,
    timestamp: str,
    date: str,
    n_emergency_exits: int = 0,
    n_triggered_exits: int = 0,
    source_catalyst_file: str = "",
    source_exit_file: str = "",
    notes: str = "",
) -> SectorSignalLogRow:
    """Project a :class:`SectorScore` into a :class:`SectorSignalLogRow`.

    Pure: copies fields verbatim from the score. The score itself is left
    untouched (scoring is upstream and out of scope for this module).
    """
    return SectorSignalLogRow(
        run_id=run_id,
        timestamp=timestamp,
        date=date,
        sector=score.sector,
        canonical_signal=score.signal,
        normalized_score=float(score.normalized_score),
        raw_score=float(score.raw_score),
        total_weight=int(score.total_weight),
        n_catalysts=int(score.n_total),
        n_bull=int(score.n_bull),
        n_neutral=int(score.n_neutral),
        n_near_threshold=int(score.n_near_threshold),
        n_broken=int(score.n_broken),
        n_emergency_exits=int(n_emergency_exits),
        n_triggered_exits=int(n_triggered_exits),
        source_catalyst_file=source_catalyst_file,
        source_exit_file=source_exit_file,
        notes=notes,
    )


def build_sector_signal_log_rows(
    sector_payloads: dict[str, dict],
    *,
    run_id: str,
    timestamp: str,
    date: str,
    notes: str = "",
) -> list[SectorSignalLogRow]:
    """Build rows from a ``{sector: payload}`` mapping.

    Each payload is ``{"catalysts": [...], "exits": [...],
    "catalyst_file": "...", "exit_file": "..."}``. Sectors whose payload is
    missing/empty (the catalyst CSV was not present at refresh time) are
    skipped silently — that is the "missing sector files handled gracefully"
    contract.
    """
    out: list[SectorSignalLogRow] = []
    for sector in sorted(sector_payloads):
        payload = sector_payloads[sector] or {}
        cats: list[Catalyst] = list(payload.get("catalysts") or [])
        exits: list[EmergencyExit] = list(payload.get("exits") or [])
        if not cats:
            # No catalyst data on disk for this sector — do not synthesise a
            # signal. The audit / planning doc treats missing data as missing.
            continue
        score = score_sector(cats, exits, sector=sector)
        n_exits = len(exits)
        n_triggered = sum(
            1 for e in exits if e.current_status == "TRIGGERED"
        )
        out.append(row_from_score(
            score,
            run_id=run_id, timestamp=timestamp, date=date,
            n_emergency_exits=n_exits,
            n_triggered_exits=n_triggered,
            source_catalyst_file=payload.get("catalyst_file", "") or "",
            source_exit_file=payload.get("exit_file", "") or "",
            notes=notes,
        ))
    return out


# --------------------------------------------------------------------------- #
# I/O — append-only with idempotent mode keyed on (run_id, sector)
# --------------------------------------------------------------------------- #
def load_sector_signal_log(path: str | Path) -> list[SectorSignalLogRow]:
    """Read the signal-log CSV. ``[]`` when the file is missing."""
    p = Path(path)
    if not p.is_file():
        return []
    out: list[SectorSignalLogRow] = []
    with p.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for r in reader:
            kwargs: dict = {k: r.get(k, "") for k in SECTOR_SIGNAL_LOG_FIELDS}
            for fl_field in ("normalized_score", "raw_score"):
                raw = kwargs.get(fl_field, "")
                try:
                    kwargs[fl_field] = float(raw) if str(raw) != "" else 0.0
                except (TypeError, ValueError) as exc:
                    raise SectorSignalLogSchemaError(
                        f"{fl_field} must be float, got {raw!r}"
                    ) from exc
            for int_field in ("total_weight", "n_catalysts", "n_bull",
                              "n_neutral", "n_near_threshold", "n_broken",
                              "n_emergency_exits", "n_triggered_exits"):
                raw = kwargs.get(int_field, "")
                try:
                    kwargs[int_field] = int(raw) if str(raw) != "" else 0
                except (TypeError, ValueError) as exc:
                    raise SectorSignalLogSchemaError(
                        f"{int_field} must be int, got {raw!r}"
                    ) from exc
            out.append(SectorSignalLogRow(**kwargs))
    return out


def ensure_sector_signal_log_header(path: str | Path) -> Path:
    """Write the header row when the file is missing/empty. Never touches
    existing rows."""
    p = Path(path)
    if p.is_file() and p.stat().st_size > 0:
        return p
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(SECTOR_SIGNAL_LOG_FIELDS))
        writer.writeheader()
    return p


def _existing_keys(path: Path) -> set[tuple[str, str]]:
    if not path.is_file() or path.stat().st_size == 0:
        return set()
    keys: set[tuple[str, str]] = set()
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for r in reader:
            keys.add((r.get("run_id", ""), r.get("sector", "")))
    return keys


def append_sector_signal_log_rows(
    rows: Iterable[SectorSignalLogRow],
    path: str | Path,
    *,
    mode: str = "idempotent",
) -> dict:
    """Append rows to the signal log. Append-only; never truncates.

    Modes (mirror V6.7 ledger / V6.8 aggregation):
      * ``"idempotent"`` (default) — skip input rows whose
        ``(run_id, sector)`` is already on disk.
      * ``"append"`` — append every row unconditionally.
      * ``"strict"`` — raise on collision.

    Returns ``{"n_input": N, "n_appended": M, "n_skipped": S}``.
    """
    if mode not in {"idempotent", "append", "strict"}:
        raise ValueError(
            f"mode must be 'idempotent' / 'append' / 'strict', got {mode!r}"
        )

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    existing = _existing_keys(p)
    needs_header = not p.is_file() or p.stat().st_size == 0

    rows_list = list(rows)
    n_input = len(rows_list)
    to_write: list[SectorSignalLogRow] = []
    n_skipped = 0

    for r in rows_list:
        key = (r.run_id, r.sector)
        if key in existing:
            if mode == "strict":
                raise SectorSignalLogSchemaError(
                    f"duplicate signal-log key already in file: {key!r}"
                )
            if mode == "idempotent":
                n_skipped += 1
                continue
            # mode == "append" -> fall through and write
        to_write.append(r)
        existing.add(key)

    with p.open("a", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(SECTOR_SIGNAL_LOG_FIELDS))
        if needs_header:
            writer.writeheader()
        for r in to_write:
            writer.writerow(r.to_dict())

    return {
        "n_input": n_input,
        "n_appended": len(to_write),
        "n_skipped": n_skipped,
    }


__all__ = [
    "SECTOR_SIGNAL_LOG_FIELDS",
    "SectorSignalLogRow", "SectorSignalLogSchemaError",
    "row_from_score", "build_sector_signal_log_rows",
    "load_sector_signal_log", "ensure_sector_signal_log_header",
    "append_sector_signal_log_rows",
]
