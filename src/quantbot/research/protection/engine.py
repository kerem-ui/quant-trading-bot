"""V7.7 Protection engine — pure derivation, no I/O.

Composes the V7.1 portfolio positions with the V6.1 canonical sector
signals, V6.7 company ledger, and V6.8 company-derived sector aggregation
into per-position :class:`ProtectionRow` snapshots.

All rules are categorical and pre-declared. There is **no hidden numeric
scoring** beyond a single position-weight threshold (a concentration
guard, not a signal). The output is research-only.

Per-axis labels are computed independently — concentration on the
position-weight axis, sector_risk on the canonical V6.1 signal axis,
company_risk on the V6.7 ledger axis. The headline ``protection_label``
is then the worst-real-risk label across those three.

Headline priority (highest-priority = headline wins):

  1. ``SECTOR_AT_RISK`` (canonical REDUCE / EXIT_WATCH)
  2. ``CONCENTRATION`` (weight ≥ ``CONCENTRATION_THRESHOLD_PCT``)
  3. ``SHARED_RISK_EXPOSED`` (company read BROKEN)
  4. ``WATCH`` (MIXED / NEAR_THRESHOLD ledger read, OR canonical positive
     paired with cautious company-derived read, OR weight in the
     ``WATCH_CONCENTRATION_THRESHOLD_PCT`` band, OR AVOID_NEW_BUY)
  5. ``DATA_GAP`` (no real risk detected and at least one axis is
     missing required input)
  6. ``OK`` (every axis returned OK or no risk-worth-surfacing was found)

The reason ``DATA_GAP`` sits BELOW the real risk labels: when one axis
is missing data but a different axis already shows a real risk, the
operator's actionable view is the real risk — not "your data is
incomplete". The per-axis ``*_label`` fields preserve the gap so a
caller can still surface it.
"""

from __future__ import annotations

from typing import Mapping

from ..sector_tracker.company_aggregation import SectorAggregationRow
from ..sector_tracker.company_ledger import CompanyLedgerRow
from ..sector_tracker.sector_signal_log import SectorSignalLogRow
from ..portfolio.schema import PositionRow
from .schema import ALLOWED_PROTECTION_LABEL, ProtectionRow

# --------------------------------------------------------------------------- #
# Pre-declared thresholds + priorities
# --------------------------------------------------------------------------- #
# Concentration guard — strictly position-weight-based; not a signal.
CONCENTRATION_THRESHOLD_PCT: float = 25.0
WATCH_CONCENTRATION_THRESHOLD_PCT: float = 15.0

# Headline priority — real risks first; DATA_GAP only beats OK so a real
# risk on another axis always wins the headline.
LABEL_PRIORITY: tuple[str, ...] = (
    "SECTOR_AT_RISK",
    "CONCENTRATION",
    "SHARED_RISK_EXPOSED",
    "WATCH",
    "DATA_GAP",
    "OK",
)

_NEGATIVE_CANONICAL_SIGNALS: frozenset[str] = frozenset({
    "REDUCE", "EXIT_WATCH",
})
_POSITIVE_CANONICAL_SIGNALS: frozenset[str] = frozenset({
    "ACCUMULATE", "SELECTIVE_BUY",
})
_CAUTIOUS_CANONICAL_SIGNALS: frozenset[str] = frozenset({
    "AVOID_NEW_BUY",
})


def worst_label(*labels: str) -> str:
    """Return the worst-bucket label per :data:`LABEL_PRIORITY`.

    Unknown labels fall back to ``"DATA_GAP"`` defensively. Empty input
    returns ``"OK"`` so the engine never emits an undefined label.
    """
    if not labels:
        return "OK"
    rank = {lbl: i for i, lbl in enumerate(LABEL_PRIORITY)}
    worst = "OK"
    worst_rank = rank[worst]
    for lbl in labels:
        if lbl not in ALLOWED_PROTECTION_LABEL:
            lbl = "DATA_GAP"
        if rank[lbl] < worst_rank:
            worst = lbl
            worst_rank = rank[lbl]
    return worst


def _try_parse_float(s: str) -> float | None:
    """Best-effort string→float (commas / ``$`` / ``%`` tolerated). None
    when empty or unparseable. Never raises."""
    if s is None:
        return None
    txt = str(s).strip()
    if not txt:
        return None
    cleaned = txt.replace(",", "").replace("$", "").replace("%", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def _classify_concentration(
    weight_pct: float | None,
    *,
    concentration_threshold: float = CONCENTRATION_THRESHOLD_PCT,
    watch_threshold: float = WATCH_CONCENTRATION_THRESHOLD_PCT,
) -> str:
    if weight_pct is None:
        return "DATA_GAP"
    if weight_pct >= concentration_threshold:
        return "CONCENTRATION"
    if weight_pct >= watch_threshold:
        return "WATCH"
    return "OK"


def _classify_sector_risk(
    canonical_signal: str,
    company_derived_read: str,
) -> str:
    if not canonical_signal:
        return "DATA_GAP"
    if canonical_signal in _NEGATIVE_CANONICAL_SIGNALS:
        return "SECTOR_AT_RISK"
    if canonical_signal in _CAUTIOUS_CANONICAL_SIGNALS:
        return "WATCH"
    # Canonical positive but the company-derived read is cautious.
    if canonical_signal in _POSITIVE_CANONICAL_SIGNALS and \
            company_derived_read in {"CAUTION", "BROKEN"}:
        return "WATCH"
    return "OK"


def _classify_company_risk(company_read: str) -> str:
    if not company_read or company_read == "N/A":
        return "DATA_GAP"
    if company_read == "BROKEN":
        return "SHARED_RISK_EXPOSED"
    if company_read in {"MIXED", "NEAR_THRESHOLD"}:
        return "WATCH"
    # BULL / NEUTRAL / TRACKED are all "OK" for protection purposes.
    return "OK"


def _compose_why(
    *,
    concentration_label: str,
    sector_risk_label: str,
    company_risk_label: str,
    weight_pct: float | None,
    canonical_signal: str,
    company_read: str,
    company_derived_read: str,
) -> str:
    parts: list[str] = []
    if concentration_label == "CONCENTRATION" and weight_pct is not None:
        parts.append(
            f"weight {weight_pct:.1f}% ≥ "
            f"{CONCENTRATION_THRESHOLD_PCT:.0f}% concentration threshold"
        )
    elif concentration_label == "WATCH" and weight_pct is not None:
        parts.append(
            f"weight {weight_pct:.1f}% in watch band "
            f"({WATCH_CONCENTRATION_THRESHOLD_PCT:.0f}–"
            f"{CONCENTRATION_THRESHOLD_PCT:.0f}%)"
        )
    if sector_risk_label == "SECTOR_AT_RISK":
        parts.append(f"canonical sector signal {canonical_signal}")
    elif sector_risk_label == "WATCH":
        if canonical_signal in _CAUTIOUS_CANONICAL_SIGNALS:
            parts.append(f"canonical sector signal {canonical_signal}")
        elif company_derived_read in {"CAUTION", "BROKEN"}:
            parts.append(
                f"canonical sector signal {canonical_signal} but "
                f"company roll-up more cautious "
                f"(company-derived {company_derived_read})"
            )
    if company_risk_label == "SHARED_RISK_EXPOSED":
        parts.append(f"company read {company_read} — shared sector risk")
    elif company_risk_label == "WATCH":
        parts.append(f"company read {company_read}")
    if not parts:
        return "no risk flags active"
    return "; ".join(parts)


def _compose_action(
    protection_label: str,
    *,
    canonical_signal: str = "",
    company_read: str = "",
) -> str:
    """Categorical, pre-declared action prompt — NEVER an order suggestion.

    Wording is deliberately advisory and review-oriented; the operator is
    the only decision-maker. No execution path lives in this module.
    """
    if protection_label == "OK":
        return "—"
    if protection_label == "WATCH":
        return "monitor; re-read at next refresh"
    if protection_label == "CONCENTRATION":
        return "review position sizing"
    if protection_label == "SECTOR_AT_RISK":
        return "review sector exposure"
    if protection_label == "SHARED_RISK_EXPOSED":
        return "review thesis vs shared sector risk"
    if protection_label == "DATA_GAP":
        return "populate missing inputs to enable a read"
    return "—"


def derive_protection_rows(
    positions: list[PositionRow],
    *,
    company_ledger_by_ticker: Mapping[str, CompanyLedgerRow] | None = None,
    sector_signals_by_sector: Mapping[str, SectorSignalLogRow] | None = None,
    company_aggregations_by_sector: Mapping[
        str, SectorAggregationRow
    ] | None = None,
    as_of: str = "",
    concentration_threshold_pct: float = CONCENTRATION_THRESHOLD_PCT,
    watch_threshold_pct: float = WATCH_CONCENTRATION_THRESHOLD_PCT,
) -> list[ProtectionRow]:
    """Compose one :class:`ProtectionRow` per non-cash position.

    PURE. No I/O. Cash positions (``asset_type == "CASH"``) are excluded
    so concentration weights reflect the *investable* book.

    All four label fields are categorical. The headline
    ``protection_label`` is the worst-bucket label across the three
    constituents, ranked by :data:`LABEL_PRIORITY`.
    """
    ledger = dict(company_ledger_by_ticker or {})
    signals = dict(sector_signals_by_sector or {})
    aggregations = dict(company_aggregations_by_sector or {})

    investable = [p for p in positions if p.asset_type != "CASH"]
    market_values = [_try_parse_float(p.market_value) for p in investable]

    if any(v is None for v in market_values):
        total_mv: float | None = None
    else:
        total = sum(market_values)
        total_mv = total if total > 0 else None

    out: list[ProtectionRow] = []
    for pos, mv in zip(investable, market_values):
        weight = (mv / total_mv * 100.0) if (mv is not None
                                              and total_mv is not None) else None
        weight_str = f"{weight:.2f}" if weight is not None else ""

        canonical_signal = ""
        company_derived_read = ""
        ssr = signals.get(pos.sector)
        if ssr is not None:
            canonical_signal = ssr.canonical_signal
        agg = aggregations.get(pos.sector)
        if agg is not None:
            company_derived_read = agg.company_derived_read

        ledger_row = ledger.get(pos.ticker)
        company_read = ledger_row.read if ledger_row is not None else ""

        concentration_label = _classify_concentration(
            weight,
            concentration_threshold=concentration_threshold_pct,
            watch_threshold=watch_threshold_pct,
        )
        sector_risk_label = _classify_sector_risk(
            canonical_signal, company_derived_read,
        )
        company_risk_label = _classify_company_risk(company_read)
        protection_label = worst_label(
            concentration_label, sector_risk_label, company_risk_label,
        )

        why_short = _compose_why(
            concentration_label=concentration_label,
            sector_risk_label=sector_risk_label,
            company_risk_label=company_risk_label,
            weight_pct=weight,
            canonical_signal=canonical_signal,
            company_read=company_read,
            company_derived_read=company_derived_read,
        )
        action_short = _compose_action(
            protection_label,
            canonical_signal=canonical_signal,
            company_read=company_read,
        )

        out.append(ProtectionRow(
            as_of=as_of or pos.as_of,
            ticker=pos.ticker,
            sector=pos.sector,
            theme=pos.theme,
            market_value=pos.market_value,
            portfolio_weight_pct=weight_str,
            company_read=company_read,
            canonical_sector_signal=canonical_signal,
            company_derived_sector_read=company_derived_read,
            concentration_label=concentration_label,
            sector_risk_label=sector_risk_label,
            company_risk_label=company_risk_label,
            protection_label=protection_label,
            why_short=why_short,
            action_short=action_short,
        ))
    return out


__all__ = [
    "CONCENTRATION_THRESHOLD_PCT",
    "WATCH_CONCENTRATION_THRESHOLD_PCT",
    "LABEL_PRIORITY",
    "worst_label",
    "derive_protection_rows",
]
