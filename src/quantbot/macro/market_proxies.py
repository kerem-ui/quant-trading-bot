"""Market proxy loader (yfinance + existing ETF cache, read-only).

Uses the existing project loader pattern (cache-first, yfinance second,
gracefully degrade on network error). Returns single-symbol DataFrames
indexed by ``date`` with the canonical OHLCV columns.

Proxy roster (configurable per call):
  SPY  - broad equity market / trend
  ^VIX - implied volatility (CBOE)
  TLT  - long-duration Treasuries (rates proxy)
  IEF  - intermediate Treasuries (rates proxy)
  HYG  - high-yield credit ETF
  LQD  - investment-grade credit ETF
  GLD  - gold ETF
  USO  - oil ETF
  UUP  - US dollar bullish ETF (USD proxy; less reliable than DXY)

The loader NEVER touches a broker. Failed downloads cache nothing and
return ``None`` for that symbol; callers must check.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from ..config import project_root
from ..data.loaders import CANONICAL_COLS, _fetch_yfinance, _read_cache, _write_cache


log = logging.getLogger("quantbot.macro.proxies")

# Curated default proxy roster
DEFAULT_PROXIES: dict[str, str] = {
    "SPY":  "Broad equity / trend",
    "^VIX": "Implied volatility",
    "TLT":  "Long-duration Treasuries (rates)",
    "IEF":  "Intermediate Treasuries (rates)",
    "HYG":  "High-yield credit",
    "LQD":  "Investment-grade credit",
    "GLD":  "Gold",
    "USO":  "Oil",
    "UUP":  "US dollar (DXY-like ETF)",
}


def market_cache_dir(root: str | Path | None = None) -> Path:
    """Cache for proxy data not already in ``data/cache/``.

    For symbols like ``^VIX`` that contain characters not friendly to the
    standard cache layout, we keep them here under ``data/macro/proxies/``
    so the existing ETF cache stays unaffected.
    """
    base = Path(root) if root else project_root() / "data" / "macro"
    return base / "proxies"


def _safe_symbol(sym: str) -> str:
    """Filesystem-safe filename for a symbol (handles ^VIX → VIX, etc.)."""
    return sym.replace("^", "").replace("/", "_").upper()


# --------------------------------------------------------------------------- #
def fetch_proxy(
    symbol: str, *,
    start: str | pd.Timestamp = "2010-01-01",
    end: str | pd.Timestamp | None = None,
    use_cache: bool = True,
    refresh: bool = False,
    root: str | Path | None = None,
) -> pd.DataFrame | None:
    """Fetch one proxy. Returns DataFrame or ``None`` on failure.

    Resolution order:
      1. Existing ``data/cache/<SYM>.csv`` (the project's main ETF cache).
      2. ``data/macro/proxies/<SAFE>.csv``.
      3. yfinance live fetch with graceful fallback.

    Never raises; never installs anything; never connects to a broker.
    """
    sym = symbol.upper()
    main_cache = (Path(root) / "data" / "cache" if root
                   else project_root() / "data" / "cache")
    macro_cache = market_cache_dir(root)
    end_str = (pd.Timestamp(end).strftime("%Y-%m-%d") if end is not None
               else pd.Timestamp.today().strftime("%Y-%m-%d"))
    start_str = pd.Timestamp(start).strftime("%Y-%m-%d")

    if use_cache and not refresh:
        # Prefer the main ETF cache for symbols already there.
        main_df = _read_cache(sym, main_cache)
        if main_df is not None:
            return _slice_window(main_df, start_str, end_str)

        # Fall back to the macro-proxy cache (handles ^VIX, etc.).
        macro_safe = _safe_symbol(symbol)
        macro_path = macro_cache / f"{macro_safe}.csv"
        if macro_path.is_file():
            df = pd.read_csv(macro_path, parse_dates=["date"]).set_index("date").sort_index()
            df.index.name = "date"
            return _slice_window(df[CANONICAL_COLS], start_str, end_str)

    df = _fetch_yfinance(symbol, start=start_str, end=end_str)
    if df is None:
        log.warning("proxy fetch unavailable for %s (network/symbol issue); "
                    "no cache either", symbol)
        return None

    macro_safe = _safe_symbol(symbol)
    _write_cache(macro_safe, df, macro_cache)
    return _slice_window(df, start_str, end_str)


def fetch_proxy_panel(
    symbols: list[str] | None = None, *,
    start: str | pd.Timestamp = "2010-01-01",
    end: str | pd.Timestamp | None = None,
    use_cache: bool = True,
    refresh: bool = False,
    root: str | Path | None = None,
) -> dict[str, pd.DataFrame | None]:
    syms = symbols or list(DEFAULT_PROXIES.keys())
    return {
        s: fetch_proxy(s, start=start, end=end,
                        use_cache=use_cache, refresh=refresh, root=root)
        for s in syms
    }


def _slice_window(df: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    out = df[(df.index >= pd.Timestamp(start)) & (df.index <= pd.Timestamp(end))]
    return out
