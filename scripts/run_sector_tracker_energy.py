"""V6.4 Energy / power-infrastructure sector tracker driver (read-only).

Builds the Energy sector dataset using the V6.1 framework and the V6.2.1/V6.3
shared helpers in ``quantbot.research.sector_tracker.driver_utils``. Splits the
sector into two clearly-labelled subsectors:

  * ``AI_POWER_INFRA``     — power equipment / grid / utility names that benefit
                             from the AI / data-center build-out
                             (GEV, ETN, VRT, PWR, CEG, NEE, SO)
  * ``TRADITIONAL_ENERGY`` — integrated oil & gas majors and related context
                             (XOM, CVX, COP, LNG / commodity context)

A small MACRO subsector carries the three sector-agnostic regime catalysts.

All catalysts are pre-declared; auto-derived statuses read EXISTING local
caches only — NO network, NO ThetaData, NO live SEC fetch. Catalysts without a
reliable local source (data-center power demand commentary, SMR / uranium,
regulatory rate cases, commodity prices, LNG contracts, per-name options) are
written as ``source_type=MANUAL`` with status ``NEUTRAL`` and explicit data-gap
notes. **No values are invented.**

Outputs (regenerated deterministically each run):
  data/research/sector_tracker/energy_thesis_tracker.csv
  data/research/sector_tracker/energy_emergency_exits.csv
  reports/research/sector_tracker/energy_signal.md

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
from quantbot.company import sec_edgar as SEC
from quantbot.research.sector_tracker import (
    Catalyst,
    EmergencyExit,
    build_sector_report,
    render_markdown,
    save_catalysts,
    save_exits,
)
from quantbot.research.sector_tracker.driver_utils import (
    DISCLAIMER,
    REV_THRESHOLD_TEXT,
    REV_YOY_BANDS,
    autoderived_section,
    bucket_higher_better,
    company_annual_flow_yoy,
    company_revenue_catalyst,
    count_auto_derived,
    data_gap_section,
    facts_cached,
    is_fresh,
    macro_catalysts,
    make_catalyst,
    yoy_pct,
)

REPORT_DATE = "2026-05-28"
SECTOR = "ENERGY"

SUBSECTOR_AI = "AI_POWER_INFRA"
SUBSECTOR_TRAD = "TRADITIONAL_ENERGY"
SUBSECTOR_MACRO = "MACRO"

# Universe (documentation only; catalysts reference these in notes).
AI_POWER_UNIVERSE = ["GEV", "ETN", "VRT", "PWR", "CEG", "NEE", "SO"]
TRAD_UNIVERSE = ["XOM", "CVX", "COP"]
UNIVERSE = AI_POWER_UNIVERSE + TRAD_UNIVERSE

DEFAULT_DATA_DIR = ROOT / "data" / "research" / "sector_tracker"
DEFAULT_REPORT_DIR = ROOT / "reports" / "research" / "sector_tracker"


# --------------------------------------------------------------------------- #
# Sector-specific catalyst builders
# --------------------------------------------------------------------------- #
def _ai_power_revenue_catalysts() -> list[Catalyst]:
    """Per-name revenue YoY for the AI_POWER_INFRA universe. Reuses the shared
    ``company_revenue_catalyst`` helper for consistent thresholds (REV_YOY_BANDS)
    and a graceful MANUAL fallback when the tag is stale (e.g. NEE)."""
    out: list[Catalyst] = []
    out.append(company_revenue_catalyst(
        ticker="GEV", sector=SECTOR, catalyst_id="ENER-GEV-REV-T1",
        subsector=SUBSECTOR_AI, tier=1, report_date=REPORT_DATE,
        name="GE Vernova revenue YoY (turbines + grid for AI build-out)"))
    out.append(company_revenue_catalyst(
        ticker="ETN", sector=SECTOR, catalyst_id="ENER-ETN-REV-T1",
        subsector=SUBSECTOR_AI, tier=1, report_date=REPORT_DATE,
        name="Eaton revenue YoY (electrical equipment for data centers)"))
    out.append(company_revenue_catalyst(
        ticker="VRT", sector=SECTOR, catalyst_id="ENER-VRT-REV-T1",
        subsector=SUBSECTOR_AI, tier=1, report_date=REPORT_DATE,
        name="Vertiv revenue YoY (data center power + cooling, most AI-direct)"))
    out.append(company_revenue_catalyst(
        ticker="PWR", sector=SECTOR, catalyst_id="ENER-PWR-REV-T1",
        subsector=SUBSECTOR_AI, tier=1, report_date=REPORT_DATE,
        name="Quanta Services revenue YoY (grid construction)"))
    out.append(company_revenue_catalyst(
        ticker="CEG", sector=SECTOR, catalyst_id="ENER-CEG-REV-T1",
        subsector=SUBSECTOR_AI, tier=1, report_date=REPORT_DATE,
        name="Constellation Energy revenue YoY (nuclear baseload for AI)"))
    out.append(company_revenue_catalyst(
        ticker="NEE", sector=SECTOR, catalyst_id="ENER-NEE-REV-T2",
        subsector=SUBSECTOR_AI, tier=2, report_date=REPORT_DATE,
        name="NextEra Energy revenue YoY (utility + renewables)"))
    out.append(company_revenue_catalyst(
        ticker="SO", sector=SECTOR, catalyst_id="ENER-SO-REV-T2",
        subsector=SUBSECTOR_AI, tier=2, report_date=REPORT_DATE,
        name="Southern Co revenue YoY (utility — AI load growth)"))
    return out


def _trad_energy_revenue_catalysts() -> list[Catalyst]:
    """Per-name revenue YoY for the TRADITIONAL_ENERGY majors."""
    out: list[Catalyst] = []
    out.append(company_revenue_catalyst(
        ticker="XOM", sector=SECTOR, catalyst_id="ENER-XOM-REV-T1",
        subsector=SUBSECTOR_TRAD, tier=1, report_date=REPORT_DATE,
        name="ExxonMobil revenue YoY (integrated oil & gas)"))
    out.append(company_revenue_catalyst(
        ticker="CVX", sector=SECTOR, catalyst_id="ENER-CVX-REV-T1",
        subsector=SUBSECTOR_TRAD, tier=1, report_date=REPORT_DATE,
        name="Chevron revenue YoY (integrated oil & gas)"))
    out.append(company_revenue_catalyst(
        ticker="COP", sector=SECTOR, catalyst_id="ENER-COP-REV-T2",
        subsector=SUBSECTOR_TRAD, tier=2, report_date=REPORT_DATE,
        name="ConocoPhillips revenue YoY (US shale + upstream)"))
    return out


def _oilgas_ocf_catalyst() -> Catalyst:
    """Aggregate operating cash flow YoY across XOM + CVX + COP. Treated as a
    cash-generation / capex-discipline proxy: when OCF is rising, the majors
    can fund both capex and shareholder returns; when falling, dividend /
    buyback coverage is stressed."""
    cid = "ENER-OILGAS-OCF-T2"
    name = "Oil & gas majors aggregate operating cash flow YoY (XOM+CVX+COP)"
    threshold = REV_THRESHOLD_TEXT
    tickers = ("XOM", "CVX", "COP")
    prev_sum = last_sum = 0.0
    fye_dates: list[pd.Timestamp] = []
    missing: list[str] = []
    for t in tickers:
        if not facts_cached(t):
            missing.append(t); continue
        prev, last, _, e_last = company_annual_flow_yoy(
            SEC.fetch_company_facts(t), "operating_cash_flow")
        if prev is None or last is None or not is_fresh(e_last, report_date=REPORT_DATE):
            missing.append(t); continue
        prev_sum += prev; last_sum += last
        fye_dates.append(pd.Timestamp(e_last))
    if missing or prev_sum == 0:
        return make_catalyst(
            catalyst_id=cid, sector=SECTOR, subsector=SUBSECTOR_TRAD,
            catalyst_name=name, tier=2, direction="ABOVE",
            threshold=threshold, current_value="n/a", status="NEUTRAL",
            source_type="MANUAL",
            source_detail=(f"OCF aggregate partial (missing: "
                           f"{','.join(missing) or 'none'})"),
            action="review cash-return assumptions",
            notes="Pre-fetch XOM/CVX/COP SEC to enable.",
            last_updated=REPORT_DATE,
        )
    yoy = yoy_pct(prev_sum, last_sum)
    status = bucket_higher_better(yoy if yoy is not None else 0.0, REV_YOY_BANDS) \
        if yoy is not None else "NEUTRAL"
    latest_fye = max(fye_dates).date()
    return make_catalyst(
        catalyst_id=cid, sector=SECTOR, subsector=SUBSECTOR_TRAD,
        catalyst_name=name, tier=2, direction="ABOVE", threshold=threshold,
        current_value=(f"{yoy:+.1f}% (latest FYE {latest_fye})"
                       if yoy is not None else "n/a"),
        status=status, source_type="SEC_EDGAR",
        source_detail=(f"SEC:XOM+CVX+COP companyfacts OCF aggregate "
                       f"(auto-derived; latest FYE {latest_fye})"),
        action="review cash-return / capex assumptions (no order)",
        notes=f"Aggregates: prev=${prev_sum/1e9:.2f}B last=${last_sum/1e9:.2f}B.",
        last_updated=REPORT_DATE,
    )


def _manual_catalysts() -> list[Catalyst]:
    """Catalysts that remain MANUAL — qualitative, private-data, or commodity
    context for which this repo has no clean local source."""
    no_cache = ("Required data not in local cache; supply MANUAL values + "
                "status when authoritative evidence is available. Do not "
                "invent values.")
    return [
        # AI_POWER_INFRA manuals
        make_catalyst(
            catalyst_id="ENER-DATACENTER-POWER-DEMAND-T1", sector=SECTOR,
            subsector=SUBSECTOR_AI,
            catalyst_name="Data-center power demand growth (AI-driven)",
            tier=1, direction="ABOVE",
            threshold=(">15% YoY load growth = BULL; 5..15 NEUTRAL; "
                       "0..5 NEAR; <0 BROKEN"),
            current_value="n/a", status="NEUTRAL", source_type="MANUAL",
            source_detail=("Utility 10-K segment commentary + EIA / ERCOT / "
                           "PJM reports (manual)"),
            action="review AI-power exposure (no order)",
            notes=("This is the headline AI_POWER_INFRA demand thesis; "
                   "individual utility filings carry segment commentary "
                   "but no clean aggregate is in the local cache."),
            last_updated=REPORT_DATE),
        make_catalyst(
            catalyst_id="ENER-NUCLEAR-SMR-T2", sector=SECTOR,
            subsector=SUBSECTOR_AI,
            catalyst_name="Nuclear / SMR progress and orders",
            tier=2, direction="ABOVE",
            threshold=("commercial SMR orders + NRC progress = BULL; "
                       "delays / cancellations = BROKEN"),
            current_value="n/a", status="NEUTRAL", source_type="MANUAL",
            source_detail=("NuScale / X-energy / TerraPower / Holtec / NRC "
                           "announcements (manual; not US SEC filers in "
                           "standard sense)"),
            action="monitor nuclear-baseload exposure (no order)",
            notes=no_cache, last_updated=REPORT_DATE),
        make_catalyst(
            catalyst_id="ENER-REGULATORY-RATECASE-T2", sector=SECTOR,
            subsector=SUBSECTOR_AI,
            catalyst_name="Utility regulatory / rate-case risk",
            tier=2, direction="QUALITATIVE",
            threshold=("constructive rate cases = NEUTRAL; rejected / "
                       "punitive = BROKEN"),
            current_value="n/a", status="NEUTRAL", source_type="MANUAL",
            source_detail=("State PUCs + FERC dockets (manual monitoring; "
                           "see emergency-exit ENER-EXIT-REGULATORY-SHOCK)"),
            action="review regulated-utility exposure",
            notes="Cross-referenced with emergency-exit scenario.",
            last_updated=REPORT_DATE),
        # TRADITIONAL_ENERGY manuals
        make_catalyst(
            catalyst_id="ENER-COMMODITY-OIL-T1", sector=SECTOR,
            subsector=SUBSECTOR_TRAD,
            catalyst_name="WTI / Brent crude oil price regime",
            tier=1, direction="ABOVE",
            threshold=(">$75 BULL; $60..75 NEUTRAL; $50..60 NEAR; <$50 BROKEN"),
            current_value="n/a", status="NEUTRAL", source_type="MANUAL",
            source_detail=("FRED DCOILWTICO / DCOILBRENTEU not in local cache; "
                           "EIA STEO reports also manual"),
            action="review traditional-energy exposure (no order)",
            notes=("FRED commodity series are NOT in the local cache "
                   "(data/macro/fred/ has only DGS10, DGS2, T10Y2Y, FEDFUNDS, "
                   "CPIAUCSL, UNRATE). Adding DCOILWTICO would require a "
                   "separate FRED fetch."),
            last_updated=REPORT_DATE),
        make_catalyst(
            catalyst_id="ENER-LNG-CONTRACTS-T2", sector=SECTOR,
            subsector=SUBSECTOR_TRAD,
            catalyst_name="LNG export contracts + EU/Asia demand",
            tier=2, direction="ABOVE",
            threshold=("rising long-term contracts + tight market = BULL; "
                       "cancellations / oversupply = BROKEN"),
            current_value="n/a", status="NEUTRAL", source_type="MANUAL",
            source_detail=("LNG.com / Cheniere / Venture Global commentary + "
                           "8-K announcements (manual)"),
            action="review LNG / midstream exposure (no order)",
            notes=no_cache, last_updated=REPORT_DATE),
    ]


def _emergency_exits() -> list[EmergencyExit]:
    """Six AI_POWER_INFRA + four TRADITIONAL_ENERGY exit scenarios, all
    MONITORING by default. No values invented; status flipped to TRIGGERED
    only by manual operator action with documented evidence."""
    common = ("research-only: re-evaluate sector sleeve; consider defined-risk "
              "hedges via the existing options layer (separate approval "
              "required); NO order execution")
    return [
        # AI_POWER_INFRA exits (6)
        EmergencyExit(
            exit_id="ENER-EXIT-DATACENTER-CAPEX-CUT", sector=SECTOR,
            scenario=("Big-Tech / hyperscaler capex pullback materially "
                      "reduces data-center power demand"),
            trigger_condition=("Cross-tracker: AI-EXIT-HYPERSCALER-CAPEX-CUT "
                               "triggers, OR AI-HYPERSCALER-CAPEX-T1 falls "
                               "below NEUTRAL band"),
            current_status="MONITORING", action=common,
            source="SEC_EDGAR (hyperscaler 10-Q + earnings — also in AI tracker)",
            last_updated=REPORT_DATE),
        EmergencyExit(
            exit_id="ENER-EXIT-GRID-ORDERS-SLOW", sector=SECTOR,
            scenario=("Grid / electrification equipment order growth "
                      "decelerates sharply"),
            trigger_condition=("ETN / VRT / PWR aggregate revenue YoY revised "
                               "lower across two consecutive prints, OR "
                               "backlog growth halts"),
            current_status="MONITORING", action=common,
            source="SEC_EDGAR (ETN / VRT / PWR 10-Q + 10-K commentary)",
            last_updated=REPORT_DATE),
        EmergencyExit(
            exit_id="ENER-EXIT-UTILITY-LOAD-MISS", sector=SECTOR,
            scenario=("Utility load-growth disappoints vs AI-power forecasts"),
            trigger_condition=("NEE / SO / CEG materially lower load-growth "
                               "guidance, OR ERCOT / PJM forward-curves cut"),
            current_status="MONITORING", action=common,
            source="SEC_EDGAR (utility 10-K commentary) + ERCOT / PJM manual",
            last_updated=REPORT_DATE),
        EmergencyExit(
            exit_id="ENER-EXIT-TURBINE-BACKLOG-DETERIORATE", sector=SECTOR,
            scenario=("Gas-turbine / equipment backlog deteriorates"),
            trigger_condition=("GEV / SIE turbine backlog growth halts or "
                               "reverses; book-to-bill < 1.0 across two prints"),
            current_status="MONITORING", action=common,
            source="MANUAL (GEV 10-Q + Reuters / SIE press releases)",
            last_updated=REPORT_DATE),
        EmergencyExit(
            exit_id="ENER-EXIT-REGULATORY-SHOCK", sector=SECTOR,
            scenario=("Punitive state PUC rate-case decision OR FERC ruling "
                      "compresses utility returns"),
            trigger_condition=("Material adverse final order in a CEG / NEE "
                               "/ SO rate case, OR FERC capacity-market change"),
            current_status="MONITORING", action=common,
            source="MANUAL (PUC / FERC dockets)",
            last_updated=REPORT_DATE),
        EmergencyExit(
            exit_id="ENER-EXIT-AI-POWER-NARRATIVE-REVERSAL", sector=SECTOR,
            scenario=("AI-power demand narrative reverses (multiple "
                      "hyperscalers cite over-build / capacity slack)"),
            trigger_condition=("Two or more of MSFT / GOOGL / AMZN / META "
                               "explicitly cite excess power capacity / "
                               "delayed data-center commissioning"),
            current_status="MONITORING", action=common,
            source=("SEC_EDGAR (hyperscaler 10-Q commentary) + cross-tracker "
                    "AI-EXIT-HYPERSCALER-CAPEX-CUT"),
            last_updated=REPORT_DATE),
        # TRADITIONAL_ENERGY exits (4)
        EmergencyExit(
            exit_id="ENER-EXIT-OIL-DEMAND-SHOCK", sector=SECTOR,
            scenario=("Material oil/gas demand shock (recession or EV "
                      "substitution acceleration)"),
            trigger_condition=("EIA / IEA cuts global oil demand by >1.5 mbd "
                               "across consecutive prints"),
            current_status="MONITORING", action=common,
            source="MANUAL (EIA STEO / IEA reports)",
            last_updated=REPORT_DATE),
        EmergencyExit(
            exit_id="ENER-EXIT-COMMODITY-PRICE-COLLAPSE", sector=SECTOR,
            scenario="WTI / Brent crude price collapses below break-even",
            trigger_condition=("WTI < $50/bbl sustained for >1 quarter, OR "
                               "Brent < $55"),
            current_status="MONITORING", action=common,
            source="MANUAL (FRED DCOILWTICO not in local cache)",
            last_updated=REPORT_DATE),
        EmergencyExit(
            exit_id="ENER-EXIT-CAPEX-DISCIPLINE-BREAK", sector=SECTOR,
            scenario=("Oil major capex discipline visibly breaks (capex rises "
                      "sharply faster than OCF)"),
            trigger_condition=("XOM / CVX / COP capex guide raised materially "
                               "while OCF guide is flat / cut"),
            current_status="MONITORING", action=common,
            source="SEC_EDGAR (XOM/CVX/COP 10-Q + capex disclosures)",
            last_updated=REPORT_DATE),
        EmergencyExit(
            exit_id="ENER-EXIT-DIVIDEND-COVERAGE-STRESS", sector=SECTOR,
            scenario=("Dividend / buyback coverage stress at the integrated "
                      "majors"),
            trigger_condition=("XOM / CVX / COP OCF falls below "
                               "dividend + buyback run-rate for >2 quarters"),
            current_status="MONITORING", action=common,
            source="SEC_EDGAR (XOM/CVX/COP 10-Q OCF + capital-return commentary)",
            last_updated=REPORT_DATE),
    ]


# --------------------------------------------------------------------------- #
# Markdown extras (custom subsector-split section in addition to the V6.1 base)
# --------------------------------------------------------------------------- #
def _subsector_split_section(catalysts: list[Catalyst]) -> str:
    """Group catalysts by subsector and show status counts per group."""
    lines = ["\n## Subsector split (AI_POWER_INFRA vs TRADITIONAL_ENERGY vs MACRO)\n"]
    groups = (SUBSECTOR_AI, SUBSECTOR_TRAD, SUBSECTOR_MACRO)
    for group in groups:
        members = [c for c in catalysts if c.subsector == group]
        if not members:
            continue
        n_bull = sum(1 for c in members if c.status == "BULL")
        n_neutral = sum(1 for c in members if c.status == "NEUTRAL")
        n_near = sum(1 for c in members if c.status == "NEAR_THRESHOLD")
        n_broken = sum(1 for c in members if c.status == "BROKEN")
        n_auto = count_auto_derived(members)
        lines.append(
            f"\n### {group}  —  {len(members)} catalysts "
            f"(auto-derived {n_auto}/{len(members)})\n"
            f"- BULL {n_bull} · NEUTRAL {n_neutral} · NEAR_THRESHOLD "
            f"{n_near} · BROKEN {n_broken}\n"
        )
        lines.append("| catalyst_id | tier | status | current_value | source |")
        lines.append("|---|---|---|---|---|")
        for c in members:
            lines.append(f"| {c.catalyst_id} | {c.tier} | {c.status} | "
                         f"{c.current_value} | {c.source_type} |")
    # Also split emergency exits by their naming-convention prefix.
    return "\n".join(lines) + "\n"


def _next_step_section() -> str:
    return (
        "\n## Next recommended step\n"
        "1. **V6.5 Streamlit dashboard** is now the natural next phase — three "
        "sector trackers (SEMI / AI / ENERGY) are populated with consistent "
        "auto-derived signals, ready to render in a single decision-support "
        "UI. (Note: streamlit is NOT installed; V6.5 requires explicit "
        "approval to add it.)\n"
        "2. **V6.4.1 refinement (optional)** could fetch additional FRED "
        "series (DCOILWTICO, DHHNGSP, DPROPANEMBTX) to auto-derive the "
        "commodity catalysts; segment-level utility load-growth would "
        "require XBRL segment extraction (out of current scope).\n"
        "3. **Do NOT fetch options data** for energy names without an "
        "explicit pre-registered hypothesis (V5.9 discipline).\n"
        "4. The AI-power-infra subsector is structurally coupled to the V6.3 "
        "AI tracker — `AI-EXIT-HYPERSCALER-CAPEX-CUT` is cross-referenced in "
        "`ENER-EXIT-DATACENTER-CAPEX-CUT` and `ENER-EXIT-AI-POWER-NARRATIVE-"
        "REVERSAL`.\n"
    )


def _roadmap_note() -> str:
    return (
        "\n## Future roadmap (NOTE ONLY — not implemented)\n"
        "See `reports/research/sector_tracker/ROADMAP.md` for the full V6.7 / "
        "V6.8 / V6.9 plan (company-level signal ledger, sector aggregation "
        "from company signals, sector-level historical backtest). None of "
        "those phases is implemented; nothing here is tradable.\n"
    )


# --------------------------------------------------------------------------- #
# Orchestrator
# --------------------------------------------------------------------------- #
def build_catalysts() -> list[Catalyst]:
    """Read local data only — no network — and assemble the catalyst list."""
    out: list[Catalyst] = []
    out.extend(_ai_power_revenue_catalysts())
    out.extend(_trad_energy_revenue_catalysts())
    out.append(_oilgas_ocf_catalyst())
    # MACRO (sector-agnostic helper produces ENER-MACRO-* IDs via sector[:4]).
    for c in macro_catalysts(sector=SECTOR, report_date=REPORT_DATE, tier=2):
        # Re-label subsector to "MACRO" for the subsector-split section.
        c = Catalyst(
            catalyst_id=c.catalyst_id, sector=c.sector, subsector=SUBSECTOR_MACRO,
            catalyst_name=c.catalyst_name, tier=c.tier, direction=c.direction,
            threshold=c.threshold, current_value=c.current_value,
            status=c.status, source_type=c.source_type,
            source_detail=c.source_detail, last_updated=c.last_updated,
            action_if_broken=c.action_if_broken, notes=c.notes,
        )
        out.append(c)
    out.extend(_manual_catalysts())
    return out


def main(data_dir: Path | str | None = None,
         report_dir: Path | str | None = None) -> dict[str, Any]:
    assert quantbot.LIVE_TRADING_ENABLED is False, \
        "V6.4 ENERGY driver is RESEARCH only."
    ddir = Path(data_dir) if data_dir else DEFAULT_DATA_DIR
    rdir = Path(report_dir) if report_dir else DEFAULT_REPORT_DIR
    ddir.mkdir(parents=True, exist_ok=True)
    rdir.mkdir(parents=True, exist_ok=True)

    catalysts = build_catalysts()
    exits = _emergency_exits()

    cat_path = save_catalysts(catalysts, ddir / "energy_thesis_tracker.csv")
    ex_path = save_exits(exits, ddir / "energy_emergency_exits.csv")

    report = build_sector_report(SECTOR, catalysts, exits)
    md = render_markdown(report)
    md += f"\n{DISCLAIMER}\n"
    md += _subsector_split_section(catalysts)
    md += autoderived_section(catalysts, version_label="V6.4")
    md += data_gap_section(catalysts)
    md += _next_step_section()
    md += _roadmap_note()
    rpt_path = rdir / "energy_signal.md"
    rpt_path.write_text(md, encoding="utf-8")

    n_auto = count_auto_derived(catalysts)
    n_ai = sum(1 for c in catalysts if c.subsector == SUBSECTOR_AI)
    n_trad = sum(1 for c in catalysts if c.subsector == SUBSECTOR_TRAD)
    n_macro = sum(1 for c in catalysts if c.subsector == SUBSECTOR_MACRO)
    print(f"ENERGY sector signal: {report.score.signal} "
          f"(norm {report.score.normalized_score:+.3f}, "
          f"raw {report.score.raw_score:+.1f} / weight {report.score.total_weight})")
    print(f"  catalysts={len(catalysts)} (BULL {report.score.n_bull}, "
          f"NEUTRAL {report.score.n_neutral}, "
          f"NEAR_THRESHOLD {report.score.n_near_threshold}, "
          f"BROKEN {report.score.n_broken})")
    print(f"  subsectors: AI_POWER_INFRA={n_ai}  TRADITIONAL_ENERGY={n_trad}  "
          f"MACRO={n_macro}")
    print(f"  auto-derived: {n_auto}/{len(catalysts)}; "
          f"manual: {len(catalysts) - n_auto}")
    print(f"  emergency exits MONITORING: "
          f"{sum(1 for e in exits if e.current_status=='MONITORING')}/{len(exits)}  "
          f"triggered={report.score.emergency_triggered}")
    print(f"\nWrote:\n  {cat_path}\n  {ex_path}\n  {rpt_path}")
    return {
        "signal": report.score.signal,
        "normalized_score": report.score.normalized_score,
        "n_catalysts": len(catalysts),
        "n_auto_derived": n_auto,
        "n_exits": len(exits),
        "n_ai_power_infra": n_ai,
        "n_traditional_energy": n_trad,
        "n_macro": n_macro,
        "paths": {"catalysts": str(cat_path), "exits": str(ex_path),
                  "report": str(rpt_path)},
    }


if __name__ == "__main__":
    raise SystemExit(0 if main() else 1)
