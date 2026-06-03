"""Spec test 7: options payoff functions match known shapes; defined risk."""

import numpy as np
import pytest

from quantbot.options.payoff import (
    call_payoff,
    iron_condor_payoff,
    put_payoff,
    straddle_payoff,
    strangle_payoff,
)
from quantbot.options.pricing import bs_price, implied_vol
from quantbot.options.structures import IronCondor, Straddle, VerticalSpread


def test_call_put_payoff_shapes():
    S = np.array([50.0, 90.0, 100.0, 110.0, 150.0])
    np.testing.assert_allclose(call_payoff(S, 100), [0, 0, 0, 10, 50])
    np.testing.assert_allclose(put_payoff(S, 100), [50, 10, 0, 0, 0])


def test_call_payoff_monotone_nonneg():
    S = np.linspace(0, 300, 100)
    c = call_payoff(S, 100)
    assert (c >= 0).all()
    assert (np.diff(c) >= -1e-9).all()  # non-decreasing in S


def test_straddle_v_shape():
    S = np.array([80.0, 100.0, 120.0])
    np.testing.assert_allclose(straddle_payoff(S, 100), [20, 0, 20])


def test_strangle_flat_between_strikes():
    S = np.array([85.0, 95.0, 100.0, 105.0, 120.0])
    pay = strangle_payoff(S, K_put=90, K_call=110)
    assert pay[1] == 0 and pay[2] == 0 and pay[3] == 0  # flat inside [90,110]
    assert pay[0] == 5 and pay[4] == 10


def test_iron_condor_defined_risk():
    legs = [
        {"type": "put", "strike": 90, "qty": 1},
        {"type": "put", "strike": 95, "qty": -1},
        {"type": "call", "strike": 105, "qty": -1},
        {"type": "call", "strike": 110, "qty": 1},
    ]
    S = np.linspace(0, 250, 600)
    pay = iron_condor_payoff(S, legs)
    # Wings cap the loss: payoff is bounded below (no -inf tail).
    assert np.isfinite(pay).all()
    assert pay.min() >= -5.0 - 1e-9  # max width 5 between 90/95 and 105/110


def test_vertical_spread_max_loss_is_finite_and_equals_debit():
    vs = VerticalSpread("call", 100, 110, long_price=4.0, short_price=1.5, spot=100)
    s = vs.summary()
    assert np.isfinite(s["max_loss"])
    assert s["max_loss"] == pytest.approx(-s["net_debit"], rel=1e-6)
    assert s["max_profit"] > 0


def test_straddle_breakevens_symmetric():
    st = Straddle(100, call_price=5.0, put_price=5.0, spot=100)
    bes = sorted(st.breakevens())
    assert len(bes) == 2
    assert bes[0] == pytest.approx(90, abs=0.5)
    assert bes[1] == pytest.approx(110, abs=0.5)


def test_iron_condor_structure_credit_and_loss():
    ic = IronCondor(
        90, 95, 105, 110,
        prices={"put_long": 0.5, "put_short": 1.2, "call_short": 1.1, "call_long": 0.4},
        spot=100,
    )
    s = ic.summary()
    assert s["net_credit"] > 0      # condor opens for a credit
    assert np.isfinite(s["max_loss"])
    assert s["max_loss"] < 0


def test_bs_price_parity_and_iv_roundtrip():
    c = bs_price(100, 100, 0.5, 0.02, 0.25, "call")
    p = bs_price(100, 100, 0.5, 0.02, 0.25, "put")
    lhs = c - p
    rhs = 100 - 100 * np.exp(-0.02 * 0.5)
    assert lhs == pytest.approx(rhs, abs=1e-6)
    assert implied_vol(c, 100, 100, 0.5, 0.02, "call") == pytest.approx(0.25, abs=1e-3)
