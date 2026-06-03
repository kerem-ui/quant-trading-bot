"""V3 S02 analytics tests (read-only reporting layer).

Key invariants:
  - per-symbol contribution reconstructs result.returns exactly,
  - risk contribution sums to annualized portfolio vol,
  - factor / regime / benchmark functions return well-formed structures,
  - no strategy defaults / broker / live / options touched.
"""

import numpy as np
import pandas as pd
import pytest

import quantbot
from quantbot.backtest.engine import BacktestEngine
from quantbot.backtest.performance import compute_metrics
from quantbot.reporting import s02_analytics as A
from quantbot.risk.risk_manager import RiskManager
from quantbot.strategies.s02_factor_blend import S02FactorBlend
from quantbot.utils.math import annualize_vol

SUBPERIODS = [("2013-2016", "2013-01-01", "2016-12-31"),
              ("2017-2020", "2017-01-01", "2020-12-31")]


def _run_s02(panel, sector_map):
    return BacktestEngine(risk_manager=RiskManager({})).run(
        S02FactorBlend({}, sector_map=sector_map), panel, sector_map=sector_map
    )


# --------------------------------------------------------------------------- #
# contribution reconciliation (the core correctness guarantee)
# --------------------------------------------------------------------------- #
def test_contribution_reconciles_to_returns(panel, sector_map):
    res = _run_s02(panel, sector_map)
    recon = A.contribution_frame(res, panel).sum(axis=1)
    diff = (recon - res.returns).abs()
    assert diff.max() < 1e-9


def test_etf_contribution_structure(panel, sector_map):
    res = _run_s02(panel, sector_map)
    ec = A.etf_contribution(res, panel)
    for col in ["total_contribution", "avg_weight_all_days",
                "avg_weight_when_held", "days_held", "annual_turnover"]:
        assert col in ec["summary"].columns
    assert len(ec["best"]) <= 5 and len(ec["worst"]) <= 5
    # sum of per-ETF contributions == arithmetic sum of portfolio returns
    assert ec["total_arithmetic_return"] == pytest.approx(
        float(res.returns.sum()), abs=1e-9)
    assert ec["yearly_by_etf"].shape[0] == ec["summary"].shape[0]


# --------------------------------------------------------------------------- #
# factor analysis
# --------------------------------------------------------------------------- #
def test_factor_analysis(small_panel, sector_map):
    fa = A.factor_analysis(small_panel, sector_map, SUBPERIODS, n_random=3)
    assert list(fa["sleeves"].index) == A.fa.FACTORS
    assert fa["correlation"].shape == (5, 5)
    assert list(fa["subperiod_stability"].columns) == [s[0] for s in SUBPERIODS]
    for k in ["default_sharpe", "equal_weight_sharpe", "edge_is_robust"]:
        assert k in fa["weight_sensitivity"]


# --------------------------------------------------------------------------- #
# regime analysis
# --------------------------------------------------------------------------- #
def test_regime_analysis(panel, sector_map):
    res = _run_s02(panel, sector_map)
    reg = A.regime_analysis(res, panel)
    for r in ["SPY bull (>200dma)", "SPY bear (<200dma)",
              "high-vol regime", "low-vol regime"]:
        assert r in reg["regimes"].index
    assert {"COVID 2020 (02-15..04-15)", "Full 2020", "Full 2022"}.issubset(
        reg["explicit"].index)
    assert "sharpe" in reg["regimes"].columns


# --------------------------------------------------------------------------- #
# risk analysis
# --------------------------------------------------------------------------- #
def test_risk_contribution_sums_to_vol(panel, sector_map):
    res = _run_s02(panel, sector_map)
    m = compute_metrics(res)
    ra = A.risk_analysis(res, panel, sector_map)
    rc = ra["risk_contribution_etf"]["ann_risk_contribution"].sum()
    assert rc == pytest.approx(m["annual_vol"], rel=1e-6, abs=1e-9)
    assert set(["peak", "trough", "depth"]).issubset(ra["drawdown_window"])
    assert not ra["exposure_by_bucket"].empty
    assert isinstance(ra["rolling_vol"], pd.Series)
    assert isinstance(ra["rolling_sharpe"], pd.Series)


# --------------------------------------------------------------------------- #
# benchmark analysis
# --------------------------------------------------------------------------- #
def test_equal_weight_basket(panel):
    b = A.equal_weight_basket_returns(panel)
    assert isinstance(b, pd.Series)
    assert b.notna().sum() > 100


def test_benchmark_analysis_table(panel, sector_map):
    res = _run_s02(panel, sector_map)
    shy = panel["TLT"]["adjusted_close"].pct_change()  # stand-in cash-like proxy
    shy.name = "CASHY"
    ba = A.benchmark_analysis(res, panel, extra_benchmarks={"CASHY": shy})
    assert "SPY_buyhold" in ba["table"].index
    assert "equal_weight_basket" in ba["table"].index
    assert "CASHY" in ba["table"].index
    for c in ["excess_cagr", "tracking_error", "beta_to_bench",
              "correlation", "information_ratio"]:
        assert c in ba["table"].columns


# --------------------------------------------------------------------------- #
# guardrails
# --------------------------------------------------------------------------- #
def test_guards_unchanged():
    assert quantbot.LIVE_TRADING_ENABLED is False
    # V3 must not have changed S01/S02/S03 numeric defaults.
    from quantbot.config import load_strategy_config, strategy_params
    sc = load_strategy_config()
    assert strategy_params("S02_factor_blend", sc)["max_weight_per_name_long_only"] == 0.04
    assert strategy_params("S01_trend_following", sc)["min_holding_days"] == 20
