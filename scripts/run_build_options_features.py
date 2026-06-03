"""V5.8 options research feature builder (read-only, existing data only).

Loads the frozen full-year SPY 2022 processed chain, builds the V5.8
feature panels with quantbot.options.features (pure, causal), and writes:

  data/options/features/SPY/2022/
    daily_underlying_features.csv
    daily_iv_summary.csv
    daily_iv_rank.csv
    daily_skew_features.csv
    daily_term_structure.csv
    daily_liquidity_features.csv
    daily_options_research_panel.csv      (merged master panel)

  reports/options/v58_research_features/
    v58_summary.md
    feature_availability.csv
    iv_rv_summary.csv
    skew_summary.csv
    term_structure_summary.csv
    liquidity_summary.csv
    sample_feature_panel.csv

No new data fetch, no ThetaData, no engine/strategy changes, no broker.
LIVE_TRADING_ENABLED stays False. NOT a trading signal -- features only.
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
FEATURE_DIR = ROOT / "data" / "options" / "features" / "SPY" / "2022"
REPORT_DIR = ROOT / "reports" / "options" / "v58_research_features"


def load_full_year() -> pd.DataFrame:
    parts = []
    for m in range(1, 13):
        df = read_processed("SPY", 2022, m)
        if df is None:
            continue
        parts.append(df)
    if not parts:
        raise FileNotFoundError("No SPY 2022 processed files found.")
    df = pd.concat(parts, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df["expiration"] = pd.to_datetime(df["expiration"]).dt.normalize()
    return df


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


def _write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def main() -> int:
    assert LIVE_TRADING_ENABLED is False, "V5.8 feature build is RESEARCH only."
    FEATURE_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    chain = load_full_year()
    n_dates = chain["date"].nunique()
    print(f"Loaded SPY chain: {len(chain):,} rows, {n_dates} dates "
          f"({chain['date'].min().date()} -> {chain['date'].max().date()})")

    # ---- 1. underlying / realized vol ----
    spot = F.underlying_series_from_chain(chain)
    rv = F.realized_vol_features(spot)
    _write_csv(rv.reset_index(), FEATURE_DIR / "daily_underlying_features.csv")

    # ---- 2. IV summary ----
    iv = F.iv_summary_panel(chain, target_dte=30, dte_band=(25, 45))
    _write_csv(iv, FEATURE_DIR / "daily_iv_summary.csv")

    # ---- 3. IV rank / percentile (causal) ----
    iv_series = iv.set_index("date")["atm_iv"]
    ivrank = F.iv_rank_features(iv_series, windows=(63, 126))
    _write_csv(ivrank.reset_index(), FEATURE_DIR / "daily_iv_rank.csv")

    # ---- 4. IV vs RV ----
    ivrv = F.iv_rv_features(iv, rv)
    # ---- 5. skew ----
    skew = F.skew_features(iv)
    _write_csv(skew, FEATURE_DIR / "daily_skew_features.csv")

    # ---- 6. term structure ----
    ts = F.term_structure_panel(chain)
    _write_csv(ts, FEATURE_DIR / "daily_term_structure.csv")

    # ---- 7. liquidity ----
    liq = F.liquidity_panel(chain)
    _write_csv(liq, FEATURE_DIR / "daily_liquidity_features.csv")

    # ---- master research panel (merge on date) ----
    panel = rv.reset_index()[["date", "underlying_price", "ret_5d", "ret_21d",
                               "ret_63d", "rv_5d_annualized",
                               "rv_21d_annualized", "rv_63d_annualized",
                               "trend_up_21d"]].copy()
    panel = panel.merge(
        iv[["date", "iv_dte", "atm_iv", "iv_25d_call", "iv_25d_put",
            "iv_coverage"]], on="date", how="left")
    panel = panel.merge(
        ivrank.reset_index()[["date", "iv_percentile_63d", "iv_rank_63d",
                               "iv_percentile_126d", "iv_rank_126d"]],
        on="date", how="left")
    panel = panel.merge(
        ivrv[["date", "iv_minus_rv21", "iv_over_rv21", "high_iv_vs_rv"]],
        on="date", how="left")
    panel = panel.merge(
        skew[["date", "put_skew", "call_skew", "put_call_skew",
              "skew_delta_basis"]], on="date", how="left")
    panel = panel.merge(
        ts[["date", "atm_iv_near", "atm_iv_mid", "atm_iv_far",
            "ts_slope", "ts_ratio"]], on="date", how="left")
    panel = panel.merge(
        liq[["date", "median_spread_pct", "p75_spread_pct", "share_zero_bid",
             "share_zero_volume", "share_spread_gt_25pct", "usable_contracts",
             "total_volume", "open_interest_missing"]], on="date", how="left")
    panel = panel.sort_values("date").reset_index(drop=True)
    _write_csv(panel, FEATURE_DIR / "daily_options_research_panel.csv")

    # ---- causality checks (explicit) ----
    F.assert_causal_panel(panel)
    F.assert_causal_panel(rv.reset_index())
    F.assert_causal_panel(ivrank.reset_index())
    # rolling features only use backward windows (pandas .rolling) -> causal.
    causal_ok = True

    # =================== reports ===================
    # feature_availability.csv
    avail_rows = []
    for col in ["atm_iv", "iv_25d_call", "iv_25d_put", "iv_30d_call",
                "iv_30d_put", "iv_coverage"]:
        avail_rows.append({"feature": col,
                            "non_nan_dates": int(iv[col].notna().sum()),
                            "total_dates": len(iv),
                            "coverage_pct": round(100 * iv[col].notna().mean(), 1)})
    for col in ["iv_percentile_63d", "iv_rank_63d", "iv_percentile_126d",
                "iv_rank_126d"]:
        avail_rows.append({"feature": col,
                            "non_nan_dates": int(ivrank[col].notna().sum()),
                            "total_dates": len(ivrank),
                            "coverage_pct": round(100 * ivrank[col].notna().mean(), 1)})
    for col, src in [("rv_21d_annualized", rv), ("rv_63d_annualized", rv)]:
        avail_rows.append({"feature": col,
                            "non_nan_dates": int(src[col].notna().sum()),
                            "total_dates": len(src),
                            "coverage_pct": round(100 * src[col].notna().mean(), 1)})
    for col in ["put_skew", "call_skew", "put_call_skew"]:
        avail_rows.append({"feature": col,
                            "non_nan_dates": int(skew[col].notna().sum()),
                            "total_dates": len(skew),
                            "coverage_pct": round(100 * skew[col].notna().mean(), 1)})
    for col in ["atm_iv_near", "atm_iv_mid", "atm_iv_far", "ts_slope"]:
        avail_rows.append({"feature": col,
                            "non_nan_dates": int(ts[col].notna().sum()),
                            "total_dates": len(ts),
                            "coverage_pct": round(100 * ts[col].notna().mean(), 1)})
    avail = pd.DataFrame(avail_rows)
    _write_csv(avail, REPORT_DIR / "feature_availability.csv")

    # iv_rv_summary.csv
    ivrv_summary = pd.DataFrame([{
        "metric": "iv_minus_rv21",
        "mean": float(ivrv["iv_minus_rv21"].mean()),
        "median": float(ivrv["iv_minus_rv21"].median()),
        "min": float(ivrv["iv_minus_rv21"].min()),
        "max": float(ivrv["iv_minus_rv21"].max()),
        "share_positive": float((ivrv["iv_minus_rv21"] > 0).mean()),
    }, {
        "metric": "iv_over_rv21",
        "mean": float(ivrv["iv_over_rv21"].mean()),
        "median": float(ivrv["iv_over_rv21"].median()),
        "min": float(ivrv["iv_over_rv21"].min()),
        "max": float(ivrv["iv_over_rv21"].max()),
        "share_positive": float((ivrv["iv_over_rv21"] > 1).mean()),
    }])
    _write_csv(ivrv_summary, REPORT_DIR / "iv_rv_summary.csv")

    # skew_summary.csv
    skew_summary = pd.DataFrame([{
        "metric": c,
        "mean": float(skew[c].mean()), "median": float(skew[c].median()),
        "min": float(skew[c].min()), "max": float(skew[c].max()),
        "non_nan_dates": int(skew[c].notna().sum()),
    } for c in ["put_skew", "call_skew", "put_call_skew"]])
    _write_csv(skew_summary, REPORT_DIR / "skew_summary.csv")

    # term_structure_summary.csv
    ts_summary = pd.DataFrame([{
        "metric": c,
        "mean": float(ts[c].mean()), "median": float(ts[c].median()),
        "min": float(ts[c].min()), "max": float(ts[c].max()),
        "non_nan_dates": int(ts[c].notna().sum()),
    } for c in ["atm_iv_near", "atm_iv_mid", "atm_iv_far", "ts_slope", "ts_ratio"]])
    _write_csv(ts_summary, REPORT_DIR / "term_structure_summary.csv")

    # liquidity_summary.csv
    liq_summary = pd.DataFrame([{
        "metric": c,
        "mean": float(liq[c].mean()), "median": float(liq[c].median()),
        "min": float(liq[c].min()), "max": float(liq[c].max()),
    } for c in ["median_spread_pct", "p75_spread_pct", "share_zero_bid",
                "share_zero_volume", "share_spread_gt_25pct",
                "usable_contracts", "total_volume"]])
    _write_csv(liq_summary, REPORT_DIR / "liquidity_summary.csv")

    # sample_feature_panel.csv (head 10 + tail 5)
    sample = pd.concat([panel.head(10), panel.tail(5)])
    _write_csv(sample, REPORT_DIR / "sample_feature_panel.csv")

    # ---- v58_summary.md ----
    oi_missing_all = bool(liq["open_interest_missing"].all())
    md = []
    md.append("# V5.8 Options Research Feature Layer — SPY full-year 2022\n")
    md.append(
        "Read-only feature foundation built from the EXISTING processed SPY "
        "2022 corpus (no new data, no ThetaData, no engine/strategy changes, "
        f"no parameter optimization). `LIVE_TRADING_ENABLED = {LIVE_TRADING_ENABLED}`. "
        "**These are descriptive features only — NOT trading signals.**\n"
    )
    md.append(f"\n- Feature dates: **{len(panel)}** "
              f"({panel['date'].min().date()} → {panel['date'].max().date()})\n"
              f"- Master panel: `data/options/features/SPY/2022/"
              f"daily_options_research_panel.csv` ({panel.shape[1]} columns)\n")

    md.append("\n## 1. Feature availability\n")
    md.append(_df_to_md(avail, "{:.1f}"))

    md.append("\n## 2. IV vs RV\n")
    md.append(_df_to_md(ivrv_summary))
    md.append(
        f"\nATM IV exceeded 21d realized vol on "
        f"**{(ivrv['iv_minus_rv21'] > 0).mean()*100:.1f}%** of dates "
        f"(a positive variance-risk-premium proxy is common but not "
        f"universal in this sample).\n"
    )

    md.append("\n## 3. Skew\n")
    md.append(_df_to_md(skew_summary))
    md.append(
        "\nPut skew (25d put IV − ATM IV) is the headline equity-index skew "
        "feature; a positive put_skew / put_call_skew indicates downside "
        "protection priced richer than upside — the usual equity-index shape.\n"
    )

    md.append("\n## 4. Term structure (max_dte=45 limited)\n")
    md.append(_df_to_md(ts_summary))
    md.append(
        "\n**Limitation:** the corpus is capped at `max_dte=45`, so the 'far' "
        "bucket is only 30–45 DTE. True term-structure analysis (e.g. 30 vs "
        "90/180 DTE) is NOT possible with this data; `ts_slope`/`ts_ratio` "
        "here measure only the short-end (≈10d vs ≈37d) curve.\n"
    )

    md.append("\n## 5. Liquidity / cost\n")
    md.append(_df_to_md(liq_summary))
    md.append(
        f"\n**Open interest:** {'MISSING on every date' if oi_missing_all else 'partially available'} "
        f"— the V4 ThetaData pipeline did not populate OI, so `open_interest` "
        f"is all-zero. The `open_interest_missing` flag = "
        f"{oi_missing_all} for the whole sample; OI-based liquidity features "
        f"are unavailable. Volume IS present and usable.\n"
    )

    md.append("\n## 6. Sample of the master research panel (head)\n")
    cols = ["date", "underlying_price", "rv_21d_annualized", "atm_iv",
            "iv_rank_63d", "iv_minus_rv21", "put_skew", "ts_slope",
            "median_spread_pct", "usable_contracts"]
    md.append(_df_to_md(panel[cols].head(8)))

    md.append("\n## 7. Causality / no-look-ahead\n")
    md.append(
        f"- Master panel dates strictly monotonic & unique: **{causal_ok}**.\n"
        "- Realized vol uses only past/current closes (backward `.rolling`).\n"
        "- IV percentile/rank use backward `.rolling(window)` (date t sees "
        "only data ≤ t); early dates < min_periods → NaN + "
        "`insufficient_history_*` flag.\n"
        "- No feature for date t reads a later option chain.\n"
    )

    md.append("\n## 8. How these features support future strategy research\n")
    md.append(
        "- **IV/VRP strategies:** `iv_minus_rv21`, `iv_over_rv21`, "
        "`iv_rank_63d/126d` give the vol-premium condition for defined-risk "
        "premium selling.\n"
        "- **Range-filtered credit (iron condors / spreads):** `iv_rank`, "
        "`put_skew`, and `median_spread_pct` gate entries on a vol-premium / "
        "liquidity condition rather than direction.\n"
        "- **Skew / risk-reversal:** `put_skew`, `call_skew`, `put_call_skew`.\n"
        "- **Term-structure (short-end only here):** `ts_slope`, `ts_ratio`.\n"
        "- **Regime-aware selection:** combine with the V5.7 macro/FRED/event "
        "context. **All of this is feature plumbing — no edge is claimed.**\n"
    )

    md.append("\n## 9. Limitations\n")
    md.append(
        "- `max_dte=45` caps term-structure to the short end.\n"
        "- Open interest unavailable (all-zero); OI-based depth features absent.\n"
        "- IV is NaN on deep-ITM/wing rows (~10–15%); ATM/25d/30d wing IVs are "
        "occasionally NaN on illiquid dates and handled as NaN, not errors.\n"
        "- Single underlying (SPY), single calendar year (2022). No edge, no "
        "out-of-sample claim — this is a feature foundation only.\n"
    )

    (REPORT_DIR / "v58_summary.md").write_text("\n".join(md), encoding="utf-8")

    print(f"\nFeature files -> {FEATURE_DIR}")
    print(f"Reports       -> {REPORT_DIR}")
    print(f"Master panel rows: {len(panel)}  cols: {panel.shape[1]}")
    print(f"ATM IV coverage: {iv['atm_iv'].notna().mean()*100:.1f}%  "
          f"IV-rank(63d) coverage: {ivrank['iv_rank_63d'].notna().mean()*100:.1f}%")
    print(f"OI missing all dates: {oi_missing_all}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
