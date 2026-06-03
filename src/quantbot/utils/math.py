"""Numerical helpers shared across indicators / strategies.

Conventions:
- 252 trading days per year for annualization.
- Functions never silently fill NaN with 0; callers decide how to handle gaps.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS_PER_YEAR = 252


def safe_divide(numerator, denominator, fill: float = np.nan):
    """Elementwise divide that returns ``fill`` where the denominator is ~0."""
    num = np.asarray(numerator, dtype=float)
    den = np.asarray(denominator, dtype=float)
    out = np.full(np.broadcast(num, den).shape, fill, dtype=float)
    mask = np.abs(den) > 1e-12
    np.divide(num, den, out=out, where=mask)
    return out


def zscore(series: pd.Series) -> pd.Series:
    """Static (full-sample) z-score. Use only on already-windowed inputs."""
    std = series.std(ddof=0)
    if std == 0 or np.isnan(std):
        return pd.Series(np.nan, index=series.index)
    return (series - series.mean()) / std


def rolling_zscore(series: pd.Series, window: int, min_periods: int | None = None) -> pd.Series:
    """Rolling z-score using only trailing data (no look-ahead)."""
    min_periods = min_periods or window
    roll = series.rolling(window=window, min_periods=min_periods)
    mean = roll.mean()
    std = roll.std(ddof=0)
    z = (series - mean) / std.replace(0.0, np.nan)
    return z


def cross_sectional_rank(df: pd.DataFrame, ascending: bool = True) -> pd.DataFrame:
    """Rank each row (a date) across columns (symbols) into [0, 1].

    Cross-sectional by construction: a row only ever sees same-date values, so
    this cannot leak future information.
    """
    return df.rank(axis=1, ascending=ascending, pct=True)


def winsorize(series: pd.Series, lower: float = 0.01, upper: float = 0.99) -> pd.Series:
    """Clip a series to the given quantiles to reduce outlier influence."""
    if series.dropna().empty:
        return series
    lo = series.quantile(lower)
    hi = series.quantile(upper)
    return series.clip(lower=lo, upper=hi)


def annualize_return(daily_returns: pd.Series, periods_per_year: int = TRADING_DAYS_PER_YEAR) -> float:
    """Geometric CAGR from a daily return series."""
    r = daily_returns.dropna()
    if r.empty:
        return np.nan
    growth = float((1.0 + r).prod())
    years = len(r) / periods_per_year
    if years <= 0 or growth <= 0:
        return np.nan
    return growth ** (1.0 / years) - 1.0


def annualize_vol(daily_returns: pd.Series, periods_per_year: int = TRADING_DAYS_PER_YEAR) -> float:
    r = daily_returns.dropna()
    if r.empty:
        return np.nan
    return float(r.std(ddof=1) * np.sqrt(periods_per_year))


def ewma_vol(returns: pd.Series, lam: float = 0.94, annualize: bool = True) -> pd.Series:
    """RiskMetrics-style EWMA volatility (causal)."""
    var = returns.pow(2).ewm(alpha=1 - lam, adjust=False).mean()
    vol = np.sqrt(var)
    if annualize:
        vol = vol * np.sqrt(TRADING_DAYS_PER_YEAR)
    return vol
