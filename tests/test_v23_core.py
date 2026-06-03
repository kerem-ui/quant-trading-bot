"""V2.3 tests: S02 core designation, factor attribution, and the opt-in
S01 conviction experiment (binary default must stay bit-identical)."""

import numpy as np
import pandas as pd
import pytest

import quantbot
from quantbot.backtest.engine import BacktestEngine
from quantbot.config import load_strategy_config, strategy_params
from quantbot.reporting import factor_attribution as fa
from quantbot.risk.risk_manager import RiskManager
from quantbot.strategies.s01_trend_following import (
    S01TrendFollowing,
    size_by_conviction,
    size_by_volatility,
)


# --------------------------------------------------------------------------- #
# Role metadata (non-numeric; behaviour-preserving)
# --------------------------------------------------------------------------- #
def test_strategy_roles():
    sc = load_strategy_config()
    assert strategy_params("S02_factor_blend", sc)["role"] == "core"
    assert strategy_params("S01_trend_following", sc)["role"] == "satellite_experimental"
    assert strategy_params("S03_pairs_mean_reversion", sc)["role"] == "research_only_no_alpha"


def test_numeric_defaults_unchanged():
    p = strategy_params("S01_trend_following", load_strategy_config())
    assert p["min_holding_days"] == 20
    assert p["cost_filter_multiplier"] == 4.0
    assert p["rebalance_band"] == 0.02
    assert p["lookbacks"] == [20, 60, 120]
    s2 = strategy_params("S02_factor_blend", load_strategy_config())
    assert s2.get("rebalance_frequency", "monthly") == "monthly"
    assert s2["max_weight_per_name_long_only"] == 0.04


# --------------------------------------------------------------------------- #
# S01 binary default is bit-identical (the critical guarantee)
# --------------------------------------------------------------------------- #
def test_s01_default_mode_is_binary():
    s = S01TrendFollowing({})
    assert s.execution_mode == "binary"


def test_binary_bit_identical_with_or_without_conviction_keys(small_panel):
    full = strategy_params("S01_trend_following", load_strategy_config())
    assert full.get("s01_execution_mode") == "binary"
    w_full = S01TrendFollowing(full).target_weights(small_panel).fillna(0.0)
    # Strip every s01_* opt-in key -> binary output must be unchanged.
    stripped = {k: v for k, v in full.items() if not k.startswith("s01_")}
    w_strip = S01TrendFollowing(stripped).target_weights(small_panel).fillna(0.0)
    np.testing.assert_allclose(w_full.values, w_strip.values, atol=1e-12)


# --------------------------------------------------------------------------- #
# S01 conviction mode behaviour
# --------------------------------------------------------------------------- #
def _conv_cfg():
    c = dict(strategy_params("S01_trend_following", load_strategy_config()))
    c["s01_execution_mode"] = "conviction"
    return c


def test_conviction_long_only_and_capped(small_panel):
    w = S01TrendFollowing(_conv_cfg()).target_weights(small_panel).fillna(0.0)
    assert (w.values >= -1e-12).all()                 # long-only
    assert w.values.max() <= 0.15 + 1e-9              # per-symbol cap intact


def test_conviction_produces_fractional_weights(small_panel):
    w = S01TrendFollowing(_conv_cfg()).target_weights(small_panel).fillna(0.0)
    v = w.values
    # genuinely continuous: some weights strictly between 0 and the cap
    assert ((v > 1e-6) & (v < 0.149)).any()


def test_conviction_differs_from_binary(small_panel):
    wb = S01TrendFollowing({}).target_weights(small_panel).fillna(0.0)
    wc = S01TrendFollowing(_conv_cfg()).target_weights(small_panel).fillna(0.0)
    common = wb.columns.intersection(wc.columns)
    assert not np.allclose(wb[common].values, wc[common].values)


def test_conviction_atr_hard_stop_still_fires(small_panel):
    cfg = _conv_cfg()
    cfg["min_holding_days"] = 999          # defer all soft exits
    cfg["trailing_stop_atr_multiple"] = 0.1  # extremely tight hard stop
    w = S01TrendFollowing(cfg).target_weights(small_panel).fillna(0.0)
    # Hard ATR stop must still force exits to flat despite huge min-hold.
    assert (w.values == 0).any()


def test_conviction_is_causal(small_panel):
    cfg = _conv_cfg()
    full = S01TrendFollowing(cfg).target_weights(small_panel)
    cut = 600
    part = S01TrendFollowing(cfg).target_weights(
        {k: v.iloc[: cut + 1] for k, v in small_panel.items()}
    )
    common = full.columns.intersection(part.columns)
    np.testing.assert_allclose(
        full[common].iloc[cut].fillna(0).values,
        part[common].iloc[cut].fillna(0).values,
        atol=1e-9,
        err_msg="conviction weight at t changed when future data added",
    )


def test_size_by_conviction_helper():
    idx = ["A", "B", "C"]
    vol = pd.Series([0.10, 0.10, 0.10], index=idx)
    full = size_by_conviction(pd.Series([1.0, 1.0, 1.0], index=idx), vol, 0.10, 0.15)
    binr = size_by_volatility(pd.Series([1, 1, 1], index=idx), vol, 0.10, 0.15)
    np.testing.assert_allclose(full.values, binr.values)          # conv=1 == binary size
    zero = size_by_conviction(pd.Series([0.0, 0.0, 0.0], index=idx), vol, 0.10, 0.15)
    assert (zero.values == 0).all()
    half = size_by_conviction(pd.Series([0.5, 0.5, 0.5], index=idx), vol, 0.10, 0.15)
    np.testing.assert_allclose(half.values, 0.5 * binr.values)
    # conviction is clipped to [0,1]
    cl = size_by_conviction(pd.Series([5.0], index=["A"]), pd.Series([0.10], index=["A"]),
                            0.10, 0.15)
    assert cl.iloc[0] == pytest.approx(0.15)


# --------------------------------------------------------------------------- #
# factor_attribution module (read-only)
# --------------------------------------------------------------------------- #
def test_factor_attribution_isolated_and_loo(small_panel, sector_map):
    iso, rets = fa.isolated_sleeves(small_panel, sector_map)
    assert list(iso.index) == fa.FACTORS
    assert {"cagr", "sharpe", "max_drawdown"}.issubset(iso.columns)
    assert set(rets) == set(fa.FACTORS)
    cm = fa.sleeve_return_correlation(rets)
    assert cm.shape == (5, 5)
    loo, blend = fa.leave_one_out(small_panel, sector_map)
    assert "sharpe" in loo.columns and "d_sharpe" in loo.columns
    assert "sharpe" in blend


def test_factor_attribution_null(small_panel, sector_map):
    nc = fa.null_comparison(small_panel, sector_map, n_random=4)
    for k in ["default_sharpe", "equal_weight_sharpe", "random_frac_positive",
              "edge_is_robust"]:
        assert k in nc


def test_regime_conditional(small_panel, sector_map):
    from quantbot.reporting.benchmark import buy_and_hold_returns
    res = fa.run_s02_variant(small_panel, sector_map, fa.default_weights())
    rc = fa.regime_conditional(res.returns, buy_and_hold_returns(small_panel, "SPY"))
    assert not rc.empty
    assert {"ann_return", "hit_rate"}.issubset(rc.columns)


# --------------------------------------------------------------------------- #
# Guardrails
# --------------------------------------------------------------------------- #
def test_no_live_or_broker():
    assert quantbot.LIVE_TRADING_ENABLED is False
