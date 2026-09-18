"""Phase 1A accounting regressions for the approved adjusted-unit ledger.

These tests exercise the existing public engine with in-memory prices only.
The original economic assertions are retained. No xfail, network or report writes.
Sixty flat warm-up bars satisfy the existing engine's minimum history length.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantbot.backtest.engine import BacktestEngine, BacktestResult
from quantbot.backtest.order import OrderStatus
from quantbot.costs.slippage import SlippageModel
from quantbot.costs.transaction_costs import EquityCostModel
from quantbot.risk.risk_manager import RiskManager
from quantbot.utils.market_calendar import USMarketCalendar


INITIAL_CAPITAL = 1_000.0
SIGNAL_BAR = 60
FILL_BAR = 61


class _ScheduledWeights:
    """Test input: submit specified targets, with no decisions on other dates."""

    rebalance_frequency = "daily"

    def __init__(self, decisions: dict[int, float]):
        self.decisions = decisions

    def target_weights(self, panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
        """Return predetermined targets without inspecting future prices."""
        index = panel["ETF"].index
        weights = pd.DataFrame(np.nan, index=index, columns=["ETF"])
        for bar, weight in self.decisions.items():
            weights.loc[index[bar], "ETF"] = weight
        return weights


class _RecordingRiskManager(RiskManager):
    """Record information delivered to the real risk pipeline by the engine."""

    def __init__(self):
        super().__init__({
            "portfolio_vol_target_annual": 0.0,
            "max_single_symbol_weight": 1.0,
            "max_asset_class_weight": 1.0,
            "max_gross_exposure": 1.0,
            "max_net_exposure": 1.0,
            "max_strategy_drawdown_pause": 1.0,
            "max_portfolio_drawdown_kill_switch": 1.0,
            "max_daily_loss_reduce_risk": 1.0,
        })
        self.observed_returns: dict[pd.Timestamp, float] = {}

    def process(self, target_weights: pd.Series, **kwargs):
        """Capture the return supplied for a decision at today's close."""
        today = kwargs["portfolio_equity"].index[-1]
        self.observed_returns[today] = kwargs["prev_day_return"]
        return super().process(target_weights, **kwargs)


def _panel() -> dict[str, pd.DataFrame]:
    # Same 65 prices/events and assertions, now on actual exchange sessions.
    dates = USMarketCalendar().sessions("2024-01-02", "2024-05-01")[:65]
    prices = pd.DataFrame(
        {"open": 100.0, "high": 100.0, "low": 100.0,
         "close": 100.0, "adjusted_close": 100.0, "volume": 1_000_000},
        index=dates,
    )
    return {"ETF": prices}


def _set_bar(prices: pd.DataFrame, bar: int, *, open_: float, close: float) -> None:
    prices.loc[prices.index[bar], ["open", "high", "low", "close", "adjusted_close"]] = (
        open_, max(open_, close), min(open_, close), close, close,
    )


def _run(
    panel: dict[str, pd.DataFrame], *, decisions: dict[int, float] | None = None,
    weight: float = 0.5, commission_bps: float = 0.0, borrow_bps: float = 0.0,
    execution: str = "next_open", risk: RiskManager | None = None,
) -> BacktestResult:
    model = EquityCostModel(
        commission_bps=commission_bps, half_spread_bps=0.0,
        slippage=SlippageModel(fixed_bps=0.0),
    )
    engine = BacktestEngine(
        initial_capital=INITIAL_CAPITAL, execution=execution, cost_model=model,
        risk_manager=risk if risk is not None else _RecordingRiskManager(),
        borrow_cost_bps_annual=borrow_bps,
    )
    return engine.run(_ScheduledWeights(
        decisions if decisions is not None else {SIGNAL_BAR: weight},
    ), panel)


@pytest.mark.parametrize("bad_open", [0.0, np.nan], ids=["zero", "missing"])
def test_rejected_entry_cannot_create_exposure_or_pnl(bad_open):
    """An unfilled buy must leave the account flat, cost-free and worth $1,000."""
    panel = _panel()
    prices = panel["ETF"]
    prices.loc[prices.index[FILL_BAR], "open"] = bad_open
    for bar in range(FILL_BAR + 1, len(prices)):
        _set_bar(prices, bar, open_=110.0, close=110.0)
    result = _run(panel)

    assert len(result.orders) == 1
    assert result.orders[0].status == OrderStatus.REJECTED
    assert result.total_cost == pytest.approx(0.0)
    assert result.weights.loc[prices.index[FILL_BAR]:, "ETF"].eq(0.0).all(), (
        "Rejected order created portfolio exposure without an executed fill"
    )
    np.testing.assert_allclose(result.equity_curve, INITIAL_CAPITAL, atol=1e-10)


@pytest.mark.parametrize(
    ("execution", "expected_equity"),
    [("next_open", 1_050.0), ("next_close", 1_000.0)],
)
def test_entry_bar_pnl_respects_execution_time(execution, expected_equity):
    """A $500 buy at open 100 earns $50 by close 110; a close buy earns $0."""
    panel = _panel()
    for bar in range(FILL_BAR, len(panel["ETF"])):
        _set_bar(panel["ETF"], bar, open_=100.0 if bar == FILL_BAR else 110.0,
                 close=110.0)
    result = _run(panel, execution=execution)

    assert len(result.orders) == 1
    assert result.orders[0].status == OrderStatus.FILLED
    assert result.orders[0].fill_price == pytest.approx(
        100.0 if execution == "next_open" else 110.0,
    )
    assert result.equity_curve.iloc[FILL_BAR] == pytest.approx(expected_equity)
    assert result.equity_curve.iloc[-1] == pytest.approx(expected_equity)


def test_changing_executed_price_changes_economic_pnl():
    """The same signal is worth $50 more when filled at 100 instead of 110."""
    cheap_panel, expensive_panel = _panel(), _panel()
    for panel, entry_open in [(cheap_panel, 100.0), (expensive_panel, 110.0)]:
        for bar in range(FILL_BAR, len(panel["ETF"])):
            _set_bar(panel["ETF"], bar,
                     open_=entry_open if bar == FILL_BAR else 110.0, close=110.0)
    cheap, expensive = _run(cheap_panel), _run(expensive_panel)

    assert cheap.orders[0].fill_price == 100.0
    assert expensive.orders[0].fill_price == 110.0
    assert cheap.equity_curve.iloc[-1] - expensive.equity_curve.iloc[-1] == (
        pytest.approx(50.0)
    ), "Different recorded fill prices have identical portfolio economics"


@pytest.mark.parametrize(
    ("commission_bps", "borrow_bps"),
    [(10.0, 0.0), (0.0, 252.0), (10.0, 252.0)],
    ids=["trading", "borrowing", "trading-and-borrowing"],
)
def test_net_returns_compound_to_equity_including_all_costs(commission_bps, borrow_bps):
    """Every reported daily net return must reproduce the cash-loss equity path."""
    result = _run(_panel(), weight=-0.5, commission_bps=commission_bps,
                  borrow_bps=borrow_bps)
    assert result.total_cost > 0.0
    assert result.total_cost == pytest.approx(result.trading_cost + result.borrow_cost)
    implied_equity = INITIAL_CAPITAL * (1.0 + result.returns).cumprod()
    np.testing.assert_allclose(
        implied_equity, result.equity_curve, rtol=1e-12, atol=1e-10,
        err_msg="Reported returns omit costs already charged to portfolio equity",
    )


def test_no_trade_round_trip_price_move_preserves_share_holdings():
    """$500 cash plus five shares must return to $1,000 after 100 -> 110 -> 100."""
    panel = _panel()
    _set_bar(panel["ETF"], FILL_BAR + 1, open_=100.0, close=110.0)
    _set_bar(panel["ETF"], FILL_BAR + 2, open_=110.0, close=100.0)
    result = _run(panel)

    assert len(result.orders) == 1
    assert result.orders[0].status == OrderStatus.FILLED
    assert result.total_cost == 0.0
    assert result.equity_curve.iloc[FILL_BAR + 1] == pytest.approx(1_050.0)
    assert result.equity_curve.iloc[-1] == pytest.approx(1_000.0), (
        "Portfolio earned money from implicit unexecuted weight rebalancing"
    )


def test_held_weight_drifts_without_another_fill():
    """Five shares at 110 are 550 / 1,050 of equity, not the entry weight 0.5."""
    panel = _panel()
    for bar in range(FILL_BAR + 1, len(panel["ETF"])):
        _set_bar(panel["ETF"], bar, open_=110.0, close=110.0)
    result = _run(panel)

    assert len(result.orders) == 1
    assert result.equity_curve.iloc[FILL_BAR + 1] == pytest.approx(1_050.0)
    assert result.weights.iloc[FILL_BAR + 1]["ETF"] == pytest.approx(550.0 / 1_050.0)


def test_risk_at_close_receives_same_days_net_return_after_fees():
    """A $0.50 entry fee is a -0.05% loss known at that day's close."""
    panel, risk = _panel(), _RecordingRiskManager()
    result = _run(panel, decisions={SIGNAL_BAR: 0.5, FILL_BAR: 0.5},
                  commission_bps=10.0, risk=risk)
    day = panel["ETF"].index[FILL_BAR]
    assert result.equity_curve.loc[day] == pytest.approx(999.5)
    assert risk.observed_returns[day] == pytest.approx(-0.5 / INITIAL_CAPITAL)


def test_risk_at_close_receives_current_market_loss_not_yesterdays_return():
    """A 10% fall on a half-invested book is today's -5%, not yesterday's 0%."""
    panel, risk = _panel(), _RecordingRiskManager()
    for bar in range(FILL_BAR + 1, len(panel["ETF"])):
        _set_bar(panel["ETF"], bar, open_=90.0, close=90.0)
    result = _run(panel, decisions={SIGNAL_BAR: 0.5, FILL_BAR + 1: 0.5}, risk=risk)
    day = panel["ETF"].index[FILL_BAR + 1]
    assert result.equity_curve.loc[day] == pytest.approx(950.0)
    assert risk.observed_returns[day] == pytest.approx(-0.05)


def test_missing_mark_for_a_held_security_is_an_explicit_error():
    """No missing-data valuation policy is requested: a missing mark must fail."""
    panel = _panel()
    prices = panel["ETF"]
    prices.loc[prices.index[FILL_BAR + 1], ["close", "adjusted_close"]] = np.nan
    with pytest.raises(ValueError, match="ETF"):
        _run(panel)


def test_flat_market_cost_deductions_are_counted_once_in_ending_equity():
    """Control: recorded trading and borrow deductions already sum once in equity."""
    result = _run(_panel(), weight=-0.5, commission_bps=10.0, borrow_bps=252.0)
    assert result.trading_cost == pytest.approx(0.5)
    assert result.borrow_cost > 0.0
    assert result.total_cost == pytest.approx(result.trading_cost + result.borrow_cost)
    assert result.equity_curve.iloc[-1] == pytest.approx(
        INITIAL_CAPITAL - result.total_cost, abs=1e-10,
    )


@pytest.mark.parametrize("execution", ["next_open", "next_close"])
@pytest.mark.parametrize("weight", [0.5, -0.5])
def test_every_event_replays_cash_quantities_costs_and_equity(execution, weight):
    """Independently replay fills and cash deductions, including reversal/exit."""
    panel = _panel()
    for bar, (op, cl) in enumerate([(100, 110), (120, 105), (90, 95), (100, 98)], 61):
        _set_bar(panel["ETF"], bar, open_=op, close=cl)
    result = _run(panel, decisions={60: weight, 61: weight / 2, 62: -weight, 63: 0},
                  commission_bps=10, borrow_bps=252, execution=execution)
    cash, quantities, costs = INITIAL_CAPITAL, {}, 0.0
    filled = iter(o for o in result.orders if o.status == OrderStatus.FILLED)
    for event in result.ledger:
        if event["event"] == "fill":
            order = next(filled)
            assert order.symbol == event["symbol"]
            assert order.executed_quantity == pytest.approx(event["quantity"])
            assert order.notional == pytest.approx(abs(order.executed_quantity * order.fill_price))
            cash -= order.executed_quantity * order.fill_price + order.cost
            quantities[order.symbol] = quantities.get(order.symbol, 0) + order.executed_quantity
            costs += order.cost
        elif event["event"] == "borrow":
            cash -= event["cost"]
            costs += event["cost"]
        assert event["cash"] == pytest.approx(cash, abs=1e-10)
        for sym in quantities.keys() | event["quantities"].keys():
            assert event["quantities"].get(sym, 0) == pytest.approx(quantities.get(sym, 0))
        marked = sum(q * event["marks"][sym] for sym, q in quantities.items() if q != 0)
        assert event["equity"] == pytest.approx(cash + marked, abs=1e-10)
        assert event["cumulative_cost"] == pytest.approx(costs, abs=1e-10)
        for sym, quantity in event["quantities"].items():
            if quantity != 0:
                bar = panel[sym].loc[event["date"]]
                expected_mark = bar["adjusted_close"]
                if event["event"] in ("execution_mark", "fill", "rejected") and execution == "next_open":
                    expected_mark = bar["open"] * bar["adjusted_close"] / bar["close"]
                assert event["marks"][sym] == pytest.approx(expected_mark)
    assert next(filled, None) is None
    assert result.quantities.iloc[-1].abs().sum() == pytest.approx(0, abs=1e-12)
    assert result.equity_curve.iloc[-1] == pytest.approx(cash, abs=1e-10)
    assert not (result.marks.isna() & result.quantities.ne(0)).to_numpy().any()
    assert result.trading_costs.to_numpy().sum() == pytest.approx(result.trading_cost)
    assert result.borrow_costs.to_numpy().sum() == pytest.approx(result.borrow_cost)
    changes = result.equity_curve.diff()
    changes.iloc[0] = result.equity_curve.iloc[0] - INITIAL_CAPITAL
    np.testing.assert_allclose((result.gross_pnl - result.trading_costs
                                - result.borrow_costs).sum(axis=1), changes, atol=1e-10)
    np.testing.assert_allclose(result.cash + (result.quantities * result.marks).sum(axis=1),
                               result.equity_curve, rtol=1e-12, atol=1e-10)
    np.testing.assert_allclose(INITIAL_CAPITAL * (1 + result.returns).cumprod(),
                               result.equity_curve, rtol=1e-12, atol=1e-10)


@pytest.mark.parametrize("execution,expected_equity,expected_cash,expected_quantity", [
    ("next_open", 1127.5, 825.0, 275.0 / 120.0),
    ("next_close", 1160.0, 870.0, 290.0 / 132.0),
])
def test_overnight_and_intraday_pnl_on_resize(execution, expected_equity,
                                            expected_cash, expected_quantity):
    """Carry five units overnight; resize using that event's marked equity."""
    panel = _panel()
    for bar in range(62, 65):
        _set_bar(panel["ETF"], bar, open_=120 if bar == 62 else 132, close=132)
    result = _run(panel, decisions={60: .5, 61: .25}, execution=execution)
    assert result.equity_curve.iloc[62] == pytest.approx(expected_equity)
    assert result.cash.iloc[62] == pytest.approx(expected_cash)
    assert result.quantities.iloc[62]["ETF"] == pytest.approx(expected_quantity)
    assert result.orders[1].executed_quantity == pytest.approx(expected_quantity - 5)


def test_adjusted_execution_and_valuation_share_one_price_basis():
    """Raw 200 open / 220 close, adjusted close 55 means adjusted open 50."""
    panel = _panel()
    prices = panel["ETF"]
    prices["adjusted_close"] = 50.0
    _set_bar(prices, 61, open_=200, close=220)
    prices.loc[prices.index[61], "adjusted_close"] = 55
    for bar in range(62, 65):
        _set_bar(prices, bar, open_=110, close=110)
        prices.loc[prices.index[bar], "adjusted_close"] = 55
    result = _run(panel)
    assert result.orders[0].fill_price == pytest.approx(50)
    assert result.orders[0].executed_quantity == pytest.approx(10)
    assert result.cash.iloc[-1] == pytest.approx(500)
    assert result.equity_curve.iloc[-1] == pytest.approx(1050)


def test_borrow_fee_uses_actual_carried_short_quantity():
    """Five short units at 100 cost $0.05 per carried bar, not a shrinking weight."""
    result = _run(_panel(), weight=-.5, commission_bps=10, borrow_bps=252)
    assert result.trading_cost == pytest.approx(.5)
    assert result.borrow_cost == pytest.approx(.15, abs=1e-12)
    assert result.equity_curve.iloc[-1] == pytest.approx(999.35)
    assert result.cash.iloc[-1] == pytest.approx(1499.35)
    assert result.quantities.iloc[-1]["ETF"] == pytest.approx(-5)


def test_turnover_and_net_attribution_use_fills_not_weight_drift():
    """A single $500 entry has 0.5 turnover and $49.50 net entry-day profit."""
    from quantbot.reporting.s02_analytics import contribution_frame, etf_contribution

    panel = _panel()
    for bar in range(61, 65):
        _set_bar(panel["ETF"], bar, open_=100 if bar == 61 else 110, close=110)
    result = _run(panel, commission_bps=10)
    assert result.turnover_series.sum() == pytest.approx(.5)
    contrib = contribution_frame(result, panel)
    assert contrib.iloc[61]["ETF"] == pytest.approx(.0495)
    np.testing.assert_allclose(contrib.sum(axis=1), result.returns, atol=1e-12)
    annual = .5 / (65 / 252)
    assert etf_contribution(result, panel)["summary"].loc["ETF", "annual_turnover"] == (
        pytest.approx(annual))
    assert result.turnover_attribution()["annual_entry"] == pytest.approx(annual)
    assert result.turnover_attribution()["annual_resize"] == 0


@pytest.mark.parametrize("bad_mark", [np.nan, 0.0, -1.0, np.inf])
def test_invalid_held_mark_reports_symbol_and_date(bad_mark):
    panel = _panel()
    date = panel["ETF"].index[62]
    panel["ETF"].loc[date, "adjusted_close"] = bad_mark
    with pytest.raises(ValueError, match=rf"ETF.*{date.date()}"):
        _run(panel)


def test_rejected_fill_does_not_mutate_existing_ledger():
    """A rejected broker instruction cannot alter an existing long position."""
    from quantbot.backtest.broker import SimulatedBroker
    from quantbot.backtest.order import Order
    from quantbot.backtest.position import Portfolio

    panel = _panel()
    broker = SimulatedBroker(panel, EquityCostModel(0, 0, SlippageModel(0)))
    dates = panel["ETF"].index
    portfolio = Portfolio(INITIAL_CAPITAL)
    buy = broker.fill(Order("ETF", dates[60], dates[61], 0, .5), portfolio.equity)
    portfolio.apply_fill(buy)
    before = (portfolio.cash, dict(portfolio.quantities), dict(portfolio.marks),
              portfolio.equity, portfolio.cumulative_cost)
    panel["ETF"].loc[dates[62], "open"] = np.nan
    sell = broker.fill(Order("ETF", dates[61], dates[62], .5, 0), portfolio.equity,
                       current_quantity=portfolio.quantities["ETF"])
    assert sell.status == OrderStatus.REJECTED
    portfolio.apply_fill(sell)
    assert before == (portfolio.cash, portfolio.quantities, portfolio.marks,
                      portfolio.equity, portfolio.cumulative_cost)
    assert sell.executed_quantity == sell.notional == sell.cost == 0


def test_mixed_rejected_and_filled_orders_only_create_executed_positions():
    """A rejected second leg must not receive the first leg's successful state."""
    panel = _panel()
    panel["BAD"] = panel["ETF"].copy()
    panel["BAD"].loc[panel["BAD"].index[61], "open"] = np.nan

    class TwoTargets(_ScheduledWeights):
        def target_weights(self, panel):
            return super().target_weights(panel).assign(BAD=lambda w: w.ETF)

    result = BacktestEngine(initial_capital=1000,
        cost_model=EquityCostModel(0, 0, SlippageModel(0))).run(TwoTargets({60: .5}), panel)
    assert {o.symbol: o.status for o in result.orders} == {
        "ETF": OrderStatus.FILLED, "BAD": OrderStatus.REJECTED}
    assert result.cash.iloc[-1] == pytest.approx(500)
    assert result.quantities.iloc[-1].to_dict() == {"ETF": 5, "BAD": 0}


def test_full_exit_is_not_suppressed_when_held_market_value_becomes_tiny():
    """A near-zero weight still represents real units that must be sold on exit."""
    panel = _panel()
    for bar in range(62, 65):
        _set_bar(panel["ETF"], bar, open_=1e-12, close=1e-12)
    result = _run(panel, decisions={60: .5, 62: 0})
    assert result.quantities.iloc[-1]["ETF"] == 0
    assert len(result.orders) == 2
    assert result.orders[-1].executed_quantity == -5


def test_nullable_missing_mark_has_an_explicit_valuation_error():
    from quantbot.backtest.position import required_mark

    with pytest.raises(ValueError, match="ETF.*2024-03-28"):
        required_mark(pd.NA, "ETF", pd.Timestamp("2024-03-28"))


def test_same_target_rebalances_actual_drift_and_charges_the_executed_amount():
    """At open 120, equity is 1100: a renewed 50% target sells $50, not zero."""
    panel = _panel()
    for bar in range(62, 65):
        _set_bar(panel["ETF"], bar, open_=120, close=120)
    result = _run(panel, decisions={60: .5, 61: .5})
    assert result.orders[1].notional == pytest.approx(50)
    assert result.quantities.iloc[62]["ETF"] == pytest.approx(550 / 120)
    assert result.cash.iloc[62] == pytest.approx(550)
    assert result.turnover_series.iloc[62] == pytest.approx(50 / 1100)


def test_no_trade_band_preserves_quantities_and_never_blocks_a_full_exit():
    panel = _panel()
    for bar in range(62, 65):
        _set_bar(panel["ETF"], bar, open_=110, close=110)
    result = BacktestEngine(initial_capital=1000, rebalance_band=.05,
        cost_model=EquityCostModel(0, 0, SlippageModel(0))).run(
            _ScheduledWeights({60: .5, 61: .5, 62: 0}), panel)
    assert result.quantities.iloc[62]["ETF"] == 5
    assert result.weights.iloc[62]["ETF"] == pytest.approx(550 / 1050)
    assert result.turnover_series.iloc[62] == 0
    assert result.quantities.iloc[63]["ETF"] == 0
    assert len(result.orders) == 2


def test_all_transaction_cost_components_are_cash_charged_once_per_fill():
    panel = _panel()
    result = BacktestEngine(initial_capital=1000, cost_model=EquityCostModel(
        commission_bps=10, half_spread_bps=5, slippage=SlippageModel(2))).run(
            _ScheduledWeights({60: .5, 61: 0}), panel)
    assert [o.notional for o in result.orders] == [500, 500]
    assert [o.cost for o in result.orders] == pytest.approx([.85, .85])
    assert result.total_cost == pytest.approx(1.7)
    assert result.cash.iloc[-1] == pytest.approx(998.3)
    assert result.equity_curve.iloc[-1] == pytest.approx(998.3)


@pytest.mark.parametrize("reverse", [False, True])
def test_multiple_fills_share_pre_cost_equity_independent_of_order(reverse):
    panel = _panel()
    panel["SECOND"] = panel["ETF"].copy()
    panel["SECOND"][["open", "high", "low", "close", "adjusted_close"]] = 200
    targets = {"ETF": .3, "SECOND": -.4}
    if reverse:
        panel = {"Z": panel["ETF"], "A": panel["SECOND"]}
        targets = {"Z": .3, "A": -.4}

    class Targets:
        rebalance_frequency = "daily"

        def target_weights(self, panel):
            w = pd.DataFrame(np.nan, index=next(iter(panel.values())).index, columns=panel)
            w.loc[w.index[60]] = pd.Series(targets)
            return w

    result = BacktestEngine(initial_capital=1000,
        cost_model=EquityCostModel(10, 0, SlippageModel(0))).run(Targets(), panel)
    assert sorted(o.notional for o in result.orders) == [300, 400]
    assert all(o.allocation_equity == 1000 for o in result.orders)
    assert result.total_cost == pytest.approx(.7)
    assert result.cash.iloc[-1] == pytest.approx(1099.3)
    assert result.equity_curve.iloc[-1] == pytest.approx(999.3)


def test_resize_cost_uses_executed_notional_after_prior_cost_and_overnight_move():
    panel = _panel()
    for bar in range(62, 65):
        _set_bar(panel["ETF"], bar, open_=120, close=120)
    result = _run(panel, decisions={60: .5, 61: .5}, commission_bps=10)
    resize = result.orders[1]
    assert resize.allocation_equity == pytest.approx(1099.5)
    assert resize.executed_quantity == pytest.approx(-.41875)
    assert resize.notional == pytest.approx(50.25)
    assert resize.cost == pytest.approx(.05025)
    assert result.cash.iloc[62] == pytest.approx(549.69975)
    assert result.equity_curve.iloc[62] == pytest.approx(1099.44975)


def test_s01_trade_diagnostic_reconciles_adjacent_trades_without_cost_overlap(capsys):
    """Exercise the actual S01 reporting function with a real, known ledger.

    Load only its two function definitions: the enclosing CLI imports broken
    statsmodels-dependent S03 diagnostics that this unit test does not exercise.
    No dependency is installed/stubbed, and full CLI import is not certified.
    """
    import ast
    from pathlib import Path
    from types import SimpleNamespace
    from quantbot.backtest.performance import compute_metrics

    panel = _panel()
    for bar, (op, cl) in enumerate([(100, 110), (120, 120), (120, 132), (144, 144)], 61):
        _set_bar(panel["ETF"], bar, open_=op, close=cl)
    result = _run(panel, decisions={60: .5, 61: 0, 62: .5, 63: 0}, commission_bps=10)
    path = Path(__file__).resolve().parents[1] / "scripts" / "research_edge.py"
    parsed = ast.parse(path.read_text(encoding="utf-8"))
    functions = [node for node in parsed.body if isinstance(node, ast.FunctionDef)
                 and node.name in {"_spells", "s01_diagnostics"}]
    assert len(functions) == 2
    namespace = {
        "np": np, "pd": pd, "TRADING_DAYS_PER_YEAR": 252,
        "compute_metrics": compute_metrics, "RiskManager": RiskManager,
        "load_risk_config": lambda: {}, "strategy_params": lambda *args: {},
        "S01TrendFollowing": lambda *args, **kwargs: None,
        "BacktestEngine": lambda **kwargs: SimpleNamespace(run=lambda *a, **kw: result),
    }
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(path), "exec"), namespace)
    diagnostic = namespace["s01_diagnostics"](panel, {}, {})
    assert diagnostic["net_sum"] == pytest.approx(.20758121, abs=1e-10)
    assert diagnostic["net_sum"] == pytest.approx(result.equity_curve.iloc[-1] / 1000 - 1)
    assert "trades=2" in capsys.readouterr().out
