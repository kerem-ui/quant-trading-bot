"""Legacy normalized CSV chain cache + metadata (not true provider raw).

Layout under ``data/options/``::

    raw/<provider>/<underlying>/<YYYY>/<YYYY-MM>/<YYYY-MM-DD>.csv.gz
    processed/<underlying>/<YYYY>/<YYYY-MM>.csv.gz
    sample/...
    metadata.json

The historical directory/API name "raw" is retained for compatibility. Its
contents are already normalized and must not be used as original provider
payload evidence. No bulk rename or migration is performed.

Storage format is CSV.gz (no extra package dependency). Writes are atomic
(temp file + rename) and **never silently overwrite** raw files - callers must
pass ``force=True``. Processed files may be overwritten because they are
deterministic re-aggregations of the raw cache.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd

from ..config import project_root
from .options_chain_loader import OPTIONS_SCHEMA_VERSION


def options_root(root: str | Path | None = None) -> Path:
    """Resolve ``data/options`` against the project root (works from any cwd)."""
    if root:
        p = Path(root)
        if not p.is_absolute():
            p = project_root() / p
        return p
    return project_root() / "data" / "options"


def raw_path(provider: str, underlying: str, date: str | pd.Timestamp,
             root: str | Path | None = None) -> Path:
    d = pd.Timestamp(date).normalize()
    base = options_root(root) / "raw" / provider.lower() / underlying.upper()
    return base / f"{d.year:04d}" / f"{d.year:04d}-{d.month:02d}" / f"{d.strftime('%Y-%m-%d')}.csv.gz"


def processed_path(underlying: str, year: int, month: int,
                   root: str | Path | None = None) -> Path:
    return (options_root(root) / "processed" / underlying.upper()
            / f"{year:04d}" / f"{year:04d}-{month:02d}.csv.gz")


def metadata_path(root: str | Path | None = None) -> Path:
    return options_root(root) / "metadata.json"


# --------------------------------------------------------------------------- #
# atomic write helpers
# --------------------------------------------------------------------------- #
def _atomic_write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".csv.gz", dir=str(path.parent))
    os.close(fd)
    try:
        df.to_csv(tmp, index=False, compression="gzip")
        os.replace(tmp, path)
    except Exception:
        if Path(tmp).exists():
            Path(tmp).unlink(missing_ok=True)
        raise


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


# --------------------------------------------------------------------------- #
# raw / processed I/O
# --------------------------------------------------------------------------- #
def write_raw(df: pd.DataFrame, provider: str, underlying: str,
              date: str | pd.Timestamp, *, force: bool = False,
              root: str | Path | None = None) -> Path:
    """Write a single-date chain to the raw cache. Refuses to overwrite unless
    ``force=True`` is set explicitly."""
    p = raw_path(provider, underlying, date, root=root)
    if p.exists() and not force:
        raise FileExistsError(
            f"Refusing to overwrite existing raw cache file: {p}. "
            "Pass force=True to override."
        )
    _atomic_write_csv(df, p)
    return p


def write_processed(df: pd.DataFrame, underlying: str, year: int, month: int,
                    root: str | Path | None = None) -> Path:
    """Write monthly processed (canonical) chain. May overwrite (re-aggregation)."""
    p = processed_path(underlying, year, month, root=root)
    _atomic_write_csv(df, p)
    return p


_DATE_COLS = ("date", "expiration")


def _read_csv_gz(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, compression="gzip")
    for c in _DATE_COLS:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c])
    return df


def read_raw(provider: str, underlying: str, date: str | pd.Timestamp,
             root: str | Path | None = None) -> pd.DataFrame | None:
    p = raw_path(provider, underlying, date, root=root)
    return _read_csv_gz(p) if p.is_file() else None


def read_processed(underlying: str, year: int, month: int,
                   root: str | Path | None = None) -> pd.DataFrame | None:
    p = processed_path(underlying, year, month, root=root)
    return _read_csv_gz(p) if p.is_file() else None


def list_raw_dates(provider: str, underlying: str,
                   root: str | Path | None = None) -> list[pd.Timestamp]:
    base = options_root(root) / "raw" / provider.lower() / underlying.upper()
    if not base.is_dir():
        return []
    out: list[pd.Timestamp] = []
    for p in base.rglob("*.csv.gz"):
        try:
            match = re.fullmatch(r"(\d{4}-\d{2}-\d{2})(?:\.greeks)?\.csv\.gz", p.name)
            if match:
                out.append(pd.Timestamp(match.group(1)))
        except Exception:
            continue
    return sorted(set(out))


# --------------------------------------------------------------------------- #
# metadata.json (atomic JSON merge)
# --------------------------------------------------------------------------- #
def load_metadata(root: str | Path | None = None) -> dict:
    p = metadata_path(root)
    if not p.is_file():
        return {"schema_version": OPTIONS_SCHEMA_VERSION, "providers": {}}
    with p.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def update_metadata(provider: str, underlying: str, dates: Iterable[pd.Timestamp],
                    n_rows: int, root: str | Path | None = None,
                    note: str | None = None) -> Path:
    """Merge a new fetch event into ``data/options/metadata.json`` atomically."""
    p = metadata_path(root)
    meta = load_metadata(root)
    dates = sorted({pd.Timestamp(d).normalize() for d in dates})
    if not dates:
        return p
    providers = meta.setdefault("providers", {})
    pblock = providers.setdefault(provider.lower(), {"underlyings": {}})
    ublock = pblock["underlyings"].setdefault(
        underlying.upper(),
        {"date_range": None, "n_rows_total": 0, "fetch_events": []},
    )
    cur_lo, cur_hi = ublock.get("date_range") or (None, None)
    # Persisted dates are ISO strings; cast back to Timestamp before min/max
    # so we never compare str and Timestamp (TypeError in Python 3).
    cur_lo = pd.Timestamp(cur_lo).normalize() if cur_lo else None
    cur_hi = pd.Timestamp(cur_hi).normalize() if cur_hi else None
    new_lo = min(d for d in [cur_lo, dates[0]] if d is not None)
    new_hi = max(d for d in [cur_hi, dates[-1]] if d is not None)
    ublock["date_range"] = (str(pd.Timestamp(new_lo).date()),
                            str(pd.Timestamp(new_hi).date()))
    ublock["n_rows_total"] = int(ublock.get("n_rows_total", 0)) + int(n_rows)
    ublock["fetch_events"].append({
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_dates": len(dates),
        "n_rows": int(n_rows),
        "first_date": str(dates[0].date()),
        "last_date": str(dates[-1].date()),
        "note": note,
    })
    meta["schema_version"] = OPTIONS_SCHEMA_VERSION
    p.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp = tempfile.mkstemp(suffix=".json", dir=str(p.parent))
    os.close(fd)
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(meta, fh, indent=2, default=str)
        os.replace(tmp, p)
    except Exception:
        if Path(tmp).exists():
            Path(tmp).unlink(missing_ok=True)
        raise
    return p
