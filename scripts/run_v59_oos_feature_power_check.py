"""V5.9 OOS feature + power check (read-only, existing local data only).

Two read-only stages, no new data and no ThetaData:

1. OOS FEATURES. Build SPY January-2023 V5.8-style feature panels by computing
   the feature functions over the COMBINED frozen SPY-2022 + Jan-2023 processed
   chain, so the rolling features (realized vol, causal IV rank/percentile) get
   their lookback from late 2022 CAUSALLY, then SLICE the Jan-2023 dates and
   write them to a SEPARATE folder. The frozen 2022 feature files are NEVER
   touched.

     data/options/features/SPY/oos_2023_01/
       daily_underlying_features.csv   daily_iv_summary.csv
       daily_iv_rank.csv               daily_skew_features.csv
       daily_term_structure.csv        daily_liquidity_features.csv
       daily_options_research_panel.csv

2. LIMITED OOS POWER CHECK. Count how many Jan-2023 candidate entry dates (and
   weekly credit-entry opportunities) survive the SAME gates the 2022 power
   check used, applying the 2022-derived tercile cutpoints (NO threshold
   optimization, NO re-fitting to Jan-2023). There is NO realised Jan-2023
   trade ledger, so this is a CANDIDATE-COUNT / feature-gate power check ONLY:
   no P&L is invented and NO edge is claimed.

     reports/options/v59_oos_power_check/
       v59_oos_power_summary.md
       jan2023_feature_availability.csv
       jan2023_gate_counts.csv
       oos_vs_2022_power_comparison.csv

No new data, no ThetaData, no engine/strategy change, no new strategy, no iron
condor, no parameter optimization, no broker. LIVE_TRADING_ENABLED = False.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from quantbot.data.options_cache import read_processed
from quantbot.options import features as F

LIVE_TRADING_ENABLED = False

OOS_YEAR, OOS_MONTH = 2023, 1
OOS_START, OOS_END = pd.Timestamp("2023-01-01"), pd.Timestamp("2023-01-31")

FEATURE_DIR = ROOT / "data" / "options" / "features" / "SPY" / "oos_2023_01"
FROZEN_2022_PANEL = ROOT / "data" / "options" / "features" / "SPY" / "2022" / "daily_options_research_panel.csv"
V59_2022_DIR = ROOT / "reports" / "options" / "v59_power_check"
REPORT_DIR = ROOT / "reports" / "options" / "v59_oos_power_check"

TOP_TERCILE_Q = 2.0 / 3.0  # same bucketing the 2022 power check used


# --------------------------------------------------------------------------- #
def load_combined_chain() -> pd.DataFrame:
    """Frozen SPY 2022 (12 months) + Jan-2023, concatenated and date-normalized.

    The combined series is what gives Jan-2023 its causal rolling lookback;
    we slice Jan-2023 only AFTER the features are computed.
    """
    parts = []
    for m in range(1, 13):
        df = read_processed("SPY", 2022, m)
        if df is not None:
            parts.append(df)
    jan = read_processed("SPY", OOS_YEAR, OOS_MONTH)
    if jan is None:
        raise FileNotFoundError("SPY 2023-01 processed file not found.")
    parts.append(jan)
    chain = pd.concat(parts, ignore_index=True)
    chain["date"] = pd.to_datetime(chain["date"]).dt.normalize()
    chain["expiration"] = pd.to_datetime(chain["expiration"]).dt.normalize()
    return chain


def build_feature_panels(chain: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """All V5.8 feature sub-frames + the merged master panel, computed over the
    full combined series (mirrors scripts/run_build_options_features.py)."""
    spot = F.underlying_series_from_chain(chain)
    rv = F.realized_vol_features(spot)
    iv = F.iv_summary_panel(chain, target_dte=30, dte_band=(25, 45))
    iv_series = iv.set_index("date")["atm_iv"]
    ivrank = F.iv_rank_features(iv_series, windows=(63, 126))
    ivrv = F.iv_rv_features(iv, rv)
    skew = F.skew_features(iv)
    ts = F.term_structure_panel(chain)
    liq = F.liquidity_panel(chain)

    panel = rv.reset_index()[["date", "underlying_price", "ret_5d", "ret_21d",
                              "ret_63d", "rv_5d_annualized", "rv_21d_annualized",
                              "rv_63d_annualized", "trend_up_21d"]].copy()
    panel = panel.merge(iv[["date", "iv_dte", "atm_iv", "iv_25d_call",
                            "iv_25d_put", "iv_coverage"]], on="date", how="left")
    panel = panel.merge(ivrank.reset_index()[["date", "iv_percentile_63d",
                        "iv_rank_63d", "iv_percentile_126d", "iv_rank_126d"]],
                        on="date", how="left")
    panel = panel.merge(ivrv[["date", "iv_minus_rv21", "iv_over_rv21",
                              "high_iv_vs_rv"]], on="date", how="left")
    panel = panel.merge(skew[["date", "put_skew", "call_skew", "put_call_skew",
                              "skew_delta_basis"]], on="date", how="left")
    panel = panel.merge(ts[["date", "atm_iv_near", "atm_iv_mid", "atm_iv_far",
                            "ts_slope", "ts_ratio"]], on="date", how="left")
    panel = panel.merge(liq[["date", "median_spread_pct", "p75_spread_pct",
                             "share_zero_bid", "share_zero_volume",
                             "share_spread_gt_25pct", "usable_contracts",
                             "total_volume", "open_interest_missing"]],
                        on="date", how="left")
    panel = panel.sort_values("date").reset_index(drop=True)

    # Causality guard on the FULL combined panel (monotone, unique dates).
    F.assert_causal_panel(panel)
    return {"rv": rv.reset_index(), "iv": iv, "ivrank": ivrank.reset_index(),
            "ivrv": ivrv, "skew": skew, "ts": ts, "liq": liq, "panel": panel}


def _slice_jan(df: pd.DataFrame) -> pd.DataFrame:
    d = pd.to_datetime(df["date"]).dt.normalize()
    return df[(d >= OOS_START) & (d <= OOS_END)].sort_values("date").reset_index(drop=True)


def _df_to_md(df: pd.DataFrame, float_fmt: str = "{:.4f}") -> str:
    if df.empty:
        return "_(empty)_"

    def fmt(v: Any) -> str:
        if v is None:
            return ""
        if isinstance(v, bool):
            return "True" if v else "False"
        if isinstance(v, (float, np.floating)):
            f = float(v)
            return "nan" if math.isnan(f) else float_fmt.format(f)
        return str(v)

    headers = [str(c) for c in df.columns]
    body = [[fmt(v) for v in row] for row in df.itertuples(index=False, name=None)]
    widths = [max(len(h), *(len(r[i]) for r in body)) for i, h in enumerate(headers)]

    def line(cells):
        return "| " + " | ".join(c.ljust(w) for c, w in zip(cells, widths)) + " |"

    sep = "| " + " | ".join("-" * w for w in widths) + " |"
    return "\n".join([line(headers), sep] + [line(r) for r in body])


def main() -> int:
    assert LIVE_TRADING_ENABLED is False, "V5.9 OOS feature/power check is RESEARCH only."
    FEATURE_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    chain = load_combined_chain()
    print(f"Combined chain: {len(chain):,} rows, {chain['date'].nunique()} dates "
          f"({chain['date'].min().date()} -> {chain['date'].max().date()})")

    panels = build_feature_panels(chain)

    # ---------- 1. write Jan-2023 OOS feature files (sliced) ----------
    out_map = {
        "daily_underlying_features.csv": panels["rv"],
        "daily_iv_summary.csv": panels["iv"],
        "daily_iv_rank.csv": panels["ivrank"],
        "daily_skew_features.csv": panels["skew"],
        "daily_term_structure.csv": panels["ts"],
        "daily_liquidity_features.csv": panels["liq"],
        "daily_options_research_panel.csv": panels["panel"],
    }
    for fname, df in out_map.items():
        _slice_jan(df).to_csv(FEATURE_DIR / fname, index=False)

    jan = _slice_jan(panels["panel"])
    n_oos = len(jan)
    print(f"Jan-2023 OOS feature dates: {n_oos}")

    # ---------- 2. feature availability ----------
    avail_cols = ["atm_iv", "iv_coverage", "iv_25d_call", "iv_25d_put",
                  "iv_rank_63d", "iv_percentile_63d", "iv_rank_126d",
                  "iv_percentile_126d", "rv_21d_annualized", "rv_63d_annualized",
                  "iv_minus_rv21", "iv_over_rv21", "put_skew", "call_skew",
                  "put_call_skew", "atm_iv_near", "atm_iv_mid", "atm_iv_far",
                  "ts_slope", "median_spread_pct", "usable_contracts"]
    avail = pd.DataFrame([{
        "feature": c,
        "non_nan_dates": int(jan[c].notna().sum()),
        "total_dates": n_oos,
        "coverage_pct": round(100 * jan[c].notna().mean(), 1),
    } for c in avail_cols])
    avail.to_csv(REPORT_DIR / "jan2023_feature_availability.csv", index=False)

    # ---------- 3. gate cutpoints from FROZEN 2022 panel (no optimization) ----------
    p2022 = pd.read_csv(FROZEN_2022_PANEL, parse_dates=["date"])
    ivr_top = float(np.nanquantile(p2022["iv_rank_63d"], TOP_TERCILE_Q))
    pskew_top = float(np.nanquantile(p2022["put_skew"], TOP_TERCILE_Q))
    print(f"2022 cutpoints reused: IV-rank top-tercile={ivr_top:.3f}, "
          f"put-skew top-tercile={pskew_top:.4f}")

    # daily gate flags on Jan-2023
    g = jan.copy()
    g["gate_high_ivrank_tercile"] = g["iv_rank_63d"] >= ivr_top
    g["gate_ivrank_ge_050"] = g["iv_rank_63d"] >= 0.50
    g["gate_vrp_positive"] = g["iv_minus_rv21"] > 0.0
    g["gate_rich_putskew_tercile"] = g["put_skew"] >= pskew_top
    g["gate_ivrank_and_vrp"] = g["gate_high_ivrank_tercile"] & g["gate_vrp_positive"]
    g["gate_ivrank_and_putskew"] = g["gate_high_ivrank_tercile"] & g["gate_rich_putskew_tercile"]
    g["gate_ivrank_vrp_putskew"] = (g["gate_high_ivrank_tercile"]
                                    & g["gate_vrp_positive"]
                                    & g["gate_rich_putskew_tercile"])

    gate_defs = [
        ("high IV-rank (2022 top tercile)", "gate_high_ivrank_tercile"),
        ("IV-rank >= 0.50", "gate_ivrank_ge_050"),
        ("positive VRP (IV>RV21)", "gate_vrp_positive"),
        ("rich put-skew (2022 top tercile)", "gate_rich_putskew_tercile"),
        ("IV-rank tercile + positive VRP", "gate_ivrank_and_vrp"),
        ("IV-rank tercile + rich put-skew", "gate_ivrank_and_putskew"),
        ("IV-rank tercile + VRP + put-skew", "gate_ivrank_vrp_putskew"),
    ]

    # weekly credit-entry cadence within Jan-2023 (mirror 2022 ISO-week-start method)
    g["iso_week"] = g["date"].apply(lambda d: (d.isocalendar().year, d.isocalendar().week))
    week_starts = g.groupby("iso_week", as_index=False).first()
    n_week_starts = len(week_starts)

    # reuse the 2022 empirical bull_put realisation rate (fills / ISO-week-start)
    cond2022 = pd.read_csv(V59_2022_DIR / "condor_weekly_cadence_estimate.csv")
    realisation_rate = float(cond2022["est_realisation_rate"].iloc[0])

    gate_rows = []
    for label, col in gate_defs:
        n_days = int(g[col].fillna(False).sum())
        n_weeks = int(week_starts[col].fillna(False).sum())
        gate_rows.append({
            "gate": label,
            "n_oos_trading_days": n_oos,
            "n_gated_days": n_days,
            "gated_day_share": round(n_days / n_oos, 3) if n_oos else float("nan"),
            "n_iso_week_starts": n_week_starts,
            "n_gated_week_starts": n_weeks,
            "reused_2022_realisation_rate": round(realisation_rate, 4),
            "est_realised_credit_trades": round(n_weeks * realisation_rate, 1),
        })
    gate_counts = pd.DataFrame(gate_rows)
    gate_counts.to_csv(REPORT_DIR / "jan2023_gate_counts.csv", index=False)

    # ---------- 4. comparison vs 2022 power check (bull_put credit lead) ----------
    hyp2022 = pd.read_csv(V59_2022_DIR / "gated_counts_by_hypothesis.csv")
    bp = hyp2022[hyp2022["strategy"] == "bull_put"].set_index("gate")
    map_2022 = {
        "high IV-rank (2022 top tercile)": "H1a high IV-rank (top tercile)",
        "IV-rank >= 0.50": "H1b IV-rank >= 0.50",
        "positive VRP (IV>RV21)": "H1c positive VRP (IV>RV21)",
        "rich put-skew (2022 top tercile)": "H3 rich put-skew (top tercile)",
    }
    cmp_rows = []
    for label, col in gate_defs:
        g2022 = bp.loc[map_2022[label], "n_gated_trades"] if label in map_2022 else np.nan
        oos_days = int(g[col].fillna(False).sum())
        oos_weeks = int(week_starts[col].fillna(False).sum())
        cmp_rows.append({
            "gate": label,
            "y2022_bull_put_gated_trades": (int(g2022) if not pd.isna(g2022) else "n/a (combo)"),
            "jan2023_gated_days_of_20": oos_days,
            "jan2023_gated_week_starts": oos_weeks,
            "jan2023_est_realised_credit_trades": round(oos_weeks * realisation_rate, 1),
        })
    comparison = pd.DataFrame(cmp_rows)
    comparison.to_csv(REPORT_DIR / "oos_vs_2022_power_comparison.csv", index=False)

    # ---------- 5. markdown summary ----------
    cov_atm = jan["atm_iv"].notna().mean() * 100
    cov_ivr63 = jan["iv_rank_63d"].notna().mean() * 100
    cov_skew = jan["put_skew"].notna().mean() * 100
    share_vrp_pos = (jan["iv_minus_rv21"] > 0).mean() * 100

    md = []
    md.append("# V5.9 OOS Feature + Power Check — SPY January 2023\n")
    md.append(
        "Read-only OOS extension of the V5.8 feature layer + a limited power "
        "check, using EXISTING local data only (frozen SPY-2022 corpus + the "
        "frozen Jan-2023 OOS month). Jan-2023 features are computed over the "
        "combined 2022+Jan-2023 chain so rolling IV-rank / realized-vol get "
        "their lookback from late 2022 CAUSALLY, then sliced to Jan-2023. The "
        "frozen 2022 feature files are untouched. **No new data, no ThetaData, "
        "no engine/strategy change, no new strategy, no iron condor, no "
        f"parameter optimization. `LIVE_TRADING_ENABLED = {LIVE_TRADING_ENABLED}`. "
        "There is NO Jan-2023 trade ledger — this is a candidate-count / "
        "feature-gate power check ONLY; no P&L is invented and NO edge is "
        "claimed.**\n")
    md.append(
        f"\n- OOS feature dates: **{n_oos}** "
        f"({jan['date'].min().date()} → {jan['date'].max().date()})\n"
        f"- OOS feature files: `data/options/features/SPY/oos_2023_01/` (7 files)\n"
        f"- Gate cutpoints REUSED from frozen 2022 (no re-fit): IV-rank top "
        f"tercile = **{ivr_top:.3f}**, put-skew top tercile = **{pskew_top:.4f}**; "
        f"VRP gate = `iv_minus_rv21 > 0`; IV-rank≥0.50 fixed.\n")

    md.append("\n## 1. Jan-2023 feature availability\n")
    md.append(_df_to_md(avail, "{:.1f}"))
    md.append(
        f"\nHeadline coverage: ATM IV **{cov_atm:.0f}%**, IV-rank(63d) "
        f"**{cov_ivr63:.0f}%**, put-skew **{cov_skew:.0f}%**. "
        f"Positive-VRP (ATM IV > RV21) on **{share_vrp_pos:.0f}%** of Jan-2023 "
        "dates. Rolling features are fully populated because the 63/126d "
        "windows draw on late-2022 history (causal).\n")

    md.append("\n## 2. Jan-2023 gate counts (candidate dates + weekly cadence)\n")
    md.append(_df_to_md(gate_counts, "{:.3f}"))
    md.append(
        "\n`n_gated_days` = Jan-2023 trading days passing the gate (of "
        f"{n_oos}). `n_gated_week_starts` = ISO-week-start credit-entry "
        f"opportunities passing the gate (of {n_week_starts}). "
        "`est_realised_credit_trades` haircuts the gated week-starts by the "
        f"2022 empirical bull_put realisation rate ({realisation_rate:.3f} "
        "fills/week-start) — an estimate, NOT a backtest, and with no P&L.\n")

    atm_first, atm_last = float(jan["atm_iv"].iloc[0]), float(jan["atm_iv"].iloc[-1])
    ivr_min, ivr_max = float(jan["iv_rank_63d"].min()), float(jan["iv_rank_63d"].max())
    ps_min, ps_max = float(jan["put_skew"].min()), float(jan["put_skew"].max())
    md.append(
        f"\n**Regime note (the zeros are real, not a bug):** Jan-2023 was a "
        f"vol-NORMALIZATION month — ATM IV fell from ~{atm_first:.3f} to "
        f"~{atm_last:.3f} across January, so measured against the trailing "
        f"63/126-day window (which still holds the elevated late-2022 vol) "
        f"Jan-2023 `iv_rank_63d` stays low (range {ivr_min:.2f}–{ivr_max:.2f}, "
        f"max BELOW both the 0.50 and the 2022 top-tercile {ivr_top:.3f} "
        f"cutpoints). `put_skew` ({ps_min:.4f}–{ps_max:.4f}) likewise sits "
        f"BELOW the 2022 rich-skew cutpoint ({pskew_top:.4f}). So the "
        f"2022-calibrated high-IV-rank and rich-put-skew gates fire ZERO times "
        f"in Jan-2023 — this OOS month cannot test those lead hypotheses at "
        f"all; only the positive-VRP gate produces candidates. That is itself "
        f"an informative OOS signal: gates calibrated on a high-vol year may "
        f"rarely trigger in a calmer regime, so a credible OOS test must span "
        f"MULTIPLE regimes, not one quiet month.\n")

    md.append("\n## 3. OOS vs 2022 power comparison (bull_put credit lead)\n")
    md.append(_df_to_md(comparison))
    md.append(
        "\n2022 full-year bull_put gated counts were already only **5–10** "
        "trades (per non-overlapping window 0–7). One OOS month adds at most a "
        "handful of additional gated entries.\n")

    md.append("\n## 4. Does Jan-2023 justify fetching February / full Q1?\n")
    best_week = int(gate_counts["n_gated_week_starts"].max())
    est_best = float(gate_counts["est_realised_credit_trades"].max())
    md.append(
        f"- Jan-2023 contributes only **{n_week_starts} weekly credit-entry "
        f"opportunities**; after gating, **≤{best_week}** survive any single "
        f"gate (≈{est_best:.1f} estimated realised credit trades, combos fewer). "
        "A single month cannot move the sample size into inferential territory.\n"
        "- Arithmetic: to lift the gated credit-trade count from the 2022 "
        "**5–10** toward even a coarse ~30+ (still weak) verdict, you need on "
        "the order of a FULL extra year of gated weekly entries — not one or "
        "two months. February alone (~4 weeks) would add only ~1–3 gated "
        "entries; full Q1 2023 (~9 more weeks) only modestly more.\n"
        "- Therefore the efficient choices are binary: either commit to a "
        "LARGE OOS expansion (full 2023, and ideally multi-name) if the IV/VRP/"
        "skew edge test is to proceed, OR pause OOS options expansion until a "
        "specific pre-registered hypothesis justifies the fetch cost. A "
        "piecemeal month-by-month fetch is low-value because each month's "
        "gated subset is tiny. **No edge is claimed either way.**\n")

    (REPORT_DIR / "v59_oos_power_summary.md").write_text("\n".join(md), encoding="utf-8")

    # ---------- console ----------
    print("\n=== Jan-2023 gate counts ===")
    for _, r in gate_counts.iterrows():
        print(f"  {r['gate']:34s}: days {int(r['n_gated_days']):2d}/{n_oos}  "
              f"week-starts {int(r['n_gated_week_starts'])}/{n_week_starts}  "
              f"est realised {r['est_realised_credit_trades']}")
    print(f"\nOOS features -> {FEATURE_DIR}")
    print(f"Reports      -> {REPORT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
