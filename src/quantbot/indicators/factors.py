"""Price-only cross-sectional factors for S02.

Inputs are *wide* DataFrames (index=date, columns=symbol). Every factor uses
only trailing data, and ranking is done per-date across symbols, so it is
cross-sectional and cannot leak future information.

v1 is price-only because point-in-time fundamentals are not available. This is
documented as a limitation in the README and the S02 module.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..utils.math import cross_sectional_rank


def momentum_12m_ex_1m(prices: pd.DataFrame, long: int = 252, skip: int = 21) -> pd.DataFrame:
    """12-month momentum excluding the most recent month (classic UMD)."""
    return prices.shift(skip) / prices.shift(long) - 1.0


def momentum_3m(prices: pd.DataFrame, window: int = 63) -> pd.DataFrame:
    return prices / prices.shift(window) - 1.0


def one_month_reversal(prices: pd.DataFrame, window: int = 21) -> pd.DataFrame:
    """Short-term reversal factor: the *negative* of the last-month return
    (a strong recent loser is attractive on the reversal thesis)."""
    return -(prices / prices.shift(window) - 1.0)


def low_volatility(prices: pd.DataFrame, window: int = 60) -> pd.DataFrame:
    """Negative trailing realized volatility (low vol -> higher factor value)."""
    rets = prices.pct_change()
    vol = rets.rolling(window, min_periods=window // 2).std(ddof=1)
    return -vol


def liquidity(prices: pd.DataFrame, volume: pd.DataFrame, window: int = 21) -> pd.DataFrame:
    """Trailing average dollar volume (higher = more liquid)."""
    dollar_vol = (prices * volume).rolling(window, min_periods=window // 2).mean()
    return dollar_vol


def composite_score(
    factor_frames: dict[str, pd.DataFrame], weights: dict[str, float]
) -> pd.DataFrame:
    """Combine factors into a single score.

    Each factor is converted to a cross-sectional percentile rank per date
    (higher rank = more attractive), then blended by ``weights``. Ranking
    per-date keeps everything cross-sectional and unit-free.
    """
    missing = set(weights) - set(factor_frames)
    if missing:
        raise KeyError(f"weights reference unknown factors: {missing}")
    score = None
    wsum = 0.0
    for name, w in weights.items():
        ranked = cross_sectional_rank(factor_frames[name], ascending=True)
        score = ranked * w if score is None else score.add(ranked * w, fill_value=np.nan)
        wsum += w
    return score / wsum if wsum else score


def build_price_only_factors(
    prices: pd.DataFrame, volume: pd.DataFrame
) -> dict[str, pd.DataFrame]:
    """Convenience: build the standard S02 price-only factor set."""
    return {
        "momentum_12m_ex_1m": momentum_12m_ex_1m(prices),
        "momentum_3m": momentum_3m(prices),
        "one_month_reversal": one_month_reversal(prices),
        "low_volatility": low_volatility(prices),
        "liquidity": liquidity(prices, volume),
    }
