"""V5.2 Stage 2A strategy / edge check (read-only, existing data only).

Runs the three frozen V5.3 defined-risk verticals (bull_call, bear_put,
bull_put) across several SPY windows drawn from the EXISTING processed
corpus (Jan-Sep 2022). No new data, no ThetaData, no engine/strategy/
default changes, no parameter optimization. LIVE_TRADING_ENABLED stays
False.

Windows:
  jan_jun_2022    : Jan-Jun 2022  (V5.3/V5.4 baseline -- must reproduce)
  jan_sep_2022    : Jan-Sep 2022  (full expanded sample so far)
  jul_sep_2022    : Jul-Sep 2022  (Stage 2A only)
  jul_aug_2022    : Jul-Aug 2022  (Stage 2A sub-window)
  sep_2022        : Sep 2022      (standalone)

For each (window, strategy) it records headline metrics + an EXPECTANCY
decomposition (avg_win * P(win) + avg_loss * P(loss)) following a
tradability lens rather than a pure profit/loss lens.

Outputs (reports/options/v52_stage2a_strategy_check/):
  stage2a_strategy_summary.md
  strategy_window_comparison.csv
  stage2a_trade_diagnostics.csv
  stage2a_rejection_summary.csv
  stage2a_expectancy_summary.csv

Usage:
    python scripts/run_stage2a_strategy_check.py
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
OUT_DIR = ROOT / "reports" / "options" / "v52_stage2a_strategy_check"
TRADING_DAYS_PER_YEAR = 252

STRATEGY_FACTORIES: dict[str, Callable[..., Any]] = {
    "bull_call": SPYBullCallSpread,
    "bear_put":  SPYBearPutSpread,
    "bull_put":  SPYBullPutSpread,
}

# window label -> list of (year, month)
WINDOWS: dict[str, list[tuple[int, int]]] = {
    "jan_jun_2022": [(2022, m) for m in range(1, 7)],
    "jan_sep_2022": [(2022, m) for m in range(1, 10)],
    "jul_sep_2022": [(2022, 7), (2022, 8), (2022, 9)],
    "jul_aug_2022": [(2022, 7), (2022, 8)],
    "sep_2022":     [(2022, 9)],
}

V53_BASELINE_PCT = {"bull_call": -1.2658, "bear_put": 0.6490, "bull_put": -1.4701}


def load_window(months: list[tuple[int, int]]) -> pd.DataFrame:
    parts = []
    for y, m in months:
        df = read_processed("SPY", y, m)
        if df is None:
            raise FileNotFoundError(f"Missing SPY {y}-{m:02d} processed file.")
        parts.append(df)
    df = pd.concat(parts, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df["expiration"] = pd.to_datetime(df["expiration"]).dt.normalize()
    return df


@dataclass
class RunOut:
    window: str
    strategy: str
    result: OptionsBacktestResult
    engine: OptionsBacktestEngine


def run_one(chain: pd.DataFrame, strat_name: str, window: str) -> RunOut:
    eng = OptionsBacktestEngine(
        chain, STRATEGY_FACTORIES[strat_name](),
        initial_capital=100_000.0,
        limits=OptionsRiskLimits(), cost_model=OptionsCostModel(),
    )
    return RunOut(window, strat_name, eng.run(), eng)


def sharpe(daily_returns: pd.Series) -> float:
    r = daily_returns.dropna()
    if len(r) < 2:
        return float("nan")
    sd = r.std(ddof=1)
    if sd == 0 or math.isnan(sd):
        return float("nan")
    return float(r.mean() / sd * math.sqrt(TRADING_DAYS_PER_YEAR))


def active_days(result: OptionsBacktestResult) -> int:
    if result.daily_greeks.empty:
        return 0
    return int((result.daily_greeks.abs().sum(axis=1) > 1e-9).sum())


def causality_ok(result: OptionsBacktestResult) -> bool:
    return all(
        (o.get("decision_date") is None
         or pd.Timestamp(o["decision_date"]) < pd.Timestamp(o["fill_date"]))
        for o in result.orders
    )


def headline_row(run: RunOut) -> dict:
    r = run.result
    tdf = r.to_trades_frame()
    wins = tdf[tdf["realized_pnl"] > 0] if not tdf.empty else tdf
    losses = tdf[tdf["realized_pnl"] < 0] if not tdf.empty else tdf
    return {
        "window": run.window,
        "strategy": run.strategy,
        "trading_days": int(len(r.equity_curve)),
        "trades": r.n_trades,
        "rejections": len(r.rejections),
        "win_rate": (len(wins) / len(tdf)) if len(tdf) else float("nan"),
        "total_return_pct": r.total_return * 100,
        "final_equity": (float(r.equity_curve.iloc[-1])
                          if len(r.equity_curve) else float("nan")),
        "max_drawdown_pct": r.max_drawdown() * 100,
        "sharpe_annualized": sharpe(r.daily_returns),
        "total_cost": r.total_cost,
        "avg_win": float(wins["realized_pnl"].mean()) if len(wins) else float("nan"),
        "avg_loss": float(losses["realized_pnl"].mean()) if len(losses) else float("nan"),
        "worst_trade": float(tdf["realized_pnl"].min()) if len(tdf) else float("nan"),
        "best_trade": float(tdf["realized_pnl"].max()) if len(tdf) else float("nan"),
        "active_position_days": active_days(r),
        "causality_ok": causality_ok(r),
    }


def expectancy_row(run: RunOut) -> dict:
    """Expectancy decomposition (per-trade $), Roman-Paolucci tradability lens.

    expectancy = P(win) * avg_win + P(loss) * avg_loss   (per-trade $)
    Also reports profit factor and a simple payoff ratio.
    """
    r = run.result
    tdf = r.to_trades_frame()
    n = len(tdf)
    wins = tdf[tdf["realized_pnl"] > 0]["realized_pnl"] if n else pd.Series(dtype=float)
    losses = tdf[tdf["realized_pnl"] < 0]["realized_pnl"] if n else pd.Series(dtype=float)
    p_win = (len(wins) / n) if n else float("nan")
    p_loss = (len(losses) / n) if n else float("nan")
    avg_win = float(wins.mean()) if len(wins) else 0.0
    avg_loss = float(losses.mean()) if len(losses) else 0.0
    expectancy = (p_win * avg_win + p_loss * avg_loss) if n else float("nan")
    gross_win = float(wins.sum()) if len(wins) else 0.0
    gross_loss = float(losses.sum()) if len(losses) else 0.0
    profit_factor = (gross_win / abs(gross_loss)) if gross_loss != 0 else float("nan")
    payoff_ratio = (avg_win / abs(avg_loss)) if avg_loss != 0 else float("nan")
    return {
        "window": run.window,
        "strategy": run.strategy,
        "n_trades": n,
        "p_win": p_win,
        "p_loss": p_loss,
        "avg_win_dollar": avg_win if len(wins) else float("nan"),
        "avg_loss_dollar": avg_loss if len(losses) else float("nan"),
        "expectancy_per_trade_dollar": expectancy,
        "total_pnl_dollar": float(tdf["realized_pnl"].sum()) if n else float("nan"),
        "profit_factor": profit_factor,
        "payoff_ratio": payoff_ratio,
    }


def trade_diag_rows(run: RunOut) -> list[dict]:
    r = run.result
    out = []
    for t in r.trades:
        out.append({
            "window": run.window,
            "strategy": run.strategy,
            "fill_open": str(pd.Timestamp(t.fill_open).date()),
            "fill_close": str(pd.Timestamp(t.fill_close).date()),
            "close_reason": t.close_reason,
            "width": t.width,
            "net_entry_cash": t.net_entry_cash,
            "realized_pnl": t.realized_pnl,
        })
    return out


def rejection_rows(run: RunOut) -> list[dict]:
    if not run.result.rejections:
        return []
    rdf = pd.DataFrame([{
        "window": run.window, "strategy": run.strategy,
        "stage": x.stage, "reason": x.reason,
    } for x in run.result.rejections])
    return rdf.groupby(
        ["window", "strategy", "stage", "reason"]).size().rename(
        "n").reset_index().to_dict("records")


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


def main() -> int:
    assert LIVE_TRADING_ENABLED is False, "Stage 2A check is RESEARCH only."
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    runs: list[RunOut] = []
    for wlabel, months in WINDOWS.items():
        chain = load_window(months)
        for s in STRATEGY_FACTORIES:
            runs.append(run_one(chain, s, wlabel))

    headline = pd.DataFrame([headline_row(r) for r in runs])
    expectancy = pd.DataFrame([expectancy_row(r) for r in runs])
    diag = pd.DataFrame(
        [row for r in runs for row in trade_diag_rows(r)])
    rej = pd.DataFrame(
        [row for r in runs for row in rejection_rows(r)]) \
        if any(r.result.rejections for r in runs) else pd.DataFrame(
            columns=["window", "strategy", "stage", "reason", "n"])

    headline.to_csv(OUT_DIR / "strategy_window_comparison.csv", index=False)
    expectancy.to_csv(OUT_DIR / "stage2a_expectancy_summary.csv", index=False)
    diag.to_csv(OUT_DIR / "stage2a_trade_diagnostics.csv", index=False)
    rej.to_csv(OUT_DIR / "stage2a_rejection_summary.csv", index=False)

    # ---- baseline check ----
    base = headline[headline["window"] == "jan_jun_2022"].set_index("strategy")
    baseline_rows = []
    for s, exp_pct in V53_BASELINE_PCT.items():
        got = float(base.loc[s, "total_return_pct"])
        baseline_rows.append({
            "strategy": s, "v53_baseline_pct": exp_pct,
            "stage2a_check_pct": got,
            "match": "OK" if abs(got - exp_pct) < 1e-3 else "MISMATCH",
        })
    baseline_df = pd.DataFrame(baseline_rows)

    # ---- markdown ----
    md = []
    md.append("# V5.2 Stage 2A strategy / edge check — SPY (existing data only)\n")
    md.append(
        "Engine V5.0 (unchanged); strategy defaults unchanged; default cost + "
        "spread filter; fresh $100,000 per (window, strategy). No new data, "
        f"no ThetaData. `LIVE_TRADING_ENABLED = {LIVE_TRADING_ENABLED}`.\n"
    )

    md.append("\n## 1. Baseline consistency (Jan–Jun 2022 must match V5.3)\n")
    md.append(_df_to_md(baseline_df))

    md.append("\n## 2. Headline metrics by window × strategy\n")
    cols = ["window", "strategy", "trading_days", "trades", "rejections",
            "win_rate", "total_return_pct", "max_drawdown_pct",
            "sharpe_annualized", "total_cost", "avg_win", "avg_loss",
            "worst_trade", "active_position_days", "causality_ok"]
    md.append(_df_to_md(headline[cols]))

    md.append("\n## 3. Expectancy decomposition (tradability lens)\n")
    md.append(
        "`expectancy_per_trade = P(win)*avg_win + P(loss)*avg_loss` (per-trade $). "
        "`profit_factor = gross_win/|gross_loss|`. "
        "`payoff_ratio = avg_win/|avg_loss|`.\n"
    )
    ecols = ["window", "strategy", "n_trades", "p_win", "avg_win_dollar",
             "avg_loss_dollar", "expectancy_per_trade_dollar",
             "total_pnl_dollar", "profit_factor", "payoff_ratio"]
    md.append(_df_to_md(expectancy[ecols]))

    md.append("\n## 4. bear_put across windows (focus)\n")
    bp = headline[headline["strategy"] == "bear_put"][
        ["window", "trades", "win_rate", "total_return_pct",
         "max_drawdown_pct"]]
    md.append(_df_to_md(bp))

    md.append("\n## 5. Rejection summary\n")
    md.append(_df_to_md(rej) if not rej.empty else "_(none)_")

    (OUT_DIR / "stage2a_strategy_summary.md").write_text(
        "\n".join(md), encoding="utf-8")

    # ---- console ----
    print("Baseline check vs V5.3:")
    print(baseline_df.to_string(index=False))
    print("\nbear_put by window:")
    print(bp.to_string(index=False))
    print(f"\nArtifacts -> {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
