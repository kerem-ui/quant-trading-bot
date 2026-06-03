"""Run the S01 Multi-Asset Volatility-Targeted Trend Following backtest.

Research/backtest only. Long-only, weekly rebalance, ETF universe, free daily
OHLCV (synthetic fallback if yfinance is unreachable).

    python scripts/run_s01.py [--source auto|synthetic|yfinance]
"""

from __future__ import annotations

import argparse

from _common import detect_data_source, print_metrics

from quantbot.backtest.engine import BacktestEngine
from quantbot.backtest.performance import compute_metrics
from quantbot.config import load_data_config, load_risk_config, load_strategy_config, strategy_params
from quantbot.data.loaders import load_universe_from_config
from quantbot.reporting.export import export_report
from quantbot.risk.risk_manager import RiskManager
from quantbot.strategies.s01_trend_following import S01TrendFollowing


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=None, help="override data source")
    args = ap.parse_args()

    data_cfg = load_data_config()
    if args.source:
        data_cfg["source"] = args.source
    strat_cfg = load_strategy_config()

    panel, sector_map = load_universe_from_config("s01_trend", data_cfg)
    src = detect_data_source(panel)
    print(src)

    s01_params = strategy_params("S01_trend_following", strat_cfg)
    strategy = S01TrendFollowing(s01_params, sector_map=sector_map)
    engine = BacktestEngine(
        risk_manager=RiskManager(load_risk_config()),
        execution=strat_cfg["global"].get("default_execution", "next_open"),
        rebalance_band=float(s01_params.get("rebalance_band", 0.0)),
    )
    result = engine.run(strategy, panel, sector_map=sector_map)

    metrics = compute_metrics(result)
    print_metrics(metrics)
    paths = export_report(result, "s01_trend_following", title="S01 Trend Following",
                          data_source=src)
    print("\nReport written to:")
    for k, v in paths.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
