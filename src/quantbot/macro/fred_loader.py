"""FRED series loader (read-only, env-var auth, atomic local cache).

Authentication
--------------
Reads ``FRED_API_KEY`` from the environment **only**. The key is never
printed, logged, written to disk, or returned. If the key is missing the
loader returns ``None`` from ``fetch_series`` with a clear log message and
the caller falls back to yfinance-only proxy mode.

Cache layout
------------
``data/macro/fred/<SERIES_ID>.csv`` -- one row per observation date,
columns ``date, value``. Re-fetching a series overwrites the cache (FRED
revisions can change historical values; the cache is treated as a
materialised view, not a source of truth).

Hard constraints
----------------
- No package install. ``urllib`` from the stdlib is used; we do NOT add
  ``fredapi`` or similar.
- No broker / live / IBKR. This module is research-only.
- Never raise on missing key or network failure -- return ``None`` and let
  the caller degrade gracefully.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

from ..config import project_root


log = logging.getLogger("quantbot.macro.fred")
FRED_BASE_URL = "https://api.stlouisfed.org/fred"

# Curated default set used by the V5.7 demo driver; callers can pick a
# subset. Adding a series is just appending to this list.
DEFAULT_SERIES: dict[str, str] = {
    "FEDFUNDS":  "Effective Federal Funds Rate (monthly, %)",
    "DGS10":     "10-Year Treasury Constant Maturity Rate (daily, %)",
    "DGS2":      "2-Year Treasury Constant Maturity Rate (daily, %)",
    "T10Y2Y":    "10Y-2Y Treasury Spread (daily, %)",
    "CPIAUCSL":  "Consumer Price Index for All Urban Consumers (monthly)",
    "UNRATE":    "Unemployment Rate (monthly, %)",
    "GDPC1":     "Real GDP (quarterly, chained 2017$)",
    "BAA10Y":    "Moody's Baa Corporate Bond Yield - 10Y Treasury spread (daily, %)",
}


# --------------------------------------------------------------------------- #
def macro_cache_dir(root: str | Path | None = None) -> Path:
    base = Path(root) if root else project_root() / "data" / "macro"
    return base / "fred"


def _cache_path(series_id: str, root: str | Path | None = None) -> Path:
    return macro_cache_dir(root) / f"{series_id.upper()}.csv"


def has_api_key() -> bool:
    """True iff FRED_API_KEY is set in the environment (value not exposed)."""
    return bool(os.environ.get("FRED_API_KEY"))


def _atomic_write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".csv", dir=str(path.parent))
    os.close(fd)
    try:
        df.to_csv(tmp, index=False)
        os.replace(tmp, path)
    except Exception:
        if Path(tmp).exists():
            Path(tmp).unlink(missing_ok=True)
        raise


def _read_cache(series_id: str, root: str | Path | None = None) -> pd.DataFrame | None:
    p = _cache_path(series_id, root)
    if not p.is_file():
        return None
    df = pd.read_csv(p, parse_dates=["date"]).set_index("date").sort_index()
    return df


# --------------------------------------------------------------------------- #
def fetch_series(
    series_id: str, *,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
    use_cache: bool = True,
    refresh: bool = False,
    timeout_seconds: float = 20.0,
    root: str | Path | None = None,
) -> pd.DataFrame | None:
    """Fetch a single FRED series.

    Returns a DataFrame indexed by ``date`` with one ``value`` column, or
    ``None`` if the series is unavailable (no key + no cache, or network
    error + no cache). Never raises.
    """
    series_id = series_id.upper()
    cache_df = _read_cache(series_id, root) if use_cache else None
    if cache_df is not None and not refresh:
        return _slice(cache_df, start, end)

    api_key = os.environ.get("FRED_API_KEY")
    if not api_key:
        log.info(
            "FRED_API_KEY not set; skipping live fetch for %s "
            "(caller should fall back to yfinance proxies). "
            "Use 'export FRED_API_KEY=...' (this code never prints it).",
            series_id,
        )
        return cache_df  # may be None; caller handles that

    # Live fetch (HTTPS, JSON output, key passed as a URL param -- standard
    # FRED protocol). The key is NEVER logged; we mask it from any error
    # we re-emit.
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
    }
    url = f"{FRED_BASE_URL}/series/observations?{urlencode(params)}"
    try:
        with urlopen(Request(url), timeout=timeout_seconds) as resp:
            body = resp.read()
    except (HTTPError, URLError, TimeoutError) as exc:
        # Mask the key in any error string we accidentally surface.
        msg = str(exc).replace(api_key, "***")
        log.warning("FRED fetch failed for %s: %s", series_id, msg)
        return cache_df  # may be None
    try:
        payload = json.loads(body)
    except Exception as exc:
        log.warning("FRED JSON parse failed for %s: %s", series_id, exc)
        return cache_df

    obs = payload.get("observations", [])
    if not obs:
        log.warning("FRED returned no observations for %s", series_id)
        return cache_df

    rows = []
    for o in obs:
        try:
            d = pd.Timestamp(o["date"]).normalize()
        except Exception:
            continue
        raw = o.get("value")
        if raw is None or raw in (".", "", "NA"):
            continue
        try:
            v = float(raw)
        except (TypeError, ValueError):
            continue
        rows.append({"date": d, "value": v})
    if not rows:
        log.warning("FRED returned no parseable rows for %s", series_id)
        return cache_df

    df = pd.DataFrame(rows).set_index("date").sort_index()
    df = df[~df.index.duplicated(keep="last")]

    out_path = _cache_path(series_id, root)
    _atomic_write_csv(df.reset_index(), out_path)
    log.info("FRED %s cached -> %s (%d rows)", series_id, out_path, len(df))
    _update_metadata(series_id, df, note="live_fetch", root=root)
    return _slice(df, start, end)


def fetch_panel(
    series_ids: list[str] | None = None, *,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
    use_cache: bool = True,
    refresh: bool = False,
    root: str | Path | None = None,
) -> dict[str, pd.DataFrame]:
    """Fetch multiple series; returns ``{series_id: dataframe or None}``."""
    series_ids = series_ids or list(DEFAULT_SERIES.keys())
    out: dict[str, pd.DataFrame] = {}
    for sid in series_ids:
        df = fetch_series(sid, start=start, end=end,
                           use_cache=use_cache, refresh=refresh, root=root)
        if df is not None:
            out[sid.upper()] = df
    return out


def _slice(df: pd.DataFrame, start, end) -> pd.DataFrame:
    if start is not None:
        df = df[df.index >= pd.Timestamp(start)]
    if end is not None:
        df = df[df.index <= pd.Timestamp(end)]
    return df


# --------------------------------------------------------------------------- #
def _metadata_path(root: str | Path | None = None) -> Path:
    return macro_cache_dir(root) / "metadata.json"


def _update_metadata(series_id: str, df: pd.DataFrame, *,
                      note: str, root: str | Path | None = None) -> None:
    p = _metadata_path(root)
    if p.is_file():
        meta = json.loads(p.read_text(encoding="utf-8"))
    else:
        meta = {"series": {}}
    meta["series"][series_id.upper()] = {
        "n_rows": int(len(df)),
        "first_date": str(df.index.min().date()),
        "last_date": str(df.index.max().date()),
        "last_update_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": note,
    }
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".json", dir=str(p.parent))
    os.close(fd)
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(meta, fh, indent=2)
        os.replace(tmp, p)
    except Exception:
        if Path(tmp).exists():
            Path(tmp).unlink(missing_ok=True)
        raise


def list_cached_series(root: str | Path | None = None) -> list[str]:
    d = macro_cache_dir(root)
    if not d.is_dir():
        return []
    return sorted(p.stem for p in d.glob("*.csv"))
