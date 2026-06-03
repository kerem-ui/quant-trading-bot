"""Shared script helpers (path setup + data source reporting)."""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def detect_data_source(panel: dict) -> str:
    """Heuristic label for the report (synthetic generator uses a bdate index
    starting exactly at the configured start and round-number seeds)."""
    any_df = next(iter(panel.values()))
    n = len(any_df)
    return (
        f"loaded {len(panel)} symbols x {n} bars "
        f"({any_df.index[0].date()} -> {any_df.index[-1].date()}). "
        "If yfinance was unreachable this is SYNTHETIC data "
        "(illustrative only, not market data) - see console log above."
    )


def print_metrics(metrics: dict) -> None:
    keys = [
        "start", "end", "n_days", "final_equity", "total_return", "cagr",
        "annual_vol", "sharpe", "sortino", "max_drawdown", "calmar",
        "win_rate", "annual_turnover", "total_transaction_cost",
        "avg_gross_exposure", "avg_net_exposure", "n_risk_events",
    ]
    print("\n=== Headline metrics ===")
    for k in keys:
        if k in metrics:
            v = metrics[k]
            print(f"  {k:26s}: {v:,.4f}" if isinstance(v, float) else f"  {k:26s}: {v}")
