"""V6.2 / V6.2.1 Semiconductor sector thesis tracker driver (read-only, local-only).

Builds the concrete semiconductor sector dataset using the V6.1 framework
(`quantbot.research.sector_tracker`). All catalysts are pre-declared here;
auto-derived statuses read EXISTING local caches only — NO network, NO ThetaData,
NO live SEC fetch. Catalysts that require data this repo does not have are
written as ``source_type=MANUAL`` with status ``NEUTRAL`` and a clear data-gap
note. **No values are invented.**

V6.2.1 upgrades (over V6.2):
  * SEC cache pre-populated for NVDA / AMD / AVGO / AMAT / LRCX / KLAC.
  * ``company_facts.py`` gained six standard us-gaap concepts (GrossProfit,
    CostOfRevenue, R&D, OperatingIncomeLoss, InventoryNet, CapEx) and a
    bug-fixed tag selector that prefers the freshest observation.
  * Three V6.2 MANUAL catalysts upgraded to auto-derived (NVDA gross margin,
    semi equipment demand, inventory cycle) and three new auto-derived
    catalysts added (NVDA / AMD / AVGO revenue YoY).
  * TSM, ASML, China policy, custom-silicon ASIC risk, semi-name options, and
    NVDA data-center segment revenue remain MANUAL (no reliable local source).

Outputs (regenerated deterministically each run):
  data/research/sector_tracker/semiconductor_thesis_tracker.csv     (catalysts)
  data/research/sector_tracker/semiconductor_emergency_exits.csv    (exits)
  reports/research/sector_tracker/semiconductor_signal.md           (report)

This is a RESEARCH SIGNAL, not a trading signal, not investment advice, and
not order execution. ``LIVE_TRADING_ENABLED`` stays ``False``. The V6.1
schema/scoring/builder/report_writer are NOT modified.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import quantbot
from quantbot.company import company_facts as CF
from quantbot.company import sec_edgar as SEC
from quantbot.research.sector_tracker import (
    Catalyst,
    EmergencyExit,
    build_sector_report,
    render_markdown,
    save_catalysts,
    save_exits,
)

# Frozen "as-of" date for this catalogue revision. Update when a catalyst is
# refreshed manually; auto-derived catalysts also stamp this date so the run is
# fully deterministic given a fixed local cache state.
REPORT_DATE = "2026-05-28"

SECTOR = "SEMICONDUCTOR"

# Universe (documentation only — catalysts reference these in notes).
UNIVERSE = ["NVDA", "AMD", "TSM", "ASML", "AVGO", "MU",
            "AMAT", "LRCX", "KLAC", "SMH", "SOXX"]

# Output paths (overridable for tests).
DEFAULT_DATA_DIR = ROOT / "data" / "research" / "sector_tracker"
DEFAULT_REPORT_DIR = ROOT / "reports" / "research" / "sector_tracker"

# Freshness gate: an auto-derived catalyst is only treated as live if the
# underlying observation's fiscal-year-end is within this window of REPORT_DATE.
# Stale observations (e.g. tags that stopped being reported) fall back to a
# NEUTRAL status with an explicit stale-data note.
FRESHNESS_WINDOW_DAYS = 540   # ~18 months

# ---- Pre-declared thresholds (fixed, not optimized) -------------------- #
# Revenue YoY (%) — used for MU + NVDA + AMD + AVGO + equipment aggregate.
REV_YOY_BANDS = [(20.0, "BULL"), (-10.0, "NEUTRAL"),
                 (-25.0, "NEAR_THRESHOLD")]  # else BROKEN

# MU NI YoY delta ($B) — preserved from V6.2.
MU_NI_DELTA_BANDS = [(1.0, "BULL"), (-1.0, "NEUTRAL"),
                     (-5.0, "NEAR_THRESHOLD")]  # else BROKEN

# Gross margin (GP / revenue, fraction) — NVDA pre-declared bands.
GROSS_MARGIN_BANDS = [(0.72, "BULL"), (0.65, "NEUTRAL"),
                      (0.60, "NEAR_THRESHOLD")]  # < 0.60 -> BROKEN

# Aggregate inventory YoY (%) for the memory/AI cohort. LOWER is better
# (semi-cycle stress shows up as inventory build).
INVENTORY_YOY_BANDS_LOWER_IS_BETTER = [(10.0, "BULL"), (30.0, "NEUTRAL"),
                                        (50.0, "NEAR_THRESHOLD")]  # >50 BROKEN

# Macro DGS10 (%) — higher = more pressure on duration-sensitive semis.
DGS10_BANDS = [(4.00, "BULL"), (4.50, "NEUTRAL"),
               (5.00, "NEAR_THRESHOLD")]   # >5.00 BROKEN

# VIX regime — lower = better.
VIX_BANDS = [(18.0, "BULL"), (22.0, "NEUTRAL"),
             (30.0, "NEAR_THRESHOLD")]    # >30 BROKEN

# 2s10s curve (T10Y2Y, pp) — higher = better.
T10Y2Y_BANDS_HIGHER_IS_BETTER = [(0.30, "BULL"), (0.0, "NEUTRAL"),
                                  (-0.30, "NEAR_THRESHOLD")]  # < -0.30 BROKEN


# --------------------------------------------------------------------------- #
# Pure helpers (no network)
# --------------------------------------------------------------------------- #
def _bucket_higher_better(value: float, bands: list[tuple[float, str]]) -> str:
    """value >= cutoff -> label (BULL/NEUTRAL/NEAR); else BROKEN."""
    for cutoff, label in bands:
        if value >= cutoff:
            return label
    return "BROKEN"


def _bucket_lower_better(value: float, bands: list[tuple[float, str]]) -> str:
    """value <= cutoff -> label; else BROKEN."""
    for cutoff, label in bands:
        if value <= cutoff:
            return label
    return "BROKEN"


def _is_fresh(end_date) -> bool:
    """True if ``end_date`` is within FRESHNESS_WINDOW_DAYS of REPORT_DATE."""
    if end_date is None or pd.isna(end_date):
        return False
    delta = (pd.Timestamp(REPORT_DATE) - pd.Timestamp(end_date)).days
    return 0 <= delta <= FRESHNESS_WINDOW_DAYS


def _company_annual_flow_yoy(facts_json: dict | None,
                              field: str) -> tuple[float | None,
                                                   float | None,
                                                   pd.Timestamp | None,
                                                   pd.Timestamp | None]:
    """Return (prev_val, last_val, prev_end, last_end) for an annual FLOW field
    (revenue / NI / OCF / GP / etc.) using the period-END convention.

    Reads from already-cached companyfacts JSON; does NO network call.
    """
    if not facts_json:
        return None, None, None, None
    obs = CF.extract_company_facts(facts_json)
    if obs.empty or field not in set(obs["field"]):
        return None, None, None, None
    sub = obs[obs["field"] == field].copy()
    sub["pd_days"] = (sub["end"] - sub["start"]).dt.days
    sub = sub[sub["pd_days"].between(350, 380)]
    ends = sorted(sub["end"].dropna().unique())
    if not ends:
        return None, None, None, None
    if len(ends) < 2:
        e_last = ends[-1]
        v_last = float(sub[sub["end"] == e_last].sort_values("fy")["val"].iloc[-1])
        return None, v_last, None, e_last
    e_prev, e_last = ends[-2], ends[-1]
    v_prev = float(sub[sub["end"] == e_prev].sort_values("fy")["val"].iloc[-1])
    v_last = float(sub[sub["end"] == e_last].sort_values("fy")["val"].iloc[-1])
    return v_prev, v_last, e_prev, e_last


def _company_instant_at_end(facts_json: dict | None, field: str,
                             at_end: pd.Timestamp) -> float | None:
    """Return value of an INSTANT field (balance-sheet) at the given fiscal-
    year-end date. None if not reported at that date."""
    if not facts_json:
        return None
    obs = CF.extract_company_facts(facts_json)
    if obs.empty:
        return None
    cand = obs[(obs["field"] == field) & (obs["end"] == at_end)]
    if cand.empty:
        return None
    return float(cand.sort_values("fy")["val"].iloc[-1])


def _yoy_pct(prev: float | None, last: float | None) -> float | None:
    if prev is None or last is None or prev == 0:
        return None
    return (last / prev - 1.0) * 100.0


def _fred_latest(name: str) -> tuple[float | None, str]:
    p = ROOT / "data" / "macro" / "fred" / f"{name}.csv"
    if not p.is_file():
        return None, ""
    df = pd.read_csv(p, parse_dates=["date"])
    df = df.dropna(subset=["value"]).sort_values("date")
    if df.empty:
        return None, ""
    last = df.iloc[-1]
    return float(last["value"]), pd.Timestamp(last["date"]).date().isoformat()


def _vix_latest() -> tuple[float | None, str]:
    p = ROOT / "data" / "macro" / "proxies" / "VIX.csv"
    if not p.is_file():
        return None, ""
    df = pd.read_csv(p, parse_dates=["date"]).set_index("date").sort_index()
    if df.empty or "close" not in df.columns:
        return None, ""
    return float(df["close"].iloc[-1]), df.index[-1].date().isoformat()


def _facts_cached(ticker: str) -> bool:
    cik = SEC.ticker_to_cik(ticker)
    if not cik:
        return False
    return (ROOT / "data" / "company" / "sec" / "companyfacts"
            / f"CIK{cik}.json").is_file()


# --------------------------------------------------------------------------- #
# Catalyst builders
# --------------------------------------------------------------------------- #
def _cat(catalyst_id: str, subsector: str, name: str, tier: int,
         direction: str, threshold: str, current_value: str, status: str,
         source_type: str, source_detail: str, action: str,
         notes: str = "", last_updated: str = REPORT_DATE) -> Catalyst:
    return Catalyst(
        catalyst_id=catalyst_id, sector=SECTOR, subsector=subsector,
        catalyst_name=name, tier=tier, direction=direction,
        threshold=threshold, current_value=current_value, status=status,
        source_type=source_type, source_detail=source_detail,
        last_updated=last_updated, action_if_broken=action, notes=notes,
    )


REV_THRESHOLD_TEXT = (
    "+20% YoY (BULL); -10..+20 NEUTRAL; -25..-10 NEAR; <-25 BROKEN"
)


def _company_revenue_catalyst(*, ticker: str, catalyst_id: str, subsector: str,
                               tier: int, name: str | None = None) -> Catalyst:
    """Build a per-company revenue-YoY catalyst. Auto-derived if companyfacts
    are cached AND the latest fiscal-year-end is fresh; otherwise MANUAL/NEUTRAL
    with a clear note. No values invented."""
    label = name or f"{ticker} revenue YoY"
    if not _facts_cached(ticker):
        return _cat(catalyst_id, subsector, label, tier, "ABOVE",
                    REV_THRESHOLD_TEXT, "n/a", "NEUTRAL", "MANUAL",
                    f"SEC:{ticker} companyfacts (NOT cached)",
                    "review thesis (no order)",
                    f"To enable: run scripts/run_company_research.py {ticker} "
                    "to cache, then re-run this driver.")
    facts = SEC.fetch_company_facts(ticker)
    prev, last, e_prev, e_last = _company_annual_flow_yoy(facts, "revenue")
    if last is None or not _is_fresh(e_last) or prev is None:
        stale = (f"latest FYE {pd.Timestamp(e_last).date()}"
                 if e_last is not None else "no annual revenue obs")
        return _cat(catalyst_id, subsector, label, tier, "ABOVE",
                    REV_THRESHOLD_TEXT, "n/a", "NEUTRAL", "MANUAL",
                    f"SEC:{ticker} companyfacts (stale: {stale})",
                    "review thesis (no order)",
                    "Stale-data: companyfacts revenue tag does not reach the "
                    "freshness window; manual review required.")
    yoy = _yoy_pct(prev, last)
    status = _bucket_higher_better(yoy if yoy is not None else 0.0, REV_YOY_BANDS) \
        if yoy is not None else "NEUTRAL"
    fy_label = f"FY{pd.Timestamp(e_prev).year}->FY{pd.Timestamp(e_last).year}"
    return _cat(catalyst_id, subsector, label, tier, "ABOVE",
                REV_THRESHOLD_TEXT,
                f"{yoy:+.1f}% ({fy_label})" if yoy is not None else "n/a",
                status, "SEC_EDGAR",
                f"SEC:{ticker} companyfacts revenue {fy_label} (auto-derived)",
                "review sector sleeve; pause adds; do not auto-trade",
                f"FYE {pd.Timestamp(e_last).date()}")


def _build_mu_catalysts() -> list[Catalyst]:
    """MU revenue + NI catalysts (preserved from V6.2 — uses period-END trend)."""
    rev_cat = _company_revenue_catalyst(
        ticker="MU", catalyst_id="SEMI-MU-HBM-REV-T1", subsector="MEMORY",
        tier=1, name="HBM / memory cycle (MU revenue YoY)")
    # MU NI delta in $B (cycle recovery proxy)
    facts = SEC.fetch_company_facts("MU") if _facts_cached("MU") else None
    if facts:
        ni_prev, ni_last, e_prev, e_last = _company_annual_flow_yoy(facts, "net_income")
    else:
        ni_prev = ni_last = None; e_prev = e_last = None
    if ni_prev is None or ni_last is None or not _is_fresh(e_last):
        ni_cat = _cat("SEMI-MU-MEMCYCLE-NI-T1", "MEMORY",
                      "Memory cycle recovery (MU net income YoY delta)", 1, "ABOVE",
                      "+$1.0B (BULL); -1..+1 NEUTRAL; -5..-1 NEAR; <-5 BROKEN",
                      "n/a", "NEUTRAL", "MANUAL",
                      "SEC:MU companyfacts (stale or missing)",
                      "review sector sleeve",
                      "")
    else:
        delta_b = (ni_last - ni_prev) / 1e9
        status = _bucket_higher_better(delta_b, MU_NI_DELTA_BANDS)
        fy_label = f"FY{pd.Timestamp(e_prev).year}->FY{pd.Timestamp(e_last).year}"
        ni_cat = _cat("SEMI-MU-MEMCYCLE-NI-T1", "MEMORY",
                      "Memory cycle recovery (MU net income YoY delta)",
                      1, "ABOVE",
                      "+$1.0B (BULL); -1..+1 NEUTRAL; -5..-1 NEAR; <-5 BROKEN",
                      f"{delta_b:+.2f}B ({fy_label})", status,
                      "SEC_EDGAR",
                      f"SEC:MU companyfacts NI {fy_label} (auto-derived)",
                      "review sector sleeve",
                      f"FYE {pd.Timestamp(e_last).date()}")
    return [rev_cat, ni_cat]


def _build_nvda_gross_margin_catalyst() -> Catalyst:
    """NVDA gross margin = GrossProfit / Revenue at latest fresh FYE."""
    catalyst_id = "SEMI-NVDA-GM-T1"
    name = "Nvidia gross margin"
    threshold = ">=72% BULL; 65..72 NEUTRAL; 60..65 NEAR; <60 BROKEN"
    if not _facts_cached("NVDA"):
        return _cat(catalyst_id, "AI_ACCELERATOR", name, 1, "ABOVE", threshold,
                    "n/a", "NEUTRAL", "MANUAL",
                    "SEC:NVDA companyfacts (NOT cached)",
                    "review NVDA exposure",
                    "Pre-fetch NVDA SEC via scripts/run_company_research.py NVDA.")
    facts = SEC.fetch_company_facts("NVDA")
    _, gp_last, _, gp_end = _company_annual_flow_yoy(facts, "gross_profit")
    _, rev_last, _, rev_end = _company_annual_flow_yoy(facts, "revenue")
    if (gp_last is None or rev_last is None or rev_last == 0
            or not _is_fresh(gp_end) or not _is_fresh(rev_end)):
        return _cat(catalyst_id, "AI_ACCELERATOR", name, 1, "ABOVE", threshold,
                    "n/a", "NEUTRAL", "MANUAL",
                    "SEC:NVDA companyfacts (stale or missing GP/revenue)",
                    "review NVDA exposure",
                    "Auto-derive failed: stale or missing data.")
    gm = gp_last / rev_last
    status = _bucket_higher_better(gm, GROSS_MARGIN_BANDS)
    fye = pd.Timestamp(min(gp_end, rev_end)).date()
    return _cat(catalyst_id, "AI_ACCELERATOR", name, 1, "ABOVE", threshold,
                f"{gm*100:.1f}% (FYE {fye})", status, "SEC_EDGAR",
                f"SEC:NVDA companyfacts GrossProfit/Revenue {fye} (auto-derived)",
                "review NVDA exposure",
                f"GP=${gp_last/1e9:.2f}B / Revenue=${rev_last/1e9:.2f}B")


def _build_equipment_demand_catalyst() -> Catalyst:
    """Aggregate revenue YoY across AMAT + LRCX + KLAC as a semi capex / fab-
    equipment-demand proxy (their revenue IS fab capex from the buyer's view)."""
    catalyst_id = "SEMI-EQUIPMENT-DEMAND-T2"
    name = "Semi equipment demand (AMAT+LRCX+KLAC aggregate revenue YoY)"
    threshold = REV_THRESHOLD_TEXT
    tickers = ("AMAT", "LRCX", "KLAC")
    prev_sum = 0.0
    last_sum = 0.0
    fye_dates: list[pd.Timestamp] = []
    missing: list[str] = []
    for t in tickers:
        if not _facts_cached(t):
            missing.append(t); continue
        prev, last, _, e_last = _company_annual_flow_yoy(
            SEC.fetch_company_facts(t), "revenue")
        if prev is None or last is None or not _is_fresh(e_last):
            missing.append(t); continue
        prev_sum += prev; last_sum += last
        fye_dates.append(pd.Timestamp(e_last))
    if missing or prev_sum == 0:
        return _cat(catalyst_id, "EQUIPMENT", name, 2, "ABOVE", threshold,
                    "n/a", "NEUTRAL", "MANUAL",
                    "Aggregate equipment-revenue auto-derive partial "
                    f"(missing: {','.join(missing) or 'none'})",
                    "review equipment-maker exposure",
                    "Pre-fetch AMAT/LRCX/KLAC SEC to enable.")
    yoy = _yoy_pct(prev_sum, last_sum)
    status = _bucket_higher_better(yoy if yoy is not None else 0.0, REV_YOY_BANDS) \
        if yoy is not None else "NEUTRAL"
    latest_fye = max(fye_dates).date()
    return _cat(catalyst_id, "EQUIPMENT", name, 2, "ABOVE", threshold,
                f"{yoy:+.1f}% (latest FYE {latest_fye})"
                if yoy is not None else "n/a",
                status, "SEC_EDGAR",
                f"SEC:AMAT+LRCX+KLAC companyfacts revenue (auto-derived; "
                f"latest FYE {latest_fye})",
                "review equipment-maker exposure",
                f"Aggregates: prev=${prev_sum/1e9:.2f}B last=${last_sum/1e9:.2f}B")


def _build_inventory_cycle_catalyst() -> Catalyst:
    """Aggregate InventoryNet YoY across NVDA + AMD + MU + AVGO. Sharp rises
    are bearish (sector inventory build); falls/stable are bullish."""
    catalyst_id = "SEMI-INVENTORY-CYCLE-T2"
    name = "Semi inventory cycle (NVDA+AMD+MU+AVGO aggregate InventoryNet YoY)"
    threshold = (
        "<=+10% BULL (controlled); +10..30 NEUTRAL; +30..50 NEAR; >+50 BROKEN"
    )
    tickers = ("NVDA", "AMD", "MU", "AVGO")
    last_total = 0.0
    prev_total = 0.0
    fye_dates: list[pd.Timestamp] = []
    missing: list[str] = []
    for t in tickers:
        if not _facts_cached(t):
            missing.append(t); continue
        facts = SEC.fetch_company_facts(t)
        # Determine the latest fresh FYE for this ticker from revenue flow
        _, _, _, e_last = _company_annual_flow_yoy(facts, "revenue")
        if e_last is None or not _is_fresh(e_last):
            missing.append(t); continue
        # Prior FYE = the one before e_last (use revenue ends to define it)
        obs = CF.extract_company_facts(facts).copy()
        obs["pd_days"] = (obs["end"] - obs["start"]).dt.days
        rev_ends = sorted(obs[(obs["field"] == "revenue")
                              & obs["pd_days"].between(350, 380)]["end"].dropna().unique())
        if len(rev_ends) < 2:
            missing.append(t); continue
        e_prev = rev_ends[-2]
        inv_last = _company_instant_at_end(facts, "inventory_net", e_last)
        inv_prev = _company_instant_at_end(facts, "inventory_net", e_prev)
        if inv_last is None or inv_prev is None:
            missing.append(t); continue
        last_total += inv_last; prev_total += inv_prev
        fye_dates.append(pd.Timestamp(e_last))
    if missing or prev_total == 0:
        return _cat(catalyst_id, "CYCLE", name, 2, "BELOW", threshold,
                    "n/a", "NEUTRAL", "MANUAL",
                    f"Inventory aggregate partial (missing: "
                    f"{','.join(missing) or 'none'})",
                    "review sector pacing",
                    "Pre-fetch NVDA/AMD/AVGO SEC + ensure InventoryNet "
                    "available at both fiscal year-ends.")
    yoy = _yoy_pct(prev_total, last_total)
    status = _bucket_lower_better(
        yoy if yoy is not None else 0.0,
        INVENTORY_YOY_BANDS_LOWER_IS_BETTER,
    ) if yoy is not None else "NEUTRAL"
    latest_fye = max(fye_dates).date()
    return _cat(catalyst_id, "CYCLE", name, 2, "BELOW", threshold,
                f"{yoy:+.1f}% (latest FYE {latest_fye})"
                if yoy is not None else "n/a",
                status, "SEC_EDGAR",
                f"SEC:NVDA+AMD+MU+AVGO InventoryNet aggregate (auto-derived; "
                f"latest FYE {latest_fye})",
                "monitor sector inventory; consider pacing",
                f"Aggregates: prev=${prev_total/1e9:.2f}B last=${last_total/1e9:.2f}B")


def _build_macro_catalysts() -> list[Catalyst]:
    out: list[Catalyst] = []
    dgs10, dgs10_dt = _fred_latest("DGS10")
    if dgs10 is not None:
        status = _bucket_lower_better(dgs10, DGS10_BANDS)
        out.append(_cat("SEMI-MACRO-RATES-T2", "MACRO",
                        "Macro regime — long-end rates (DGS10)", 2, "BELOW",
                        "<=4.00 BULL; <=4.50 NEUTRAL; <=5.00 NEAR; >5.00 BROKEN",
                        f"{dgs10:.2f}% ({dgs10_dt})", status,
                        "FRED", "FRED:DGS10 (local cache)",
                        "monitor rates", "Tier 2: macro amplifier."))
    else:
        out.append(_cat("SEMI-MACRO-RATES-T2", "MACRO",
                        "Macro regime — long-end rates (DGS10)", 2, "BELOW",
                        "<=4.00 BULL; <=4.50 NEUTRAL; <=5.00 NEAR; >5.00 BROKEN",
                        "n/a", "NEUTRAL", "FRED", "FRED:DGS10 (NOT FOUND)",
                        "monitor rates", "FRED DGS10 cache missing."))

    vix, vix_dt = _vix_latest()
    if vix is not None:
        status = _bucket_lower_better(vix, VIX_BANDS)
        out.append(_cat("SEMI-MACRO-VOL-T2", "MACRO",
                        "Macro regime — equity volatility (VIX)", 2, "BELOW",
                        "<=18 BULL; <=22 NEUTRAL; <=30 NEAR; >30 BROKEN",
                        f"{vix:.2f} ({vix_dt})", status,
                        "YFINANCE", "VIX proxy (data/macro/proxies/VIX.csv)",
                        "monitor volatility regime",
                        "Tier 2: macro amplifier."))
    else:
        out.append(_cat("SEMI-MACRO-VOL-T2", "MACRO",
                        "Macro regime — equity volatility (VIX)", 2, "BELOW",
                        "<=18 BULL; <=22 NEUTRAL; <=30 NEAR; >30 BROKEN",
                        "n/a", "NEUTRAL", "YFINANCE", "VIX cache (NOT FOUND)",
                        "monitor volatility regime", "VIX cache missing."))

    t10y2y, t10y2y_dt = _fred_latest("T10Y2Y")
    if t10y2y is not None:
        status = _bucket_higher_better(t10y2y, T10Y2Y_BANDS_HIGHER_IS_BETTER)
        out.append(_cat("SEMI-MACRO-CURVE-T2", "MACRO",
                        "Macro regime — 2s10s curve (T10Y2Y)", 2, "ABOVE",
                        ">=+0.30 BULL; >=0 NEUTRAL; >=-0.30 NEAR; <-0.30 BROKEN",
                        f"{t10y2y:+.2f}pp ({t10y2y_dt})", status,
                        "FRED", "FRED:T10Y2Y (local cache)",
                        "monitor curve", "Tier 2: macro amplifier."))
    else:
        out.append(_cat("SEMI-MACRO-CURVE-T2", "MACRO",
                        "Macro regime — 2s10s curve (T10Y2Y)", 2, "ABOVE",
                        ">=+0.30 BULL; >=0 NEUTRAL; >=-0.30 NEAR; <-0.30 BROKEN",
                        "n/a", "NEUTRAL", "FRED", "FRED:T10Y2Y (NOT FOUND)",
                        "monitor curve", "FRED T10Y2Y cache missing."))
    return out


def _build_manual_catalysts() -> list[Catalyst]:
    """Catalysts that remain MANUAL/NEUTRAL after V6.2.1 — declared with
    thresholds but unverified. No values invented."""
    no_cache_note = (
        "Required data not in local cache. To enable auto-derivation, supply "
        "MANUAL values + status. Do not invent values."
    )
    return [
        _cat("SEMI-NVDA-DC-REV-T1", "AI_ACCELERATOR",
             "Nvidia data-center revenue (segment)", 1, "ABOVE",
             ">+50% YoY BULL; +20..+50 NEUTRAL; 0..+20 NEAR; <0 BROKEN",
             "n/a", "NEUTRAL", "MANUAL",
             "NVDA 10-Q segment table (not in standard companyfacts top-level "
             "concepts; segment XBRL extraction is out of V6.2.1 scope)",
             "review NVDA exposure separately; no auto-trade",
             no_cache_note),
        _cat("SEMI-TSM-N3-DEMAND-T1", "FOUNDRY",
             "TSMC advanced-node (N3/N5) demand", 1, "ABOVE", "qualitative",
             "n/a", "NEUTRAL", "MANUAL",
             "TSM 20-F / monthly revenue release (foreign filer; 20-F not in "
             "V6.1 SUPPORTED_FORMS)",
             "review foundry exposure", no_cache_note),
        _cat("SEMI-ASML-BOOKINGS-T1", "EQUIPMENT",
             "ASML bookings / EUV demand", 1, "ABOVE", "qualitative",
             "n/a", "NEUTRAL", "MANUAL",
             "ASML 20-F / Q-report (foreign filer)",
             "review equipment-maker exposure", no_cache_note),
        _cat("SEMI-CHINA-EXPORT-RISK-T1", "GEOPOLITICAL",
             "China / US export-control policy risk", 1, "QUALITATIVE",
             "no new material restrictions = NEUTRAL; new ban = BROKEN",
             "n/a", "NEUTRAL", "MANUAL",
             "BIS/Commerce/State announcements (manual monitoring)",
             "see emergency-exit SEMI-EXIT-CHINA-EXPORT-SHOCK",
             "Tier 1 risk; also tracked as a separate emergency-exit scenario."),
        _cat("SEMI-CUSTOM-SILICON-T2", "AI_ACCELERATOR",
             "Custom silicon / ASIC displacement risk (hyperscaler in-house)", 2,
             "BELOW",
             "qualitative: accelerating displacement = BROKEN",
             "n/a", "NEUTRAL", "MANUAL",
             "manual tracking of Google TPU / AWS Trainium / Microsoft Maia "
             "announcements + hyperscaler 10-Qs",
             "monitor NVDA share-of-AI-accelerator commentary",
             no_cache_note),
        _cat("SEMI-OPTIONS-RISK-T2", "OPTIONS_MARKET",
             "Options IV-rank / skew / liquidity (semi names)", 2,
             "QUALITATIVE",
             "low IV-rank + tight liquidity = NEUTRAL; elevated risk = BROKEN",
             "n/a", "NEUTRAL", "OPTIONS_FEATURE",
             "V5.8 features exist for SPY only (2022 + Jan-2023 OOS); no "
             "per-name semi option data has been fetched in this repo",
             "do not fetch options data without explicit approval (V5.9 discipline)",
             "Per-name semi options pull is out of scope until a pre-registered "
             "hypothesis."),
    ]


def _build_emergency_exits() -> list[EmergencyExit]:
    common_action = (
        "research-only: re-evaluate sector sleeve; consider defined-risk hedges "
        "via the existing options layer (separate approval required); NO order "
        "execution"
    )
    return [
        EmergencyExit(
            exit_id="SEMI-EXIT-NVDA-DC-SEQ-DECLINE", sector=SECTOR,
            scenario="Nvidia data-center revenue posts a sequential (QoQ) decline",
            trigger_condition=(
                "NVDA reported DC revenue QoQ < 0% in two consecutive quarterly "
                "10-Q / earnings 8-K releases"
            ),
            current_status="MONITORING", action=common_action,
            source="MANUAL (NVDA 10-Q / 8-K segment data)",
            last_updated=REPORT_DATE),
        EmergencyExit(
            exit_id="SEMI-EXIT-HYPERSCALER-CAPEX-CUT", sector=SECTOR,
            scenario="Hyperscaler capex guide is cut materially",
            trigger_condition=(
                "MSFT / GOOGL / AMZN / META capex guidance YoY revised "
                "lower by >= 10% across two consecutive prints"
            ),
            current_status="MONITORING", action=common_action,
            source="MANUAL (hyperscaler 10-Q + earnings commentary, not cached)",
            last_updated=REPORT_DATE),
        EmergencyExit(
            exit_id="SEMI-EXIT-HBM-ASP-DETERIORATION", sector=SECTOR,
            scenario="HBM ASP / memory gross margin deteriorates sharply",
            trigger_condition=(
                "MU gross-margin guide cut > 500 bps QoQ OR HBM ASP commentary "
                "turns negative in MU/SK Hynix releases"
            ),
            current_status="MONITORING", action=common_action,
            source="SEC_EDGAR (MU 8-K/10-Q; companyfacts GrossProfit now available)",
            last_updated=REPORT_DATE),
        EmergencyExit(
            exit_id="SEMI-EXIT-CHINA-EXPORT-SHOCK", sector=SECTOR,
            scenario="Major new US/China export-control restriction on AI chips",
            trigger_condition=(
                "New BIS rule or Entity-List action materially restricting AI "
                "accelerator exports / specific names"
            ),
            current_status="MONITORING", action=common_action,
            source="MANUAL (BIS/Commerce/State announcements)",
            last_updated=REPORT_DATE),
        EmergencyExit(
            exit_id="SEMI-EXIT-CUSTOM-SILICON-DISPLACE", sector=SECTOR,
            scenario="Custom silicon displacement of merchant AI accelerators "
                      "accelerates",
            trigger_condition=(
                "Two or more hyperscalers disclose accelerating share shift to "
                "in-house ASIC (TPU / Trainium / Maia) over consecutive prints"
            ),
            current_status="MONITORING", action=common_action,
            source="MANUAL (hyperscaler 10-K / 10-Q commentary)",
            last_updated=REPORT_DATE),
        EmergencyExit(
            exit_id="SEMI-EXIT-INVENTORY-SHARP-NEG", sector=SECTOR,
            scenario="Semiconductor inventory cycle turns sharply negative",
            trigger_condition=(
                "Aggregate semi-customer inventory days rise materially QoQ AND "
                "two or more sector names guide revenue lower on inventory "
                "digestion"
            ),
            current_status="MONITORING", action=common_action,
            source="SEC_EDGAR (V6.2.1 inventory aggregate catalyst is "
                   "SEMI-INVENTORY-CYCLE-T2)",
            last_updated=REPORT_DATE),
    ]


# --------------------------------------------------------------------------- #
# Markdown extras (appended to V6.1 base render)
# --------------------------------------------------------------------------- #
DISCLAIMER = (
    "**This is a research signal, not a trading signal, not investment "
    "advice, and not order execution.**"
)


def _data_gap_section(catalysts: list[Catalyst]) -> str:
    gaps = [c for c in catalysts
            if c.source_type == "MANUAL"
            or "NOT FOUND" in c.source_detail
            or "(NOT cached" in c.source_detail
            or "stale" in c.source_detail.lower()]
    lines = ["\n## Data gaps (unverified / MANUAL or stale catalysts)\n"]
    if not gaps:
        lines.append("_(none — every catalyst is auto-derived from local data)_\n")
        return "\n".join(lines)
    lines.append("| catalyst_id | catalyst_name | source_detail |")
    lines.append("|---|---|---|")
    for c in gaps:
        lines.append(f"| {c.catalyst_id} | {c.catalyst_name} | {c.source_detail} |")
    lines.append("\n_Manual / unverified catalysts are written with status "
                 "`NEUTRAL` and explicit data-gap notes — no values are invented. "
                 "They still consume scoring weight, so an unverified sector "
                 "reads as deliberately cautious until populated._\n")
    return "\n".join(lines)


def _autoderived_section(catalysts: list[Catalyst]) -> str:
    auto = [c for c in catalysts if c.source_type in {"SEC_EDGAR", "FRED",
                                                       "YFINANCE"}
            and "NOT FOUND" not in c.source_detail
            and "stale" not in c.source_detail.lower()]
    lines = ["\n## Auto-derived catalysts (V6.2.1)\n"]
    if not auto:
        lines.append("_(none)_\n"); return "\n".join(lines)
    lines.append("| catalyst_id | tier | status | current_value | source |")
    lines.append("|---|---|---|---|---|")
    for c in auto:
        lines.append(f"| {c.catalyst_id} | {c.tier} | {c.status} | "
                     f"{c.current_value} | {c.source_type} |")
    return "\n".join(lines)


def _next_step_section() -> str:
    return (
        "\n## Next recommended step\n"
        "1. **(Optional) TSM / ASML foreign-filer support** — would require "
        "extending the company layer to 20-F / 6-K forms; out of V6.2.1 scope.\n"
        "2. **NVDA segment data** (data-center revenue) is still MANUAL — "
        "XBRL segment extraction is non-trivial and intentionally deferred.\n"
        "3. **V6.3 AI tracker** is the natural next phase now that the company "
        "layer auto-derives reliably for US filers.\n"
        "4. **Do NOT fetch options data** for semi names without an explicit "
        "pre-registered hypothesis (V5.9 discipline).\n"
    )


def _roadmap_note() -> str:
    return (
        "\n## Future roadmap (NOTE ONLY — not implemented)\n"
        "See `reports/research/sector_tracker/ROADMAP.md` for the full V6.7 / "
        "V6.8 / V6.9 plan (company-level signal ledger, sector aggregation from "
        "company signals, sector-level historical backtest). None of those "
        "phases is implemented; nothing here is tradable.\n"
    )


# --------------------------------------------------------------------------- #
# Orchestrator
# --------------------------------------------------------------------------- #
def build_catalysts() -> list[Catalyst]:
    """Read local data only — no network — and assemble the catalyst list."""
    out: list[Catalyst] = []
    out.extend(_build_mu_catalysts())
    # New per-company revenue catalysts (auto if cached + fresh; else MANUAL).
    out.append(_company_revenue_catalyst(
        ticker="NVDA", catalyst_id="SEMI-NVDA-REV-T1",
        subsector="AI_ACCELERATOR", tier=1,
        name="Nvidia revenue YoY (AI accelerator demand)"))
    out.append(_build_nvda_gross_margin_catalyst())
    out.append(_company_revenue_catalyst(
        ticker="AMD", catalyst_id="SEMI-AMD-REV-T2", subsector="AI_ACCELERATOR",
        tier=2, name="AMD revenue YoY"))
    out.append(_company_revenue_catalyst(
        ticker="AVGO", catalyst_id="SEMI-AVGO-REV-T2",
        subsector="AI_ACCELERATOR", tier=2,
        name="AVGO revenue YoY (AI custom silicon / networking)"))
    out.append(_build_equipment_demand_catalyst())
    out.append(_build_inventory_cycle_catalyst())
    out.extend(_build_macro_catalysts())
    out.extend(_build_manual_catalysts())
    return out


def main(data_dir: Path | str | None = None,
         report_dir: Path | str | None = None) -> dict[str, Any]:
    assert quantbot.LIVE_TRADING_ENABLED is False, "V6.2.1 driver is RESEARCH only."
    ddir = Path(data_dir) if data_dir else DEFAULT_DATA_DIR
    rdir = Path(report_dir) if report_dir else DEFAULT_REPORT_DIR
    ddir.mkdir(parents=True, exist_ok=True)
    rdir.mkdir(parents=True, exist_ok=True)

    catalysts = build_catalysts()
    exits = _build_emergency_exits()

    cat_path = save_catalysts(catalysts, ddir / "semiconductor_thesis_tracker.csv")
    ex_path = save_exits(exits, ddir / "semiconductor_emergency_exits.csv")

    report = build_sector_report(SECTOR, catalysts, exits)
    md = render_markdown(report)
    md += f"\n{DISCLAIMER}\n"
    md += _autoderived_section(catalysts)
    md += _data_gap_section(catalysts)
    md += _next_step_section()
    md += _roadmap_note()
    rpt_path = rdir / "semiconductor_signal.md"
    rpt_path.write_text(md, encoding="utf-8")

    auto_count = sum(1 for c in catalysts
                     if c.source_type in {"SEC_EDGAR", "FRED", "YFINANCE"}
                     and "NOT FOUND" not in c.source_detail
                     and "stale" not in c.source_detail.lower())
    print(f"Semiconductor sector signal: {report.score.signal} "
          f"(norm {report.score.normalized_score:+.3f}, "
          f"raw {report.score.raw_score:+.1f} / weight {report.score.total_weight})")
    print(f"  catalysts={len(catalysts)} (BULL {report.score.n_bull}, "
          f"NEUTRAL {report.score.n_neutral}, "
          f"NEAR_THRESHOLD {report.score.n_near_threshold}, "
          f"BROKEN {report.score.n_broken})")
    print(f"  auto-derived: {auto_count}/{len(catalysts)}; "
          f"manual: {len(catalysts) - auto_count}")
    print(f"  emergency exits MONITORING: "
          f"{sum(1 for e in exits if e.current_status=='MONITORING')}/{len(exits)}  "
          f"triggered={report.score.emergency_triggered}")
    print(f"\nWrote:\n  {cat_path}\n  {ex_path}\n  {rpt_path}")
    return {
        "signal": report.score.signal,
        "normalized_score": report.score.normalized_score,
        "n_catalysts": len(catalysts),
        "n_auto_derived": auto_count,
        "n_exits": len(exits),
        "paths": {"catalysts": str(cat_path), "exits": str(ex_path),
                  "report": str(rpt_path)},
    }


if __name__ == "__main__":
    raise SystemExit(0 if main() else 1)
