"""V5.7.1 / V5.8 Edge-Tradability final report builder (read-only).

Consolidates the EXISTING V5.3-V5.7 + Stage 2A/2B strategy-check artifacts
into one decision document. Reads already-computed CSVs (no backtest
re-run, no data fetch, no ThetaData). Emits the v571_tradability report
folder.

Sources (must already exist):
  reports/options/v52_stage2b_strategy_check/strategy_window_comparison.csv
  reports/options/v52_stage2b_strategy_check/stage2b_expectancy_summary.csv

Outputs (reports/research/v571_tradability/):
  strategy_final_verdict.csv
  expectancy_decomposition_full_year.csv
  regime_dependence_summary.csv
  v571_summary.md
  validated_vs_not_validated.md
  next_research_plan.md

LIVE_TRADING_ENABLED stays False. No engine/strategy/default changes.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "reports" / "options" / "v52_stage2b_strategy_check"
OUT_DIR = ROOT / "reports" / "research" / "v571_tradability"

LIVE_TRADING_ENABLED = False

PRIMARY_WINDOWS = ["jan_jun_2022", "jul_sep_2022", "oct_dec_2022",
                    "jan_sep_2022", "jan_dec_2022"]
REGIME_OF = {
    "jan_jun_2022": "bear / downtrend",
    "jul_sep_2022": "bear-rally then renewed decline",
    "oct_dec_2022": "bear-low -> Q4 recovery -> Dec fade",
    "jan_sep_2022": "bear + partial rebound",
    "jan_dec_2022": "full-year mixed (bear -> recovery)",
}


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
    assert LIVE_TRADING_ENABLED is False, "V5.7.1 report is RESEARCH only."
    comp = pd.read_csv(SRC_DIR / "strategy_window_comparison.csv")
    exp = pd.read_csv(SRC_DIR / "stage2b_expectancy_summary.csv")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Merge headline + expectancy on (window, strategy)
    m = comp.merge(
        exp[["window", "strategy", "p_win", "p_loss", "avg_win_dollar",
             "avg_loss_dollar", "expectancy_per_trade_dollar",
             "profit_factor", "payoff_ratio", "total_pnl_dollar"]],
        on=["window", "strategy"], how="left",
    )

    # ---- expectancy_decomposition_full_year.csv (primary windows) ----
    decomp = m[m["window"].isin(PRIMARY_WINDOWS)][[
        "window", "strategy", "trades", "win_rate",
        "total_return_pct", "avg_win_dollar", "avg_loss_dollar",
        "expectancy_per_trade_dollar", "profit_factor", "payoff_ratio",
        "max_drawdown_pct", "total_cost",
    ]].copy()
    decomp["window"] = pd.Categorical(decomp["window"],
                                       categories=PRIMARY_WINDOWS, ordered=True)
    decomp = decomp.sort_values(["strategy", "window"]).reset_index(drop=True)
    decomp.to_csv(OUT_DIR / "expectancy_decomposition_full_year.csv", index=False)

    # ---- regime_dependence_summary.csv ----
    regime_rows = []
    for strat in ("bull_call", "bear_put", "bull_put"):
        for w in PRIMARY_WINDOWS:
            row = m[(m["strategy"] == strat) & (m["window"] == w)]
            if row.empty:
                continue
            r = row.iloc[0]
            regime_rows.append({
                "strategy": strat, "window": w, "regime": REGIME_OF[w],
                "total_return_pct": r["total_return_pct"],
                "win_rate": r["win_rate"],
                "expectancy_per_trade": r["expectancy_per_trade_dollar"],
                "profit_factor": r["profit_factor"],
                "positive_window": bool(r["total_return_pct"] > 0),
                "profit_factor_gt1": bool(r["profit_factor"] > 1.0)
                                       if not pd.isna(r["profit_factor"]) else False,
            })
    regime = pd.DataFrame(regime_rows)
    regime.to_csv(OUT_DIR / "regime_dependence_summary.csv", index=False)

    # ---- strategy_final_verdict.csv ----
    verdict_rows = []
    for strat in ("bull_call", "bear_put", "bull_put"):
        sub = m[(m["strategy"] == strat) & (m["window"].isin(PRIMARY_WINDOWS))]
        rets = sub.set_index("window")["total_return_pct"]
        pos = int((rets > 0).sum())
        neg = int((rets < 0).sum())
        n = len(rets)
        sign_stable = (pos == n) or (neg == n)
        best_w = rets.idxmax()
        worst_w = rets.idxmin()
        # full-year numbers
        fy = m[(m["strategy"] == strat) & (m["window"] == "jan_dec_2022")].iloc[0]
        # profit factor > 1 count across primary windows
        pf = sub.set_index("window")["profit_factor"]
        pf_gt1 = int((pf > 1.0).sum())
        verdict_rows.append({
            "strategy": strat,
            "full_year_return_pct": round(float(fy["total_return_pct"]), 4),
            "full_year_expectancy_per_trade": round(float(fy["expectancy_per_trade_dollar"]), 2),
            "full_year_profit_factor": round(float(fy["profit_factor"]), 3),
            "windows_positive": f"{pos}/{n}",
            "windows_pf_gt_1": f"{pf_gt1}/{n}",
            "best_window": str(best_w),
            "best_window_ret_pct": round(float(rets.max()), 4),
            "worst_window": str(worst_w),
            "worst_window_ret_pct": round(float(rets.min()), 4),
            "sign_stable_across_regimes": sign_stable,
            "verdict": VERDICTS[strat],
        })
    verdict = pd.DataFrame(verdict_rows)
    verdict.to_csv(OUT_DIR / "strategy_final_verdict.csv", index=False)

    # ---- v571_summary.md ----
    md = []
    md.append("# V5.7.1 / V5.8 Edge-Tradability Final Report — SPY defined-risk verticals (2022)\n")
    md.append(
        "Consolidates V5.3 (strategy testing), V5.4 (robustness), V5.5 "
        "(rolling-window stability), V5.6 (non-overlapping windows), V5.7 "
        "(macro/FRED/event context), and the Stage 2A/2B strategy-edge "
        "checks into one decision document. Read-only: no new data, no "
        "ThetaData, no engine/strategy/default changes, no parameter "
        f"optimization. `LIVE_TRADING_ENABLED = {LIVE_TRADING_ENABLED}`.\n"
    )
    md.append(
        "\n**Lens (Roman-Paolucci tradability principles):** profitability is "
        "not edge. We decompose expectancy, inspect winner/loss distributions, "
        "test sign + magnitude stability across regimes, identify regime "
        "dependence, and reject backtest profitability that does not survive a "
        "regime shift.\n"
    )

    md.append("\n## 1. Is any current strategy deployable? — NO\n")
    md.append(
        "No defined-risk vertical (bull_call, bear_put, bull_put) shows a "
        "positive expectancy that persists across BOTH the 2022 H1 bear and "
        "the Q4 recovery. Each is positive only in the regime that matches its "
        "directional bias. None is deployable.\n"
    )

    md.append("\n## 2. Final verdict table\n")
    md.append(_df_to_md(verdict))

    md.append("\n## 3. Expectancy decomposition (primary windows)\n")
    md.append(
        "`expectancy_per_trade = P(win)*avg_win + P(loss)*avg_loss` ($/trade). "
        "`profit_factor = gross_win/|gross_loss|`.\n"
    )
    md.append(_df_to_md(decomp))

    md.append("\n## 4. Regime dependence (does the strategy's sign track the regime?)\n")
    md.append(_df_to_md(regime[[
        "strategy", "window", "regime", "total_return_pct",
        "profit_factor", "positive_window", "profit_factor_gt1"]]))
    md.append(
        "\n**Pattern:** bear_put is positive (PF>1) ONLY in down-trend windows; "
        "bull_put is positive (PF>1) ONLY in the Q4 recovery window; bull_call "
        "is never PF>1 (best is near-flat in the recovery). The signs are a "
        "mirror image driven by spot direction + vega (VIX 16->29 in the H1 "
        "bear; VIX 30->22 in the Q4 recovery). This is directional exposure, "
        "NOT independent structural edge.\n"
    )

    md.append("\n## 5. bear_put falsification — CONFIRMED REJECTED\n")
    bp = decomp[decomp["strategy"] == "bear_put"]
    md.append(_df_to_md(bp[["window", "trades", "win_rate", "total_return_pct",
                             "expectancy_per_trade_dollar", "profit_factor"]]))
    md.append(
        "\nExpectancy/trade decays monotonically as non-bear regime is added: "
        "+$64.90 (Jan-Jun) -> +$33.93 (Jan-Sep) -> -$5.70 (Jul-Sep) -> "
        "-$65.00 (Oct-Dec). Profit factor falls 2.41 -> 0.27. The Jan-Jun "
        "+0.65% was a clean-bear artifact; it does NOT survive the Q4 "
        "recovery. bear_put is **rejected as a regime-independent tradable "
        "edge** and confirmed as a regime-directional bearish bet.\n"
    )

    md.append("\n## 6. Winner / loss distribution read\n")
    md.append(
        "- **bear_put:** avg win ~$159 vs avg loss ~$154 (payoff ~1.0); lives "
        "or dies on win PROBABILITY, which is regime-driven (70% in the bear, "
        "20% in the recovery). Wins do not structurally outsize losses.\n"
        "- **bull_put:** small avg win (~$73) vs larger avg loss (~$190); "
        "payoff ratio < 0.4; needs a very high win rate to profit, achieved "
        "ONLY in the calm recovery (80% Oct-Dec) and never in down regimes.\n"
        "- **bull_call:** avg win ~$178 vs avg loss ~$250; payoff < 1 and low "
        "win rate; negative expectancy in every primary window.\n"
        "- Across regimes, **no strategy keeps profit factor > 1** outside its "
        "favorable regime. Average wins do NOT compensate average losses on a "
        "through-the-cycle basis.\n"
    )

    md.append("\n## 7. What is validated vs NOT validated\n")
    md.append("See `validated_vs_not_validated.md`. In short: the **engine, "
              "data pipeline, defined-risk accounting, IV/Greeks enrichment, "
              "robustness/stability framework, and macro/event research layer "
              "are validated**; a **deployable trading edge is NOT**.\n")

    md.append("\n## 8. Do we need 2023 data? — OPTIONAL, not required\n")
    md.append(
        "Full-year 2022 already rejected all three verticals as "
        "regime-independent edges. A single confirmatory quarter (SPY "
        "Jan-Mar 2023, a non-2022 recovery/sideways regime) would only "
        "RE-CONFIRM the regime-directional reading; it is not needed to reach "
        "the verdict. Further 2023 data should be fetched ONLY in service of a "
        "specific NEW hypothesis (e.g. an IV/VRP strategy), not to keep "
        "re-testing a rejected edge.\n"
    )

    md.append("\n## 9. Recommended next research directions\n")
    md.append("See `next_research_plan.md` for the ranked plan (A: new "
              "strategy research incl. IV/VRP & range-filtered credit "
              "structures; B: company/fundamentals layer; C: optional 2023 "
              "Q1 confirmation; D: paper trading — NOT yet).\n")

    md.append("\n## 10. Final answers\n")
    md.append(
        "1. **Is any current strategy deployable?** No.\n"
        "2. **Was bear_put falsified as a regime-independent edge?** Yes — "
        "rejected (Oct-Dec −0.33%, PF 0.27, expectancy −$65/trade).\n"
        "3. **What did the bot validate?** Engine mechanics, defined-risk "
        "debit/credit accounting, no-look-ahead causality, the ThetaData "
        "historical pipeline (full-year SPY 2022: 1,096,626 rows, 100% "
        "Greeks, 0 hard rejects, 0 dup rows), IV/Greeks enrichment, "
        "cost/spread sensitivity, rolling/non-overlapping stability, and the "
        "macro/FRED/event read-only context layer.\n"
        "4. **What next?** Move to NEW strategy research (IV/VRP, "
        "range-filtered defined-risk credit structures) and/or a "
        "company/fundamentals research layer — not more testing of the "
        "rejected verticals.\n"
        "5. **Fetch 2023 now or move on?** Move on. 2023 Q1 is optional "
        "confirmation only; the verdict is already reached on 2022.\n"
    )

    md.append(
        "\n**Deployment warning:** This is a research finding, not a trading "
        "recommendation. No defined-risk vertical is deployable. No live "
        "trading, no broker, no IBKR. `LIVE_TRADING_ENABLED` remains False.\n"
    )
    (OUT_DIR / "v571_summary.md").write_text("\n".join(md), encoding="utf-8")

    # ---- validated_vs_not_validated.md ----
    vmd = []
    vmd.append("# V5.7.1 Validated vs NOT validated\n")
    vmd.append("## Validated (mechanics / infrastructure)\n")
    vmd.append(
        "- V5.0 options backtest engine: decision<fill causality, daily MTM, "
        "expiration settlement, force-close at final bar, defined-risk "
        "debit/credit accounting. Verified across 24+ (window x strategy) "
        "runs, all causality-clean, deterministic.\n"
        "- Defined-risk debit AND credit vertical accounting (bull_call / "
        "bear_put debit; bull_put credit). Naked / unlimited-risk structures "
        "are impossible by construction.\n"
        "- No look-ahead / causality discipline (asserted in engine + tested).\n"
        "- ThetaData historical options pipeline: full calendar-year SPY 2022, "
        "1,096,626 canonical rows, 251 date-files, 100% Greeks coverage, "
        "0 validator hard rejects, 0 processed duplicate rows.\n"
        "- IV / Greeks enrichment (greeks/eod), edge-of-band 472 handling, "
        "240s OPEX timeout, multi-chunk EOD + Greeks-regeneration repair.\n"
        "- Cost / spread sensitivity reporting (V5.4).\n"
        "- Rolling-window (V5.5) + non-overlapping (V5.6) stability framework.\n"
        "- Macro / FRED / event read-only research + annotation layer (V5.7), "
        "including expectancy / tradability decomposition.\n"
        "- 219/219 pytest green throughout.\n"
    )
    vmd.append("\n## NOT validated (no evidence yet)\n")
    vmd.append(
        "- A deployable trading edge.\n"
        "- Regime-independent profitability for any of the three verticals.\n"
        "- Live / paper execution of any kind.\n"
        "- IBKR (or any broker) execution.\n"
        "- Any options strategy suitable for deployment.\n"
        "- Macro / regime / event signals as TRADING filters (V5.7 is "
        "annotation only; no signal feeds the engine).\n"
    )
    (OUT_DIR / "validated_vs_not_validated.md").write_text(
        "\n".join(vmd), encoding="utf-8")

    # ---- next_research_plan.md ----
    nmd = []
    nmd.append("# V5.7.1 Next research plan (ranked)\n")
    nmd.append(
        "Priorities are RESEARCH directions, not deployment steps. "
        "`LIVE_TRADING_ENABLED` stays False until a real, regime-robust edge "
        "is demonstrated out-of-sample.\n"
    )
    nmd.append("\n## A. New strategy research (highest priority)\n")
    nmd.append(
        "The three directional verticals are exhausted as edge candidates. "
        "Research instead structures whose thesis is NOT pure direction:\n"
        "- **IV / volatility-risk-premium (VRP):** sell defined-risk premium "
        "when implied >> realized; the V5.7 layer already has IV + a realized-"
        "vol helper to build the IV-RV spread signal.\n"
        "- **Range-filtered defined-risk credit structures:** iron condors / "
        "credit spreads gated by an explicit IV-rank / expected-move filter, "
        "so entries require a vol-premium condition, not a direction call.\n"
        "- **Calendar / diagonal spreads** if the data's DTE coverage supports "
        "a front/back structure (term-structure premium).\n"
        "- **Regime-aware strategy selection** (e.g. bear_put in down regimes, "
        "bull_put in up regimes) — but this is only worth pursuing AFTER strict "
        "out-of-sample testing, since it risks fitting the 2022 regime labels.\n"
        "Every new structure must clear the SAME falsification stack "
        "(V5.3->V5.6 + Stage 2A/2B-style regime splits) before any edge claim.\n"
    )
    nmd.append("\n## B. Company / fundamentals research layer\n")
    nmd.append(
        "- SEC EDGAR (10-K / 10-Q / 8-K) read-only ingestion.\n"
        "- Balance-sheet / debt / liquidity / revenue-earnings context.\n"
        "- Company-specific options research (e.g. AAPL / NVDA) once a "
        "single-name options dataset is approved.\n"
        "- LSEG / Datastream only if a license is available.\n"
        "Read-only and additive, like the V5.7 macro layer. No trading signal "
        "until separately validated.\n"
    )
    nmd.append("\n## C. Optional 2023 Q1 confirmation\n")
    nmd.append(
        "- SPY Jan-Mar 2023 (one quarter) is OPTIONAL out-of-sample "
        "confirmation in a non-2022 recovery/sideways regime.\n"
        "- Expected to re-confirm the regime-directional reading (bull_put "
        "relatively better, bear_put worse). Not required for the verdict.\n"
        "- Fetch ONLY if paired with a specific new hypothesis (e.g. testing "
        "an IV/VRP structure on fresh data), not to re-test rejected verticals.\n"
    )
    nmd.append("\n## D. V6 paper trading — NOT yet\n")
    nmd.append(
        "- Premature: no edge established.\n"
        "- Would require live options data + options permission (and, for "
        "IBKR paper orders, a broker connection) — all currently OUT of scope.\n"
        "- Defer until a strategy demonstrates regime-robust positive "
        "expectancy out-of-sample.\n"
    )
    (OUT_DIR / "next_research_plan.md").write_text("\n".join(nmd), encoding="utf-8")

    # ---- console ----
    print("Final verdict table:")
    print(verdict.to_string(index=False))
    print(f"\nArtifacts -> {OUT_DIR}")
    return 0


VERDICTS = {
    "bear_put": "REJECTED as regime-independent edge; regime-directional bearish bet (engine validated)",
    "bull_put": "NOT deployable; positive only in Q4 recovery; regime-directional bullish/credit bet",
    "bull_call": "NOT deployable; improved toward flat in recovery but no persistent positive expectancy",
}


if __name__ == "__main__":
    sys.exit(main())
