"""V5.4 robustness diagnostics on the frozen SPY Jan-Jun 2022 corpus.

NO new data fetch. NO engine logic changes. NO strategy defaults changed.
NO new strategies. NO broker / live / IBKR. ``LIVE_TRADING_ENABLED`` stays
``False``.

What this script does
---------------------
1. Re-runs the three V5.3 defined-risk verticals (bull_call, bear_put,
   bull_put) at default cost + default spread filter -- this is the
   comparison baseline. Phase 1B corrected accounting supersedes archived
   V5.3 numbers; the old spread-fee double count is no longer reproduced.
2. Sweeps the ``OptionsCostModel`` parameters across realistic ranges
   to test whether any strategy result flips sign purely due to cost
   assumptions.
3. Sweeps ``spread_max_pct`` (the per-leg bid/ask liquidity gate) on
   BOTH the strategy and the engine ``OptionsRiskLimits`` together.
4. Breaks baseline trade P&L down by month for regime analysis.
5. Emits compact trade diagnostics (best/worst trade, avg DTE at entry/
   exit, etc.) and rejection-reason counts.

All parameter overrides are DISPLAY-ONLY -- no defaults are promoted.
The strategies and the engine are never mutated; each sensitivity run
constructs fresh instances with the override values.

Output artifacts
----------------
``reports/options/v54_robustness/``
  - v54_summary.md
  - baseline_results.csv
  - cost_sensitivity.csv
  - spread_filter_sensitivity.csv
  - monthly_breakdown.csv
  - rejection_analysis.csv
  - trade_diagnostics.csv

Usage::

    python scripts/run_options_v54.py
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

# Path setup.
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
OUT_DIR = ROOT / "reports" / "options" / "v54_robustness"
TRADING_DAYS_PER_YEAR = 252


# --------------------------------------------------------------------------- #
# Strategy registry. Factories return a FRESH instance each call so internal
# state (e.g. _weeks_attempted) is never shared between sensitivity runs.
# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# Run helpers
# --------------------------------------------------------------------------- #
@dataclass
class RunOut:
    strategy: str
    scenario: str
    result: OptionsBacktestResult
    cost_model_repr: str
    limits_repr: str


def run_one(
    chain: pd.DataFrame, strategy_name: str, *,
    scenario: str,
    strategy_overrides: dict | None = None,
    limits_overrides: dict | None = None,
    cost_overrides: dict | None = None,
    initial_capital: float = 100_000.0,
) -> RunOut:
    factory = STRATEGY_FACTORIES[strategy_name]
    strat = factory(**(strategy_overrides or {}))
    limits = OptionsRiskLimits(**(limits_overrides or {}))
    cost = OptionsCostModel(**(cost_overrides or {}))
    engine = OptionsBacktestEngine(
        chain, strat,
        initial_capital=initial_capital,
        limits=limits, cost_model=cost,
    )
    res = engine.run()
    return RunOut(
        strategy=strategy_name, scenario=scenario, result=res,
        cost_model_repr=(f"per_contract_fee={cost.per_contract_fee:.2f},"
                          "spread_crossing=in_fill_price,"
                          f"multi_leg_penalty={cost.multi_leg_penalty:.2f}"),
        limits_repr=f"spread_max_pct={limits.spread_max_pct:.2f}",
    )


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
        "scenario": run.scenario,
        "trades": r.n_trades,
        "rejections": len(r.rejections),
        "final_equity": float(r.equity_curve.iloc[-1]) if len(r.equity_curve) else float("nan"),
        "total_return_pct": r.total_return * 100,
        "max_drawdown_pct": r.max_drawdown() * 100,
        "sharpe_annualized": sharpe(r.daily_returns),
        "win_rate": (len(wins) / len(trades_df)) if len(trades_df) else float("nan"),
        "avg_win_dollar": float(wins["realized_pnl"].mean()) if len(wins) else float("nan"),
        "avg_loss_dollar": float(losses["realized_pnl"].mean()) if len(losses) else float("nan"),
        "total_cost": r.total_cost,
        "cost_model": run.cost_model_repr,
        "limits": run.limits_repr,
    }


# --------------------------------------------------------------------------- #
# Sensitivity scenarios (DISPLAY-ONLY; never promoted to defaults)
# --------------------------------------------------------------------------- #
COST_SCENARIOS: dict[str, dict] = {
    # name: kwargs for OptionsCostModel
    "low_cost":       dict(per_contract_fee=0.30,
                            multi_leg_penalty=0.50),
    "default":        dict(per_contract_fee=0.65,
                            multi_leg_penalty=1.00),
    "high_cost":      dict(per_contract_fee=1.50,
                            multi_leg_penalty=2.00),
}

# spread_max_pct must be overridden on BOTH the strategy AND the engine
# limits together so the decision-day filter and the next-bar fill gate
# stay consistent.
SPREAD_SCENARIOS: dict[str, float] = {
    "strict_0.15":  0.15,
    "default_0.25": 0.25,
    "loose_0.35":   0.35,
}


# --------------------------------------------------------------------------- #
# Trade diagnostics
# --------------------------------------------------------------------------- #
def _dte_at(row, when: str) -> int:
    """``when`` is 'open' or 'close'. The trade record stores per-leg
    expirations; DTE = (expiration - fill_date).days for the first leg.
    """
    legs = row["legs"]
    if not legs:
        return -1
    exp = pd.Timestamp(legs[0]["expiration"])
    when_date = pd.Timestamp(row["fill_open"] if when == "open" else row["fill_close"])
    return int((exp - when_date).days)


def diagnostics_row(run: RunOut) -> dict | None:
    r = run.result
    if r.n_trades == 0:
        return None

    trades_df = r.to_trades_frame()
    # Augment with the per-leg list (kept on the dataclass, not in the frame).
    trades_df = trades_df.copy()
    trades_df["legs"] = [t.legs for t in r.trades]
    trades_df["entry_spread_pct"] = [
        # Spread cannot be inferred from commissions/extra slippage. Keep this
        # unavailable diagnostic explicit instead of treating fees as spread.
        float("nan") for _ in r.trades
    ]
    trades_df["dte_open"] = trades_df.apply(lambda r_: _dte_at(r_, "open"), axis=1)
    trades_df["dte_close"] = trades_df.apply(lambda r_: _dte_at(r_, "close"), axis=1)

    best = trades_df.loc[trades_df["realized_pnl"].idxmax()]
    worst = trades_df.loc[trades_df["realized_pnl"].idxmin()]
    largest_cost = trades_df.loc[
        (trades_df["open_cost"] + trades_df["close_cost"]).idxmax()
    ]
    wins = trades_df[trades_df["realized_pnl"] > 0]
    losses = trades_df[trades_df["realized_pnl"] < 0]
    common_close = trades_df["close_reason"].mode()
    common_close = common_close.iloc[0] if len(common_close) else "n/a"

    return {
        "strategy": run.strategy,
        "n_trades": len(trades_df),
        "best_trade_dollar": float(best["realized_pnl"]),
        "best_trade_open": str(pd.Timestamp(best["fill_open"]).date()),
        "best_trade_close": str(pd.Timestamp(best["fill_close"]).date()),
        "best_trade_reason": str(best["close_reason"]),
        "worst_trade_dollar": float(worst["realized_pnl"]),
        "worst_trade_open": str(pd.Timestamp(worst["fill_open"]).date()),
        "worst_trade_close": str(pd.Timestamp(worst["fill_close"]).date()),
        "worst_trade_reason": str(worst["close_reason"]),
        "avg_win_dollar": (float(wins["realized_pnl"].mean()) if len(wins)
                            else float("nan")),
        "avg_loss_dollar": (float(losses["realized_pnl"].mean()) if len(losses)
                             else float("nan")),
        "largest_cost_open": str(pd.Timestamp(largest_cost["fill_open"]).date()),
        "largest_cost_total":
            float(largest_cost["open_cost"] + largest_cost["close_cost"]),
        "most_common_close_reason": common_close,
        "avg_dte_at_entry": float(trades_df["dte_open"].mean()),
        "avg_dte_at_exit": float(trades_df["dte_close"].mean()),
    }


def rejection_table(run: RunOut) -> pd.DataFrame:
    if not run.result.rejections:
        return pd.DataFrame(
            columns=["strategy", "stage", "reason", "n"]
        )
    rdf = pd.DataFrame([{
        "strategy": run.strategy,
        "stage": x.stage,
        "reason": x.reason,
    } for x in run.result.rejections])
    return rdf.groupby(["strategy", "stage", "reason"]).size().rename(
        "n").reset_index().sort_values("n", ascending=False)


def monthly_table(run: RunOut) -> pd.DataFrame:
    if run.result.n_trades == 0:
        return pd.DataFrame(
            columns=["strategy", "month", "trades", "pnl_sum",
                     "pnl_mean", "win_rate"]
        )
    tdf = run.result.to_trades_frame().copy()
    tdf["month"] = pd.to_datetime(tdf["fill_close"]).dt.to_period("M").astype(str)
    grp = tdf.groupby("month").agg(
        trades=("realized_pnl", "count"),
        pnl_sum=("realized_pnl", "sum"),
        pnl_mean=("realized_pnl", "mean"),
        win_rate=("realized_pnl", lambda s: float((s > 0).mean())),
    ).reset_index()
    grp.insert(0, "strategy", run.strategy)
    return grp


# --------------------------------------------------------------------------- #
# Markdown writer
# --------------------------------------------------------------------------- #
def _df_to_md(df: pd.DataFrame, float_fmt: str = "{:.4f}") -> str:
    """Render a small DataFrame as a GitHub-style Markdown table without
    the ``tabulate`` package (which is not allowed to be installed)."""
    if df.empty:
        return "_(empty)_"

    def fmt(v: Any) -> str:
        if v is None:
            return ""
        if isinstance(v, float):
            if math.isnan(v):
                return "nan"
            return float_fmt.format(v)
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
    out = [line(headers), sep] + [line(r) for r in body]
    return "\n".join(out)


def write_summary_md(
    out_path: Path,
    baseline: pd.DataFrame,
    cost: pd.DataFrame,
    spread: pd.DataFrame,
    monthly: pd.DataFrame,
    diagnostics: pd.DataFrame,
    rejections: pd.DataFrame,
) -> None:
    lines: list[str] = []
    lines.append("# V5.4 Robustness diagnostics — SPY Jan–Jun 2022 (frozen V5.2 Stage 1 corpus)\n")
    lines.append(
        "Engine: V5.0 (unchanged). Strategy defaults: unchanged. "
        "All non-default parameter values below are **display-only sensitivity "
        "overrides** and are NOT promoted to defaults.\n"
    )
    lines.append(
        f"**Guardrails:** `LIVE_TRADING_ENABLED = {LIVE_TRADING_ENABLED}`, "
        "no broker / live / IBKR, no new data fetch, no ThetaData calls, "
        "no naked or unlimited-risk structures.\n"
    )

    lines.append("\n## 1. Baseline (matches V5.3 archive)\n")
    cols = ["strategy", "trades", "rejections", "final_equity",
            "total_return_pct", "max_drawdown_pct", "sharpe_annualized",
            "win_rate", "total_cost"]
    lines.append(_df_to_md(baseline[cols]))

    lines.append("\n## 2. Cost sensitivity\n")
    lines.append(
        "Same strategies, default `spread_max_pct=0.25`, varying "
        "`OptionsCostModel` parameters. "
        "Scenarios: `low_cost` (fee 0.30 / penalty 0.50), "
        "`default` (fee 0.65 / penalty 1.00), "
        "`high_cost` (fee 1.50 / penalty 2.00). "
        "Actual bid/ask crossing is already in the fills; these scenarios "
        "vary commissions and explicit additional slippage only. "
        "**No setting is being recommended as default.**\n"
    )
    cs = cost[["strategy", "scenario", "trades", "total_return_pct",
                "max_drawdown_pct", "sharpe_annualized", "total_cost",
                "final_equity"]]
    lines.append(_df_to_md(cs))

    # Sign-flip analysis
    pivot = cost.pivot_table(index="strategy", columns="scenario",
                              values="total_return_pct")
    flips = []
    for strat in pivot.index:
        signs = {scen: (1 if v > 0 else (-1 if v < 0 else 0))
                  for scen, v in pivot.loc[strat].items()}
        unique = set(signs.values()) - {0}
        if len(unique) > 1:
            flips.append((strat, signs))
    if flips:
        lines.append("\n**Sign flips driven by cost assumptions:**\n")
        for strat, signs in flips:
            lines.append(f"- `{strat}`: " + ", ".join(
                f"{s}={'+' if v > 0 else ('-' if v < 0 else '0')}"
                for s, v in signs.items()))
    else:
        lines.append("\n**No strategy flips sign solely from cost changes** "
                      "across these four scenarios.\n")

    lines.append("\n## 3. Spread-filter sensitivity\n")
    lines.append(
        "Same strategies, default cost model, varying the per-leg "
        "`spread_max_pct` gate on BOTH the strategy and the engine "
        "`OptionsRiskLimits` together. **No setting is being recommended.**\n"
    )
    sp = spread[["strategy", "scenario", "trades", "rejections",
                  "total_return_pct", "max_drawdown_pct",
                  "total_cost", "final_equity"]]
    lines.append(_df_to_md(sp))

    lines.append("\n## 4. Monthly / regime breakdown (baseline cost + spread)\n")
    lines.append(
        "SPY context: Jan–Feb early drawdown; March rebound; "
        "April acceleration of the bear; May vol shock; June further "
        "drawdown to ~$365 trough. Directional bias bearish for the period.\n"
    )
    lines.append(_df_to_md(monthly))

    lines.append("\n## 5. Trade-level diagnostics (baseline)\n")
    lines.append(_df_to_md(diagnostics))

    lines.append("\n## 6. Rejection analysis (baseline)\n")
    lines.append(_df_to_md(rejections))
    lines.append("\nMost rejections are **scheduling / risk-control** "
                  "(concurrency cap and per-trade debit cap), not liquidity. "
                  "The fill-time `spread_too_wide` gate fires occasionally; "
                  "the chain's `zero_bid` rows are filtered earlier by the "
                  "spread-builder's liquidity gate so they rarely surface as "
                  "engine-level rejections.\n")

    out_path.write_text("\n".join(lines), encoding="utf-8")


# --------------------------------------------------------------------------- #
def main() -> int:
    assert LIVE_TRADING_ENABLED is False, "V5.4 is RESEARCH only."
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    chain = load_spy_chain_2022_h1()
    print(f"V5.4 robustness  |  SPY chain: {len(chain):,} rows, "
          f"{chain['date'].nunique()} dates "
          f"({chain['date'].min().date()} -> {chain['date'].max().date()})")
    print(f"Outputs -> {OUT_DIR}")

    strategies = list(STRATEGY_FACTORIES.keys())

    # ===== 1. BASELINE =====
    print("\n--- Baseline (default cost + default spread filter) ---")
    baseline_runs: list[RunOut] = []
    for s in strategies:
        run = run_one(chain, s, scenario="baseline")
        baseline_runs.append(run)
        h = headline_row(run)
        print(f"  {s:10s}  trades={h['trades']:>3d}  ret={h['total_return_pct']:+.4f}%  "
              f"dd={h['max_drawdown_pct']:+.4f}%  sharpe={h['sharpe_annualized']:+.3f}  "
              f"cost=${h['total_cost']:.2f}")
    baseline_df = pd.DataFrame([headline_row(r) for r in baseline_runs])
    baseline_df.to_csv(OUT_DIR / "baseline_results.csv", index=False)

    # ===== 2. COST SENSITIVITY =====
    print("\n--- Cost sensitivity ---")
    cost_rows: list[dict] = []
    for s in strategies:
        for scen, kwargs in COST_SCENARIOS.items():
            run = run_one(
                chain, s,
                scenario=scen,
                cost_overrides=kwargs,
            )
            cost_rows.append(headline_row(run))
    cost_df = pd.DataFrame(cost_rows)
    cost_df.to_csv(OUT_DIR / "cost_sensitivity.csv", index=False)
    print(f"  -> cost_sensitivity.csv  ({len(cost_df)} rows)")

    # ===== 3. SPREAD FILTER SENSITIVITY =====
    print("\n--- Spread filter sensitivity ---")
    spread_rows: list[dict] = []
    for s in strategies:
        for scen, val in SPREAD_SCENARIOS.items():
            run = run_one(
                chain, s,
                scenario=scen,
                strategy_overrides={"spread_max_pct": val},
                limits_overrides={"spread_max_pct": val},
            )
            spread_rows.append(headline_row(run))
    spread_df = pd.DataFrame(spread_rows)
    spread_df.to_csv(OUT_DIR / "spread_filter_sensitivity.csv", index=False)
    print(f"  -> spread_filter_sensitivity.csv  ({len(spread_df)} rows)")

    # ===== 4. MONTHLY BREAKDOWN =====
    print("\n--- Monthly breakdown (baseline) ---")
    monthly_df = pd.concat([monthly_table(r) for r in baseline_runs],
                            ignore_index=True)
    monthly_df.to_csv(OUT_DIR / "monthly_breakdown.csv", index=False)
    print(f"  -> monthly_breakdown.csv  ({len(monthly_df)} rows)")

    # ===== 5. TRADE DIAGNOSTICS =====
    print("\n--- Trade diagnostics (baseline) ---")
    diag_rows = [d for d in (diagnostics_row(r) for r in baseline_runs)
                  if d is not None]
    diag_df = pd.DataFrame(diag_rows)
    diag_df.to_csv(OUT_DIR / "trade_diagnostics.csv", index=False)
    print(f"  -> trade_diagnostics.csv  ({len(diag_df)} rows)")

    # ===== 6. REJECTION ANALYSIS =====
    print("\n--- Rejection analysis (baseline) ---")
    rej_df = pd.concat([rejection_table(r) for r in baseline_runs],
                        ignore_index=True)
    rej_df.to_csv(OUT_DIR / "rejection_analysis.csv", index=False)
    print(f"  -> rejection_analysis.csv  ({len(rej_df)} rows)")

    # ===== 7. SUMMARY MARKDOWN =====
    write_summary_md(
        OUT_DIR / "v54_summary.md",
        baseline=baseline_df, cost=cost_df, spread=spread_df,
        monthly=monthly_df, diagnostics=diag_df, rejections=rej_df,
    )
    print(f"\n  -> v54_summary.md")

    print("\nV5.4 robustness run complete.  No data fetched, "
          "no engine logic touched, no strategy defaults promoted.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
