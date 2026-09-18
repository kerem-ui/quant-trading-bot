"""Tearsheet assembly: metrics + tables + stress + a Markdown report string."""

from __future__ import annotations

import pandas as pd

from ..backtest.performance import (
    compute_metrics,
    monthly_returns_table,
    yearly_returns,
)
from ..risk.stress import stress_period_returns

DISCLAIMER = (
    "Research/backtest only. No live trading. No profitability is promised. "
    "Costs, slippage, spread (and S03 borrow) are modelled but real-world "
    "results will differ. If run on synthetic data, results are illustrative "
    "only and not based on market data."
)


def build_tearsheet(
    result,
    title: str = "Backtest",
    data_source: str = "unknown",
    benchmarks: dict | None = None,
) -> dict:
    """Return a structured tearsheet dict.

    ``benchmarks``: optional {name: daily-return Series} (e.g. S02 and SPY
    buy-&-hold). When provided, a benchmark-comparison table is added.
    """
    metrics = compute_metrics(result)
    ts = {
        "title": title,
        "data_source": data_source,
        "disclaimer": DISCLAIMER,
        "config": result.config,
        "metrics": metrics,
        "yearly_returns": yearly_returns(result.returns),
        "monthly_returns": monthly_returns_table(result.returns),
        "stress_periods": stress_period_returns(result.returns),
        "risk_events": result.risk_events,
        "benchmark_comparison": None,
        # V2.1 diagnostics (degrade gracefully on older result objects).
        "exposure_diagnostics": result.exposure_diagnostics()
        if hasattr(result, "exposure_diagnostics") else None,
        "turnover_attribution": result.turnover_attribution()
        if hasattr(result, "turnover_attribution") else None,
        "cost_attribution": result.cost_attribution()
        if hasattr(result, "cost_attribution") else None,
        "pnl_components": result.pnl_components.sum()
        if hasattr(result, 'pnl_components') and not result.pnl_components.empty else None,
    }
    if benchmarks:
        from .benchmark import compare_to_benchmarks

        ts["benchmark_comparison"] = compare_to_benchmarks(result.returns, benchmarks)
    return ts


def _fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:,.4f}"
    return str(v)


def tearsheet_to_markdown(ts: dict) -> str:
    m = ts["metrics"]
    lines = [
        f"# {ts['title']}",
        "",
        f"> {ts['disclaimer']}",
        "",
        f"**Data source:** {ts['data_source']}  ",
        f"**Config:** `{ts['config']}`",
        "",
        "## Headline metrics",
        "",
        "| Metric | Value |",
        "|---|---|",
    ]
    key_order = [
        "start", "end", "n_days", "initial_capital", "final_equity",
        "total_return", "cagr", "annual_vol", "sharpe", "sortino",
        "max_drawdown", "max_dd_duration_days", "calmar", "ulcer_index",
        "win_rate", "avg_win", "avg_loss", "hist_var_95", "hist_es_95",
        "annual_turnover", "total_transaction_cost", "short_borrow_cost", "financing_cost",
        "total_cost", "cost_drag_pct_of_initial",
        "avg_gross_exposure", "avg_net_exposure", "n_risk_events",
    ]
    for k in key_order:
        if k in m:
            lines.append(f"| {k} | {_fmt(m[k])} |")

    yr = ts["yearly_returns"]
    if len(yr):
        lines += ["", "## Yearly returns", "", "| Year | Return |", "|---|---|"]
        lines += [f"| {y} | {r:,.2%} |" for y, r in yr.items()]

    sp = ts["stress_periods"]
    if isinstance(sp, pd.DataFrame) and not sp.empty:
        lines += ["", "## Stress periods", "",
                  "| Window | Days | Cumulative | Worst day |", "|---|---|---|---|"]
        for _, row in sp.iterrows():
            lines.append(
                f"| {row['window']} | {int(row['n_days'])} | "
                f"{row['cumulative_return']:,.2%} | {row['worst_day']:,.2%} |"
            )

    ed = ts.get("exposure_diagnostics")
    if ed:
        lines += [
            "", "## Exposure diagnostics", "",
            "| Measure | Value |", "|---|---|",
            f"| all-day avg gross | {ed['all_day_avg_gross']:.4f} |",
            f"| all-day avg net | {ed['all_day_avg_net']:.4f} |",
            f"| days / active days | {ed['n_days']} / {ed['n_active_days']} "
            f"({ed['active_day_fraction']:.1%}) |",
        ]
        if ed.get("n_active_days"):
            lines += [
                f"| active-day avg gross | {ed['active_avg_gross']:.4f} |",
                f"| active-day median gross | {ed['active_median_gross']:.4f} |",
                f"| active-day max gross | {ed['active_max_gross']:.4f} |",
                f"| active-day avg net | {ed['active_avg_net']:.5f} |",
                f"| active-day \\|net\\|/gross | {ed['active_abs_net_over_gross']:.4f} |",
            ]
        lines.append(
            "\n_All-day average understates an opportunistic book (e.g. S03 is "
            "flat most days); the active-day figures are the honest gauge._"
        )

    ta = ts.get("turnover_attribution")
    if ta:
        lines += [
            "", "## Turnover attribution (one-way |Δw|)", "",
            "| Component | Annualised | Share |", "|---|---|---|",
            f"| entries | {ta['annual_entry']:.3f} | {ta['entry_pct']:.1%} |",
            f"| exits | {ta['annual_exit']:.3f} | {ta['exit_pct']:.1%} |",
            f"| resizing/rotation | {ta['annual_resize']:.3f} | {ta['resize_pct']:.1%} |",
        ]

    ca = ts.get("cost_attribution")
    if ca:
        lines += [
            "", "## Cost attribution", "",
            "| Component | $ |", "|---|---|",
            f"| trading (buy) | {ca['trading_buy_cost']:,.0f} |",
            f"| trading (sell) | {ca['trading_sell_cost']:,.0f} |",
            f"| trading total | {ca['trading_cost']:,.0f} |",
            f"| borrow (S03 short leg) | {ca['borrow_cost']:,.0f} "
            f"({ca['borrow_pct_of_total']:.1%} of total) |",
            f"| cash financing | {ca.get('financing_cost', 0):,.6f} |",
            f"| **total** | **{ca['total_cost']:,.0f}** |",
        ]

    bc = ts.get("benchmark_comparison")
    components = ts.get('pnl_components')
    if components is not None:
        lines += ['', '## Reconciled dollar P&L', '', '| Component | $ |', '|---|---:|']
        lines += [f'| {name} | {amount:,.6f} |' for name,amount in components.items()]

    if isinstance(bc, pd.DataFrame) and not bc.empty:
        cols = [
            "strat_sharpe", "bench_sharpe", "excess_cagr", "information_ratio",
            "beta_to_bench", "correlation", "tracking_error", "down_capture",
        ]
        cols = [c for c in cols if c in bc.columns]
        lines += [
            "", "## Benchmark comparison",
            "", "_Internal benchmark: S02. External: SPY buy-&-hold. "
            "Aligned on common dates._", "",
            "| Benchmark | " + " | ".join(cols) + " |",
            "|" + "---|" * (len(cols) + 1),
        ]
        for name, row in bc.iterrows():
            vals = " | ".join(
                f"{row[c]:,.4f}" if isinstance(row[c], (int, float)) and pd.notna(row[c])
                else str(row.get(c, ""))
                for c in cols
            )
            lines.append(f"| {name} | {vals} |")

    ev = ts["risk_events"]
    lines += ["", "## Risk events", "", f"Total risk interventions: **{len(ev)}**"]
    for e in ev[:15]:
        lines.append(f"- {pd.Timestamp(e['date']).date()}: {'; '.join(e['notes'])}")
    if len(ev) > 15:
        lines.append(f"- ... (+{len(ev) - 15} more)")
    lines.append("")
    return "\n".join(lines)
