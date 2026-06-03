"""Simple, transparent regime labels (read-only).

Intentionally **not** an ML classifier. Each label is a deterministic
function of a handful of macro / market inputs. Labels are designed to be
easy to defend and audit, not to optimise any backtest.

Labels (each a pandas Series of category strings, indexed by date):
  trend       : "up" | "down" | "flat"      (SPY 21D return vs threshold)
  vol         : "low" | "mid" | "high"      (VIX level bucket)
  rates       : "up" | "down" | "stable"    (DGS10 21d change vs threshold)
  credit      : "risk_on" | "risk_off" | "neutral"  (HYG/LQD 21d change)
  combined    : human-readable concatenation of the above
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .macro_indicators import credit_proxy_trend


@dataclass(frozen=True)
class RegimeThresholds:
    # Trend (SPY 21D return)
    trend_up_pct:   float = 0.02       # +2% over 21d -> up
    trend_down_pct: float = -0.02      # -2% over 21d -> down

    # Vol (VIX level)
    vol_low_max:   float = 16.0
    vol_high_min:  float = 25.0

    # Rates (DGS10 21-day change in percentage points)
    rates_up_bp:   float = 0.20        # +20bp over 21d -> up
    rates_down_bp: float = -0.20       # -20bp over 21d -> down

    # Credit (HYG/LQD 21d change in percent)
    credit_on_pct:  float = 0.01       # +1% in 21d -> risk on
    credit_off_pct: float = -0.01      # -1% in 21d -> risk off


# --------------------------------------------------------------------------- #
def _bucket(value, low_thr: float, high_thr: float,
            low_lbl: str, mid_lbl: str, high_lbl: str) -> str:
    if pd.isna(value):
        return "unknown"
    v = float(value)
    if v < low_thr:
        return low_lbl
    if v > high_thr:
        return high_lbl
    return mid_lbl


def classify_trend(spy_close: pd.Series, *,
                    th: RegimeThresholds | None = None) -> pd.Series:
    th = th or RegimeThresholds()
    ret21 = spy_close.pct_change(21)
    out = pd.Series(index=ret21.index, dtype=object)
    for d, v in ret21.items():
        out.loc[d] = _bucket(
            v, th.trend_down_pct, th.trend_up_pct,
            "down", "flat", "up",
        )
    return out.rename("trend")


def classify_vol(vix_level: pd.Series, *,
                  th: RegimeThresholds | None = None) -> pd.Series:
    th = th or RegimeThresholds()
    out = pd.Series(index=vix_level.index, dtype=object)
    for d, v in vix_level.items():
        out.loc[d] = _bucket(
            v, th.vol_low_max, th.vol_high_min,
            "low", "mid", "high",
        )
    return out.rename("vol")


def classify_rates(dgs10: pd.Series, *,
                    th: RegimeThresholds | None = None) -> pd.Series:
    th = th or RegimeThresholds()
    chg = dgs10.diff(21)
    out = pd.Series(index=chg.index, dtype=object)
    for d, v in chg.items():
        out.loc[d] = _bucket(
            v, th.rates_down_bp, th.rates_up_bp,
            "down", "stable", "up",
        )
    return out.rename("rates")


def classify_credit(hyg: pd.Series | None, lqd: pd.Series | None, *,
                     th: RegimeThresholds | None = None) -> pd.Series | None:
    if hyg is None or lqd is None:
        return None
    th = th or RegimeThresholds()
    ratio_chg = credit_proxy_trend(hyg, lqd, window=21)
    out = pd.Series(index=ratio_chg.index, dtype=object)
    for d, v in ratio_chg.items():
        out.loc[d] = _bucket(
            v, th.credit_off_pct, th.credit_on_pct,
            "risk_off", "neutral", "risk_on",
        )
    return out.rename("credit")


def build_regime_panel(
    *,
    spy_close: pd.Series,
    vix_level: pd.Series | None = None,
    dgs10: pd.Series | None = None,
    hyg: pd.Series | None = None,
    lqd: pd.Series | None = None,
    th: RegimeThresholds | None = None,
) -> pd.DataFrame:
    """Combine available regime labels into one DataFrame.

    Inputs that are ``None`` produce no column in the output (we never
    fabricate data we don't have)."""
    th = th or RegimeThresholds()
    cols: dict[str, pd.Series] = {"trend": classify_trend(spy_close, th=th)}
    if vix_level is not None:
        cols["vol"] = classify_vol(vix_level, th=th)
    if dgs10 is not None:
        cols["rates"] = classify_rates(dgs10, th=th)
    credit = classify_credit(hyg, lqd, th=th)
    if credit is not None:
        cols["credit"] = credit

    df = pd.concat(cols, axis=1).sort_index()

    def _combine(row) -> str:
        parts = [f"{k}={row[k]}" for k in df.columns
                  if not pd.isna(row[k]) and row[k] != "unknown"]
        return "|".join(parts) if parts else "unknown"

    df["combined"] = df.apply(_combine, axis=1)
    return df
