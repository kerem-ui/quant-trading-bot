"""Spec test 8: parity scanner uses bid/ask and does NOT flag false
opportunities once a cost buffer is applied."""

import pandas as pd
import pytest

from quantbot.costs.transaction_costs import OptionsCostModel
from quantbot.data.options_loader import synthetic_option_chain
from quantbot.options.parity import (
    put_call_parity_value,
    scan_box_spreads,
    scan_butterfly_convexity,
    scan_parity_violations,
)


def test_parity_value_zero_when_consistent():
    # Construct C, P that satisfy parity exactly: C - P = S - K e^{-rT}
    S, K, r, dte = 100.0, 100.0, 0.03, 30
    T = dte / 365
    synth = S - K * pow(2.718281828, -r * T)
    P = 3.0
    C = P + synth
    resid = put_call_parity_value(C, P, K, r, dte, S)
    assert abs(resid) < 1e-6


def test_consistent_chain_has_no_false_parity_flags():
    """A BS-consistent synthetic chain priced with a real bid/ask spread must
    NOT produce parity flags once worst-case costs + buffer are applied."""
    chain = synthetic_option_chain("SPY", 100.0, pd.Timestamp("2021-01-04"), seed=11)
    flags = scan_parity_violations(
        chain, underlying_price=100.0, rate=0.03,
        cost_model=OptionsCostModel(), safety_buffer=0.05,
    )
    assert flags.empty, f"false parity positives: {flags}"


def test_no_false_box_flags():
    chain = synthetic_option_chain("SPY", 100.0, pd.Timestamp("2021-01-04"), seed=5)
    box = scan_box_spreads(chain, rate=0.03, cost_model=OptionsCostModel())
    assert box.empty


def test_scanner_detects_injected_violation():
    """Sanity: if we corrupt a quote badly, the scanner SHOULD flag it
    (otherwise the test above would be vacuous)."""
    chain = synthetic_option_chain("SPY", 100.0, pd.Timestamp("2021-01-04"), seed=1)
    mask = (chain["option_type"] == "call") & (chain["strike"] == 100.0)
    # Make the call absurdly cheap -> conversion arbitrage appears.
    chain.loc[mask, ["bid", "ask", "mid"]] = 0.01
    flags = scan_parity_violations(
        chain, 100.0, rate=0.03, cost_model=OptionsCostModel(), safety_buffer=0.05
    )
    assert not flags.empty


def test_convexity_violation_flagged_as_bad_data():
    chain = synthetic_option_chain("SPY", 100.0, pd.Timestamp("2021-01-04"), seed=2)
    # Force a convexity break on the middle strike of a call triplet.
    calls = chain[chain["option_type"] == "call"].sort_values("strike")
    mid_strike = calls["strike"].iloc[len(calls) // 2]
    m = (chain["option_type"] == "call") & (chain["strike"] == mid_strike)
    chain.loc[m, ["bid", "ask"]] = [999.0, 1000.0]
    out = scan_butterfly_convexity(chain)
    assert not out.empty
    assert out["flag"].str.contains("CONVEXITY").any()
