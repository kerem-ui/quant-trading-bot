"""Hand-checkable execution mechanics; no downloaded market data."""
import numpy as np
import pandas as pd
import pytest

from quantbot.backtest.broker import SimulatedBroker
from quantbot.backtest.engine import BacktestEngine
from quantbot.backtest.order import Order, OrderStatus
from quantbot.costs.slippage import SlippageModel
from quantbot.costs.transaction_costs import EquityCostModel
from quantbot.risk.risk_manager import RiskManager
from quantbot.strategies.s03_pairs_mean_reversion import build_pair_orders
from quantbot.utils.market_calendar import USMarketCalendar


def panel():
    dates = USMarketCalendar().sessions('2024-01-02', '2024-04-10')
    return {s: pd.DataFrame(dict(open=p, high=p+1, low=p-1, close=p,
        adjusted_close=p, volume=1000.), index=dates) for s, p in [('A',100.),('B',40.)]}


def zero_cost():
    return EquityCostModel(0, 0, SlippageModel(0))


class Targets:
    rebalance_frequency = 'daily'

    def __init__(self, targets):
        self.targets = targets

    def target_weights(self, p):
        out = pd.DataFrame(np.nan, index=p['A'].index, columns=p)
        for i, weights in self.targets.items():
            out.iloc[i] = weights
        return out


def test_current_pair_does_not_ignore_beta():
    # Equal-price case already fails: old helper ignores beta entirely.
    w = build_pair_orders(1, 2., .01)
    assert w['b'] == pytest.approx(-2*w['a'])
    assert abs(w['a']) + abs(w['b']) == pytest.approx(.02)


@pytest.mark.parametrize('beta', [np.nan, np.inf, -1., 0.])
def test_invalid_beta_fails_explicitly(beta):
    with pytest.raises(ValueError, match='beta'):
        build_pair_orders(1, beta, .01)


def test_pair_prices_and_direction():
    for direction in (-1,1):
        w = build_pair_orders(direction, 2, .009, price_a=100, price_b=40)
        qa, qb = w['a']*10000/100, w['b']*10000/40
        assert (qa,qb) == pytest.approx((direction, -2*direction))
        assert qa*2 + qb*1 == pytest.approx(0)


def test_risk_caps_scale_whole_hedged_book():
    rm = RiskManager({'max_net_exposure':.001, 'max_single_symbol_weight':.009})
    w, _ = rm.process(pd.Series({'A':.01,'B':-.008}), preserve_ratios=True,
                      hedged=True)
    assert w.to_dict() == pytest.approx({'A':.005,'B':-.004})
    rm.validate_final(w)


def test_s02_ineligible_extreme_does_not_affect_scores(monkeypatch):
    import quantbot.strategies.s02_factor_blend as module
    p = panel()
    p['C'] = p['A'].copy()
    p['X'] = p['A'].copy()
    p['X']['volume'] = 0
    def factors(prices, volume):
        return {'momentum_3m':pd.DataFrame({s:float(i) for i,s in enumerate(prices.columns)}, index=prices.index)}
    monkeypatch.setattr(module, 'build_price_only_factors', factors)
    cfg = {'min_avg_dollar_volume':1, 'factor_weights_price_only':{'momentum_3m':1}}
    with_x = module.S02FactorBlend(cfg).generate_signals(p)
    without_x = module.S02FactorBlend(cfg).generate_signals({s:d for s,d in p.items() if s!='X'})
    pd.testing.assert_frame_equal(with_x[['A','B','C']], without_x)


def test_s01_atr_uses_adjusted_ohlc(monkeypatch):
    import quantbot.strategies.s01_trend_following as module
    p = panel()['A']
    p['adjusted_close'] = 50.
    observed = []
    def capture(df, window):
        observed.append(df.copy())
        return pd.Series(1., index=df.index)
    monkeypatch.setattr(module, 'atr', capture)
    module.S01TrendFollowing()._position_path(p)
    assert observed[0]['high'].iloc[0] == 50.5
    assert observed[0]['close'].iloc[0] == 50.


def test_cost_minimum_applies_to_commission_only():
    model = EquityCostModel(1,2,SlippageModel(3),min_commission=1)
    assert model.cost(1000) == pytest.approx(1.5)
    assert model.components(1000) == pytest.approx(dict(commission=1,spread=.2,slippage=.3,impact=0))


def test_capacity_uses_prior_session_not_future_volume():
    p = panel()
    p['A'].iloc[1,p['A'].columns.get_loc('volume')] = 1e9
    broker = SimulatedBroker(p,zero_cost(), max_participation=.01)
    o = Order('A',p['A'].index[0],p['A'].index[1],0,.5)
    broker.fill(o,10000)
    assert o.executed_quantity == 10
    assert o.execution_outcome == 'capacity_limited'
    assert o.notional == 1000


def test_delta_only_unchanged_resize_reverse_exit():
    p = panel()
    r = BacktestEngine(initial_capital=10000,cost_model=zero_cost()).run(
        Targets({0:[.1,0],1:[.1,0],2:[.05,0],3:[-.05,0],4:[0,0]}),p)
    assert [o.executed_quantity for o in r.orders] == pytest.approx([10,-5,-10,5])
    assert r.turnover_series.sum() == pytest.approx(.3)
    assert r.cash.iloc[-1] == 10000
    np.testing.assert_allclose(10000*(1+r.returns).cumprod(),r.equity_curve)


class PairTargets(Targets):
    hedged = True
    preserve_ratios = True

    def target_weights(self, p):
        result = super().target_weights(p)
        self.pair_targets = {p['A'].index[i]: [dict(a='A', b='B', beta=2., signal=1, gross=.018)]
                             for i in self.targets}
        return result


def test_pair_execution_preserves_beta_after_overnight_price_change():
    p = panel()
    p['A'].loc[p['A'].index[1]:, ['open','close','adjusted_close']] = 120.
    r = BacktestEngine(initial_capital=10000,cost_model=zero_cost(),risk_manager=RiskManager({})).run(
        PairTargets({0:[.01,-.008]}), p)
    assert r.quantities.iloc[1].to_dict() == pytest.approx({'A':.9,'B':-1.8})
    assert r.turnover_series.sum() == pytest.approx(.018)
    assert r.cash.iloc[-1] == pytest.approx(9964.)


def test_pair_missing_leg_entry_is_atomic():
    p = panel()
    p['B'].iloc[1,p['B'].columns.get_loc('open')] = np.nan
    r = BacktestEngine(initial_capital=10000,cost_model=zero_cost()).run(PairTargets({0:[.01,-.008]}),p)
    assert r.quantities.abs().sum().sum() == 0
    assert all(o.status == OrderStatus.REJECTED for o in r.orders)
    assert r.cash.iloc[-1] == 10000


def test_pair_capacity_rejects_entire_batch():
    p = panel()
    p['B']['volume'] = 1.
    r = BacktestEngine(initial_capital=10000,cost_model=zero_cost(),max_participation=.01).run(
        PairTargets({0:[.01,-.008]}),p)
    assert r.quantities.abs().sum().sum() == 0
    assert all(o.execution_outcome == 'rejected_atomic' for o in r.orders)
    assert r.total_cost == 0


class WeeklyTargets(Targets):
    rebalance_frequency = 'weekly'
    daily_exits = True


def test_daily_exit_does_not_wait_for_weekly_rebalance():
    p=panel()
    r=BacktestEngine(initial_capital=10000,cost_model=zero_cost()).run(
        WeeklyTargets({3:[.1,0],5:[0,0]}),p)
    assert r.quantities.iloc[4].A == 10
    assert r.quantities.iloc[6].A == 0


def test_daily_risk_reduction_does_not_wait_for_weekly_rebalance():
    p=panel()
    p['A'].loc[p['A'].index[5]:,['open','close','adjusted_close']]=90.
    rm=RiskManager({'max_daily_loss_reduce_risk':.005})
    r=BacktestEngine(initial_capital=10000,cost_model=zero_cost(),risk_manager=rm).run(
        WeeklyTargets({3:[.1,0]}),p)
    assert r.quantities.iloc[6].A == pytest.approx(5.)


@pytest.mark.parametrize('volume',[np.nan,0.,-1.,np.inf])
def test_invalid_liquidity_rejects_without_cash_cost(volume):
    p=panel(); p['A'].iloc[0,p['A'].columns.get_loc('volume')]=volume
    broker=SimulatedBroker(p,EquityCostModel(),max_participation=.01)
    o=Order('A',p['A'].index[0],p['A'].index[1],0,.1)
    broker.fill(o,10000)
    assert o.status == OrderStatus.REJECTED
    assert o.execution_outcome == 'rejected_liquidity'
    assert o.cost == o.executed_quantity == 0


def test_s01_split_like_input_invariance():
    from quantbot.indicators.volatility import adjusted_ohlc, atr
    p=panel()['A']; p['adjusted_close']=50.
    equivalent=p.copy()
    equivalent.loc[equivalent.index[30]:,['open','high','low','close']] /= 2
    pd.testing.assert_series_equal(atr(adjusted_ohlc(p)),atr(adjusted_ohlc(equivalent)))
    from quantbot.strategies.s01_trend_following import S01TrendFollowing
    pd.testing.assert_series_equal(S01TrendFollowing()._position_path(p),
                                   S01TrendFollowing()._position_path(equivalent))


def test_pair_zero_net_limit_rejects_non_neutral_allocation():
    rm=RiskManager({'max_net_exposure':0.})
    w,_=rm.process(pd.Series({'A':.01,'B':-.008}),hedged=True,preserve_ratios=True)
    assert w.abs().sum() == 0



def test_s02_incomplete_factor_history_is_ineligible_before_ranking(monkeypatch):
    import quantbot.strategies.s02_factor_blend as module
    p=panel(); p['X']=p['A'].copy()
    def factors(prices,volume):
        f=pd.DataFrame({s:float(i) for i,s in enumerate(prices.columns)},index=prices.index)
        g=f.copy()
        if 'X' in g: g['X']=np.nan
        return {'momentum_3m':f,'low_volatility':g}
    monkeypatch.setattr(module,'build_price_only_factors',factors)
    cfg={'min_avg_dollar_volume':1,'factor_weights_price_only':{'momentum_3m':.5,'low_volatility':.5}}
    actual=module.S02FactorBlend(cfg).generate_signals(p)[['A','B']]
    expected=module.S02FactorBlend(cfg).generate_signals({s:d for s,d in p.items() if s!='X'})
    pd.testing.assert_frame_equal(actual,expected)


def test_execution_cost_decomposition_reconciles_once():
    p=panel(); model=EquityCostModel(1,2,SlippageModel(3),min_commission=1)
    r=BacktestEngine(initial_capital=10000,cost_model=model).run(Targets({0:[.1,0]}),p)
    o=r.orders[0]
    assert o.fill_price == 100
    assert o.executed_quantity == 10
    assert o.cost_components == pytest.approx({'commission':1.,'spread':.2,'slippage':.3,'impact':0.})
    assert r.cash.iloc[-1] == 8998.5
    assert r.equity_curve.iloc[-1] == 9998.5
    assert r.total_cost == 1.5
    assert r.turnover_series.sum() == .1
    for event in r.ledger:
        assert event['equity'] == pytest.approx(event['cash']+sum(q*event['marks'][s] for s,q in event['quantities'].items()))


def test_pair_market_pnl_reconciles_through_executed_ledger():
    p=panel()
    for s,price in [('A',102.),('B',41.)]:
        p[s].loc[p[s].index[2]:,['open','close','adjusted_close']]=price
    r=BacktestEngine(initial_capital=10000,cost_model=zero_cost()).run(PairTargets({0:[.01,-.008]}),p)
    assert r.quantities.iloc[-1].to_dict() == pytest.approx({'A':1.,'B':-2.})
    assert r.gross_pnl.sum().to_dict() == pytest.approx({'A':2.,'B':-2.})
    assert r.cash.iloc[-1] == 9980
    assert r.equity_curve.iloc[-1] == 10000


def test_pair_exit_failure_keeps_both_legs_and_deducts_no_cost():
    class ExitPair(PairTargets):
        def target_weights(self,p):
            out=super().target_weights(p)
            self.pair_targets[p['A'].index[2]]=[]
            return out
    p=panel(); p['B'].iloc[2,p['B'].columns.get_loc('volume')]=np.nan
    r=BacktestEngine(initial_capital=10000,cost_model=zero_cost(),max_participation=.1).run(ExitPair({0:[.01,-.008]}),p)
    assert r.quantities.iloc[3].to_dict() == pytest.approx({'A':1.,'B':-2.})
    assert r.orders[-1].status == OrderStatus.REJECTED
    assert r.orders[-2].status == OrderStatus.REJECTED
    assert r.cash.iloc[-1] == 9980


@pytest.mark.parametrize('config',[
    {'max_single_symbol_weight':.005}, {'max_gross_exposure':.009},
    {'max_asset_class_weight':.009}, {'max_net_exposure':.001}])
def test_all_pair_caps_preserve_quantities(config):
    rm=RiskManager(config)
    r=BacktestEngine(initial_capital=10000,cost_model=zero_cost(),risk_manager=rm).run(
        PairTargets({0:[.01,-.008]}),panel())
    q=r.quantities.iloc[1]
    assert q.B == pytest.approx(-2*q.A)
    rm.validate_final(r.weights.iloc[1])
    assert 0 < q.A <= .5+1e-12



def test_scheduled_rebalance_cannot_bypass_executed_minimum_hold():
    class ActualHold(WeeklyTargets):
        min_holding_days=10
        def execution_exit(self,symbol,date,df,entry,current):
            return current-entry >= self.min_holding_days
    p=panel()
    r=BacktestEngine(initial_capital=10000,cost_model=zero_cost()).run(
        ActualHold({3:[.1,0],8:[0,0]}),p)
    assert r.quantities.iloc[9].A == 10
    assert r.quantities.iloc[15].A == 0


def test_off_cycle_signal_cannot_create_entry():
    r=BacktestEngine(initial_capital=10000,cost_model=zero_cost()).run(
        WeeklyTargets({0:[.1,0]}),panel())
    assert not r.orders


def test_overlapping_pair_components_reconcile_to_net_holdings():
    class Overlap(PairTargets):
        def target_weights(self,p):
            out=super().target_weights(p)
            self.pair_targets[p['A'].index[0]].append(dict(a='B',b='C',beta=.5,signal=-1,gross=.012))
            return out
    p=panel();p['C']=p['A'].copy()
    r=BacktestEngine(initial_capital=10000,cost_model=zero_cost(),risk_manager=RiskManager({})).run(
        Overlap({0:[.01,-.016,.004]}),p)
    for event in r.ledger:
        if event['event']=='pair_batch' and event['accepted']:
            summed={s:0. for s in p}
            for spec in event['pairs']:
                assert spec['quantity_b'] == pytest.approx(-spec['beta']*spec['quantity_a'])
                summed[spec['a']] += spec['quantity_a']
                summed[spec['b']] += spec['quantity_b']
            assert summed == pytest.approx({s:event['quantities'].get(s,0.) for s in p})



def test_s01_fill_based_min_hold_soft_exit_and_hard_stop():
    from quantbot.strategies.s01_trend_following import S01TrendFollowing
    p=panel()['A']; s=S01TrendFollowing({'min_holding_days':10})
    s._execution_exit_inputs={'A':dict(soft=pd.Series(True,index=p.index),atr=pd.Series(1.,index=p.index))}
    assert not s.execution_exit('A',p.index[6],p,4,6)
    assert s.execution_exit('A',p.index[14],p,4,14)
    p.iloc[6,p.columns.get_loc('adjusted_close')]=90.
    assert s.execution_exit('A',p.index[6],p,4,6)


def test_pair_daily_exit_preserves_other_pair_quantities():
    class TwoPairs(PairTargets):
        def target_weights(self,p):
            out=super().target_weights(p)
            second=dict(a='B',b='C',beta=.5,signal=-1,gross=.012)
            self.pair_targets[p['A'].index[0]].append(second)
            self.pair_targets[p['A'].index[2]]=[second]
            return out
    p=panel();p['C']=p['A'].copy()
    r=BacktestEngine(initial_capital=10000,cost_model=zero_cost()).run(TwoPairs({0:[.01,-.016,.004]}),p)
    first=next(x for x in r.ledger if x['event']=='pair_batch' and x['accepted'])
    retained=first['pairs'][1]
    assert r.quantities.iloc[3].to_dict() == pytest.approx({'A':0.,'B':retained['quantity_a'],'C':retained['quantity_b']})


def test_pair_raw_units_are_explicitly_converted():
    from quantbot.backtest.market_mechanics import CorporateActionBook
    p=panel()
    p['A']['adjusted_close']=50.
    for df in p.values(): df.attrs['price_basis']='raw_unadjusted'
    book=CorporateActionBook((),tuple(p),p['A'].index[0],p['A'].index[-1],source='fixture',complete=True)
    r=BacktestEngine(initial_capital=10000,cost_model=zero_cost(),price_mode='raw',corporate_actions=book).run(
        PairTargets({0:[.01,-.008]}),p)
    q=r.quantities.iloc[1]
    assert q.B == pytest.approx(-2*(q.A/.5))
    assert sum(abs(q[s]*p[s]['close'].iloc[1]) for s in p)==pytest.approx(180.)


def test_execution_rechecks_net_cap_after_gap():
    p=panel();p['A'].loc[p['A'].index[1]:,['open','close','adjusted_close']]=200.
    rm=RiskManager({'max_net_exposure':.001})
    r=BacktestEngine(initial_capital=10000,cost_model=zero_cost(),risk_manager=rm).run(
        PairTargets({0:[.01,-.008]}),p)
    q=r.quantities.iloc[1]
    assert q.B == pytest.approx(-2*q.A)
    assert r.weights.iloc[1].sum() == pytest.approx(.001)


def test_capacity_adjusted_units_and_cost_scale_with_executed_notional():
    p=panel();p['A']['adjusted_close']=50.
    r=BacktestEngine(initial_capital=10000,cost_model=EquityCostModel(1,2,SlippageModel(3)),
                     max_participation=.01).run(Targets({0:[.5,0]}),p)
    o=r.orders[0]
    assert o.executed_quantity == 20
    assert o.notional == 1000
    assert o.cost == pytest.approx(.6)
    assert r.equity_curve.iloc[-1] == pytest.approx(9999.4)
    assert r.cash.iloc[-1] == pytest.approx(8999.4)
    assert r.turnover_series.sum() == .1



@pytest.mark.parametrize('kind',['missing_column','overflow'])
def test_unusable_liquidity_never_silently_removes_capacity_limit(kind):
    p=panel()
    if kind=='missing_column':
        p['A']=p['A'].drop(columns='volume')
    else:
        p['A']['volume']=1e308
    o=Order('A',p['A'].index[0],p['A'].index[1],0,.1)
    SimulatedBroker(p,zero_cost(),max_participation=.01).fill(o,10000)
    assert o.status == OrderStatus.REJECTED
    assert o.execution_outcome == 'rejected_liquidity'
    assert o.executed_quantity == o.cost == 0



def test_s01_exit_guard_uses_dates_for_later_starting_instrument():
    from quantbot.strategies.s01_trend_following import S01TrendFollowing
    p=panel()['A']; late=p.iloc[50:].copy(); s=S01TrendFollowing({'min_holding_days':10})
    s._execution_exit_inputs={'A':dict(soft=pd.Series(False,index=late.index),atr=pd.Series(1.,index=late.index))}
    assert not s.execution_exit('A',p.index[55],late,54,55)



def test_raw_split_does_not_rewrite_historical_pair_diagnostics():
    from quantbot.backtest.market_mechanics import CorporateActionBook,CorporateAction
    p=panel(); date=p['A'].index[2]
    p['A'].loc[date:,['open','high','low','close']]=50.
    for df in p.values(): df.attrs['price_basis']='raw_unadjusted'
    book=CorporateActionBook((CorporateAction('A',date,'split',2.),),tuple(p),
        p['A'].index[0],p['A'].index[-1],source='fixture',complete=True)
    r=BacktestEngine(initial_capital=10000,cost_model=zero_cost(),price_mode='raw',corporate_actions=book).run(
        PairTargets({0:[.01,-.008]}),p)
    entry=next(e for e in r.ledger if e['event']=='pair_batch')
    assert entry['pairs'][0]['quantity_a'] == pytest.approx(1.)
    assert entry['quantities']['A'] == pytest.approx(1.)
    assert r.quantities.iloc[-1].to_dict() == pytest.approx({'A':2.,'B':-2.})
    assert r.equity_curve.iloc[-1] == 10000



def test_rejected_liquidity_keeps_correct_pretrade_diagnostics():
    p=panel();p['A']['volume']=np.nan
    o=Order('A',p['A'].index[0],p['A'].index[1],.1,0.)
    SimulatedBroker(p,zero_cost(),max_participation=.01).fill(o,10000,current_quantity=10.)
    assert o.status == OrderStatus.REJECTED
    assert o.quantity_before == 10.
    assert o.allocation_equity == 10000
    assert o.intended_quantity == -10.
    assert o.executed_quantity == o.cost == 0.
