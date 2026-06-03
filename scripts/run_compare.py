"""Run S01, S02, S03 on the same data and compare them to the benchmarks.

Internal benchmark = S02 (strongest real-data book in V1). External = SPY
buy-&-hold. Each strategy's report is regenerated WITH the benchmark section;
a consolidated table is printed to the console.

    python scripts/run_compare.py [--source auto|cache|synthetic|yfinance]

Research/backtest only. ETF-only, no broker, no live trading.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
from _common import detect_data_source

from quantbot.backtest.engine import BacktestEngine
from quantbot.backtest.performance import compute_metrics
from quantbot.backtest.walk_forward import param_sensitivity
from quantbot.config import project_root
from quantbot.config import (
    load_data_config,
    load_risk_config,
    load_strategy_config,
    strategy_params,
)
from quantbot.data.loaders import load_universe_from_config
from quantbot.reporting.benchmark import buy_and_hold_returns, relative_metrics
from quantbot.reporting.export import export_report
from quantbot.risk.risk_manager import RiskManager
from quantbot.strategies.s01_trend_following import S01TrendFollowing
from quantbot.strategies.s02_factor_blend import S02FactorBlend
from quantbot.strategies.s03_pairs_mean_reversion import S03PairsMeanReversion


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=None)
    args = ap.parse_args()

    dc = load_data_config()
    if args.source:
        dc["source"] = args.source
    sc = load_strategy_config()
    execn = sc["global"].get("default_execution", "next_open")

    def rm() -> RiskManager:
        return RiskManager(load_risk_config())

    # --- S02 first: it is the internal benchmark -------------------------- #
    p2, sm2 = load_universe_from_config("s02_factor", dc)
    src = detect_data_source(p2)
    res2 = BacktestEngine(risk_manager=rm(), execution=execn).run(
        S02FactorBlend(strategy_params("S02_factor_blend", sc), sector_map=sm2),
        p2, sector_map=sm2,
    )

    # --- S01 --------------------------------------------------------------- #
    p1, sm1 = load_universe_from_config("s01_trend", dc)
    s01p = strategy_params("S01_trend_following", sc)
    res1 = BacktestEngine(
        risk_manager=rm(), execution=execn,
        rebalance_band=float(s01p.get("rebalance_band", 0.0)),
    ).run(S01TrendFollowing(s01p, sector_map=sm1), p1, sector_map=sm1)

    # --- S03 --------------------------------------------------------------- #
    p3, sm3 = load_universe_from_config("s03_pairs", dc)
    res3 = BacktestEngine(
        risk_manager=rm(), execution=execn, borrow_cost_bps_annual=50.0
    ).run(
        S03PairsMeanReversion(strategy_params("S03_pairs_mean_reversion", sc), sector_map=sm3),
        p3, sector_map=sm3,
    )

    spy = buy_and_hold_returns(p1, "SPY")
    benchmarks_for = {
        "S01_trend_following": (res1, {"S02_factor": res2.returns, "SPY_buyhold": spy}),
        "S02_factor_blend": (res2, {"SPY_buyhold": spy}),
        "S03_pairs_mean_reversion": (res3, {"S02_factor": res2.returns, "SPY_buyhold": spy}),
    }

    print("\n" + src + "\n")
    rows = []
    for name, (res, bms) in benchmarks_for.items():
        m = compute_metrics(res)
        vs_s02 = relative_metrics(res.returns, res2.returns) if name != "S02_factor_blend" else {}
        rows.append({
            "strategy": name,
            "CAGR": round(m["cagr"], 4),
            "Sharpe": round(m["sharpe"], 3),
            "maxDD": round(m["max_drawdown"], 4),
            "ann_turnover": round(m["annual_turnover"], 3),
            "tot_cost": round(m["total_transaction_cost"], 0),
            "avg_gross": round(m["avg_gross_exposure"], 4),
            "excess_cagr_vs_S02": round(vs_s02.get("excess_cagr", 0.0), 4),
            "IR_vs_S02": round(vs_s02.get("information_ratio", 0.0), 3),
        })
        export_report(
            res, name, title=name, data_source=src, benchmarks=bms, make_plots=True
        )

    df = pd.DataFrame(rows).set_index("strategy")
    pd.set_option("display.width", 180)
    print("=== Strategy comparison (S02 = internal benchmark) ===")
    print(df.to_string())

    # --- V1 / V2 / V2.1 three-way before/after --------------------------- #
    root = project_root()
    archives = {
        "V1": root / "reports" / "_v1_archive",
        "V2": root / "reports" / "_v2_archive",
        "V2.1": root / "reports" / "backtests",  # just regenerated
    }
    keys = ["cagr", "sharpe", "max_drawdown", "max_dd_duration_days",
            "annual_turnover", "total_transaction_cost",
            "cost_drag_pct_of_initial", "avg_gross_exposure"]
    print("\n=== V1 / V2 / V2.1 before-after (real yfinance) ===")
    for strat in ["s01_trend_following", "s02_factor_blend", "s03_pairs_mean_reversion"]:
        cols = {}
        for ver, d in archives.items():
            mp = d / strat / "metrics.json"
            if mp.is_file():
                cols[ver] = {k: json.load(open(mp)).get(k) for k in keys}
        if cols:
            print(f"\n[{strat}]")
            print(pd.DataFrame(cols).reindex(keys).to_string(
                float_format=lambda x: f"{x:,.4f}"))

    # --- S02 robustness (DISPLAY ONLY - default unchanged) --------------- #
    print("\n=== S02 sensitivity (display only; default stays monthly/0.04) ===")
    s02_sens = param_sensitivity(
        S02FactorBlend, strategy_params("S02_factor_blend", sc),
        {"rebalance_frequency": ["monthly", "quarterly"],
         "max_weight_per_name_long_only": [0.04, 0.06]},
        p2, rm(), sector_map=sm2,
    )
    print(s02_sens.round(4).to_string(index=False))

    print("\nReports (benchmark + diagnostics) under reports/backtests/<strategy>/")


if __name__ == "__main__":
    main()
