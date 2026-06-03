# Sector Thesis Tracker — Future Roadmap (V6.6 / V6.7 / V6.8 / V6.9)

*Status: **planning note only**. Nothing in this document is implemented.
None of these phases starts until each is independently approved. **No live
trading. No broker. No IBKR orders. `LIVE_TRADING_ENABLED` stays `False`
throughout.***

---

## V6.6 — Daily refresh, change log, and news / event context layer

**Goal.** Add a scheduled or manually-triggered refresh of approved local /
public data sources for the sector trackers, with timestamped change logs and
read-only news/event annotations attached to each catalyst.

### Refresh

- **Scheduled or manual trigger** (initially: a `scripts/refresh_sector_trackers.py`
  driver invoked by the operator; future: a cron / Task Scheduler entry).
- **Only existing, approved data sources** — SEC EDGAR via `quantbot.company`,
  FRED via `quantbot.macro.fred_loader`, the local VIX proxy. **No new
  ThetaData fetches; no live news scraping; no automated browsing.**
- The driver re-runs the V6.2 / V6.3 / V6.4 sector drivers under their
  existing freshness gates and writes the same CSV / MD artefacts (no schema
  change to the V6.1 framework).

### Change log

- For every catalyst, record `(timestamp, catalyst_id, prior_value,
  new_value, prior_status, new_status, source_file, source_date)` in a
  rolling CSV at `data/research/sector_tracker/change_log.csv`.
- For every emergency exit, log `(timestamp, exit_id, prior_status,
  new_status)`.
- The change log is APPEND-ONLY — no edits or deletions of past rows; any
  correction is a new annotated row.

### Dashboard drill-down (V6.5.1 follow-on)

- A catalyst-detail page in the V6.5 dashboard showing:
  - prior value vs new value
  - timestamp of last change
  - source file and source date
  - related SEC filing / FRED release / company event identifiers
  - affected companies (for aggregate catalysts)
  - effect on the sector score (delta in raw / normalized score)

### News / event annotations

- A read-only news / event annotation table at
  `data/research/sector_tracker/event_annotations.csv` where the operator
  can pin a short note (timestamp, source URL, free text) to a specific
  catalyst or emergency exit.
- **The annotations are CONTEXT ONLY, never an autonomous trading signal.**
- No automated news ingestion in V6.6 — annotations are operator-curated.

### Safety rules

- No live trading. No broker. No IBKR orders. No order execution.
- `LIVE_TRADING_ENABLED` stays `False`.
- No package installs without explicit approval.
- No web scraping; no automated browsing; no LLM-generated facts pinned to
  catalysts.
- News / event entries must carry an explicit operator-curated source field;
  if the source is missing, the entry is not rendered as a signal driver.

### Out of scope for V6.6

- V6.7 company-level signal ledger.
- V6.8 sector aggregation from company signals.
- V6.9 sector-level historical backtest.
- Any live trading / paper-trading / IBKR order placement.

---

The V6.1 framework currently scores ONE sector at a time from a flat catalyst
list. The phases below describe how the framework would be extended into a
multi-ticker, dated, and (later) backtested system — but only as a roadmap.
The V6.1 schema / scoring / builder / report_writer remain frozen for this
note.

---

## V6.7 — Company-level SEC/fundamental signal ledger

**Goal.** Expand the sector thesis tracker into a *company-level* signal system
across many tickers, using **SEC EDGAR / companyfacts** and the existing local
research utilities (`quantbot.company`, `quantbot.macro`, `quantbot.options.features`,
`quantbot.research`). The output is a **dated signal ledger** showing which
company received which signal on which date.

### Initial universe (initial idea — not final)

**Semiconductor:**
`NVDA, AMD, TSM, ASML, AVGO, MU, AMAT, LRCX, KLAC, ARM, MRVL`

**AI / cloud / software:**
`MSFT, GOOGL, AMZN, META, ORCL, PLTR, CRM, SNOW, NOW, ADBE`

**Energy / power infrastructure:**
`GEV, ETN, VRT, PWR, CEG, NEE, SO, XOM, CVX, COP`, LNG-related names, SMR-related
names if available.

### Ledger schema (per `(date, ticker)` row)

| field | meaning |
|---|---|
| `date` | as-of date for the signal (ISO YYYY-MM-DD) |
| `ticker` | company ticker symbol |
| `sector` | one of `AI` / `SEMICONDUCTOR` / `ENERGY` |
| `subsector` | optional finer bucket |
| `fundamental_score` | derived from companyfacts (revenue / NI / OCF / debt etc.) |
| `macro_score` | derived from FRED + VIX regime |
| `options_risk_score` | from V5.8 options features **if and only if** that ticker actually has options data fetched locally |
| `price_trend_score` | from yfinance / proxy cache; causal moving-window measure |
| `final_company_signal` | one of `ACCUMULATE / HOLD / SELECTIVE_BUY / AVOID_NEW_BUY / REDUCE / EXIT_WATCH` (V6.1 labels reused — research recommendation, **not a broker order**) |
| `reason_codes` | machine-readable list of which catalysts drove the label |
| `source_files` | list of files actually read (provenance) |
| `source_dates` | per-source latest date used (e.g. companyfacts FY end, FRED date) |
| `filing_date` | most recent relevant SEC filing date |
| `filing_lag_assumption` | assumed lag from period end → tradable signal (e.g. T+1 after filing) |
| `last_updated` | when this ledger row was written |

### Causality rules (binding, not optional)

- SEC filing data can only be used **after** the actual filing date. The
  `filing_date` field is the binding constraint, not the period-end date.
- Backtests must use **next-trading-day execution** after signal generation.
- **No look-ahead.** Every score for date `t` uses only data with
  `as-of <= t` (and for filings, `filing_date <= t`).
- **No future-revised data treated as historically available** — companyfacts
  restatements appear in later filings; if the ledger reads them for a date
  before that later filing was published, that's look-ahead.
- **No assumption a company was tradable before it existed / listed.**
  ARM (2023 IPO), PLTR (2020 IPO), SNOW (2020 IPO), GEV (2024 spin-off), etc.
  must respect their listing dates.
- **Survivorship bias must be explicit.** If the universe is constructed from
  *today's* member lists, that is survivorship bias and the validation report
  must label it as such.

### Suggested outputs

- `data/research/sector_tracker/company_signal_ledger.csv`
- `reports/research/sector_tracker/company_signal_summary.md`

### Out of scope for V6.7

- No options data fetch for any ticker (would require pre-registered hypothesis,
  per V5.9 discipline).
- No live broker / order execution.
- No threshold optimization — every cutpoint is pre-declared.

---

## V6.8 — Sector aggregation from company signals

**Goal.** Aggregate the V6.7 company-level signals into a sector-level signal
per date, so the sector tracker can read "12 of 18 semi names are
ACCUMULATE" instead of relying on a handful of representative catalysts.

### Per-sector, per-date

- Count companies in each label bucket:
  `ACCUMULATE / HOLD / SELECTIVE_BUY / AVOID_NEW_BUY / REDUCE / EXIT_WATCH`.
- **Equal-weight sector score first** (transparent baseline).
- **Market-cap-weighted score later — only if** a market-cap source becomes
  available locally (yfinance shares-outstanding × close, or an explicit
  manually-maintained snapshot). If market cap is not available, the layer
  must say so and **not invent values**.
- Identify the **top companies driving the sector signal** in each direction
  (largest contributors to the BULL drivers / BROKEN risks).

### Suggested outputs

- `data/research/sector_tracker/sector_aggregated_signals.csv`
- `reports/research/sector_tracker/sector_aggregation_summary.md`

### Relationship to V6.1 / V6.2

V6.1 / V6.2 score a sector from a *flat* catalyst list. V6.8 swaps that source
for a *roll-up of company-level scores* from the V6.7 ledger. The V6.1
schema/scoring/builder may or may not need extending — that decision is part
of V6.8 design and is **not committed here**.

---

## V6.9 — Sector signal backtest (validation only)

**Goal.** Empirically test whether the V6.7 company-level and V6.8 sector-level
signals had **historical value**, before any version is ever called tradable.

### Backtest targets

- **Semiconductor:** `SMH` or `SOXX`, plus optional equal-weight semiconductor
  basket of the V6.7 universe (subject to listing-date causality).
- **AI / cloud / software:** `QQQ` or `XLK`, plus optional custom AI basket.
- **Energy infrastructure (AI power):** `XLI` / `XLU` or a custom equal-weight
  basket (depending on which tickers have data).
- **Traditional energy:** `XLE` or an equal-weight energy basket.

### Backtest comparisons (each target gets all three)

1. **Buy-and-hold sector ETF.**
2. **Sector signal strategy** — use V6.8 sector-level signal as a position
   controller (e.g. full sleeve on `ACCUMULATE`, partial on
   `SELECTIVE_BUY`, flat / reduced on `AVOID_NEW_BUY` / `REDUCE`,
   defensive on `EXIT_WATCH`). No leverage. No shorting. Defined-risk only.
3. **Equal-weight company basket** built from the V6.7 company-level signals
   (constituents weighted by label tier).

### Metrics

- total return; annualized return (if enough data)
- max drawdown; volatility; Sharpe (if appropriate sample size)
- hit rate after `ACCUMULATE` signals (forward N-day positive share)
- forward 1M / 3M / 6M return by **signal bucket**
- drawdown avoided after `REDUCE` / `EXIT_WATCH` (vs the buy-and-hold path)
- turnover; number of signals; number of companies contributing to each signal

### Causality discipline (mirrors V5.x falsification stack)

- Same no-look-ahead rules as V6.7.
- Cutpoints / label-to-position mappings are **pre-declared, not optimized**.
- Report **non-overlapping** sub-period results (e.g. annual splits) so the
  reader can see regime dependence — single-window numbers are
  hypothesis-generating only.
- Survivorship-bias and listing-date treatment must be documented.

### Dashboard addition (later — V6.5 follow-on, not V6.9 itself)

A new **"Signal History / Backtest"** page on the (V6.5) Streamlit dashboard
showing:

- which company received which signal on which date,
- sector signal history over time,
- backtest equity curve,
- forward return by signal bucket,
- top companies driving each sector signal.

---

## Standing safety rules (apply to V6.7 / V6.8 / V6.9)

- This is **future research validation only**. Not a trading signal until
  validated and explicitly approved.
- **No live trading.** **No IBKR orders.** **No broker connection.**
- `LIVE_TRADING_ENABLED` stays `False`.
- No package installs without explicit approval.
- No options data fetches without a separate pre-registered hypothesis
  (V5.9 discipline).
- No threshold / parameter optimization; every cutpoint is pre-declared.
- No fabricated values: if a data source is unavailable, the layer says so
  and marks the field NaN / `MANUAL` — it does not invent.

---

*Nothing in this document is implemented. The next concrete step is the
V6.2.1 semiconductor data-gap closure (separately scoped), not any of the
phases above.*
