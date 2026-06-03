"""Core book runner (V2.3).

Role-driven, evidence-based:
  * S02 = core         -> run, export report (benchmark + diagnostics)
  * S01 = satellite     -> run (binary default) as an EXPERIMENTAL sleeve only
  * S03 = research-only  -> NOT traded as alpha (V2.2 falsified: 0/13 pairs);
                            excluded here, pointer to scripts/research_edge.py

Roles are read from strategy_configs.json ("role"). No defaults changed.
Research/backtest only - no broker, no live trading, no options.

Run:  python scripts/run_core.py [--source cache|auto|synthetic]
"""

from __future__ import annotations

import argparse

from _common import detect_data_source, print_metrics

from quantbot.backtest.engine import BacktestEngine
from quantbot.backtest.performance import compute_metrics
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


def _role(sc, key):
    return strategy_params(key, sc).get("role", "unspecified")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="cache")
    args = ap.parse_args()
    dc = load_data_config()
    dc["source"] = args.source
    sc = load_strategy_config()
    execn = sc["global"].get("default_execution", "next_open")

    def rm():
        return RiskManager(load_risk_config())

    print("=" * 74)
    print("CORE BOOK (V2.3, evidence-based roles)")
    print("=" * 74)

    # ---- S02 : CORE ---------------------------------------------------- #
    p2, sm2 = load_universe_from_config("s02_factor", dc)
    src = detect_data_source(p2)
    print(src)
    print(f"\n[S02] role={_role(sc, 'S02_factor_blend')}  ** CORE STRATEGY **")
    res2 = BacktestEngine(risk_manager=rm(), execution=execn).run(
        S02FactorBlend(strategy_params("S02_factor_blend", sc), sector_map=sm2),
        p2, sector_map=sm2,
    )
    m2 = compute_metrics(res2)
    print_metrics(m2)
    spy = buy_and_hold_returns(p2, "SPY")
    export_report(res2, "s02_factor_blend", title="S02 Factor Blend (CORE)",
                  data_source=src, benchmarks={"SPY_buyhold": spy})

    # ---- S01 : SATELLITE / EXPERIMENTAL -------------------------------- #
    p1, sm1 = load_universe_from_config("s01_trend", dc)
    s01p = strategy_params("S01_trend_following", sc)
    print(f"\n[S01] role={_role(sc, 'S01_trend_following')}  "
          f"(experimental satellite; mode={s01p.get('s01_execution_mode', 'binary')})")
    res1 = BacktestEngine(
        risk_manager=rm(), execution=execn,
        rebalance_band=float(s01p.get("rebalance_band", 0.0)),
    ).run(S01TrendFollowing(s01p, sector_map=sm1), p1, sector_map=sm1)
    m1 = compute_metrics(res1)
    print_metrics(m1)
    r1 = relative_metrics(res1.returns, res2.returns)
    print(f"  S01 vs S02 core: excess_cagr={r1['excess_cagr']:+.4f} "
          f"IR={r1['information_ratio']:+.3f} corr={r1['correlation']:+.3f}")
    print("  NOTE: satellite only - does not replace the core; conviction "
          "mode is an opt-in research experiment (off by default).")

    # ---- S03 : RESEARCH-ONLY, NOT ALPHA -------------------------------- #
    print(f"\n[S03] role={_role(sc, 'S03_pairs_mean_reversion')}  "
          "-- EXCLUDED from the book --")
    print("  V2.2 falsification: 0/13 same-sector ETF pairs survived a strict "
          "out-of-sample + cost bar (best full net ~ -1.2%).")
    print("  Near-identical clones have ~0 spread after costs; sector twins do "
          "not mean-revert. S03 is NOT traded as alpha.")
    print("  Diagnostics only: scripts/research_edge.py")

    print("\n" + "=" * 74)
    print("SUMMARY: core = S02. S01 = experimental satellite. S03 = research-only.")
    print("Reports under reports/backtests/  | deep S02: scripts/report_s02.py")
    print("=" * 74)


if __name__ == "__main__":
    main()
