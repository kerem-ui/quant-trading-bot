"""V7.5.1 — Local price-cache reader for the Company Detail page.

Reads existing local CSV caches under ``data/cache/<TICKER>.csv``. **Never
fetches** any live market resource — no equity feed, no options feed,
no broker API, no network call whatsoever. Missing caches yield
``None`` — the Company Detail page surfaces a friendly empty state.

Header tolerance: the reader accepts the canonical V1/V2 cache shape
(``date,open,high,low,close,adjusted_close,volume``) and a few common
external-cache variants (``Date``, ``Close``, ``Adj Close``) so older or
externally-curated caches "just work".

``quantbot.LIVE_TRADING_ENABLED`` stays ``False``. Nothing here imports a
broker, IBKR API, ThetaData feed, or any live-market resource.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

# Repo root (.../quant_trading_bot). Module sits at
# src/quantbot/research/company_detail/price_cache.py — four levels up.
_THIS_FILE = Path(__file__).resolve()
ROOT = _THIS_FILE.parents[4]
DEFAULT_PRICE_CACHE_DIR: Path = ROOT / "data" / "cache"

# Canonical column-name candidates, in priority order. The reader normalises
# headers case-insensitively and picks the first match it finds.
_DATE_HEADER_CANDIDATES: tuple[str, ...] = ("date",)
_CLOSE_HEADER_CANDIDATES: tuple[str, ...] = (
    "close", "adjusted_close", "adj_close", "adj close", "adjclose",
)


@dataclass(frozen=True)
class PriceSeries:
    """Aligned (date, close) time series for one ticker.

    The dataclass is intentionally minimal — the Company Detail page only
    needs ``ticker`` (for display), ``cache_path`` (so the page can show
    "loaded from X"), and the two parallel lists. No OHLCV, no volume —
    those belong to a future technicals expansion.

    ``dates`` and ``closes`` are guaranteed equal-length and chronologically
    ascending (the reader sorts by date on read).
    """

    ticker: str
    cache_path: str
    dates: list[str] = field(default_factory=list)
    closes: list[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        if len(self.dates) != len(self.closes):
            raise ValueError(
                "PriceSeries.dates and .closes must have equal length "
                f"({len(self.dates)} vs {len(self.closes)})"
            )

    @property
    def n_rows(self) -> int:
        return len(self.closes)

    @property
    def latest_date(self) -> str:
        return self.dates[-1] if self.dates else ""

    @property
    def latest_close(self) -> float | None:
        return self.closes[-1] if self.closes else None


def _normalise_header(name: str) -> str:
    return name.strip().lower().replace("﻿", "")


def _pick_header(
    fieldnames: list[str], candidates: tuple[str, ...],
) -> str | None:
    """Return the first original-cased header matching any candidate."""
    norm_map = {_normalise_header(f): f for f in fieldnames}
    for cand in candidates:
        if cand in norm_map:
            return norm_map[cand]
    return None


def _parse_iso_date(value: str) -> str | None:
    """Validate + canonicalise an ISO date string. None if unparseable."""
    if not value:
        return None
    txt = value.strip()
    if not txt:
        return None
    # Many caches store a full ISO datetime; truncate to the date part.
    if "T" in txt:
        txt = txt.split("T", 1)[0]
    if " " in txt:
        txt = txt.split(" ", 1)[0]
    try:
        return date.fromisoformat(txt).isoformat()
    except ValueError:
        return None


def _parse_float(value: str) -> float | None:
    if value is None:
        return None
    txt = str(value).strip()
    if not txt:
        return None
    try:
        return float(txt)
    except ValueError:
        return None


def load_price_series(
    ticker: str,
    *,
    cache_dir: Path | str = DEFAULT_PRICE_CACHE_DIR,
    cache_path: Path | str | None = None,
) -> PriceSeries | None:
    """Read a local price cache for ``ticker``. ``None`` if missing.

    Strictly cache-only. If no file is found, returns ``None`` — the caller
    (the Company Detail page) shows a friendly empty state. Header
    variants the reader accepts:

      * ``date`` / ``Date`` / ``DATE`` for the date column.
      * ``close`` / ``Close`` / ``adjusted_close`` / ``Adj Close`` /
        ``adj_close`` / ``Adjusted Close`` for the close column. The
        reader's preference order is documented in
        :data:`_CLOSE_HEADER_CANDIDATES`.

    Rows whose date or close cannot be parsed are skipped silently. The
    resulting series is sorted ascending by date.
    """
    if cache_path is not None:
        p = Path(cache_path)
    else:
        p = Path(cache_dir) / f"{ticker}.csv"

    if not p.is_file() or p.stat().st_size == 0:
        return None

    rows: list[tuple[str, float]] = []
    with p.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            return None
        date_col = _pick_header(list(reader.fieldnames),
                                 _DATE_HEADER_CANDIDATES)
        close_col = _pick_header(list(reader.fieldnames),
                                  _CLOSE_HEADER_CANDIDATES)
        if date_col is None or close_col is None:
            return None
        for r in reader:
            d = _parse_iso_date(r.get(date_col, ""))
            c = _parse_float(r.get(close_col, ""))
            if d is None or c is None:
                continue
            rows.append((d, c))

    if not rows:
        return None

    rows.sort(key=lambda x: x[0])
    return PriceSeries(
        ticker=ticker,
        cache_path=str(p),
        dates=[r[0] for r in rows],
        closes=[r[1] for r in rows],
    )


__all__ = [
    "DEFAULT_PRICE_CACHE_DIR",
    "PriceSeries",
    "load_price_series",
]
