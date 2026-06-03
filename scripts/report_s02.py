"""Deep S02 attribution + robustness report (READ-ONLY).

S02 is the core strategy. This produces the dedicated deeper report:
isolated factor sleeves, leave-one-out marginal, sleeve correlation,
sub-period stability, regime-conditional behaviour, robustness battery, and
the null comparison. Console + Markdown (reports/core/s02_attribution.md).

No defaults / configs / strategy logic changed.

Run:  python scripts/report_s02.py [--source cache|auto|synthetic]
"""

from __future__ import annotations

import argparse

import pandas as pd
from _common import detect_data_source

from quantbot.backtest.engine import BacktestEngine
from quantbot.backtest.performance import compute_metrics
from quantbot.config import load_data_config, load_risk_config, project_root
from quantbot.data.loaders import load_universe_from_config
from quantbot.reporting import factor_attribution as fa
from quantbot.reporting.benchmark import buy_and_hold_returns, relative_metrics
from quantbot.risk.risk_manager import RiskManager
from quantbot.strategies.s02_factor_blend import S02FactorBlend
from quantbot.utils.math import annualize_return, annualize_vol, TRADING_DAYS_PER_YEAR

pd.set_option("display.width", 180)

SUBPERIODS = [("2010-2014", "2010-01-01", "2014-12-31"),
              ("2015-2019", "2015-01-01", "2019-12-31"),
              ("2020-2026", "2020-01-01", "2026-12-31")]


def _sharpe(r):
    r = r.dropna()
    sd = r.std(ddof=1)
    return float(r.mean() / sd * (TRADING_DAYS_PER_YEAR ** 0.5)) if sd > 1e-18 else float("nan")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="cache")
    args = ap.parse_args()
    dc = load_data_config()
    dc["source"] = args.source

    panel, sm = load_universe_from_config("s02_factor", dc)
    src = detect_data_source(panel)

    base = fa._base_config()
    res = BacktestEngine(risk_manager=RiskManager(load_risk_config())).run(
        S02FactorBlend(base, sector_map=sm), panel, sector_map=sm
    )
    m = compute_metrics(res)
    spy = buy_and_hold_returns(panel, "SPY")
    rel = relative_metrics(res.returns, spy)

    out, md = print, []

    def emit(line=""):
        out(line)
        md.append(line)

    emit("# S02 (CORE) - Deep Attribution & Robustness")
    emit()
    emit(f"_{src}_")
    emit()
    emit(f"DEFAULT blend: CAGR={m['cagr']:.4f} Sharpe={m['sharpe']:.3f} "
         f"Sortino={m['sortino']:.3f} maxDD={m['max_drawdown']:.4f} "
         f"turnover={m['annual_turnover']:.2f} cost_drag={m['cost_drag_pct_of_initial']:.4f}")
    emit(f"vs SPY buy-hold: excess_cagr={rel['excess_cagr']:+.4f} "
         f"IR={rel['information_ratio']:+.3f} beta={rel['beta_to_bench']:.3f} "
         f"down_capture={rel['down_capture']:.3f} "
         f"(strat Sharpe {rel['strat_sharpe']:.3f} vs SPY {rel['bench_sharpe']:.3f})")

    emit("\n## [A] Isolated single-factor sleeves")
    iso, rets = fa.isolated_sleeves(panel, sm, base=base)
    emit(iso.round(4).to_string())
    emit("\n(If every sleeve is positive, the edge is the FACTORS, not the blend.)")

    emit("\n## [B] Leave-one-out marginal (vs default blend)")
    loo, blend = fa.leave_one_out(panel, sm, base=base)
    emit(loo.round(4).to_string())

    emit("\n## [C] Sleeve return correlation (diversification)")
    cm = fa.sleeve_return_correlation(rets)
    emit(cm.round(2).to_string())

    emit("\n## [D] Sub-period stability (default blend)")
    rr = res.returns
    for label, s, e in SUBPERIODS:
        seg = rr.loc[(rr.index >= s) & (rr.index <= e)].dropna()
        if len(seg) < 30:
            continue
        emit(f"  {label}: CAGR={annualize_return(seg):+.4f} "
             f"vol={annualize_vol(seg):.4f} Sharpe={_sharpe(seg):+.3f} "
             f"cum={(1 + seg).prod() - 1:+.3f}")

    emit("\n## [E] Regime-conditional (vs SPY)")
    emit(fa.regime_conditional(res.returns, spy).round(4).to_string())

    emit("\n## [F] Robustness battery")
    rb = fa.robustness_battery(panel, sm, base=base)
    emit("\nWalk-forward (out-of-sample folds):")
    emit(rb["walk_forward"].round(4).to_string(index=False))
    emit("\nCost sensitivity:")
    emit(rb["cost_sensitivity"].round(4).to_string(index=False))
    emit("\nParameter sensitivity (rebalance x top_quantile) - DISPLAY ONLY:")
    emit(rb["param_sensitivity"].round(4).to_string(index=False))

    emit("\n## [G] Null comparison")
    nc = fa.null_comparison(panel, sm, base=base)
    for k, v in nc.items():
        emit(f"  {k}: {v}")
    emit(f"\n--> S02 edge: {'ROBUST (factor-driven, not weight-tuned)' if nc['edge_is_robust'] else 'SUSPECT (weight-sensitive)'}")

    out_dir = project_root() / "reports" / "core"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "s02_attribution.md").write_text("\n".join(md), encoding="utf-8")
    out(f"\nMarkdown written: {out_dir / 's02_attribution.md'}")


if __name__ == "__main__":
    main()
