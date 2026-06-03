"""Shared helpers for per-sector tracker drivers (V6.2.1 / V6.3+).

Pure functions that read EXISTING local caches only — no network, no broker.
Used by:
  * scripts/run_sector_tracker_semi.py   (V6.2 / V6.2.1)
  * scripts/run_sector_tracker_ai.py     (V6.3)
  * and any future per-sector driver

This module is part of the V6.1 framework package but is intentionally a
DRIVER-FACING utility (not part of the schema / scoring / builder contract).
Nothing here imports a broker, IBKR API, or order module. The output of any
driver remains a research signal label only.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ...company import company_facts as CF
from ...company import sec_edgar as SEC
from ...config import project_root
from .schema import Catalyst

# Project root (used to locate local data caches).
ROOT = project_root()


# --------------------------------------------------------------------------- #
# Pre-declared threshold bands (fixed, NOT optimized). Sector drivers reuse
# these for cross-sector consistency. Adding a new band-set requires a separate
# decision (e.g. a sector-specific YoY definition).
# --------------------------------------------------------------------------- #
REV_YOY_BANDS: list[tuple[float, str]] = [
    (20.0, "BULL"),
    (-10.0, "NEUTRAL"),
    (-25.0, "NEAR_THRESHOLD"),
]   # else BROKEN — uses "higher is better" bucket

REV_THRESHOLD_TEXT = (
    "+20% YoY (BULL); -10..+20 NEUTRAL; -25..-10 NEAR; <-25 BROKEN"
)

NI_DELTA_BANDS: list[tuple[float, str]] = [
    (1.0, "BULL"),
    (-1.0, "NEUTRAL"),
    (-5.0, "NEAR_THRESHOLD"),
]   # else BROKEN — net income YoY delta in $B

GROSS_MARGIN_BANDS_72: list[tuple[float, str]] = [
    (0.72, "BULL"),
    (0.65, "NEUTRAL"),
    (0.60, "NEAR_THRESHOLD"),
]   # for high-margin names (NVDA-tier hardware)

OPERATING_MARGIN_BANDS_30: list[tuple[float, str]] = [
    (0.30, "BULL"),
    (0.20, "NEUTRAL"),
    (0.10, "NEAR_THRESHOLD"),
]   # general software / large-cap operating margin band

INVENTORY_YOY_BANDS_LOWER_IS_BETTER: list[tuple[float, str]] = [
    (10.0, "BULL"),
    (30.0, "NEUTRAL"),
    (50.0, "NEAR_THRESHOLD"),
]   # else BROKEN

# Macro
DGS10_BANDS: list[tuple[float, str]] = [
    (4.00, "BULL"),
    (4.50, "NEUTRAL"),
    (5.00, "NEAR_THRESHOLD"),
]   # else BROKEN — lower is better

VIX_BANDS: list[tuple[float, str]] = [
    (18.0, "BULL"),
    (22.0, "NEUTRAL"),
    (30.0, "NEAR_THRESHOLD"),
]   # else BROKEN — lower is better

T10Y2Y_BANDS_HIGHER_IS_BETTER: list[tuple[float, str]] = [
    (0.30, "BULL"),
    (0.0, "NEUTRAL"),
    (-0.30, "NEAR_THRESHOLD"),
]   # else BROKEN — positive curve is good

# Freshness gate: an auto-derived catalyst is only treated as live when the
# underlying observation's fiscal-year-end is within this window of "today".
FRESHNESS_WINDOW_DAYS = 540   # ~18 months


# --------------------------------------------------------------------------- #
# Bucket helpers
# --------------------------------------------------------------------------- #
def bucket_higher_better(value: float, bands: list[tuple[float, str]]) -> str:
    """``value >= cutoff -> label`` (descending bands); else ``"BROKEN"``."""
    for cutoff, label in bands:
        if value >= cutoff:
            return label
    return "BROKEN"


def bucket_lower_better(value: float, bands: list[tuple[float, str]]) -> str:
    """``value <= cutoff -> label`` (ascending bands); else ``"BROKEN"``."""
    for cutoff, label in bands:
        if value <= cutoff:
            return label
    return "BROKEN"


def is_fresh(end_date, *, report_date: str) -> bool:
    """True if ``end_date`` is within :data:`FRESHNESS_WINDOW_DAYS` of
    ``report_date`` (ISO string)."""
    if end_date is None or pd.isna(end_date):
        return False
    delta = (pd.Timestamp(report_date) - pd.Timestamp(end_date)).days
    return 0 <= delta <= FRESHNESS_WINDOW_DAYS


# --------------------------------------------------------------------------- #
# Companyfacts helpers (cache-only)
# --------------------------------------------------------------------------- #
def facts_cached(ticker: str) -> bool:
    """True iff a companyfacts JSON for ``ticker`` exists in the local cache."""
    cik = SEC.ticker_to_cik(ticker)
    if not cik:
        return False
    return (ROOT / "data" / "company" / "sec" / "companyfacts"
            / f"CIK{cik}.json").is_file()


def yoy_pct(prev: float | None, last: float | None) -> float | None:
    if prev is None or last is None or prev == 0:
        return None
    return (last / prev - 1.0) * 100.0


def company_annual_flow_yoy(facts_json: dict | None, field: str) -> tuple[
        float | None, float | None,
        pd.Timestamp | None, pd.Timestamp | None]:
    """Return ``(prev_val, last_val, prev_end, last_end)`` for an annual FLOW
    field (revenue / NI / OCF / GP / etc.) using the period-END convention.

    Uses the V6.2.1 fresh-tag-aware ``extract_company_facts``. Pure function;
    does NO network call.
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


def company_instant_at_end(facts_json: dict | None, field: str,
                            at_end: pd.Timestamp) -> float | None:
    """Return the value of an INSTANT field (balance-sheet item) at ``at_end``.
    ``None`` if not reported at that date."""
    if not facts_json:
        return None
    obs = CF.extract_company_facts(facts_json)
    if obs.empty:
        return None
    cand = obs[(obs["field"] == field) & (obs["end"] == at_end)]
    if cand.empty:
        return None
    return float(cand.sort_values("fy")["val"].iloc[-1])


# --------------------------------------------------------------------------- #
# Macro / market helpers (cache-only)
# --------------------------------------------------------------------------- #
def fred_latest(name: str) -> tuple[float | None, str]:
    """Latest (value, date_iso) from ``data/macro/fred/<name>.csv``."""
    p = ROOT / "data" / "macro" / "fred" / f"{name}.csv"
    if not p.is_file():
        return None, ""
    df = pd.read_csv(p, parse_dates=["date"])
    df = df.dropna(subset=["value"]).sort_values("date")
    if df.empty:
        return None, ""
    last = df.iloc[-1]
    return float(last["value"]), pd.Timestamp(last["date"]).date().isoformat()


def vix_latest() -> tuple[float | None, str]:
    """Latest (close, date_iso) from the cached VIX proxy."""
    p = ROOT / "data" / "macro" / "proxies" / "VIX.csv"
    if not p.is_file():
        return None, ""
    df = pd.read_csv(p, parse_dates=["date"]).set_index("date").sort_index()
    if df.empty or "close" not in df.columns:
        return None, ""
    return float(df["close"].iloc[-1]), df.index[-1].date().isoformat()


# --------------------------------------------------------------------------- #
# Catalyst factories
# --------------------------------------------------------------------------- #
def make_catalyst(*, catalyst_id: str, sector: str, subsector: str,
                  catalyst_name: str, tier: int, direction: str,
                  threshold: str, current_value: str, status: str,
                  source_type: str, source_detail: str, action: str,
                  notes: str = "", last_updated: str) -> Catalyst:
    """Tiny factory that constructs a ``Catalyst`` with the V6.1 schema."""
    return Catalyst(
        catalyst_id=catalyst_id, sector=sector, subsector=subsector,
        catalyst_name=catalyst_name, tier=tier, direction=direction,
        threshold=threshold, current_value=current_value, status=status,
        source_type=source_type, source_detail=source_detail,
        last_updated=last_updated, action_if_broken=action, notes=notes,
    )


def company_revenue_catalyst(
    *, ticker: str, sector: str, catalyst_id: str, subsector: str,
    tier: int, report_date: str, name: str | None = None,
    action: str = "review thesis (no order)",
) -> Catalyst:
    """Build a per-company revenue-YoY catalyst.

    Auto-derived from companyfacts if cached AND the latest fiscal-year-end is
    fresh; otherwise MANUAL / NEUTRAL with an explicit data-gap note. No values
    invented under any branch.
    """
    label = name or f"{ticker} revenue YoY"
    if not facts_cached(ticker):
        return make_catalyst(
            catalyst_id=catalyst_id, sector=sector, subsector=subsector,
            catalyst_name=label, tier=tier, direction="ABOVE",
            threshold=REV_THRESHOLD_TEXT, current_value="n/a",
            status="NEUTRAL", source_type="MANUAL",
            source_detail=f"SEC:{ticker} companyfacts (NOT cached)",
            action=action,
            notes=(f"To enable: run scripts/run_company_research.py {ticker} "
                   "to cache, then re-run this driver."),
            last_updated=report_date,
        )
    facts = SEC.fetch_company_facts(ticker)
    prev, last, e_prev, e_last = company_annual_flow_yoy(facts, "revenue")
    if last is None or prev is None or not is_fresh(e_last, report_date=report_date):
        stale = (f"latest FYE {pd.Timestamp(e_last).date()}"
                 if e_last is not None else "no annual revenue obs")
        return make_catalyst(
            catalyst_id=catalyst_id, sector=sector, subsector=subsector,
            catalyst_name=label, tier=tier, direction="ABOVE",
            threshold=REV_THRESHOLD_TEXT, current_value="n/a",
            status="NEUTRAL", source_type="MANUAL",
            source_detail=f"SEC:{ticker} companyfacts (stale: {stale})",
            action=action,
            notes=("Stale-data: companyfacts revenue tag does not reach the "
                   "freshness window; manual review required."),
            last_updated=report_date,
        )
    yoy = yoy_pct(prev, last)
    status = bucket_higher_better(yoy if yoy is not None else 0.0, REV_YOY_BANDS) \
        if yoy is not None else "NEUTRAL"
    fy_label = f"FY{pd.Timestamp(e_prev).year}->FY{pd.Timestamp(e_last).year}"
    return make_catalyst(
        catalyst_id=catalyst_id, sector=sector, subsector=subsector,
        catalyst_name=label, tier=tier, direction="ABOVE",
        threshold=REV_THRESHOLD_TEXT,
        current_value=(f"{yoy:+.1f}% ({fy_label})" if yoy is not None else "n/a"),
        status=status, source_type="SEC_EDGAR",
        source_detail=f"SEC:{ticker} companyfacts revenue {fy_label} (auto-derived)",
        action=action,
        notes=f"FYE {pd.Timestamp(e_last).date()}",
        last_updated=report_date,
    )


def macro_catalysts(*, sector: str, report_date: str,
                    tier: int = 2) -> list[Catalyst]:
    """Three sector-agnostic macro catalysts (DGS10 / VIX / 2s10s curve)."""
    out: list[Catalyst] = []
    dgs10, dgs10_dt = fred_latest("DGS10")
    if dgs10 is not None:
        out.append(make_catalyst(
            catalyst_id=f"{sector[:4]}-MACRO-RATES-T{tier}",
            sector=sector, subsector="MACRO",
            catalyst_name="Macro regime — long-end rates (DGS10)",
            tier=tier, direction="BELOW",
            threshold="<=4.00 BULL; <=4.50 NEUTRAL; <=5.00 NEAR; >5.00 BROKEN",
            current_value=f"{dgs10:.2f}% ({dgs10_dt})",
            status=bucket_lower_better(dgs10, DGS10_BANDS),
            source_type="FRED", source_detail="FRED:DGS10 (local cache)",
            action="monitor rates",
            notes=f"Tier {tier}: macro amplifier.",
            last_updated=report_date,
        ))
    else:
        out.append(make_catalyst(
            catalyst_id=f"{sector[:4]}-MACRO-RATES-T{tier}",
            sector=sector, subsector="MACRO",
            catalyst_name="Macro regime — long-end rates (DGS10)",
            tier=tier, direction="BELOW",
            threshold="<=4.00 BULL; <=4.50 NEUTRAL; <=5.00 NEAR; >5.00 BROKEN",
            current_value="n/a", status="NEUTRAL",
            source_type="FRED", source_detail="FRED:DGS10 (NOT FOUND)",
            action="monitor rates", notes="FRED DGS10 cache missing.",
            last_updated=report_date,
        ))

    vix, vix_dt = vix_latest()
    if vix is not None:
        out.append(make_catalyst(
            catalyst_id=f"{sector[:4]}-MACRO-VOL-T{tier}",
            sector=sector, subsector="MACRO",
            catalyst_name="Macro regime — equity volatility (VIX)",
            tier=tier, direction="BELOW",
            threshold="<=18 BULL; <=22 NEUTRAL; <=30 NEAR; >30 BROKEN",
            current_value=f"{vix:.2f} ({vix_dt})",
            status=bucket_lower_better(vix, VIX_BANDS),
            source_type="YFINANCE",
            source_detail="VIX proxy (data/macro/proxies/VIX.csv)",
            action="monitor volatility regime",
            notes=f"Tier {tier}: macro amplifier.",
            last_updated=report_date,
        ))
    else:
        out.append(make_catalyst(
            catalyst_id=f"{sector[:4]}-MACRO-VOL-T{tier}",
            sector=sector, subsector="MACRO",
            catalyst_name="Macro regime — equity volatility (VIX)",
            tier=tier, direction="BELOW",
            threshold="<=18 BULL; <=22 NEUTRAL; <=30 NEAR; >30 BROKEN",
            current_value="n/a", status="NEUTRAL",
            source_type="YFINANCE", source_detail="VIX cache (NOT FOUND)",
            action="monitor volatility regime", notes="VIX cache missing.",
            last_updated=report_date,
        ))

    t10y2y, t10y2y_dt = fred_latest("T10Y2Y")
    if t10y2y is not None:
        out.append(make_catalyst(
            catalyst_id=f"{sector[:4]}-MACRO-CURVE-T{tier}",
            sector=sector, subsector="MACRO",
            catalyst_name="Macro regime — 2s10s curve (T10Y2Y)",
            tier=tier, direction="ABOVE",
            threshold=">=+0.30 BULL; >=0 NEUTRAL; >=-0.30 NEAR; <-0.30 BROKEN",
            current_value=f"{t10y2y:+.2f}pp ({t10y2y_dt})",
            status=bucket_higher_better(t10y2y, T10Y2Y_BANDS_HIGHER_IS_BETTER),
            source_type="FRED", source_detail="FRED:T10Y2Y (local cache)",
            action="monitor curve", notes=f"Tier {tier}: macro amplifier.",
            last_updated=report_date,
        ))
    else:
        out.append(make_catalyst(
            catalyst_id=f"{sector[:4]}-MACRO-CURVE-T{tier}",
            sector=sector, subsector="MACRO",
            catalyst_name="Macro regime — 2s10s curve (T10Y2Y)",
            tier=tier, direction="ABOVE",
            threshold=">=+0.30 BULL; >=0 NEUTRAL; >=-0.30 NEAR; <-0.30 BROKEN",
            current_value="n/a", status="NEUTRAL",
            source_type="FRED", source_detail="FRED:T10Y2Y (NOT FOUND)",
            action="monitor curve", notes="FRED T10Y2Y cache missing.",
            last_updated=report_date,
        ))
    return out


# --------------------------------------------------------------------------- #
# Markdown extras
# --------------------------------------------------------------------------- #
DISCLAIMER = (
    "**This is a research signal, not a trading signal, not investment "
    "advice, and not order execution.**"
)


def data_gap_section(catalysts: list[Catalyst]) -> str:
    """Markdown section listing MANUAL or stale catalysts."""
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


def autoderived_section(catalysts: list[Catalyst], *, version_label: str = "") -> str:
    """Markdown section listing the catalysts whose status came from local data."""
    auto = [c for c in catalysts
            if c.source_type in {"SEC_EDGAR", "FRED", "YFINANCE"}
            and "NOT FOUND" not in c.source_detail
            and "stale" not in c.source_detail.lower()]
    header = f"\n## Auto-derived catalysts{f' ({version_label})' if version_label else ''}\n"
    lines = [header]
    if not auto:
        lines.append("_(none)_\n"); return "\n".join(lines)
    lines.append("| catalyst_id | tier | status | current_value | source |")
    lines.append("|---|---|---|---|---|")
    for c in auto:
        lines.append(f"| {c.catalyst_id} | {c.tier} | {c.status} | "
                     f"{c.current_value} | {c.source_type} |")
    return "\n".join(lines)


def count_auto_derived(catalysts: list[Catalyst]) -> int:
    """How many catalysts have a non-MANUAL source AND fresh local data."""
    return sum(
        1 for c in catalysts
        if c.source_type in {"SEC_EDGAR", "FRED", "YFINANCE"}
        and "NOT FOUND" not in c.source_detail
        and "stale" not in c.source_detail.lower()
    )


__all__ = [
    # bands
    "REV_YOY_BANDS", "REV_THRESHOLD_TEXT", "NI_DELTA_BANDS",
    "GROSS_MARGIN_BANDS_72", "OPERATING_MARGIN_BANDS_30",
    "INVENTORY_YOY_BANDS_LOWER_IS_BETTER",
    "DGS10_BANDS", "VIX_BANDS", "T10Y2Y_BANDS_HIGHER_IS_BETTER",
    "FRESHNESS_WINDOW_DAYS",
    # helpers
    "bucket_higher_better", "bucket_lower_better", "is_fresh",
    "facts_cached", "yoy_pct",
    "company_annual_flow_yoy", "company_instant_at_end",
    "fred_latest", "vix_latest",
    # factories
    "make_catalyst", "company_revenue_catalyst", "macro_catalysts",
    # markdown extras
    "DISCLAIMER", "data_gap_section", "autoderived_section",
    "count_auto_derived",
]
