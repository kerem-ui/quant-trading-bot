"""V5.3 strategy testing driver.

Runs the existing V5.0 ``OptionsBacktestEngine`` (UNCHANGED) on the frozen
V5.2 Stage 1 SPY corpus (Jan -> Jun 2022, already on disk under
``data/options/processed/SPY/2022/``).

This script is RESEARCH/BACKTEST ONLY:
  - SPY only.
  - Local processed CSV.gz only -- NO new ThetaData fetch.
  - No broker, no IBKR, no live trading.
  - ``LIVE_TRADING_ENABLED`` stays ``False``.
  - Strategy default parameters are NOT changed.
  - Defined-risk structures only (the existing risk gate rejects
    ``is_naked=True`` and unlimited-loss candidates).

Phase A (this initial version) reruns the SPY bull call spread on the full
Jan-Jun 2022 corpus, side-by-side with per-month and full-period sub-reports.
Bear put + bull put are added in subsequent updates once their builders are
tested.

Usage::

    python scripts/run_options_v53.py
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

# Path setup.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

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


# --------------------------------------------------------------------------- #
def load_spy_chain_2022_h1() -> pd.DataFrame:
    """Concatenate the V5.2 Stage 1 frozen SPY corpus (Jan -> Jun 2022)."""
    parts: list[pd.DataFrame] = []
    missing: list[str] = []
    for m in range(1, 7):
        df = read_processed("SPY", 2022, m)
        if df is None:
            missing.append(f"2022-{m:02d}")
        else:
            parts.append(df)
    if missing:
        raise FileNotFoundError(
            "Missing SPY processed file(s): " + ", ".join(missing)
            + ". V5.3 expects the V5.2 Stage 1 corpus on disk."
        )
    df = pd.concat(parts, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df["expiration"] = pd.to_datetime(df["expiration"]).dt.normalize()
    return df


def _fmt_money(x: float) -> str:
    return f"${x:,.2f}"


def _fmt_pct(x: float) -> str:
    return f"{x * 100:+.4f}%"


# --------------------------------------------------------------------------- #
@dataclass
class StrategyRun:
    name: str
    result: OptionsBacktestResult
    engine: OptionsBacktestEngine


def run_strategy(chain: pd.DataFrame, strategy, *,
                  name: str,
                  initial_capital: float = 100_000.0,
                  limits: OptionsRiskLimits | None = None,
                  cost_model: OptionsCostModel | None = None,
                  ) -> StrategyRun:
    eng = OptionsBacktestEngine(
        chain, strategy,
        initial_capital=initial_capital,
        limits=limits or OptionsRiskLimits(),
        cost_model=cost_model or OptionsCostModel(),
    )
    return StrategyRun(name=name, result=eng.run(), engine=eng)


# --------------------------------------------------------------------------- #
def _print_header(title: str) -> None:
    print("=" * 78)
    print(f" {title}")
    print("=" * 78)


def print_strategy_report(run: StrategyRun) -> None:
    r = run.result
    print(f"\n--- {run.name} :: headline ---")
    print(f"  Initial capital   : {_fmt_money(r.initial_capital)}")
    if len(r.equity_curve):
        print(f"  Final equity      : "
              f"{_fmt_money(float(r.equity_curve.iloc[-1]))}")
    print(f"  Total return      : {_fmt_pct(r.total_return)}")
    print(f"  Max drawdown      : {_fmt_pct(r.max_drawdown())}")
    print(f"  Total cost paid   : {_fmt_money(r.total_cost)}")
    print(f"  # trades closed   : {r.n_trades}")
    print(f"  # rejections      : {len(r.rejections)}")
    print(f"  # orders          : {len(r.orders)}")

    trades_df = r.to_trades_frame()
    if not trades_df.empty:
        cols = ["structure", "fill_open", "fill_close", "close_reason",
                "width", "net_entry_cash", "open_cost", "close_cost",
                "max_profit", "max_loss", "realized_pnl"]
        print(f"\n--- {run.name} :: per-trade table ---")
        with pd.option_context("display.max_rows", None,
                                "display.width", 170,
                                "display.float_format", "{:,.2f}".format):
            print(trades_df[cols].to_string(index=False))

        wins = trades_df[trades_df["realized_pnl"] > 0]
        losses = trades_df[trades_df["realized_pnl"] < 0]
        wr = len(wins) / len(trades_df) if len(trades_df) else float("nan")
        print(f"\n  Win rate          : {wr:.2%}  "
              f"({len(wins)}W / {len(losses)}L)")
        if len(wins):
            print(f"  Avg win           : "
                  f"{_fmt_money(float(wins['realized_pnl'].mean()))}")
        if len(losses):
            print(f"  Avg loss          : "
                  f"{_fmt_money(float(losses['realized_pnl'].mean()))}")
        wt = r.worst_trade()
        if wt is not None:
            print(f"  Worst trade       : {_fmt_money(wt.realized_pnl)} "
                  f"({wt.close_reason}, fill_open={wt.fill_open.date()})")

        # Per-month P&L breakdown
        if not trades_df["fill_close"].isna().all():
            tdf = trades_df.copy()
            tdf["month"] = pd.to_datetime(tdf["fill_close"]).dt.to_period("M")
            month_pnl = tdf.groupby("month").agg(
                trades=("realized_pnl", "count"),
                pnl_sum=("realized_pnl", "sum"),
                pnl_mean=("realized_pnl", "mean"),
            )
            print(f"\n--- {run.name} :: per-month realized P&L ---")
            with pd.option_context("display.float_format", "{:,.2f}".format):
                print(month_pnl.to_string())
    else:
        print(f"\n--- {run.name} :: per-trade table ---\n  (no closed trades)")

    if r.rejections:
        rej_df = pd.DataFrame([{
            "stage": x.stage, "reason": x.reason
        } for x in r.rejections])
        counts = rej_df.groupby(["stage", "reason"]).size().rename(
            "n").reset_index().sort_values("n", ascending=False)
        print(f"\n--- {run.name} :: rejection counts ---")
        print(counts.to_string(index=False))
    else:
        print(f"\n--- {run.name} :: rejection counts ---\n  (none)")

    if not r.daily_greeks.empty:
        nonzero_days = (r.daily_greeks.abs().sum(axis=1) > 1e-9).sum()
        print(f"\n--- {run.name} :: daily net Greeks ---")
        print(f"  Days with non-zero net Greeks: {nonzero_days} / "
              f"{len(r.daily_greeks)}")
        with pd.option_context("display.float_format", "{:,.4f}".format):
            desc = r.daily_greeks.describe().loc[
                ["mean", "min", "max"]]
            print("  Aggregate stats (mean / min / max):")
            print(desc.to_string())

    # Engine self-check
    causal_ok = all(
        (o.get("decision_date") is None
         or pd.Timestamp(o["decision_date"]) < pd.Timestamp(o["fill_date"]))
        for o in r.orders
    )
    open_at_end = len(
        [p for p in run.engine._open_positions if not p.closed]
    )
    print(f"\n--- {run.name} :: engine self-check ---")
    print(f"  decision_date < fill_date on every order: {causal_ok}")
    print(f"  Open positions at final bar             : {open_at_end}")


# --------------------------------------------------------------------------- #
def main() -> int:
    assert LIVE_TRADING_ENABLED is False, "V5.3 is RESEARCH only."

    _print_header("V5.3 Options Strategy Testing  (engine UNCHANGED from V5.0)")
    print(" Underlying: SPY  |  Period: 2022-01-03 to 2022-06-30 (frozen V5.2 Stage 1)")
    print(" Strategies: bull call (debit), bear put (debit), bull put (CREDIT)")
    print("             all defined-risk; defaults unchanged from each strategy's class")
    print(" Data: data/options/processed/SPY/2022/2022-{01..06}.csv.gz  (NO new fetch)")

    chain = load_spy_chain_2022_h1()
    n_dates = chain["date"].nunique()
    print(f"\nLoaded SPY chain: {len(chain):,} rows across {n_dates} trading days "
          f"({chain['date'].min().date()} -> {chain['date'].max().date()})")

    runs: list[StrategyRun] = []

    # --- Strategy 1 / 3 : SPY bull call spread (V5.0 baseline strategy) ---
    _print_header("Strategy 1 / 3  :  spy_bull_call_spread_v5_proof  (DEBIT, defaults)")
    runs.append(run_strategy(
        chain, SPYBullCallSpread(), name="bull_call",
    ))
    print_strategy_report(runs[-1])

    # --- Strategy 2 / 3 : SPY bear put spread (V5.3 addition) ---
    _print_header("Strategy 2 / 3  :  spy_bear_put_spread_v53  (DEBIT, defaults)")
    runs.append(run_strategy(
        chain, SPYBearPutSpread(), name="bear_put",
    ))
    print_strategy_report(runs[-1])

    # --- Strategy 3 / 3 : SPY bull put credit spread (V5.3 addition) ---
    _print_header("Strategy 3 / 3  :  spy_bull_put_spread_v53  (CREDIT, defaults)")
    runs.append(run_strategy(
        chain, SPYBullPutSpread(), name="bull_put",
    ))
    print_strategy_report(runs[-1])

    # --- Comparative summary ---
    _print_header("V5.3 comparative summary  (all 3 strategies on frozen Jan-Jun 2022 SPY)")
    rows = []
    for run in runs:
        r = run.result
        final_eq = float(r.equity_curve.iloc[-1]) if len(r.equity_curve) else float("nan")
        rows.append({
            "strategy": run.name,
            "trades": r.n_trades,
            "rejections": len(r.rejections),
            "final_equity": final_eq,
            "total_return_pct": r.total_return * 100,
            "max_drawdown_pct": r.max_drawdown() * 100,
            "total_cost": r.total_cost,
        })
    summary = pd.DataFrame(rows)
    with pd.option_context("display.float_format", "{:,.4f}".format,
                            "display.width", 160):
        print(summary.to_string(index=False))

    print("\nV5.3 run complete.")
    print("(Verifies engine mechanics across debit + credit defined-risk "
          "verticals; NOT a strategy-edge conclusion.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
