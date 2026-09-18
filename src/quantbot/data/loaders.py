"""Price data loading.

Sources, in order of preference:
  1. Local CSV cache (``data/cache/<symbol>.csv``)
  2. yfinance (free daily OHLCV) if installed and reachable
  3. Synthetic generator (deterministic) so the repo always runs offline

The canonical return type is a *panel*: ``dict[str, DataFrame]`` where each
DataFrame is indexed by a DatetimeIndex named ``date`` with columns
open, high, low, close, adjusted_close, volume.

ETF-only universe and free daily data per project constraints. No live feeds.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ..config import load_data_config, project_root
from ..utils.logging import get_logger
from ..utils.market_calendar import USMarketCalendar
from .validators import validate_panel

log = get_logger("data.loaders")

CANONICAL_COLS = ["open", "high", "low", "close", "adjusted_close", "volume"]


# --------------------------------------------------------------------------- #
# Cache helpers
# --------------------------------------------------------------------------- #
def _cache_path(symbol: str, cache_dir: Path) -> Path:
    return cache_dir / f"{symbol.upper()}.csv"


def _read_cache(symbol: str, cache_dir: Path) -> pd.DataFrame | None:
    p = _cache_path(symbol, cache_dir)
    if not p.is_file():
        return None
    df = pd.read_csv(p, parse_dates=["date"]).set_index("date").sort_index()
    df.index.name = "date"
    return df[CANONICAL_COLS]


def _write_cache(symbol: str, df: pd.DataFrame, cache_dir: Path) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = df.copy()
    out.index.name = "date"
    out.reset_index().to_csv(_cache_path(symbol, cache_dir), index=False)


# --------------------------------------------------------------------------- #
# yfinance
# --------------------------------------------------------------------------- #
def _fetch_yfinance(symbol: str, start: str, end: str | None) -> pd.DataFrame | None:
    try:
        import yfinance as yf
    except ImportError:
        log.warning("yfinance not installed; cannot fetch %s", symbol)
        return None
    try:
        raw = yf.download(
            symbol, start=start, end=end, auto_adjust=False,
            progress=False, threads=False,
        )
    except Exception as exc:  # network / rate limit / symbol error
        log.warning("yfinance download failed for %s: %s", symbol, exc)
        return None
    if raw is None or len(raw) == 0:
        return None
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    raw = raw.rename(
        columns={
            "Open": "open", "High": "high", "Low": "low", "Close": "close",
            "Adj Close": "adjusted_close", "Volume": "volume",
        }
    )
    if "adjusted_close" not in raw.columns:
        raw["adjusted_close"] = raw["close"]
    raw.index = pd.to_datetime(raw.index)
    raw.index.name = "date"
    return raw[CANONICAL_COLS].sort_index()


# --------------------------------------------------------------------------- #
# Synthetic generator (deterministic, offline-safe)
# --------------------------------------------------------------------------- #
def generate_synthetic_panel(
    symbols: list[str],
    start: str = "2010-01-01",
    end: str | None = None,
    *,
    seed: int = 42,
    sector_map: dict[str, str] | None = None,
) -> dict[str, pd.DataFrame]:
    """Generate deterministic OHLCV with trends, a crisis, and cointegrated pairs.

    Design goals so the bundled strategies have signal to find:
      - A market factor with regime-switching drift (trend + a drawdown crisis).
      - Symbols sharing a ``sector`` co-move; multiple symbols in one sector are
        built from a shared price path + small stationary noise, so their spread
        is mean-reverting (cointegrated) - exactly what S03 looks for.

    This is *not* real data. Results on synthetic data are illustrative only.
    """
    rng = np.random.default_rng(seed)
    end = end or pd.Timestamp.today().strftime("%Y-%m-%d")
    dates = USMarketCalendar().sessions(start, end).rename('date')
    n = len(dates)
    if n < 50:
        raise ValueError("synthetic date range too short")

    # Market factor: regime-switching daily drift + a crisis window.
    regime_len = max(60, n // 8)
    drift = np.zeros(n)
    pos = 0
    while pos < n:
        mu = rng.choice([0.0006, 0.0002, -0.0005, 0.0009])
        drift[pos : pos + regime_len] = mu
        pos += regime_len
    crisis_start = int(n * 0.55)
    crisis_end = crisis_start + max(30, n // 20)
    drift[crisis_start:crisis_end] = -0.004  # sharp drawdown for stress testing
    mkt_ret = drift + rng.normal(0, 0.011, n)

    sector_map = sector_map or {}
    # Build one base log-price path per sector for cointegration within sector.
    sectors = sorted({sector_map.get(s, s) for s in symbols})
    sector_base: dict[str, np.ndarray] = {}
    for sec in sectors:
        sec_ret = 0.55 * mkt_ret + rng.normal(0, 0.006, n) + rng.choice([1, -1]) * 0.0001
        sector_base[sec] = np.cumsum(sec_ret)

    panel: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        sec = sector_map.get(sym, sym)
        base = sector_base[sec]
        # Stationary AR(1) tracking noise -> spread vs sector mean-reverts.
        eps = np.zeros(n)
        phi = 0.92
        for t in range(1, n):
            eps[t] = phi * eps[t - 1] + rng.normal(0, 0.004)
        idio_drift = rng.normal(0.00005, 0.00005)
        log_price = (
            np.log(rng.uniform(40, 120))
            + base
            + eps
            + idio_drift * np.arange(n)
        )
        close = np.exp(log_price)
        intraday = np.abs(rng.normal(0, 0.006, n)) * close
        open_ = close * (1 + rng.normal(0, 0.003, n))
        high = np.maximum(open_, close) + intraday
        low = np.minimum(open_, close) - intraday
        low = np.clip(low, 0.01, None)
        volume = rng.integers(5e5, 8e6, n).astype(float)
        df = pd.DataFrame(
            {
                "open": open_, "high": high, "low": low, "close": close,
                "adjusted_close": close, "volume": volume,
            },
            index=dates,
        )
        panel[sym] = df
    return panel


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def load_prices(
    symbols: list[str],
    start: str = "2010-01-01",
    end: str | None = None,
    *,
    source: str = "auto",
    cache_dir: str | Path | None = None,
    allow_synthetic: bool = True,
    sector_map: dict[str, str] | None = None,
    validate: bool = True,
    use_cache: bool = True,
) -> dict[str, pd.DataFrame]:
    """Load OHLCV for ``symbols``.

    ``source``: ``auto`` (cache -> yfinance -> synthetic), ``yfinance``,
    ``synthetic``, or ``cache``. If real fetches fail and ``allow_synthetic``
    is set, the entire panel is regenerated synthetically so partial/real +
    partial/synthetic data is never mixed.
    """
    # Resolve a relative cache_dir against the project root, not the CWD, so
    # scripts run from anywhere (e.g. scripts/) still hit the real cache and do
    # not silently fall back to synthetic data.
    if cache_dir:
        cache_dir = Path(cache_dir)
        if not cache_dir.is_absolute():
            cache_dir = project_root() / cache_dir
    else:
        cache_dir = project_root() / "data" / "cache"
    panel: dict[str, pd.DataFrame] = {}
    need_synthetic = False

    if source == "synthetic":
        need_synthetic = True
    else:
        for sym in symbols:
            df = None
            if use_cache and source in ("auto", "cache"):
                df = _read_cache(sym, cache_dir)
                if df is not None:
                    log.info("loaded %s from cache (%d rows)", sym, len(df))
            if df is None and source in ("auto", "yfinance"):
                df = _fetch_yfinance(sym, start, end)
                if df is not None and use_cache:
                    _write_cache(sym, df, cache_dir)
                    log.info("fetched %s via yfinance (%d rows)", sym, len(df))
            if df is None:
                need_synthetic = True
                break
            panel[sym] = df.loc[
                (df.index >= pd.Timestamp(start))
                & (df.index <= pd.Timestamp(end or pd.Timestamp.today()))
            ]

    if need_synthetic:
        if not allow_synthetic:
            raise RuntimeError(
                "Real data unavailable for one or more symbols and "
                "allow_synthetic=False. Refusing to run on partial data."
            )
        log.warning(
            "Falling back to SYNTHETIC data for the full universe. "
            "Results are illustrative only, not based on market data."
        )
        panel = generate_synthetic_panel(
            symbols, start, end, sector_map=sector_map
        )

    if validate:
        reports = validate_panel(panel)
        for sym, rep in reports.items():
            if not rep.ok:
                log.error("validation issues for %s: %s", sym, rep.errors)
        # Hard-fail only if every symbol is unusable.
        if all(not r.ok for r in reports.values()):
            raise RuntimeError("All symbols failed OHLCV validation; aborting.")
    return panel


def load_universe_from_config(
    universe_key: str, data_config: dict | None = None
) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    """Load a named universe from the data config. Returns (panel, sector_map)."""
    cfg = data_config or load_data_config()
    symbols = cfg["universes"][universe_key]
    sector_map = cfg.get("sector_map", {})
    panel = load_prices(
        symbols,
        start=cfg.get("start_date", "2010-01-01"),
        end=cfg.get("end_date"),
        source=cfg.get("source", "auto"),
        cache_dir=cfg.get("cache_dir"),
        allow_synthetic=cfg.get("allow_synthetic_fallback", True),
        sector_map=sector_map,
    )
    return panel, sector_map


def to_wide(panel: dict[str, pd.DataFrame], field: str = "adjusted_close") -> pd.DataFrame:
    """Stack a panel into a wide DataFrame (index=date, columns=symbol).

    Uses an outer join on dates; missing values stay NaN (handled explicitly
    downstream, never silently zero-filled).
    """
    cols = {sym: df[field] for sym, df in panel.items()}
    wide = pd.DataFrame(cols).sort_index()
    wide.index.name = "date"
    return wide


def returns_from_panel(
    panel: dict[str, pd.DataFrame], field: str = "adjusted_close"
) -> pd.DataFrame:
    """Wide simple-return DataFrame derived from a panel."""
    return to_wide(panel, field).pct_change()
