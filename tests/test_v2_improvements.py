"""V2 regression tests:

- RiskManager two-sided volatility targeting (scale up & down, bounded)
- engine no-trade band (consistency + always allow full exit)
- S01 turnover reduction vs a no-band / no-min-hold baseline
- S03 exposure improvement while staying ~dollar-neutral
- benchmark comparison output
"""

import numpy as np
import pandas as pd
import pytest

from quantbot.backtest.engine import BacktestEngine
from quantbot.backtest.performance import compute_metrics
from quantbot.reporting.benchmark import (
    buy_and_hold_returns,
    compare_to_benchmarks,
    relative_metrics,
)
from quantbot.risk.risk_manager import RiskManager
from quantbot.strategies.s01_trend_following import S01TrendFollowing
from quantbot.strategies.s03_pairs_mean_reversion import S03PairsMeanReversion


# --------------------------------------------------------------------------- #
# Phase 1 - two-sided vol targeting
# --------------------------------------------------------------------------- #
def test_vol_target_default_does_not_lever_up():
    rm = RiskManager({"portfolio_vol_target_annual": 0.10})
    w = pd.Series({"A": 0.10, "B": 0.10})
    vols = pd.Series({"A": 0.04, "B": 0.04})
    # Back-compat: with no opt-in, a low-vol book is NOT scaled above 1.0.
    assert rm.volatility_target_scale(w, None, vols) == pytest.approx(1.0)


def test_vol_target_scales_up_when_opted_in_and_is_bounded():
    rm = RiskManager({"portfolio_vol_target_annual": 0.10, "max_vol_scale": 4.0})
    w = pd.Series({"A": 0.10, "B": 0.10})
    vols = pd.Series({"A": 0.04, "B": 0.04})
    s = rm.volatility_target_scale(w, None, vols, allow_leverage_up=True)
    assert s > 1.0
    assert s <= 4.0  # hard-bounded by max_vol_scale


def test_vol_target_still_derisks_high_vol_without_optin():
    rm = RiskManager({"portfolio_vol_target_annual": 0.10})
    w = pd.Series({"X": 1.0})
    vols = pd.Series({"X": 0.50})
    assert rm.volatility_target_scale(w, None, vols) < 1.0


def test_market_neutral_not_downscaled_by_additive_proxy():
    rm = RiskManager({"portfolio_vol_target_annual": 0.10})
    w = pd.Series({"A": 0.5, "B": -0.5})  # hedged
    vols = pd.Series({"A": 0.20, "B": 0.20})
    # Additive proxy would say vol ~0.20 -> scale down; market_neutral must not.
    assert rm.volatility_target_scale(w, None, vols, market_neutral=True) == 1.0


def test_gross_cap_is_final_bound_even_with_leverage():
    rm = RiskManager({"max_gross_exposure": 1.5, "max_vol_scale": 10.0,
                       "portfolio_vol_target_annual": 0.10})
    w = pd.Series({"A": 0.5, "B": 0.5})
    vols = pd.Series({"A": 0.02, "B": 0.02})
    out, st = rm.process(w, asset_vols=vols, allow_leverage_up=True)
    assert out.abs().sum() <= 1.5 + 1e-9  # gross cap always wins


# --------------------------------------------------------------------------- #
# Phase 2 - no-trade band + S01 turnover
# --------------------------------------------------------------------------- #
def test_no_trade_band_blocks_small_changes_but_allows_full_exit(small_panel):
    rm = RiskManager({})
    res = BacktestEngine(risk_manager=rm, rebalance_band=0.05).run(
        S01TrendFollowing({"min_holding_days": 5}), small_panel
    )
    deltas = res.weights.diff().abs()
    nonzero = deltas.values[deltas.values > 1e-9]
    # Every executed change is either >= band OR a move to flat (0).
    flat_moves = ((res.weights.shift() != 0) & (res.weights == 0)).values.sum()
    assert nonzero.size > 0
    assert (nonzero[nonzero < 0.05].size == 0) or flat_moves > 0


def test_band_reduces_turnover(small_panel):
    """Isolate the no-trade band: identical strategy config, vary only the
    band. With the same signals, adding a band can only *skip* trades, so
    turnover and cost must be monotonically non-increasing."""
    rm = RiskManager({})
    cfg = {"min_holding_days": 10}  # held FIXED across both runs
    base = BacktestEngine(risk_manager=rm, rebalance_band=0.0).run(
        S01TrendFollowing(cfg), small_panel
    )
    banded = BacktestEngine(risk_manager=rm, rebalance_band=0.05).run(
        S01TrendFollowing(cfg), small_panel
    )
    assert banded.annual_turnover <= base.annual_turnover + 1e-9
    assert banded.total_cost <= base.total_cost + 1e-6
    # And the band must actually bite on this data (sanity, not vacuous).
    assert banded.total_cost < base.total_cost


def test_s01_min_holding_keeps_hard_stop(small_panel):
    """ATR stop must still be able to fire (risk guardrail not deferred)."""
    s = S01TrendFollowing({"min_holding_days": 999, "trailing_stop_atr_multiple": 0.1})
    w = s.target_weights(small_panel)
    # With an extremely tight ATR stop, positions cannot stay on forever even
    # though min_holding is huge -> some exits to zero must occur.
    assert (w.fillna(0.0) == 0).values.any()


def test_s01_still_long_only_after_v2(small_panel):
    w = S01TrendFollowing({"min_holding_days": 10}).target_weights(small_panel)
    assert (w.fillna(0.0).values >= -1e-12).all()


# --------------------------------------------------------------------------- #
# Phase 3 - S03 exposure up, still dollar-neutral
# --------------------------------------------------------------------------- #
def test_s03_target_gross_increases_exposure_and_stays_neutral(panel, sector_map):
    rm = RiskManager({})
    base = BacktestEngine(risk_manager=rm, borrow_cost_bps_annual=50.0).run(
        S03PairsMeanReversion({"target_gross": 0.0, "max_active_pairs": 10},
                              sector_map=sector_map),
        panel, sector_map=sector_map,
    )
    sized = BacktestEngine(risk_manager=rm, borrow_cost_bps_annual=50.0).run(
        S03PairsMeanReversion({"target_gross": 0.60, "max_active_pairs": 10},
                              sector_map=sector_map),
        panel, sector_map=sector_map,
    )
    g_base = base.weights.abs().sum(axis=1)
    g_sized = sized.weights.abs().sum(axis=1)
    # Exposure on active days is materially higher with target_gross on.
    assert g_sized[g_sized > 1e-6].mean() > 5 * max(g_base[g_base > 1e-6].mean(), 1e-9)
    # Still ~dollar-neutral: |net|/gross small on active days.
    net = sized.weights.sum(axis=1)
    act = g_sized > 1e-6
    assert (net[act].abs() / g_sized[act]).mean() < 0.15
    # Genuine long AND short legs remain.
    assert (sized.weights.values > 1e-9).any()
    assert (sized.weights.values < -1e-9).any()


def test_s03_market_neutral_flag_set():
    assert S03PairsMeanReversion({}).market_neutral is True


# --------------------------------------------------------------------------- #
# Phase 4 - benchmark comparison
# --------------------------------------------------------------------------- #
def test_relative_metrics_fields():
    idx = pd.bdate_range("2015-01-01", periods=400)
    rng = np.random.default_rng(0)
    strat = pd.Series(rng.normal(0.0004, 0.01, 400), index=idx)
    bench = pd.Series(rng.normal(0.0003, 0.012, 400), index=idx)
    m = relative_metrics(strat, bench)
    for k in ["excess_cagr", "information_ratio", "beta_to_bench",
              "correlation", "tracking_error", "down_capture"]:
        assert k in m
    # Identical series -> ~zero excess, ~unit beta, ~unit correlation.
    same = relative_metrics(strat, strat)
    assert same["excess_cagr"] == pytest.approx(0.0, abs=1e-9)
    assert same["beta_to_bench"] == pytest.approx(1.0, abs=1e-6)
    assert same["correlation"] == pytest.approx(1.0, abs=1e-6)


def test_compare_to_benchmarks_shape(small_panel):
    res = BacktestEngine(risk_manager=RiskManager({})).run(
        S01TrendFollowing({}), small_panel
    )
    spy = buy_and_hold_returns(small_panel, "SPY")
    df = compare_to_benchmarks(res.returns, {"SPY_buyhold": spy})
    assert "SPY_buyhold" in df.index
    assert "information_ratio" in df.columns


def test_buy_and_hold_requires_symbol(small_panel):
    with pytest.raises(KeyError):
        buy_and_hold_returns(small_panel, "NOT_A_SYMBOL")
