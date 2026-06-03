"""V2.1 cleanup tests (safe-improvements scope only):

- engine cost split (trading + borrow == total)
- turnover attribution sums to annual turnover
- cost attribution (buy+sell == trading; borrow split)
- exposure diagnostics (active-day vs all-day) and S03 stays ~dollar-neutral
- benchmark now exposes absolute Sharpe for strat & bench
- quarterly rebalance support
- param_sensitivity is display-only (does not mutate base config / defaults)
- S01 conservative config applied; no broker / live trading
"""

import json

import numpy as np
import pandas as pd
import pytest

import quantbot
from quantbot.backtest.engine import BacktestEngine
from quantbot.backtest.walk_forward import param_sensitivity
from quantbot.config import load_strategy_config, strategy_params
from quantbot.reporting.benchmark import relative_metrics
from quantbot.risk.risk_manager import RiskManager
from quantbot.strategies.s01_trend_following import S01TrendFollowing
from quantbot.strategies.s02_factor_blend import S02FactorBlend
from quantbot.strategies.s03_pairs_mean_reversion import S03PairsMeanReversion
from quantbot.utils.dates import rebalance_dates


# --------------------------------------------------------------------------- #
# Engine cost split + attribution
# --------------------------------------------------------------------------- #
def test_cost_split_sums_to_total(panel, sector_map):
    res = BacktestEngine(
        risk_manager=RiskManager({}), borrow_cost_bps_annual=50.0
    ).run(
        S03PairsMeanReversion({"target_gross": 0.6, "max_active_pairs": 10},
                              sector_map=sector_map),
        panel, sector_map=sector_map,
    )
    assert res.trading_cost >= 0.0
    assert res.borrow_cost > 0.0  # S03 has a short leg -> borrow charged
    assert res.trading_cost + res.borrow_cost == pytest.approx(res.total_cost, rel=1e-9, abs=1e-6)


def test_turnover_attribution_sums_to_annual_turnover(small_panel):
    res = BacktestEngine(risk_manager=RiskManager({})).run(
        S01TrendFollowing({"min_holding_days": 20}), small_panel
    )
    ta = res.turnover_attribution()
    parts = ta["annual_entry"] + ta["annual_exit"] + ta["annual_resize"]
    assert parts == pytest.approx(res.annual_turnover, rel=1e-6, abs=1e-6)
    if ta["total_oneway"] > 0:
        assert ta["entry_pct"] + ta["exit_pct"] + ta["resize_pct"] == pytest.approx(1.0, abs=1e-6)


def test_cost_attribution_consistent(small_panel):
    res = BacktestEngine(risk_manager=RiskManager({})).run(
        S01TrendFollowing({}), small_panel
    )
    ca = res.cost_attribution()
    # buy + sell split must equal trading_cost; long-only -> no borrow.
    assert ca["trading_buy_cost"] + ca["trading_sell_cost"] == pytest.approx(
        ca["trading_cost"], rel=1e-9, abs=1e-6
    )
    assert ca["borrow_cost"] == pytest.approx(0.0, abs=1e-9)
    assert ca["total_cost"] == pytest.approx(res.total_cost, rel=1e-9, abs=1e-6)


# --------------------------------------------------------------------------- #
# Exposure diagnostics (active vs all-day) - the key S03 clarity fix
# --------------------------------------------------------------------------- #
def test_exposure_diagnostics_active_vs_all_day(panel, sector_map):
    res = BacktestEngine(
        risk_manager=RiskManager({}), borrow_cost_bps_annual=50.0
    ).run(
        S03PairsMeanReversion({"target_gross": 0.6, "max_active_pairs": 10},
                              sector_map=sector_map),
        panel, sector_map=sector_map,
    )
    ed = res.exposure_diagnostics()
    assert ed["n_days"] == len(res.weights)
    assert 0.0 <= ed["active_day_fraction"] <= 1.0
    assert ed["n_active_days"] <= ed["n_days"]
    if ed["n_active_days"]:
        # Active-day gross must exceed the (diluted) all-day average for an
        # opportunistic book - this is exactly the clarity V2.1 adds.
        assert ed["active_avg_gross"] >= ed["all_day_avg_gross"]
        # S03 still ~dollar-neutral on active days.
        assert ed["active_abs_net_over_gross"] < 0.20


# --------------------------------------------------------------------------- #
# Benchmark absolute metrics
# --------------------------------------------------------------------------- #
def test_relative_metrics_has_absolute_sharpe():
    idx = pd.bdate_range("2015-01-01", periods=400)
    rng = np.random.default_rng(1)
    s = pd.Series(rng.normal(0.0005, 0.01, 400), index=idx)
    b = pd.Series(rng.normal(0.0003, 0.012, 400), index=idx)
    m = relative_metrics(s, b)
    assert "strat_sharpe" in m and "bench_sharpe" in m
    same = relative_metrics(s, s)
    assert same["strat_sharpe"] == pytest.approx(same["bench_sharpe"], rel=1e-9)


# --------------------------------------------------------------------------- #
# Quarterly rebalance support
# --------------------------------------------------------------------------- #
def test_quarterly_rebalance_dates():
    idx = pd.bdate_range("2018-01-01", "2020-12-31")
    q = rebalance_dates(idx, "quarterly")
    m = rebalance_dates(idx, "monthly")
    assert len(q) > 0
    assert len(q) < len(m)              # fewer rebalances than monthly
    assert len(q) == pytest.approx(12, abs=1)  # ~4 per year over 3 years
    # Every quarterly date is an actual trading day in the index.
    assert set(q).issubset(set(idx))


# --------------------------------------------------------------------------- #
# param_sensitivity is display-only and non-mutating
# --------------------------------------------------------------------------- #
def test_param_sensitivity_display_only(small_panel, sector_map):
    base = {"rebalance_frequency": "monthly", "max_weight_per_name_long_only": 0.04}
    snapshot = dict(base)
    tbl = param_sensitivity(
        S02FactorBlend, base,
        {"rebalance_frequency": ["monthly", "quarterly"]},
        small_panel, RiskManager({}), sector_map=sector_map,
    )
    assert list(tbl["rebalance_frequency"]) == ["monthly", "quarterly"]
    assert {"cagr", "sharpe", "annual_turnover"}.issubset(tbl.columns)
    # Must NOT mutate the caller's base config (no silent default change).
    assert base == snapshot


# --------------------------------------------------------------------------- #
# Config / guardrails
# --------------------------------------------------------------------------- #
def test_s01_conservative_config_applied():
    p = strategy_params("S01_trend_following", load_strategy_config())
    assert p["min_holding_days"] == 20      # conservatively raised (was 10)
    assert p["cost_filter_multiplier"] == 4.0  # conservatively raised (was 3)
    assert p["rebalance_band"] == 0.02       # unchanged


def test_s02_default_still_monthly_benchmark():
    p = strategy_params("S02_factor_blend", load_strategy_config())
    # S02 default must remain the benchmark (unchanged by V2.1).
    assert p.get("rebalance_frequency", "monthly") == "monthly"
    assert p["max_weight_per_name_long_only"] == 0.04


def test_no_live_trading_or_broker():
    assert quantbot.LIVE_TRADING_ENABLED is False
