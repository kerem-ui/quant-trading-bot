"""V5.2 Stage 2B strategy / edge check (read-only, existing data only).

Runs the three frozen V5.3 defined-risk verticals (bull_call, bear_put,
bull_put) across SPY windows drawn from the EXISTING processed corpus
(now full-year Jan-Dec 2022). No new data, no ThetaData, no engine/
strategy/default changes, no parameter optimization. LIVE_TRADING_ENABLED
stays False.

Windows:
  jan_jun_2022 : Jan-Jun 2022  (V5.3/V5.4 baseline -- must reproduce)
  jul_sep_2022 : Jul-Sep 2022  (Stage 2A)
  oct_dec_2022 : Oct-Dec 2022  (Stage 2B -- Q4 recovery/fade)
  jan_sep_2022 : Jan-Sep 2022  (expanded sample)
  jan_dec_2022 : Jan-Dec 2022  (full-year)
  oct_2022 / nov_2022 / dec_2022 : standalone months

Adds an EXPECTANCY decomposition (tradability lens) and a per-window
MACRO CONTEXT overlay (SPY return, VIX, dominant regime) drawn from the
existing V5.7 macro layer -- explanation only, NOT a trading signal.

Outputs (reports/options/v52_stage2b_strategy_check/):
  stage2b_strategy_summary.md
  strategy_window_comparison.csv
  stage2b_expectancy_summary.csv
  stage2b_trade_diagnostics.csv
  stage2b_rejection_summary.csv

Usage:
    python scripts/run_stage2b_strategy_check.py
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
from quantbot.macro.market_proxies import fetch_proxy
from quantbot.macro.regime_classifier import RegimeThresholds, build_regime_panel
from quantbot.options.backtest_engine import (
    OptionsBacktestEngine,
    OptionsBacktestResult,
)
from quantbot.options.risk import OptionsRiskLimits
from quantbot.options.strategies.spy_bear_put import SPYBearPutSpread
from quantbot.options.strategies.spy_bull_call import SPYBullCallSpread
from quantbot.options.strategies.spy_bull_put import SPYBullPutSpread


LIVE_TRADING_ENABLED = False
OUT_DIR = ROOT / "reports" / "options" / "v52_stage2b_strategy_check"
TRADING_DAYS_PER_YEAR = 252

STRATEGY_FACTORIES: dict[str, Callable[..., Any]] = {
    "bull_call": SPYBullCallSpread,
    "bear_put":  SPYBearPutSpread,
    "bull_put":  SPYBullPutSpread,
}

WINDOWS: dict[str, list[tuple[int, int]]] = {
    "jan_jun_2022": [(2022, m) for m in range(1, 7)],
    "jul_sep_2022": [(2022, 7), (2022, 8), (2022, 9)],
    "oct_dec_2022": [(2022, 10), (2022, 11), (2022, 12)],
    "jan_sep_2022": [(2022, m) for m in range(1, 10)],
    "jan_dec_2022": [(2022, m) for m in range(1, 13)],
    "oct_2022":     [(2022, 10)],
    "nov_2022":     [(2022, 11)],
    "dec_2022":     [(2022, 12)],
}

V53_BASELINE_PCT = {"bull_call": -1.2658, "bear_put": 0.6490, "bull_put": -1.4701}

REGIME_NOTE = {
    "jan_jun_2022": "2022 H1 bear (monotonic decline ~$478 -> ~$365)",
    "jul_sep_2022": "summer rally then renewed decline into Oct low",
    "oct_dec_2022": "Oct bear-low -> Nov Q4 recovery rally -> Dec fade",
    "jan_sep_2022": "bear + partial rebound",
    "jan_dec_2022": "full-year: bear -> rally -> low -> recovery -> fade",
    "oct_2022":     "bear-market low ~$356 then turn up",
    "nov_2022":     "Q4 recovery rally $371 -> $408",
    "dec_2022":     "December fade $407 -> $382",
}


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


def run_one(chain: pd.DataFrame, strat_name: str, window: str) -> RunOut:
    eng = OptionsBacktestEngine(
        chain, STRATEGY_FACTORIES[strat_name](),
        initial_capital=100_000.0,
        limits=OptionsRiskLimits(), cost_model=OptionsCostModel(),
    )
    return RunOut(window, strat_name, eng.run())


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
        "window": run.window, "strategy": run.strategy,
        "trading_days": int(len(r.equity_curve)),
        "trades": r.n_trades, "rejections": len(r.rejections),
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
    pf = (gross_win / abs(gross_loss)) if gross_loss != 0 else float("nan")
    payoff = (avg_win / abs(avg_loss)) if avg_loss != 0 else float("nan")
    return {
        "window": run.window, "strategy": run.strategy, "n_trades": n,
        "p_win": p_win, "p_loss": p_loss,
        "avg_win_dollar": avg_win if len(wins) else float("nan"),
        "avg_loss_dollar": avg_loss if len(losses) else float("nan"),
        "expectancy_per_trade_dollar": expectancy,
        "total_pnl_dollar": float(tdf["realized_pnl"].sum()) if n else float("nan"),
        "profit_factor": pf, "payoff_ratio": payoff,
    }


def trade_diag_rows(run: RunOut) -> list[dict]:
    return [{
        "window": run.window, "strategy": run.strategy,
        "fill_open": str(pd.Timestamp(t.fill_open).date()),
        "fill_close": str(pd.Timestamp(t.fill_close).date()),
        "close_reason": t.close_reason, "width": t.width,
        "net_entry_cash": t.net_entry_cash, "realized_pnl": t.realized_pnl,
    } for t in run.result.trades]


def rejection_rows(run: RunOut) -> list[dict]:
    if not run.result.rejections:
        return []
    rdf = pd.DataFrame([{
        "window": run.window, "strategy": run.strategy,
        "stage": x.stage, "reason": x.reason,
    } for x in run.result.rejections])
    return rdf.groupby(["window", "strategy", "stage", "reason"]).size().rename(
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


def macro_context_rows() -> pd.DataFrame:
    """Per-window SPY return / VIX context + dominant regime label
    (read-only, explanation only). Degrades gracefully if proxies
    unavailable."""
    spy = fetch_proxy("SPY", start="2021-06-01", end="2023-01-31")
    vix = fetch_proxy("^VIX", start="2021-06-01", end="2023-01-31")
    rows = []
    regime = None
    if spy is not None:
        regime = build_regime_panel(
            spy_close=spy["adjusted_close"],
            vix_level=(vix["close"] if vix is not None else None),
            th=RegimeThresholds(),
        )
    for wlabel, months in WINDOWS.items():
        start = pd.Timestamp(months[0][0], months[0][1], 1)
        end = (pd.Timestamp(months[-1][0], months[-1][1], 1)
               + pd.offsets.MonthEnd(1))
        row = {"window": wlabel, "regime_note": REGIME_NOTE.get(wlabel, "")}
        if spy is not None:
            sub = spy.loc[start:end, "adjusted_close"]
            if len(sub) >= 2:
                row["spy_start"] = round(float(sub.iloc[0]), 2)
                row["spy_end"] = round(float(sub.iloc[-1]), 2)
                row["spy_return_pct"] = round(float(sub.iloc[-1] / sub.iloc[0] - 1) * 100, 2)
        if vix is not None:
            vsub = vix.loc[start:end, "close"]
            if len(vsub) >= 2:
                row["vix_start"] = round(float(vsub.iloc[0]), 2)
                row["vix_end"] = round(float(vsub.iloc[-1]), 2)
        if regime is not None and "combined" in regime.columns:
            rsub = regime.loc[start:end, "trend"] if "trend" in regime.columns else None
            if rsub is not None and len(rsub):
                modes = rsub[rsub != "unknown"].mode()
                row["dominant_trend"] = str(modes.iloc[0]) if len(modes) else ""
        rows.append(row)
    return pd.DataFrame(rows)


def main() -> int:
    assert LIVE_TRADING_ENABLED is False, "Stage 2B check is RESEARCH only."
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    runs: list[RunOut] = []
    for wlabel, months in WINDOWS.items():
        chain = load_window(months)
        for s in STRATEGY_FACTORIES:
            runs.append(run_one(chain, s, wlabel))

    headline = pd.DataFrame([headline_row(r) for r in runs])
    expectancy = pd.DataFrame([expectancy_row(r) for r in runs])
    diag = pd.DataFrame([row for r in runs for row in trade_diag_rows(r)])
    rej = pd.DataFrame([row for r in runs for row in rejection_rows(r)]) \
        if any(r.result.rejections for r in runs) else pd.DataFrame(
            columns=["window", "strategy", "stage", "reason", "n"])

    headline.to_csv(OUT_DIR / "strategy_window_comparison.csv", index=False)
    expectancy.to_csv(OUT_DIR / "stage2b_expectancy_summary.csv", index=False)
    diag.to_csv(OUT_DIR / "stage2b_trade_diagnostics.csv", index=False)
    rej.to_csv(OUT_DIR / "stage2b_rejection_summary.csv", index=False)

    base = headline[headline["window"] == "jan_jun_2022"].set_index("strategy")
    baseline_df = pd.DataFrame([{
        "strategy": s, "v53_baseline_pct": exp_pct,
        "stage2b_check_pct": float(base.loc[s, "total_return_pct"]),
        "match": "OK" if abs(float(base.loc[s, "total_return_pct"]) - exp_pct) < 1e-3 else "MISMATCH",
    } for s, exp_pct in V53_BASELINE_PCT.items()])

    macro = macro_context_rows()

    # compact window comparison (the 5 primary windows)
    primary = ["jan_jun_2022", "jul_sep_2022", "oct_dec_2022",
               "jan_sep_2022", "jan_dec_2022"]
    comp = headline[headline["window"].isin(primary)].merge(
        expectancy[["window", "strategy", "expectancy_per_trade_dollar",
                     "profit_factor"]],
        on=["window", "strategy"], how="left")
    comp_view = comp[["window", "strategy", "trades", "win_rate",
                       "total_return_pct", "expectancy_per_trade_dollar",
                       "profit_factor", "max_drawdown_pct"]]

    md = []
    md.append("# V5.2 Stage 2B strategy / edge check — SPY full-year 2022 (existing data only)\n")
    md.append(
        "Engine V5.0 (unchanged); strategy defaults unchanged; default cost + "
        "spread filter; fresh $100,000 per (window, strategy). No new data, no "
        f"ThetaData. `LIVE_TRADING_ENABLED = {LIVE_TRADING_ENABLED}`.\n"
    )

    md.append("\n## 1. Baseline consistency (Jan–Jun 2022 must match V5.3)\n")
    md.append(_df_to_md(baseline_df))

    md.append("\n## 2. Compact window comparison (5 primary windows)\n")
    md.append(_df_to_md(comp_view.sort_values(["strategy", "window"]).reset_index(drop=True)))

    md.append("\n## 3. Full headline metrics (all windows × strategies)\n")
    cols = ["window", "strategy", "trading_days", "trades", "rejections",
            "win_rate", "total_return_pct", "max_drawdown_pct",
            "sharpe_annualized", "total_cost", "avg_win", "avg_loss",
            "worst_trade", "active_position_days", "causality_ok"]
    md.append(_df_to_md(headline[cols]))

    md.append("\n## 4. Expectancy decomposition (tradability lens)\n")
    md.append(
        "`expectancy_per_trade = P(win)*avg_win + P(loss)*avg_loss` ($/trade). "
        "`profit_factor = gross_win/|gross_loss|`. "
        "`payoff_ratio = avg_win/|avg_loss|`.\n"
    )
    ecols = ["window", "strategy", "n_trades", "p_win", "avg_win_dollar",
             "avg_loss_dollar", "expectancy_per_trade_dollar",
             "total_pnl_dollar", "profit_factor", "payoff_ratio"]
    md.append(_df_to_md(expectancy[ecols]))

    md.append("\n## 5. bear_put across windows (focus)\n")
    bp = headline[headline["strategy"] == "bear_put"][
        ["window", "trades", "win_rate", "total_return_pct", "max_drawdown_pct"]]
    md.append(_df_to_md(bp))

    md.append("\n## 6. Macro / regime context (explanation only, NOT a signal)\n")
    md.append(_df_to_md(macro))

    md.append("\n## 7. Rejection summary\n")
    md.append(_df_to_md(rej) if not rej.empty else "_(none)_")

    (OUT_DIR / "stage2b_strategy_summary.md").write_text("\n".join(md), encoding="utf-8")

    print("Baseline check vs V5.3:")
    print(baseline_df.to_string(index=False))
    print("\nCompact window comparison:")
    print(comp_view.sort_values(["strategy", "window"]).to_string(index=False))
    print(f"\nArtifacts -> {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
