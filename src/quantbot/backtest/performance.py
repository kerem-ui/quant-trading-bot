"""Performance metrics computed from a BacktestResult.

Risk-free rate defaults to 0 (research convention). Annualisation uses 252
trading days.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..risk.drawdown import max_drawdown, max_drawdown_duration, ulcer_index
from ..risk.var_es import historical_es, historical_var
from ..utils.math import TRADING_DAYS_PER_YEAR, annualize_return, annualize_vol


def sharpe_ratio(returns: pd.Series, rf: float = 0.0) -> float:
    r = returns.dropna()
    if r.empty or r.std(ddof=1) == 0:
        return np.nan
    excess = r - rf / TRADING_DAYS_PER_YEAR
    return float(excess.mean() / r.std(ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR))


def sortino_ratio(returns: pd.Series, rf: float = 0.0) -> float:
    r = returns.dropna()
    if r.empty:
        return np.nan
    excess = r - rf / TRADING_DAYS_PER_YEAR
    downside = r[r < 0]
    dd = downside.std(ddof=1)
    if dd == 0 or np.isnan(dd):
        return np.nan
    return float(excess.mean() / dd * np.sqrt(TRADING_DAYS_PER_YEAR))


def calmar_ratio(equity: pd.Series, returns: pd.Series) -> float:
    mdd = abs(max_drawdown(equity))
    if mdd == 0 or np.isnan(mdd):
        return np.nan
    return float(annualize_return(returns) / mdd)


def win_rate(returns: pd.Series) -> float:
    r = returns.dropna()
    r = r[r != 0.0]
    return float((r > 0).mean()) if len(r) else np.nan


def avg_win_loss(returns: pd.Series) -> tuple[float, float]:
    r = returns.dropna()
    wins = r[r > 0]
    losses = r[r < 0]
    return (
        float(wins.mean()) if len(wins) else np.nan,
        float(losses.mean()) if len(losses) else np.nan,
    )


def rolling_sharpe(returns: pd.Series, window: int = 126) -> pd.Series:
    roll = returns.rolling(window, min_periods=window // 2)
    return roll.mean() / roll.std(ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR)


def monthly_returns_table(returns: pd.Series) -> pd.DataFrame:
    """Pivot of monthly compounded returns (rows=year, cols=month)."""
    r = returns.dropna()
    if r.empty:
        return pd.DataFrame()
    monthly = (1.0 + r).resample("ME").prod() - 1.0
    df = monthly.to_frame("ret")
    df["year"] = df.index.year
    df["month"] = df.index.month
    return df.pivot_table(index="year", columns="month", values="ret")


def yearly_returns(returns: pd.Series) -> pd.Series:
    r = returns.dropna()
    if r.empty:
        return pd.Series(dtype=float)
    yearly = (1.0 + r).resample("YE").prod() - 1.0
    yearly.index = yearly.index.year
    return yearly


def compute_metrics(result, rf: float = 0.0) -> dict:
    """Full metric dict for a BacktestResult (or equity/returns pair)."""
    equity = result.equity_curve
    returns = result.returns
    aw, al = avg_win_loss(returns)
    metrics = {
        "start": str(equity.index[0].date()),
        "end": str(equity.index[-1].date()),
        "n_days": int(len(equity)),
        "initial_capital": float(result.initial_capital),
        "final_equity": float(equity.iloc[-1]),
        "total_return": float(equity.iloc[-1] / equity.iloc[0] - 1.0),
        "cagr": annualize_return(returns),
        "annual_vol": annualize_vol(returns),
        "sharpe": sharpe_ratio(returns, rf),
        "sortino": sortino_ratio(returns, rf),
        "max_drawdown": max_drawdown(equity),
        "max_dd_duration_days": max_drawdown_duration(equity),
        "calmar": calmar_ratio(equity, returns),
        "ulcer_index": ulcer_index(equity),
        "win_rate": win_rate(returns),
        "avg_win": aw,
        "avg_loss": al,
        "hist_var_95": historical_var(returns, 0.95),
        "hist_es_95": historical_es(returns, 0.95),
        "annual_turnover": float(getattr(result, "annual_turnover", np.nan)),
        "total_transaction_cost": float(result.total_cost),
        "cost_drag_pct_of_initial": float(
            result.total_cost / result.initial_capital
        ),
        "avg_gross_exposure": float(result.weights.abs().sum(axis=1).mean()),
        "avg_net_exposure": float(result.weights.sum(axis=1).mean()),
        "n_risk_events": int(len(result.risk_events)),
    }
    return metrics
