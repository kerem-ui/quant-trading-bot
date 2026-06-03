"""V5.0 options contract selection.

Pick contracts from a single-day chain slice by:
  - DTE band (closest expiration to band centre),
  - target delta (closest |delta| match for the given option_type),
  - moneyness (alternative to delta).

All selectors are CAUSAL by construction: the caller passes
``chain.on_date(t)`` and we never look at later rows.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


# --------------------------------------------------------------------------- #
# Expiration selection
# --------------------------------------------------------------------------- #
def select_expiration(
    chain_today: pd.DataFrame,
    dte_min: int, dte_max: int,
    *, prefer: str = "band_center",
) -> pd.Timestamp | None:
    """Return the expiration whose DTE is closest to the centre of [min,max].

    If no expiration is in the band, returns the expiration with DTE
    closest to the band centre overall (a documented soft-fallback so a
    V4 dataset capped at e.g. max_dte=30 can still trade a DTE>=30 strategy).
    Returns ``None`` only if the chain itself is empty.
    """
    if chain_today.empty:
        return None
    target = (dte_min + dte_max) / 2.0
    grp = chain_today.groupby("expiration")["dte"].first().sort_index()
    in_band = grp[(grp >= dte_min) & (grp <= dte_max)]
    pool = in_band if not in_band.empty else grp
    chosen_exp = pool.iloc[(pool - target).abs().argsort()].index[0]
    return pd.Timestamp(chosen_exp)


# --------------------------------------------------------------------------- #
# Strike selection
# --------------------------------------------------------------------------- #
def _liquidity_ok(row: pd.Series, spread_max_pct: float) -> bool:
    bid = float(row.get("bid", 0.0) or 0.0)
    ask = float(row.get("ask", 0.0) or 0.0)
    if bid <= 0 or ask <= 0:
        return False
    mid = (bid + ask) / 2.0
    if mid <= 0:
        return False
    return abs(ask - bid) / mid <= spread_max_pct


def select_by_delta(
    chain_today: pd.DataFrame,
    *, expiration: pd.Timestamp,
    option_type: str,
    target_delta: float,
    spread_max_pct: float = 0.25,
    min_strike: float | None = None,
    max_strike: float | None = None,
) -> pd.Series | None:
    """Return the chain row whose ``delta`` is closest to ``target_delta``.

    Convention: callers should pass the SIGNED target (call > 0, put < 0)
    OR an absolute target with ``option_type`` already filtered - we match
    on signed delta here. Filters drop NaN delta and rows that fail the
    liquidity gate. ``min_strike`` / ``max_strike`` are optional hard bounds
    used by spread builders (e.g. short leg must be above the long leg).
    """
    sub = chain_today[
        (chain_today["expiration"] == pd.Timestamp(expiration))
        & (chain_today["option_type"].str.lower() == option_type.lower())
    ].copy()
    sub = sub.dropna(subset=["delta"])
    if min_strike is not None:
        sub = sub[sub["strike"] > min_strike]
    if max_strike is not None:
        sub = sub[sub["strike"] < max_strike]
    if sub.empty:
        return None
    sub = sub[sub.apply(_liquidity_ok, axis=1, args=(spread_max_pct,))]
    if sub.empty:
        return None
    sub = sub.iloc[(sub["delta"] - target_delta).abs().argsort()]
    return sub.iloc[0]


def select_by_moneyness(
    chain_today: pd.DataFrame, *, expiration: pd.Timestamp,
    option_type: str, target_moneyness: float,
    spread_max_pct: float = 0.25,
) -> pd.Series | None:
    """Pick the strike closest to ``spot * target_moneyness``."""
    sub = chain_today[
        (chain_today["expiration"] == pd.Timestamp(expiration))
        & (chain_today["option_type"].str.lower() == option_type.lower())
    ]
    if sub.empty:
        return None
    spot = float(sub["underlying_price"].iloc[0])
    target_strike = spot * target_moneyness
    sub = sub[sub.apply(_liquidity_ok, axis=1, args=(spread_max_pct,))]
    if sub.empty:
        return None
    sub = sub.iloc[(sub["strike"] - target_strike).abs().argsort()]
    return sub.iloc[0]


def lookup_row(
    chain_today: pd.DataFrame, *, expiration: pd.Timestamp,
    option_type: str, strike: float,
) -> pd.Series | None:
    """Find an exact (expiration, option_type, strike) row on a given day.

    Used for daily MTM and for closing/expiration settlement.
    """
    sub = chain_today[
        (chain_today["expiration"] == pd.Timestamp(expiration))
        & (chain_today["option_type"].str.lower() == option_type.lower())
        & (np.isclose(chain_today["strike"].astype(float), float(strike)))
    ]
    if sub.empty:
        return None
    return sub.iloc[0]
