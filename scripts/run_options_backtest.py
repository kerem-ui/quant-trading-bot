"""V5.0 proof-of-engine driver.

Loads SPY processed chain for 2022-01 + 2022-02, runs the bull call spread
proof strategy through :class:`OptionsBacktestEngine`, prints a mechanics
summary.

Usage::

    python scripts/run_options_backtest.py

Limits:
  - SPY only.
  - Local processed CSV.gz only (no ThetaData, no broker).
  - LIVE_TRADING_ENABLED stays False.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

# Path setup -- shared helper.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from quantbot.costs.transaction_costs import OptionsCostModel
from quantbot.data.options_cache import read_processed
from quantbot.options.backtest_engine import OptionsBacktestEngine
from quantbot.options.risk import OptionsRiskLimits
from quantbot.options.strategies.spy_bull_call import SPYBullCallSpread


LIVE_TRADING_ENABLED = False


def load_spy_chain() -> pd.DataFrame:
    """Concatenate SPY 2022-01 + 2022-02 processed monthly files."""
    jan = read_processed("SPY", 2022, 1)
    feb = read_processed("SPY", 2022, 2)
    parts = [p for p in (jan, feb) if p is not None]
    if not parts:
        raise FileNotFoundError(
            "No SPY processed data found for 2022-01 or 2022-02. "
            "V5 proof-of-engine requires the V4 checkpointed data."
        )
    df = pd.concat(parts, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df["expiration"] = pd.to_datetime(df["expiration"]).dt.normalize()
    return df


def _fmt_money(x: float) -> str:
    return f"${x:,.2f}"


def main() -> int:
    assert LIVE_TRADING_ENABLED is False, "V5 proof-of-engine is RESEARCH only."

    print("=" * 72)
    print(" V5.0 Options Backtest Engine - Proof of Engine")
    print(" Underlying: SPY  |  Period: 2022-01 to 2022-02")
    print(" Strategy:  SPY bull call spread (mechanics check, not a recommendation)")
    print("=" * 72)

    chain = load_spy_chain()
    n_dates = chain["date"].nunique()
    print(f"\nLoaded chain: {len(chain):,} rows across {n_dates} trading days "
          f"({chain['date'].min().date()} -> {chain['date'].max().date()})")

    strategy = SPYBullCallSpread()
    limits = OptionsRiskLimits()  # defaults: width<=10, max 1 concurrent, no naked
    costs = OptionsCostModel()
    engine = OptionsBacktestEngine(
        chain, strategy,
        initial_capital=100_000.0, limits=limits, cost_model=costs,
    )
    result = engine.run()

    # --- Equity / mechanics ---
    print("\n--- Engine output ---")
    print(f"  Initial capital   : {_fmt_money(result.initial_capital)}")
    if len(result.equity_curve):
        print(f"  Final equity      : {_fmt_money(float(result.equity_curve.iloc[-1]))}")
    print(f"  Total return      : {result.total_return * 100:+.4f}%")
    print(f"  Max drawdown      : {result.max_drawdown() * 100:+.4f}%")
    print(f"  Total cost paid   : {_fmt_money(result.total_cost)}")
    print(f"  # trades closed   : {result.n_trades}")
    print(f"  # rejections      : {len(result.rejections)}")
    print(f"  # orders          : {len(result.orders)}")

    # --- Trades table ---
    trades_df = result.to_trades_frame()
    if not trades_df.empty:
        cols = ["structure", "fill_open", "fill_close", "close_reason",
                "width", "net_entry_cash", "open_cost", "close_cost",
                "max_profit", "max_loss", "realized_pnl"]
        print("\n--- Per-trade table ---")
        with pd.option_context("display.max_rows", None,
                                "display.width", 160,
                                "display.float_format", "{:,.2f}".format):
            print(trades_df[cols].to_string(index=False))

        wins = trades_df[trades_df["realized_pnl"] > 0]
        losses = trades_df[trades_df["realized_pnl"] < 0]
        print(f"\n  Win rate          : {len(wins) / len(trades_df):.2%}"
              f"  ({len(wins)}W / {len(losses)}L)")
        if len(wins):
            print(f"  Avg win           : {_fmt_money(float(wins['realized_pnl'].mean()))}")
        if len(losses):
            print(f"  Avg loss          : {_fmt_money(float(losses['realized_pnl'].mean()))}")
        wt = result.worst_trade()
        if wt is not None:
            print(f"  Worst trade       : {_fmt_money(wt.realized_pnl)} "
                  f"({wt.close_reason}, fill_open={wt.fill_open.date()})")
    else:
        print("\n--- Per-trade table ---\n  (no closed trades)")

    # --- Rejections ---
    if result.rejections:
        print("\n--- Rejection log ---")
        rej_df = pd.DataFrame([{
            "date": r.date, "stage": r.stage, "reason": r.reason,
            **r.meta,
        } for r in result.rejections])
        with pd.option_context("display.max_rows", 50,
                                "display.width", 160):
            print(rej_df.head(50).to_string(index=False))
    else:
        print("\n--- Rejection log ---\n  (none)")

    # --- Daily net Greeks ---
    if not result.daily_greeks.empty:
        print("\n--- Daily net Greeks (head) ---")
        with pd.option_context("display.max_rows", 12,
                                "display.float_format", "{:,.4f}".format):
            print(result.daily_greeks.head(12).to_string())
        nonzero_days = (result.daily_greeks.abs().sum(axis=1) > 1e-9).sum()
        print(f"  Days with non-zero net Greeks: {nonzero_days} / "
              f"{len(result.daily_greeks)}")

    # --- Engine self-check ---
    print("\n--- Engine self-check ---")
    causal_ok = all(
        (o.get("decision_date") is None
         or pd.Timestamp(o["decision_date"]) < pd.Timestamp(o["fill_date"]))
        for o in result.orders
    )
    print(f"  Causality (decision < fill on every order): {causal_ok}")
    cash_only_at_end = (
        len([p for p in engine._open_positions if not p.closed]) == 0
    )
    print(f"  All positions closed at final bar         : {cash_only_at_end}")

    print("\nV5.0 proof-of-engine run complete.")
    print("(This script verifies engine mechanics only; it does NOT validate "
          "strategy profitability.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
