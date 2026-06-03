"""Drawdown analytics."""

from __future__ import annotations

import numpy as np
import pandas as pd


def drawdown_series(equity: pd.Series) -> pd.Series:
    """Drawdown vs running peak (values <= 0)."""
    return equity / equity.cummax() - 1.0


def max_drawdown(equity: pd.Series) -> float:
    dd = drawdown_series(equity)
    return float(dd.min()) if len(dd) else np.nan


def current_drawdown(equity: pd.Series) -> float:
    if len(equity) == 0:
        return 0.0
    return float(equity.iloc[-1] / equity.cummax().iloc[-1] - 1.0)


def drawdown_duration(equity: pd.Series) -> pd.Series:
    """Number of consecutive periods spent underwater (0 when at a new peak)."""
    underwater = drawdown_series(equity) < 0
    grp = (~underwater).cumsum()
    return underwater.groupby(grp).cumsum()


def max_drawdown_duration(equity: pd.Series) -> int:
    dur = drawdown_duration(equity)
    return int(dur.max()) if len(dur) else 0


def ulcer_index(equity: pd.Series) -> float:
    """Ulcer Index: RMS of percentage drawdowns (penalises depth & duration)."""
    dd = drawdown_series(equity) * 100.0
    if len(dd) == 0:
        return np.nan
    return float(np.sqrt((dd**2).mean()))
