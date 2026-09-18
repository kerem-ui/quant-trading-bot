"""Independent model and explicit analytical representation acceptance tests."""
from datetime import date
from dataclasses import replace
import math
import numpy as np
import pandas as pd
import pytest
from scipy.integrate import quad
from quantbot.options.pricing import bs_price, price_bounds, solve_iv
from quantbot.options.greeks import bs_greeks
from quantbot.options.analytics import AnalyticsInputs, ContractMetadata, analyze_observation
from quantbot.options.surface import AnalyticalChain, fixed_tenor


@pytest.mark.parametrize('right', ['call', 'put'])
@pytest.mark.parametrize('S,K,T,r,q,sigma', [
    (100,100,1,.05,0,.2), (80,100,.5,0,.02,.3), (120,100,2,-.01,.03,.25),
    (100,100,1/365,0,0,.2), (100,100,3,.04,.02,.8),
    (100,100,.00001,0,0,.01), (100,100,1,0,0,.00001)])
def test_independent_lognormal_payoff_quadrature(right,S,K,T,r,q,sigma):
    # Integrate the discounted risk-neutral payoff, no d1/d2/CDF formula.
    drift=(r-q-.5*sigma**2)*T
    width=sigma*math.sqrt(T)
    z=(math.log(K/S)-drift)/width
    def payoff(x):
        st=S*math.exp(drift+width*x)
        return max(st-K if right=='call' else K-st,0)*math.exp(-x*x/2)/math.sqrt(2*math.pi)
    lo,hi=(max(-12,z),12) if right=='call' else (-12,min(12,z))
    expected=math.exp(-r*T)*quad(payoff,lo,hi,epsabs=1e-10)[0]
    assert bs_price(S,K,T,r,sigma,right,q)==pytest.approx(expected,abs=2e-8)
    c,p=[bs_price(S,K,T,r,sigma,opt,q) for opt in ('call','put')]
    assert c-p==pytest.approx(S*math.exp(-q*T)-K*math.exp(-r*T),abs=1e-11)
    lower,upper=price_bounds(S,K,T,r,right,q)
    assert lower <= bs_price(S,K,T,r,sigma,right,q) <= upper
    iv=solve_iv(bs_price(S,K,T,r,sigma,right,q),S,K,T,r,right,q,tol=1e-10)
    assert iv.status=='ok'
    assert bs_price(S,K,T,r,iv.volatility,right,q)==pytest.approx(expected,abs=2e-8)


@pytest.mark.parametrize('right',['call','put'])
@pytest.mark.parametrize('S,K,T,r,q,sigma',[(100,100,.5,.03,.01,.2),
    (80,100,2,0,.02,.3),(120,100,1/365,.05,0,.5)])
def test_all_greeks_match_finite_differences(right,S,K,T,r,q,sigma):
    def p(s=S,t=T,v=sigma,rate=r):return bs_price(s,K,t,rate,v,right,q)
    h=.001
    actual=bs_greeks(S,K,T,r,sigma,right,q)
    expected=dict(delta=(p(s=S+h)-p(s=S-h))/(2*h),
        gamma=(p(s=S+h)-2*p()+p(s=S-h))/h**2,
        theta=(p(t=T-1e-6)-p(t=T+1e-6))/(2e-6*365),
        vega=(p(v=sigma+1e-5)-p(v=sigma-1e-5))/(2e-5*100),
        rho=(p(rate=r+1e-5)-p(rate=r-1e-5))/(2e-5*100))
    for name in expected:
        assert actual[name]==pytest.approx(expected[name],rel=1e-4,abs=1e-7)


def contract(style='european',multiplier=100):
    return ContractMetadata('SPY',date(2022,2,2),100.,'call',style,'physical',multiplier,
                            'deterministic fixture')


def inputs(r=.03,q=.01):
    return AnalyticsInputs(date(2022,1,3),r,q,'explicit test rate','explicit test yield')


def observation():
    px=bs_price(100,100,30/365,.03,.2,q=.01)
    return dict(observation_date=date(2022,1,3),underlying='SPY',
        expiration=date(2022,2,2),strike=100.,right='call',bid=px-.01,ask=px+.01,
        underlying_price=100.,implied_volatility=.21,delta=None,gamma=.02,
        theta=-.03,vega=.1,rho=None,open_interest=None)


def test_contract_scaled_model_outputs_and_provider_separation():
    row=observation(); old=dict(row)
    out=analyze_observation(row,inputs(),contract(),quantity=-2)
    assert out['local_iv']==pytest.approx(.2,abs=1e-7)
    assert out['provider_iv']==.21 and out['provider_greeks']['delta'] is None
    assert out['local_greeks']['delta']>0
    assert out['position_greeks']['delta']==pytest.approx(-200*out['local_greeks']['delta'])
    assert out['local_position_value']==pytest.approx(-200*out['local_price'])
    assert out['open_interest'] is None and row==old


def test_american_is_labelled_and_does_not_invent_early_exercise():
    out=analyze_observation(observation(),inputs(),contract('american'))
    assert out['model_status']=='european_approximation_for_american'
    assert out['contract']['settlement_type']=='physical'


@pytest.mark.parametrize('r,q',[(None,.01),(.03,None),(None,None)])
def test_missing_assumptions_remain_missing(r,q):
    out=analyze_observation(observation(),inputs(r,q),contract())
    assert out['status']=='missing_rate_or_dividend_input'
    assert out['local_iv'] is None and out['local_greeks']['delta'] is None
    assert out['provider_iv']==.21


def test_date_and_contract_mismatch_rejected():
    with pytest.raises(ValueError,match='date'):
        analyze_observation(observation(),replace(inputs(),valuation_date=date(2022,1,4)),contract())
    with pytest.raises(ValueError,match='identity'):
        analyze_observation(observation(),inputs(),replace(contract(),underlying='QQQ'))


def test_quote_inversion_and_missing_provider_fields():
    row=observation()|{'ask':float('nan'),'implied_volatility':None}
    out=analyze_observation(row,inputs(),contract())
    assert out['status']=='invalid_quote' and out['local_iv'] is None
    assert out['provider_iv'] is None


def chain():
    rows=[]
    for dte,iv in [(10,.3),(30,.2)]:
        for right in ('call','put'):
            for strike,delta in [(95,.75),(100,.5),(105,.25)]:
                rows.append(observation()|dict(expiration=date(2022,1,3)+pd.Timedelta(days=dte),
                    strike=strike,right=right,delta=delta if right=='call' else delta-1,
                    implied_volatility=iv+(100-strike)*.001,open_interest=None))
    return pd.DataFrame(rows)


def test_chain_keeps_observations_and_missingness_separate():
    frame=chain(); frame.loc[0,'implied_volatility']=np.nan
    old=frame.copy(deep=True)
    view=AnalyticalChain(frame)
    assert view.observations['provider_iv'].isna().sum()==1
    assert view.observations['open_interest'].isna().all()
    assert 'local_iv' not in view.observations
    pd.testing.assert_frame_equal(old,frame)
    with pytest.raises(ValueError,match='duplicate'):
        AnalyticalChain(pd.concat([frame,frame.iloc[:1]]))


def test_chain_flags_bad_iv_and_quote_monotonicity_without_cleaning():
    frame=chain();frame.loc[0,'implied_volatility']=-.1
    frame.loc[2,['bid','ask']]=[99,100]
    view=AnalyticalChain(frame)
    assert len(view.observations)==len(frame)
    assert view.quality['invalid_iv']==1
    assert view.quality['strike_monotonicity_violations']>0


def test_atm_skew_selection_reports_observed_delta_and_no_extrapolation():
    view=AnalyticalChain(chain())
    out=view.skew(date(2022,1,13))
    assert out['atm_iv']==pytest.approx(.3)
    assert out['put_call_skew']==pytest.approx(.01)
    assert out['risk_reversal_call_minus_put']==pytest.approx(-.01)
    assert out['put_wing']['selected_delta']==-.25
    assert out['put_wing']['delta_distance']==0
    result=view.tenor(20)
    assert result['status']=='interpolated_total_variance'
    assert result['iv']==pytest.approx(math.sqrt((.3**2*10+.2**2*30)/2/20))
    assert result['bracket_dtes']==[10,30]
    assert view.tenor(60)['iv'] is None
    assert view.tenor(90)['status']=='insufficient_tenor_coverage'
    assert view.tenor(10)['status']=='observed'


def test_total_variance_decrease_is_flagged_not_smoothed_away():
    result=fixed_tenor([(10,.5),(30,.1)],20)
    assert result['iv'] is None and result['status']=='decreasing_total_variance'

def test_known_contract_terms_cannot_silently_disagree():
    row=observation()|{'multiplier':100,'exercise_style':'american'}
    with pytest.raises(ValueError,match='terms'):
        analyze_observation(row,inputs(),contract('european'))


def test_reused_contract_id_cannot_mask_distinct_contracts():
    c=chain();c['contract_id']='same-id'
    with pytest.raises(ValueError,match='identity'):
        AnalyticalChain(c)


def test_invalid_signed_delta_is_flagged():
    c=chain();c.loc[0,'delta']=-.5
    assert AnalyticalChain(c).quality['invalid_delta']==1

@pytest.mark.parametrize('right,S,expected',[('call',120,20),('put',80,20),('call',80,0),('put',120,0)])
def test_expiration_payoff_and_greek_convention(right,S,expected):
    assert bs_price(S,100,0,.10,0,right,.02)==expected
    g=bs_greeks(S,100,0,.10,.2,right,.02)
    assert math.isnan(g['theta'])
    assert g['delta']==(1. if right=='call' else -1.)*(expected>0)
    assert g['gamma']==g['vega']==g['rho']==0


def test_iv_configured_bounds_and_unidentifiable_floor():
    px=bs_price(100,100,.5,.02,.4)
    assert solve_iv(px,100,100,.5,.02,upper=.3).status=='outside_volatility_bracket'
    assert solve_iv(px,100,100,.5,.02,upper=1).volatility==pytest.approx(.4,abs=1e-8)
    assert solve_iv(bs_price(120,100,1,.05,0),120,100,1,.05).status=='boundary_unidentifiable'


def test_unknown_multiplier_cannot_become_one_contract():
    out=analyze_observation(observation(),inputs(),contract(multiplier=None))
    assert out['local_iv'] is not None
    assert out['local_position_value'] is None
    assert all(v is None for v in out['position_greeks'].values())


def test_missing_yield_source_and_naive_timestamp_rejected():
    from datetime import datetime
    with pytest.raises(ValueError,match='source'):
        AnalyticsInputs(date(2022,1,3),.03,.0,'supplied','')
    with pytest.raises(ValueError,match='timezone'):
        replace(inputs(),valuation_timestamp=datetime(2022,1,3))


def test_zero_vol_discounted_greeks_agree_with_deterministic_price_derivatives():
    for right,S in [('call',120),('put',80)]:
        r,q,T=.05,.02,1.
        g=bs_greeks(S,100,T,r,0,right,q)
        p=lambda s,t,rate:bs_price(s,100,t,rate,0,right,q)
        assert g['delta']==pytest.approx((p(S+.001,T,r)-p(S-.001,T,r))/.002)
        assert g['theta']==pytest.approx((p(S,T-1e-5,r)-p(S,T+1e-5,r))/(2e-5*365))
        assert g['rho']==pytest.approx((p(S,T,r+1e-5)-p(S,T,r-1e-5))/(2e-5*100))

def test_chain_reports_missing_greeks_without_zero_substitution():
    c=chain();c['gamma']=np.nan
    out=AnalyticalChain(c)
    assert out.quality['missing_greeks']['gamma']==len(c)
    assert out.observations['provider_gamma'].isna().all()
