"""Value-at-Risk and Expected Shortfall (research estimates).

Both historical and Gaussian-parametric estimates are provided. These are
risk *diagnostics* for the tearsheet, not a guarantee of loss bounds.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats


def historical_var(returns: pd.Series, level: float = 0.95) -> float:
    """Historical VaR as a positive loss fraction at the given confidence."""
    r = returns.dropna()
    if r.empty:
        return np.nan
    return float(-np.quantile(r, 1.0 - level))


def historical_es(returns: pd.Series, level: float = 0.95) -> float:
    """Historical Expected Shortfall (mean loss beyond VaR)."""
    r = returns.dropna()
    if r.empty:
        return np.nan
    var = -historical_var(r, level)
    tail = r[r <= var]
    return float(-tail.mean()) if len(tail) else float(-var)


def parametric_var(returns: pd.Series, level: float = 0.95) -> float:
    """Gaussian VaR (positive loss fraction)."""
    r = returns.dropna()
    if r.empty:
        return np.nan
    z = stats.norm.ppf(1.0 - level)
    return float(-(r.mean() + z * r.std(ddof=1)))


def parametric_es(returns: pd.Series, level: float = 0.95) -> float:
    r = returns.dropna()
    if r.empty:
        return np.nan
    z = stats.norm.ppf(1.0 - level)
    pdf = stats.norm.pdf(z)
    es = -(r.mean() - r.std(ddof=1) * pdf / (1.0 - level))
    return float(es)
