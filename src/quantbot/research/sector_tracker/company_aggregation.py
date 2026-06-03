"""V6.8 — Company-derived sector aggregation (audit / research view).

Reads the V6.7 company signal ledger (one row per company per run) and
produces a parallel **categorical** sector roll-up — *one row per
(run_id, sector)* — into a separate CSV.

This is a **separate audit view, not a replacement** for the canonical V6.1
sector score. ``score_sector`` outputs are untouched; the company-derived
read can be compared side-by-side with the canonical sector signal to surface
divergence (e.g. canonical sector ``HOLD`` while company-derived view is
``CAUTION`` because three companies are MIXED + one is BROKEN).

Design rules (all categorical, no hidden numeric scoring):

  1. ``n_active == 0`` (everything ``N/A``) → ``N_A``
  2. ``n_broken >= 1``:
       * ``BROKEN`` if ``n_broken >= n_bull`` (broken dominates or ties)
       * else ``CAUTION`` (a few brokens with a bull majority — surface caution
         rather than forcing bullish)
  3. ``n_mixed + n_near_threshold >= 1``:
       * ``CAUTION`` if ``(n_mixed + n_near) >= n_bull`` (many MIXED never gets
         a forced bullish read)
       * else ``MIXED``
  4. ``n_bull > 0`` and ``n_bull >= max(n_neutral, n_tracked)`` → ``BULL``
  5. ``n_tracked > n_neutral`` and ``n_tracked >= n_bull`` → ``TRACKED_HEAVY``
  6. otherwise → ``NEUTRAL``

The labels mirror V6.5.2's worst-bucket-first philosophy: ``BROKEN`` /
``CAUTION`` only ever override bull when the negative evidence is at least
as strong as the bull evidence. A solitary ``BROKEN`` in a fleet of bulls is
``CAUTION``, not ``BROKEN``.

``quantbot.LIVE_TRADING_ENABLED`` stays ``False``. Nothing here imports a
broker, IBKR API, or order module. The aggregation never feeds the canonical
sector scorer, never emits a trading signal, never executes an order.
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Mapping

from .company_ledger import ALLOWED_READ, CompanyLedgerRow
from .schema import ALLOWED_SECTORS

# --------------------------------------------------------------------------- #
# Enumerations
# --------------------------------------------------------------------------- #
ALLOWED_COMPANY_DERIVED_READ: frozenset[str] = frozenset({
    "BULL", "MIXED", "NEUTRAL", "CAUTION",
    "BROKEN", "TRACKED_HEAVY", "N_A",
})

# Maximum number of tickers surfaced in each top_* field of the row.
TOP_TICKERS_CAP: int = 5

AGGREGATION_FIELDS: tuple[str, ...] = (
    "run_id", "timestamp", "date", "sector",
    "n_companies", "n_bull", "n_mixed", "n_neutral",
    "n_near_threshold", "n_broken", "n_tracked", "n_na",
    "company_derived_read",
    "top_bull_companies", "top_mixed_or_risk_companies",
    "tracked_only_companies",
    "notes", "source_ledger",
)

# Map ledger ``read`` values to aggregation column names.
_READ_TO_COUNT: dict[str, str] = {
    "BULL": "n_bull",
    "MIXED": "n_mixed",
    "NEUTRAL": "n_neutral",
    "NEAR_THRESHOLD": "n_near_threshold",
    "BROKEN": "n_broken",
    "TRACKED": "n_tracked",
    "N/A": "n_na",
}


class CompanyAggregationSchemaError(ValueError):
    """Raised when a SectorAggregationRow fails validation."""


# --------------------------------------------------------------------------- #
# Dataclass
# --------------------------------------------------------------------------- #
@dataclass
class SectorAggregationRow:
    """One company-derived sector roll-up row.

    Counts are integers; everything else is free-text composed from the
    underlying ledger rows. ``company_derived_read`` is the only enumerated
    string field.
    """

    run_id: str
    timestamp: str
    date: str
    sector: str
    n_companies: int
    n_bull: int
    n_mixed: int
    n_neutral: int
    n_near_threshold: int
    n_broken: int
    n_tracked: int
    n_na: int
    company_derived_read: str
    top_bull_companies: str            # ";"-joined tickers
    top_mixed_or_risk_companies: str   # ";"-joined tickers
    tracked_only_companies: str        # ";"-joined tickers
    notes: str = ""
    source_ledger: str = ""

    def __post_init__(self) -> None:
        if not self.run_id:
            raise CompanyAggregationSchemaError(
                "run_id is required (non-empty)"
            )
        if not self.timestamp:
            raise CompanyAggregationSchemaError(
                "timestamp is required (non-empty)"
            )
        if not self.sector:
            raise CompanyAggregationSchemaError(
                "sector is required (non-empty)"
            )
        if self.sector not in ALLOWED_SECTORS:
            raise CompanyAggregationSchemaError(
                f"sector must be in {sorted(ALLOWED_SECTORS)}, "
                f"got {self.sector!r}"
            )
        if self.company_derived_read not in ALLOWED_COMPANY_DERIVED_READ:
            raise CompanyAggregationSchemaError(
                "company_derived_read must be in "
                f"{sorted(ALLOWED_COMPANY_DERIVED_READ)}, "
                f"got {self.company_derived_read!r}"
            )
        # All count fields must be non-negative ints.
        for fld in ("n_companies", "n_bull", "n_mixed", "n_neutral",
                    "n_near_threshold", "n_broken", "n_tracked", "n_na"):
            val = getattr(self, fld)
            if not isinstance(val, int):
                raise CompanyAggregationSchemaError(
                    f"{fld} must be int, got {type(val).__name__}"
                )
            if val < 0:
                raise CompanyAggregationSchemaError(
                    f"{fld} must be non-negative, got {val}"
                )
        # Internal consistency — counts must sum to n_companies.
        bucket_sum = (self.n_bull + self.n_mixed + self.n_neutral
                       + self.n_near_threshold + self.n_broken
                       + self.n_tracked + self.n_na)
        if bucket_sum != self.n_companies:
            raise CompanyAggregationSchemaError(
                f"bucket counts sum to {bucket_sum} but n_companies is "
                f"{self.n_companies}"
            )

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- #
# Pure derivation — categorical only, no hidden numeric scoring.
# --------------------------------------------------------------------------- #
def derive_company_derived_read(counts: Mapping[str, int]) -> str:
    """Return the categorical ``company_derived_read`` for one sector.

    ``counts`` is keyed by the aggregation column names
    (``n_bull`` / ``n_mixed`` / ``n_neutral`` / ``n_near_threshold`` /
    ``n_broken`` / ``n_tracked`` / ``n_na``). Missing keys default to 0.

    Rules (first match wins):

      1. ``n_active`` (all buckets except ``n_na``) == 0  →  ``N_A``
      2. ``n_broken >= 1``:
           - ``BROKEN`` if ``n_broken >= n_bull``  (dominates or ties)
           - else ``CAUTION``
      3. ``n_mixed + n_near_threshold >= 1``:
           - ``CAUTION`` if ``(n_mixed + n_near) >= n_bull``
           - else ``MIXED``
      4. ``n_bull > 0`` and ``n_bull >= max(n_neutral, n_tracked)`` → ``BULL``
      5. ``n_tracked > n_neutral`` and ``n_tracked >= n_bull`` → ``TRACKED_HEAVY``
      6. otherwise → ``NEUTRAL``
    """
    g = lambda k: int(counts.get(k, 0))
    n_bull = g("n_bull")
    n_mixed = g("n_mixed")
    n_neutral = g("n_neutral")
    n_near = g("n_near_threshold")
    n_broken = g("n_broken")
    n_tracked = g("n_tracked")
    n_na = g("n_na")

    n_active = n_bull + n_mixed + n_neutral + n_near + n_broken + n_tracked
    if n_active == 0:
        return "N_A"

    if n_broken >= 1:
        return "BROKEN" if n_broken >= n_bull else "CAUTION"

    n_neg = n_mixed + n_near
    if n_neg >= 1:
        return "CAUTION" if n_neg >= n_bull else "MIXED"

    if n_bull > 0 and n_bull >= max(n_neutral, n_tracked):
        return "BULL"

    if n_tracked > n_neutral and n_tracked >= n_bull:
        return "TRACKED_HEAVY"

    return "NEUTRAL"


def _compose_notes(counts: Mapping[str, int], read: str) -> str:
    """Build a short human-readable notes string explaining the read."""
    parts = []
    for label, key in (("BULL", "n_bull"), ("MIXED", "n_mixed"),
                       ("BROKEN", "n_broken"), ("NEAR", "n_near_threshold"),
                       ("NEUTRAL", "n_neutral"), ("TRACKED", "n_tracked"),
                       ("N/A", "n_na")):
        v = int(counts.get(key, 0))
        if v:
            parts.append(f"{v} {label}")
    distribution = ", ".join(parts) if parts else "no companies"
    return f"company-derived read {read} from {distribution}"


def _top_tickers(rows: list[CompanyLedgerRow], reads: set[str],
                 cap: int = TOP_TICKERS_CAP) -> str:
    """Return the first ``cap`` tickers (sorted) whose read is in ``reads``."""
    tickers = sorted({r.ticker for r in rows if r.read in reads})
    return ";".join(tickers[:cap])


def aggregate_sector(
    sector: str,
    ledger_rows: list[CompanyLedgerRow],
    *,
    run_id: str,
    timestamp: str,
    date: str,
    source_ledger: str = "",
) -> SectorAggregationRow:
    """Aggregate the ledger rows for ONE sector and a single run into a
    :class:`SectorAggregationRow`.

    The caller is expected to pre-filter ``ledger_rows`` to the right
    ``(run_id, sector)``; this function asserts that the input is consistent
    and tolerates an empty list (emits an ``N_A`` row).
    """
    if sector not in ALLOWED_SECTORS:
        raise CompanyAggregationSchemaError(
            f"sector must be in {sorted(ALLOWED_SECTORS)}, got {sector!r}"
        )

    # Defensive: ensure caller really pre-filtered. Any row with a different
    # sector or run_id is a programming error upstream.
    for r in ledger_rows:
        if r.run_id != run_id:
            raise CompanyAggregationSchemaError(
                f"ledger row run_id={r.run_id!r} does not match "
                f"requested run_id={run_id!r}"
            )
        if r.sector != sector:
            raise CompanyAggregationSchemaError(
                f"ledger row sector={r.sector!r} does not match "
                f"requested sector={sector!r}"
            )
        if r.read not in ALLOWED_READ:
            raise CompanyAggregationSchemaError(
                f"ledger row read={r.read!r} not in {sorted(ALLOWED_READ)}"
            )

    counts: dict[str, int] = {v: 0 for v in _READ_TO_COUNT.values()}
    for r in ledger_rows:
        counts[_READ_TO_COUNT[r.read]] += 1

    read = derive_company_derived_read(counts)
    top_bull = _top_tickers(ledger_rows, {"BULL"})
    top_mixed_or_risk = _top_tickers(
        ledger_rows, {"MIXED", "BROKEN", "NEAR_THRESHOLD"}
    )
    tracked_only = _top_tickers(ledger_rows, {"TRACKED"})

    return SectorAggregationRow(
        run_id=run_id,
        timestamp=timestamp,
        date=date,
        sector=sector,
        n_companies=len(ledger_rows),
        n_bull=counts["n_bull"],
        n_mixed=counts["n_mixed"],
        n_neutral=counts["n_neutral"],
        n_near_threshold=counts["n_near_threshold"],
        n_broken=counts["n_broken"],
        n_tracked=counts["n_tracked"],
        n_na=counts["n_na"],
        company_derived_read=read,
        top_bull_companies=top_bull,
        top_mixed_or_risk_companies=top_mixed_or_risk,
        tracked_only_companies=tracked_only,
        notes=_compose_notes(counts, read),
        source_ledger=source_ledger,
    )


def build_sector_aggregation_rows(
    ledger_rows: list[CompanyLedgerRow],
    *,
    run_id: str,
    source_ledger: str = "",
    sectors: Iterable[str] | None = None,
) -> list[SectorAggregationRow]:
    """Build aggregation rows for one ``run_id``, one row per sector.

    Iterates ``sectors`` (defaults to sorted :data:`ALLOWED_SECTORS`) so the
    output is deterministic and stable even if some sectors are entirely
    missing from the ledger snapshot — those simply produce an ``N_A`` row.

    All ledger rows must share the same ``run_id`` (caller's responsibility);
    this function asserts that invariant. ``timestamp`` / ``date`` are taken
    from the first matching ledger row for the run (deterministic given a
    deterministic ledger).
    """
    if not ledger_rows:
        raise CompanyAggregationSchemaError(
            "ledger_rows is empty — supply at least one row for the run"
        )

    # All rows must share the requested run_id.
    bad = [r.run_id for r in ledger_rows if r.run_id != run_id]
    if bad:
        raise CompanyAggregationSchemaError(
            f"ledger_rows contains run_ids != {run_id!r}: {set(bad)!r}"
        )

    # Use the first row's timestamp + date as the canonical (deterministic).
    timestamp = ledger_rows[0].timestamp
    date = ledger_rows[0].date

    secs = sorted(sectors) if sectors is not None else sorted(ALLOWED_SECTORS)
    out: list[SectorAggregationRow] = []
    for sec in secs:
        sec_rows = [r for r in ledger_rows if r.sector == sec]
        out.append(aggregate_sector(
            sec, sec_rows,
            run_id=run_id, timestamp=timestamp, date=date,
            source_ledger=source_ledger,
        ))
    return out


# --------------------------------------------------------------------------- #
# I/O — append-only, idempotent by (run_id, sector).
# --------------------------------------------------------------------------- #
def load_sector_aggregation(path: str | Path) -> list[SectorAggregationRow]:
    """Read the aggregation CSV. ``[]`` if the file is missing."""
    p = Path(path)
    if not p.is_file():
        return []
    out: list[SectorAggregationRow] = []
    with p.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for r in reader:
            kwargs: dict = {k: r.get(k, "") for k in AGGREGATION_FIELDS}
            for int_field in ("n_companies", "n_bull", "n_mixed", "n_neutral",
                              "n_near_threshold", "n_broken", "n_tracked",
                              "n_na"):
                raw = kwargs.get(int_field, "")
                try:
                    kwargs[int_field] = int(raw) if str(raw) != "" else 0
                except (TypeError, ValueError) as exc:
                    raise CompanyAggregationSchemaError(
                        f"{int_field} must be int, got {raw!r}"
                    ) from exc
            out.append(SectorAggregationRow(**kwargs))
    return out


def load_latest_aggregation_per_sector(
    path: str | Path,
) -> dict[str, SectorAggregationRow]:
    """V6.8.1 — Return ``{sector: latest_row}`` from the aggregation CSV.

    "Latest" means the largest ``run_id`` per sector. Run-ids are
    timestamp-formatted (``YYYY-MM-DDTHH-MM-SSZ``) so a plain string compare
    sorts them chronologically. Returns an empty dict if the file is missing
    or has no data rows — callers should treat that as an empty state, not
    an error.

    Pure read-only helper: no writes, no network, no broker calls. Lives in
    the aggregation module (not the dashboard) so other consumers — future
    notebooks, validation scripts — can reuse it without importing
    ``apps/sector_thesis_dashboard``.
    """
    p = Path(path)
    if not p.is_file():
        return {}
    rows = load_sector_aggregation(p)
    latest: dict[str, SectorAggregationRow] = {}
    for r in rows:
        prev = latest.get(r.sector)
        if prev is None or r.run_id > prev.run_id:
            latest[r.sector] = r
    return latest


def ensure_sector_aggregation_header(path: str | Path) -> Path:
    """Write the header row if the file is missing or empty."""
    p = Path(path)
    if p.is_file() and p.stat().st_size > 0:
        return p
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(AGGREGATION_FIELDS))
        writer.writeheader()
    return p


def _existing_keys(path: Path) -> set[tuple[str, str]]:
    """Set of ``(run_id, sector)`` tuples already in the file."""
    if not path.is_file() or path.stat().st_size == 0:
        return set()
    keys: set[tuple[str, str]] = set()
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for r in reader:
            keys.add((r.get("run_id", ""), r.get("sector", "")))
    return keys


def append_sector_aggregation_rows(
    rows: Iterable[SectorAggregationRow],
    path: str | Path,
    *,
    mode: str = "idempotent",
) -> dict:
    """Append aggregation rows. Append-only; never truncates.

    Modes (mirror the V6.7 company ledger writer):
      * ``"idempotent"`` (default) — skip any input row whose
        ``(run_id, sector)`` already exists on disk.
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
    to_write: list[SectorAggregationRow] = []
    n_skipped = 0

    for r in rows_list:
        key = (r.run_id, r.sector)
        if key in existing:
            if mode == "strict":
                raise CompanyAggregationSchemaError(
                    f"duplicate aggregation key already in file: {key!r}"
                )
            if mode == "idempotent":
                n_skipped += 1
                continue
            # mode == "append" — fall through and write anyway
        to_write.append(r)
        existing.add(key)

    with p.open("a", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(AGGREGATION_FIELDS))
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
    # enums + constants
    "ALLOWED_COMPANY_DERIVED_READ", "AGGREGATION_FIELDS", "TOP_TICKERS_CAP",
    # schema
    "SectorAggregationRow", "CompanyAggregationSchemaError",
    # derivation
    "derive_company_derived_read",
    "aggregate_sector", "build_sector_aggregation_rows",
    # I/O
    "load_sector_aggregation", "load_latest_aggregation_per_sector",
    "ensure_sector_aggregation_header",
    "append_sector_aggregation_rows",
]
