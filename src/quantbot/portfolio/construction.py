"""Portfolio construction primitives.

Turns strategy signals into target weights. Sizing decisions here are
pre-risk-manager: the RiskManager still gets the final say on caps and vol
targeting. All functions are pure and side-effect free.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..risk.risk_manager import reduce_net_exposure


def equal_weight(signals: pd.Series) -> pd.Series:
    """Equal weight across non-zero signals, preserving long/short sign.

    Gross exposure sums to 1.0 (before risk scaling).
    """
    s = signals.fillna(0.0)
    active = s[s != 0]
    if active.empty:
        return pd.Series(0.0, index=signals.index)
    w = np.sign(active) / len(active)
    return w.reindex(signals.index).fillna(0.0)


def inverse_vol_weight(
    signals: pd.Series, vol: pd.Series, target_vol_per_asset: float = 0.10
) -> pd.Series:
    """Volatility-targeted sizing: ``w_i = sign_i * target_vol / vol_i``.

    This is the S01 sizing rule. Names with missing/zero vol are dropped
    (never sized to infinity).
    """
    s = signals.fillna(0.0)
    active = s[s != 0].index
    w = pd.Series(0.0, index=signals.index)
    v = vol.reindex(active)
    valid = v[(v > 1e-6) & v.notna()].index
    w.loc[valid] = np.sign(s.loc[valid]) * (target_vol_per_asset / v.loc[valid])
    return w


def volatility_target(
    weights: pd.Series, asset_vols: pd.Series, portfolio_vol_target: float = 0.10
) -> pd.Series:
    """Scale a weight vector so the (fully-correlated proxy) portfolio vol
    equals the target. Conservative proxy; the RiskManager refines with a
    covariance matrix when available."""
    proxy_vol = float((weights.abs() * asset_vols.reindex(weights.index).fillna(0.0)).sum())
    if proxy_vol <= 1e-9:
        return weights
    return weights * (portfolio_vol_target / proxy_vol)


def apply_constraints(weights: pd.Series, constraints: dict) -> pd.Series:
    """Apply max single weight and gross/net caps (a lightweight pre-clamp).

    The authoritative enforcement is in :class:`RiskManager`; this exists so
    portfolio code can be unit-tested in isolation.
    """
    w = weights.copy()
    for key in ("max_single_symbol_weight", "max_gross_exposure", "max_net_exposure"):
        value = constraints.get(key)
        if value is not None and (not np.isfinite(value) or value < 0):
            raise ValueError(f"{key} must be finite and nonnegative")
    max_single = constraints.get("max_single_symbol_weight")
    if max_single is not None:
        w = w.clip(-max_single, max_single)
    max_gross = constraints.get("max_gross_exposure")
    if max_gross is not None:
        gross = w.abs().sum()
        if gross > max_gross and gross > 0:
            w *= max_gross / gross
    max_net = constraints.get("max_net_exposure")
    return reduce_net_exposure(w, max_net) if max_net is not None else w


def combine_strategy_weights(
    strategy_weights: dict[str, pd.Series], strategy_alloc: dict[str, float] | None = None
) -> pd.Series:
    """Blend multiple strategies' weight vectors by capital allocation.

    ``strategy_alloc`` maps strategy name -> capital fraction (defaults to
    equal). Overlapping symbols are summed.
    """
    if not strategy_weights:
        return pd.Series(dtype=float)
    if strategy_alloc is None:
        strategy_alloc = {k: 1.0 / len(strategy_weights) for k in strategy_weights}
    all_syms: set[str] = set()
    for w in strategy_weights.values():
        all_syms |= set(w.index)
    combined = pd.Series(0.0, index=sorted(all_syms))
    for name, w in strategy_weights.items():
        alloc = strategy_alloc.get(name, 0.0)
        combined = combined.add(w.reindex(combined.index).fillna(0.0) * alloc, fill_value=0.0)
    return combined
