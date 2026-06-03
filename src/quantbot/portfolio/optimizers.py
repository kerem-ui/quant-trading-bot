"""Optional portfolio optimizers.

v1 keeps construction rule-based (equal / inverse-vol) for robustness and
testability. A minimum-variance helper is provided for research comparison but
is not on the default backtest path. No aggressive optimization in v1.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def min_variance_weights(
    cov: pd.DataFrame, long_only: bool = True, max_weight: float | None = None
) -> pd.Series:
    """Closed-form global minimum-variance weights (w âˆ Σ⁻¹·1).

    Research helper only. If the covariance is singular, falls back to equal
    weight. Optional long-only clipping + renormalisation.
    """
    syms = list(cov.columns)
    if len(syms) == 0:
        return pd.Series(dtype=float)
    Sigma = cov.values
    try:
        inv = np.linalg.pinv(Sigma)
    except np.linalg.LinAlgError:
        return pd.Series(1.0 / len(syms), index=syms)
    ones = np.ones(len(syms))
    raw = inv @ ones
    denom = ones @ raw
    if not np.isfinite(denom) or abs(denom) < 1e-12:
        return pd.Series(1.0 / len(syms), index=syms)
    w = pd.Series(raw / denom, index=syms)
    if long_only:
        w = w.clip(lower=0.0)
    if max_weight is not None:
        w = w.clip(upper=max_weight)
    total = w.sum()
    return w / total if total > 0 else pd.Series(1.0 / len(syms), index=syms)
