"""V5.0: conservative fill model tests.

Fills NEVER use ``last``. Buys hit ASK, sells hit BID. Wide-spread or
zero-bid legs are rejected, and any rejected leg fails the whole structure
(no half-opened defined-risk spread).
"""

from __future__ import annotations

import pandas as pd
import pytest

from quantbot.options.fill_model import (
    StructureFillResult,
    close_leg,
    fill_leg,
    fill_structure,
)


def _row(bid, ask, *, strike=400.0, last=None):
    d = {
        "date": pd.Timestamp("2022-01-03"),
        "expiration": pd.Timestamp("2022-02-04"),
        "option_type": "call", "strike": float(strike),
        "bid": float(bid), "ask": float(ask),
        "mid": (bid + ask) / 2.0,
    }
    if last is not None:
        d["last"] = float(last)
    return pd.Series(d)


# --------------------------------------------------------------------------- #
def test_fill_leg_buy_takes_ask():
    fr = fill_leg(_row(1.00, 1.10), qty=+1)
    assert fr.accepted
    assert fr.side == "buy"
    assert fr.fill_price == 1.10


def test_fill_leg_sell_takes_bid():
    fr = fill_leg(_row(1.00, 1.10), qty=-1)
    assert fr.accepted
    assert fr.side == "sell"
    assert fr.fill_price == 1.00


def test_fill_leg_never_uses_last_price():
    # 'last' is wildly off but fill must come from bid/ask.
    row = _row(1.00, 1.10, last=99.99)
    fr_buy = fill_leg(row, qty=+1)
    fr_sell = fill_leg(row, qty=-1)
    assert fr_buy.fill_price == 1.10
    assert fr_sell.fill_price == 1.00


def test_fill_leg_rejects_zero_bid():
    fr = fill_leg(_row(0.00, 1.10), qty=+1)
    assert not fr.accepted
    assert "zero_bid" in fr.reject_reason


def test_fill_leg_rejects_wide_spread():
    # spread% = (5-1)/3 = 1.33 >> 0.25
    fr = fill_leg(_row(1.0, 5.0), qty=+1)
    assert not fr.accepted
    assert "spread_too_wide" in fr.reject_reason


# --------------------------------------------------------------------------- #
def test_fill_structure_net_cash_is_debit_for_long_spread():
    legs = [{"option_type": "call", "strike": 400, "qty": +1},
            {"option_type": "call", "strike": 405, "qty": -1}]
    rows = [_row(5.00, 5.10, strike=400), _row(2.00, 2.10, strike=405)]
    out = fill_structure(legs, rows)
    assert out.accepted
    # Pay 5.10 long, receive 2.00 short -> debit 3.10 -> net_cash = -310
    assert out.net_cash == pytest.approx(-(5.10 - 2.00) * 100)


def test_fill_structure_rejects_whole_if_any_leg_fails():
    legs = [{"option_type": "call", "strike": 400, "qty": +1},
            {"option_type": "call", "strike": 405, "qty": -1}]
    rows = [_row(5.00, 5.10, strike=400),
            _row(0.00, 2.10, strike=405)]   # zero bid on short leg
    out = fill_structure(legs, rows)
    assert not out.accepted
    assert "leg_rejected" in out.reject_reason
    assert out.net_cash == 0.0


def test_fill_structure_charges_cost():
    legs = [{"option_type": "call", "strike": 400, "qty": +1},
            {"option_type": "call", "strike": 405, "qty": -1}]
    rows = [_row(5.00, 5.10, strike=400), _row(2.00, 2.10, strike=405)]
    out = fill_structure(legs, rows)
    assert out.accepted
    # Cost > 0 (per-contract fees + bid/ask fraction + multi-leg penalty).
    assert out.cost > 0


# --------------------------------------------------------------------------- #
def test_close_leg_inverts_side():
    # Held +1 long; close = sell at BID.
    fr = close_leg(_row(2.50, 2.60), qty_to_close=+1)
    assert fr.accepted
    assert fr.side == "sell"
    assert fr.fill_price == 2.50
    # Held -1 short; close = buy at ASK.
    fr2 = close_leg(_row(2.50, 2.60), qty_to_close=-1)
    assert fr2.accepted
    assert fr2.side == "buy"
    assert fr2.fill_price == 2.60
