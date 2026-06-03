"""Trend indicators for S01.

All computations are causal: every value at date ``t`` uses only data up to and
including ``t``. Rolling z-scores use a trailing window so there is no
look-ahead.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..utils.math import rolling_zscore

DEFAULT_LOOKBACKS = (20, 60, 120)
DEFAULT_WEIGHTS = (0.35, 0.35, 0.30)


def trailing_return(prices: pd.Series, lookback: int) -> pd.Series:
    """Simple return over the trailing ``lookback`` sessions (causal)."""
    return prices / prices.shift(lookback) - 1.0


def ema(series: pd.Series, span: int) -> pd.Series:
    """Exponential moving average (causal)."""
    return series.ewm(span=span, adjust=False, min_periods=span).mean()


def compute_trend_score(
    df: pd.DataFrame,
    lookbacks: tuple[int, ...] = DEFAULT_LOOKBACKS,
    weights: tuple[float, ...] = DEFAULT_WEIGHTS,
    zscore_window: int = 252,
    price_col: str = "adjusted_close",
) -> pd.Series:
    """Blended trend score for one symbol.

    ``score = sum_i weight_i * rolling_zscore(return_{lookback_i})``

    The z-score normalises each horizon's trailing return by its own trailing
    distribution, so the blend is comparable across horizons and assets.
    """
    if len(lookbacks) != len(weights):
        raise ValueError("lookbacks and weights must be the same length")
    prices = df[price_col]
    score = pd.Series(0.0, index=prices.index)
    wsum = 0.0
    for lb, w in zip(lookbacks, weights):
        r = trailing_return(prices, lb)
        z = rolling_zscore(r, window=zscore_window, min_periods=max(20, lb))
        score = score.add(w * z, fill_value=np.nan)
        wsum += w
    return score / wsum if wsum else score


def breakout_signal(df: pd.DataFrame, window: int = 100, price_col: str = "adjusted_close") -> pd.Series:
    """+1 on a new ``window``-day high, -1 on a new low, else 0.

    The rolling extremes are shifted by one bar so the current close is
    compared against the *prior* window only (no look-ahead).
    """
    px = df[price_col]
    prior_high = px.rolling(window, min_periods=window).max().shift(1)
    prior_low = px.rolling(window, min_periods=window).min().shift(1)
    sig = pd.Series(0, index=px.index, dtype=int)
    sig[px > prior_high] = 1
    sig[px < prior_low] = -1
    return sig


def ema_trend_filter(
    df: pd.DataFrame, fast: int = 50, slow: int = 200, price_col: str = "adjusted_close"
) -> pd.Series:
    """+1 when fast EMA > slow EMA (uptrend), -1 otherwise. Causal."""
    px = df[price_col]
    f = ema(px, fast)
    s = ema(px, slow)
    out = pd.Series(np.where(f > s, 1, -1), index=px.index)
    out[f.isna() | s.isna()] = 0
    return out.astype(int)


def consecutive_below_ema(
    df: pd.DataFrame, ema_span: int = 50, price_col: str = "adjusted_close"
) -> pd.Series:
    """Count of consecutive sessions the close has been below the EMA.

    Used by the S01 exit rule "close below EMA_50 for 3 consecutive sessions".
    """
    px = df[price_col]
    e = ema(px, ema_span)
    below = (px < e).astype(int)
    # Running count that resets to 0 whenever price is not below the EMA.
    grp = (below == 0).cumsum()
    return below.groupby(grp).cumsum()
