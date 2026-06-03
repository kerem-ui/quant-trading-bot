"""V5.0: contract_selector tests.

Verifies expiration/strike picking, liquidity gating, and bounded-strike
filters. All inputs are synthetic so the tests have no external dependency.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantbot.options import contract_selector as cs


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


def _chain(rows):
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
def test_select_expiration_picks_band_centre():
    rows = []
    # Expirations at DTE 10, 30, 35, 50 (band centre = 37.5)
    for dte in (10, 30, 35, 50):
        exp = pd.Timestamp("2022-01-03") + pd.Timedelta(days=dte)
        rows.append(_row("call", exp, 400, dte=dte))
    chain = _chain(rows)
    exp = cs.select_expiration(chain, dte_min=30, dte_max=45)
    assert exp == pd.Timestamp("2022-01-03") + pd.Timedelta(days=35)


def test_select_expiration_fallback_to_closest_when_band_empty():
    # No expirations in [30, 45], closest below band centre 37.5 is 25.
    rows = []
    for dte in (10, 25, 60):
        exp = pd.Timestamp("2022-01-03") + pd.Timedelta(days=dte)
        rows.append(_row("call", exp, 400, dte=dte))
    chain = _chain(rows)
    exp = cs.select_expiration(chain, dte_min=30, dte_max=45)
    assert exp == pd.Timestamp("2022-01-03") + pd.Timedelta(days=25)


def test_select_expiration_empty_returns_none():
    chain = pd.DataFrame(columns=["date", "expiration", "dte"])
    assert cs.select_expiration(chain, 30, 45) is None


# --------------------------------------------------------------------------- #
def test_select_by_delta_picks_closest_match():
    exp = pd.Timestamp("2022-02-04")
    rows = [_row("call", exp, k, delta=d, bid=1.0, ask=1.05, dte=32)
            for k, d in [(395, 0.60), (400, 0.50), (405, 0.40), (410, 0.30)]]
    chain = _chain(rows)
    row = cs.select_by_delta(chain, expiration=exp, option_type="call",
                              target_delta=0.50)
    assert row is not None
    assert row["strike"] == 400.0


def test_select_by_delta_skips_illiquid_zero_bid():
    exp = pd.Timestamp("2022-02-04")
    rows = [
        _row("call", exp, 400, delta=0.50, bid=0.0, ask=0.10),   # zero bid -> skip
        _row("call", exp, 410, delta=0.30, bid=0.50, ask=0.55),
    ]
    chain = _chain(rows)
    # Target 0.50 would prefer strike 400, but it is illiquid.
    row = cs.select_by_delta(chain, expiration=exp, option_type="call",
                              target_delta=0.50)
    assert row is not None
    assert row["strike"] == 410.0


def test_select_by_delta_respects_min_strike():
    exp = pd.Timestamp("2022-02-04")
    rows = [_row("call", exp, k, delta=d) for k, d in
            [(395, 0.60), (400, 0.50), (405, 0.40), (410, 0.30)]]
    chain = _chain(rows)
    row = cs.select_by_delta(chain, expiration=exp, option_type="call",
                              target_delta=0.50, min_strike=400.0)
    # 400 is excluded by strict >, so the next-best is 405.
    assert row is not None
    assert row["strike"] == 405.0


def test_select_by_delta_drops_nan_delta():
    exp = pd.Timestamp("2022-02-04")
    rows = [
        _row("call", exp, 400, delta=np.nan),
        _row("call", exp, 405, delta=0.45),
    ]
    chain = _chain(rows)
    row = cs.select_by_delta(chain, expiration=exp, option_type="call",
                              target_delta=0.50)
    assert row is not None
    assert row["strike"] == 405.0


# --------------------------------------------------------------------------- #
def test_lookup_row_finds_exact_strike():
    exp = pd.Timestamp("2022-02-04")
    rows = [_row("call", exp, 400), _row("call", exp, 405),
            _row("put", exp, 400)]
    chain = _chain(rows)
    row = cs.lookup_row(chain, expiration=exp, option_type="call", strike=405)
    assert row is not None
    assert row["strike"] == 405.0
    miss = cs.lookup_row(chain, expiration=exp, option_type="call", strike=999)
    assert miss is None
