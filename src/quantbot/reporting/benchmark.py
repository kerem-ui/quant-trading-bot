"""Benchmark comparison.

S02 (the strongest real-data strategy in V1) is the internal benchmark; SPY
buy-&-hold is the external benchmark. All comparisons align on the common date
range first, so a strategy is never credited/penalised for dates the benchmark
does not cover. Research only - relative metrics, not advice.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..utils.math import TRADING_DAYS_PER_YEAR, annualize_return, annualize_vol


def buy_and_hold_returns(panel: dict[str, pd.DataFrame], symbol: str = "SPY") -> pd.Series:
    """Daily returns of a passive long position in one ETF (external benchmark)."""
    if symbol not in panel:
        raise KeyError(f"{symbol} not in panel; cannot build buy&hold benchmark")
    r = panel[symbol]["adjusted_close"].pct_change()
    r.name = f"{symbol}_buyhold"
    return r


def _align(strat: pd.Series, bench: pd.Series) -> tuple[pd.Series, pd.Series]:
    df = pd.concat([strat.rename("s"), bench.rename("b")], axis=1).dropna()
    return df["s"], df["b"]


def relative_metrics(
    strat_returns: pd.Series, bench_returns: pd.Series, rf: float = 0.0
) -> dict:
    """Strategy-vs-benchmark stats on the aligned overlap."""
    s, b = _align(strat_returns, bench_returns)
    if len(s) < 20:
        return {"n_obs": int(len(s)), "note": "insufficient overlap"}
    active = s - b
    te = float(active.std(ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR))
    var_b = float(b.var(ddof=1))
    beta = float(s.cov(b) / var_b) if var_b > 1e-18 else np.nan
    up = b > 0
    down = b < 0

    def _sharpe(x: pd.Series) -> float:
        sd = x.std(ddof=1)
        return float(x.mean() / sd * np.sqrt(TRADING_DAYS_PER_YEAR)) if sd > 1e-18 else np.nan

    return {
        "n_obs": int(len(s)),
        "strat_cagr": annualize_return(s),
        "bench_cagr": annualize_return(b),
        "excess_cagr": annualize_return(s) - annualize_return(b),
        "strat_vol": annualize_vol(s),
        "bench_vol": annualize_vol(b),
        # Absolute (standalone) Sharpe for strategy and benchmark, shown next
        # to the relative metrics so S02-as-benchmark is legible at a glance.
        "strat_sharpe": _sharpe(s),
        "bench_sharpe": _sharpe(b),
        "tracking_error": te,
        "information_ratio": float(active.mean() / active.std(ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR))
        if active.std(ddof=1) > 1e-18 else np.nan,
        "beta_to_bench": beta,
        "correlation": float(s.corr(b)),
        "up_capture": float(s[up].mean() / b[up].mean()) if up.any() and b[up].mean() != 0 else np.nan,
        "down_capture": float(s[down].mean() / b[down].mean()) if down.any() and b[down].mean() != 0 else np.nan,
    }


def compare_to_benchmarks(
    strat_returns: pd.Series, benchmarks: dict[str, pd.Series], rf: float = 0.0
) -> pd.DataFrame:
    """One row per benchmark; columns are the relative metrics."""
    rows = {name: relative_metrics(strat_returns, b, rf) for name, b in benchmarks.items()}
    df = pd.DataFrame(rows).T
    df.index.name = "benchmark"
    return df
