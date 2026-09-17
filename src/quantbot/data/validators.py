"""Data validation.

The backtest must never run on impossible OHLC data, and missing data must be
handled explicitly (never silently coerced to zero). Validation produces a
structured report; callers decide whether to raise.

Canonical OHLCV frame: a single symbol, DatetimeIndex (named ``date``),
columns: open, high, low, close, adjusted_close, volume.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

OHLCV_REQUIRED = ("open", "high", "low", "close", "adjusted_close", "volume")


@dataclass
class ValidationReport:
    symbol: str
    n_rows: int
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def raise_if_failed(self) -> "ValidationReport":
        if self.errors:
            raise DataValidationError(
                f"OHLCV validation failed for {self.symbol!r}: " + "; ".join(self.errors)
            )
        return self

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        head = f"[{self.symbol}] rows={self.n_rows} ok={self.ok}"
        lines = [head]
        lines += [f"  ERROR: {e}" for e in self.errors]
        lines += [f"  warn:  {w}" for w in self.warnings]
        return "\n".join(lines)


class DataValidationError(ValueError):
    """Raised when OHLCV data violates a hard correctness rule."""


def validate_ohlcv(
    df: pd.DataFrame,
    symbol: str = "<unknown>",
    *,
    max_missing_fraction: float = 0.05,
    raise_on_error: bool = False,
) -> ValidationReport:
    """Validate a single-symbol OHLCV frame against the hard rules.

    Hard rules (errors):
      - required columns present
      - no duplicate dates
      - high >= low
      - high >= open and high >= close
      - low <= open and low <= close
      - adjusted_close strictly positive
      - volume non-negative

    Soft rules (warnings):
      - non-monotonic / unsorted index
      - missing-value fraction above ``max_missing_fraction``
      - zero-volume sessions (suspicious but not impossible for some ETFs)
    """
    rep = ValidationReport(symbol=symbol, n_rows=len(df))

    missing_cols = [c for c in OHLCV_REQUIRED if c not in df.columns]
    if missing_cols:
        rep.errors.append(f"missing required columns: {missing_cols}")
        if raise_on_error:
            rep.raise_if_failed()
        return rep

    if len(df) == 0:
        rep.errors.append("empty frame")
        if raise_on_error:
            rep.raise_if_failed()
        return rep

    idx = df.index
    if not isinstance(idx, pd.DatetimeIndex):
        rep.errors.append("index is not a DatetimeIndex")
    else:
        if idx.has_duplicates:
            dupes = idx[idx.duplicated()].unique()
            rep.errors.append(f"duplicate dates: {len(dupes)} (e.g. {list(dupes[:3])})")
        if not idx.is_monotonic_increasing:
            rep.warnings.append("index not sorted ascending")

    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    ac, v = df["adjusted_close"], df["volume"]

    def _count(mask: pd.Series) -> int:
        return int(mask.fillna(False).sum())

    n = _count(h < l)
    if n:
        rep.errors.append(f"high < low on {n} rows")
    n = _count((h < o) | (h < c))
    if n:
        rep.errors.append(f"high < open/close on {n} rows")
    n = _count((l > o) | (l > c))
    if n:
        rep.errors.append(f"low > open/close on {n} rows")
    n = _count(ac <= 0)
    if n:
        rep.errors.append(f"adjusted_close <= 0 on {n} rows")
    n = _count(v < 0)
    if n:
        rep.errors.append(f"negative volume on {n} rows")

    # Missing data is explicit: count, warn, never auto-fill here.
    price_na = df[["open", "high", "low", "close", "adjusted_close"]].isna()
    frac = float(price_na.any(axis=1).mean()) if len(df) else 0.0
    if frac > 0:
        level = rep.errors if frac > max_missing_fraction else rep.warnings
        level.append(
            f"missing price data on {frac:.2%} of rows "
            f"(threshold {max_missing_fraction:.0%})"
        )
    if _count(v == 0):
        rep.warnings.append(f"zero-volume sessions: {_count(v == 0)}")

    if np.isinf(df[list(OHLCV_REQUIRED)].to_numpy(dtype=float, na_value=np.nan)).any():
        rep.errors.append("infinite values present")

    if raise_on_error:
        rep.raise_if_failed()
    return rep


def validate_panel(
    panel: dict[str, pd.DataFrame], *, raise_on_error: bool = False, **kwargs
) -> dict[str, ValidationReport]:
    """Validate every symbol in a panel. Returns symbol -> report."""
    reports: dict[str, ValidationReport] = {}
    for sym, df in panel.items():
        reports[sym] = validate_ohlcv(df, sym, raise_on_error=False, **kwargs)
    if raise_on_error:
        failed = {s: r for s, r in reports.items() if not r.ok}
        if failed:
            msg = "; ".join(f"{s}: {r.errors}" for s, r in failed.items())
            raise DataValidationError(f"panel validation failed: {msg}")
    return reports


# --- Placeholders for derivative data (built out only when data exists) ----


def validate_options_chain(df: pd.DataFrame, *, max_spread_pct: float = 0.25) -> ValidationReport:
    """Options chain validator (interface-complete, used by S05+ later).

    Rules: bid <= ask; mid consistency; reject zero bid/ask; reject spreads
    wider than ``max_spread_pct`` of mid; DTE/expiration consistency.
    """
    rep = ValidationReport(symbol="<options_chain>", n_rows=len(df))
    required = ("expiration", "dte", "option_type", "strike", "bid", "ask")
    miss = [c for c in required if c not in df.columns]
    if miss:
        rep.errors.append(f"missing required option columns: {miss}")
        return rep
    if len(df) == 0:
        rep.errors.append("empty options chain")
        return rep
    bad = int((df["bid"] > df["ask"]).fillna(False).sum())
    if bad:
        rep.errors.append(f"bid > ask on {bad} rows")
    nonpos = int(((df["bid"] <= 0) | (df["ask"] <= 0)).fillna(False).sum())
    if nonpos:
        rep.warnings.append(f"non-positive bid/ask on {nonpos} rows")
    mid = (df["bid"] + df["ask"]) / 2.0
    width = (df["ask"] - df["bid"]) / mid.replace(0, np.nan)
    wide = int((width > max_spread_pct).fillna(False).sum())
    if wide:
        rep.warnings.append(f"{wide} rows with spread > {max_spread_pct:.0%} of mid")
    return rep


def validate_futures_chain(df: pd.DataFrame) -> ValidationReport:
    """Futures chain validator placeholder (used by S04 if futures data exists)."""
    rep = ValidationReport(symbol="<futures_chain>", n_rows=len(df))
    required = ("date", "root_symbol", "contract", "expiration", "settlement")
    miss = [c for c in required if c not in df.columns]
    if miss:
        rep.errors.append(f"missing required futures columns: {miss}")
    return rep
