"""Deeper S02 factor attribution & robustness (READ-ONLY).

Nothing here mutates configs, defaults, or strategy logic. Every function
builds in-memory variant configs only to *measure* where S02's edge comes from
and whether it is robust. Judged against the V2.2 pre-registered criteria
(plateau, OOS stability, cost-robust, beats null).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..backtest.engine import BacktestEngine
from ..backtest.performance import compute_metrics
from ..backtest.walk_forward import cost_sensitivity, param_sensitivity, walk_forward_run
from ..config import load_risk_config, load_strategy_config
from ..risk.risk_manager import RiskManager
from ..strategies.s02_factor_blend import S02FactorBlend
from ..utils.math import TRADING_DAYS_PER_YEAR, annualize_return, annualize_vol

FACTORS = [
    "momentum_12m_ex_1m",
    "momentum_3m",
    "one_month_reversal",
    "low_volatility",
    "liquidity",
]


def _rm() -> RiskManager:
    return RiskManager(load_risk_config())


def _base_config() -> dict:
    cfg = load_strategy_config()["strategies"]["S02_factor_blend"]
    return dict(cfg)


def default_weights(base: dict | None = None) -> dict:
    base = base or _base_config()
    return dict(base.get(
        "factor_weights_price_only",
        {"momentum_12m_ex_1m": .45, "momentum_3m": .20, "one_month_reversal": .20,
         "low_volatility": .10, "liquidity": .05},
    ))


def run_s02_variant(
    panel: dict[str, pd.DataFrame],
    sector_map: dict[str, str],
    factor_weights: dict,
    *,
    base: dict | None = None,
    rebalance: str | None = None,
):
    """Run S02 with a given factor-weight vector (and optional rebalance).
    Returns the BacktestResult. Read-only - no defaults touched."""
    cfg = {**(base or _base_config()), "factor_weights_price_only": factor_weights}
    if rebalance:
        cfg["rebalance_frequency"] = rebalance
    return BacktestEngine(risk_manager=_rm()).run(
        S02FactorBlend(cfg, sector_map=sector_map), panel, sector_map=sector_map
    )


def isolated_sleeves(panel, sector_map, base: dict | None = None):
    """Per-factor standalone sleeve: metrics + daily returns.

    If every isolated sleeve is positive, the edge is in the *factors*, not the
    blend weights.
    """
    rows, rets = [], {}
    for f in FACTORS:
        res = run_s02_variant(panel, sector_map, {f: 1.0}, base=base)
        m = compute_metrics(res)
        rows.append({"factor": f, "cagr": m["cagr"], "sharpe": m["sharpe"],
                     "max_drawdown": m["max_drawdown"],
                     "annual_turnover": m["annual_turnover"]})
        rets[f] = res.returns.rename(f)
    return pd.DataFrame(rows).set_index("factor"), rets


def leave_one_out(panel, sector_map, base: dict | None = None):
    """Marginal contribution of each factor: drop it, renormalise, re-measure."""
    base = base or _base_config()
    bw = default_weights(base)
    blend = compute_metrics(run_s02_variant(panel, sector_map, bw, base=base))
    rows = []
    for f in FACTORS:
        w = {k: v for k, v in bw.items() if k != f}
        if not w:
            continue
        m = compute_metrics(run_s02_variant(panel, sector_map, w, base=base))
        rows.append({"dropped": f,
                     "sharpe": m["sharpe"],
                     "d_sharpe": m["sharpe"] - blend["sharpe"],
                     "d_cagr": m["cagr"] - blend["cagr"]})
    return pd.DataFrame(rows).set_index("dropped"), blend


def sleeve_return_correlation(sleeve_returns: dict[str, pd.Series]) -> pd.DataFrame:
    """Correlation matrix of the isolated-sleeve return streams (diversification
    diagnostic - low off-diagonal => factors are genuinely independent)."""
    df = pd.concat(sleeve_returns.values(), axis=1)
    df.columns = list(sleeve_returns)
    return df.corr()


def regime_conditional(strategy_returns: pd.Series, spy_returns: pd.Series) -> pd.DataFrame:
    """S02 performance conditioned on market regime (SPY up/down) and
    volatility regime (SPY 20d realized vol above/below its median)."""
    s, b = strategy_returns.align(spy_returns, join="inner")
    s, b = s.dropna(), b.dropna()
    s, b = s.align(b, join="inner")
    vol = b.rolling(20, min_periods=10).std()
    vmed = vol.median()
    regimes = {
        "SPY up days": b > 0,
        "SPY down days": b < 0,
        "high-vol regime": vol > vmed,
        "low-vol regime": vol <= vmed,
    }
    rows = []
    for name, mask in regimes.items():
        seg = s[mask.fillna(False)]
        if len(seg) < 20:
            continue
        rows.append({"regime": name, "n_days": int(len(seg)),
                     "ann_return": annualize_return(seg),
                     "ann_vol": annualize_vol(seg),
                     "hit_rate": float((seg > 0).mean())})
    return pd.DataFrame(rows).set_index("regime")


def null_comparison(panel, sector_map, base: dict | None = None, n_random: int = 24,
                    seed: int = 12345):
    """Equal-weight + random-weight ensemble null.

    Edge is robust (the factors, not the tuning) if equal-weight ~= default and
    the random ensemble is overwhelmingly Sharpe>0.
    """
    base = base or _base_config()
    bw = default_weights(base)
    default_sh = compute_metrics(run_s02_variant(panel, sector_map, bw, base=base))["sharpe"]
    eq = compute_metrics(run_s02_variant(
        panel, sector_map, {f: 1 / len(FACTORS) for f in FACTORS}, base=base))["sharpe"]
    rng = np.random.default_rng(seed)
    sh = []
    for _ in range(n_random):
        v = rng.random(len(FACTORS))
        sh.append(compute_metrics(run_s02_variant(
            panel, sector_map, dict(zip(FACTORS, v / v.sum())), base=base))["sharpe"])
    sh = np.array(sh)
    return {
        "default_sharpe": float(default_sh),
        "equal_weight_sharpe": float(eq),
        "random_mean": float(sh.mean()),
        "random_min": float(sh.min()),
        "random_max": float(sh.max()),
        "random_frac_positive": float((sh > 0).mean()),
        "default_percentile_in_random": float((sh < default_sh).mean()),
        "edge_is_robust": bool((sh > 0).mean() > 0.7 and eq > 0.4),
    }


def robustness_battery(panel, sector_map, base: dict | None = None):
    """Walk-forward + cost sensitivity + parameter (top_quantile / rebalance)
    sensitivity for the DEFAULT S02 blend. Display-only; nothing promoted."""
    base = base or _base_config()
    rm = _rm()

    def factory():
        return S02FactorBlend(base, sector_map=sector_map)

    wf = walk_forward_run(factory, panel, rm, n_splits=4, sector_map=sector_map)
    cs = cost_sensitivity(factory, panel, rm, sector_map=sector_map)
    ps = param_sensitivity(
        S02FactorBlend, base,
        {"rebalance_frequency": ["monthly", "quarterly"],
         "top_quantile_long": [0.20, 0.30, 0.40]},
        panel, rm, sector_map=sector_map,
    )
    return {"walk_forward": wf, "cost_sensitivity": cs, "param_sensitivity": ps}
