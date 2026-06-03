"""Company research report generator (read-only orchestration).

Pulls public SEC EDGAR data (filings index + XBRL fundamentals), lines it up
against the company's strongest price-move windows (reusing the V5.7
``research.price_moves`` helper) and available macro/market context, and writes
descriptive Markdown/CSV reports under ``reports/company/sec_edgar/``.

This is RESEARCH ONLY: it produces context, never a trading signal, and is
never wired into a strategy or backtest. Every fetch degrades gracefully --
if SEC / yfinance / FRED are unreachable and uncached, the reports say so
instead of failing.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import project_root
from . import company_facts as CF
from . import filing_index as FI
from . import sec_edgar as SEC
from .filing_parser import summarize_filing_text
from .lseg_placeholder import LSEG_DESIGN_NOTE

log = logging.getLogger("quantbot.company.report")

SUPPORTED_FORMS = FI.SUPPORTED_FORMS


def report_dir(root: str | Path | None = None) -> Path:
    base = Path(root) if root else project_root()
    return base / "reports" / "company" / "sec_edgar"


# --------------------------------------------------------------------------- #
# small md/csv helpers (kept local; mirrors the V5.x script style)
# --------------------------------------------------------------------------- #
def _fmt(v, float_fmt: str = "{:.4f}") -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "True" if v else "False"
    if isinstance(v, (float, np.floating)):
        f = float(v)
        return "nan" if math.isnan(f) else float_fmt.format(f)
    if isinstance(v, pd.Timestamp):
        return v.date().isoformat()
    return str(v)


def df_to_md(df: pd.DataFrame, float_fmt: str = "{:.4f}", max_rows: int = 60) -> str:
    if df is None or df.empty:
        return "_(none)_"
    if len(df) > max_rows:
        df = df.head(max_rows)
    headers = [str(c) for c in df.columns]
    body = [[_fmt(v, float_fmt) for v in row]
            for row in df.itertuples(index=False, name=None)]
    widths = [max(len(h), *(len(r[i]) for r in body)) for i, h in enumerate(headers)]

    def line(cells):
        return "| " + " | ".join(c.ljust(w) for c, w in zip(cells, widths)) + " |"

    sep = "| " + " | ".join("-" * w for w in widths) + " |"
    return "\n".join([line(headers), sep] + [line(r) for r in body])


def _write_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


# --------------------------------------------------------------------------- #
# optional context loaders (best-effort, never raise)
# --------------------------------------------------------------------------- #
def _load_prices(ticker: str, start, end, *, root):
    """AAPL (or any ticker) daily close via the existing proxy loader."""
    try:
        from ..macro.market_proxies import fetch_proxy
        df = fetch_proxy(ticker, start=start, end=end, root=root)
        if df is not None and "close" in df.columns and not df.empty:
            return df["close"].dropna()
    except Exception as exc:
        log.warning("price load failed for %s: %s", ticker, type(exc).__name__)
    return None


def _strongest_move_context(close, spy_close, vix_close, windows=(21, 63), top_k=3):
    """Top up/down move windows annotated with same-window SPY return + end VIX."""
    from ..research.price_moves import strongest_moves
    rows = []
    for w in windows:
        for direction in ("up", "down"):
            for m in strongest_moves(close, window=w, top_k=top_k, direction=direction):
                rec = {
                    "window_days": m.n_days,
                    "direction": m.direction,
                    "start_date": m.start_date.date().isoformat(),
                    "end_date": m.end_date.date().isoformat(),
                    "return_pct": m.return_pct,
                    "spy_return_pct": _window_return(spy_close, m.start_date, m.end_date),
                    "vix_at_end": _value_at(vix_close, m.end_date),
                }
                rows.append(rec)
    return pd.DataFrame(rows)


def _window_return(close, start_dt, end_dt):
    if close is None or close.empty:
        return float("nan")
    try:
        s = close.loc[:start_dt].iloc[-1]
        e = close.loc[:end_dt].iloc[-1]
        return float((e / s - 1.0) * 100.0)
    except Exception:
        return float("nan")


def _value_at(series, dt):
    if series is None or series.empty:
        return float("nan")
    try:
        return float(series.loc[:dt].iloc[-1])
    except Exception:
        return float("nan")


# --------------------------------------------------------------------------- #
# main orchestrator
# --------------------------------------------------------------------------- #
def build_company_research(
    ticker: str = "AAPL", *,
    start: str = "2019-01-01",
    end: str = "2024-12-31",
    forms: tuple[str, ...] = SUPPORTED_FORMS,
    max_filings_to_parse: int = 3,
    use_cache: bool = True,
    refresh: bool = False,
    root: str | Path | None = None,
    out_dir: str | Path | None = None,
    **http_kwargs,
) -> dict:
    """Build the full read-only company research bundle for ``ticker``.

    Returns a summary dict (counts + paths + availability flags). Always writes
    at least the data-availability report, even fully offline.
    """
    ticker = ticker.upper().strip()
    rdir = Path(out_dir) if out_dir else report_dir(root)
    rdir.mkdir(parents=True, exist_ok=True)

    # ---- 1. resolve + submissions + filing index ----
    cik = SEC.ticker_to_cik(ticker, use_cache=use_cache, refresh=refresh,
                            root=root, **http_kwargs)
    submissions = SEC.fetch_submissions(ticker, use_cache=use_cache,
                                        refresh=refresh, root=root, **http_kwargs)
    full_index = FI.build_filing_index(submissions)
    index = FI.filter_filings(full_index, forms=forms, start=start, end=end)

    # ---- 2. company facts ----
    facts_json = SEC.fetch_company_facts(ticker, use_cache=use_cache,
                                        refresh=refresh, root=root, **http_kwargs)
    facts_obs = CF.extract_company_facts(facts_json)
    facts_avail = CF.company_facts_availability(facts_json)
    facts_latest = CF.latest_annual_facts(facts_obs)

    # ---- 3. price-move + macro/market context ----
    close = _load_prices(ticker, start, end, root=root)
    spy_close = _load_prices("SPY", start, end, root=root)
    vix_close = _load_prices("^VIX", start, end, root=root)
    moves = (_strongest_move_context(close, spy_close, vix_close)
             if close is not None and not close.empty else pd.DataFrame())

    # filings lined up against each move window (descriptive only)
    move_filings = []
    if not moves.empty and not index.empty:
        for _, mv in moves.iterrows():
            near = FI.filings_near(index, mv["end_date"], window_days=45)
            for _, fl in near.iterrows():
                move_filings.append({
                    "move_window_days": mv["window_days"],
                    "move_direction": mv["direction"],
                    "move_end_date": mv["end_date"],
                    "move_return_pct": mv["return_pct"],
                    "form": fl["form"],
                    "filing_date": fl["filing_date"].date().isoformat()
                    if pd.notna(fl["filing_date"]) else "",
                    "days_from_move_end": fl["days_from_target"],
                    "primary_doc_description": fl["primary_doc_description"],
                })
    move_filings_df = pd.DataFrame(move_filings)

    # ---- 4. best-effort text/section parse of a few recent filings ----
    parsed_rows = []
    if not index.empty and cik:
        for _, fl in index.head(max_filings_to_parse).iterrows():
            doc = SEC.fetch_filing_document(
                cik, fl["accession_number"], fl["primary_document"],
                use_cache=use_cache, refresh=refresh, root=root, **http_kwargs)
            if not doc:
                continue
            from .filing_parser import html_to_text
            summ = summarize_filing_text(html_to_text(doc), fl["form"])
            parsed_rows.append({
                "form": fl["form"],
                "filing_date": fl["filing_date"].date().isoformat()
                if pd.notna(fl["filing_date"]) else "",
                "n_words": summ["n_words"],
                "detected_sections": ", ".join(summ["detected_sections"]),
            })
    parsed_df = pd.DataFrame(parsed_rows)

    # ============================ write reports ============================ #
    online = submissions is not None
    paths = _write_reports(
        ticker=ticker, cik=cik, start=start, end=end, rdir=rdir,
        full_index=full_index, index=index, facts_avail=facts_avail,
        facts_latest=facts_latest, facts_obs=facts_obs, moves=moves,
        move_filings_df=move_filings_df, parsed_df=parsed_df,
        online=online, prices_ok=close is not None,
    )

    return {
        "ticker": ticker,
        "cik": cik or "",
        "online_submissions": online,
        "n_filings_total": int(len(full_index)),
        "n_filings_in_scope": int(len(index)),
        "n_facts_fields_available": int(facts_avail["available"].sum())
        if not facts_avail.empty else 0,
        "n_facts_fields_total": int(len(facts_avail)),
        "prices_available": close is not None and not (close is None or close.empty),
        "n_move_windows": int(len(moves)),
        "n_filings_parsed": int(len(parsed_df)),
        "reports": {k: str(v) for k, v in paths.items()},
    }


def _write_reports(*, ticker, cik, start, end, rdir, full_index, index,
                   facts_avail, facts_latest, facts_obs, moves,
                   move_filings_df, parsed_df, online, prices_ok) -> dict:
    paths: dict[str, Path] = {}

    # --- filing index CSV ---
    p = rdir / f"{ticker}_filing_index.csv"
    _write_csv(index, p)
    paths["filing_index_csv"] = p

    # --- company facts summary CSV ---
    p = rdir / f"{ticker}_company_facts_summary.csv"
    _write_csv(facts_latest if not facts_latest.empty else facts_avail, p)
    paths["company_facts_summary_csv"] = p

    # --- data availability report ---
    md = [f"# {ticker} — Company Data Availability (SEC EDGAR, read-only)\n"]
    ua_note = ("custom QUANTBOT_SEC_USER_AGENT set" if SEC.has_custom_user_agent()
               else "DEFAULT placeholder User-Agent (set QUANTBOT_SEC_USER_AGENT "
                    "to your 'Name email' for real fetching)")
    md.append(
        f"- Ticker: **{ticker}**  CIK: **{cik or 'unresolved'}**\n"
        f"- Requested range: {start} → {end}\n"
        f"- SEC submissions available this run (live or cached): **{online}** "
        f"(if False, nothing was reachable and no cache existed).\n"
        f"- SEC User-Agent: {ua_note}.\n"
        f"- Prices (yfinance/cache) available: **{prices_ok}**.\n"
        f"- Filings total (recent block): **{len(full_index)}**; "
        f"in supported forms {SUPPORTED_FORMS} within range: **{len(index)}**.\n"
    )
    md.append("\n## Company facts availability (XBRL us-gaap)\n")
    md.append(df_to_md(facts_avail))
    md.append("\n_Fields map to ordered candidate tags; we use the first present "
              "and never guess a missing one._\n")
    md.append("\n## Filing counts by form (in scope)\n")
    if not index.empty:
        by_form = (index.groupby("form").size().rename("n_filings")
                   .reset_index().sort_values("n_filings", ascending=False))
        md.append(df_to_md(by_form))
    else:
        md.append("_(no filings in scope — offline with no cache, or none filed)_\n")
    md.append("\n## Limitations\n")
    md.append(
        "- Only the submissions `recent` block is parsed (older shards are a "
        "future extension).\n"
        "- XBRL tags vary by filer/era; unavailable fields are reported, not "
        "inferred.\n"
        "- Section extraction is best-effort (heading regex), not a legal parse.\n"
        f"- LSEG/Datastream not implemented. {LSEG_DESIGN_NOTE}\n"
    )
    p = rdir / "company_data_availability.md"
    _write_text("\n".join(md), p)
    paths["data_availability_md"] = p

    # --- recent filings summary ---
    md = [f"# {ticker} — Recent Filings Summary ({start} → {end})\n"]
    md.append("Read-only index of 10-K / 10-Q / 8-K filings. Not a signal.\n")
    cols = ["form", "filing_date", "report_date", "primary_doc_description",
            "items", "document_url"]
    show = index[cols].copy() if not index.empty else index
    md.append(df_to_md(show, max_rows=80))
    if not parsed_df.empty:
        md.append("\n## Parsed text / detected sections (most recent filings)\n")
        md.append(df_to_md(parsed_df))
    else:
        md.append("\n## Parsed text / detected sections\n")
        md.append("_(no filing documents fetched this run — offline/uncached)_\n")
    p = rdir / f"{ticker}_recent_filings_summary.md"
    _write_text("\n".join(md), p)
    paths["recent_filings_summary_md"] = p

    # --- macro/company context ---
    md = [f"# {ticker} — Macro / Market / Filing Context\n"]
    md.append(
        "Lines up the company's strongest 21d/63d price moves with same-window "
        "SPY return + VIX, and with filings dated near each move. Purely "
        "descriptive context for research; **not** connected to any strategy.\n"
    )
    md.append("\n## Strongest price-move windows\n")
    md.append(df_to_md(moves))
    md.append("\n## Filings near strongest-move windows (±45 days)\n")
    md.append(df_to_md(move_filings_df, max_rows=80))
    if not facts_latest.empty:
        md.append("\n## Latest annual fundamentals (context)\n")
        md.append(df_to_md(facts_latest))
    md.append("\n## How this will combine with options/macro research later\n")
    md.append(
        "- The same filings/fundamentals context can sit beside the V5.7 macro "
        "regime + V5.8 options-IV features as *explanatory* annotation when "
        "reviewing a name before any options study.\n"
        "- It stays annotation-only: no filing or fundamental will feed a "
        "strategy or backtest decision in this project version.\n"
    )
    p = rdir / f"{ticker}_macro_company_context.md"
    _write_text("\n".join(md), p)
    paths["macro_company_context_md"] = p

    return paths
