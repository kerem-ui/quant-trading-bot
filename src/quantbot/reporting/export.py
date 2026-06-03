"""Export a BacktestResult: Markdown report, CSV series, and figures."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from ..config import project_root
from .tearsheet import build_tearsheet, tearsheet_to_markdown


def export_report(
    result,
    name: str,
    *,
    title: str | None = None,
    data_source: str = "unknown",
    out_dir: str | Path | None = None,
    make_plots: bool = True,
    benchmarks: dict | None = None,
) -> dict:
    """Write report.md, metrics.json, equity/returns/weights CSVs and figures.

    ``benchmarks``: optional {name: daily-return Series} for the comparison
    section. Returns a dict of written paths.
    """
    out_dir = Path(out_dir) if out_dir else project_root() / "reports" / "backtests" / name
    out_dir.mkdir(parents=True, exist_ok=True)
    fig_dir = project_root() / "reports" / "figures" / name

    ts = build_tearsheet(
        result, title=title or name, data_source=data_source, benchmarks=benchmarks
    )
    written: dict[str, str] = {}

    md_path = out_dir / "report.md"
    md_path.write_text(tearsheet_to_markdown(ts), encoding="utf-8")
    written["report_md"] = str(md_path)

    (out_dir / "metrics.json").write_text(
        json.dumps(ts["metrics"], indent=2, default=str), encoding="utf-8"
    )
    written["metrics_json"] = str(out_dir / "metrics.json")

    result.equity_curve.to_csv(out_dir / "equity_curve.csv")
    result.returns.to_csv(out_dir / "returns.csv")
    result.weights.to_csv(out_dir / "weights.csv")
    ts["monthly_returns"].to_csv(out_dir / "monthly_returns.csv")
    if isinstance(ts["stress_periods"], pd.DataFrame):
        ts["stress_periods"].to_csv(out_dir / "stress_periods.csv", index=False)
    written["csv_dir"] = str(out_dir)

    if make_plots:
        try:
            from .plots import (
                plot_drawdown,
                plot_equity_curve,
                plot_exposure,
                plot_rolling_sharpe,
            )

            written["fig_equity"] = str(plot_equity_curve(result, fig_dir / "equity.png"))
            written["fig_drawdown"] = str(plot_drawdown(result, fig_dir / "drawdown.png"))
            written["fig_rolling_sharpe"] = str(
                plot_rolling_sharpe(result, fig_dir / "rolling_sharpe.png")
            )
            written["fig_exposure"] = str(plot_exposure(result, fig_dir / "exposure.png"))
        except Exception as exc:  # plotting must never break a backtest
            written["plot_error"] = repr(exc)

    return written
