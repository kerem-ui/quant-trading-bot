"""Pairs / statistical-arbitrage indicators for S03.

Critical anti-look-ahead rules:
  - Hedge ratio and z-score use trailing rolling windows only.
  - ``find_candidate_pairs`` must be called with price history sliced to the
    selection date (walk-forward). It never sees the future; the caller is
    responsible for passing a window that ends at-or-before the rebalance date.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.tsa.stattools import coint


@dataclass(frozen=True)
class PairStats:
    sym_a: str
    sym_b: str
    correlation: float
    coint_pvalue: float
    hedge_ratio: float
    half_life: float


def rolling_hedge_ratio(
    price_a: pd.Series, price_b: pd.Series, window: int = 252
) -> pd.Series:
    """Rolling OLS beta of A on B: beta_t = Cov(A,B)/Var(B) over trailing window.

    Causal - each beta uses only the trailing ``window`` observations.
    """
    cov = price_a.rolling(window, min_periods=window).cov(price_b)
    var = price_b.rolling(window, min_periods=window).var()
    return cov / var.replace(0.0, np.nan)


def compute_spread(
    price_a: pd.Series, price_b: pd.Series, hedge_ratio: pd.Series | float
) -> pd.Series:
    """spread = A - hedge_ratio * B (hedge_ratio may be a rolling series)."""
    return price_a - hedge_ratio * price_b


def spread_zscore(spread: pd.Series, window: int = 60) -> pd.Series:
    """Rolling z-score of the spread (trailing window, no look-ahead)."""
    mean = spread.rolling(window, min_periods=window).mean()
    std = spread.rolling(window, min_periods=window).std(ddof=0)
    return (spread - mean) / std.replace(0.0, np.nan)


def estimate_half_life(spread: pd.Series) -> float:
    """Ornstein-Uhlenbeck half-life of mean reversion.

    Regress Δspread_t on spread_{t-1}: Δs = a + b·s_{t-1}.
    half_life = -ln(2)/b for b < 0, else +inf (no mean reversion).
    """
    s = spread.dropna()
    if len(s) < 30:
        return np.inf
    lag = s.shift(1).dropna()
    delta = (s - s.shift(1)).dropna()
    lag, delta = lag.align(delta, join="inner")
    if len(lag) < 30:
        return np.inf
    x = sm.add_constant(lag.values)
    beta = sm.OLS(delta.values, x).fit().params[1]
    if beta >= 0:
        return np.inf
    return float(-np.log(2.0) / beta)


def rolling_correlation(
    price_a: pd.Series, price_b: pd.Series, window: int = 252
) -> pd.Series:
    """Trailing correlation of daily returns."""
    ra = price_a.pct_change()
    rb = price_b.pct_change()
    return ra.rolling(window, min_periods=window // 2).corr(rb)


def engle_granger_pvalue(price_a: pd.Series, price_b: pd.Series) -> float:
    """Engle-Granger cointegration p-value (lower = more cointegrated)."""
    a, b = price_a.align(price_b, join="inner")
    a, b = a.dropna(), b.dropna()
    a, b = a.align(b, join="inner")
    if len(a) < 60:
        return 1.0
    try:
        _, pvalue, _ = coint(a.values, b.values)
        return float(pvalue)
    except Exception:
        return 1.0


def find_candidate_pairs(
    prices: pd.DataFrame,
    sector_map: dict[str, str],
    *,
    min_correlation: float = 0.70,
    coint_pvalue_threshold: float = 0.05,
    correlation_window: int = 252,
    half_life_window: int = 252,
    min_half_life: float = 3.0,
    max_half_life: float = 30.0,
) -> list[PairStats]:
    """Walk-forward pair selection on the supplied (already-sliced) prices.

    ``prices`` MUST be history up to the selection date only. Within-sector
    candidates must pass: rolling correlation, Engle-Granger cointegration,
    and an OU half-life inside ``[min_half_life, max_half_life]``.
    """
    symbols = list(prices.columns)
    selected: list[PairStats] = []
    for i in range(len(symbols)):
        for j in range(i + 1, len(symbols)):
            a, b = symbols[i], symbols[j]
            if sector_map.get(a) != sector_map.get(b):
                continue  # same-sector only
            pa, pb = prices[a].dropna(), prices[b].dropna()
            pa, pb = pa.align(pb, join="inner")
            if len(pa) < correlation_window:
                continue
            corr = rolling_correlation(pa, pb, correlation_window).iloc[-1]
            if not np.isfinite(corr) or corr < min_correlation:
                continue
            pval = engle_granger_pvalue(pa.iloc[-correlation_window:], pb.iloc[-correlation_window:])
            if pval > coint_pvalue_threshold:
                continue
            hr = rolling_hedge_ratio(pa, pb, half_life_window).iloc[-1]
            if not np.isfinite(hr):
                continue
            spread = compute_spread(
                pa.iloc[-half_life_window:], pb.iloc[-half_life_window:], hr
            )
            hl = estimate_half_life(spread)
            if not (min_half_life <= hl <= max_half_life):
                continue
            selected.append(
                PairStats(a, b, float(corr), float(pval), float(hr), float(hl))
            )
    # Best (most cointegrated) first.
    selected.sort(key=lambda p: p.coint_pvalue)
    return selected
