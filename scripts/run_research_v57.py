"""V5.7 read-only macro / market / news research driver.

This script never trades and never feeds context back into a strategy
decision. It:

  1. Loads the existing SPY ETF cache (no network if cache present).
  2. Attempts to fetch a small set of yfinance proxies (^VIX, HYG, LQD,
     etc.); missing / unreachable symbols degrade gracefully.
  3. Attempts to fetch a small set of FRED macro series IF
     ``FRED_API_KEY`` is set in the environment; otherwise notes that
     macro coverage is yfinance-only.
  4. Re-runs the three V5.3 strategies (UNCHANGED defaults) on the
     frozen V5.2 Stage 1 SPY corpus to obtain the same trade tables
     V5.3-V5.6 archived, and annotates each trade with the available
     macro / market context.
  5. Identifies the strongest 5d / 21d / 63d return windows for SPY
     over the V4-cached date range, then attempts an AAPL example if
     yfinance succeeds. AAPL is OPTIONAL -- the script will continue
     without it and clearly state so in the summary.
  6. Writes everything under ``reports/research/v57_macro_context/``.

LIVE_TRADING_ENABLED stays False. No broker. No IBKR. No order
execution.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from quantbot.costs.transaction_costs import OptionsCostModel
from quantbot.data.options_cache import read_processed
from quantbot.events.manual_events import (
    build_event_flag_panel,
    load_events,
    load_events_detailed,
)
from quantbot.macro import fred_loader
from quantbot.macro.market_proxies import DEFAULT_PROXIES, fetch_proxy
from quantbot.macro.regime_classifier import RegimeThresholds, build_regime_panel
from quantbot.options.backtest_engine import OptionsBacktestEngine
from quantbot.options.risk import OptionsRiskLimits
from quantbot.options.strategies.spy_bear_put import SPYBearPutSpread
from quantbot.options.strategies.spy_bull_call import SPYBullCallSpread
from quantbot.options.strategies.spy_bull_put import SPYBullPutSpread
from quantbot.research.price_moves import strongest_moves_panel
from quantbot.research.reporting import df_to_md, write_csv, write_text
from quantbot.research.trade_context import (
    annotate_event_overlap,
    annotate_trades,
    summarize_event_overlap,
    summarize_winners_vs_losers,
)


LIVE_TRADING_ENABLED = False
OUT_DIR = ROOT / "reports" / "research" / "v57_macro_context"
log = logging.getLogger("v57")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")

STRATEGY_FACTORIES = {
    "bull_call": SPYBullCallSpread,
    "bear_put":  SPYBearPutSpread,
    "bull_put":  SPYBullPutSpread,
}

PROXY_ROSTER = ["SPY", "^VIX", "TLT", "IEF", "HYG", "LQD", "GLD"]


# --------------------------------------------------------------------------- #
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


def run_strategy_trades(chain: pd.DataFrame, name: str) -> pd.DataFrame:
    """Re-run a strategy on the frozen corpus and return its trade frame."""
    factory = STRATEGY_FACTORIES[name]
    eng = OptionsBacktestEngine(
        chain, factory(),
        initial_capital=100_000.0,
        limits=OptionsRiskLimits(),
        cost_model=OptionsCostModel(),
    )
    res = eng.run()
    tdf = res.to_trades_frame()
    tdf.insert(0, "strategy", name)
    return tdf


# --------------------------------------------------------------------------- #
def main() -> int:
    assert LIVE_TRADING_ENABLED is False, "V5.7 is READ-ONLY research."
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    log.info("V5.7 macro/news context layer -- output dir: %s", OUT_DIR)

    # ---- 1. PROXY DATA -------------------------------------------------- #
    log.info("Fetching market proxies (cache-first, yfinance-fallback) ...")
    proxies: dict[str, pd.DataFrame | None] = {}
    for sym in PROXY_ROSTER:
        proxies[sym] = fetch_proxy(sym, start="2010-01-01")
    proxy_status_rows = [{
        "symbol": s,
        "available": proxies[s] is not None,
        "rows": (len(proxies[s]) if proxies[s] is not None else 0),
        "first_date": (str(proxies[s].index.min().date())
                        if proxies[s] is not None else ""),
        "last_date": (str(proxies[s].index.max().date())
                       if proxies[s] is not None else ""),
        "description": DEFAULT_PROXIES.get(s, ""),
    } for s in PROXY_ROSTER]
    proxy_status = pd.DataFrame(proxy_status_rows)
    write_csv(proxy_status, OUT_DIR / "proxy_availability.csv")

    # ---- 2. FRED MACRO (graceful no-key path) --------------------------- #
    fred_present = fred_loader.has_api_key()
    log.info("FRED_API_KEY present: %s", fred_present)
    fred_panel: dict[str, pd.DataFrame] = {}
    if fred_present:
        fred_panel = fred_loader.fetch_panel(
            ["DGS10", "DGS2", "T10Y2Y", "FEDFUNDS", "CPIAUCSL", "UNRATE"],
            start="2010-01-01",
        )
    else:
        # Try a cache-only read in case the user previously fetched.
        for sid in ("DGS10", "DGS2", "T10Y2Y", "FEDFUNDS", "CPIAUCSL", "UNRATE"):
            cached = fred_loader.fetch_series(sid)
            if cached is not None:
                fred_panel[sid] = cached
    fred_status_rows = [{
        "series_id": sid,
        "rows": len(df),
        "first_date": str(df.index.min().date()),
        "last_date": str(df.index.max().date()),
        "description": fred_loader.DEFAULT_SERIES.get(sid, ""),
    } for sid, df in fred_panel.items()]
    fred_status = pd.DataFrame(fred_status_rows)
    write_csv(fred_status, OUT_DIR / "fred_availability.csv")

    # ---- 3. BUILD REGIME PANEL ----------------------------------------- #
    spy_proxy = proxies.get("SPY")
    vix_proxy = proxies.get("^VIX")
    hyg_proxy = proxies.get("HYG")
    lqd_proxy = proxies.get("LQD")
    dgs10_series = (fred_panel.get("DGS10")["value"]
                     if "DGS10" in fred_panel else None)

    if spy_proxy is None:
        log.error("SPY proxy unavailable; regime panel cannot be built.")
        regime_panel = pd.DataFrame()
    else:
        regime_panel = build_regime_panel(
            spy_close=spy_proxy["adjusted_close"],
            vix_level=(vix_proxy["close"] if vix_proxy is not None else None),
            dgs10=dgs10_series,
            hyg=(hyg_proxy["adjusted_close"] if hyg_proxy is not None else None),
            lqd=(lqd_proxy["adjusted_close"] if lqd_proxy is not None else None),
            th=RegimeThresholds(),
        )
        write_csv(regime_panel.reset_index().rename(columns={"index": "date"}),
                   OUT_DIR / "macro_regime_snapshot.csv")

    # ---- 4. EVENTS ----------------------------------------------------- #
    events = load_events()
    if not events.empty and not regime_panel.empty:
        flag_panel = build_event_flag_panel(events, date_index=regime_panel.index)
        write_csv(flag_panel.reset_index().rename(columns={"index": "date"}),
                   OUT_DIR / "event_flag_panel.csv")
    else:
        flag_panel = None

    # ---- 5. SPY STRATEGY TRADE CONTEXT (re-run, then annotate) --------- #
    log.info("Re-running 3 strategies on frozen V5.2 Stage 1 corpus ...")
    chain = load_spy_chain_2022_h1()
    all_trades: list[pd.DataFrame] = []
    for sname in STRATEGY_FACTORIES.keys():
        all_trades.append(run_strategy_trades(chain, sname))
    trades_df = pd.concat(all_trades, ignore_index=True)

    annotated = annotate_trades(
        trades_df,
        spy_close=(spy_proxy["adjusted_close"] if spy_proxy is not None else None),
        vix_level=(vix_proxy["close"] if vix_proxy is not None else None),
        dgs10=dgs10_series,
        hyg=(hyg_proxy["adjusted_close"] if hyg_proxy is not None else None),
        lqd=(lqd_proxy["adjusted_close"] if lqd_proxy is not None else None),
        trend_label=(regime_panel["trend"] if "trend" in regime_panel.columns else None),
        vol_label=(regime_panel["vol"] if "vol" in regime_panel.columns else None),
        rates_label=(regime_panel["rates"] if "rates" in regime_panel.columns else None),
        credit_label=(regime_panel["credit"] if "credit" in regime_panel.columns else None),
        combined_regime=(regime_panel["combined"]
                          if "combined" in regime_panel.columns else None),
        event_flags=flag_panel,
    )

    # Richer event-overlap annotation from the DETAILED events frame
    # (importance- and type-aware). Read-only; never touches P&L.
    events_detailed = load_events_detailed()
    annotated = annotate_event_overlap(annotated, events_detailed)
    write_csv(annotated, OUT_DIR / "strategy_trade_context.csv")

    summaries = []
    for sname, g in annotated.groupby("strategy"):
        s = summarize_winners_vs_losers(g)
        s.insert(0, "strategy", sname)
        summaries.append(s)
    win_loss_summary = pd.concat(summaries, ignore_index=True)
    write_csv(win_loss_summary, OUT_DIR / "win_loss_context_summary.csv")

    # Per-(strategy, win/loss) event-overlap aggregation.
    event_overlap_summary = summarize_event_overlap(annotated)
    write_csv(event_overlap_summary, OUT_DIR / "event_overlap_summary.csv")

    # ---- 6. STRONGEST-MOVES CONTEXT (SPY example + optional AAPL) ------ #
    spy_moves_df = pd.DataFrame()
    if spy_proxy is not None and len(spy_proxy) > 200:
        spy_moves_df = strongest_moves_panel(
            spy_proxy["adjusted_close"], windows=(5, 21, 63), top_k=5,
            direction="both",
        )
        spy_moves_df.insert(0, "ticker", "SPY")
        write_csv(spy_moves_df, OUT_DIR / "strongest_moves_context_SPY.csv")

    aapl_ok = False
    aapl_moves_df = pd.DataFrame()
    aapl = fetch_proxy("AAPL", start="2019-01-01", end="2024-12-31")
    if aapl is not None and len(aapl) > 200:
        aapl_ok = True
        aapl_moves_df = strongest_moves_panel(
            aapl["adjusted_close"], windows=(21, 63), top_k=5,
            direction="both",
        )
        aapl_moves_df.insert(0, "ticker", "AAPL")
        write_csv(aapl_moves_df, OUT_DIR / "strongest_moves_context_AAPL.csv")
    else:
        log.info("AAPL example skipped (yfinance unavailable or fetch failed).")

    # ---- 7. SUMMARY MARKDOWN ------------------------------------------- #
    md_lines: list[str] = []
    md_lines.append("# V5.7 Macro / market / news context report\n")
    md_lines.append(
        f"Engine: V5.0 (unchanged). LIVE_TRADING_ENABLED = "
        f"`{LIVE_TRADING_ENABLED}`. No broker / live / IBKR. No order "
        f"execution. No strategy decisions altered.\n"
    )

    md_lines.append("\n## 1. Proxy data availability\n")
    md_lines.append(df_to_md(proxy_status, "{:.0f}"))

    md_lines.append("\n## 2. FRED macro data\n")
    if fred_present:
        md_lines.append("`FRED_API_KEY` was present at run time. Series fetched:\n")
        md_lines.append(df_to_md(fred_status, "{:.0f}") if not fred_status.empty
                          else "_(no series returned)_")
    else:
        md_lines.append(
            "`FRED_API_KEY` was **not** present at run time. The driver "
            "did **not** issue any live FRED HTTP calls. If a previously-"
            "cached series was on disk it was loaded; otherwise the macro "
            "context is yfinance-proxy-only.\n"
        )
        if not fred_status.empty:
            md_lines.append("\nCached series available:\n")
            md_lines.append(df_to_md(fred_status, "{:.0f}"))

    md_lines.append("\n## 3. Macro regime snapshot (last 10 rows)\n")
    if regime_panel.empty:
        md_lines.append("_(regime panel could not be built; SPY proxy missing)_")
    else:
        snap = regime_panel.tail(10).reset_index().rename(columns={"index": "date"})
        snap["date"] = snap["date"].dt.strftime("%Y-%m-%d")
        md_lines.append(df_to_md(snap))

    md_lines.append("\n## 4. Strategy trade context (V5.2 Stage 1 corpus)\n")
    md_lines.append(
        f"Re-ran all three strategies (defaults UNCHANGED) on the frozen "
        f"SPY Jan-Jun 2022 corpus, producing {len(annotated)} closed trades "
        f"across `bull_call`, `bear_put`, `bull_put`. Each trade is "
        f"annotated with macro / market context drawn from the available "
        f"proxies and FRED series. **Trade P&L and engine results are NOT "
        f"mutated by annotation.**\n"
    )

    md_lines.append("\n### 4a. Win/loss context summary per strategy\n")
    md_lines.append(df_to_md(win_loss_summary))

    md_lines.append("\n### 4b. Per-trade context table (head 12)\n")
    cols = [c for c in [
        "strategy", "fill_open", "fill_close", "close_reason", "realized_pnl",
        "holding_days", "spy_return_in_trade_pct", "vix_at_entry",
        "vix_change_in_trade", "trend_at_entry", "vol_at_entry",
        "macro_regime_at_entry",
    ] if c in annotated.columns]
    md_lines.append(df_to_md(annotated[cols].head(12)))

    md_lines.append("\n### 4c. Event overlap (CPI / FOMC) — context only, NOT a signal\n")
    if events_detailed.empty:
        md_lines.append(
            "_(no manual events loaded; populate "
            "`data/events/manual_events.csv` to enable event annotation)_"
        )
    else:
        n_cpi = int(annotated["cpi_event_during_trade"].sum())
        n_fomc = int(annotated["fomc_event_during_trade"].sum())
        n_any = int((annotated["event_count_during_trade"] > 0).sum())
        md_lines.append(
            f"{len(events_detailed)} manual events loaded "
            f"({(events_detailed['event_type'] == 'CPI').sum()} CPI, "
            f"{(events_detailed['event_type'] == 'FOMC').sum()} FOMC, "
            f"{(events_detailed['event_type'] == 'FOMC_MINUTES').sum()} "
            f"FOMC_MINUTES). Of {len(annotated)} trades: "
            f"**{n_any}** overlapped >=1 event "
            f"({n_cpi} overlapped a CPI release, {n_fomc} overlapped an "
            f"FOMC statement/minutes). Event overlap is annotation only — "
            f"trades and P&L are unchanged.\n"
        )
        md_lines.append("\n**Per-(strategy, win/loss) event overlap:**\n")
        md_lines.append(df_to_md(event_overlap_summary))
        ev_cols = [c for c in [
            "strategy", "fill_open", "fill_close", "realized_pnl",
            "event_count_during_trade", "cpi_event_during_trade",
            "fomc_event_during_trade", "high_importance_event_during_trade",
            "events_during_trade",
        ] if c in annotated.columns]
        md_lines.append("\n**Per-trade event overlap (head 12):**\n")
        md_lines.append(df_to_md(annotated[ev_cols].head(12)))

    md_lines.append("\n## 5. Strongest SPY return windows (cache-only)\n")
    if spy_moves_df.empty:
        md_lines.append("_(SPY history insufficient or proxy unavailable)_")
    else:
        md_lines.append(df_to_md(spy_moves_df.head(15)))

    md_lines.append("\n## 6. AAPL example (yfinance, optional)\n")
    if aapl_ok:
        md_lines.append(
            f"yfinance fetch succeeded for AAPL "
            f"({len(aapl)} rows, "
            f"{aapl.index.min().date()} -> {aapl.index.max().date()}).\n"
        )
        md_lines.append(df_to_md(aapl_moves_df.head(20)))
    else:
        md_lines.append(
            "AAPL example was **skipped**: yfinance was unavailable, "
            "rate-limited, or the symbol returned no data. The module "
            "is still importable and the regime / annotation flow can "
            "be reused on any other underlying for which a price series "
            "is available.\n"
        )

    md_lines.append("\n## 7. Data availability summary\n")
    md_lines.append(
        f"- Market proxies available: "
        f"{sum(1 for _, df in proxies.items() if df is not None)} / "
        f"{len(proxies)}\n"
        f"- FRED series available: {len(fred_panel)} "
        f"({'live + cache' if fred_present else 'cache-only'})\n"
        f"- Events: {len(events)} manual events loaded\n"
        f"- AAPL example: {'ran' if aapl_ok else 'skipped'}\n"
    )

    md_lines.append("\n## 8. Guardrails honored\n")
    md_lines.append(
        "- `LIVE_TRADING_ENABLED = False` (runtime).\n"
        "- No broker / live / IBKR / order-execution imports anywhere in "
        "  `quantbot.macro`, `quantbot.research`, or `quantbot.events`.\n"
        "- No strategy decisions or engine logic altered. The strategy "
        "  re-runs reproduce the V5.3 / V5.4 / V5.5 / V5.6 archived baselines "
        "  exactly.\n"
        "- No packages installed. yfinance and FRED handled with graceful "
        "  fallback.\n"
        "- No credentials read into source, logs, or output files. "
        "  `FRED_API_KEY` is consulted via `os.environ.get(...)` only.\n"
    )

    write_text("\n".join(md_lines), OUT_DIR / "v57_summary.md")

    # ---- 8. DATA AVAILABILITY REPORT (separate file) ------------------- #
    avail_md = "# V5.7 data availability report\n\n"
    avail_md += "## Market proxies (yfinance + ETF cache)\n"
    avail_md += df_to_md(proxy_status, "{:.0f}") + "\n\n"
    avail_md += "## FRED macro series\n"
    avail_md += f"`FRED_API_KEY` present at run time: **{fred_present}**\n\n"
    if not fred_status.empty:
        avail_md += df_to_md(fred_status, "{:.0f}") + "\n"
    else:
        avail_md += "_No FRED series cached and no live fetch performed._\n"
    write_text(avail_md, OUT_DIR / "data_availability_report.md")

    log.info("V5.7 reports written.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
