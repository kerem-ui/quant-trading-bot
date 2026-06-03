"""Walk-forward and robustness tooling.

The goal is robustness, NOT finding a single best parameter. These helpers
make it easy to check that performance is stable across time splits and across
cost/parameter assumptions.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product

import pandas as pd

from ..costs.slippage import SlippageModel
from ..costs.transaction_costs import EquityCostModel
from .engine import BacktestEngine
from .performance import compute_metrics


@dataclass
class WalkForwardWindow:
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp


def make_walk_forward_windows(
    index: pd.DatetimeIndex, n_splits: int = 4, train_frac: float = 0.6
) -> list[WalkForwardWindow]:
    """Sequential (non-overlapping test) walk-forward windows."""
    index = index.sort_values()
    n = len(index)
    if n < 100 or n_splits < 1:
        return []
    fold = n // (n_splits + 1)
    windows = []
    for k in range(n_splits):
        tr_s = 0
        tr_e = fold * (k + 1)
        te_s = tr_e + 1
        te_e = min(tr_e + fold, n - 1)
        if te_s >= n:
            break
        windows.append(
            WalkForwardWindow(
                index[tr_s], index[tr_e], index[te_s], index[te_e]
            )
        )
    return windows


def slice_panel(
    panel: dict[str, pd.DataFrame], start: pd.Timestamp, end: pd.Timestamp
) -> dict[str, pd.DataFrame]:
    return {
        s: df.loc[(df.index >= start) & (df.index <= end)] for s, df in panel.items()
    }


def cost_sensitivity(
    strategy_factory,
    panel: dict[str, pd.DataFrame],
    risk_manager,
    cost_bps_grid=(0.0, 1.0, 3.0, 5.0, 10.0),
    sector_map: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Re-run the backtest across a grid of round-trip cost assumptions.

    ``cost_bps_grid`` values are applied as the slippage fixed-bps component.
    Returns a tidy DataFrame so cost robustness is easy to eyeball.
    """
    rows = []
    for bps in cost_bps_grid:
        cm = EquityCostModel(
            commission_bps=1.0,
            half_spread_bps=2.0,
            slippage=SlippageModel(fixed_bps=bps),
        )
        eng = BacktestEngine(cost_model=cm, risk_manager=risk_manager)
        res = eng.run(strategy_factory(), panel, sector_map=sector_map)
        m = compute_metrics(res)
        rows.append(
            {
                "slippage_bps": bps,
                "cagr": m["cagr"],
                "sharpe": m["sharpe"],
                "max_drawdown": m["max_drawdown"],
                "annual_turnover": m["annual_turnover"],
                "total_cost": m["total_transaction_cost"],
            }
        )
    return pd.DataFrame(rows)


def parameter_grid(param_space: dict[str, list]) -> list[dict]:
    """Cartesian product of a parameter space -> list of param dicts."""
    keys = list(param_space)
    return [dict(zip(keys, combo)) for combo in product(*param_space.values())]


def param_sensitivity(
    strategy_cls,
    base_config: dict,
    param_space: dict[str, list],
    panel: dict[str, pd.DataFrame],
    risk_manager,
    *,
    sector_map: dict[str, str] | None = None,
    engine_kwargs: dict | None = None,
) -> pd.DataFrame:
    """Run a strategy across a small parameter grid; return a tidy table.

    DISPLAY / ROBUSTNESS ONLY - this never selects a "best" parameter set and
    must not be used to overwrite defaults. It exists so reports can show that
    results are stable (or not) across reasonable parameter choices.
    """
    engine_kwargs = engine_kwargs or {}
    rows = []
    for combo in parameter_grid(param_space):
        cfg = {**base_config, **combo}
        strat = strategy_cls(cfg, sector_map=sector_map)
        res = BacktestEngine(risk_manager=risk_manager, **engine_kwargs).run(
            strat, panel, sector_map=sector_map
        )
        m = compute_metrics(res)
        row = {**combo,
               "cagr": m["cagr"], "sharpe": m["sharpe"],
               "max_drawdown": m["max_drawdown"],
               "annual_turnover": m["annual_turnover"],
               "total_cost": m["total_transaction_cost"],
               "avg_gross": m["avg_gross_exposure"]}
        rows.append(row)
    return pd.DataFrame(rows)


def walk_forward_run(
    strategy_factory,
    panel: dict[str, pd.DataFrame],
    risk_manager,
    n_splits: int = 4,
    sector_map: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Run the strategy on each walk-forward test window; report per-fold stats.

    Pair/factor selection inside strategies is already walk-forward; this adds
    an outer time-split so out-of-sample stability is visible.
    """
    any_df = next(iter(panel.values()))
    windows = make_walk_forward_windows(any_df.index, n_splits=n_splits)
    rows = []
    for k, w in enumerate(windows):
        test_panel = slice_panel(panel, w.train_start, w.test_end)
        eng = BacktestEngine(risk_manager=risk_manager)
        res = eng.run(strategy_factory(), test_panel, sector_map=sector_map)
        # Evaluate only the out-of-sample test segment.
        test_ret = res.returns.loc[
            (res.returns.index >= w.test_start) & (res.returns.index <= w.test_end)
        ]
        if test_ret.empty:
            continue
        from ..utils.math import annualize_return, annualize_vol
        rows.append(
            {
                "fold": k,
                "test_start": str(w.test_start.date()),
                "test_end": str(w.test_end.date()),
                "oos_cagr": annualize_return(test_ret),
                "oos_vol": annualize_vol(test_ret),
                "oos_total_return": float((1 + test_ret).prod() - 1),
            }
        )
    return pd.DataFrame(rows)
