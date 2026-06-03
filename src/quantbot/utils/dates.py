"""Trading-calendar / rebalance-date helpers.

These helpers derive rebalance dates from an existing price index. We never
fabricate dates that aren't in the data, which keeps the backtest aligned to
actual trading days and avoids accidental look-ahead from synthetic calendars.
"""

from __future__ import annotations

import pandas as pd

VALID_FREQUENCIES = ("daily", "weekly", "monthly", "quarterly")


def rebalance_dates(index: pd.DatetimeIndex, frequency: str) -> pd.DatetimeIndex:
    """Return the subset of ``index`` on which rebalancing occurs.

    weekly    -> last available trading day of each ISO week
    monthly   -> last available trading day of each calendar month
    quarterly -> last available trading day of each calendar quarter
    daily     -> every day

    The *last available* day is used (not a fixed weekday) so the schedule is
    robust to holidays and missing data.
    """
    if frequency not in VALID_FREQUENCIES:
        raise ValueError(f"frequency must be one of {VALID_FREQUENCIES}, got {frequency!r}")
    if not isinstance(index, pd.DatetimeIndex):
        index = pd.DatetimeIndex(index)
    index = index.sort_values()
    if len(index) == 0:
        return index

    if frequency == "daily":
        return index

    s = pd.Series(index, index=index)
    if frequency == "weekly":
        keys = index.isocalendar()
        grp = pd.Series(list(zip(keys["year"], keys["week"])), index=index)
    elif frequency == "quarterly":
        grp = pd.Series(index.to_period("Q"), index=index)
    else:  # monthly
        grp = pd.Series(index.to_period("M"), index=index)

    last_per_group = s.groupby(grp.values).max()
    return pd.DatetimeIndex(sorted(last_per_group.values))


def is_rebalance_day(date: pd.Timestamp, index: pd.DatetimeIndex, frequency: str) -> bool:
    """True if ``date`` is a rebalance day for the given schedule."""
    return pd.Timestamp(date) in set(rebalance_dates(index, frequency))


def month_starts(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """First available trading day of each calendar month (used for monthly pair reselection)."""
    if len(index) == 0:
        return index
    s = pd.Series(index, index=index)
    grp = pd.Series(index.to_period("M"), index=index)
    first_per_group = s.groupby(grp.values).min()
    return pd.DatetimeIndex(sorted(first_per_group.values))


def trading_days_between(index: pd.DatetimeIndex, start: pd.Timestamp, end: pd.Timestamp) -> int:
    """Number of trading days in ``index`` strictly after ``start`` up to ``end``."""
    mask = (index > pd.Timestamp(start)) & (index <= pd.Timestamp(end))
    return int(mask.sum())
