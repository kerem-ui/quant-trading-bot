"""Strongest / weakest return windows for a ticker.

Given a daily close series, scan for the most extreme N-day return windows.
A "window" is identified by its END date; the N-day return is
``close[t] / close[t - N] - 1``.

Pure functions, no I/O, no broker, no live data.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class PriceMoveWindow:
    end_date: pd.Timestamp
    start_date: pd.Timestamp
    n_days: int
    return_pct: float
    direction: str   # "up" | "down"
    start_price: float
    end_price: float


def _topk_extremes(series: pd.Series, k: int, *,
                    largest: bool) -> pd.Series:
    s = series.dropna()
    if len(s) == 0:
        return s
    return (s.nlargest(k) if largest else s.nsmallest(k)).sort_values(
        ascending=not largest
    )


def rolling_returns(close: pd.Series, window: int) -> pd.Series:
    """``close[t] / close[t-window] - 1`` series, indexed by end date."""
    if window <= 0:
        raise ValueError("window must be > 0")
    return close.pct_change(window).rename(f"ret_{window}d")


def strongest_moves(
    close: pd.Series, *,
    window: int = 21,
    top_k: int = 10,
    direction: str = "both",
) -> list[PriceMoveWindow]:
    """Top-k strongest moves of a given window length.

    direction:
      - 'up'   -> only positive returns (largest)
      - 'down' -> only negative returns (smallest)
      - 'both' -> top-k by absolute return
    """
    if direction not in ("up", "down", "both"):
        raise ValueError("direction must be 'up', 'down', or 'both'")
    rets = rolling_returns(close, window)

    if direction == "up":
        picks = _topk_extremes(rets, top_k, largest=True)
    elif direction == "down":
        picks = _topk_extremes(rets, top_k, largest=False)
    else:
        # by absolute magnitude
        abs_sorted = rets.dropna().abs().sort_values(ascending=False).head(top_k)
        picks = rets.loc[abs_sorted.index].sort_values(ascending=False)

    out: list[PriceMoveWindow] = []
    for end_dt, ret in picks.items():
        # locate the start_date as the trading bar `window` trading days before
        try:
            idx = close.index.get_loc(end_dt)
        except KeyError:
            continue
        start_idx = idx - window
        if start_idx < 0:
            continue
        start_dt = close.index[start_idx]
        out.append(PriceMoveWindow(
            end_date=pd.Timestamp(end_dt),
            start_date=pd.Timestamp(start_dt),
            n_days=int(window),
            return_pct=float(ret) * 100.0,
            direction=("up" if ret > 0 else "down"),
            start_price=float(close.iloc[start_idx]),
            end_price=float(close.iloc[idx]),
        ))
    return out


def strongest_moves_panel(
    close: pd.Series, *,
    windows: tuple[int, ...] = (5, 21, 63),
    top_k: int = 10,
    direction: str = "both",
) -> pd.DataFrame:
    """Convenience: run :func:`strongest_moves` across multiple window
    lengths and return a single long-format DataFrame."""
    rows: list[dict] = []
    for w in windows:
        for m in strongest_moves(close, window=w, top_k=top_k, direction=direction):
            rows.append({
                "window_days": m.n_days,
                "start_date": str(m.start_date.date()),
                "end_date": str(m.end_date.date()),
                "direction": m.direction,
                "return_pct": m.return_pct,
                "start_price": m.start_price,
                "end_price": m.end_price,
            })
    return pd.DataFrame(rows)
