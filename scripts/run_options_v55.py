"""V5.5 rolling-window stability analysis on the frozen SPY Jan-Jun 2022 corpus.

Tests whether the V5.3/V5.4 strategy results are STABLE or HIGHLY DEPENDENT on
start-week / entry timing.

Method
------
- Identify every ISO week's first trading day in the frozen V5.2 Stage 1 SPY
  corpus.
- For each (strategy, start_week_offset), slice the chain to start from that
  week and run the same engine with the same defaults. No parameter
  optimization. No engine logic change. No strategy default change.
- Aggregate the distribution of total returns / max drawdowns / trade counts
  / rejection counts across all valid offsets.

Falsification logic
-------------------
If a baseline result (e.g. bear_put +0.65% at offset 0) collapses or flips
sign across the offset distribution, that baseline is **not stable evidence
of edge**. The V5.5 summary states this explicitly per strategy.

Guardrails
----------
- LIVE_TRADING_ENABLED stays False.
- No new data fetched, no ThetaData calls, no broker / live / IBKR code.
- No new strategies, no naked / unlimited-risk structures.
- No parameter optimization. NO start offset is recommended -- this is a
  falsification diagnostic, not a tuning step.

Outputs
-------
reports/options/v55_stability/
  - v55_summary.md
  - rolling_window_results.csv
  - stability_summary.csv
  - shifted_trade_counts.csv
  - shifted_rejection_summary.csv

Usage::

    python scripts/run_options_v55.py
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from quantbot.costs.transaction_costs import OptionsCostModel
from quantbot.data.options_cache import read_processed
from quantbot.options.backtest_engine import (
    OptionsBacktestEngine,
    OptionsBacktestResult,
)
from quantbot.options.risk import OptionsRiskLimits
from quantbot.options.strategies.spy_bear_put import SPYBearPutSpread
from quantbot.options.strategies.spy_bull_call import SPYBullCallSpread
from quantbot.options.strategies.spy_bull_put import SPYBullPutSpread


LIVE_TRADING_ENABLED = False
OUT_DIR = ROOT / "reports" / "options" / "v55_stability"
TRADING_DAYS_PER_YEAR = 252

# Minimum number of forward trading days after the start week, so each
# shifted run can still attempt several entries / exits. With weekly cadence
# and DTE 30-45 entries that close at DTE <= 21, ~6 forward weeks gives the
# strategy room to make 4-6 entries before the final bar force-close.
MIN_FORWARD_TRADING_DAYS = 30


STRATEGY_FACTORIES: dict[str, Callable[..., Any]] = {
    "bull_call": SPYBullCallSpread,
    "bear_put":  SPYBearPutSpread,
    "bull_put":  SPYBullPutSpread,
}


def load_spy_chain_2022_h1() -> pd.DataFrame:
    parts = []
    for m in range(1, 7):
        df = read_processed("SPY", 2022, m)
        if df is None:
            raise FileNotFoundError(f"Missing SPY 2022-{m:02d} processed file.")
        parts.append(df)
    df = pd.concat(parts, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df["expiration"] = pd.to_datetime(df["expiration"]).dt.normalize()
    return df


def iso_week_starts(dates: list[pd.Timestamp]) -> list[pd.Timestamp]:
    """Return the FIRST trading day in each distinct ISO week within ``dates``.
    The result is sorted ascending and contains one date per ISO week."""
    out: list[pd.Timestamp] = []
    seen: set = set()
    for d in sorted(dates):
        iso = (d.isocalendar().year, d.isocalendar().week)
        if iso not in seen:
            seen.add(iso)
            out.append(d)
    return out


# --------------------------------------------------------------------------- #
@dataclass
class RunOut:
    strategy: str
    start_offset: int
    start_date: pd.Timestamp
    result: OptionsBacktestResult


def run_one(
    chain: pd.DataFrame, strategy_name: str, *,
    start_offset: int, start_date: pd.Timestamp,
    initial_capital: float = 100_000.0,
) -> RunOut:
    factory = STRATEGY_FACTORIES[strategy_name]
    strat = factory()                   # FRESH instance per run (no shared state)
    limits = OptionsRiskLimits()        # ALL DEFAULTS
    cost = OptionsCostModel()           # ALL DEFAULTS
    engine = OptionsBacktestEngine(
        chain, strat,
        initial_capital=initial_capital,
        limits=limits, cost_model=cost,
    )
    res = engine.run()
    return RunOut(strategy=strategy_name, start_offset=start_offset,
                   start_date=start_date, result=res)


def sharpe(daily_returns: pd.Series) -> float:
    r = daily_returns.dropna()
    if len(r) < 2:
        return float("nan")
    sd = r.std(ddof=1)
    if sd == 0 or math.isnan(sd):
        return float("nan")
    return float(r.mean() / sd * math.sqrt(TRADING_DAYS_PER_YEAR))


def headline_row(run: RunOut) -> dict:
    r = run.result
    trades_df = r.to_trades_frame()
    wins = trades_df[trades_df["realized_pnl"] > 0] if not trades_df.empty else trades_df
    losses = trades_df[trades_df["realized_pnl"] < 0] if not trades_df.empty else trades_df
    return {
        "strategy": run.strategy,
        "start_offset_weeks": run.start_offset,
        "first_decision_date": str(run.start_date.date()),
        "trading_days": int(len(r.equity_curve)),
        "trades": r.n_trades,
        "rejections": len(r.rejections),
        "final_equity": (float(r.equity_curve.iloc[-1])
                          if len(r.equity_curve) else float("nan")),
        "total_return_pct": r.total_return * 100,
        "max_drawdown_pct": r.max_drawdown() * 100,
        "sharpe_annualized": sharpe(r.daily_returns),
        "win_rate": ((len(wins) / len(trades_df))
                      if len(trades_df) else float("nan")),
        "avg_trade_pnl": (float(trades_df["realized_pnl"].mean())
                           if len(trades_df) else float("nan")),
        "worst_trade_pnl": (float(trades_df["realized_pnl"].min())
                             if len(trades_df) else float("nan")),
        "best_trade_pnl": (float(trades_df["realized_pnl"].max())
                            if len(trades_df) else float("nan")),
        "total_cost": r.total_cost,
    }


def trade_count_row(run: RunOut) -> dict:
    r = run.result
    return {
        "strategy": run.strategy,
        "start_offset_weeks": run.start_offset,
        "first_decision_date": str(run.start_date.date()),
        "trades": r.n_trades,
        "wins": sum(1 for t in r.trades if t.realized_pnl > 0),
        "losses": sum(1 for t in r.trades if t.realized_pnl < 0),
        "zero_pnl": sum(1 for t in r.trades if t.realized_pnl == 0),
        "n_force_close": sum(1 for t in r.trades
                              if t.close_reason == "force_close_final_bar"),
        "n_expiration": sum(1 for t in r.trades
                             if t.close_reason == "expiration"),
        "n_dte_exit": sum(1 for t in r.trades
                           if t.close_reason == "dte_exit"),
        "n_profit_target": sum(1 for t in r.trades
                                if t.close_reason == "profit_target"),
        "n_stop_loss": sum(1 for t in r.trades
                            if t.close_reason == "stop_loss"),
    }


def rejection_rows(run: RunOut) -> list[dict]:
    if not run.result.rejections:
        return []
    rdf = pd.DataFrame([{
        "strategy": run.strategy,
        "start_offset_weeks": run.start_offset,
        "first_decision_date": str(run.start_date.date()),
        "stage": x.stage,
        "reason": x.reason,
    } for x in run.result.rejections])
    return rdf.groupby(
        ["strategy", "start_offset_weeks", "first_decision_date",
         "stage", "reason"]
    ).size().rename("n").reset_index().to_dict("records")


# --------------------------------------------------------------------------- #
def stability_summary(rolling_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate distribution stats per strategy across all valid offsets."""
    rows = []
    for strat, g in rolling_df.groupby("strategy"):
        n = len(g)
        rows.append({
            "strategy": strat,
            "n_runs": n,
            "mean_total_return_pct": float(g["total_return_pct"].mean()),
            "median_total_return_pct": float(g["total_return_pct"].median()),
            "std_total_return_pct": float(g["total_return_pct"].std(ddof=1))
                                      if n > 1 else float("nan"),
            "min_total_return_pct": float(g["total_return_pct"].min()),
            "max_total_return_pct": float(g["total_return_pct"].max()),
            "pct_runs_positive": float((g["total_return_pct"] > 0).mean()),
            "pct_runs_negative": float((g["total_return_pct"] < 0).mean()),
            "mean_max_drawdown_pct": float(g["max_drawdown_pct"].mean()),
            "worst_max_drawdown_pct": float(g["max_drawdown_pct"].min()),
            "mean_trade_count": float(g["trades"].mean()),
            "median_trade_count": float(g["trades"].median()),
        })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
def _df_to_md(df: pd.DataFrame, float_fmt: str = "{:.4f}") -> str:
    """GitHub-flavoured Markdown table without the ``tabulate`` package."""
    if df.empty:
        return "_(empty)_"

    def fmt(v: Any) -> str:
        if v is None:
            return ""
        if isinstance(v, float):
            return "nan" if math.isnan(v) else float_fmt.format(v)
        if isinstance(v, (np.floating,)):
            f = float(v)
            return "nan" if math.isnan(f) else float_fmt.format(f)
        return str(v)

    headers = [str(c) for c in df.columns]
    body = [[fmt(v) for v in row] for row in df.itertuples(index=False, name=None)]
    widths = [max(len(h), *(len(r[i]) for r in body)) for i, h in enumerate(headers)]

    def line(cells: list[str]) -> str:
        return "| " + " | ".join(c.ljust(w) for c, w in zip(cells, widths)) + " |"

    sep = "| " + " | ".join("-" * w for w in widths) + " |"
    return "\n".join([line(headers), sep] + [line(r) for r in body])


# --------------------------------------------------------------------------- #
def write_summary_md(
    out_path: Path, *,
    rolling: pd.DataFrame, stability: pd.DataFrame,
    counts: pd.DataFrame, rejections: pd.DataFrame,
    baseline_offsets: dict[str, dict],
) -> None:
    lines: list[str] = []
    lines.append("# V5.5 Rolling-window stability analysis — SPY Jan–Jun 2022 (frozen V5.2 Stage 1)\n")
    lines.append(
        "Engine: V5.0 (unchanged). Strategy defaults: unchanged. "
        "Cost model: default. Spread filter: default. "
        "**No start offset is being recommended** — this is a falsification "
        "diagnostic, not a tuning step.\n"
    )
    lines.append(
        f"**Guardrails:** `LIVE_TRADING_ENABLED = {LIVE_TRADING_ENABLED}`, "
        "no broker / live / IBKR, no new data fetch, no ThetaData calls, "
        "no naked or unlimited-risk structures, no parameter optimization.\n"
    )

    lines.append("\n## 1. Baseline confirmation (offset = 0)\n")
    lines.append(
        "The `start_offset_weeks=0` row for each strategy below must "
        "match the V5.3 / V5.4 archived baseline. Comparison vs V5.4 "
        "archive:\n"
    )
    bl_md = pd.DataFrame([
        {"strategy": k, "v54_baseline_pct": v["v54"],
         "v55_offset0_pct": v["v55"],
         "match": "OK" if abs(v["v54"] - v["v55"]) < 1e-6 else "MISMATCH"}
        for k, v in baseline_offsets.items()
    ])
    lines.append(_df_to_md(bl_md))

    lines.append("\n## 2. Rolling-window results (one row per shifted run)\n")
    cols = ["strategy", "start_offset_weeks", "first_decision_date",
            "trading_days", "trades", "rejections", "total_return_pct",
            "max_drawdown_pct", "win_rate", "final_equity", "total_cost"]
    lines.append(_df_to_md(rolling[cols].sort_values(
        ["strategy", "start_offset_weeks"]).reset_index(drop=True)))

    lines.append("\n## 3. Stability summary (distribution per strategy)\n")
    stab_md = stability.copy()
    cols = ["strategy", "n_runs", "mean_total_return_pct",
            "median_total_return_pct", "std_total_return_pct",
            "min_total_return_pct", "max_total_return_pct",
            "pct_runs_positive", "mean_max_drawdown_pct",
            "mean_trade_count"]
    lines.append(_df_to_md(stab_md[cols]))

    # Falsification verdict per strategy
    lines.append("\n### Stability verdict per strategy\n")
    verdicts: list[str] = []
    for _, r in stability.iterrows():
        strat = r["strategy"]
        mu = r["mean_total_return_pct"]
        sd = r["std_total_return_pct"]
        rng = r["max_total_return_pct"] - r["min_total_return_pct"]
        pos = r["pct_runs_positive"] * 100
        sign_consistent = pos in (0.0, 100.0)
        verdict_parts = [
            f"- **`{strat}`**:",
            f"mean **{mu:+.3f}%**, std **{sd:.3f}%**, "
            f"range **{rng:.3f} pp** "
            f"(min {r['min_total_return_pct']:+.3f}%, "
            f"max {r['max_total_return_pct']:+.3f}%); "
            f"{pos:.0f}% of runs positive.",
        ]
        if not sign_consistent:
            verdict_parts.append(
                "**Sign is NOT stable across start offsets** — "
                "baseline result depends on entry timing."
            )
        elif sd > abs(mu):
            verdict_parts.append(
                "Sign consistent but **std exceeds the mean in magnitude** — "
                "result is high-variance / noisy."
            )
        else:
            verdict_parts.append(
                "Sign consistent across all offsets; "
                "however n is small and these are NOT independent observations "
                "(overlapping windows share most of the chain)."
            )
        verdicts.append(" ".join(verdict_parts))
    lines.append("\n".join(verdicts))

    lines.append("\n## 4. Bear_put falsification check\n")
    bp = stability[stability["strategy"] == "bear_put"].iloc[0]
    bp_pos = bp["pct_runs_positive"] * 100
    lines.append(
        f"bear_put baseline (offset 0) total return: "
        f"**{baseline_offsets['bear_put']['v55']:+.4f}%**. "
        f"Across {int(bp['n_runs'])} shifted starts: "
        f"mean **{bp['mean_total_return_pct']:+.3f}%**, "
        f"min **{bp['min_total_return_pct']:+.3f}%**, "
        f"max **{bp['max_total_return_pct']:+.3f}%**, "
        f"std **{bp['std_total_return_pct']:.3f}%**, "
        f"**{bp_pos:.0f}%** of runs positive."
    )
    if bp_pos == 100:
        lines.append(
            "\n**Bear_put remains positive across every shifted start.** "
            "This is consistent with a regime-explained outcome on a "
            "structurally bearish strategy over a bear-market window. It is "
            "still NOT a strategy-edge claim — wider data (non-bear regimes) "
            "is required for falsification."
        )
    elif bp_pos == 0:
        lines.append(
            "\n**Bear_put is negative across every shifted start.** "
            "The baseline +0.65% result was the only positive run. Baseline "
            "is unstable and should not be treated as edge."
        )
    else:
        lines.append(
            f"\n**Bear_put sign is NOT stable across start offsets** "
            f"({bp_pos:.0f}% positive, {100-bp_pos:.0f}% negative). The "
            "baseline +0.65% is an artifact of a specific entry schedule "
            "and is NOT evidence of edge."
        )

    lines.append("\n## 5. Timing sensitivity ranking\n")
    sens = stability.sort_values(
        "std_total_return_pct", ascending=False)[
        ["strategy", "std_total_return_pct",
         "mean_total_return_pct", "min_total_return_pct",
         "max_total_return_pct"]
    ].reset_index(drop=True)
    lines.append("Ranked by std of total return across offsets "
                  "(largest std = most timing-sensitive):\n")
    lines.append(_df_to_md(sens))

    lines.append("\n## 6. Shifted trade counts (close-reason breakdown)\n")
    cnt_cols = ["strategy", "start_offset_weeks", "first_decision_date",
                "trades", "wins", "losses", "n_force_close",
                "n_dte_exit", "n_profit_target", "n_stop_loss"]
    lines.append(_df_to_md(counts[cnt_cols].sort_values(
        ["strategy", "start_offset_weeks"]).reset_index(drop=True)))

    lines.append("\n## 7. Shifted rejection summary\n")
    if rejections.empty:
        lines.append("_(no rejections logged)_")
    else:
        rej_agg = rejections.groupby(
            ["strategy", "stage", "reason"]).agg(
            total_rejections=("n", "sum"),
            n_offsets_seen=("start_offset_weeks", "nunique"),
        ).reset_index().sort_values(
            ["strategy", "total_rejections"], ascending=[True, False])
        lines.append(_df_to_md(rej_agg))

    lines.append("\n## 8. NON-claims (explicit)\n")
    lines.append(
        "- Shifted-start runs are **NOT independent**. Adjacent offsets "
        "share most of the data, so std and range understate the true "
        "uncertainty of any edge claim.\n"
        "- This analysis does **NOT** evaluate the strategies on non-bear "
        "regimes. A different macro regime could invert the signs entirely.\n"
        "- No start offset is being **recommended** as a tunable parameter. "
        "The whole point is to test whether the baseline offset of 0 was "
        "lucky or representative.\n"
        "- 8-13 trades per run is still too small for statistical claims. "
        "Sharpe ratios are reported as diagnostics, not evidence."
    )

    out_path.write_text("\n".join(lines), encoding="utf-8")


# --------------------------------------------------------------------------- #
def main() -> int:
    assert LIVE_TRADING_ENABLED is False, "V5.5 is RESEARCH only."
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    chain = load_spy_chain_2022_h1()
    all_dates = sorted(chain["date"].unique().tolist())
    week_starts = iso_week_starts(all_dates)
    last_date = all_dates[-1]
    print(f"V5.5 stability  |  SPY chain: {len(chain):,} rows, "
          f"{len(all_dates)} dates, {len(week_starts)} ISO weeks "
          f"({all_dates[0].date()} -> {last_date.date()})")
    print(f"Outputs -> {OUT_DIR}")

    # Determine the set of feasible offsets:
    # every week_start where >= MIN_FORWARD_TRADING_DAYS trading days remain
    # in the chain after that start.
    offsets: list[tuple[int, pd.Timestamp]] = []
    for k, ws in enumerate(week_starts):
        n_forward = sum(1 for d in all_dates if d >= ws)
        if n_forward >= MIN_FORWARD_TRADING_DAYS:
            offsets.append((k, pd.Timestamp(ws)))
    print(f"\nFeasible start offsets: {len(offsets)} "
          f"(week 0 = {offsets[0][1].date()} -> "
          f"week {offsets[-1][0]} = {offsets[-1][1].date()}; "
          f">= {MIN_FORWARD_TRADING_DAYS} forward trading days)")

    rolling_rows: list[dict] = []
    count_rows: list[dict] = []
    rejection_rows_all: list[dict] = []

    # Track baseline (offset 0) per strategy for comparison vs V5.4
    V54_BASELINE_PCT = {
        "bull_call": -1.2658,
        "bear_put":   0.6490,
        "bull_put":  -1.4701,
    }
    baseline_table: dict[str, dict] = {}

    for strat_name in STRATEGY_FACTORIES.keys():
        print(f"\n--- {strat_name} ---")
        for k, ws in offsets:
            sliced = chain[chain["date"] >= ws]
            run = run_one(sliced, strat_name,
                           start_offset=k, start_date=ws)
            h = headline_row(run)
            rolling_rows.append(h)
            count_rows.append(trade_count_row(run))
            rejection_rows_all.extend(rejection_rows(run))
            if k == 0:
                baseline_table[strat_name] = {
                    "v54": V54_BASELINE_PCT[strat_name],
                    "v55": h["total_return_pct"],
                }
            print(f"  offset={k:2d}  start={ws.date()}  "
                  f"trades={h['trades']:2d}  "
                  f"ret={h['total_return_pct']:+7.4f}%  "
                  f"dd={h['max_drawdown_pct']:+7.4f}%  "
                  f"win={(h['win_rate'] or 0)*100:4.1f}%")

    rolling_df = pd.DataFrame(rolling_rows)
    counts_df = pd.DataFrame(count_rows)
    rejections_df = pd.DataFrame(rejection_rows_all) \
        if rejection_rows_all else pd.DataFrame(
            columns=["strategy", "start_offset_weeks", "first_decision_date",
                     "stage", "reason", "n"]
        )
    stability_df = stability_summary(rolling_df)

    rolling_df.to_csv(OUT_DIR / "rolling_window_results.csv", index=False)
    counts_df.to_csv(OUT_DIR / "shifted_trade_counts.csv", index=False)
    rejections_df.to_csv(OUT_DIR / "shifted_rejection_summary.csv", index=False)
    stability_df.to_csv(OUT_DIR / "stability_summary.csv", index=False)
    print(f"\n  -> rolling_window_results.csv  ({len(rolling_df)} rows)")
    print(f"  -> shifted_trade_counts.csv     ({len(counts_df)} rows)")
    print(f"  -> shifted_rejection_summary.csv ({len(rejections_df)} rows)")
    print(f"  -> stability_summary.csv         ({len(stability_df)} rows)")

    write_summary_md(
        OUT_DIR / "v55_summary.md",
        rolling=rolling_df, stability=stability_df,
        counts=counts_df, rejections=rejections_df,
        baseline_offsets=baseline_table,
    )
    print(f"  -> v55_summary.md")

    # Baseline sanity check
    print("\n--- Baseline (offset 0) vs V5.4 archive ---")
    for strat, vals in baseline_table.items():
        match = "OK" if abs(vals["v54"] - vals["v55"]) < 1e-6 else "MISMATCH"
        print(f"  {strat:10s}  V5.4={vals['v54']:+.4f}%  "
              f"V5.5(offset 0)={vals['v55']:+.4f}%  [{match}]")

    print("\nV5.5 stability run complete.  No data fetched, "
          "no engine logic touched, no parameters optimized.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
