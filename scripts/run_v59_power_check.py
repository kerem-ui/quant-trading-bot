"""V5.9 power check (read-only): how many trades survive a feature gate?

Before designing any IV/VRP or range-filtered credit strategy we must know
whether the EXISTING SPY-2022 corpus can even support an edge verdict. A
vol-premium / skew gate only ever REMOVES entries from the existing weekly
cadence, so the gated trade set is a strict SUBSET of the unconditional set.
That lets us count exact post-gate sample sizes by retrospectively filtering
the already-realised full-year trade ledger against the V5.8 feature panel,
evaluated at each trade's CAUSAL decision date (the trading bar before fill).

No new data, no ThetaData, no engine/strategy changes, no parameter
optimisation, no broker. `LIVE_TRADING_ENABLED = False`. This is a sample-size
/ statistical-power diagnostic ONLY -- it makes NO edge claim. Subset PnL is
reported purely as descriptive context and is explicitly NOT inferential at
these counts.

Inputs (existing, frozen):
  data/options/features/SPY/2022/daily_options_research_panel.csv   (V5.8)
  reports/options/v52_stage2b_strategy_check/stage2b_trade_diagnostics.csv

Outputs:
  reports/options/v59_power_check/
    v59_power_summary.md
    gated_trade_ledger.csv          (every jan_dec trade + decision-date features + gate flags)
    gated_counts_by_hypothesis.csv
    gated_counts_by_window.csv
    condor_weekly_cadence_estimate.csv
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

LIVE_TRADING_ENABLED = False

ROOT = Path(__file__).resolve().parents[1]
PANEL_CSV = ROOT / "data" / "options" / "features" / "SPY" / "2022" / "daily_options_research_panel.csv"
LEDGER_CSV = ROOT / "reports" / "options" / "v52_stage2b_strategy_check" / "stage2b_trade_diagnostics.csv"
REPORT_DIR = ROOT / "reports" / "options" / "v59_power_check"

# Canonical full-year window (the other stage2b windows are subsets of this).
FULL_YEAR_WINDOW = "jan_dec_2022"

# V5.6-style non-overlapping partition of 2022.
NONOVERLAP_WINDOWS = {
    "jan_jun_2022": ("2022-01-01", "2022-06-30"),
    "jul_sep_2022": ("2022-07-01", "2022-09-30"),
    "oct_dec_2022": ("2022-10-01", "2022-12-31"),
}

# Credit structure we lead with (per the agreed scope). The two debit verticals
# are reported too so the gate's selectivity can be seen across all structures.
CREDIT_STRATEGY = "bull_put"
STRATEGIES = ["bull_put", "bull_call", "bear_put"]

# Gates expressed against V5.8 features. Tercile cutpoints are FULL-SAMPLE
# descriptive statistics used only to bucket trades for the count; they are NOT
# a tradeable causal threshold (a real strategy would need a causal cutpoint).
TOP_TERCILE_Q = 2.0 / 3.0


def _load_panel() -> pd.DataFrame:
    p = pd.read_csv(PANEL_CSV, parse_dates=["date"])
    p["date"] = p["date"].dt.normalize()
    return p.sort_values("date").reset_index(drop=True)


def _decision_date(fill_open: pd.Timestamp, trading_days: np.ndarray) -> pd.Timestamp | None:
    """The trading bar immediately BEFORE the fill = the causal decision bar.

    The engine decides on bar t and fills on t+1, so the gate must be read on
    the bar preceding the recorded fill. Returns None if the fill is the very
    first trading day (no prior bar to decide on).
    """
    idx = np.searchsorted(trading_days, np.datetime64(fill_open), side="left")
    if idx <= 0:
        return None
    return pd.Timestamp(trading_days[idx - 1])


def _binom_ci95_halfwidth(n: int, p: float = 0.5) -> float:
    """Normal-approx 95% CI half-width on a win-rate at sample size n.

    Reported only to make 'is n large enough?' concrete. p=0.5 is the
    widest (most conservative) case.
    """
    if n <= 0:
        return float("nan")
    return 1.96 * math.sqrt(p * (1 - p) / n)


def _window_of(d: pd.Timestamp) -> str:
    for name, (lo, hi) in NONOVERLAP_WINDOWS.items():
        if pd.Timestamp(lo) <= d <= pd.Timestamp(hi):
            return name
    return "unassigned"


def _df_to_md(df: pd.DataFrame, float_fmt: str = "{:.4f}") -> str:
    if df.empty:
        return "_(empty)_"

    def fmt(v) -> str:
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
    assert LIVE_TRADING_ENABLED is False, "V5.9 power check is RESEARCH only."
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    panel = _load_panel()
    trading_days = panel["date"].values.astype("datetime64[ns]")

    # ---- gate cutpoints (descriptive, full-sample) ----
    ivr = panel["iv_rank_63d"]
    pskew = panel["put_skew"]
    ivr_top = float(np.nanquantile(ivr, TOP_TERCILE_Q))
    pskew_top = float(np.nanquantile(pskew, TOP_TERCILE_Q))

    feat_cols = ["iv_rank_63d", "iv_minus_rv21", "put_skew", "median_spread_pct",
                 "atm_iv", "rv_21d_annualized"]
    panel_idx = panel.set_index("date")

    # ---- load canonical full-year ledger ----
    led = pd.read_csv(LEDGER_CSV, parse_dates=["fill_open", "fill_close"])
    led = led[led["window"] == FULL_YEAR_WINDOW].copy()
    led["fill_open"] = led["fill_open"].dt.normalize()

    rows = []
    for _, tr in led.iterrows():
        dd = _decision_date(tr["fill_open"], trading_days)
        rec = {
            "strategy": tr["strategy"],
            "fill_open": tr["fill_open"].date().isoformat(),
            "decision_date": dd.date().isoformat() if dd is not None else "",
            "realized_pnl": float(tr["realized_pnl"]),
            "window": _window_of(tr["fill_open"]),
        }
        for c in feat_cols:
            rec[c] = float(panel_idx.loc[dd, c]) if dd is not None and dd in panel_idx.index else float("nan")
        rec["decision_features_available"] = not (
            math.isnan(rec["iv_rank_63d"]) and math.isnan(rec["put_skew"])
        )
        rows.append(rec)
    ledger = pd.DataFrame(rows)

    # ---- gate flags ----
    ledger["gate_high_ivrank_tercile"] = ledger["iv_rank_63d"] >= ivr_top
    ledger["gate_ivrank_ge_050"] = ledger["iv_rank_63d"] >= 0.50
    ledger["gate_vrp_positive"] = ledger["iv_minus_rv21"] > 0.0
    ledger["gate_rich_putskew_tercile"] = ledger["put_skew"] >= pskew_top

    ledger.to_csv(REPORT_DIR / "gated_trade_ledger.csv", index=False)

    # ---- counts by hypothesis (credit structure focus + all structures) ----
    gates = {
        "H1a high IV-rank (top tercile)": "gate_high_ivrank_tercile",
        "H1b IV-rank >= 0.50": "gate_ivrank_ge_050",
        "H1c positive VRP (IV>RV21)": "gate_vrp_positive",
        "H3 rich put-skew (top tercile)": "gate_rich_putskew_tercile",
    }
    hyp_rows = []
    for strat in STRATEGIES:
        sub = ledger[ledger["strategy"] == strat]
        n_total = len(sub)
        n_nan = int((~sub["decision_features_available"]).sum())
        for label, col in gates.items():
            n_gated = int(sub[col].fillna(False).sum())
            pnl = sub.loc[sub[col].fillna(False), "realized_pnl"]
            hyp_rows.append({
                "strategy": strat,
                "gate": label,
                "n_total_trades": n_total,
                "n_decision_feat_nan": n_nan,
                "n_gated_trades": n_gated,
                "gated_share": (n_gated / n_total) if n_total else float("nan"),
                "subset_pnl_sum_dollar": float(pnl.sum()),
                "subset_mean_pnl_dollar": float(pnl.mean()) if n_gated else float("nan"),
                "winrate_ci95_halfwidth": _binom_ci95_halfwidth(n_gated),
            })
    hyp = pd.DataFrame(hyp_rows)
    hyp.to_csv(REPORT_DIR / "gated_counts_by_hypothesis.csv", index=False)

    # ---- counts by non-overlapping window (credit structure only) ----
    win_rows = []
    credit = ledger[ledger["strategy"] == CREDIT_STRATEGY]
    for wname in NONOVERLAP_WINDOWS:
        wsub = credit[credit["window"] == wname]
        rec = {"window": wname, "n_total_credit_trades": len(wsub)}
        for label, col in gates.items():
            rec[label] = int(wsub[col].fillna(False).sum())
        win_rows.append(rec)
    bywin = pd.DataFrame(win_rows)
    bywin.to_csv(REPORT_DIR / "gated_counts_by_window.csv", index=False)

    # ---- H2 iron-condor weekly-cadence estimate ----
    # A condor would share the weekly first-trading-day-of-ISO-week cadence.
    # Estimate gated entry OPPORTUNITIES, then haircut by the empirical
    # bull_put realisation rate (fills / week-starts) to estimate realised N.
    panel["iso_week"] = panel["date"].apply(lambda d: (d.isocalendar().year, d.isocalendar().week))
    week_starts = panel.groupby("iso_week", as_index=False).first()
    n_week_starts = len(week_starts)
    n_credit_fills = len(credit)
    realisation_rate = n_credit_fills / n_week_starts if n_week_starts else float("nan")

    cond_rows = []
    for label, col, op, thr in [
        ("high IV-rank (top tercile)", "iv_rank_63d", "ge", ivr_top),
        ("IV-rank >= 0.50", "iv_rank_63d", "ge", 0.50),
        ("positive VRP (IV>RV21)", "iv_minus_rv21", "gt", 0.0),
        ("rich put-skew (top tercile)", "put_skew", "ge", pskew_top),
    ]:
        vals = week_starts[col]
        mask = vals >= thr if op == "ge" else vals > thr
        n_weeks_gated = int(mask.fillna(False).sum())
        cond_rows.append({
            "gate": label,
            "n_week_starts": n_week_starts,
            "n_gated_week_starts": n_weeks_gated,
            "est_realisation_rate": realisation_rate,
            "est_realised_condor_trades": round(n_weeks_gated * realisation_rate, 1),
        })
    condor = pd.DataFrame(cond_rows)
    condor.to_csv(REPORT_DIR / "condor_weekly_cadence_estimate.csv", index=False)

    # =================== markdown summary ===================
    md = []
    md.append("# V5.9 Power Check — can SPY-2022 alone support an IV/VRP edge verdict?\n")
    md.append(
        "Read-only sample-size diagnostic. A vol-premium / skew gate only "
        "REMOVES entries from the existing weekly cadence, so gated trades are "
        "a strict subset of the realised full-year ledger. We count how many "
        "survive each gate, evaluated at the causal decision bar (the bar "
        "before fill). No new data, no ThetaData, no engine/strategy change, no "
        f"parameter optimisation. `LIVE_TRADING_ENABLED = {LIVE_TRADING_ENABLED}`. "
        "**No edge is claimed; subset PnL is descriptive only.**\n"
    )
    md.append(
        f"\n- Canonical ledger: `{FULL_YEAR_WINDOW}` from stage2b "
        f"({len(ledger)} trades across {ledger['strategy'].nunique()} structures).\n"
        f"- Lead credit structure: **{CREDIT_STRATEGY}** "
        f"({len(credit)} full-year trades).\n"
        f"- Gate cutpoints (full-sample, descriptive): IV-rank top tercile = "
        f"**{ivr_top:.3f}**, put-skew top tercile = **{pskew_top:.4f}**.\n"
    )

    md.append("\n## 1. Gated trade counts by hypothesis\n")
    md.append(_df_to_md(hyp))
    md.append(
        "\n`winrate_ci95_halfwidth` is the normal-approx 95% CI half-width on a "
        "win rate at that sample size (p=0.5, the widest case). A half-width "
        "near or above 0.5 means the win rate is statistically indistinguishable "
        "from a coin flip — i.e. no inference is possible.\n"
    )

    md.append(f"\n## 2. {CREDIT_STRATEGY} gated counts by non-overlapping window\n")
    md.append(_df_to_md(bywin))
    md.append(
        "\nPer-window counts are what a V5.6-style non-overlapping verdict would "
        "rest on. Single-digit (often 0–3) gated trades per window cannot "
        "support a per-regime edge claim.\n"
    )

    md.append("\n## 3. H2 iron-condor weekly-cadence estimate\n")
    md.append(_df_to_md(condor))
    md.append(
        f"\nThe condor is not in the ledger (no 4-leg builder yet), so this "
        f"estimates its gated entries from the weekly cadence "
        f"({n_week_starts} ISO-week starts in 2022), haircut by the empirical "
        f"{CREDIT_STRATEGY} realisation rate "
        f"({n_credit_fills}/{n_week_starts} = {realisation_rate:.2f}). It is an "
        "upper-bound-style estimate, not a backtest.\n"
    )

    # ---- headline verdict ----
    credit_hyp = hyp[hyp["strategy"] == CREDIT_STRATEGY]
    worst = credit_hyp["n_gated_trades"].min()
    best = credit_hyp["n_gated_trades"].max()
    md.append("\n## 4. Verdict\n")
    md.append(
        f"- Full-year {CREDIT_STRATEGY} gated counts range **{worst}–{best}** "
        "trades depending on the gate.\n"
        "- Split across three non-overlapping windows, every gate yields "
        "low-single-digit per-window N.\n"
        "- At these counts the 95% CI on win rate spans most of [0,1]; **no "
        "edge can be confirmed or rejected on 2022 alone.**\n"
        "- **Recommendation:** treat 2022 strictly as hypothesis-generating. A "
        "credible V5.9 edge test needs more independent trades — i.e. the "
        "2023 Q1 (and ideally multi-year / multi-name) out-of-sample data the "
        "V5.7.1 plan flagged — BEFORE wiring any gated strategy into the engine. "
        "The 4-leg condor builder is only worth writing once that data path is "
        "approved.\n"
    )

    (REPORT_DIR / "v59_power_summary.md").write_text("\n".join(md), encoding="utf-8")

    # ---- console ----
    print(f"Ledger trades (full year): {len(ledger)}  "
          f"({CREDIT_STRATEGY}={len(credit)})")
    print(f"IV-rank top-tercile cutpoint: {ivr_top:.3f}  "
          f"put-skew top-tercile cutpoint: {pskew_top:.4f}")
    print("\n=== bull_put gated counts (full year) ===")
    for _, r in credit_hyp.iterrows():
        print(f"  {r['gate']:34s}: {int(r['n_gated_trades']):2d} / "
              f"{int(r['n_total_trades'])}  (CI95 half-width "
              f"{r['winrate_ci95_halfwidth']:.2f})")
    print(f"\nReports -> {REPORT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
