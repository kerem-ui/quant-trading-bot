"""Simple historical stress windows and scenario PnL.

Stress windows are well-known crisis periods. On synthetic data they will not
line up with real history (the synthetic generator injects one engineered
drawdown instead) - reports label this explicitly.
"""

from __future__ import annotations

import pandas as pd

# (label, start, end) - inclusive
STRESS_WINDOWS = [
    ("GFC 2008", "2008-09-01", "2009-03-31"),
    ("Euro crisis 2011", "2011-07-01", "2011-10-31"),
    ("Vol spike 2015-08", "2015-08-01", "2015-09-30"),
    ("Q4 2018 selloff", "2018-10-01", "2018-12-31"),
    ("COVID crash 2020", "2020-02-15", "2020-04-15"),
    ("2022 bear", "2022-01-01", "2022-10-31"),
]


def stress_period_returns(returns: pd.Series) -> pd.DataFrame:
    """Cumulative strategy return inside each stress window present in the data."""
    rows = []
    for label, start, end in STRESS_WINDOWS:
        seg = returns.loc[
            (returns.index >= pd.Timestamp(start)) & (returns.index <= pd.Timestamp(end))
        ].dropna()
        if seg.empty:
            continue
        cum = float((1.0 + seg).prod() - 1.0)
        rows.append(
            {
                "window": label,
                "start": start,
                "end": end,
                "n_days": int(len(seg)),
                "cumulative_return": cum,
                "worst_day": float(seg.min()),
            }
        )
    return pd.DataFrame(rows)


def scenario_pnl(weights: pd.Series, shocks: dict[str, float]) -> float:
    """First-order portfolio PnL fraction for a dict of per-symbol return shocks."""
    total = 0.0
    for sym, w in weights.items():
        total += w * shocks.get(sym, 0.0)
    return float(total)
