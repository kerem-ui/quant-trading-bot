"""Volatility / risk indicators.

All causal. ``realized_vol`` and ``atr`` use trailing windows only.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..utils.math import TRADING_DAYS_PER_YEAR


def daily_returns(df: pd.DataFrame, price_col: str = "adjusted_close") -> pd.Series:
    return df[price_col].pct_change()


def realized_vol(
    returns: pd.Series, window: int = 20, annualize: bool = True
) -> pd.Series:
    """Trailing realized volatility (sample std of daily returns)."""
    vol = returns.rolling(window, min_periods=max(2, window // 2)).std(ddof=1)
    if annualize:
        vol = vol * np.sqrt(TRADING_DAYS_PER_YEAR)
    return vol


def true_range(df: pd.DataFrame) -> pd.Series:
    """True range = max(H-L, |H-prevC|, |L-prevC|)."""
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr


def atr(df: pd.DataFrame, window: int = 14) -> pd.Series:
    """Average True Range, Wilder smoothing (causal)."""
    tr = true_range(df)
    return tr.ewm(alpha=1.0 / window, adjust=False, min_periods=window).mean()


def rolling_drawdown(series: pd.Series) -> pd.Series:
    """Drawdown of a price/equity series vs its running maximum (<= 0)."""
    running_max = series.cummax()
    return series / running_max - 1.0


def max_drawdown(series: pd.Series) -> float:
    dd = rolling_drawdown(series)
    return float(dd.min()) if len(dd) else np.nan


def vol_spike_ratio(returns: pd.Series, window: int = 60) -> pd.Series:
    """Current short (5d) realized vol divided by the median of trailing
    ``window``-day vol. Used by the S01 vol-spike kill switch."""
    short = returns.rolling(5, min_periods=3).std(ddof=1)
    med = short.rolling(window, min_periods=window // 2).median()
    return short / med.replace(0.0, np.nan)
