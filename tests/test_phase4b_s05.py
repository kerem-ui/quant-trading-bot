"""Approved S05 specification: economic regressions before implementation."""
from dataclasses import replace
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pytest
from quantbot.strategies.s05_implied_vs_realized_vol import (
    S05Parameters, S05ImpliedVsRealizedVol, build_condor, exit_decision,
)
from quantbot.options.s05_features import ewma_rv, iv_percentile, signal_eligible, build_signal_panel
from quantbot.options.backtest_engine import OptionsBacktestEngine
from quantbot.options.risk import OptionsRiskLimits
from quantbot.options.fill_model import fill_structure
from quantbot.utils.market_calendar import USMarketCalendar

P = S05Parameters()


def chain(day='2022-07-05', expiration='2022-08-05', credit=100., debit=None):
    """One $5-wide condor, finite quotes and observed ATM analytics."""
    rows=[]
    for right,strike,delta,bid,ask in [
        ('put',90,-.10,.45,.50),('put',95,-.20,1.,1.05),
        ('call',105,.20,1.,1.05),('call',110,.10,.45,.50),
        ('put',100,-.50,3.,3.10),('call',100,.50,3.,3.10)]:
        if strike in (95,105):
            bid=.5+credit/200; ask=bid+.05
            if debit is not None: ask=.45+debit/200;bid=ask-.02
        rows.append(dict(date=pd.Timestamp(day),underlying='SPY',expiration=pd.Timestamp(expiration),
            option_type=right,strike=float(strike),delta=delta,bid=bid,ask=ask,
            implied_volatility=.30,underlying_price=100.,contract_multiplier=100,
            gamma=.01,theta=-.02,vega=.1,rho=.03))
    return pd.DataFrame(rows)


def panel(days):
    return pd.DataFrame(dict(iv30=.30,rv=.20,percentile=.8,vrp=.10,signal=True,
        status='eligible',iv_count=126),index=pd.DatetimeIndex(days))


def test_rv_warmup_manual_recursion_and_causality():
    days=USMarketCalendar().sessions('2022-01-03','2022-03-01')
    prices=pd.Series(100*1.01**np.arange(len(days)),index=days)
    got=ewma_rv(prices,P)
    assert got.iloc[:20].isna().all()
    assert got.iloc[20]==pytest.approx(.01*np.sqrt(252))
    changed=prices.copy();changed.iloc[25:]*=2
    pd.testing.assert_series_equal(got.iloc[:25],ewma_rv(changed,P).iloc[:25])
    prices.iloc[21]=np.nan
    assert ewma_rv(prices,P).iloc[21:].isna().all()


def test_percentile_warmup_strict_ties_and_null_denominator():
    s=pd.Series([.2]*125+[.3,np.nan,.3])
    got=iv_percentile(s,P)
    assert got.iloc[:125].isna().all()
    assert got.iloc[125]==1
    assert np.isnan(got.iloc[126])
    assert got.iloc[127]==pytest.approx(125/126)


@pytest.mark.parametrize('iv,rv,pct,expected',[(.30,.20,.7,True),(.25,.20,.7,True),
    (.249,.20,.9,False),(.15,.20,.9,False),(.30,.20,.699,False),
    (np.nan,.20,.9,False),(.30,np.nan,.9,False)])
def test_signal_boundary(iv,rv,pct,expected):
    assert signal_eligible(iv,rv,pct,P)==expected


def test_condor_identity_selection_and_economics():
    c=build_condor(chain(),pd.Timestamp('2022-07-05'),'SPY',P)
    assert not c.reject_reason
    assert [(l['option_type'],l['strike'],l['qty']) for l in c.legs]==[
        ('put',90.,1),('put',95.,-1),('call',105.,-1),('call',110.,1)]
    assert c.width==5 and c.net_cash==pytest.approx(100)
    assert c.max_loss==pytest.approx(-400)
    assert all(l['underlying']=='SPY' and l['expiration']==pd.Timestamp('2022-08-05') for l in c.legs)


@pytest.mark.parametrize('kind',['nan','crossed','missing_wing','missing_delta'])
def test_atomic_candidate_rejection(kind):
    df=chain()
    if kind=='nan':df.loc[0,'ask']=np.nan
    if kind=='crossed':df.loc[0,'bid']=1
    if kind=='missing_wing':df=df.drop(0)
    if kind=='missing_delta':df.loc[1,'delta']=np.nan
    c=build_condor(df,pd.Timestamp('2022-07-05'),'SPY',P)
    assert c.reject_reason and not c.fill.accepted


@pytest.mark.parametrize('debit,reason',[(50.,'profit_credit'),(50.01,''),(199.99,''),(200.,'stop_credit')])
@pytest.mark.parametrize('fees',[0.,3.6,70.])
def test_exits_are_gross_credit_not_fee_sensitive(debit,reason,fees):
    pos=SimpleNamespace(expiration=pd.Timestamp('2022-08-05'),net_entry_cash=100.,open_cost=fees,
        legs=[SimpleNamespace(option_type='put',strike=95.,qty=-1),
              SimpleNamespace(option_type='call',strike=105.,qty=-1)])
    assert exit_decision(pos,pd.Timestamp('2022-07-05'),100.,debit,P)[1]==reason


def test_dte_strike_and_expiration_exit():
    pos=SimpleNamespace(expiration=pd.Timestamp('2022-08-05'),net_entry_cash=100.,
        legs=[SimpleNamespace(option_type='put',strike=95.,qty=-1),SimpleNamespace(option_type='call',strike=105.,qty=-1)])
    assert exit_decision(pos,pd.Timestamp('2022-07-15'),100.,120.,P)[1]=='dte_exit'
    assert exit_decision(pos,pd.Timestamp('2022-07-05'),95.,120.,P)[1]=='strike_breach'
    assert exit_decision(pos,pd.Timestamp('2022-08-05'),100.,None,P)[1]=='dte_exit'


def test_cash_risk_fee_budget_and_fill_recheck():
    c=build_condor(chain(),pd.Timestamp('2022-07-05'),'SPY',P)
    s=S05ImpliedVsRealizedVol('SPY',panel(['2022-07-05']),P)
    def decision(cash,equity,fill=c.fill):
        view=SimpleNamespace(cash=cash,equity=equity,open_positions=0,portfolio_defined_loss=0)
        return s.admit_execution(c,fill,pd.Timestamp('2022-07-06'),chain('2022-07-06'),view,100000)
    assert decision(100000,100000).accepted
    assert not decision(100000,40000).accepted # 407.20 > 1% * 40,000
    assert not decision(500,100000).accepted # reserve500+7.20 before credit
    assert not decision(100000,100000,replace(c.fill,net_cash=-1)).accepted
    assert not decision(100000,100000,replace(c.fill,net_cash=500)).accepted


def test_holiday_cadence_no_catchup():
    s=S05ImpliedVsRealizedVol('SPY',panel(['2022-07-05','2022-07-06']),P)
    view=SimpleNamespace(cash=100000,equity=100000,open_positions=0,portfolio_defined_loss=0)
    assert s.on_decision_open(pd.Timestamp('2022-07-05'),chain(),view) is not None
    assert s.on_decision_open(pd.Timestamp('2022-07-06'),chain('2022-07-06'),view) is None
    # Tuesday missing on a holiday week must not turn Wednesday into first session.
    s=S05ImpliedVsRealizedVol('SPY',panel(['2022-07-06']),P)
    assert s.on_decision_open(pd.Timestamp('2022-07-06'),chain('2022-07-06'),view) is None


def test_full_next_observation_roundtrip_and_balance_sheet():
    days=pd.to_datetime(['2022-07-05','2022-07-06','2022-07-07','2022-07-08'])
    df=pd.concat([chain(days[0]),chain(days[1]),chain(days[2],debit=50),chain(days[3],debit=40)])
    s=S05ImpliedVsRealizedVol('SPY',panel(days),P)
    result=OptionsBacktestEngine(df,s,limits=OptionsRiskLimits(spread_max_pct=.20)).run()
    assert len(result.trades)==1
    tr=result.trades[0]
    assert tr.decision_open==days[0] and tr.fill_open==days[1]
    assert tr.decision_close==days[2] and tr.fill_close==days[3]
    assert tr.close_reason=='profit_credit'
    assert tr.realized_pnl==pytest.approx(52.8)
    assert result.cash_curve.iloc[-1]==pytest.approx(100052.8)
    assert result.total_cost==pytest.approx(7.2)
    assert 100000*(1+result.daily_returns).prod()==pytest.approx(result.equity_curve.iloc[-1])
    for e in result.event_ledger:
        assert e['cash']+sum(l['qty']*l['multiplier']*l['mark_price'] for l in e['holdings'])==pytest.approx(e['equity'])


def test_missing_fill_leg_never_creates_position():
    days=pd.to_datetime(['2022-07-05','2022-07-06','2022-07-07'])
    df=pd.concat([chain(days[0]),chain(days[1]).drop(0),chain(days[2])])
    result=OptionsBacktestEngine(df,S05ImpliedVsRealizedVol('SPY',panel(days),P),limits=OptionsRiskLimits(spread_max_pct=.2)).run()
    assert not result.trades and not result.orders
    assert result.cash_curve.eq(100000).all()
    assert any(r.reason=='leg_missing_on_fill_day' for r in result.rejections)


def test_engine_enforces_s05_funding_hook():
    days=pd.to_datetime(['2022-07-05','2022-07-06','2022-07-07'])
    # Candidate fits decision-day equity, but tiny real account must not admit it.
    result=OptionsBacktestEngine(pd.concat([chain(d) for d in days]),
        S05ImpliedVsRealizedVol('SPY',panel(days),P),initial_capital=40000,
        limits=OptionsRiskLimits(spread_max_pct=.2)).run()
    assert not result.orders
    assert result.rejections

def test_actual_fill_risk_increase_is_rejected_before_booking():
    days=pd.to_datetime(['2022-07-05','2022-07-06','2022-07-07'])
    df=pd.concat([chain(days[0],credit=100),chain(days[1],credit=90),chain(days[2])])
    result=OptionsBacktestEngine(df,S05ImpliedVsRealizedVol('SPY',panel(days),P),
        initial_capital=41000,limits=OptionsRiskLimits(spread_max_pct=.2)).run()
    assert not result.orders, '407.20 decision loss fits 410; actual 417.20 must reject atomically'
    assert result.cash_curve.eq(41000).all()
    assert any(r.reason=='fee_inclusive_max_loss' for r in result.rejections)

def normalized(df):
    return df.rename(columns={'date':'observation_date','option_type':'right','contract_multiplier':'multiplier'})


def test_feature_panel_phase4a_tenor_warmup_and_truncation():
    days=USMarketCalendar().sessions('2022-01-03','2022-08-01')[:128]
    frames=[]
    for i,d in enumerate(days):
        c=chain(d,d+pd.Timedelta(days=30));c.implied_volatility=.20 if i<125 else .30
        frames.append(normalized(c))
    prices=pd.Series(100.,index=days)
    df=pd.concat(frames)
    out=build_signal_panel(df,prices,P)
    assert not out.signal.iloc[:125].any()
    assert out.signal.iloc[125]
    assert out.iv30.iloc[125]==pytest.approx(.30)
    assert out.percentile.iloc[125]==1.
    truncated=build_signal_panel(df[df.observation_date<=days[125]],prices.iloc[:126],P)
    pd.testing.assert_frame_equal(out.iloc[:126],truncated)


def test_no_extrapolation_and_missing_iv_are_explicit():
    d=pd.Timestamp('2022-07-05')
    c=normalized(chain(d,d+pd.Timedelta(days=29)))
    out=build_signal_panel(c,pd.Series([100.],index=[d]),P)
    assert out.iv30.isna().all() and not out.signal.any()
    c.expiration=d+pd.Timedelta(days=30);c.implied_volatility=np.nan
    assert build_signal_panel(c,pd.Series([100.],index=[d]),P).iv30.isna().all()


def test_fixed_tenor_interpolates_total_variance_not_iv():
    d=pd.Timestamp('2022-07-05')
    lo=normalized(chain(d,d+pd.Timedelta(days=20)));lo.implied_volatility=.2
    hi=normalized(chain(d,d+pd.Timedelta(days=40)));hi.implied_volatility=.3
    out=build_signal_panel(pd.concat([lo,hi]),pd.Series([100.],index=[d]),P)
    assert out.iv30.iloc[0]==pytest.approx(np.sqrt((.2**2*20+.3**2*40)/2/30))
    assert out.interpolated.iloc[0]


def test_selected_identity_does_not_change_to_improve_quotes():
    df=chain()
    # The mechanically nearest common wing is invalid, a wider one is valid.
    extra=df.iloc[[0,3]].copy();extra.loc[extra.option_type=='put','strike']=85
    extra.loc[extra.option_type=='call','strike']=115
    df.loc[0,'bid']=0
    assert build_condor(pd.concat([df,extra]),pd.Timestamp('2022-07-05'),'SPY',P).reject_reason


def test_earliest_expiry_and_delta_tie_lower_strike():
    df=chain();later=chain(expiration='2022-08-12')
    c=build_condor(pd.concat([df,later]),pd.Timestamp('2022-07-05'),'SPY',P)
    assert c.expiration==pd.Timestamp('2022-08-05')
    df.loc[1,'delta']=-.1875
    alternate=df.iloc[[1]].copy();alternate['strike']=96.;alternate['delta']=-.2125
    # The tie must keep95 and therefore the existing five-dollar wings.
    c=build_condor(pd.concat([df,alternate]),pd.Timestamp('2022-07-05'),'SPY',P)
    assert c.legs[1]['strike']==95


def test_terminal_and_expiration_cash_reconciliation():
    # Long gap is explicit next-observation data; expiry intrinsic needs exact day.
    days=pd.to_datetime(['2022-07-05','2022-07-06','2022-08-05'])
    result=OptionsBacktestEngine(pd.concat([chain(d) for d in days]),
        S05ImpliedVsRealizedVol('SPY',panel(days),P),limits=OptionsRiskLimits(spread_max_pct=.2)).run()
    assert result.trades[0].close_reason=='expiration'
    assert result.trades[0].realized_pnl==pytest.approx(96.4)
    assert result.cash_curve.iloc[-1]==pytest.approx(100096.4)
    ds=days[:2]
    result=OptionsBacktestEngine(pd.concat([chain(d) for d in ds]),
        S05ImpliedVsRealizedVol('SPY',panel(ds),P),limits=OptionsRiskLimits(spread_max_pct=.2)).run()
    assert result.trades[0].close_reason=='force_close_final_bar'
    assert result.trades[0].realized_pnl==pytest.approx(-27.2)


def test_missing_held_quote_aborts_without_phantom_equity():
    days=pd.to_datetime(['2022-07-05','2022-07-06','2022-07-07'])
    engine=OptionsBacktestEngine(pd.concat([chain(days[0]),chain(days[1]),chain(days[2]).drop(0)]),
        S05ImpliedVsRealizedVol('SPY',panel(days),P),limits=OptionsRiskLimits(spread_max_pct=.2))
    with pytest.raises(ValueError,match='required option mark'):engine.run()
    assert len(engine._open_positions)==1 and engine._cash==pytest.approx(100096.4)


def test_invalid_close_quote_does_not_trigger_fake_profit():
    from quantbot.options.position import BacktestPosition,BacktestLeg
    c=build_condor(chain(),pd.Timestamp('2022-07-05'),'SPY',P)
    legs=[BacktestLeg(l['option_type'],l['expiration'],l['strike'],l['qty'],r.fill_price,underlying='SPY') for l,r in zip(c.legs,c.fill.legs)]
    pos=BacktestPosition(c.structure_name,'SPY',pd.Timestamp('2022-07-01'),pd.Timestamp('2022-07-05'),c.expiration,legs,3.6,100,100,-400,5)
    df=chain(debit=40);df.loc[0,'bid']=0
    s=S05ImpliedVsRealizedVol('SPY',panel(['2022-07-05']),P)
    assert s.on_decision_close(pos,df,pd.Timestamp('2022-07-05'))==(False,'')
    assert s.exit_observations[-1]['liquidation_debit'] is None

@pytest.mark.parametrize('observed_debit,fill_debit,reason,pnl',[
    (50.,50.,'profit_credit',42.8),(200.,200.,'stop_credit',-107.2),
    (200.,250.,'stop_credit',-157.2)])
def test_gross_exit_boundary_net_cash_and_next_day_gap(observed_debit,fill_debit,reason,pnl):
    days=pd.to_datetime(['2022-07-05','2022-07-06','2022-07-07','2022-07-08'])
    df=pd.concat([chain(days[0]),chain(days[1]),chain(days[2],debit=observed_debit),chain(days[3],debit=fill_debit)])
    result=OptionsBacktestEngine(df,S05ImpliedVsRealizedVol('SPY',panel(days),P),
        limits=OptionsRiskLimits(spread_max_pct=.2)).run()
    assert result.trades[0].close_reason==reason
    assert result.trades[0].realized_pnl==pytest.approx(pnl)
    assert result.cash_curve.iloc[1]==pytest.approx(100096.4)
    assert result.equity_curve.iloc[1]==pytest.approx(99976.4)
    assert result.cash_curve.iloc[-1]==pytest.approx(100000+pnl)
    assert result.trades[0].fill_close==days[3]
    assert result.trades[0].net_exit_cash==pytest.approx(-fill_debit)