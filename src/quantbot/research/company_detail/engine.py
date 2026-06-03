"""V7.5 Company Detail engine — pure derivation, no I/O.

Single public entry point: :func:`build_company_detail_view`. Takes every
upstream surface as a typed argument and returns one
:class:`CompanyDetailView`. The platform adapter wires the on-disk
loaders into this; tests inject hand-crafted fixtures.

No I/O, no scoring, no network. ``quantbot.LIVE_TRADING_ENABLED`` stays
``False``.
"""

from __future__ import annotations

from typing import Iterable

from ..portfolio.schema import PositionRow
from ..porttech.schema import PortTechRow
from ..protection.schema import ProtectionRow
from ..sector_tracker.change_log import Change, EventAnnotation
from ..sector_tracker.company_aggregation import SectorAggregationRow
from ..sector_tracker.company_ledger import CompanyLedgerRow
from ..sector_tracker.schema import Catalyst
from ..sector_tracker.sector_signal_log import SectorSignalLogRow
from .schema import CompanyDetailView

# --------------------------------------------------------------------------- #
# Pure helpers
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


def ticker_universe(
    company_ledger_rows: Iterable[CompanyLedgerRow] | None = None,
    positions: Iterable[PositionRow] | None = None,
) -> list[str]:
    """Return sorted unique tickers across ledger and (non-cash) positions.

    Used by the page's ticker selector. Empty inputs yield an empty list.
    """
    tickers: set[str] = set()
    for r in (company_ledger_rows or []):
        if r.ticker:
            tickers.add(r.ticker)
    for p in (positions or []):
        if p.asset_type == "CASH":
            continue
        if p.ticker:
            tickers.add(p.ticker)
    return sorted(tickers)


def _latest_ledger_row_for_ticker(
    rows: list[CompanyLedgerRow], ticker: str,
) -> CompanyLedgerRow | None:
    """Most-recent ledger row for ``ticker`` across all run_ids."""
    candidates = [r for r in rows if r.ticker == ticker]
    if not candidates:
        return None
    candidates.sort(key=lambda r: r.run_id, reverse=True)
    return candidates[0]


def _historical_ledger_rows_for_ticker(
    rows: list[CompanyLedgerRow], ticker: str,
) -> list[CompanyLedgerRow]:
    """All ledger rows for ``ticker``, newest first (descending run_id)."""
    matches = [r for r in rows if r.ticker == ticker]
    matches.sort(key=lambda r: r.run_id, reverse=True)
    return matches


def _latest_signal_for_sector(
    rows: list[SectorSignalLogRow], sector: str,
) -> SectorSignalLogRow | None:
    candidates = [r for r in rows if r.sector == sector]
    if not candidates:
        return None
    candidates.sort(key=lambda r: r.run_id, reverse=True)
    return candidates[0]


def _latest_agg_for_sector(
    rows: list[SectorAggregationRow], sector: str,
) -> SectorAggregationRow | None:
    candidates = [r for r in rows if r.sector == sector]
    if not candidates:
        return None
    candidates.sort(key=lambda r: r.run_id, reverse=True)
    return candidates[0]


def _latest_position_for_ticker(
    positions: list[PositionRow], ticker: str,
) -> PositionRow | None:
    """Latest (by ``as_of``) non-cash position for ``ticker``.

    If multiple accounts hold the ticker on the same date, the first
    occurrence wins (caller-supplied stable order).
    """
    matches = [p for p in positions
               if p.ticker == ticker and p.asset_type != "CASH"]
    if not matches:
        return None
    matches.sort(key=lambda p: p.as_of, reverse=True)
    return matches[0]


def _split_linked_catalyst_ids(s: str) -> list[str]:
    """Parse the V6.7 ledger ``linked_catalysts`` semicolon-joined string."""
    if not s:
        return []
    return [x.strip() for x in s.split(";") if x.strip()]


def _resolve_catalysts(
    all_catalysts: list[Catalyst], linked_ids: list[str],
) -> list[Catalyst]:
    """Look up ``Catalyst`` objects whose ``catalyst_id`` matches ``linked_ids``.

    Preserves the order in ``linked_ids``; missing ids are silently skipped
    (the data-gap notes section surfaces them as "missing catalyst details").
    """
    by_id = {c.catalyst_id: c for c in all_catalysts}
    out: list[Catalyst] = []
    for cid in linked_ids:
        if cid in by_id:
            out.append(by_id[cid])
    return out


def _filter_change_log(
    rows: list[Change], *, linked_ids: list[str], ticker: str,
    top_k: int = 20,
) -> list[Change]:
    """Return change-log rows that touch one of the linked catalysts, the
    ticker as a record_id, or the ticker via COMPANY_SIGNAL annotations.

    Sorted newest-first by ``timestamp``; capped at ``top_k`` rows.
    """
    linked_set = set(linked_ids)
    out: list[Change] = []
    for r in rows:
        if r.record_id in linked_set:
            out.append(r)
        elif r.record_id == ticker:
            out.append(r)
    out.sort(key=lambda r: r.timestamp, reverse=True)
    return out[:top_k]


def _filter_event_annotations(
    rows: list[EventAnnotation], *, ticker: str, linked_ids: list[str],
    top_k: int = 20,
) -> list[EventAnnotation]:
    """Event annotations matching the ticker, one of the linked catalysts,
    or a COMPANY_SIGNAL annotation keyed on the ticker."""
    linked_set = set(linked_ids)
    out: list[EventAnnotation] = []
    for r in rows:
        if r.ticker == ticker:
            out.append(r)
            continue
        if r.related_id in linked_set:
            out.append(r)
            continue
        # COMPANY_SIGNAL annotations key on the ticker as related_id.
        if (r.related_type == "COMPANY_SIGNAL"
                and r.related_id == ticker):
            out.append(r)
    out.sort(key=lambda r: r.timestamp, reverse=True)
    return out[:top_k]


def _portfolio_total_market_value(
    positions: list[PositionRow], as_of: str,
) -> float | None:
    """Sum of non-cash market_value at ``as_of``. None if any row is
    unparseable or the snapshot is empty."""
    if not as_of:
        return None
    snap = [p for p in positions
            if p.as_of == as_of and p.asset_type != "CASH"]
    if not snap:
        return None
    mvs = [_try_parse_float(p.market_value) for p in snap]
    if any(v is None for v in mvs):
        return None
    total = sum(mvs)
    return total if total > 0 else None


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
def build_company_detail_view(
    ticker: str,
    *,
    company_ledger_rows: list[CompanyLedgerRow] | None = None,
    sector_signal_log_rows: list[SectorSignalLogRow] | None = None,
    sector_aggregation_rows: list[SectorAggregationRow] | None = None,
    positions: list[PositionRow] | None = None,
    protection_rows: list[ProtectionRow] | None = None,
    porttech_rows: list[PortTechRow] | None = None,
    catalysts: list[Catalyst] | None = None,
    change_log_rows: list[Change] | None = None,
    event_annotations: list[EventAnnotation] | None = None,
    as_of: str = "",
) -> CompanyDetailView:
    """Compose every available signal about ``ticker`` into a single view.

    PURE. No I/O, no caching, no global state. Missing inputs yield
    empty / blank fields and a populated ``data_gap_notes``.
    """
    if not ticker:
        # Defer to dataclass __post_init__ for the friendly error.
        return CompanyDetailView(ticker=ticker)

    ledger_rows = list(company_ledger_rows or [])
    signal_rows = list(sector_signal_log_rows or [])
    agg_rows = list(sector_aggregation_rows or [])
    pos_rows = list(positions or [])
    prot_rows = list(protection_rows or [])
    pt_rows = list(porttech_rows or [])
    cat_rows = list(catalysts or [])
    cl_rows = list(change_log_rows or [])
    ann_rows = list(event_annotations or [])

    # --- ledger (current + history) --------------------------------------- #
    latest_ledger = _latest_ledger_row_for_ticker(ledger_rows, ticker)
    history = _historical_ledger_rows_for_ticker(ledger_rows, ticker)

    company_or_label = (
        latest_ledger.company_or_label if latest_ledger else ticker
    )
    sector = latest_ledger.sector if latest_ledger else ""
    theme = latest_ledger.theme if latest_ledger else ""
    current_read = latest_ledger.read if latest_ledger else ""
    why_short = latest_ledger.why_short if latest_ledger else ""
    main_risk_short = (
        latest_ledger.main_risk_short if latest_ledger else ""
    )
    linked_catalyst_ids = (
        _split_linked_catalyst_ids(latest_ledger.linked_catalysts)
        if latest_ledger else []
    )

    # --- sector signal + aggregation -------------------------------------- #
    sig = _latest_signal_for_sector(signal_rows, sector) if sector else None
    canonical = sig.canonical_signal if sig else ""
    agg = _latest_agg_for_sector(agg_rows, sector) if sector else None
    company_derived = agg.company_derived_read if agg else ""

    # --- position join ---------------------------------------------------- #
    pos = _latest_position_for_ticker(pos_rows, ticker)
    position_present = pos is not None
    if pos is not None:
        quantity = pos.quantity
        market_value = pos.market_value
        average_cost = pos.average_cost
        unrealized_pnl = pos.unrealized_pnl
        total_mv = _portfolio_total_market_value(pos_rows, pos.as_of)
        mv_f = _try_parse_float(market_value)
        if mv_f is not None and total_mv is not None and total_mv > 0:
            weight_pct = f"{(mv_f / total_mv) * 100.0:.2f}"
        else:
            weight_pct = ""
    else:
        quantity = ""
        market_value = ""
        average_cost = ""
        unrealized_pnl = ""
        weight_pct = ""

    # --- protection / porttech labels ------------------------------------- #
    protection_label = ""
    porttech_label = ""
    for r in prot_rows:
        if r.ticker == ticker:
            protection_label = r.protection_label
            break
    for r in pt_rows:
        if r.ticker == ticker:
            porttech_label = r.porttech_label
            break

    # --- catalysts -------------------------------------------------------- #
    current_catalysts = _resolve_catalysts(cat_rows, linked_catalyst_ids)

    # --- recent changes + event annotations ------------------------------ #
    recent_changes = _filter_change_log(
        cl_rows, linked_ids=linked_catalyst_ids, ticker=ticker,
    )
    relevant_annotations = _filter_event_annotations(
        ann_rows, ticker=ticker, linked_ids=linked_catalyst_ids,
    )

    # --- data gaps -------------------------------------------------------- #
    gaps: list[str] = []
    if latest_ledger is None:
        gaps.append(
            "no V6.7 ledger row for this ticker — run "
            "`python scripts/build_company_signal_ledger.py`"
        )
    else:
        # Linked catalysts that we could not resolve get called out so the
        # operator knows the sector catalyst CSV is missing rows.
        resolved_ids = {c.catalyst_id for c in current_catalysts}
        missing_ids = [cid for cid in linked_catalyst_ids
                       if cid not in resolved_ids]
        if missing_ids:
            gaps.append(
                "missing catalyst details for: "
                + ", ".join(missing_ids)
            )
    if sector and sig is None:
        gaps.append(
            "no V6.6.2 canonical signal log row for this sector"
        )
    if sector and agg is None:
        gaps.append(
            "no V6.8 company-derived aggregation row for this sector"
        )
    if pos is None:
        gaps.append("no V7.1 position on file — tracked, not held")
    if pos is not None and not protection_label:
        gaps.append(
            "no V7.7 protection row supplied — call "
            "derive_protection_rows() first"
        )
    if pos is not None and not porttech_label:
        gaps.append(
            "no V7.4 PortTech row supplied — call "
            "derive_porttech_rows() first"
        )

    return CompanyDetailView(
        ticker=ticker,
        company_or_label=company_or_label,
        sector=sector,
        theme=theme,
        current_company_read=current_read,
        why_short=why_short,
        main_risk_short=main_risk_short,
        linked_catalysts=linked_catalyst_ids,
        canonical_sector_signal=canonical,
        company_derived_sector_read=company_derived,
        position_present=position_present,
        quantity=quantity,
        market_value=market_value,
        portfolio_weight_pct=weight_pct,
        average_cost=average_cost,
        unrealized_pnl=unrealized_pnl,
        protection_label=protection_label,
        porttech_label=porttech_label,
        historical_company_reads=history,
        current_catalysts=current_catalysts,
        recent_changes=recent_changes,
        event_annotations=relevant_annotations,
        data_gap_notes=gaps,
        as_of=as_of,
    )


__all__ = [
    "ticker_universe",
    "build_company_detail_view",
]
