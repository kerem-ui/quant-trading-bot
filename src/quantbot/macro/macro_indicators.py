"""Derived macro / market indicators (pure functions, no I/O).

All helpers operate on a price/value DataFrame and return new DataFrames /
Series. No side effects, no broker connection, no live data.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


# --------------------------------------------------------------------------- #
def moving_averages(close: pd.Series, windows: tuple[int, ...] = (20, 50, 200)
                     ) -> pd.DataFrame:
    """Return a DataFrame with one MA column per window: ``ma_20`` etc."""
    out = pd.DataFrame(index=close.index)
    for w in windows:
        out[f"ma_{w}"] = close.rolling(w, min_periods=max(2, w // 4)).mean()
    return out


def returns_over(close: pd.Series, periods: tuple[int, ...] = (5, 21, 63)
                  ) -> pd.DataFrame:
    """Trailing simple returns over each ``period`` (in trading days)."""
    out = pd.DataFrame(index=close.index)
    for p in periods:
        out[f"ret_{p}d"] = close.pct_change(p)
    return out


def realized_vol(returns: pd.Series, window: int = 21,
                  annualization: int = 252) -> pd.Series:
    """Rolling realised vol (std of daily returns x sqrt(annualization))."""
    return returns.rolling(window, min_periods=max(5, window // 4)).std(ddof=1) \
                  * np.sqrt(annualization)


def level_and_change(series: pd.Series, change_periods: tuple[int, ...] = (5, 21)
                      ) -> pd.DataFrame:
    """Return a frame with the raw level + diff over each requested period.

    Useful for VIX / yields where the natural unit is a level, not a return.
    """
    out = pd.DataFrame({"level": series.astype(float)}, index=series.index)
    for p in change_periods:
        out[f"chg_{p}d"] = series.diff(p)
    return out


def credit_proxy_trend(hyg: pd.Series, lqd: pd.Series, *,
                        window: int = 21) -> pd.Series:
    """Rolling change in the HYG/LQD ratio.

    Rising ratio = high-yield outperforming investment-grade = "risk on"
    in credit. Falling ratio = credit stress / risk-off.
    """
    ratio = hyg / lqd
    return ratio.pct_change(window)


def yield_inversion_flag(dgs10: pd.Series, dgs2: pd.Series) -> pd.Series:
    """True wherever the 10Y-2Y spread is inverted (DGS10 < DGS2)."""
    return (dgs10 - dgs2) < 0
