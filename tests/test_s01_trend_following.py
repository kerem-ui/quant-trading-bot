"""Spec test 5: S01 signal logic and position caps are enforced."""

import numpy as np
import pandas as pd

from quantbot.backtest.engine import BacktestEngine
from quantbot.risk.risk_manager import RiskManager
from quantbot.strategies.s01_trend_following import (
    S01TrendFollowing,
    generate_trend_signals,
    size_by_volatility,
)


def test_trend_signal_hysteresis():
    # Score rises above entry (1.0) then falls between exit (0.25) and entry.
    score = pd.Series([0.0, 1.2, 0.9, 0.5, 0.3, 0.1, 0.4, 1.5, -1.0])
    sig = generate_trend_signals(score, entry_threshold=1.0, exit_threshold=0.25)
    assert sig.tolist() == [0, 1, 1, 1, 1, 0, 0, 1, 0]
    assert set(sig.unique()) <= {0, 1}  # long-only


def test_size_by_volatility_caps_weight():
    sig = pd.Series([1, 1, 1], index=["A", "B", "C"])
    vol = pd.Series([0.05, 0.40, 0.10], index=["A", "B", "C"])  # A would blow up
    w = size_by_volatility(sig, vol, target_vol=0.10, max_weight=0.15)
    assert (w <= 0.15 + 1e-12).all()
    assert (w >= 0).all()  # long-only
    assert w["A"] == 0.15  # capped (0.10/0.05 = 2.0 -> capped)


def test_s01_is_long_only(small_panel):
    s = S01TrendFollowing({})
    w = s.target_weights(small_panel)
    assert (w.fillna(0.0).values >= -1e-12).all()


def test_s01_respects_position_cap_after_risk(small_panel, sector_map):
    cfg = {"max_weight_per_symbol": 0.15, "rebalance_frequency": "weekly"}
    rm = RiskManager({"max_single_symbol_weight": 0.15})
    res = BacktestEngine(risk_manager=rm).run(
        S01TrendFollowing(cfg), small_panel, sector_map=sector_map
    )
    # Caps constrain allocations. Fixed quantities subsequently drift with prices
    # and cash costs; clipping those marked weights would create unfilled trades.
    filled = [o for o in res.orders if o.status.name == "FILLED"]
    assert filled
    assert all(0 <= o.target_weight <= 0.15 + 1e-9 for o in filled)
    for order in filled:
        allocated_weight = ((order.quantity_before + order.executed_quantity)
                            * order.fill_price / order.allocation_equity)
        np.testing.assert_allclose(allocated_weight, order.target_weight, atol=1e-12)
    assert not (res.marks.isna() & res.quantities.ne(0)).to_numpy().any()
    actual_weights = (res.quantities * res.marks).fillna(0).div(res.equity_curve, axis=0)
    np.testing.assert_allclose(res.weights, actual_weights, atol=1e-12)


def test_s01_signals_causal(small_panel):
    s = S01TrendFollowing({})
    full = s.target_weights(small_panel)
    cut = 600
    partial = S01TrendFollowing({}).target_weights(
        {k: v.iloc[: cut + 1] for k, v in small_panel.items()}
    )
    common = full.columns.intersection(partial.columns)
    np.testing.assert_allclose(
        full[common].iloc[cut].fillna(0).values,
        partial[common].iloc[cut].fillna(0).values,
        atol=1e-9,
        err_msg="S01 weight at t changed when future data added (look-ahead)",
    )
