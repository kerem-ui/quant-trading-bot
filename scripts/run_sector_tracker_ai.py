"""V6.3 AI / cloud / software-infrastructure sector tracker driver (read-only).

Builds the AI sector dataset using the V6.1 framework and the V6.2.1 reusable
helpers in ``quantbot.research.sector_tracker.driver_utils``. All catalysts
are pre-declared; auto-derived statuses read EXISTING local caches only — NO
network, NO ThetaData, NO live SEC fetch. Catalysts that require data this
repo does not have (private-company ARR, qualitative policy, per-name AI
options) are written as ``source_type=MANUAL`` with status ``NEUTRAL`` and
explicit data-gap notes. **No values are invented.**

Outputs (regenerated deterministically each run):
  data/research/sector_tracker/ai_thesis_tracker.csv
  data/research/sector_tracker/ai_emergency_exits.csv
  reports/research/sector_tracker/ai_signal.md

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
    OPERATING_MARGIN_BANDS_30,
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

# Frozen "as-of" date — auto-derived catalysts stamp this so re-runs are
# byte-identical given a fixed local cache state.
REPORT_DATE = "2026-05-28"
SECTOR = "AI"

# Universe (documentation only; catalysts reference these in notes).
UNIVERSE = ["MSFT", "GOOGL", "AMZN", "META", "ORCL", "PLTR"]

DEFAULT_DATA_DIR = ROOT / "data" / "research" / "sector_tracker"
DEFAULT_REPORT_DIR = ROOT / "reports" / "research" / "sector_tracker"


# --------------------------------------------------------------------------- #
# Sector-specific catalyst builders (auto where data is locally available)
# --------------------------------------------------------------------------- #
def _operating_margin_catalyst(*, ticker: str, catalyst_id: str,
                                subsector: str, tier: int,
                                name: str | None = None) -> Catalyst:
    """OperatingIncomeLoss / Revenue at the latest fresh FYE. Banded by
    :data:`OPERATING_MARGIN_BANDS_30`."""
    label = name or f"{ticker} operating margin"
    threshold = ">=30% BULL; 20..30 NEUTRAL; 10..20 NEAR; <10 BROKEN"
    if not facts_cached(ticker):
        return make_catalyst(
            catalyst_id=catalyst_id, sector=SECTOR, subsector=subsector,
            catalyst_name=label, tier=tier, direction="ABOVE",
            threshold=threshold, current_value="n/a", status="NEUTRAL",
            source_type="MANUAL",
            source_detail=f"SEC:{ticker} companyfacts (NOT cached)",
            action="review thesis (no order)",
            notes=f"Pre-fetch {ticker} SEC to enable.",
            last_updated=REPORT_DATE,
        )
    facts = SEC.fetch_company_facts(ticker)
    _, oi_last, _, oi_end = company_annual_flow_yoy(facts, "operating_income")
    _, rev_last, _, rev_end = company_annual_flow_yoy(facts, "revenue")
    if (oi_last is None or rev_last is None or rev_last == 0
            or not is_fresh(oi_end, report_date=REPORT_DATE)
            or not is_fresh(rev_end, report_date=REPORT_DATE)):
        return make_catalyst(
            catalyst_id=catalyst_id, sector=SECTOR, subsector=subsector,
            catalyst_name=label, tier=tier, direction="ABOVE",
            threshold=threshold, current_value="n/a", status="NEUTRAL",
            source_type="MANUAL",
            source_detail=f"SEC:{ticker} companyfacts (stale or missing)",
            action="review thesis", notes="Stale-data: auto-derive failed.",
            last_updated=REPORT_DATE,
        )
    margin = oi_last / rev_last
    status = bucket_higher_better(margin, OPERATING_MARGIN_BANDS_30)
    fye = pd.Timestamp(min(oi_end, rev_end)).date()
    return make_catalyst(
        catalyst_id=catalyst_id, sector=SECTOR, subsector=subsector,
        catalyst_name=label, tier=tier, direction="ABOVE",
        threshold=threshold, current_value=f"{margin*100:.1f}% (FYE {fye})",
        status=status, source_type="SEC_EDGAR",
        source_detail=f"SEC:{ticker} companyfacts OpInc/Revenue {fye} (auto-derived)",
        action="review thesis",
        notes=f"OpInc=${oi_last/1e9:.2f}B / Revenue=${rev_last/1e9:.2f}B",
        last_updated=REPORT_DATE,
    )


def _hyperscaler_capex_catalyst() -> Catalyst:
    """Aggregate capex YoY across MSFT + GOOGL + META (AMZN excluded by the
    freshness gate — its PaymentsToAcquirePropertyPlantAndEquipment tag stops
    in 2017). This is the headline AI-infrastructure-investment signal."""
    cid = "AI-HYPERSCALER-CAPEX-T1"
    name = "Hyperscaler capex (MSFT+GOOGL+META aggregate YoY)"
    threshold = REV_THRESHOLD_TEXT
    tickers = ("MSFT", "GOOGL", "META")
    prev_sum = last_sum = 0.0
    fye_dates: list[pd.Timestamp] = []
    missing: list[str] = []
    for t in tickers:
        if not facts_cached(t):
            missing.append(t); continue
        prev, last, _, e_last = company_annual_flow_yoy(
            SEC.fetch_company_facts(t), "capex")
        if prev is None or last is None or not is_fresh(e_last, report_date=REPORT_DATE):
            missing.append(t); continue
        prev_sum += prev; last_sum += last
        fye_dates.append(pd.Timestamp(e_last))
    if missing or prev_sum == 0:
        return make_catalyst(
            catalyst_id=cid, sector=SECTOR, subsector="AI_INFRASTRUCTURE",
            catalyst_name=name, tier=1, direction="ABOVE",
            threshold=threshold, current_value="n/a", status="NEUTRAL",
            source_type="MANUAL",
            source_detail=(f"Hyperscaler capex aggregate partial (missing: "
                           f"{','.join(missing) or 'none'})"),
            action="review AI-infrastructure exposure",
            notes=("AMZN capex tag historically stale (stops ~2017) and is "
                   "intentionally excluded from this aggregate."),
            last_updated=REPORT_DATE,
        )
    yoy = yoy_pct(prev_sum, last_sum)
    status = bucket_higher_better(yoy if yoy is not None else 0.0, REV_YOY_BANDS) \
        if yoy is not None else "NEUTRAL"
    latest_fye = max(fye_dates).date()
    return make_catalyst(
        catalyst_id=cid, sector=SECTOR, subsector="AI_INFRASTRUCTURE",
        catalyst_name=name, tier=1, direction="ABOVE", threshold=threshold,
        current_value=(f"{yoy:+.1f}% (latest FYE {latest_fye})"
                       if yoy is not None else "n/a"),
        status=status, source_type="SEC_EDGAR",
        source_detail=(f"SEC:MSFT+GOOGL+META companyfacts capex aggregate "
                       f"(auto-derived; latest FYE {latest_fye})"),
        action="review AI-infrastructure exposure (no order)",
        notes=(f"Aggregates: prev=${prev_sum/1e9:.2f}B last=${last_sum/1e9:.2f}B. "
               "Excludes AMZN (stale capex tag)."),
        last_updated=REPORT_DATE,
    )


def _rd_growth_catalyst() -> Catalyst:
    """Aggregate R&D YoY across MSFT + GOOGL + META + ORCL (AMZN excluded —
    no standard us-gaap R&D tag; PLTR excluded — small base)."""
    cid = "AI-RD-GROWTH-T2"
    name = "R&D growth (MSFT+GOOGL+META+ORCL aggregate YoY)"
    threshold = REV_THRESHOLD_TEXT
    tickers = ("MSFT", "GOOGL", "META", "ORCL")
    prev_sum = last_sum = 0.0
    fye_dates: list[pd.Timestamp] = []
    missing: list[str] = []
    for t in tickers:
        if not facts_cached(t):
            missing.append(t); continue
        prev, last, _, e_last = company_annual_flow_yoy(
            SEC.fetch_company_facts(t), "rd_expense")
        if prev is None or last is None or not is_fresh(e_last, report_date=REPORT_DATE):
            missing.append(t); continue
        prev_sum += prev; last_sum += last
        fye_dates.append(pd.Timestamp(e_last))
    if missing or prev_sum == 0:
        return make_catalyst(
            catalyst_id=cid, sector=SECTOR, subsector="AI_ACCELERATOR",
            catalyst_name=name, tier=2, direction="ABOVE",
            threshold=threshold, current_value="n/a", status="NEUTRAL",
            source_type="MANUAL",
            source_detail=(f"R&D aggregate partial (missing: "
                           f"{','.join(missing) or 'none'})"),
            action="review AI R&D commitment",
            notes=("AMZN R&D not under standard us-gaap; PLTR excluded "
                   "(small absolute base)."),
            last_updated=REPORT_DATE,
        )
    yoy = yoy_pct(prev_sum, last_sum)
    status = bucket_higher_better(yoy if yoy is not None else 0.0, REV_YOY_BANDS) \
        if yoy is not None else "NEUTRAL"
    latest_fye = max(fye_dates).date()
    return make_catalyst(
        catalyst_id=cid, sector=SECTOR, subsector="AI_ACCELERATOR",
        catalyst_name=name, tier=2, direction="ABOVE", threshold=threshold,
        current_value=(f"{yoy:+.1f}% (latest FYE {latest_fye})"
                       if yoy is not None else "n/a"),
        status=status, source_type="SEC_EDGAR",
        source_detail=(f"SEC:MSFT+GOOGL+META+ORCL companyfacts R&D aggregate "
                       f"(auto-derived; latest FYE {latest_fye})"),
        action="review AI R&D commitment (no order)",
        notes=f"Aggregates: prev=${prev_sum/1e9:.2f}B last=${last_sum/1e9:.2f}B.",
        last_updated=REPORT_DATE,
    )


def _manual_catalysts() -> list[Catalyst]:
    """Catalysts that remain MANUAL — private-company ARR, qualitative policy,
    enterprise-adoption evidence, per-name options. No values invented."""
    no_cache_note = (
        "Required data not in local public-company cache. Supply MANUAL values "
        "+ status when authoritative evidence is available. Do not invent values."
    )
    return [
        make_catalyst(
            catalyst_id="AI-OPENAI-ARR-T1", sector=SECTOR,
            subsector="FRONTIER_LAB",
            catalyst_name="OpenAI ARR / funding status",
            tier=1, direction="ABOVE",
            threshold=(">$10B ARR + funded = BULL; $5..10B = NEUTRAL; "
                       "<$5B / funding stress = BROKEN"),
            current_value="n/a", status="NEUTRAL", source_type="MANUAL",
            source_detail=("Private company — no SEC filings; rely on "
                           "operator-curated entries"),
            action="review AI infrastructure thesis (no order)",
            notes=no_cache_note, last_updated=REPORT_DATE),
        make_catalyst(
            catalyst_id="AI-ANTHROPIC-ARR-T1", sector=SECTOR,
            subsector="FRONTIER_LAB",
            catalyst_name="Anthropic ARR / private valuation",
            tier=1, direction="ABOVE",
            threshold="qualitative: rising ARR + funded = BULL; stress = BROKEN",
            current_value="n/a", status="NEUTRAL", source_type="MANUAL",
            source_detail="Private company — no SEC filings",
            action="review AI infrastructure thesis (no order)",
            notes=no_cache_note, last_updated=REPORT_DATE),
        make_catalyst(
            catalyst_id="AI-REGULATION-RISK-T1", sector=SECTOR,
            subsector="GEOPOLITICAL",
            catalyst_name="AI regulation / export-control risk",
            tier=1, direction="QUALITATIVE",
            threshold=("no new material AI/chip rule = NEUTRAL; "
                       "new ban/Section-232/EU AI Act enforcement = BROKEN"),
            current_value="n/a", status="NEUTRAL", source_type="MANUAL",
            source_detail=("BIS / Commerce / EU AI Act / state-level "
                           "announcements (manual monitoring)"),
            action="see emergency-exit AI-EXIT-REGULATION-SHOCK",
            notes=("Tier 1 risk; also tracked as a separate emergency-exit "
                   "scenario."),
            last_updated=REPORT_DATE),
        make_catalyst(
            catalyst_id="AI-MODEL-PRICING-T2", sector=SECTOR,
            subsector="AI_ACCELERATOR",
            catalyst_name="AI model API pricing pressure",
            tier=2, direction="ABOVE",
            threshold=("pricing stable / capacity-led = NEUTRAL; "
                       "sustained > 30% price cuts = BROKEN"),
            current_value="n/a", status="NEUTRAL", source_type="MANUAL",
            source_detail=("OpenAI / Anthropic / GOOGL Gemini / xAI public "
                           "pricing pages (manual tracking)"),
            action="review margin assumptions (no order)",
            notes=no_cache_note, last_updated=REPORT_DATE),
        make_catalyst(
            catalyst_id="AI-ENTERPRISE-ROI-T2", sector=SECTOR,
            subsector="ENTERPRISE_AI",
            catalyst_name="Enterprise AI ROI evidence",
            tier=2, direction="QUALITATIVE",
            threshold=("rising adoption metrics + ROI case studies = BULL; "
                       "broad disillusionment + reversed deployments = BROKEN"),
            current_value="n/a", status="NEUTRAL", source_type="MANUAL",
            source_detail=("Hyperscaler 10-Q / 10-K AI revenue commentary, "
                           "Gartner / IDC adoption reports (manual)"),
            action="review thesis breadth (no order)",
            notes=no_cache_note, last_updated=REPORT_DATE),
        make_catalyst(
            catalyst_id="AI-CUSTOM-SILICON-T2", sector=SECTOR,
            subsector="AI_ACCELERATOR",
            catalyst_name=("Hyperscaler custom silicon displacement of merchant "
                           "accelerators"),
            tier=2, direction="BELOW",
            threshold=("qualitative: accelerating share to TPU/Trainium/Maia "
                       "= BROKEN"),
            current_value="n/a", status="NEUTRAL", source_type="MANUAL",
            source_detail=("MSFT / GOOGL / AMZN 10-K + earnings commentary "
                           "(manual)"),
            action=("review NVDA share assumptions; cross-referenced in semi "
                    "tracker"),
            notes=("Same scenario also tracked in the SEMICONDUCTOR "
                   "tracker (SEMI-CUSTOM-SILICON-T2)."),
            last_updated=REPORT_DATE),
        make_catalyst(
            catalyst_id="AI-OPTIONS-RISK-T2", sector=SECTOR,
            subsector="OPTIONS_MARKET",
            catalyst_name="Options IV-rank / skew / liquidity (AI names)",
            tier=2, direction="QUALITATIVE",
            threshold=("low IV-rank + tight liquidity = NEUTRAL; elevated "
                       "risk = BROKEN"),
            current_value="n/a", status="NEUTRAL",
            source_type="OPTIONS_FEATURE",
            source_detail=("V5.8 features cover SPY only; no per-name AI "
                           "options data in this repo"),
            action=("do not fetch options data without explicit approval "
                    "(V5.9 discipline)"),
            notes=("Per-name AI options pull is out of scope until a "
                   "pre-registered hypothesis."),
            last_updated=REPORT_DATE),
    ]


def _emergency_exits() -> list[EmergencyExit]:
    common_action = (
        "research-only: re-evaluate sector sleeve; consider defined-risk hedges "
        "via the existing options layer (separate approval required); NO order "
        "execution"
    )
    return [
        EmergencyExit(
            exit_id="AI-EXIT-HYPERSCALER-CAPEX-CUT", sector=SECTOR,
            scenario="Big-Tech / hyperscaler capex guide cut materially",
            trigger_condition=(
                "MSFT / GOOGL / AMZN / META aggregate capex guidance YoY "
                "revised LOWER by >=10% across two consecutive prints"
            ),
            current_status="MONITORING", action=common_action,
            source="SEC_EDGAR (hyperscaler 10-Q + earnings commentary)",
            last_updated=REPORT_DATE),
        EmergencyExit(
            exit_id="AI-EXIT-CLOUD-DECEL", sector=SECTOR,
            scenario="Cloud growth decelerates across Azure / AWS / Google Cloud",
            trigger_condition=(
                "Two of {Azure / AWS / Google Cloud} report cloud-segment "
                "growth deceleration QoQ over two consecutive quarters"
            ),
            current_status="MONITORING", action=common_action,
            source="MANUAL (segment data not in standard companyfacts top-level)",
            last_updated=REPORT_DATE),
        EmergencyExit(
            exit_id="AI-EXIT-INFRA-FINANCING-STRESS", sector=SECTOR,
            scenario=("AI infrastructure financing stress or major customer "
                      "renegotiation"),
            trigger_condition=(
                "Material AI compute commitment renegotiated lower OR "
                "publicly reported financing stress at a major lab / hyperscaler"
            ),
            current_status="MONITORING", action=common_action,
            source="MANUAL (press / 8-K disclosures)",
            last_updated=REPORT_DATE),
        EmergencyExit(
            exit_id="AI-EXIT-LAB-SCALING-PULLBACK", sector=SECTOR,
            scenario="Frontier AI lab pulls back on scaling commitments",
            trigger_condition=(
                "OpenAI / Anthropic / GOOGL DeepMind / Meta AI publicly "
                "delay / cancel next-generation training-run plans"
            ),
            current_status="MONITORING", action=common_action,
            source="MANUAL (lab announcements / press)",
            last_updated=REPORT_DATE),
        EmergencyExit(
            exit_id="AI-EXIT-MODEL-PRICING-COLLAPSE", sector=SECTOR,
            scenario="AI model token price erosion accelerates sharply",
            trigger_condition=(
                "Sustained > 50% price cuts across multiple frontier "
                "providers within a quarter"
            ),
            current_status="MONITORING", action=common_action,
            source="MANUAL (public pricing pages, AI-MODEL-PRICING-T2)",
            last_updated=REPORT_DATE),
        EmergencyExit(
            exit_id="AI-EXIT-REGULATION-SHOCK", sector=SECTOR,
            scenario="Major AI regulation / export-control shock",
            trigger_condition=(
                "New material rule (US export controls / EU AI Act enforcement "
                "action / China response) targeting AI accelerators or model "
                "deployment"
            ),
            current_status="MONITORING", action=common_action,
            source="MANUAL (BIS / Commerce / EU / state-level announcements)",
            last_updated=REPORT_DATE),
    ]


def _next_step_section() -> str:
    return (
        "\n## Next recommended step\n"
        "1. **V6.4 Energy / power infrastructure tracker** is the natural next "
        "phase now that the AI driver auto-derives reliably for the major US "
        "AI infrastructure filers.\n"
        "2. **V6.3.1 refinement (optional)** could add: (a) segment-level "
        "cloud growth (Azure / AWS / Google Cloud) — requires XBRL segment "
        "extraction, currently out of scope; (b) OpenAI / Anthropic manual-"
        "entry helpers; (c) AMZN R&D under non-standard tag (`TechnologyAnd"
        "ContentExpense`) — still requires care.\n"
        "3. **Do NOT fetch options data** for AI names without an explicit "
        "pre-registered hypothesis (V5.9 discipline).\n"
        "4. The hyperscaler-capex BULL is the dominant AI-infrastructure "
        "investment signal here; the emergency-exit `AI-EXIT-HYPERSCALER-"
        "CAPEX-CUT` is the most important monitor.\n"
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
    """Read local data only — no network — and assemble the AI catalyst list."""
    out: list[Catalyst] = []
    # Tier 1: hyperscaler / mega-cap AI revenue + AI-infrastructure capex.
    out.append(company_revenue_catalyst(
        ticker="MSFT", sector=SECTOR, catalyst_id="AI-MSFT-REV-T1",
        subsector="HYPERSCALER", tier=1, report_date=REPORT_DATE,
        name="Microsoft revenue YoY"))
    out.append(company_revenue_catalyst(
        ticker="GOOGL", sector=SECTOR, catalyst_id="AI-GOOGL-REV-T1",
        subsector="HYPERSCALER", tier=1, report_date=REPORT_DATE,
        name="Alphabet revenue YoY"))
    out.append(company_revenue_catalyst(
        ticker="AMZN", sector=SECTOR, catalyst_id="AI-AMZN-REV-T1",
        subsector="HYPERSCALER", tier=1, report_date=REPORT_DATE,
        name="Amazon revenue YoY"))
    out.append(company_revenue_catalyst(
        ticker="META", sector=SECTOR, catalyst_id="AI-META-REV-T1",
        subsector="HYPERSCALER", tier=1, report_date=REPORT_DATE,
        name="Meta revenue YoY"))
    out.append(company_revenue_catalyst(
        ticker="ORCL", sector=SECTOR, catalyst_id="AI-ORCL-REV-T1",
        subsector="CLOUD_INFRASTRUCTURE", tier=1, report_date=REPORT_DATE,
        name="Oracle revenue YoY (cloud + Stargate)"))
    out.append(_hyperscaler_capex_catalyst())

    # Tier 2: secondary-cap AI revenue + margins + R&D + macro.
    out.append(company_revenue_catalyst(
        ticker="PLTR", sector=SECTOR, catalyst_id="AI-PLTR-REV-T2",
        subsector="ENTERPRISE_AI", tier=2, report_date=REPORT_DATE,
        name="Palantir revenue YoY"))
    out.append(_operating_margin_catalyst(
        ticker="MSFT", catalyst_id="AI-MSFT-OPMARGIN-T2",
        subsector="HYPERSCALER", tier=2, name="Microsoft operating margin"))
    out.append(_operating_margin_catalyst(
        ticker="GOOGL", catalyst_id="AI-GOOGL-OPMARGIN-T2",
        subsector="HYPERSCALER", tier=2, name="Alphabet operating margin"))
    out.append(_rd_growth_catalyst())
    out.extend(macro_catalysts(sector=SECTOR, report_date=REPORT_DATE, tier=2))

    # MANUAL (private companies, qualitative, options).
    out.extend(_manual_catalysts())
    return out


def main(data_dir: Path | str | None = None,
         report_dir: Path | str | None = None) -> dict[str, Any]:
    assert quantbot.LIVE_TRADING_ENABLED is False, "V6.3 AI driver is RESEARCH only."
    ddir = Path(data_dir) if data_dir else DEFAULT_DATA_DIR
    rdir = Path(report_dir) if report_dir else DEFAULT_REPORT_DIR
    ddir.mkdir(parents=True, exist_ok=True)
    rdir.mkdir(parents=True, exist_ok=True)

    catalysts = build_catalysts()
    exits = _emergency_exits()

    cat_path = save_catalysts(catalysts, ddir / "ai_thesis_tracker.csv")
    ex_path = save_exits(exits, ddir / "ai_emergency_exits.csv")

    report = build_sector_report(SECTOR, catalysts, exits)
    md = render_markdown(report)
    md += f"\n{DISCLAIMER}\n"
    md += autoderived_section(catalysts, version_label="V6.3")
    md += data_gap_section(catalysts)
    md += _next_step_section()
    md += _roadmap_note()
    rpt_path = rdir / "ai_signal.md"
    rpt_path.write_text(md, encoding="utf-8")

    n_auto = count_auto_derived(catalysts)
    print(f"AI sector signal: {report.score.signal} "
          f"(norm {report.score.normalized_score:+.3f}, "
          f"raw {report.score.raw_score:+.1f} / weight {report.score.total_weight})")
    print(f"  catalysts={len(catalysts)} (BULL {report.score.n_bull}, "
          f"NEUTRAL {report.score.n_neutral}, "
          f"NEAR_THRESHOLD {report.score.n_near_threshold}, "
          f"BROKEN {report.score.n_broken})")
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
        "paths": {"catalysts": str(cat_path), "exits": str(ex_path),
                  "report": str(rpt_path)},
    }


if __name__ == "__main__":
    raise SystemExit(0 if main() else 1)
