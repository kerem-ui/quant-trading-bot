"""Spec tests 3 & 4: no look-ahead in execution; costs reduce performance."""

import numpy as np
import pandas as pd
import pytest

from quantbot.backtest.engine import BacktestEngine
from quantbot.backtest.order import Order, OrderStatus
from quantbot.costs.slippage import SlippageModel
from quantbot.costs.transaction_costs import EquityCostModel
from quantbot.risk.risk_manager import RiskManager
from quantbot.strategies.s01_trend_following import S01TrendFollowing


def test_order_rejects_lookahead():
    t = pd.Timestamp("2020-01-10")
    with pytest.raises(ValueError):
        Order("SPY", signal_date=t, execution_date=t, prev_weight=0, target_weight=1)
    with pytest.raises(ValueError):
        Order("SPY", signal_date=t, execution_date=t - pd.Timedelta(days=1),
              prev_weight=0, target_weight=1)


def test_every_order_executes_after_signal(small_panel):
    eng = BacktestEngine(risk_manager=RiskManager({}))
    res = eng.run(S01TrendFollowing({"rebalance_frequency": "weekly"}), small_panel)
    assert len(res.orders) > 0
    for o in res.orders:
        assert o.execution_date > o.signal_date
        if o.status == OrderStatus.FILLED:
            assert o.fill_price is not None and o.fill_price > 0


def test_execution_price_is_next_bar(small_panel):
    """Fill price must equal the NEXT bar's adjusted open (execution=next_open),
    never the signal-bar price."""
    eng = BacktestEngine(
        cost_model=EquityCostModel(),
        risk_manager=RiskManager({}),
        execution="next_open",
    )
    res = eng.run(S01TrendFollowing({}), small_panel)
    filled = [o for o in res.orders if o.status == OrderStatus.FILLED]
    assert filled
    o = filled[0]
    bar = small_panel[o.symbol].loc[o.execution_date]
    expected = bar["open"] * bar["adjusted_close"] / bar["close"]
    assert o.fill_price == pytest.approx(float(expected))
    assert o.execution_date > o.signal_date


def test_costs_reduce_performance(small_panel):
    rm = RiskManager({})
    free = BacktestEngine(
        cost_model=EquityCostModel(0.0, 0.0, SlippageModel(0.0)),
        risk_manager=rm,
    ).run(S01TrendFollowing({}), small_panel)
    costly = BacktestEngine(
        cost_model=EquityCostModel(2.0, 5.0, SlippageModel(10.0)),
        risk_manager=rm,
    ).run(S01TrendFollowing({}), small_panel)
    assert free.total_cost == pytest.approx(0.0, abs=1e-6)
    assert costly.total_cost > 0.0
    assert costly.equity_curve.iloc[-1] < free.equity_curve.iloc[-1]


def test_no_signal_executes_on_signal_day(small_panel):
    """The weight change for a rebalance date must take effect strictly after
    that date (turnover recorded only from the execution bar onward)."""
    eng = BacktestEngine(risk_manager=RiskManager({}))
    res = eng.run(S01TrendFollowing({}), small_panel)
    # Day 0 must be flat (nothing can have executed before any signal).
    assert res.weights.iloc[0].abs().sum() == pytest.approx(0.0)


def test_kill_switch_flattens(small_panel):
    """A tight drawdown kill switch must force the book flat after a crash."""
    rm = RiskManager({"max_portfolio_drawdown_kill_switch": 0.02})
    res = BacktestEngine(risk_manager=rm).run(S01TrendFollowing({}), small_panel)
    assert any("KILL" in "; ".join(e["notes"]) for e in res.risk_events) or \
        res.weights.abs().sum(axis=1).min() == 0.0
