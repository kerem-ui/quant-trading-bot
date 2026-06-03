"""Spec test 2: indicators are causal (no future data leaks into a value)."""

import numpy as np
import pandas as pd

from quantbot.indicators.pairs import (
    estimate_half_life,
    rolling_hedge_ratio,
    spread_zscore,
)
from quantbot.indicators.trend import compute_trend_score, trailing_return
from quantbot.indicators.volatility import atr, realized_vol


def test_trailing_return_is_causal():
    s = pd.Series(np.arange(1, 101, dtype=float))
    r = trailing_return(s, 10)
    # First 10 are NaN (no trailing window); value at t uses only s[t], s[t-10].
    assert r.iloc[:10].isna().all()
    assert np.isclose(r.iloc[10], s.iloc[10] / s.iloc[0] - 1.0)


def test_trend_score_no_lookahead(small_panel):
    df = small_panel["SPY"]
    full = compute_trend_score(df)
    # Recompute using only data up to a cutoff; the value at the cutoff must
    # be identical (it cannot depend on later rows).
    cut = 400
    partial = compute_trend_score(df.iloc[: cut + 1])
    assert np.isclose(
        full.iloc[cut], partial.iloc[cut], equal_nan=True
    ), "trend_score at t changed when future rows were added -> look-ahead"


def test_realized_vol_and_atr_causal(small_panel):
    df = small_panel["QQQ"]
    rv_full = realized_vol(df["adjusted_close"].pct_change(), 20)
    rv_part = realized_vol(df["adjusted_close"].iloc[:300].pct_change(), 20)
    assert np.isclose(rv_full.iloc[299], rv_part.iloc[299], equal_nan=True)
    a_full = atr(df, 14)
    a_part = atr(df.iloc[:300], 14)
    assert np.isclose(a_full.iloc[299], a_part.iloc[299], equal_nan=True)


def test_rolling_hedge_ratio_trailing(small_panel):
    a = small_panel["SPY"]["adjusted_close"]
    b = small_panel["QQQ"]["adjusted_close"]
    hr_full = rolling_hedge_ratio(a, b, 252)
    hr_part = rolling_hedge_ratio(a.iloc[:500], b.iloc[:500], 252)
    assert np.isclose(hr_full.iloc[499], hr_part.iloc[499], equal_nan=True)


def test_half_life_positive_for_mean_reverting():
    rng = np.random.default_rng(0)
    n = 500
    x = np.zeros(n)
    for t in range(1, n):
        x[t] = 0.8 * x[t - 1] + rng.normal()  # strongly mean-reverting
    hl = estimate_half_life(pd.Series(x))
    assert 0 < hl < 30


def test_zscore_centered():
    s = pd.Series(np.sin(np.linspace(0, 20, 400)) * 3 + 50)
    z = spread_zscore(s, 60).dropna()
    assert abs(z.mean()) < 1.0
