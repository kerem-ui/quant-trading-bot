"""V5.6 non-overlapping window analysis on the frozen SPY Jan-Jun 2022 corpus.

Tests whether the bear_put baseline result survives in INDEPENDENT
sub-windows -- not just the overlapping shifted windows of V5.5.

Method
------
- Define non-overlapping date ranges on the V5.2 Stage 1 SPY corpus.
- For each (strategy, window) pair, slice the chain to that window ONLY
  (not "from window_start onward"), then run the same engine with the
  same defaults. Each run starts with fresh $100,000 capital.
- Aggregate per-window results.

Two splits are evaluated side-by-side (same data, different partitioning):
  3-window: Jan-Feb 2022 / Mar-Apr 2022 / May-Jun 2022
  2-window: Jan-Mar 2022 / Apr-Jun 2022

A "full period" baseline (Jan-Jun) is also run; its result must match the
V5.4 archive numbers exactly (sanity check that no engine state drifted).

Falsification logic
-------------------
If bear_put's positive baseline +0.65% is concentrated in one or two
months, the non-overlapping split will surface a window where it loses.
If bear_put is positive in EVERY independent window, that is stronger
than overlapping-window stability but STILL not a strategy-edge claim
(the whole period remains one bear-market regime).

Guardrails
----------
- LIVE_TRADING_ENABLED stays False.
- No new data fetched, no ThetaData calls.
- No broker / live / IBKR. No new strategies.
- No naked / unlimited-risk structures.
- No parameter optimization. Strategy defaults UNCHANGED.

Outputs
-------
reports/options/v56_nonoverlap/
  - v56_summary.md
  - nonoverlap_results.csv
  - window_summary.csv
  - nonoverlap_trade_counts.csv
  - nonoverlap_rejection_summary.csv

Usage::

    python scripts/run_options_v56.py
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
OUT_DIR = ROOT / "reports" / "options" / "v56_nonoverlap"
TRADING_DAYS_PER_YEAR = 252


STRATEGY_FACTORIES: dict[str, Callable[..., Any]] = {
    "bull_call": SPYBullCallSpread,
    "bear_put":  SPYBearPutSpread,
    "bull_put":  SPYBullPutSpread,
}


# --------------------------------------------------------------------------- #
# Non-overlapping windows (display-only labels; not promoted to anything)
# --------------------------------------------------------------------------- #
WINDOWS_3WAY: list[tuple[str, str, str, str]] = [
    # (split, label, start_inclusive, end_inclusive)
    ("3way", "Jan-Feb_2022", "2022-01-03", "2022-02-28"),
    ("3way", "Mar-Apr_2022", "2022-03-01", "2022-04-29"),
    ("3way", "May-Jun_2022", "2022-05-02", "2022-06-30"),
]
WINDOWS_2WAY: list[tuple[str, str, str, str]] = [
    ("2way", "Jan-Mar_2022", "2022-01-03", "2022-03-31"),
    ("2way", "Apr-Jun_2022", "2022-04-01", "2022-06-30"),
]
WINDOWS_FULL: list[tuple[str, str, str, str]] = [
    ("full", "Jan-Jun_2022_baseline", "2022-01-03", "2022-06-30"),
]
ALL_WINDOWS = WINDOWS_FULL + WINDOWS_3WAY + WINDOWS_2WAY

# Regime context, for the markdown summary (informational only)
REGIME_NOTES = {
    "Jan-Feb_2022":           "early drawdown / choppy down",
    "Mar-Apr_2022":           "March rebound then bear acceleration into April",
    "May-Jun_2022":           "vol shock + deeper drawdown to ~$365 trough",
    "Jan-Mar_2022":           "drawdown then mid-March rebound",
    "Apr-Jun_2022":           "sustained bear acceleration through vol shock",
    "Jan-Jun_2022_baseline":  "full 2022 H1 (whole bear leg)",
}

V54_BASELINE_PCT = {
    "bull_call": -1.2658,
    "bear_put":   0.6490,
    "bull_put":  -1.4701,
}


# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
@dataclass
class RunOut:
    strategy: str
    split: str
    window_label: str
    start: pd.Timestamp
    end: pd.Timestamp
    result: OptionsBacktestResult


def run_one(
    chain_window: pd.DataFrame, strategy_name: str, *,
    split: str, window_label: str,
    start: pd.Timestamp, end: pd.Timestamp,
    initial_capital: float = 100_000.0,
) -> RunOut:
    factory = STRATEGY_FACTORIES[strategy_name]
    strat = factory()                   # FRESH instance per run
    limits = OptionsRiskLimits()        # ALL DEFAULTS
    cost = OptionsCostModel()           # ALL DEFAULTS
    engine = OptionsBacktestEngine(
        chain_window, strat,
        initial_capital=initial_capital,
        limits=limits, cost_model=cost,
    )
    res = engine.run()
    return RunOut(strategy=strategy_name, split=split,
                   window_label=window_label, start=start, end=end,
                   result=res)


def sharpe(daily_returns: pd.Series) -> float:
    r = daily_returns.dropna()
    if len(r) < 2:
        return float("nan")
    sd = r.std(ddof=1)
    if sd == 0 or math.isnan(sd):
        return float("nan")
    return float(r.mean() / sd * math.sqrt(TRADING_DAYS_PER_YEAR))


def active_position_days(result: OptionsBacktestResult) -> int:
    """Number of trading days where any net Greek was non-zero."""
    if result.daily_greeks.empty:
        return 0
    nonzero = (result.daily_greeks.abs().sum(axis=1) > 1e-9)
    return int(nonzero.sum())


def causality_ok(result: OptionsBacktestResult) -> bool:
    return all(
        (o.get("decision_date") is None
         or pd.Timestamp(o["decision_date"]) < pd.Timestamp(o["fill_date"]))
        for o in result.orders
    )


def headline_row(run: RunOut) -> dict:
    r = run.result
    trades_df = r.to_trades_frame()
    wins = trades_df[trades_df["realized_pnl"] > 0] if not trades_df.empty else trades_df
    losses = trades_df[trades_df["realized_pnl"] < 0] if not trades_df.empty else trades_df
    return {
        "split": run.split,
        "window_label": run.window_label,
        "window_start": str(run.start.date()),
        "window_end": str(run.end.date()),
        "strategy": run.strategy,
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
        "active_position_days": active_position_days(r),
        "causality_ok": causality_ok(r),
    }


def trade_count_row(run: RunOut) -> dict:
    r = run.result
    return {
        "split": run.split,
        "window_label": run.window_label,
        "strategy": run.strategy,
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
        "split": run.split,
        "window_label": run.window_label,
        "strategy": run.strategy,
        "stage": x.stage,
        "reason": x.reason,
    } for x in run.result.rejections])
    return rdf.groupby(
        ["split", "window_label", "strategy", "stage", "reason"]
    ).size().rename("n").reset_index().to_dict("records")


def window_summary_rows(rolling_df: pd.DataFrame) -> pd.DataFrame:
    """Per-window cross-strategy summary: how each strategy fared in
    each window, side by side."""
    out_rows = []
    for (split, lbl), g in rolling_df.groupby(["split", "window_label"]):
        row = {
            "split": split,
            "window_label": lbl,
            "window_start": g["window_start"].iloc[0],
            "window_end": g["window_end"].iloc[0],
            "trading_days": int(g["trading_days"].iloc[0]),
        }
        for strat in ("bull_call", "bear_put", "bull_put"):
            sub = g[g["strategy"] == strat]
            if not sub.empty:
                row[f"{strat}_ret_pct"] = float(sub["total_return_pct"].iloc[0])
                row[f"{strat}_trades"] = int(sub["trades"].iloc[0])
                row[f"{strat}_dd_pct"] = float(sub["max_drawdown_pct"].iloc[0])
        out_rows.append(row)
    return pd.DataFrame(out_rows)


# --------------------------------------------------------------------------- #
def _df_to_md(df: pd.DataFrame, float_fmt: str = "{:.4f}") -> str:
    if df.empty:
        return "_(empty)_"

    def fmt(v: Any) -> str:
        if v is None:
            return ""
        if isinstance(v, bool):
            return "True" if v else "False"
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
    results: pd.DataFrame,
    window_summary: pd.DataFrame,
    counts: pd.DataFrame,
    rejections: pd.DataFrame,
    baseline_match: dict[str, dict],
) -> None:
    lines: list[str] = []
    lines.append("# V5.6 Non-overlapping window analysis — SPY Jan–Jun 2022 (frozen V5.2 Stage 1)\n")
    lines.append(
        "Engine: V5.0 (unchanged). Strategy defaults: unchanged. "
        "Cost model: default. Spread filter: default. Fresh $100,000 capital "
        "per (strategy, window) run. **No window is being recommended** -- "
        "this is a falsification diagnostic, not a tuning step.\n"
    )
    lines.append(
        f"**Guardrails:** `LIVE_TRADING_ENABLED = {LIVE_TRADING_ENABLED}`, "
        "no broker / live / IBKR, no new data fetch, no ThetaData calls, "
        "no new strategies, no naked or unlimited-risk structures, no "
        "parameter optimization.\n"
    )

    lines.append("\n## 1. Full-period baseline consistency check (must match V5.4)\n")
    lines.append(
        "The `Jan-Jun_2022_baseline` row for each strategy below must "
        "match the V5.4 / V5.5 archived baseline. Comparison:\n"
    )
    bm = pd.DataFrame([
        {"strategy": k,
         "v54_baseline_pct": v["v54"],
         "v56_full_pct": v["v56"],
         "match": "OK" if abs(v["v54"] - v["v56"]) < 1e-6 else "MISMATCH"}
        for k, v in baseline_match.items()
    ])
    lines.append(_df_to_md(bm))

    lines.append("\n## 2. Per-window per-strategy results\n")
    cols = ["split", "window_label", "window_start", "window_end",
            "trading_days", "strategy", "trades", "rejections",
            "total_return_pct", "max_drawdown_pct", "win_rate",
            "active_position_days", "final_equity", "total_cost",
            "causality_ok"]
    lines.append(_df_to_md(
        results[cols].sort_values(
            ["split", "window_label", "strategy"]).reset_index(drop=True)
    ))

    lines.append("\n## 3. Window summary (side-by-side per strategy)\n")
    cols = ["split", "window_label", "window_start", "window_end",
            "trading_days",
            "bull_call_ret_pct", "bull_call_trades",
            "bear_put_ret_pct",  "bear_put_trades",
            "bull_put_ret_pct",  "bull_put_trades"]
    lines.append(_df_to_md(window_summary[cols]))

    lines.append("\n## 4. Bear_put falsification per non-overlapping window\n")
    bp = results[results["strategy"] == "bear_put"].copy()
    bp_3 = bp[bp["split"] == "3way"][
        ["window_label", "window_start", "window_end", "trades",
         "total_return_pct", "max_drawdown_pct", "win_rate"]
    ].reset_index(drop=True)
    bp_2 = bp[bp["split"] == "2way"][
        ["window_label", "window_start", "window_end", "trades",
         "total_return_pct", "max_drawdown_pct", "win_rate"]
    ].reset_index(drop=True)
    lines.append("**3-way split (Jan-Feb / Mar-Apr / May-Jun):**\n")
    lines.append(_df_to_md(bp_3))
    lines.append("\n**2-way split (Jan-Mar / Apr-Jun):**\n")
    lines.append(_df_to_md(bp_2))

    bp_3_pos = int((bp_3["total_return_pct"] > 0).sum())
    bp_2_pos = int((bp_2["total_return_pct"] > 0).sum())
    bp_3_n = len(bp_3); bp_2_n = len(bp_2)
    if bp_3_pos == bp_3_n and bp_2_pos == bp_2_n:
        verdict = (
            f"\n**bear_put is positive in EVERY non-overlapping window** "
            f"({bp_3_pos}/{bp_3_n} in 3-way split, {bp_2_pos}/{bp_2_n} in "
            f"2-way split). This is **stronger than V5.5 rolling-window** "
            f"stability because these windows do NOT share data. It is "
            f"**still NOT a strategy-edge claim**: the entire test period "
            f"remains one broad bear-market regime, and a directionally "
            f"bearish strategy should mechanically win there regardless of "
            f"how the period is partitioned. Wider data (non-bear regimes) "
            f"is required for falsification."
        )
    elif bp_3_pos == 0 and bp_2_pos == 0:
        verdict = (
            "\n**bear_put is NEGATIVE in every non-overlapping window.** "
            "The V5.4/V5.5 +0.65% baseline was an artifact of the specific "
            "full-period schedule and does NOT survive partitioning. "
            "Treat the baseline as unstable; this is not edge."
        )
    else:
        verdict = (
            f"\n**bear_put fails on some windows.** "
            f"3-way: {bp_3_pos}/{bp_3_n} positive. "
            f"2-way: {bp_2_pos}/{bp_2_n} positive. "
            "Positivity is concentrated in specific sub-periods, not a "
            "uniform property of the period. The V5.4/V5.5 baseline is "
            "regime-pocket-concentrated, NOT independent evidence of edge."
        )
    lines.append(verdict)

    lines.append("\n## 5. Regime-directional consistency check\n")
    lines.append(
        "Expected directional behaviour given the SPY 2022 H1 bear:\n"
        "- bull_call: should struggle (long-call debit ages against the "
        "  underlying when SPY falls).\n"
        "- bear_put: should benefit (long-put debit gains when SPY falls).\n"
        "- bull_put: should struggle (short-put credit collected gets "
        "  overwhelmed by downside moves into the strike).\n"
    )
    regime_table = []
    for _, w in window_summary.iterrows():
        notes = REGIME_NOTES.get(w["window_label"], "")
        regime_table.append({
            "split": w["split"],
            "window_label": w["window_label"],
            "regime_context": notes,
            "bull_call_ret_pct": w["bull_call_ret_pct"],
            "bear_put_ret_pct": w["bear_put_ret_pct"],
            "bull_put_ret_pct": w["bull_put_ret_pct"],
            "expected_pattern": "bear_put > 0; bull_call & bull_put < 0",
            "matches_expected": (
                "Yes"
                if (w["bear_put_ret_pct"] > 0
                    and w["bull_call_ret_pct"] < 0
                    and w["bull_put_ret_pct"] < 0)
                else "Partial / No"
            ),
        })
    lines.append(_df_to_md(pd.DataFrame(regime_table)))

    lines.append("\n## 6. Trade-count breakdown by close reason\n")
    cnt_cols = ["split", "window_label", "strategy", "trades", "wins",
                "losses", "n_force_close", "n_dte_exit",
                "n_profit_target", "n_stop_loss"]
    lines.append(_df_to_md(counts[cnt_cols].sort_values(
        ["split", "window_label", "strategy"]).reset_index(drop=True)))

    lines.append("\n## 7. Rejection summary by window\n")
    if rejections.empty:
        lines.append("_(no rejections logged)_")
    else:
        rej_agg = rejections.groupby(
            ["split", "window_label", "strategy", "stage", "reason"]).agg(
            n=("n", "sum"),
        ).reset_index().sort_values(
            ["split", "window_label", "strategy", "n"],
            ascending=[True, True, True, False])
        lines.append(_df_to_md(rej_agg))

    lines.append("\n## 8. NON-claims (explicit)\n")
    lines.append(
        "- The 3-way and 2-way windows are NON-overlapping with respect to "
        "data, but they all sit inside the **same broad bear-market regime** "
        "(SPY drew down from ~$478 in Jan to ~$365 in late Jun). Surviving "
        "these windows is **NOT** evidence the strategy works in non-bear "
        "regimes.\n"
        "- Each window forces an engine FORCE-CLOSE at the window's last "
        "trading day for any position still open. This is part of the "
        "experiment design (windows are independent), not a strategy "
        "behaviour to optimise.\n"
        "- No window is being **recommended** as a tradable period; the "
        "splits exist only to test whether the baseline is regime-pocket-"
        "concentrated or distributed.\n"
        "- 1-7 trades per window is still too small for statistical claims."
    )

    out_path.write_text("\n".join(lines), encoding="utf-8")


# --------------------------------------------------------------------------- #
def main() -> int:
    assert LIVE_TRADING_ENABLED is False, "V5.6 is RESEARCH only."
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    chain = load_spy_chain_2022_h1()
    print(f"V5.6 nonoverlap  |  SPY chain: {len(chain):,} rows, "
          f"{chain['date'].nunique()} dates "
          f"({chain['date'].min().date()} -> {chain['date'].max().date()})")
    print(f"Outputs -> {OUT_DIR}")

    rolling_rows: list[dict] = []
    count_rows: list[dict] = []
    rejection_rows_all: list[dict] = []
    baseline_match: dict[str, dict] = {}

    for split, label, start_s, end_s in ALL_WINDOWS:
        start = pd.Timestamp(start_s)
        end = pd.Timestamp(end_s)
        chain_w = chain[(chain["date"] >= start) & (chain["date"] <= end)]
        n_days = chain_w["date"].nunique()
        print(f"\n--- split={split}  window={label}  "
              f"[{start.date()} .. {end.date()}]  trading_days={n_days} ---")
        for strat in STRATEGY_FACTORIES.keys():
            run = run_one(chain_w, strat,
                          split=split, window_label=label,
                          start=start, end=end)
            h = headline_row(run)
            rolling_rows.append(h)
            count_rows.append(trade_count_row(run))
            rejection_rows_all.extend(rejection_rows(run))
            if split == "full":
                baseline_match[strat] = {
                    "v54": V54_BASELINE_PCT[strat],
                    "v56": h["total_return_pct"],
                }
            print(f"  {strat:10s}  trades={h['trades']:2d}  "
                  f"ret={h['total_return_pct']:+7.4f}%  "
                  f"dd={h['max_drawdown_pct']:+7.4f}%  "
                  f"win={(h['win_rate'] or 0)*100:5.1f}%  "
                  f"act_days={h['active_position_days']:2d}  "
                  f"causal={h['causality_ok']}")

    results_df = pd.DataFrame(rolling_rows)
    counts_df = pd.DataFrame(count_rows)
    rejections_df = (pd.DataFrame(rejection_rows_all)
                      if rejection_rows_all else pd.DataFrame(
                          columns=["split", "window_label", "strategy",
                                   "stage", "reason", "n"]))
    window_summary_df = window_summary_rows(results_df)

    results_df.to_csv(OUT_DIR / "nonoverlap_results.csv", index=False)
    counts_df.to_csv(OUT_DIR / "nonoverlap_trade_counts.csv", index=False)
    rejections_df.to_csv(OUT_DIR / "nonoverlap_rejection_summary.csv", index=False)
    window_summary_df.to_csv(OUT_DIR / "window_summary.csv", index=False)
    print(f"\n  -> nonoverlap_results.csv          ({len(results_df)} rows)")
    print(f"  -> nonoverlap_trade_counts.csv     ({len(counts_df)} rows)")
    print(f"  -> nonoverlap_rejection_summary.csv ({len(rejections_df)} rows)")
    print(f"  -> window_summary.csv               ({len(window_summary_df)} rows)")

    write_summary_md(
        OUT_DIR / "v56_summary.md",
        results=results_df,
        window_summary=window_summary_df,
        counts=counts_df,
        rejections=rejections_df,
        baseline_match=baseline_match,
    )
    print(f"  -> v56_summary.md")

    print("\n--- Full-period baseline vs V5.4 archive ---")
    for strat, vals in baseline_match.items():
        match = "OK" if abs(vals["v54"] - vals["v56"]) < 1e-6 else "MISMATCH"
        print(f"  {strat:10s}  V5.4={vals['v54']:+.4f}%  "
              f"V5.6(full)={vals['v56']:+.4f}%  [{match}]")

    print("\nV5.6 non-overlapping window analysis complete.  No data fetched, "
          "no engine logic touched, no parameters optimized.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
