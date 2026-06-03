"""V7.4 PortTech engine — pure derivation, no I/O.

Composes the V7.1 portfolio positions with the V6.1 canonical sector
signals (via V6.6.2 log), V6.7 company ledger, V6.8 company-derived sector
aggregation, and the optional V7.7 protection labels into per-position
:class:`PortTechRow` snapshots.

All rules are **categorical and pre-declared**. There is no hidden numeric
scoring beyond a single position-weight concentration cap (the same
threshold the V7.7 engine uses). The output is research-only.

Derivation is a four-step pipeline applied per position:

  1. **Base recommendation** — a pre-declared lookup table keyed on
     ``(company_read, canonical_sector_signal)``.
  2. **Caution modifier** — if base is ``ADD`` and the company-derived
     sector read is ``CAUTION`` / ``BROKEN``, downgrade to ``HOLD``.
  3. **Concentration cap** — if portfolio weight ≥
     :data:`CONCENTRATION_CAP_PCT`, cap ``ADD`` to ``HOLD``. Lower labels
     are not changed.
  4. **Protection override** — if the V7.7 ``protection_label`` is
     ``SECTOR_AT_RISK`` / ``SHARED_RISK_EXPOSED`` / ``CONCENTRATION`` /
     ``WATCH``, downgrade the candidate accordingly. Pre-declared mapping.

If any required input is missing (position weight, canonical signal,
company read), the row's headline becomes ``DATA_GAP`` and the
``data_gap_note`` field explains which axes were absent.

No broker, no IBKR, no live feed, no order. ``LIVE_TRADING_ENABLED`` stays
``False``.
"""

from __future__ import annotations

from typing import Mapping

from ..portfolio.schema import PositionRow
from ..protection.schema import ProtectionRow
from ..sector_tracker.company_aggregation import SectorAggregationRow
from ..sector_tracker.company_ledger import CompanyLedgerRow
from ..sector_tracker.sector_signal_log import SectorSignalLogRow
from .schema import ALLOWED_PORTTECH_LABEL, PortTechRow

# --------------------------------------------------------------------------- #
# Pre-declared thresholds + priority
# --------------------------------------------------------------------------- #
CONCENTRATION_CAP_PCT: float = 25.0

# Headline priority (worst-first). Used internally for protection-override
# downgrades and exposed for tests / future callers.
LABEL_PRIORITY: tuple[str, ...] = (
    "EXIT_WATCH",
    "TRIM",
    "WATCH",
    "HOLD",
    "ADD",
    "DATA_GAP",
)

_CAUTIOUS_AGG_READS: frozenset[str] = frozenset({"CAUTION", "BROKEN"})

# --------------------------------------------------------------------------- #
# Pre-declared base recommendation lookup.
# Rows are company_read; columns are canonical_sector_signal. Any
# combination not present here lands the row in DATA_GAP.
# --------------------------------------------------------------------------- #
BASE_RECOMMENDATION: dict[tuple[str, str], str] = {
    # BULL company read
    ("BULL", "ACCUMULATE"):    "ADD",
    ("BULL", "SELECTIVE_BUY"): "ADD",
    ("BULL", "HOLD"):           "HOLD",
    ("BULL", "AVOID_NEW_BUY"): "WATCH",
    ("BULL", "REDUCE"):         "TRIM",
    ("BULL", "EXIT_WATCH"):     "EXIT_WATCH",
    # NEUTRAL company read (in-band fundamentals)
    ("NEUTRAL", "ACCUMULATE"):    "HOLD",
    ("NEUTRAL", "SELECTIVE_BUY"): "HOLD",
    ("NEUTRAL", "HOLD"):           "HOLD",
    ("NEUTRAL", "AVOID_NEW_BUY"): "WATCH",
    ("NEUTRAL", "REDUCE"):         "TRIM",
    ("NEUTRAL", "EXIT_WATCH"):     "EXIT_WATCH",
    # MIXED company read — never aggressive ADD per the V7.4 spec.
    ("MIXED", "ACCUMULATE"):    "WATCH",
    ("MIXED", "SELECTIVE_BUY"): "WATCH",
    ("MIXED", "HOLD"):           "WATCH",
    ("MIXED", "AVOID_NEW_BUY"): "WATCH",
    ("MIXED", "REDUCE"):         "TRIM",
    ("MIXED", "EXIT_WATCH"):     "EXIT_WATCH",
    # NEAR_THRESHOLD — close to BROKEN; treat like MIXED.
    ("NEAR_THRESHOLD", "ACCUMULATE"):    "WATCH",
    ("NEAR_THRESHOLD", "SELECTIVE_BUY"): "WATCH",
    ("NEAR_THRESHOLD", "HOLD"):           "WATCH",
    ("NEAR_THRESHOLD", "AVOID_NEW_BUY"): "WATCH",
    ("NEAR_THRESHOLD", "REDUCE"):         "TRIM",
    ("NEAR_THRESHOLD", "EXIT_WATCH"):     "EXIT_WATCH",
    # BROKEN company read — thesis already broken.
    ("BROKEN", "ACCUMULATE"):    "TRIM",
    ("BROKEN", "SELECTIVE_BUY"): "TRIM",
    ("BROKEN", "HOLD"):           "TRIM",
    ("BROKEN", "AVOID_NEW_BUY"): "TRIM",
    ("BROKEN", "REDUCE"):         "EXIT_WATCH",
    ("BROKEN", "EXIT_WATCH"):     "EXIT_WATCH",
    # TRACKED — manual placeholder; conservative HOLD by default.
    ("TRACKED", "ACCUMULATE"):    "HOLD",
    ("TRACKED", "SELECTIVE_BUY"): "HOLD",
    ("TRACKED", "HOLD"):           "HOLD",
    ("TRACKED", "AVOID_NEW_BUY"): "HOLD",
    ("TRACKED", "REDUCE"):         "WATCH",
    ("TRACKED", "EXIT_WATCH"):     "WATCH",
}


# --------------------------------------------------------------------------- #
# Pure helpers (testable in isolation)
# --------------------------------------------------------------------------- #
def _try_parse_float(s: str) -> float | None:
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


def _base_recommendation(
    company_read: str, canonical_sector_signal: str,
) -> str | None:
    """Return the pre-declared base recommendation or ``None`` if unknown."""
    return BASE_RECOMMENDATION.get((company_read, canonical_sector_signal))


def _apply_caution_modifier(
    label: str, company_derived_read: str,
) -> str:
    """If base is ``ADD`` and the company-derived sector read is cautious,
    downgrade to ``HOLD``. Mirrors the V6.5.2 / V7.4 spec rule."""
    if label == "ADD" and company_derived_read in _CAUTIOUS_AGG_READS:
        return "HOLD"
    return label


def _apply_concentration_cap(
    label: str, weight_pct: float | None,
    threshold: float = CONCENTRATION_CAP_PCT,
) -> str:
    """If weight ≥ threshold, cap ``ADD`` at ``HOLD``."""
    if weight_pct is None:
        return label
    if weight_pct >= threshold and label == "ADD":
        return "HOLD"
    return label


def _apply_protection_override(
    label: str, protection_label: str,
) -> str:
    """Downgrade ``label`` per the V7.7 protection signal.

    Pre-declared per-pair mapping so the override behaviour is auditable
    by inspection of a single table.
    """
    if not protection_label:
        return label
    # Per-protection downgrade rules. Worse protection signals downgrade
    # candidate labels more aggressively. A "stay" entry means no change.
    rules: dict[tuple[str, str], str] = {
        # SECTOR_AT_RISK — canonical REDUCE / EXIT_WATCH already pulled the
        # base toward TRIM / EXIT_WATCH, but if base is still positive due
        # to mismatched data we force WATCH at minimum.
        ("SECTOR_AT_RISK", "ADD"):   "WATCH",
        ("SECTOR_AT_RISK", "HOLD"):  "WATCH",
        # SHARED_RISK_EXPOSED — company read is BROKEN. Base should already
        # be TRIM/EXIT_WATCH, but if the lookup landed elsewhere (e.g. due
        # to upstream override) push toward TRIM.
        ("SHARED_RISK_EXPOSED", "ADD"):  "TRIM",
        ("SHARED_RISK_EXPOSED", "HOLD"): "WATCH",
        # CONCENTRATION — keep ADD at HOLD (mirrors the explicit cap above).
        ("CONCENTRATION", "ADD"):  "HOLD",
        # WATCH protection — concentration watch band or AVOID_NEW_BUY;
        # downgrade ADD to HOLD.
        ("WATCH", "ADD"): "HOLD",
    }
    return rules.get((protection_label, label), label)


def _compose_why(
    *,
    label: str,
    company_read: str,
    canonical_sector_signal: str,
    company_derived_read: str,
    protection_label: str,
    weight_pct: float | None,
    base_label: str,
) -> str:
    """Plain-English explanation of which signals produced ``label``."""
    parts: list[str] = []

    # Headline reasons depend on label.
    if label == "ADD":
        parts.append(
            f"company {company_read} + canonical {canonical_sector_signal}"
        )
    elif label == "HOLD":
        if base_label == "ADD" and company_derived_read in _CAUTIOUS_AGG_READS:
            parts.append(
                f"company {company_read} + canonical "
                f"{canonical_sector_signal} but company roll-up "
                f"{company_derived_read} caps to HOLD"
            )
        elif base_label == "ADD" and weight_pct is not None and \
                weight_pct >= CONCENTRATION_CAP_PCT:
            parts.append(
                f"weight {weight_pct:.1f}% ≥ "
                f"{CONCENTRATION_CAP_PCT:.0f}% caps ADD to HOLD"
            )
        else:
            parts.append(
                f"company {company_read} + canonical {canonical_sector_signal}"
            )
    elif label == "WATCH":
        if protection_label == "SECTOR_AT_RISK":
            parts.append(
                f"sector-at-risk override (canonical {canonical_sector_signal})"
            )
        else:
            parts.append(
                f"company {company_read} + canonical {canonical_sector_signal}"
            )
    elif label == "TRIM":
        parts.append(
            f"company {company_read} + canonical {canonical_sector_signal}"
        )
    elif label == "EXIT_WATCH":
        parts.append(
            f"company {company_read} + canonical {canonical_sector_signal}"
        )
    elif label == "DATA_GAP":
        # Caller provides data_gap_note; why_short stays short here.
        return "missing inputs — see data_gap_note"

    if protection_label and protection_label not in {"OK", ""}:
        parts.append(f"protection {protection_label}")
    return "; ".join(parts) if parts else f"label {label}"


def _compose_action(label: str) -> str:
    """Pre-declared advisory action prompt. **Never** an order
    instruction — phrased as a research review prompt."""
    return {
        "ADD":         "research-only — fundamentals constructive",
        "HOLD":         "research-only — current weighting reasonable",
        "TRIM":         "research-only — review thesis vs. weighting",
        "WATCH":        "research-only — monitor for further signal",
        "EXIT_WATCH":   "research-only — review thesis urgently",
        "DATA_GAP":     "populate missing inputs to enable a read",
    }.get(label, "—")


def _missing_inputs_note(
    *, weight_pct: float | None,
    canonical_sector_signal: str,
    company_read: str,
) -> str:
    missing: list[str] = []
    if weight_pct is None:
        missing.append("portfolio weight (unparseable market_value)")
    if not canonical_sector_signal:
        missing.append("canonical sector signal")
    if not company_read or company_read == "N/A":
        missing.append("company ledger read")
    if not missing:
        return ""
    return "missing: " + ", ".join(missing)


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
def derive_porttech_rows(
    positions: list[PositionRow],
    *,
    company_ledger_by_ticker: Mapping[str, CompanyLedgerRow] | None = None,
    sector_signals_by_sector: Mapping[str, SectorSignalLogRow] | None = None,
    company_aggregations_by_sector: Mapping[
        str, SectorAggregationRow
    ] | None = None,
    protection_rows_by_ticker: Mapping[str, ProtectionRow] | None = None,
    as_of: str = "",
    concentration_cap_pct: float = CONCENTRATION_CAP_PCT,
) -> list[PortTechRow]:
    """Compose one :class:`PortTechRow` per non-cash position.

    PURE. No I/O. Cash positions (``asset_type == "CASH"``) are excluded.

    Required inputs per row to avoid ``DATA_GAP``:
      * parseable ``market_value`` (so weight can be computed)
      * a canonical sector signal (V6.6.2 log row)
      * a company ledger read (V6.7)

    Optional inputs:
      * company-derived aggregation read (V6.8) — drives caution modifier
      * V7.7 protection label — drives the protection override
    """
    ledger = dict(company_ledger_by_ticker or {})
    signals = dict(sector_signals_by_sector or {})
    aggregations = dict(company_aggregations_by_sector or {})
    protection = dict(protection_rows_by_ticker or {})

    investable = [p for p in positions if p.asset_type != "CASH"]
    market_values = [_try_parse_float(p.market_value) for p in investable]

    if any(v is None for v in market_values):
        total_mv: float | None = None
    else:
        total = sum(market_values)
        total_mv = total if total > 0 else None

    out: list[PortTechRow] = []
    for pos, mv in zip(investable, market_values):
        weight = (mv / total_mv * 100.0) if (mv is not None
                                              and total_mv is not None) else None
        weight_str = f"{weight:.2f}" if weight is not None else ""

        ssr = signals.get(pos.sector)
        canonical_signal = ssr.canonical_signal if ssr is not None else ""

        agg = aggregations.get(pos.sector)
        company_derived_read = (
            agg.company_derived_read if agg is not None else ""
        )

        ledger_row = ledger.get(pos.ticker)
        company_read = ledger_row.read if ledger_row is not None else ""

        prot_row = protection.get(pos.ticker)
        protection_label = (
            prot_row.protection_label if prot_row is not None else ""
        )

        gap_note = _missing_inputs_note(
            weight_pct=weight,
            canonical_sector_signal=canonical_signal,
            company_read=company_read,
        )

        if gap_note:
            label = "DATA_GAP"
            base_label = "DATA_GAP"
        else:
            base_label = _base_recommendation(
                company_read, canonical_signal,
            )
            if base_label is None:
                # Should not happen given the full lookup, but if a future
                # status appears we surface the gap defensively.
                label = "DATA_GAP"
                gap_note = (
                    f"unknown (company_read={company_read!r}, "
                    f"canonical={canonical_signal!r})"
                )
                base_label = "DATA_GAP"
            else:
                label = _apply_caution_modifier(
                    base_label, company_derived_read,
                )
                label = _apply_concentration_cap(
                    label, weight, threshold=concentration_cap_pct,
                )
                label = _apply_protection_override(
                    label, protection_label,
                )

        if label not in ALLOWED_PORTTECH_LABEL:
            # Defence-in-depth: pipeline must never yield an out-of-enum
            # value. If it ever does, fail loud at the dataclass.
            label = "DATA_GAP"

        why = _compose_why(
            label=label,
            company_read=company_read,
            canonical_sector_signal=canonical_signal,
            company_derived_read=company_derived_read,
            protection_label=protection_label,
            weight_pct=weight,
            base_label=base_label,
        )
        action = _compose_action(label)

        out.append(PortTechRow(
            as_of=as_of or pos.as_of,
            ticker=pos.ticker,
            sector=pos.sector,
            theme=pos.theme,
            market_value=pos.market_value,
            portfolio_weight_pct=weight_str,
            company_read=company_read,
            canonical_sector_signal=canonical_signal,
            company_derived_sector_read=company_derived_read,
            protection_label=protection_label,
            porttech_label=label,
            why_short=why,
            action_short=action,
            data_gap_note=gap_note,
        ))
    return out


__all__ = [
    "BASE_RECOMMENDATION",
    "CONCENTRATION_CAP_PCT",
    "LABEL_PRIORITY",
    "derive_porttech_rows",
]
