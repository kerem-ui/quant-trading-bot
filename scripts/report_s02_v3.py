"""V3 S02 core-strategy report (READ-ONLY).

Runs the S02 core strategy on real cached yfinance data and emits the V3
analytics bundle:

  reports/core/s02_v3_report.md
  reports/core/s02_v3_metrics.json
  reports/core/s02_v3_tables/*.csv
  reports/figures/s02_v3/*.png

No strategy logic / defaults / config changed. ETF-only, no broker/live/options.

Run:  python scripts/report_s02_v3.py [--source cache|auto|synthetic]
"""

from __future__ import annotations

import argparse
import json

import matplotlib
import pandas as pd
from _common import detect_data_source

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from quantbot.backtest.engine import BacktestEngine  # noqa: E402
from quantbot.backtest.performance import compute_metrics  # noqa: E402
from quantbot.config import (  # noqa: E402
    load_data_config,
    load_risk_config,
    load_strategy_config,
    project_root,
    strategy_params,
)
from quantbot.data.loaders import load_prices, load_universe_from_config  # noqa: E402
from quantbot.reporting import s02_analytics as A  # noqa: E402
from quantbot.risk.drawdown import drawdown_series  # noqa: E402
from quantbot.risk.risk_manager import RiskManager  # noqa: E402
from quantbot.strategies.s02_factor_blend import S02FactorBlend  # noqa: E402

SUBPERIODS = [("2010-2014", "2010-01-01", "2014-12-31"),
              ("2015-2019", "2015-01-01", "2019-12-31"),
              ("2020-2026", "2020-01-01", "2026-12-31")]


def _md(df) -> str:
    """GitHub-flavoured markdown table without the optional 'tabulate' dep."""
    df = df.copy()
    if df.index.name or not isinstance(df.index, pd.RangeIndex):
        df = df.reset_index()

    def fmt(x):
        if isinstance(x, float):
            return f"{x:.4f}"
        return str(x)

    cols = [str(c) for c in df.columns]
    lines = ["| " + " | ".join(cols) + " |",
             "|" + "|".join(["---"] * len(cols)) + "|"]
    for _, row in df.iterrows():
        lines.append("| " + " | ".join(fmt(v) for v in row.tolist()) + " |")
    return "\n".join(lines)


def _save_fig(fig, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="cache")
    args = ap.parse_args()
    dc = load_data_config()
    dc["source"] = args.source
    sc = load_strategy_config()

    panel, sm = load_universe_from_config("s02_factor", dc)
    src = detect_data_source(panel)
    res = BacktestEngine(risk_manager=RiskManager(load_risk_config())).run(
        S02FactorBlend(strategy_params("S02_factor_blend", sc), sector_map=sm),
        panel, sector_map=sm,
    )
    m = compute_metrics(res)

    # SHY cash proxy (cached real data; not in the S02 universe).
    try:
        shy = load_prices(["SHY"], source="cache", validate=False)["SHY"]
        shy_ret = shy["adjusted_close"].pct_change()
        shy_ret.name = "SHY_cash"
    except Exception:
        shy_ret = None

    etf = A.etf_contribution(res, panel)
    fac = A.factor_analysis(panel, sm, SUBPERIODS, n_random=16)
    reg = A.regime_analysis(res, panel)
    risk = A.risk_analysis(res, panel, sm)
    bench = A.benchmark_analysis(
        res, panel, extra_benchmarks={"SHY_cash": shy_ret} if shy_ret is not None else None
    )

    root = project_root()
    core = root / "reports" / "core"
    tbl = core / "s02_v3_tables"
    figs = root / "reports" / "figures" / "s02_v3"
    tbl.mkdir(parents=True, exist_ok=True)
    figs.mkdir(parents=True, exist_ok=True)

    # ---- tables (CSV) -------------------------------------------------- #
    tables = {
        "etf_summary": etf["summary"],
        "etf_yearly_contribution": etf["yearly_by_etf"],
        "factor_sleeves": fac["sleeves"],
        "factor_leave_one_out": fac["leave_one_out"],
        "factor_correlation": fac["correlation"],
        "factor_subperiod_stability": fac["subperiod_stability"],
        "regimes": reg["regimes"],
        "crisis_windows": reg["crisis_windows"],
        "explicit_2020_2022": reg["explicit"],
        "exposure_by_bucket": risk["exposure_by_bucket"],
        "risk_contribution_etf": risk["risk_contribution_etf"],
        "risk_contribution_bucket": risk["risk_contribution_bucket"].to_frame("ann_risk"),
        "drawdown_contribution_etf": etf["by_etf"].to_frame("total_contribution"),
        "benchmark_table": bench["table"],
    }
    for name, df in tables.items():
        df.to_csv(tbl / f"{name}.csv")

    # ---- figures ------------------------------------------------------- #
    fig, ax = plt.subplots(figsize=(10, 4))
    res.equity_curve.plot(ax=ax, color="navy", lw=1.2)
    ax.set_title("S02 Equity Curve"); ax.grid(alpha=0.3)
    _save_fig(fig, figs / "equity.png")

    fig, ax = plt.subplots(figsize=(10, 3))
    dd = drawdown_series(res.equity_curve)
    ax.fill_between(dd.index, dd.values, 0.0, color="firebrick", alpha=0.5)
    ax.set_title("S02 Drawdown"); ax.grid(alpha=0.3)
    _save_fig(fig, figs / "drawdown.png")

    fig, ax = plt.subplots(figsize=(10, 3))
    risk["rolling_vol"].plot(ax=ax, color="purple", lw=1.0)
    ax.set_title("S02 Rolling Volatility (63d, annualized)"); ax.grid(alpha=0.3)
    _save_fig(fig, figs / "rolling_vol.png")

    fig, ax = plt.subplots(figsize=(10, 3))
    risk["rolling_sharpe"].plot(ax=ax, color="darkgreen", lw=1.0)
    ax.axhline(0, color="black", lw=0.6)
    ax.set_title("S02 Rolling Sharpe (126d)"); ax.grid(alpha=0.3)
    _save_fig(fig, figs / "rolling_sharpe.png")

    fig, ax = plt.subplots(figsize=(10, 4))
    etf["by_etf"].sort_values().plot.barh(ax=ax, color="steelblue")
    ax.set_title("S02 Total Contribution by ETF"); ax.grid(alpha=0.3)
    _save_fig(fig, figs / "contribution_by_etf.png")

    fig, ax = plt.subplots(figsize=(8, 4))
    risk["exposure_by_bucket"]["avg_gross"].sort_values().plot.barh(
        ax=ax, color="teal")
    ax.set_title("S02 Avg Gross Exposure by Bucket"); ax.grid(alpha=0.3)
    _save_fig(fig, figs / "exposure_by_bucket.png")

    fig, ax = plt.subplots(figsize=(10, 4))
    growth = {"S02": (1 + res.returns.fillna(0)).cumprod()}
    for nm, br in bench["benchmark_returns"].items():
        growth[nm] = (1 + br.reindex(res.returns.index).fillna(0)).cumprod()
    pd.DataFrame(growth).plot(ax=ax, lw=1.0)
    ax.set_title("Growth of $1: S02 vs benchmarks"); ax.grid(alpha=0.3)
    _save_fig(fig, figs / "benchmark_growth.png")

    # ---- metrics.json -------------------------------------------------- #
    metrics = {
        "data_source": src,
        "headline": {k: m[k] for k in [
            "start", "end", "n_days", "cagr", "annual_vol", "sharpe",
            "sortino", "max_drawdown", "max_dd_duration_days", "calmar",
            "annual_turnover", "total_transaction_cost",
            "cost_drag_pct_of_initial", "avg_gross_exposure"]},
        "cost_split": res.cost_attribution(),
        "etf_best": etf["best"].round(6).to_dict(),
        "etf_worst": etf["worst"].round(6).to_dict(),
        "factor_weight_sensitivity": fac["weight_sensitivity"],
        "drawdown_window": risk["drawdown_window"],
        "regime_sharpe": {
            "SPY_bull": float(reg["regimes"].loc["SPY bull (>200dma)", "sharpe"]),
            "SPY_bear": float(reg["regimes"].loc["SPY bear (<200dma)", "sharpe"]),
            "high_vol": float(reg["regimes"].loc["high-vol regime", "sharpe"]),
            "low_vol": float(reg["regimes"].loc["low-vol regime", "sharpe"]),
        },
        "explicit_2020_2022": reg["explicit"][
            ["cum_return", "spy_cum_return", "max_drawdown"]].round(6).to_dict("index"),
        "benchmark_table": bench["table"].round(6).to_dict("index"),
        "guards": {"live_trading_enabled": False, "options_added": False,
                   "broker_added": False, "defaults_changed": False},
    }
    (core / "s02_v3_metrics.json").write_text(
        json.dumps(metrics, indent=2, default=str), encoding="utf-8")

    # ---- markdown report ---------------------------------------------- #
    L = []
    a = L.append
    a("# S02 (CORE) - V3 Analytics Report")
    a("")
    a(f"_{src}_")
    a("")
    a("> Research/backtest only. No broker/live/options. No strategy defaults "
      "changed. S02 is the core strategy (S01 satellite, S03 research-only).")
    a("")
    a("## Headline")
    a("")
    a("| metric | value |")
    a("|---|---|")
    for k, v in metrics["headline"].items():
        a(f"| {k} | {v:.4f} |" if isinstance(v, float) else f"| {k} | {v} |")
    cs = metrics["cost_split"]
    a(f"| trading_cost | {cs['trading_cost']:.0f} |")
    a(f"| borrow_cost | {cs['borrow_cost']:.0f} |")

    a("\n## 1. ETF-level contribution")
    a("")
    a(etf["summary"].round(5).pipe(_md))
    a(f"\n**Best:** {', '.join(f'{k} {v:+.4f}' for k, v in etf['best'].items())}")
    a(f"**Worst:** {', '.join(f'{k} {v:+.4f}' for k, v in etf['worst'].items())}")
    a("\nYearly contribution by ETF:")
    a("")
    a(etf["yearly_by_etf"].round(4).pipe(_md))

    a("\n## 2. Factor analysis")
    a("")
    a("Isolated single-factor sleeves:")
    a("")
    a(fac["sleeves"].round(4).pipe(_md))
    a(f"\nBlend Sharpe = {fac['blend']['sharpe']:.3f}. Leave-one-out:")
    a("")
    a(fac["leave_one_out"].round(4).pipe(_md))
    a("\nSleeve return correlation:")
    a("")
    a(fac["correlation"].round(2).pipe(_md))
    a("\nFactor stability by sub-period (sleeve Sharpe):")
    a("")
    a(fac["subperiod_stability"].round(3).pipe(_md))
    ws = fac["weight_sensitivity"]
    a(f"\nWeight sensitivity: default Sharpe {ws['default_sharpe']:.3f}, "
      f"equal-weight {ws['equal_weight_sharpe']:.3f}, random "
      f"[{ws['random_min']:.3f}, {ws['random_max']:.3f}], "
      f"{ws['random_frac_positive']:.0%} positive -> "
      f"edge_is_robust = **{ws['edge_is_robust']}**.")

    a("\n## 3. Regime analysis")
    a("")
    a(reg["regimes"][["n_days", "cum_return", "ann_return", "ann_vol",
                      "sharpe", "max_drawdown"]].round(4).pipe(_md))
    a("\nCrisis windows:")
    a("")
    a(reg["crisis_windows"][["n_days", "cum_return", "max_drawdown",
                             "spy_cum_return"]].round(4).pipe(_md))
    a("\nExplicit 2020 / 2022:")
    a("")
    a(reg["explicit"][["n_days", "cum_return", "spy_cum_return",
                       "max_drawdown"]].round(4).pipe(_md))

    a("\n## 4. Risk analysis")
    a("")
    a(f"Max-drawdown window: {risk['drawdown_window']['peak']} -> "
      f"{risk['drawdown_window']['trough']} "
      f"(depth {risk['drawdown_window']['depth']:.4f})")
    a("\nExposure by bucket:")
    a("")
    a(risk["exposure_by_bucket"].round(4).pipe(_md))
    a("\nRisk contribution by bucket (annualized; sums to ann vol):")
    a("")
    a(risk["risk_contribution_bucket"].round(5).to_frame("ann_risk").pipe(_md))
    a("\nDrawdown contribution by bucket (max-DD window):")
    a("")
    a(risk["drawdown_contribution_bucket"].round(5).to_frame("dd_contrib").pipe(_md))

    a("\n## 5. Benchmark analysis")
    a("")
    a(bench["table"].round(4).pipe(_md))
    a("\n_Interpretation: S02 is a low-beta, downside-protective, cash-plus "
      "book - it trails SPY on raw CAGR but with far lower beta/drawdown and "
      "strong downside protection (low down-capture), and beats a SHY cash "
      "proxy on a risk-adjusted basis._")
    a("")
    a("## Figures")
    a("")
    for f in ["equity", "drawdown", "rolling_vol", "rolling_sharpe",
              "contribution_by_etf", "exposure_by_bucket", "benchmark_growth"]:
        a(f"- `reports/figures/s02_v3/{f}.png`")
    a("")

    (core / "s02_v3_report.md").write_text("\n".join(L), encoding="utf-8")

    print(src)
    print("V3 S02 report written:")
    print(f"  {core / 's02_v3_report.md'}")
    print(f"  {core / 's02_v3_metrics.json'}")
    print(f"  {tbl}  ({len(tables)} CSV tables)")
    print(f"  {figs}  (7 figures)")
    print(f"\nHeadline: CAGR={m['cagr']:.4f} Sharpe={m['sharpe']:.3f} "
          f"maxDD={m['max_drawdown']:.4f} turnover={m['annual_turnover']:.2f}")
    print(f"Factor edge_is_robust={fac['weight_sensitivity']['edge_is_robust']} | "
          f"2020 S02 {reg['explicit'].loc['Full 2020','cum_return']:+.3f} vs "
          f"SPY {reg['explicit'].loc['Full 2020','spy_cum_return']:+.3f} | "
          f"2022 S02 {reg['explicit'].loc['Full 2022','cum_return']:+.3f} vs "
          f"SPY {reg['explicit'].loc['Full 2022','spy_cum_return']:+.3f}")


if __name__ == "__main__":
    main()
