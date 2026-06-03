"""Canonical options-chain filter helpers.

Each function returns a *new* DataFrame, never mutates the input. All filters
respect missing values gracefully (NaN rows are excluded by the test, not
treated as passing).
"""

from __future__ import annotations

import pandas as pd


def filter_underlying(df: pd.DataFrame, underlying: str | list[str]) -> pd.DataFrame:
    syms = [underlying] if isinstance(underlying, str) else list(underlying)
    syms = [s.upper() for s in syms]
    return df[df["underlying"].str.upper().isin(syms)].copy()


def filter_option_type(df: pd.DataFrame, option_type: str | None) -> pd.DataFrame:
    if option_type is None:
        return df.copy()
    return df[df["option_type"].str.lower() == option_type.lower()].copy()


def filter_dte(df: pd.DataFrame, dte_min: int | None = None,
               dte_max: int | None = None) -> pd.DataFrame:
    out = df
    if dte_min is not None:
        out = out[out["dte"] >= dte_min]
    if dte_max is not None:
        out = out[out["dte"] <= dte_max]
    return out.copy()


def filter_delta(df: pd.DataFrame, min_abs_delta: float | None = None,
                 max_abs_delta: float | None = None) -> pd.DataFrame:
    out = df.dropna(subset=["delta"])
    abs_d = out["delta"].abs()
    if min_abs_delta is not None:
        out = out[abs_d >= min_abs_delta]
        abs_d = out["delta"].abs()
    if max_abs_delta is not None:
        out = out[abs_d <= max_abs_delta]
    return out.copy()


def filter_moneyness(df: pd.DataFrame, lo: float, hi: float) -> pd.DataFrame:
    """Keep rows where ``strike/underlying_price`` is in [lo, hi]."""
    m = df["strike"] / df["underlying_price"]
    return df[(m >= lo) & (m <= hi)].copy()


def filter_liquidity(df: pd.DataFrame, min_volume: int = 0,
                     min_open_interest: int = 0) -> pd.DataFrame:
    out = df
    if min_volume > 0:
        out = out[out["volume"].fillna(0) >= min_volume]
    if min_open_interest > 0:
        out = out[out["open_interest"].fillna(0) >= min_open_interest]
    return out.copy()


def filter_spread(df: pd.DataFrame, max_spread_pct: float) -> pd.DataFrame:
    """Keep rows where ``(ask-bid)/mid <= max_spread_pct``.

    Rows with non-positive mid are dropped to avoid divide-by-zero ambiguity.
    """
    mid = df["mid"].where(df["mid"] > 0)
    spread_pct = (df["ask"] - df["bid"]) / mid
    return df[spread_pct.abs() <= max_spread_pct].copy()


def filter_expirations(df: pd.DataFrame,
                       expirations: list[str | pd.Timestamp]) -> pd.DataFrame:
    exps = pd.to_datetime(expirations)
    return df[df["expiration"].isin(exps)].copy()


__all__ = [
    "filter_underlying", "filter_option_type", "filter_dte", "filter_delta",
    "filter_moneyness", "filter_liquidity", "filter_spread", "filter_expirations",
]
