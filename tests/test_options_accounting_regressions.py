"""Phase 1B: hand-calculated accounting, atomic fills and lifecycle guards.

Single-leg cases exercise the accounting primitive, not a new strategy. The
short-put example has $10,000 cash against a $10,000 strike obligation.
"""
from copy import deepcopy

import numpy as np
import pandas as pd
import pytest

from quantbot.costs.transaction_costs import OptionsCostModel
from quantbot.options import contract_selector as cs
from quantbot.options.backtest_engine import (
    OptionsBacktestEngine, PendingClose, PendingOpen,
)
from quantbot.options.fill_model import close_leg, fill_leg, fill_structure
from quantbot.options.position import BacktestLeg, BacktestPosition
from quantbot.options.spreads import build_bull_call_spread


D0, D1, D2 = map(pd.Timestamp, ["2026-01-05", "2026-01-06", "2026-01-07"])
EXP = pd.Timestamp("2026-02-06")
CM = OptionsCostModel(per_contract_fee=1.0, bid_ask_fraction=0.5,
                      multi_leg_penalty=0.5)


def row(strike=100, bid=2.0, ask=2.2, *, date=D1, expiration=EXP,
        underlying="SPY", right="call", spot=102.0, delta=0.5):
    return pd.Series(dict(date=date, underlying=underlying, expiration=expiration,
                          option_type=right, strike=float(strike), bid=bid, ask=ask,
                          underlying_price=spot, delta=delta, gamma=0.01,
                          theta=-0.02, vega=0.1, contract_multiplier=100,
                          dte=(expiration-date).days))


def chain(*rows):
    return pd.DataFrame(rows).reset_index(drop=True)


def position(*, vertical=False, right="call", qty=1, expiration=EXP):
    legs = [BacktestLeg(right, expiration, 100.0, qty, 2.2 if qty > 0 else 2.0)]
    if vertical:
        legs.append(BacktestLeg(right, expiration, 105.0, -1, 1.0))
    premium = -sum(l.qty*l.fill_price*l.multiplier for l in legs)
    return BacktestPosition("fixture", "SPY", D0, D1, expiration, legs,
                            2.5 if vertical else 1.0, premium, 380, -220, 5)


class OneShot:
    name, underlying = "accounting_fixture", "SPY"

    def __init__(self, normal_close=False):
        self.fired = False
        self.normal_close = normal_close

    def on_decision_open(self, t, quotes, portfolio):
        if self.fired:
            return None
        self.fired = True
        return build_bull_call_spread(quotes, cost_model=CM)

    def on_decision_close(self, pos, quotes, t):
        return self.normal_close, "normal_close"


def series(*, expiration=EXP):
    return chain(*(r for t in (D0, D1, D2) for r in (
        row(100, 2, 2.2, date=t, expiration=expiration),
        row(105, 1, 1.1, date=t, expiration=expiration, delta=0.3))))


def seeded_engine(pos):
    engine = OptionsBacktestEngine(series(), OneShot(), initial_capital=10000,
                                  cost_model=CM)
    engine._open_positions = [pos]
    engine._cash += pos.net_entry_cash - pos.open_cost
    engine._pending_closes_next = []
    return engine


@pytest.mark.parametrize("bid,ask", [(np.nan, 2.2), (2, np.nan),
                                      (np.inf, 2.2), (2, np.inf), (2.2, 2)])
@pytest.mark.parametrize("qty", [1, -1])
def test_invalid_quotes_never_fill(bid, ask, qty):
    assert not fill_leg(row(bid=bid, ask=ask), qty).accepted


def test_missing_quote_field_is_explicit_rejection():
    assert not fill_leg(row().drop("ask"), 1).accepted


def test_bid_ask_is_not_charged_again_as_a_spread_fee():
    out = fill_structure([dict(qty=1), dict(qty=-1)],
                         [row(), row(105, 1, 1.1)], cost_model=CM)
    assert out.accepted
    assert out.net_cash == pytest.approx(-120)
    assert out.cost == pytest.approx(2.5)  # $2 commission + $0.50 explicit penalty


def test_position_mark_uses_full_underlying_identity():
    pos = position()
    pos.mark(chain(row(bid=8, ask=8.1, underlying="QQQ"), row()), D1)
    assert pos.last_mtm_value == pytest.approx(200)


def test_contract_strike_lookup_is_exact_not_fuzzy():
    found = cs.lookup_row(chain(row(100.0005)), expiration=EXP,
                          option_type="call", strike=100)
    assert found is None


def test_builder_does_not_select_another_underlying():
    q = chain(row(100, 8, 8.1, underlying="QQQ"),
              row(105, 1, 1.1, underlying="QQQ", delta=0.3),
              row(), row(105, 1, 1.1, delta=0.3))
    cand = build_bull_call_spread(q, underlying="SPY", cost_model=CM)
    assert not cand.reject_reason
    assert cand.net_cash == pytest.approx(-120)


@pytest.mark.parametrize("bad", ["missing", "nan", "crossed"])
def test_bad_held_mark_raises_and_preserves_entire_prior_state(bad):
    pos = position(vertical=True)
    good = chain(row(), row(105, 1, 1.1))
    pos.mark(good, D1)
    prior = deepcopy(pos.__dict__)
    broken = good.copy()
    broken["date"] = D2
    if bad == "missing":
        broken = broken.iloc[:1]
    else:
        broken.loc[1, "bid"] = np.nan if bad == "nan" else 1.2
    with pytest.raises(ValueError, match=r"SPY.*105.*2026-01-07"):
        pos.mark(broken, D2)
    assert pos.__dict__ == prior


@pytest.mark.parametrize("bid,ask", [(1, 1.5), (0.01, 2)])
def test_terminal_exit_obeys_normal_spread_gate_without_midpoint(bid, ask):
    pos = position()
    eng = seeded_engine(pos)
    quotes = chain(row(bid=bid, ask=ask, date=D2))
    pos.mark(quotes, D2)
    prior = (eng._cash, deepcopy(pos.__dict__))
    with pytest.raises(ValueError, match=r"terminal.*SPY.*2026-01-07"):
        eng._force_close_remaining(D2, quotes)
    assert (eng._cash, pos.__dict__) == prior
    assert not eng._orders and not eng._trades


def test_terminal_missing_leg_never_partially_closes():
    pos = position(vertical=True)
    pos.mark(chain(row(), row(105, 1, 1.1)), D1)
    eng = seeded_engine(pos)
    prior = (eng._cash, deepcopy(pos.__dict__))
    with pytest.raises(ValueError, match=r"terminal.*SPY.*105.*2026-01-07"):
        eng._force_close_remaining(D2, chain(row(date=D2)))
    assert (eng._cash, pos.__dict__) == prior
    assert not eng._orders and not eng._trades


def test_expiration_uses_own_underlying_and_clears_value():
    pos = position(expiration=D2)
    pos.last_mtm_value = 200
    pnl = pos.settle_at_expiration(chain(
        row(date=D2, underlying="QQQ", spot=900), row(date=D2, spot=103)), D2)
    assert pnl == pytest.approx(79)  # 300 intrinsic - 220 entry - 1 commission
    assert pos.last_mtm_value == 0
    assert pos.closed


@pytest.mark.parametrize("bad", ["empty", "nan", "wrong_underlying", "conflict"])
def test_expiration_requires_valid_same_underlying_spot(bad):
    pos = position(expiration=D2)
    q = chain(row(date=D2))
    if bad == "empty":
        q = q.iloc[:0]
    elif bad == "nan":
        q["underlying_price"] = np.nan
    elif bad == "wrong_underlying":
        q["underlying"] = "QQQ"
    else:
        q = chain(row(date=D2, spot=102), row(105, date=D2, spot=103))
    prior = deepcopy(pos.__dict__)
    with pytest.raises(ValueError, match=r"SPY.*2026-01-07"):
        pos.settle_at_expiration(q, D2)
    assert pos.__dict__ == prior


def test_skipped_expiration_is_not_traded_or_marked_after_expiry():
    pos = position(expiration=D1)
    eng = seeded_engine(pos)
    with pytest.raises(ValueError, match=r"expiration.*SPY.*2026-01-06"):
        eng._settle_expirations(D2, chain(row(date=D2)))
    assert not pos.closed


def test_close_cannot_accept_rejected_fill_or_repeat_cash_entitlement():
    pos = position()
    prior = deepcopy(pos.__dict__)
    rejected = close_leg(row(bid=0, ask=2), 1)
    with pytest.raises(ValueError, match="fill"):
        pos.close_at([rejected], D2, cost=1, reason="test")
    assert pos.__dict__ == prior
    good = close_leg(row(bid=3, ask=3.2), 1)
    pos.close_at([good], D2, cost=1, reason="test")
    assert pos.last_mtm_value == 0
    with pytest.raises(ValueError, match="closed"):
        pos.close_at([good], D2, cost=1, reason="test")


@pytest.mark.parametrize("invalid", ["missing", "nan", "crossed"])
def test_rejected_entry_is_atomic_and_leaves_cash_unchanged(invalid):
    eng = OptionsBacktestEngine(series(), OneShot(), initial_capital=10000,
                                cost_model=CM)
    cand = build_bull_call_spread(chain(row(), row(105, 1, 1.1, delta=.3)))
    eng._pending_opens = [PendingOpen(D0, cand)]
    q = chain(row(), row(105, 1, 1.1))
    if invalid == "missing":
        q = q.iloc[:1]
    else:
        q.loc[1, "bid"] = np.nan if invalid == "nan" else 1.2
    eng._execute_pending_opens(D1, q)
    assert eng._cash == 10000
    assert not eng._open_positions and not eng._orders
    assert eng._total_cost == 0
    assert eng._rejections


@pytest.mark.parametrize("kind,rights,qtys,strikes,entry,exit_,expected", [
    ("long_call", ["call"], [1], [100], [(2, 2.2)], [(3, 3.2)], 78),
    ("cash_secured_short_put", ["put"], [-1], [100], [(2, 2.2)], [(1, 1.1)], 88),
    ("debit_vertical", ["call", "call"], [1, -1], [100, 105],
     [(2, 2.2), (1, 1.1)], [(4, 4.2), (1.5, 1.6)], 115),
    ("credit_vertical", ["put", "put"], [1, -1], [95, 100],
     [(1, 1.1), (2, 2.2)], [(.4, .5), (.8, .9)], 35),
])
def test_hand_calculated_round_trip(kind, rights, qtys, strikes, entry, exit_, expected):
    legs = [dict(option_type=r, strike=k, qty=q)
            for r, k, q in zip(rights, strikes, qtys)]
    opening = [row(k, *ba, right=r) for k, ba, r in zip(strikes, entry, rights)]
    closing = [row(k, *ba, right=r, date=D2) for k, ba, r in zip(strikes, exit_, rights)]
    fill = fill_structure(legs, opening, cost_model=CM)
    pos = BacktestPosition(kind, "SPY", D0, D1, EXP,
        [BacktestLeg(r, EXP, k, q, fr.fill_price)
         for r, k, q, fr in zip(rights, strikes, qtys, fill.legs)],
        fill.cost, fill.net_cash, 0, -10000, 5)
    cash = 10000 + fill.net_cash - fill.cost
    pos.mark(chain(*opening), D1)
    entry_mark = sum(q*ba[0 if q > 0 else 1]*100 for q, ba in zip(qtys, entry))
    assert pos.last_mtm_value == pytest.approx(entry_mark)
    assert cash + entry_mark == pytest.approx(10000 + pos.paper_pnl)
    pos.mark(chain(*closing), D2)
    eng = seeded_engine(pos)
    eng._pending_closes = [PendingClose(D1, pos, "normal_close")]
    eng._execute_pending_closes(D2, chain(*closing))
    assert pos.realized_pnl == pytest.approx(expected)
    assert eng._cash == pytest.approx(10000 + expected)
    assert pos.last_mtm_value == 0
    assert eng._portfolio_view().equity == pytest.approx(eng._cash)


@pytest.mark.parametrize("expiry,normal", [(EXP, True), (EXP, False), (D2, False)])
def test_engine_daily_net_returns_reconcile_with_hand_cash(expiry, normal):
    eng = OptionsBacktestEngine(series(expiration=expiry), OneShot(normal),
                                initial_capital=10000, cost_model=CM)
    res = eng.run()
    # -120 premium, -2.50 entry cost; normal close +90, -2.50;
    # expiry spot102 pays 200 intrinsic with no exit fee.
    ending = 10077.5 if expiry == D2 else 9965.0
    assert res.equity_curve.iloc[-1] == pytest.approx(ending)
    assert res.cash_curve.iloc[-1] == pytest.approx(ending)
    assert res.trades[0].realized_pnl == pytest.approx(ending-10000)
    assert res.total_cost == pytest.approx(2.5 if expiry == D2 else 5)
    np.testing.assert_allclose(10000*(1+res.daily_returns).cumprod(), res.equity_curve,
                               atol=1e-9, rtol=1e-12)
    assert not eng._open_positions
    assert res.daily_greeks.iloc[-1].eq(0).all()


def test_builder_and_executed_orders_retain_full_contract_and_cash_details():
    cand = build_bull_call_spread(series().query("date == @D0"))
    for leg in cand.legs:
        assert leg.get("underlying") == "SPY"
        assert leg.get("expiration") == EXP
        assert leg.get("multiplier") == 100
    eng = OptionsBacktestEngine(series(), OneShot(True), initial_capital=10000,
                                cost_model=CM)
    res = eng.run()
    for order in res.orders:
        legs = order.get("legs", [])
        assert len(legs) == 2
        for leg in legs:
            assert leg.get("underlying") == "SPY"
            assert leg.get("expiration") == EXP
            assert leg["notional"] == pytest.approx(abs(leg["qty"])*leg["fill_price"]*100)
            assert leg["cash_flow"] == pytest.approx(-leg["qty"]*leg["fill_price"]*100)
        premium = order["net_cash"] if order["type"] == "open" else order["close_cash"]
        assert sum(l["cash_flow"] for l in legs) == pytest.approx(premium)
        assert order["cost"] == order["commission"] + order["slippage"]
        assert order["spread_cost"] == 0
    tr = res.trades[0]
    assert tr.net_exit_cash == pytest.approx(90)
    assert tr.open_commission == tr.close_commission == 2
    assert tr.open_slippage == tr.close_slippage == .5


@pytest.mark.parametrize("expiry", [EXP, D2])
def test_every_event_reconciles_cash_signed_holdings_pnl_and_executions(expiry):
    res = OptionsBacktestEngine(series(expiration=expiry), OneShot(),
        initial_capital=10000, cost_model=CM).run()
    known = set()
    expected_cash = 10000.0
    orders = iter(res.orders)
    for event in res.event_ledger:
        if event["event"] in ("open", "close", "expire"):
            order = next(orders)
            for leg in order["legs"]:
                key = (leg["underlying"], leg["expiration"], leg["option_type"], leg["strike"])
                if order["type"] == "open":
                    known.add(key)
                else:
                    assert key in known
                    known.remove(key)
            premium = sum(l["cash_flow"] for l in order["legs"])
            expected_cash += premium - order["cost"]
        value = 0.0
        for leg in event["holdings"]:
            key = (leg["underlying"], leg["expiration"], leg["option_type"], leg["strike"])
            assert key in known  # no holdings before a valid executed open
            assert leg["mark_date"] <= event["date"]
            value += leg["qty"] * leg["multiplier"] * leg["mark_price"]
        assert event["cash"] == pytest.approx(expected_cash, abs=1e-9)
        assert event["equity"] == pytest.approx(expected_cash + value, abs=1e-9)
        assert event["equity"] == pytest.approx(
            10000 + event["realized_pnl"] + event["unrealized_pnl"], abs=1e-9)
    assert next(orders, None) is None
    assert not known


def test_changed_fill_price_changes_premium_cash_and_pnl_once():
    base = OptionsBacktestEngine(series(), OneShot(True), initial_capital=10000,
                                 cost_model=CM).run()
    altered = series()
    altered.loc[(altered.date == D1) & (altered.strike == 100), "ask"] = 2.4
    other = OptionsBacktestEngine(altered, OneShot(True), initial_capital=10000,
                                  cost_model=CM).run()
    assert other.orders[0]["net_cash"] - base.orders[0]["net_cash"] == pytest.approx(-20)
    assert other.cash_curve.iloc[1] - base.cash_curve.iloc[1] == pytest.approx(-20)
    assert other.trades[0].realized_pnl - base.trades[0].realized_pnl == pytest.approx(-20)
    assert other.total_cost == base.total_cost


@pytest.mark.parametrize("bad", ["underlying", "expiration", "multiplier"])
def test_leg_identity_mismatch_cannot_be_substituted_at_entry(bad):
    cand = build_bull_call_spread(chain(row(), row(105, 1, 1.1, delta=.3)))
    cand.legs[1][bad] = {"underlying": "QQQ", "expiration": EXP+pd.Timedelta(days=7),
                          "multiplier": 10}[bad]
    eng = OptionsBacktestEngine(series(), OneShot(), initial_capital=10000, cost_model=CM)
    eng._pending_opens = [PendingOpen(D0, cand)]
    eng._execute_pending_opens(D1, chain(row(), row(105, 1, 1.1)))
    assert eng._cash == 10000
    assert not eng._open_positions and not eng._orders
    assert eng._rejections


def test_nonstandard_deliverable_is_explicitly_unsupported():
    q = series()
    q["contract_multiplier"] = 10
    res = OptionsBacktestEngine(q, OneShot(), initial_capital=10000, cost_model=CM).run()
    assert not res.orders
    assert res.rejections
    assert res.equity_curve.eq(10000).all()


@pytest.mark.parametrize("expiry_offset", [0, -1])
def test_pending_entry_cannot_execute_on_or_after_expiry(expiry_offset):
    exp = D1 + pd.Timedelta(days=expiry_offset)
    q = series(expiration=exp)
    res = OptionsBacktestEngine(q, OneShot(), initial_capital=10000, cost_model=CM).run()
    assert not res.orders
    assert res.rejections
    assert res.equity_curve.eq(10000).all()


def test_engine_missing_held_quote_stops_with_prior_valid_mark_intact():
    q = series()
    q = q[~((q.date == D2) & (q.strike == 105))]
    eng = OptionsBacktestEngine(q, OneShot(), initial_capital=10000, cost_model=CM)
    with pytest.raises(ValueError, match=r"SPY.*105.*2026-01-07"):
        eng.run()
    assert len(eng._open_positions) == 1
    assert eng._open_positions[0].last_mtm_value == pytest.approx(90)
    assert eng._cash == pytest.approx(9877.5)
    assert not eng._trades


def test_normal_rejected_close_keeps_all_legs_and_cash_then_can_retry():
    pos = position(vertical=True)
    pos.mark(chain(row(), row(105, 1, 1.1)), D1)
    eng = seeded_engine(pos)
    eng._pending_closes = [PendingClose(D1, pos, "normal_close")]
    state = (eng._cash, deepcopy(pos.__dict__))
    eng._execute_pending_closes(D2, chain(row(date=D2)))
    assert (eng._cash, pos.__dict__) == state
    assert not eng._orders and len(eng._pending_closes) == 1
    eng._execute_pending_closes(D2+pd.Timedelta(days=1), chain(
        row(date=D2+pd.Timedelta(days=1)), row(105, 1, 1.1, date=D2+pd.Timedelta(days=1))))
    assert pos.closed and len(eng._orders) == 1
    assert eng._cash == pytest.approx(9965)


@pytest.mark.parametrize("qty,spot,pnl", [(1, 103, 79), (1, 99, -221),
                                        (-1, 98, -1), (-1, 103, 199)])
def test_single_leg_intrinsic_expiration_cash_examples(qty, spot, pnl):
    right = "call" if qty > 0 else "put"
    pos = position(right=right, qty=qty, expiration=D2)
    eng = seeded_engine(pos)
    eng._settle_expirations(D2, chain(row(date=D2, right=right, spot=spot)))
    assert pos.realized_pnl == pytest.approx(pnl)
    assert eng._cash == pytest.approx(10000+pnl)
    assert eng._portfolio_view().equity == pytest.approx(eng._cash)
    assert pos.closed and pos.last_mtm_value == 0


@pytest.mark.parametrize("bad", ["underlying", "expiration", "date"])
def test_atomic_fill_cannot_mix_row_contract_scope(bad):
    first, second = row(), row(105, 1, 1.1)
    second[bad] = {"underlying": "QQQ", "expiration": EXP+pd.Timedelta(days=1),
                    "date": D2}[bad]
    result = fill_structure([dict(qty=1), dict(qty=-1)], [first, second])
    assert not result.accepted
    assert result.net_cash == result.cost == 0


@pytest.mark.parametrize("action", ["mark", "normal_close", "terminal_close"])
def test_changed_contract_multiplier_cannot_mark_or_close_existing_contract(action):
    pos = position()
    pos.mark(chain(row()), D1)
    q = chain(row(date=D2))
    q["contract_multiplier"] = 10
    eng = seeded_engine(pos)
    prior = (eng._cash, deepcopy(pos.__dict__))
    if action == "mark":
        with pytest.raises(ValueError, match=r"SPY.*100.*2026-01-07"):
            pos.mark(q, D2)
    elif action == "normal_close":
        eng._pending_closes = [PendingClose(D1, pos, "normal_close")]
        eng._execute_pending_closes(D2, q)
        assert eng._rejections
    else:
        with pytest.raises(ValueError, match=r"terminal.*SPY.*2026-01-07"):
            eng._force_close_remaining(D2, q)
    assert (eng._cash, pos.__dict__) == prior
    assert not eng._orders


def test_two_contract_vertical_has_correct_fill_time_payoff_bounds():
    cand = build_bull_call_spread(chain(row(), row(105, 1, 1.1, delta=.3)))
    for leg in cand.legs:
        leg["qty"] *= 2
    eng = OptionsBacktestEngine(series(), OneShot(), initial_capital=10000, cost_model=CM)
    eng._pending_opens = [PendingOpen(D0, cand)]
    eng._execute_pending_opens(D1, chain(row(), row(105, 1, 1.1)))
    pos = eng._open_positions[0]
    assert pos.net_entry_cash == pytest.approx(-240)
    assert pos.max_profit == pytest.approx(760)
    assert pos.max_loss == pytest.approx(-240)


@pytest.mark.parametrize("bad_fee", [np.nan, np.inf, -1])
def test_nonfinite_or_negative_execution_cost_cannot_change_cash(bad_fee):
    eng = OptionsBacktestEngine(series(), OneShot(), initial_capital=10000,
        cost_model=OptionsCostModel(per_contract_fee=bad_fee))
    with pytest.raises(ValueError, match="cost"):
        eng.run()
    assert eng._cash == 10000
    assert not eng._open_positions


def test_old_wide_bid_ask_fee_scenario_is_not_presented_as_spread_stress():
    from pathlib import Path
    import runpy
    script = Path(__file__).resolve().parents[1] / "scripts" / "run_options_v54.py"
    scenarios = runpy.run_path(str(script))["COST_SCENARIOS"]
    # Executions already cross the actual spread. Changing only the estimator
    # bid_ask_fraction is not a real bid/ask stress and must not be sold as one.
    assert "wide_bid_ask" not in scenarios
