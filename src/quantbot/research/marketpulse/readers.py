"""V7.8 MarketPulse CSV readers.

Three load helpers + three matching ``ensure_*_header`` helpers. Mirrors
the V6 / V6.7 / V6.8 / V6.6.2 reader pattern: missing file → ``[]``;
header-only file → ``[]``; populated file → list of typed rows.

``ensure_*_header`` is provided for a future V7.8.1 operator-population
script. The MarketPulse platform page never calls these — it only reads.

No network, no broker, no live feed. ``LIVE_TRADING_ENABLED`` stays
``False``.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Type

from .schema import (
    EVENT_CALENDAR_FIELDS,
    EventCalendarRow,
    MarketPulseSchemaError,
    REGIME_DASHBOARD_FIELDS,
    RegimeRow,
    SECTOR_ETF_FIELDS,
    SectorETFRow,
)

# --------------------------------------------------------------------------- #
# Default file locations
# --------------------------------------------------------------------------- #
_THIS_FILE = Path(__file__).resolve()
ROOT = _THIS_FILE.parents[4]
DEFAULT_MARKETPULSE_DIR: Path = ROOT / "data" / "research" / "marketpulse"
DEFAULT_REGIME_DASHBOARD_FILE: Path = (
    DEFAULT_MARKETPULSE_DIR / "regime_dashboard.csv"
)
DEFAULT_SECTOR_ETF_SCOREBOARD_FILE: Path = (
    DEFAULT_MARKETPULSE_DIR / "sector_etf_scoreboard.csv"
)
DEFAULT_EVENT_CALENDAR_FILE: Path = (
    DEFAULT_MARKETPULSE_DIR / "event_calendar.csv"
)


# --------------------------------------------------------------------------- #
# Generic helpers
# --------------------------------------------------------------------------- #
def _ensure_header(path: Path, fields: tuple[str, ...]) -> Path:
    """Write the header row when the file is missing/empty. Never touches
    existing rows."""
    if path.is_file() and path.stat().st_size > 0:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(fields))
        writer.writeheader()
    return path


def _load_typed_rows(
    path: Path,
    fields: tuple[str, ...],
    cls: Type,
) -> list:
    """Read ``path`` and instantiate ``cls`` per row. ``[]`` if file missing.

    The dataclass ``__post_init__`` is responsible for validation; a single
    bad row stops the read with a clear :class:`MarketPulseSchemaError`.
    """
    if not path.is_file():
        return []
    out: list = []
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for r in reader:
            kwargs = {k: (r.get(k, "") or "") for k in fields}
            out.append(cls(**kwargs))
    return out


# --------------------------------------------------------------------------- #
# Regime dashboard
# --------------------------------------------------------------------------- #
def load_regime_dashboard(
    path: str | Path = DEFAULT_REGIME_DASHBOARD_FILE,
) -> list[RegimeRow]:
    return _load_typed_rows(Path(path), REGIME_DASHBOARD_FIELDS, RegimeRow)


def ensure_regime_dashboard_header(
    path: str | Path = DEFAULT_REGIME_DASHBOARD_FILE,
) -> Path:
    return _ensure_header(Path(path), REGIME_DASHBOARD_FIELDS)


# --------------------------------------------------------------------------- #
# Sector ETF scoreboard
# --------------------------------------------------------------------------- #
def load_sector_etf_scoreboard(
    path: str | Path = DEFAULT_SECTOR_ETF_SCOREBOARD_FILE,
) -> list[SectorETFRow]:
    return _load_typed_rows(Path(path), SECTOR_ETF_FIELDS, SectorETFRow)


def ensure_sector_etf_scoreboard_header(
    path: str | Path = DEFAULT_SECTOR_ETF_SCOREBOARD_FILE,
) -> Path:
    return _ensure_header(Path(path), SECTOR_ETF_FIELDS)


# --------------------------------------------------------------------------- #
# Event calendar
# --------------------------------------------------------------------------- #
def load_event_calendar(
    path: str | Path = DEFAULT_EVENT_CALENDAR_FILE,
) -> list[EventCalendarRow]:
    return _load_typed_rows(Path(path), EVENT_CALENDAR_FIELDS,
                              EventCalendarRow)


def ensure_event_calendar_header(
    path: str | Path = DEFAULT_EVENT_CALENDAR_FILE,
) -> Path:
    return _ensure_header(Path(path), EVENT_CALENDAR_FIELDS)


# --------------------------------------------------------------------------- #
# V7.8.1 — Append helpers (used by scripts/populate_marketpulse.py only).
# The MarketPulse PLATFORM never calls these. Append-only with explicit
# idempotent/append/strict modes, mirroring the V6.7 / V6.8 / V6.6.2 pattern.
# Idempotence keys per V7.8.1 spec:
#   * regime: (panel, indicator, last_updated)
#   * ETF:    (ticker, last_updated)
#   * event:  (date, event, country)
# --------------------------------------------------------------------------- #
_VALID_MODES: frozenset[str] = frozenset({"idempotent", "append", "strict"})


def _existing_keys(
    path: Path,
    key_fields: tuple[str, ...],
) -> set[tuple[str, ...]]:
    """Return the set of composite keys already present in ``path``."""
    if not path.is_file() or path.stat().st_size == 0:
        return set()
    keys: set[tuple[str, ...]] = set()
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for r in reader:
            keys.add(tuple(r.get(k, "") or "" for k in key_fields))
    return keys


def _append_typed_rows(
    rows,
    path: Path,
    fields: tuple[str, ...],
    key_fields: tuple[str, ...],
    *,
    mode: str,
) -> dict:
    """Generic append-only writer for the three MarketPulse CSV types.

    Returns ``{"n_input": N, "n_appended": M, "n_skipped": S}``. Never
    truncates or rewrites existing rows.
    """
    if mode not in _VALID_MODES:
        raise ValueError(
            f"mode must be one of {sorted(_VALID_MODES)}, got {mode!r}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = _existing_keys(path, key_fields)
    needs_header = not path.is_file() or path.stat().st_size == 0

    rows_list = list(rows)
    to_write = []
    n_skipped = 0

    for r in rows_list:
        d = r.to_dict()
        key = tuple(str(d.get(k, "") or "") for k in key_fields)
        if key in existing:
            if mode == "strict":
                raise MarketPulseSchemaError(
                    f"duplicate marketpulse key already in file: {key!r}"
                )
            if mode == "idempotent":
                n_skipped += 1
                continue
            # mode == "append" → fall through and write
        to_write.append(r)
        existing.add(key)

    with path.open("a", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(fields))
        if needs_header:
            writer.writeheader()
        for r in to_write:
            writer.writerow(r.to_dict())

    return {
        "n_input": len(rows_list),
        "n_appended": len(to_write),
        "n_skipped": n_skipped,
    }


# Idempotence keys per the V7.8.1 spec.
REGIME_IDEMPOTENCE_KEY: tuple[str, ...] = (
    "panel", "indicator", "last_updated",
)
SECTOR_ETF_IDEMPOTENCE_KEY: tuple[str, ...] = ("ticker", "last_updated")
EVENT_CALENDAR_IDEMPOTENCE_KEY: tuple[str, ...] = (
    "date", "event", "country",
)


def append_regime_rows(
    rows,
    path: str | Path = DEFAULT_REGIME_DASHBOARD_FILE,
    *,
    mode: str = "idempotent",
) -> dict:
    """Append :class:`RegimeRow` objects to the regime dashboard CSV.

    Idempotent by ``(panel, indicator, last_updated)``.
    """
    return _append_typed_rows(
        rows, Path(path),
        REGIME_DASHBOARD_FIELDS, REGIME_IDEMPOTENCE_KEY,
        mode=mode,
    )


def append_sector_etf_rows(
    rows,
    path: str | Path = DEFAULT_SECTOR_ETF_SCOREBOARD_FILE,
    *,
    mode: str = "idempotent",
) -> dict:
    """Append :class:`SectorETFRow` objects to the scoreboard CSV.

    Idempotent by ``(ticker, last_updated)``.
    """
    return _append_typed_rows(
        rows, Path(path),
        SECTOR_ETF_FIELDS, SECTOR_ETF_IDEMPOTENCE_KEY,
        mode=mode,
    )


def append_event_calendar_rows(
    rows,
    path: str | Path = DEFAULT_EVENT_CALENDAR_FILE,
    *,
    mode: str = "idempotent",
) -> dict:
    """Append :class:`EventCalendarRow` objects to the event calendar CSV.

    Idempotent by ``(date, event, country)``.
    """
    return _append_typed_rows(
        rows, Path(path),
        EVENT_CALENDAR_FIELDS, EVENT_CALENDAR_IDEMPOTENCE_KEY,
        mode=mode,
    )


__all__ = [
    "DEFAULT_MARKETPULSE_DIR",
    "DEFAULT_REGIME_DASHBOARD_FILE",
    "DEFAULT_SECTOR_ETF_SCOREBOARD_FILE",
    "DEFAULT_EVENT_CALENDAR_FILE",
    "load_regime_dashboard", "ensure_regime_dashboard_header",
    "load_sector_etf_scoreboard", "ensure_sector_etf_scoreboard_header",
    "load_event_calendar", "ensure_event_calendar_header",
    # V7.8.1 append helpers
    "append_regime_rows", "append_sector_etf_rows",
    "append_event_calendar_rows",
    "REGIME_IDEMPOTENCE_KEY", "SECTOR_ETF_IDEMPOTENCE_KEY",
    "EVENT_CALENDAR_IDEMPOTENCE_KEY",
    # re-export schema-error so consumers can `except` it without a deep import
    "MarketPulseSchemaError",
]
