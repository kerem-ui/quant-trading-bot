"""Run the S02 Cross-Sectional Factor Blend backtest (price-only v1).

Research/backtest only. Long-only, MONTHLY rebalance, ETF universe. Price-only
factors (no point-in-time fundamentals available in v1 - a documented bias).

    python scripts/run_s02.py [--source auto|synthetic|yfinance]
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
from quantbot.strategies.s02_factor_blend import S02FactorBlend


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=None)
    args = ap.parse_args()

    data_cfg = load_data_config()
    if args.source:
        data_cfg["source"] = args.source
    strat_cfg = load_strategy_config()

    panel, sector_map = load_universe_from_config("s02_factor", data_cfg)
    src = detect_data_source(panel)
    print(src)
    print("NOTE: price-only factors in v1; results carry survivorship/"
          "point-in-time caveats described in the README.")

    strategy = S02FactorBlend(
        strategy_params("S02_factor_blend", strat_cfg), sector_map=sector_map
    )
    engine = BacktestEngine(
        risk_manager=RiskManager(load_risk_config()),
        execution=strat_cfg["global"].get("default_execution", "next_open"),
    )
    result = engine.run(strategy, panel, sector_map=sector_map)

    metrics = compute_metrics(result)
    print_metrics(metrics)
    paths = export_report(result, "s02_factor_blend",
                          title="S02 Factor Blend (price-only v1)", data_source=src)
    print("\nReport written to:")
    for k, v in paths.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
