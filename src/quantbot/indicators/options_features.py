"""Options / volatility features for S05+ (approximate, research only).

These operate on an underlying return series plus an (approximate) options
chain. With only free daily OHLCV available in v1, IV-based features must come
from a synthetic chain and are therefore explicitly approximate.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..utils.math import TRADING_DAYS_PER_YEAR, ewma_vol


def realized_vol_forecast(returns: pd.Series, lam: float = 0.94) -> pd.Series:
    """EWMA realized-vol forecast (annualized, causal)."""
    return ewma_vol(returns, lam=lam, annualize=True)


def iv_rank(iv_series: pd.Series, window: int = 252) -> pd.Series:
    """IV rank over a trailing window: (iv - min) / (max - min), in [0, 1]."""
    lo = iv_series.rolling(window, min_periods=window // 2).min()
    hi = iv_series.rolling(window, min_periods=window // 2).max()
    return (iv_series - lo) / (hi - lo).replace(0.0, np.nan)


def iv_percentile(iv_series: pd.Series, window: int = 252) -> pd.Series:
    """Fraction of the trailing window below the current IV (causal)."""
    return iv_series.rolling(window, min_periods=window // 2).apply(
        lambda x: (x[:-1] < x[-1]).mean() if len(x) > 1 else np.nan, raw=True
    )


def volatility_risk_premium(atm_iv: float, rv_forecast: float) -> float:
    """VRP in annualized vol points: implied minus forecast realized."""
    return float(atm_iv - rv_forecast)


def atm_iv_from_chain(chain: pd.DataFrame, spot: float, dte_target: int = 30) -> float:
    """Approximate ATM implied vol from a chain snapshot (nearest strike/DTE)."""
    if chain.empty:
        return np.nan
    c = chain.copy()
    c["k_dist"] = (c["strike"] - spot).abs()
    c["dte_dist"] = (c["dte"] - dte_target).abs()
    c = c.sort_values(["dte_dist", "k_dist"])
    return float(c["implied_volatility"].iloc[0])


def skew_slope(chain: pd.DataFrame, spot: float) -> float:
    """OTM-put IV minus ATM IV (a crude 25-delta-ish skew proxy)."""
    if chain.empty:
        return np.nan
    puts = chain[chain["option_type"] == "put"].copy()
    if puts.empty:
        return np.nan
    atm = atm_iv_from_chain(chain, spot)
    otm = puts[puts["strike"] < spot * 0.95]
    if otm.empty:
        return np.nan
    return float(otm["implied_volatility"].mean() - atm)
