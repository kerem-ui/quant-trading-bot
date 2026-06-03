"""V7.1 portfolio CSV readers + append helpers.

Mirrors the V7.8 / V7.8.1 / V6.7 / V6.8 / V6.6.2 reader pattern:

  * ``load_positions`` / ``load_transactions`` — return ``[]`` on missing
    or header-only files; otherwise list of typed rows.
  * ``ensure_*_header`` — write the header when the file is missing or
    empty; never touches existing rows.
  * ``append_*_rows`` — append-only with explicit
    ``idempotent | append | strict`` modes keyed on stable composite
    fields.

The MarketPulse / portfolio platform pages only READ — append helpers are
used exclusively by ``scripts/populate_portfolio.py``.

No network, no broker, no live feed. ``LIVE_TRADING_ENABLED`` stays
``False``.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Type

from .schema import (
    POSITION_FIELDS,
    PortfolioSchemaError,
    PositionRow,
    TRANSACTION_FIELDS,
    TransactionRow,
)

# --------------------------------------------------------------------------- #
# Default file locations
# --------------------------------------------------------------------------- #
_THIS_FILE = Path(__file__).resolve()
ROOT = _THIS_FILE.parents[4]
DEFAULT_PORTFOLIO_DIR: Path = ROOT / "data" / "portfolio"
DEFAULT_POSITIONS_FILE: Path = DEFAULT_PORTFOLIO_DIR / "positions.csv"
DEFAULT_TRANSACTIONS_FILE: Path = DEFAULT_PORTFOLIO_DIR / "transactions.csv"


# --------------------------------------------------------------------------- #
# Idempotence keys
# --------------------------------------------------------------------------- #
POSITIONS_IDEMPOTENCE_KEY: tuple[str, ...] = ("as_of", "account", "ticker")
TRANSACTIONS_IDEMPOTENCE_KEY: tuple[str, ...] = (
    "date", "account", "ticker", "side", "quantity",
)


# --------------------------------------------------------------------------- #
# Generic helpers (reused from the V7.8 pattern)
# --------------------------------------------------------------------------- #
_VALID_MODES: frozenset[str] = frozenset({"idempotent", "append", "strict"})


def _ensure_header(path: Path, fields: tuple[str, ...]) -> Path:
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
    if not path.is_file():
        return []
    out: list = []
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for r in reader:
            kwargs = {k: (r.get(k, "") or "") for k in fields}
            out.append(cls(**kwargs))
    return out


def _existing_keys(
    path: Path,
    key_fields: tuple[str, ...],
) -> set[tuple[str, ...]]:
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
                raise PortfolioSchemaError(
                    f"duplicate portfolio key already in file: {key!r}"
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


# --------------------------------------------------------------------------- #
# Positions
# --------------------------------------------------------------------------- #
def load_positions(
    path: str | Path = DEFAULT_POSITIONS_FILE,
) -> list[PositionRow]:
    return _load_typed_rows(Path(path), POSITION_FIELDS, PositionRow)


def ensure_positions_header(
    path: str | Path = DEFAULT_POSITIONS_FILE,
) -> Path:
    return _ensure_header(Path(path), POSITION_FIELDS)


def append_position_rows(
    rows,
    path: str | Path = DEFAULT_POSITIONS_FILE,
    *,
    mode: str = "idempotent",
) -> dict:
    """Append :class:`PositionRow` objects. Idempotent by
    ``(as_of, account, ticker)``."""
    return _append_typed_rows(
        rows, Path(path),
        POSITION_FIELDS, POSITIONS_IDEMPOTENCE_KEY,
        mode=mode,
    )


# --------------------------------------------------------------------------- #
# Transactions
# --------------------------------------------------------------------------- #
def load_transactions(
    path: str | Path = DEFAULT_TRANSACTIONS_FILE,
) -> list[TransactionRow]:
    return _load_typed_rows(Path(path), TRANSACTION_FIELDS, TransactionRow)


def ensure_transactions_header(
    path: str | Path = DEFAULT_TRANSACTIONS_FILE,
) -> Path:
    return _ensure_header(Path(path), TRANSACTION_FIELDS)


def append_transaction_rows(
    rows,
    path: str | Path = DEFAULT_TRANSACTIONS_FILE,
    *,
    mode: str = "idempotent",
) -> dict:
    """Append :class:`TransactionRow` objects. Idempotent by
    ``(date, account, ticker, side, quantity)``."""
    return _append_typed_rows(
        rows, Path(path),
        TRANSACTION_FIELDS, TRANSACTIONS_IDEMPOTENCE_KEY,
        mode=mode,
    )


__all__ = [
    "DEFAULT_PORTFOLIO_DIR",
    "DEFAULT_POSITIONS_FILE", "DEFAULT_TRANSACTIONS_FILE",
    "POSITIONS_IDEMPOTENCE_KEY", "TRANSACTIONS_IDEMPOTENCE_KEY",
    "load_positions", "ensure_positions_header", "append_position_rows",
    "load_transactions", "ensure_transactions_header",
    "append_transaction_rows",
]
