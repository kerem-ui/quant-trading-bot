"""Phase 4A economic regressions, written before implementation."""
import math
import numpy as np
import pandas as pd
import pytest
from quantbot.options.pricing import bs_price, implied_vol
from quantbot.options.greeks import bs_greeks
from quantbot.options import features as F


def test_zero_vol_is_discounted_forward_payoff():
    assert bs_price(100, 100, 1, .05, 0) == pytest.approx(100 - 100 * math.exp(-.05))


def test_put_iv_below_spot_intrinsic_can_be_valid():
    px = bs_price(80, 100, 1, .10, .2, "put")
    assert px < 20
    assert implied_vol(px, 80, 100, 1, .10, "put") == pytest.approx(.2, abs=1e-5)


@pytest.mark.parametrize("price", [101., float("nan"), -1.])
def test_impossible_price_rejected(price):
    assert math.isnan(implied_vol(price, 100, 100, 1, 0))


def test_unbracketed_iv_not_upper_bound():
    px = bs_price(100, 100, 1, 0, 6.)
    assert math.isnan(implied_vol(px, 100, 100, 1, 0))


def test_iv_nonconvergence_is_not_an_estimate():
    px = bs_price(100, 100, 1, 0, .23)
    assert math.isnan(implied_vol(px, 100, 100, 1, 0, max_iter=1))


def test_zero_vol_itm_delta_not_zero():
    assert bs_greeks(120, 100, 1, .05, 0)["delta"] == pytest.approx(1.)


def test_expiry_kink_greeks_are_undefined():
    assert all(math.isnan(v) for v in bs_greeks(100, 100, 0, 0, .2).values())


def test_greeks_invalid_right_rejected():
    with pytest.raises(ValueError, match="option_type"):
        bs_greeks(100, 100, 1, 0, .2, "banana")


@pytest.mark.parametrize("S,K,T,sigma", [(-1, 100, 1, .2), (100, 0, 1, .2),
    (100, 100, -1, .2), (100, 100, 1, -.2), (np.nan, 100, 1, .2)])
def test_invalid_model_inputs_rejected(S, K, T, sigma):
    with pytest.raises(ValueError):
        bs_price(S, K, T, 0, sigma)


def small_chain():
    return pd.DataFrame([dict(date=pd.Timestamp("2022-01-03"), underlying="SPY",
        expiration=pd.Timestamp("2022-01-13"), dte=10, option_type="call", strike=100.,
        implied_volatility=.2, delta=.27, underlying_price=100.)])


def test_expiry_selection_does_not_silently_leave_band():
    assert np.isnan(F.iv_summary_for_date(small_chain())["atm_iv"])


def test_delta_selection_reports_actual_distance():
    out = F.iv_summary_for_date(small_chain(), target_dte=10, dte_band=(7, 14))
    assert out["iv_25d_call_selected_delta"] == pytest.approx(.27)
    assert out["iv_25d_call_delta_distance"] == pytest.approx(.02)


def test_invalid_iv_not_a_feature():
    chain = small_chain()
    chain["implied_volatility"] = -0.2
    assert np.isnan(F.iv_summary_for_date(chain, target_dte=10, dte_band=(7, 14))["atm_iv"])

def test_missing_position_greek_remains_unknown_and_cash_unchanged():
    from test_options_accounting_regressions import position, row, chain, D1
    pos=position()
    record=pos.mark(chain(row(delta=np.nan)),D1)
    assert math.isnan(record['delta'])
    assert record['mtm_close_cash']==200.
    assert record['paper_pnl']==pytest.approx(-21.)


def test_parity_european_filter_rejects_american_assumption():
    from quantbot.data.options_loader import synthetic_option_chain
    from quantbot.options.parity import scan_parity_violations
    c=synthetic_option_chain('SPY',100.,pd.Timestamp('2022-01-03'))
    c['exercise_style']='american'
    c.loc[(c['option_type']=='call') & (c['strike']==100),['bid','ask','mid']]=.01
    assert scan_parity_violations(c,100.).empty


def test_feature_summary_refuses_multiple_underlyings():
    c=small_chain()
    c=pd.concat([c,c.assign(underlying='QQQ')])
    with pytest.raises(ValueError,match='underlying'):
        F.iv_summary_for_date(c)


def test_feature_median_excludes_invalid_iv_and_reports_it():
    c=small_chain(); c['implied_volatility']=-.2
    out=F.iv_summary_for_date(c)
    assert np.isnan(out['median_iv_all'])
    assert out['invalid_iv_count']==1

def test_aggregate_missing_greek_is_unknown():
    from quantbot.risk.greeks import aggregate_structure_greeks
    class Incomplete:
        def net_greeks(self):return {'gamma':.1,'theta':-.1,'vega':1.}
        def max_loss(self):return -100.
    out=aggregate_structure_greeks([Incomplete()])
    assert math.isnan(out.delta)
    assert out.max_loss==100.

def test_legacy_surface_slice_rejects_duplicate_identities():
    from quantbot.options.chain import OptionsChain
    c=small_chain()
    c=pd.concat([c,c.assign(implied_volatility=.4)],ignore_index=True)
    with pytest.raises(ValueError,match='duplicate'):
        OptionsChain(c).surface_slice('2022-01-03')


def test_legacy_surface_slice_rejects_mixed_underlyings():
    from quantbot.options.chain import OptionsChain
    c=small_chain()
    c=pd.concat([c,c.assign(underlying='QQQ')],ignore_index=True)
    with pytest.raises(ValueError,match='underlying'):
        OptionsChain(c).surface_slice('2022-01-03')
