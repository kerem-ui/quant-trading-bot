"""Option payoff functions at expiry.

All accept a scalar or numpy array of underlying prices ``S`` and return payoff
in the same shape (per 1 unit / 1 contract-equivalent, multiplier applied by
the caller). Premiums are handled by the structure layer, not here - these are
pure terminal payoff shapes used for tests and scenario PnL.
"""

from __future__ import annotations

import numpy as np


def call_payoff(S, K: float):
    return np.maximum(np.asarray(S, dtype=float) - K, 0.0)


def put_payoff(S, K: float):
    return np.maximum(K - np.asarray(S, dtype=float), 0.0)


def long_call(S, K, premium=0.0):
    return call_payoff(S, K) - premium


def long_put(S, K, premium=0.0):
    return put_payoff(S, K) - premium


def vertical_spread_payoff(S, legs: list[dict]):
    """Generic multi-leg vertical payoff.

    ``legs``: list of {type: 'call'|'put', strike, qty} where qty>0 long,
    qty<0 short. Premiums excluded (structure layer adds net debit/credit).
    """
    S = np.asarray(S, dtype=float)
    total = np.zeros_like(S)
    for leg in legs:
        pay = call_payoff(S, leg["strike"]) if leg["type"] == "call" else put_payoff(S, leg["strike"])
        total = total + leg["qty"] * pay
    return total


def straddle_payoff(S, K: float):
    """Long straddle terminal payoff (call + put at same strike)."""
    return call_payoff(S, K) + put_payoff(S, K)


def strangle_payoff(S, K_put: float, K_call: float):
    """Long strangle terminal payoff (OTM put + OTM call)."""
    return put_payoff(S, K_put) + call_payoff(S, K_call)


def iron_condor_payoff(S, legs: list[dict]):
    """Iron condor = short put spread + short call spread.

    ``legs`` must contain the four legs with signed ``qty`` (short inner
    options qty=-1, long outer wings qty=+1).
    """
    return vertical_spread_payoff(S, legs)


def calendar_placeholder_payoff(S, K: float):
    """Calendars depend on forward vol/time, not a single expiry payoff.

    Returned as NaN to make explicit that a terminal-payoff diagram is not a
    valid representation of a calendar spread (handled approximately in
    structures.CalendarSpread)."""
    return np.full_like(np.asarray(S, dtype=float), np.nan)
