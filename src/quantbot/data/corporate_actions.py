"""Corporate-action handling.

For the ETF universe we rely on the data vendor's ``adjusted_close`` (yfinance
"Adj Close"), which already incorporates splits and dividends. This module
documents that decision and provides a check so we never silently mix adjusted
and unadjusted series.

Per project rules: do not ignore dividends/splits for equities. ETFs here use
total-return-adjusted close. Single-stock fundamental adjustment (point-in-time)
is out of scope for v1 and explicitly flagged where it would matter (S02 notes).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def adjustment_is_applied(df: pd.DataFrame, tol: float = 1e-6) -> bool:
    """Heuristic: True if ``adjusted_close`` differs from ``close`` anywhere
    (i.e. at least one dividend/split was applied)."""
    if "adjusted_close" not in df or "close" not in df:
        return False
    diff = (df["adjusted_close"] - df["close"]).abs()
    return bool((diff > tol).any())


def assert_using_adjusted(df: pd.DataFrame) -> None:
    """Guard used by strategies: refuse to proceed if adjusted_close missing."""
    if "adjusted_close" not in df.columns:
        raise ValueError(
            "adjusted_close missing - strategies must use total-return-adjusted "
            "prices so dividends/splits are not ignored."
        )
    if df["adjusted_close"].le(0).any():
        raise ValueError("adjusted_close has non-positive values; data is invalid.")


def split_adjust_check(df: pd.DataFrame, max_daily_jump: float = 0.40) -> pd.Series:
    """Flag suspicious one-day jumps in *unadjusted* close that may be an
    unhandled split (e.g. a -50% or +100% move with no adjustment)."""
    if "close" not in df:
        return pd.Series(dtype=bool)
    ret = df["close"].pct_change()
    return ret.abs() > max_daily_jump
