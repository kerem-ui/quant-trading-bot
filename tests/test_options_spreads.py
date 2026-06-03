"""V5.0/V5.3: defined-risk spread builder tests.

Bull call (V5.0) + bear put (V5.3) + bull put (V5.3) -- all defined-risk;
the bull put is the credit variant. NO naked / unlimited-risk structures
are ever built; every test below asserts ``is_naked is False`` and bounded
max_loss / max_profit.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantbot.options.spreads import (
    build_bear_put_spread,
    build_bull_call_spread,
    build_bull_put_spread,
)


def _row(option_type, expiration, strike, *, bid=1.0, ask=1.05, delta=0.5,
         dte=30, underlying_price=400.0, date="2022-01-03"):
    return {
        "date": pd.Timestamp(date),
        "underlying": "SPY",
        "expiration": pd.Timestamp(expiration),
        "dte": int(dte),
        "option_type": option_type,
        "strike": float(strike),
        "bid": float(bid), "ask": float(ask),
        "mid": (bid + ask) / 2.0,
        "volume": 100, "open_interest": 1000,
        "implied_volatility": 0.2,
        "delta": float(delta), "gamma": 0.01,
        "theta": -0.05, "vega": 0.10,
        "underlying_price": float(underlying_price),
        "contract_multiplier": 100,
        "exercise_style": "american",
    }


def _build_chain(spot=400.0):
    """Two expirations, deltas decreasing with strike."""
    rows = []
    for dte in (32,):    # one good expiration in the band
        exp = pd.Timestamp("2022-01-03") + pd.Timedelta(days=dte)
        # Deltas tuned so long@0.50 -> strike 400, short@0.30 -> strike 405.
        deltas = {395: 0.65, 400: 0.50, 405: 0.30, 410: 0.20}
        bids = {395: 6.00, 400: 4.00, 405: 2.00, 410: 1.00}
        asks = {395: 6.10, 400: 4.10, 405: 2.10, 410: 1.10}
        for k in (395, 400, 405, 410):
            rows.append(_row("call", exp, k, bid=bids[k], ask=asks[k],
                              delta=deltas[k], dte=dte,
                              underlying_price=spot))
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
def test_bull_call_spread_happy_path():
    chain = _build_chain()
    cand = build_bull_call_spread(chain)
    assert not cand.reject_reason, cand.reject_reason
    assert cand.structure_name == "bull_call_spread"
    # Long strike < short strike, both calls.
    assert cand.legs[0]["option_type"] == "call"
    assert cand.legs[1]["option_type"] == "call"
    assert cand.legs[0]["strike"] < cand.legs[1]["strike"]
    # Long +1, short -1.
    assert cand.legs[0]["qty"] == +1
    assert cand.legs[1]["qty"] == -1


def test_bull_call_spread_is_defined_risk():
    chain = _build_chain()
    cand = build_bull_call_spread(chain)
    # max_loss <= 0 (bounded) and not naked.
    assert cand.max_loss <= 0
    assert cand.max_profit >= 0
    assert cand.is_naked is False
    # max_loss + max_profit == width*100 by definition of vertical.
    assert cand.width * 100 == pytest.approx(cand.max_profit + abs(cand.max_loss))


def test_bull_call_spread_pricing_consistent_with_fill():
    chain = _build_chain()
    cand = build_bull_call_spread(chain)
    # net_cash = - (long_ask - short_bid) * 100
    long_ask = float(chain.loc[chain["strike"] == 400, "ask"].iloc[0])
    short_bid = float(chain.loc[chain["strike"] == 405, "bid"].iloc[0])
    expected_net = -(long_ask - short_bid) * 100
    assert cand.net_cash == pytest.approx(expected_net)


def test_bull_call_spread_respects_max_width():
    """A tight max_width must force a narrower spread (here: only $5 allowed
    so even with a fat chain we never cross more than $5 of strikes)."""
    rows = []
    exp = pd.Timestamp("2022-02-04")
    # Long target ~ 0.50 -> 400; short target ~ 0.30 -> 415, but 415-400=15
    # > max_width 5. With a 5-wide cap the builder must pick the nearest
    # delta-0.30 strike INSIDE the band (here: 404, which is the only
    # strike strictly above 400 and strictly below 405).
    bids = {395: 6.00, 400: 4.00, 404: 2.40, 415: 0.50}
    asks = {395: 6.10, 400: 4.10, 404: 2.50, 415: 0.55}
    deltas = {395: 0.65, 400: 0.50, 404: 0.32, 415: 0.10}
    for k in (395, 400, 404, 415):
        rows.append(_row("call", exp, k, bid=bids[k], ask=asks[k],
                          delta=deltas[k], dte=32))
    chain = pd.DataFrame(rows)
    cand = build_bull_call_spread(chain, max_width=5.0)
    assert not cand.reject_reason, cand.reject_reason
    assert cand.width <= 5.0
    assert cand.legs[1]["strike"] == 404.0


def test_bull_call_spread_rejects_empty_chain():
    chain = pd.DataFrame(columns=["date", "expiration", "dte", "option_type",
                                    "strike", "bid", "ask", "mid", "delta",
                                    "underlying_price"])
    cand = build_bull_call_spread(chain)
    assert cand.reject_reason == "empty_chain"


def test_bull_call_spread_rejects_when_short_leg_missing():
    """Only one strike exists -> no valid short leg above the long."""
    exp = pd.Timestamp("2022-02-04")
    rows = [_row("call", exp, 400, bid=4.00, ask=4.10, delta=0.50, dte=32)]
    chain = pd.DataFrame(rows)
    cand = build_bull_call_spread(chain)
    assert cand.reject_reason == "no_short_leg"


# =========================================================================== #
# V5.3 bear put spread (debit, defined-risk)
# =========================================================================== #
def _put_chain(spot=400.0):
    """Put ladder with negative deltas decreasing in magnitude as strike
    drops -- ATM put delta ~ -0.50, OTM (lower-strike) put closer to 0.

    Strikes are chosen so that the default delta targets fall strictly
    INSIDE the (long_strike - max_width, long_strike) band, since both
    spread builders use strict ``>`` / ``<`` bounds for safety (a short
    leg exactly at long_strike or long_strike - max_width is excluded).
    """
    exp = pd.Timestamp("2022-02-04")
    deltas = {388: -0.15, 393: -0.30, 397: -0.38, 400: -0.50, 405: -0.65}
    bids = {388: 1.00, 393: 2.00, 397: 3.00, 400: 4.00, 405: 6.00}
    asks = {388: 1.10, 393: 2.10, 397: 3.10, 400: 4.10, 405: 6.10}
    rows = []
    for k in (388, 393, 397, 400, 405):
        rows.append(_row("put", exp, k, bid=bids[k], ask=asks[k],
                          delta=deltas[k], dte=32, underlying_price=spot))
    return pd.DataFrame(rows)


def test_bear_put_spread_happy_path():
    chain = _put_chain()
    cand = build_bear_put_spread(chain)
    assert not cand.reject_reason, cand.reject_reason
    assert cand.structure_name == "bear_put_spread"
    # Both legs are puts.
    assert cand.legs[0]["option_type"] == "put"
    assert cand.legs[1]["option_type"] == "put"
    # Long put is the HIGHER strike (closer to ATM), short is lower.
    assert cand.legs[0]["strike"] > cand.legs[1]["strike"]
    # Long +1, short -1.
    assert cand.legs[0]["qty"] == +1
    assert cand.legs[1]["qty"] == -1
    # Default delta targets (-0.50 / -0.30) pick 400 / 393 from this chain.
    assert cand.legs[0]["strike"] == 400.0
    assert cand.legs[1]["strike"] == 393.0


def test_bear_put_spread_is_defined_risk():
    chain = _put_chain()
    cand = build_bear_put_spread(chain)
    assert cand.max_loss <= 0
    assert cand.max_profit >= 0
    assert cand.is_naked is False
    # Vertical identity: max_loss + max_profit == width * 100.
    assert cand.width * 100 == pytest.approx(
        cand.max_profit + abs(cand.max_loss)
    )


def test_bear_put_spread_pricing_is_debit():
    chain = _put_chain()
    cand = build_bear_put_spread(chain)
    # Debit = long_ask - short_bid (per share); net_cash is signed negative.
    long_ask = float(chain.loc[chain["strike"] == 400, "ask"].iloc[0])
    short_bid = float(chain.loc[chain["strike"] == 393, "bid"].iloc[0])
    expected_net = -(long_ask - short_bid) * 100
    assert cand.net_cash == pytest.approx(expected_net)
    assert cand.net_cash < 0   # debit by construction


def test_bear_put_spread_respects_max_width():
    """Tight max_width forces a narrower spread; the short put is constrained
    to lie strictly above (long_strike - max_width) and below long_strike."""
    exp = pd.Timestamp("2022-02-04")
    deltas = {385: -0.15, 397: -0.32, 400: -0.50}
    bids = {385: 1.00, 397: 2.50, 400: 4.00}
    asks = {385: 1.10, 397: 2.60, 400: 4.10}
    rows = []
    for k in (385, 397, 400):
        rows.append(_row("put", exp, k, bid=bids[k], ask=asks[k],
                          delta=deltas[k], dte=32))
    chain = pd.DataFrame(rows)
    cand = build_bear_put_spread(chain, max_width=5.0)
    assert not cand.reject_reason, cand.reject_reason
    assert cand.width <= 5.0
    # 385 is excluded (15 wide); 397 is the only valid short leg in band.
    assert cand.legs[1]["strike"] == 397.0


def test_bear_put_spread_rejects_empty_chain():
    chain = pd.DataFrame(columns=["date", "expiration", "dte", "option_type",
                                    "strike", "bid", "ask", "mid", "delta",
                                    "underlying_price"])
    cand = build_bear_put_spread(chain)
    assert cand.reject_reason == "empty_chain"


def test_bear_put_spread_rejects_when_short_leg_missing():
    """Only an ATM put exists -> nothing strictly below to short."""
    exp = pd.Timestamp("2022-02-04")
    rows = [_row("put", exp, 400, bid=4.00, ask=4.10, delta=-0.50, dte=32)]
    chain = pd.DataFrame(rows)
    cand = build_bear_put_spread(chain)
    assert cand.reject_reason == "no_short_leg"


# =========================================================================== #
# V5.3 bull put spread (CREDIT, defined-risk)
# =========================================================================== #
def test_bull_put_spread_happy_path():
    chain = _put_chain()
    cand = build_bull_put_spread(chain)
    assert not cand.reject_reason, cand.reject_reason
    assert cand.structure_name == "bull_put_spread"
    # Both legs are puts.
    assert cand.legs[0]["option_type"] == "put"
    assert cand.legs[1]["option_type"] == "put"
    # Long (protective) put is at the LOWER strike; short is higher.
    assert cand.legs[0]["strike"] < cand.legs[1]["strike"]
    # Long +1, short -1.
    assert cand.legs[0]["qty"] == +1
    assert cand.legs[1]["qty"] == -1
    # Default delta targets (-0.30 / -0.15) pick short=393, long=388.
    assert cand.legs[0]["strike"] == 388.0
    assert cand.legs[1]["strike"] == 393.0


def test_bull_put_spread_is_defined_risk_and_NOT_naked():
    """The protective long-put wing is what makes this defined-risk; without
    it the structure would be naked-short-put (unbounded loss).  The builder
    must always include both legs and report ``is_naked is False``."""
    chain = _put_chain()
    cand = build_bull_put_spread(chain)
    assert cand.is_naked is False
    assert cand.max_loss <= 0
    assert cand.max_profit >= 0
    # Vertical identity for credit spread:
    #   max_profit (credit) + |max_loss| == width * 100
    assert cand.width * 100 == pytest.approx(
        cand.max_profit + abs(cand.max_loss)
    )
    # And there are exactly two legs with opposite signs.
    assert sum(L["qty"] for L in cand.legs) == 0


def test_bull_put_spread_pricing_is_credit():
    chain = _put_chain()
    cand = build_bull_put_spread(chain)
    # Credit = short_bid - long_ask (per share); net_cash is signed positive.
    short_bid = float(chain.loc[chain["strike"] == 393, "bid"].iloc[0])
    long_ask = float(chain.loc[chain["strike"] == 388, "ask"].iloc[0])
    expected_net = +(short_bid - long_ask) * 100
    assert cand.net_cash == pytest.approx(expected_net)
    assert cand.net_cash > 0   # credit by construction


def test_bull_put_spread_rejects_non_credit_pricing():
    """If the long wing is more expensive than the short (degenerate quotes),
    the structure is not a real credit spread; refuse to book it."""
    exp = pd.Timestamp("2022-02-04")
    # Short put strike 390 quoted at $0.01 bid; long put strike 385 quoted at
    # $5 ask. short_bid - long_ask = -4.99 -> non-credit; must reject.
    rows = [
        _row("put", exp, 385, bid=4.90, ask=5.00, delta=-0.15, dte=32),
        _row("put", exp, 390, bid=0.01, ask=0.02, delta=-0.30, dte=32),
    ]
    chain = pd.DataFrame(rows)
    cand = build_bull_put_spread(chain)
    # Either non_credit_pricing or zero_bid leg rejection is acceptable;
    # both are equally safe failure modes (we just must NOT open).
    assert cand.reject_reason != ""


def test_bull_put_spread_respects_max_width():
    """Tight max_width forces a narrower spread; the long wing must lie
    strictly above (short_strike - max_width) and below short_strike."""
    exp = pd.Timestamp("2022-02-04")
    deltas = {370: -0.05, 387: -0.16, 390: -0.30}
    bids = {370: 0.20, 387: 1.10, 390: 2.00}
    asks = {370: 0.25, 387: 1.20, 390: 2.10}
    rows = []
    for k in (370, 387, 390):
        rows.append(_row("put", exp, k, bid=bids[k], ask=asks[k],
                          delta=deltas[k], dte=32))
    chain = pd.DataFrame(rows)
    cand = build_bull_put_spread(chain, max_width=5.0)
    assert not cand.reject_reason, cand.reject_reason
    assert cand.width <= 5.0
    # 370 is excluded (20 wide); 387 is the only valid long leg in band.
    assert cand.legs[0]["strike"] == 387.0


def test_bull_put_spread_rejects_empty_chain():
    chain = pd.DataFrame(columns=["date", "expiration", "dte", "option_type",
                                    "strike", "bid", "ask", "mid", "delta",
                                    "underlying_price"])
    cand = build_bull_put_spread(chain)
    assert cand.reject_reason == "empty_chain"


def test_bull_put_spread_rejects_when_long_wing_missing():
    """No wing below the short -> would be naked; the builder must refuse."""
    exp = pd.Timestamp("2022-02-04")
    rows = [_row("put", exp, 390, bid=2.00, ask=2.10, delta=-0.30, dte=32)]
    chain = pd.DataFrame(rows)
    cand = build_bull_put_spread(chain)
    assert cand.reject_reason == "no_long_leg"
