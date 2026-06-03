"""Company Research multi-ticker validation — MU (Micron Technology), read-only.

Validates the SEC EDGAR / company-fundamentals research layer on a NEW ticker
outside AAPL. Two stages, both read-only and existing-sources only:

1. SEC LAYER (reuses quantbot.company.build_company_research): resolve MU->CIK,
   fetch/cache submissions + XBRL companyfacts, build the 10-K/10-Q/8-K filing
   index, parse a few recent filings, and write the base reports into
   reports/company/sec_edgar/MU/.

2. ENRICHED MOVE/MACRO CONTEXT: identify MU's strongest/weakest 21d & 63d return
   windows in 2025 and 2026-YTD (separately), annotate each with same-window SPY
   & QQQ return, VIX level+change, FRED DGS10 (level + bps change) and the
   2s10s spread (DGS10-DGS2), a simple risk-on/off regime label, and the nearest
   10-K/10-Q/8-K filing. No future data; no causality claimed.

RESEARCH ONLY. No options data, no ThetaData, no MU options, no strategy/backtest
change, no trading signal, no broker/live/IBKR, no LSEG, no package installs, no
credentials printed. LIVE_TRADING_ENABLED stays False.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import quantbot
from quantbot.company import sec_edgar as SEC
from quantbot.company import filing_index as FI
from quantbot.company import company_facts as CF
from quantbot.company.company_report import build_company_research, df_to_md
from quantbot.macro.market_proxies import fetch_proxy
from quantbot.research.price_moves import rolling_returns

TICKER = "MU"
SEC_START, SEC_END = "2019-01-01", "2026-05-23"
PRICE_START = "2024-06-01"   # lookback so 63d windows ending early-2025 are valid
SCOPES = {"2025": ("2025-01-01", "2025-12-31"),
          "2026_YTD": ("2026-01-01", "2026-05-23")}
WINDOWS = (21, 63)
TOP_K = 2
OUT_DIR = ROOT / "reports" / "company" / "sec_edgar" / TICKER
FRED_DIR = ROOT / "data" / "macro" / "fred"
EVENTS_CSV = ROOT / "data" / "events" / "manual_events.csv"


def _close(sym: str) -> pd.Series | None:
    df = fetch_proxy(sym, start=PRICE_START, end=SEC_END)
    if df is None or df.empty or "close" not in df.columns:
        return None
    return df["close"].dropna().sort_index()


def _fred(name: str) -> pd.Series | None:
    p = FRED_DIR / f"{name}.csv"
    if not p.is_file():
        return None
    s = pd.read_csv(p, parse_dates=["date"]).set_index("date")["value"]
    return pd.to_numeric(s, errors="coerce").dropna().sort_index()


def _win_ret(close: pd.Series | None, a, b) -> float:
    if close is None or close.empty:
        return float("nan")
    try:
        return float((close.loc[:b].iloc[-1] / close.loc[:a].iloc[-1] - 1.0) * 100.0)
    except Exception:
        return float("nan")


def _asof(series: pd.Series | None, dt) -> float:
    if series is None or series.empty:
        return float("nan")
    try:
        return float(series.loc[:dt].iloc[-1])
    except Exception:
        return float("nan")


def _regime(spy_ret: float, vix_chg: float) -> str:
    if np.isnan(spy_ret) or np.isnan(vix_chg):
        return "n/a"
    if spy_ret > 0 and vix_chg < 0:
        return "risk-on (SPY up, VIX down)"
    if spy_ret < 0 and vix_chg > 0:
        return "risk-off (SPY down, VIX up)"
    return "mixed"


def _events_cover_2025() -> bool:
    if not EVENTS_CSV.is_file():
        return False
    ev = pd.read_csv(EVENTS_CSV, parse_dates=["date"])
    return bool((ev["date"] >= "2025-01-01").any())


def main() -> int:
    assert quantbot.LIVE_TRADING_ENABLED is False, "Company research is RESEARCH only."
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # ---------------- Stage 1: SEC layer (reuse orchestrator) ---------------- #
    print(f"[1] SEC company research for {TICKER} ({SEC_START}->{SEC_END}) ...")
    # parse enough recent filings (12) that at least one 10-K is included, so
    # the parser's business / risk-factor / market-risk detection is exercised
    # across form types (the 3 most-recent are 8-Ks + a 10-Q).
    summary = build_company_research(TICKER, start=SEC_START, end=SEC_END,
                                     out_dir=OUT_DIR, max_filings_to_parse=12)
    # Normalize availability filename to the MU_-prefixed convention.
    generic_avail = OUT_DIR / "company_data_availability.md"
    mu_avail = OUT_DIR / f"{TICKER}_company_data_availability.md"
    if generic_avail.is_file():
        mu_avail.write_text(generic_avail.read_text(encoding="utf-8"), encoding="utf-8")
        generic_avail.unlink()
    print(f"    CIK={summary['cik']} online={summary['online_submissions']} "
          f"filings_in_scope={summary['n_filings_in_scope']} "
          f"facts_fields={summary['n_facts_fields_available']}/{summary['n_facts_fields_total']} "
          f"parsed={summary['n_filings_parsed']}")

    # filing index (rebuild from now-cached submissions) for move/event linking
    submissions = SEC.fetch_submissions(TICKER)
    index = FI.filter_filings(FI.build_filing_index(submissions),
                              forms=FI.SUPPORTED_FORMS, start=SEC_START, end=SEC_END)

    # companyfacts -> fundamentals trend (Q4)
    facts_json = SEC.fetch_company_facts(TICKER)
    facts_obs = CF.extract_company_facts(facts_json)
    facts_avail = CF.company_facts_availability(facts_json)

    # ---------------- Stage 2: enriched price-move + macro context ----------- #
    print("[2] Enriched 2025 / 2026-YTD move + macro context ...")
    mu = _close(TICKER)
    spy, qqq, vix = _close("SPY"), _close("QQQ"), _close("^VIX")
    dgs10, dgs2 = _fred("DGS10"), _fred("DGS2")
    events_2025 = _events_cover_2025()
    event_note = ("see manual_events.csv" if events_2025
                  else "n/a (manual_events.csv ends 2022-06)")

    move_rows, event_rows = [], []
    if mu is not None and not mu.empty:
        for scope, (lo, hi) in SCOPES.items():
            lo_ts, hi_ts = pd.Timestamp(lo), pd.Timestamp(hi)
            for w in WINDOWS:
                rets = rolling_returns(mu, w).dropna()
                rets = rets[(rets.index >= lo_ts) & (rets.index <= hi_ts)]
                if rets.empty:
                    continue
                picks = pd.concat([rets.nlargest(TOP_K), rets.nsmallest(TOP_K)])
                picks = picks[~picks.index.duplicated()]
                for end_dt, ret in picks.items():
                    loc = mu.index.get_loc(end_dt)
                    if loc - w < 0:
                        continue
                    start_dt = mu.index[loc - w]
                    spy_r = _win_ret(spy, start_dt, end_dt)
                    vix_e, vix_s = _asof(vix, end_dt), _asof(vix, start_dt)
                    vix_chg = (vix_e - vix_s) if not (np.isnan(vix_e) or np.isnan(vix_s)) else float("nan")
                    d10_e, d10_s = _asof(dgs10, end_dt), _asof(dgs10, start_dt)
                    d2_e = _asof(dgs2, end_dt)
                    move_rows.append({
                        "year_scope": scope,
                        "window_days": w,
                        "direction": "up" if ret > 0 else "down",
                        "start_date": start_dt.date().isoformat(),
                        "end_date": end_dt.date().isoformat(),
                        "mu_return_pct": round(float(ret) * 100, 2),
                        "spy_return_pct": round(spy_r, 2),
                        "qqq_return_pct": round(_win_ret(qqq, start_dt, end_dt), 2),
                        "vix_at_end": round(vix_e, 2),
                        "vix_change": round(vix_chg, 2),
                        "dgs10_at_end_pct": round(d10_e, 2),
                        "dgs10_change_bps": round((d10_e - d10_s) * 100, 1)
                        if not (np.isnan(d10_e) or np.isnan(d10_s)) else float("nan"),
                        "spread_2s10s_at_end": round(d10_e - d2_e, 2)
                        if not (np.isnan(d10_e) or np.isnan(d2_e)) else float("nan"),
                        "event_proximity": event_note,
                        "regime_label": _regime(spy_r, vix_chg),
                    })
                    # nearest filings (±45d of move end)
                    near = FI.filings_near(index, end_dt, window_days=45)
                    for _, fl in near.iterrows():
                        event_rows.append({
                            "year_scope": scope,
                            "window_days": w,
                            "direction": "up" if ret > 0 else "down",
                            "move_end_date": end_dt.date().isoformat(),
                            "mu_return_pct": round(float(ret) * 100, 2),
                            "form": fl["form"],
                            "filing_date": fl["filing_date"].date().isoformat()
                            if pd.notna(fl["filing_date"]) else "",
                            "days_from_move_end": int(fl["days_from_target"]),
                            "items": fl["items"],
                            "primary_doc_description": fl["primary_doc_description"],
                        })

    moves_df = pd.DataFrame(move_rows).sort_values(
        ["year_scope", "window_days", "direction", "mu_return_pct"],
        ascending=[True, True, True, False]).reset_index(drop=True) if move_rows else pd.DataFrame()
    events_df = pd.DataFrame(event_rows) if event_rows else pd.DataFrame()
    moves_df.to_csv(OUT_DIR / f"{TICKER}_strongest_moves_context.csv", index=False)
    events_df.to_csv(OUT_DIR / f"{TICKER}_filing_event_context.csv", index=False)

    # ---- fundamentals trend (annual values per field, keyed by PERIOD END) ---- #
    # NOTE: companyfacts `fy` is the FILING's fiscal year and each 10-K carries
    # 2-3 years of comparatives, so we must key off the actual period END date,
    # not `fy`. Flow items (revenue / NI / OCF) use the ~365d annual period;
    # the set of those annual period-end dates ARE the fiscal-year-ends, at which
    # we then read the point-in-time balance-sheet items. Restatements: take the
    # value from the latest-filed observation (max fy) for each (field, end).
    FLOW_FIELDS = {"revenue", "net_income", "operating_cash_flow"}
    fy_tbl = pd.DataFrame()
    if not facts_obs.empty:
        obs = facts_obs.copy()
        obs["period_days"] = (obs["end"] - obs["start"]).dt.days
        obs["fy_num"] = pd.to_numeric(obs["fy"], errors="coerce")
        flow = obs[obs["field"].isin(FLOW_FIELDS) & obs["period_days"].between(350, 380)]
        fye_dates = sorted(pd.Series(flow["end"].dropna().unique()))
        rows = []
        for fye in fye_dates:
            rec = {"fiscal_year_end": pd.Timestamp(fye).date().isoformat()}
            for field in CF.TARGET_CONCEPTS:
                if field in FLOW_FIELDS:
                    cand = obs[(obs["field"] == field) & (obs["end"] == fye)
                               & obs["period_days"].between(350, 380)]
                else:  # instant balance-sheet item at the fiscal-year-end date
                    cand = obs[(obs["field"] == field) & (obs["end"] == fye)]
                if cand.empty:
                    rec[field] = float("nan")
                else:
                    rec[field] = float(cand.sort_values("fy_num")["val"].iloc[-1]) / 1e9
            rows.append(rec)
        if rows:
            fy_tbl = (pd.DataFrame(rows)
                      [["fiscal_year_end"] + list(CF.TARGET_CONCEPTS)]
                      .tail(7).round(3).reset_index(drop=True))

    # ---------------- enriched macro/company context report ------------------ #
    md = [f"# {TICKER} (Micron Technology) — Macro / Market / Filing Context\n"]
    md.append(
        "Read-only multi-ticker validation of the company research layer on a "
        "NEW ticker outside AAPL. Lines up MU's strongest/weakest **2025** and "
        "**2026-YTD** price-move windows with same-window SPY & QQQ returns, VIX "
        "level+change, FRED 10y yield (DGS10) + 2s10s spread, a simple regime "
        "label, and the nearest 10-K/10-Q/8-K filing. **Descriptive context "
        "only — no trading signal, no causality claim, no future data, no "
        f"options/ThetaData. LIVE_TRADING_ENABLED = {quantbot.LIVE_TRADING_ENABLED}.**\n")
    md.append(
        f"\n- CIK: **{summary['cik']}**  ({summary.get('ticker','')})  "
        f"SEC online this run: **{summary['online_submissions']}**\n"
        f"- Filings in scope (10-K/10-Q/8-K, {SEC_START}→{SEC_END}): "
        f"**{summary['n_filings_in_scope']}**; recent filings parsed: "
        f"**{summary['n_filings_parsed']}**\n"
        f"- companyfacts fields available: "
        f"**{summary['n_facts_fields_available']}/{summary['n_facts_fields_total']}**\n"
        f"- MU price rows (yfinance/cache): **{0 if mu is None else len(mu)}** "
        f"({'n/a' if mu is None else mu.index.min().date()} → "
        f"{'n/a' if mu is None else mu.index.max().date()})\n"
        f"- Macro/event note: {event_note}\n")

    md.append("\n## 1–2. Strongest / weakest MU move windows + macro backdrop\n")
    md.append(df_to_md(moves_df, max_rows=80))
    md.append(
        "\n`mu_return_pct` is over the window; SPY/QQQ are same-window returns; "
        "`vix_change`/`dgs10_change_bps` are end-minus-start; `spread_2s10s_at_end` "
        "= DGS10−DGS2 (pp). `regime_label` is a simple SPY-direction × VIX-direction "
        "heuristic, not a model. CPI/FOMC proximity is unavailable for 2025/2026 "
        "(the bundled manual_events.csv ends 2022-06).\n")

    md.append("\n## 3. Recent-filing sections detected\n")
    md.append("See `MU_recent_filings_summary.md` (business / risk factors / MD&A / "
              "liquidity / market-risk heading detection on the most recent filings) "
              "and `MU_filing_index.csv` for the full 10-K/10-Q/8-K index.\n")

    md.append("\n## 4. Fundamentals over available SEC history (annual 10-K FY, $B)\n")
    if not fy_tbl.empty:
        md.append(df_to_md(fy_tbl, "{:.3f}"))
        md.append("\n_Values in $ billions, keyed by the period END (fiscal-year-end) "
                  "date — not the filing `fy` (each 10-K carries multi-year "
                  "comparatives). Flow items use the ~365d annual period; balance "
                  "items are the point-in-time value at the fiscal-year-end. MU's "
                  "fiscal year ends in late August/early September; NaN = tag not "
                  "reported for that year._\n")
    else:
        md.append("_(no annual 10-K FY observations extracted)_\n")
    md.append("\n### companyfacts field availability\n")
    md.append(df_to_md(facts_avail))

    md.append("\n## 5. Filing/event proximity to move windows\n")
    md.append(df_to_md(events_df, max_rows=80))
    md.append("\nProximity is descriptive only: a filing near a move window is NOT "
              "asserted to have caused it. MU's quarterly earnings (8-K + 10-Q) are "
              "the most likely scheduled catalysts.\n")

    md.append("\n## 6. Robustness note\n")
    md.append(
        "- The SEC layer resolved MU→CIK, fetched submissions + companyfacts, built "
        "the filing index, and parsed recent filings with no AAPL-specific "
        "assumptions — it generalizes to a new ticker.\n"
        "- XBRL tags vary by filer; unavailable fundamentals are reported, not "
        "guessed (see availability table).\n"
        "- Single new ticker; this validates plumbing, not any edge. No options "
        "data was fetched and none is implied.\n")

    (OUT_DIR / f"{TICKER}_macro_company_context.md").write_text("\n".join(md), encoding="utf-8")

    # ---------------- console summary ---------------- #
    print(f"\n=== {TICKER} availability ===")
    print(facts_avail[["field", "matched_tag", "available", "n_observations"]].to_string(index=False))
    print(f"\n=== {TICKER} move windows ({len(moves_df)}) ===")
    if not moves_df.empty:
        print(moves_df[["year_scope", "window_days", "direction", "end_date",
                        "mu_return_pct", "spy_return_pct", "qqq_return_pct",
                        "vix_at_end", "regime_label"]].to_string(index=False))
    if not fy_tbl.empty:
        print(f"\n=== {TICKER} fundamentals trend ($B, annual FY) ===")
        print(fy_tbl.to_string())
    print(f"\nReports -> {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
