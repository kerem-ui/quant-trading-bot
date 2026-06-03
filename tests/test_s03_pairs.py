"""Spec test 6: S03 pairs entry/exit/stop and max-holding behaviour."""

import numpy as np
import pandas as pd

from quantbot.backtest.engine import BacktestEngine
from quantbot.risk.risk_manager import RiskManager
from quantbot.strategies.s03_pairs_mean_reversion import (
    S03PairsMeanReversion,
    build_pair_orders,
    generate_pair_signals,
)


def test_entry_short_and_long_spread():
    z = pd.Series([0.0, 2.5, 0.0, -2.5, 0.0])
    sig = generate_pair_signals(z, entry_z=2.0, exit_z=0.5, stop_z=3.5,
                                max_holding_days=99)
    assert sig.iloc[1] == -1   # z high -> short spread
    # After exit at |z|<=0.5 it can re-enter long when z very negative.
    assert -1 in sig.values and 1 in sig.values


def test_exit_at_exit_z():
    z = pd.Series([0.0, 2.5, 1.0, 0.4])  # enters short, exits when |z|<=0.5
    sig = generate_pair_signals(z, entry_z=2.0, exit_z=0.5, stop_z=3.5,
                                max_holding_days=99)
    assert sig.tolist() == [0, -1, -1, 0]


def test_stop_at_stop_z():
    z = pd.Series([0.0, 2.5, 3.0, 3.6, 2.0])  # widens to stop -> flat
    sig = generate_pair_signals(z, entry_z=2.0, exit_z=0.5, stop_z=3.5,
                                max_holding_days=99)
    assert sig.iloc[1] == -1
    assert sig.iloc[3] == 0  # stopped out at z>=3.5


def test_max_holding_period():
    z = pd.Series([0.0] + [2.5] * 10)  # stays elevated, never hits exit/stop
    sig = generate_pair_signals(z, entry_z=2.0, exit_z=0.5, stop_z=9.9,
                                max_holding_days=3)
    held = (sig != 0).sum()
    assert held == 3  # forced flat after 3 days


def test_corr_break_forces_exit():
    z = pd.Series([0.0, 2.5, 2.4, 2.3])
    corr = pd.Series([0.9, 0.9, 0.4, 0.4])  # corr collapses below 0.5
    sig = generate_pair_signals(z, entry_z=2.0, exit_z=0.5, stop_z=3.5,
                                max_holding_days=99, corr=corr, min_corr=0.5)
    assert sig.iloc[1] == -1
    assert sig.iloc[2] == 0  # exited because correlation broke


def test_build_pair_orders_dollar_neutral():
    legs = build_pair_orders(1, hedge_ratio=1.3, risk_per_pair=0.01)
    assert legs["a"] == 0.01 and legs["b"] == -0.01
    assert legs["a"] + legs["b"] == 0.0  # dollar-neutral
    flat = build_pair_orders(0, 1.0, 0.01)
    assert flat == {"a": 0.0, "b": 0.0}


def test_s03_dollar_neutral_and_has_short_leg(panel, sector_map):
    s = S03PairsMeanReversion(
        {"max_active_pairs": 10, "risk_per_pair": 0.01}, sector_map=sector_map
    )
    res = BacktestEngine(
        risk_manager=RiskManager({}), borrow_cost_bps_annual=50.0
    ).run(s, panel, sector_map=sector_map)
    net = res.weights.sum(axis=1)
    assert net.abs().mean() < 0.05  # dollar-neutral on average
    assert (res.weights.values < -1e-9).any()  # genuine short legs exist
    assert (res.weights.values > 1e-9).any()


def test_s03_no_lookahead_in_orders(small_panel, sector_map):
    s = S03PairsMeanReversion({}, sector_map=sector_map)
    res = BacktestEngine(risk_manager=RiskManager({})).run(
        s, small_panel, sector_map=sector_map
    )
    for o in res.orders:
        assert o.execution_date > o.signal_date
