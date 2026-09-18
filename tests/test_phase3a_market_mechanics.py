"""Deterministic Phase 3A market mechanics and economic invariants."""
import numpy as np
import pandas as pd
import pytest
from quantbot.backtest.engine import BacktestEngine
from quantbot.costs.transaction_costs import EquityCostModel
from quantbot.costs.slippage import SlippageModel


class Targets:
    rebalance_frequency = 'daily'

    def __init__(self, decisions):
        self.decisions = decisions

    def target_weights(self, panel):
        out = pd.DataFrame(np.nan, index=next(iter(panel.values())).index, columns=panel)
        for day, values in self.decisions.items():
            out.loc[pd.Timestamp(day)] = values
        return out


def prices(end='2024-04-10', symbols=('ETF',)):
    from quantbot.utils.market_calendar import USMarketCalendar
    idx = USMarketCalendar().sessions('2024-01-02', end)
    return {s: pd.DataFrame(dict(open=100., high=100., low=100., close=100.,
        adjusted_close=100., volume=1000000), index=idx) for s in symbols}


def run(panel, decisions, *, fee=0, **kwargs):
    result = BacktestEngine(initial_capital=1000,
        cost_model=EquityCostModel(fee, 0, SlippageModel(0)), **kwargs).run(Targets(decisions), panel)
    changes = result.equity_curve.diff()
    changes.iloc[0] = result.equity_curve.iloc[0]-1000
    np.testing.assert_allclose(result.pnl_components.total_net_pnl, changes, atol=1e-10)
    np.testing.assert_allclose(result.pnl_components.drop(columns='total_net_pnl').sum(axis=1), changes, atol=1e-10)
    np.testing.assert_allclose(1000*(1+result.returns).cumprod(), result.equity_curve, atol=1e-9)
    for e in result.ledger:
        assert e['equity'] == pytest.approx(e['cash']+sum(q*e['marks'][s] for s,q in e['quantities'].items()), abs=1e-10)
    return result


@pytest.mark.parametrize('day,next_day', [
    ('2024-03-28','2024-04-01'), ('2024-05-24','2024-05-28'),
    ('2021-12-30','2021-12-31'), ('2021-12-31','2022-01-03'),
    ('2024-12-31','2025-01-02'), ('2025-01-08','2025-01-10'),
    ('2012-10-26','2012-10-31'), ('2022-06-17','2022-06-21')])
def test_next_session(day, next_day):
    from quantbot.utils.market_calendar import USMarketCalendar
    assert USMarketCalendar().next_session(day) == pd.Timestamp(next_day)


def test_early_close_timezone_year_count():
    from quantbot.utils.market_calendar import USMarketCalendar
    cal = USMarketCalendar()
    assert len(cal.sessions('2022-01-01','2022-12-31')) == 251
    for day in ('2024-11-29','2024-07-03','2024-12-24'):
        assert cal.session(day).close.hour == 13
    assert cal.session('2024-12-26').close.hour == 16
    assert str(cal.session('2024-03-11').open.tz_convert('UTC')) == '2024-03-11 13:30:00+00:00'
    with pytest.raises(ValueError, match='supported'):
        cal.sessions('1990-01-01','1990-01-31')


def test_holiday_execution_and_session_roles():
    p = prices()
    r = run(p, {'2024-03-28':[.5]})
    o = r.orders[0]
    assert o.execution_date == pd.Timestamp('2024-04-01')
    assert r.cash.iloc[-1] == 500 and r.quantities.iloc[-1].ETF == 5
    assert r.equity_curve.iloc[-1] == 1000
    assert r.sessions.loc[o.execution_date,'execution_time'].hour == 9
    assert r.sessions.loc[o.signal_date,'signal_time'].hour == 16


def test_calendar_rejects_closed_and_missing_sessions():
    p = prices()
    p['ETF'].loc[pd.Timestamp('2024-03-29')] = p['ETF'].iloc[0]
    p['ETF'] = p['ETF'].sort_index()
    with pytest.raises(ValueError, match='non-session'):
        BacktestEngine().run(Targets({}), p)
    p = prices()
    p['ETF'] = p['ETF'].drop(pd.Timestamp('2024-03-28'))
    with pytest.raises(ValueError, match='missing.*session'):
        BacktestEngine().run(Targets({}), p)


def raw_book(panel, events=()):
    from quantbot.backtest.market_mechanics import CorporateActionBook
    for df in panel.values():
        df.attrs['price_basis'] = 'raw_unadjusted'
    idx = next(iter(panel.values())).index
    return CorporateActionBook(tuple(events),tuple(panel),idx[0],idx[-1],source='fixture',complete=True)


def test_split_has_no_market_loss():
    from quantbot.backtest.market_mechanics import CorporateAction
    p = prices()
    p['ETF'].loc['2024-04-02':,['open','close']] = 50
    book = raw_book(p,[CorporateAction('ETF','2024-04-02','split',2)])
    r = run(p, {'2024-03-28':[.5]}, price_mode='raw', corporate_actions=book)
    assert r.cash.iloc[-1] == 500 and r.quantities.iloc[-1].ETF == 10
    assert r.equity_curve.iloc[-1] == 1000
    assert r.pnl_components.market_pnl.sum() == 0


@pytest.mark.parametrize('kind',['dividend','special_dividend'])
@pytest.mark.parametrize('weight',[.5,-.5])
def test_dividend_prior_holdings_and_short_payment(kind,weight):
    from quantbot.backtest.market_mechanics import CorporateAction
    p = prices()
    p['ETF'].loc['2024-04-02':,['open','close']] = 98
    book = raw_book(p,[CorporateAction('ETF','2024-04-02',kind,2)])
    r = run(p,{'2024-03-28':[weight]},price_mode='raw',corporate_actions=book)
    assert r.dividends.sum().ETF == pytest.approx(weight*20)
    assert r.cash.iloc[-1] == pytest.approx(1000-weight*1000+weight*20)
    assert r.pnl_components.market_pnl.sum() == pytest.approx(-weight*20)
    assert r.equity_curve.iloc[-1] == 1000


def test_ex_date_entry_gets_no_dividend_but_exit_does():
    from quantbot.backtest.market_mechanics import CorporateAction
    p = prices()
    book = raw_book(p,[CorporateAction('ETF','2024-04-02','dividend',2)])
    assert run(p,{'2024-04-01':[.5]},price_mode='raw',corporate_actions=book).dividends.sum().ETF == 0
    r = run(p,{'2024-03-28':[.5],'2024-04-01':[0]},price_mode='raw',corporate_actions=book)
    assert r.cash.iloc[-1] == 1010 and r.dividends.sum().ETF == 10


def test_adjusted_accounting_cannot_mix_with_explicit_events():
    p = prices()
    book = raw_book(p)
    with pytest.raises(ValueError,match='adjusted.*corporate'):
        run(p,{},corporate_actions=book)
    p = prices()
    p['ETF'].loc['2024-04-02':,['open','close']] = 50
    r = run(p,{'2024-03-28':[.5]})
    assert r.quantities.iloc[-1].ETF == 5 and r.cash.iloc[-1] == 500
    assert r.equity_curve.iloc[-1] == 1000


def test_raw_requires_complete_actions_and_raw_attestation():
    from quantbot.backtest.market_mechanics import CorporateActionBook
    p = prices()
    with pytest.raises(ValueError,match='corporate.action'):
        run(p,{},price_mode='raw')
    book = CorporateActionBook((),('ETF',),'2024-01-02','2024-04-10',source='fixture',complete=False)
    with pytest.raises(ValueError,match='complete'):
        run(p,{},price_mode='raw',corporate_actions=book)
    book = raw_book(p)
    p['ETF'].attrs.clear()
    with pytest.raises(ValueError,match='raw_unadjusted'):
        run(p,{},price_mode='raw',corporate_actions=book)


def test_cash_interest_act365_and_disabled_legacy():
    p = prices()
    r = run(p,{},cash_interest_rate=.0365)
    cash = 1000.
    idx = p['ETF'].index
    for prior,day in zip(idx[:-1],idx[1:]):
        cash *= 1+.0365*(day-prior).days/365
        assert r.cash.loc[day] == pytest.approx(cash)
    assert r.pnl_components.cash_interest.sum() == pytest.approx(cash-1000)
    assert run(p,{}).cash.eq(1000).all()


def test_no_implicit_free_leverage_or_fee_debt():
    p = prices()
    for weight,fee in [(1.5,0),(1,10)]:
        with pytest.raises(ValueError,match='financing'):
            BacktestEngine(initial_capital=1000,
                cost_model=EquityCostModel(fee,0,SlippageModel(0))).run(
                    Targets({'2024-03-28':[weight]}),p)


def test_financed_long_charges_previous_debit_once():
    r = run(prices(end='2024-04-02'),{'2024-03-28':[1.5]},financing_rate=.073)
    assert r.cash.iloc[-1] == pytest.approx(-500.1)
    assert r.quantities.iloc[-1].ETF == 15
    assert r.financing_cost == pytest.approx(.1)
    assert r.equity_curve.iloc[-1] == pytest.approx(999.9)


def test_short_borrow_calendar_days_and_close():
    r = run(prices(end='2024-04-04'),{'2024-03-26':[-.5],'2024-04-01':[0]},
        borrow_cost_bps_annual=365,borrow_day_count='actual_365')
    assert r.borrow_cost == pytest.approx(.3)
    assert r.cash.iloc[-1] == pytest.approx(999.7)
    assert r.quantities.iloc[-1].ETF == 0
    assert r.borrow_costs.loc['2024-04-03':].sum().ETF == 0


def test_cash_interest_excludes_marked_short_collateral():
    from quantbot.backtest.market_mechanics import CashBalanceModel
    model = CashBalanceModel(.0365,None)
    assert model.accrual(1500,500,1) == pytest.approx((.1,0))
    assert model.accrual(100,500,1) == (0,0)


def test_combined_components_and_reporting():
    from quantbot.reporting.s02_analytics import contribution_frame,etf_contribution
    from quantbot.reporting.tearsheet import build_tearsheet,tearsheet_to_markdown
    p = prices(end='2024-04-02',symbols=('LONG','SHORT'))
    p['LONG'].loc['2024-04-02',['open','close','adjusted_close']] = 110
    r = run(p,{'2024-03-28':[.5,-.25]},fee=10,cash_interest_rate=.0365,
        borrow_cost_bps_annual=365,borrow_day_count='actual_365')
    entry_equity = r.equity_curve.loc['2024-03-28']*(1+.0365*4/365)
    qlong,qshort = entry_equity*.5/100,-entry_equity*.25/100
    entry_cash = entry_equity*.75-entry_equity*.75*.001
    interest = (entry_cash-abs(qshort)*100)*.0365/365
    borrow = abs(qshort)*100*.0365/365
    assert r.cash.iloc[-1] == pytest.approx(entry_cash+interest-borrow)
    c = r.pnl_components.iloc[-1]
    assert c.market_pnl == pytest.approx(qlong*10)
    assert c.cash_interest == pytest.approx(interest)
    assert c.short_borrow_cost == pytest.approx(-borrow)
    np.testing.assert_allclose(contribution_frame(r,p).sum(axis=1),r.returns,atol=1e-12)
    assert etf_contribution(r,p)['total_arithmetic_return'] == pytest.approx(r.returns.sum())
    assert 'cash_interest' in tearsheet_to_markdown(build_tearsheet(r))


def test_unfunded_rotation_sells_before_buy_without_changing_allocations():
    p = prices(symbols=('A','Z'))
    r = run(p,{'2024-03-28':[0,1],'2024-04-01':[1,0]})
    assert all(e['cash'] >= -1e-9 for e in r.ledger)
    assert r.quantities.iloc[-1].to_dict() == {'A':10,'Z':0}
    assert r.equity_curve.iloc[-1] == 1000


def test_cost_metrics_do_not_label_financing_as_transaction_cost():
    from quantbot.backtest.performance import compute_metrics
    r = run(prices(end='2024-04-02'),{'2024-03-28':[1.5]},financing_rate=.073)
    metrics = compute_metrics(r)
    assert metrics['total_transaction_cost'] == 0
    assert metrics['financing_cost'] == pytest.approx(.1)
    assert metrics['total_cost'] == pytest.approx(.1)


@pytest.mark.parametrize('field,value', [
    ('cash_interest_rate',None),('cash_interest_rate',float('nan')),
    ('financing_rate',-1),('financing_rate',float('inf')),
    ('borrow_cost_bps_annual',-1),('borrow_cost_bps_annual',float('nan'))])
def test_bad_rates_fail_explicitly(field,value):
    with pytest.raises(ValueError,match='rate'):
        BacktestEngine(**{field:value})


@pytest.mark.parametrize('case',['duplicate','unknown_symbol','closed_day','bad_ratio','due_bill'])
def test_ambiguous_corporate_actions_are_rejected(case):
    from quantbot.backtest.market_mechanics import CorporateAction
    p = prices()
    event = CorporateAction('ETF','2024-04-02','split',2)
    events = [event]
    if case == 'duplicate': events.append(event)
    if case == 'unknown_symbol': events = [CorporateAction('OTHER','2024-04-02','split',2)]
    if case == 'closed_day': events = [CorporateAction('ETF','2024-03-29','split',2)]
    if case == 'bad_ratio': events = [CorporateAction('ETF','2024-04-02','split',0)]
    if case == 'due_bill': events = [CorporateAction('ETF','2024-04-02','special_dividend',2,'due_bill')]
    with pytest.raises(ValueError,match='[Aa]mbiguous|[Uu]nsupported'):
        run(p,{},price_mode='raw',corporate_actions=raw_book(p,events))


@pytest.mark.parametrize('execution',['next_open','next_close'])
def test_split_short_borrow_reconciles_and_flat_split_never_creates_holding(execution):
    from quantbot.backtest.market_mechanics import CorporateAction
    p = prices(end='2024-04-02')
    p['ETF'].loc['2024-04-02',['open','close']] = 50
    book = raw_book(p,[CorporateAction('ETF','2024-04-02','split',2)])
    r = run(p,{'2024-03-28':[-.5]},price_mode='raw',corporate_actions=book,
        borrow_cost_bps_annual=252,execution=execution)
    assert r.quantities.iloc[-1].ETF == -10
    assert r.borrow_cost == pytest.approx(.05)
    assert r.equity_curve.iloc[-1] == pytest.approx(999.95)
    assert run(p,{},price_mode='raw',corporate_actions=book).quantities.eq(0).all().all()


def test_next_close_borrowing_starts_after_entry_and_cash_accrues_before_entry():
    r = run(prices(end='2024-04-02'),{'2024-03-28':[1.5]},
        execution='next_close',financing_rate=.073)
    assert r.financing_costs.loc['2024-04-01'] == 0
    assert r.financing_costs.loc['2024-04-02'] == pytest.approx(.1)


def test_real_strategy_directional_targets_need_not_use_borrowed_cash(small_panel):
    from quantbot.strategies.s01_trend_following import S01TrendFollowing
    from quantbot.risk.risk_manager import RiskManager
    r = BacktestEngine(risk_manager=RiskManager({})).run(S01TrendFollowing({}),small_panel)
    assert r.cash.min() >= 0
    assert r.financing_cost == 0
    assert r.borrow_cost == 0


def test_result_records_exact_action_input_and_reverse_split():
    from quantbot.backtest.market_mechanics import CorporateAction
    p = prices()
    p['ETF'].loc['2024-04-02':,['open','close']] = 200
    book = raw_book(p,[CorporateAction('ETF','2024-04-02','split',.5)])
    r = run(p,{'2024-03-28':[.5]},price_mode='raw',corporate_actions=book)
    assert r.quantities.iloc[-1].ETF == 2.5
    assert r.equity_curve.iloc[-1] == 1000
    assert r.config['corporate_actions']['events'] == [dict(
        symbol='ETF',date='2024-04-02',kind='split',value=.5,convention='prior_close_ex_date_cash')]


def test_risk_receives_financing_and_dividend_in_current_net_return():
    class Capture:
        def __init__(self): self.observed = {}
        def process(self, weights, **kwargs):
            from quantbot.risk.risk_manager import RiskState
            self.observed[kwargs['portfolio_equity'].index[-1]] = kwargs['prev_day_return']
            return weights,RiskState()
    risk = Capture()
    r = run(prices(),{'2024-03-28':[1.5],'2024-04-02':[0]},financing_rate=.073,risk_manager=risk)
    assert risk.observed[pd.Timestamp('2024-04-02')] == pytest.approx(-.1/1000)
    assert risk.observed[pd.Timestamp('2024-04-02')] == r.returns.loc['2024-04-02']
