"""Spec test 4 (part): transaction cost model behaves correctly."""

import pytest

from quantbot.costs.slippage import SlippageModel
from quantbot.costs.transaction_costs import (
    EquityCostModel,
    OptionsCostModel,
    equity_cost_model_from_config,
)


def test_cost_scales_with_notional():
    cm = EquityCostModel(commission_bps=1, half_spread_bps=2,
                         slippage=SlippageModel(fixed_bps=2))
    c1 = cm.cost(10_000)
    c2 = cm.cost(20_000)
    assert c2 == pytest.approx(2 * c1)
    # 1+2+2 = 5 bps one-way
    assert c1 == pytest.approx(10_000 * 5 / 1e4)


def test_zero_trade_zero_cost():
    assert EquityCostModel().cost(0.0) == 0.0


def test_round_trip_is_double_one_way():
    cm = EquityCostModel()
    assert cm.round_trip_bps() == pytest.approx(2 * cm.one_way_bps())


def test_cost_filter_blocks_thin_edge():
    cm = EquityCostModel()  # round trip = 2*(1+2+2)=10 bps
    assert not cm.passes_cost_filter(expected_edge_bps=20, cost_multiplier=3.0)
    assert cm.passes_cost_filter(expected_edge_bps=40, cost_multiplier=3.0)


def test_slippage_market_impact_monotonic():
    sm = SlippageModel(fixed_bps=2.0, impact_coef_bps=10.0)
    assert sm.slippage_bps(0.0) == 2.0
    assert sm.slippage_bps(1.0) > sm.slippage_bps(0.25) > sm.slippage_bps(0.0)


def test_slippage_moves_price_against_trader():
    sm = SlippageModel(fixed_bps=10.0)
    buy = sm.adjust_fill_price(100.0, side=+1)
    sell = sm.adjust_fill_price(100.0, side=-1)
    assert buy > 100.0 > sell


def test_options_multi_leg_penalty():
    om = OptionsCostModel(per_contract_fee=0.65, bid_ask_fraction=0.5,
                          multi_leg_penalty=1.0)
    one = om.structure_cost([{"contracts": 1, "bid": 1.0, "ask": 1.2}])
    two = om.structure_cost(
        [{"contracts": 1, "bid": 1.0, "ask": 1.2},
         {"contracts": 1, "bid": 0.5, "ask": 0.7}]
    )
    assert two > one  # extra leg + multi-leg penalty


def test_from_config():
    cfg = {"global": {"default_commission_bps": 1.0, "default_slippage_bps": 2.0}}
    cm = equity_cost_model_from_config(cfg)
    assert cm.commission_bps == 1.0
