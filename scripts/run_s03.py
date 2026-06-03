"""Run the S03 Pairs / Statistical-Arbitrage Mean Reversion backtest.

Research/backtest only. Dollar-neutral (long + short ETF legs), weekly
rebalance, MONTHLY walk-forward pair reselection. Borrow cost on the short
leg is modelled.

    python scripts/run_s03.py [--source auto|synthetic|yfinance] [--borrow-bps 50]
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
from quantbot.strategies.s03_pairs_mean_reversion import S03PairsMeanReversion


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=None)
    ap.add_argument("--borrow-bps", type=float, default=50.0,
                    help="annualized borrow cost (bps) charged on short leg")
    args = ap.parse_args()

    data_cfg = load_data_config()
    if args.source:
        data_cfg["source"] = args.source
    strat_cfg = load_strategy_config()

    panel, sector_map = load_universe_from_config("s03_pairs", data_cfg)
    src = detect_data_source(panel)
    print(src)

    strategy = S03PairsMeanReversion(
        strategy_params("S03_pairs_mean_reversion", strat_cfg), sector_map=sector_map
    )
    engine = BacktestEngine(
        risk_manager=RiskManager(load_risk_config()),
        execution=strat_cfg["global"].get("default_execution", "next_open"),
        borrow_cost_bps_annual=args.borrow_bps,
    )
    result = engine.run(strategy, panel, sector_map=sector_map)

    metrics = compute_metrics(result)
    print_metrics(metrics)
    paths = export_report(result, "s03_pairs_mean_reversion",
                          title="S03 Pairs Mean Reversion", data_source=src)
    print("\nReport written to:")
    for k, v in paths.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
