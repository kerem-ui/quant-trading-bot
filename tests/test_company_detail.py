"""V7.5 — Tests for the Company Detail / Stock Intelligence page.

Covers:

  * :class:`CompanyDetailView` schema validation.
  * Ticker universe builder (union of ledger tickers + non-cash positions).
  * Current ledger read lookup (latest run_id wins).
  * Historical reads collection (newest-first).
  * Position join — held vs tracked-not-held.
  * Protection / PortTech label join.
  * Linked-catalyst parsing + resolution against the catalyst CSVs.
  * Change-log filter (linked catalysts + ticker).
  * Event annotation filter (ticker + linked catalysts + COMPANY_SIGNAL).
  * Missing-input branches produce DATA_GAP notes.
  * **No effect on**: Portfolio totals, Protection rows, PortTech rows,
    ``score_sector``.
  * Guardrails: no broker / IBKR / order / hedge tokens; no network
    imports; ``LIVE_TRADING_ENABLED`` False.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

import quantbot
from quantbot.research.company_detail import (
    COMPANY_DETAIL_FIELDS,
    CompanyDetailSchemaError,
    CompanyDetailView,
    build_company_detail_view,
    ticker_universe,
)
from quantbot.research.portfolio import (
    PositionRow,
    append_position_rows,
    ensure_transactions_header,
)
from quantbot.research.porttech import (
    PortTechRow,
    derive_porttech_rows,
)
from quantbot.research.protection import (
    ProtectionRow,
    derive_protection_rows,
)
from quantbot.research.sector_tracker import (
    Catalyst,
    Change,
    CompanyLedgerRow,
    EventAnnotation,
    SectorAggregationRow,
    SectorSignalLogRow,
    score_sector,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
_TS = "2026-06-03T00:00:00+00:00"
_DATE = "2026-06-03"


# --------------------------------------------------------------------------- #
# fixtures + builders
# --------------------------------------------------------------------------- #
@pytest.fixture
def platform():
    sys.path.insert(0, str(REPO_ROOT / "apps"))
    try:
        yield importlib.import_module("portfolio_platform")
    finally:
        if str(REPO_ROOT / "apps") in sys.path:
            sys.path.remove(str(REPO_ROOT / "apps"))


def _pos(*, ticker: str, sector: str = "SEMICONDUCTOR",
         theme: str = "",
         market_value: str = "10000",
         asset_type: str = "STOCK",
         as_of: str = _DATE, account: str = "MAIN",
         currency: str = "USD",
         quantity: str = "100",
         average_cost: str = "100",
         unrealized_pnl: str = "500") -> PositionRow:
    return PositionRow(
        as_of=as_of, account=account, ticker=ticker,
        asset_type=asset_type, market_value=market_value,
        sector=sector, theme=theme, currency=currency,
        quantity=quantity, average_cost=average_cost,
        unrealized_pnl=unrealized_pnl,
    )


def _lrow(*, ticker: str, sector: str = "SEMICONDUCTOR",
          read: str = "BULL", run_id: str = "RUN-1",
          date: str = _DATE, theme: str = "x",
          why_short: str = "why-x",
          main_risk_short: str = "risk-x",
          linked_catalysts: str = "",
          company_or_label: str = "") -> CompanyLedgerRow:
    return CompanyLedgerRow(
        run_id=run_id, timestamp=_TS, date=date,
        ticker=ticker,
        company_or_label=company_or_label or ticker,
        sector=sector, theme=theme, read=read,
        why_short=why_short, main_risk_short=main_risk_short,
        linked_catalysts=linked_catalysts,
        n_linked_present=0, n_linked_total=0,
        source_files="", source_dates="",
        is_manual_or_tracked_context="false",
        reason="", notes="",
    )


def _ssr(*, sector: str = "SEMICONDUCTOR",
         signal: str = "SELECTIVE_BUY",
         run_id: str = "RUN-1") -> SectorSignalLogRow:
    return SectorSignalLogRow(
        run_id=run_id, timestamp=_TS, date=_DATE, sector=sector,
        canonical_signal=signal, normalized_score=0.0, raw_score=0.0,
        total_weight=0, n_catalysts=0, n_bull=0, n_neutral=0,
        n_near_threshold=0, n_broken=0, n_emergency_exits=0,
        n_triggered_exits=0,
    )


def _agg(*, sector: str = "SEMICONDUCTOR",
         read: str = "BULL",
         run_id: str = "RUN-1") -> SectorAggregationRow:
    return SectorAggregationRow(
        run_id=run_id, timestamp=_TS, date=_DATE, sector=sector,
        n_companies=1, n_bull=1, n_mixed=0, n_neutral=0,
        n_near_threshold=0, n_broken=0, n_tracked=0, n_na=0,
        company_derived_read=read,
        top_bull_companies="X", top_mixed_or_risk_companies="",
        tracked_only_companies="",
        notes="", source_ledger="",
    )


def _cat(*, cid: str, sector: str = "SEMICONDUCTOR",
         status: str = "BULL",
         catalyst_name: str = "name",
         current_value: str = "+10%",
         tier: int = 1) -> Catalyst:
    return Catalyst(
        catalyst_id=cid, sector=sector, subsector="x",
        catalyst_name=catalyst_name, tier=tier, direction="ABOVE",
        threshold="t", current_value=current_value, status=status,
        source_type="SEC_EDGAR", source_detail="ok",
        last_updated="2026-05-28", action_if_broken="review", notes="",
    )


def _change(*, record_id: str, sector: str = "SEMICONDUCTOR",
            timestamp: str = _TS, run_id: str = "RUN-1",
            field_changed: str = "status",
            prior_value: str = "NEUTRAL",
            new_value: str = "BULL") -> Change:
    return Change(
        timestamp=timestamp, sector=sector, record_type="CATALYST",
        record_id=record_id, field_changed=field_changed,
        prior_value=prior_value, new_value=new_value,
        prior_status=prior_value, new_status=new_value,
        source_file="x.csv", source_date=_DATE,
        refresh_run_id=run_id, notes="",
    )


def _annotation(*, ticker: str = "",
                related_id: str = "X",
                related_type: str = "CATALYST",
                event_type: str = "EARNINGS",
                title: str = "title",
                timestamp: str = _TS) -> EventAnnotation:
    return EventAnnotation(
        timestamp=timestamp, sector="SEMICONDUCTOR",
        related_id=related_id, related_type=related_type,
        ticker=ticker, event_type=event_type, title=title,
        note="note", source="MANUAL", source_url_or_file="",
        added_by="op", confidence="HIGH",
    )


# --------------------------------------------------------------------------- #
# Guardrails (V7.5 surface only)
# --------------------------------------------------------------------------- #
class TestGuardrails:
    SCHEMA_SOURCE = (
        REPO_ROOT / "src" / "quantbot" / "research" / "company_detail"
        / "schema.py"
    ).read_text(encoding="utf-8")
    ENGINE_SOURCE = (
        REPO_ROOT / "src" / "quantbot" / "research" / "company_detail"
        / "engine.py"
    ).read_text(encoding="utf-8")

    def test_live_trading_disabled(self):
        assert quantbot.LIVE_TRADING_ENABLED is False

    def test_no_broker_or_order_tokens(self):
        for src in (self.SCHEMA_SOURCE, self.ENGINE_SOURCE):
            for token in ("ib_insync", "place_order", "submit_order",
                          "from broker", "import broker", "ibapi",
                          "placeOrder"):
                assert token not in src, (
                    f"forbidden token {token!r} in V7.5 surface"
                )

    def test_no_network_imports(self):
        for src in (self.SCHEMA_SOURCE, self.ENGINE_SOURCE):
            for token in ("import requests", "import urllib",
                          "import aiohttp", "import socket",
                          "from requests", "from urllib",
                          "from aiohttp", "from socket"):
                assert token not in src, (
                    f"forbidden network import {token!r} in V7.5 surface"
                )

    def test_no_thetadata_imports(self):
        for src in (self.SCHEMA_SOURCE, self.ENGINE_SOURCE):
            assert "import thetadata" not in src.lower()
            assert "from thetadata" not in src.lower()

    def test_no_hedge_execution_tokens(self):
        for src in (self.SCHEMA_SOURCE, self.ENGINE_SOURCE):
            for token in ("execute_hedge", "submit_hedge",
                          "place_hedge", "hedge_order",
                          "execute_trade", "place_trade",
                          "submit_trade", "execute_order",
                          "buy_button", "sell_button"):
                assert token not in src, (
                    f"forbidden token {token!r} in V7.5 surface"
                )


# --------------------------------------------------------------------------- #
# Schema
# --------------------------------------------------------------------------- #
class TestSchema:
    def test_fields_stable(self):
        for name in (
            "ticker", "company_or_label", "sector", "theme",
            "current_company_read", "why_short", "main_risk_short",
            "linked_catalysts", "canonical_sector_signal",
            "company_derived_sector_read", "position_present",
            "quantity", "market_value", "portfolio_weight_pct",
            "average_cost", "unrealized_pnl",
            "protection_label", "porttech_label",
            "historical_company_reads", "current_catalysts",
            "recent_changes", "event_annotations",
            "data_gap_notes",
        ):
            assert name in COMPANY_DETAIL_FIELDS

    def test_valid_view_constructs(self):
        v = CompanyDetailView(ticker="NVDA")
        assert v.ticker == "NVDA"
        assert v.linked_catalysts == []
        assert v.position_present is False

    def test_missing_ticker_rejected(self):
        with pytest.raises(CompanyDetailSchemaError):
            CompanyDetailView(ticker="")

    def test_non_list_field_rejected(self):
        with pytest.raises(CompanyDetailSchemaError):
            CompanyDetailView(
                ticker="X",
                linked_catalysts="not-a-list",  # type: ignore[arg-type]
            )


# --------------------------------------------------------------------------- #
# ticker_universe
# --------------------------------------------------------------------------- #
class TestTickerUniverse:
    def test_empty_inputs_yield_empty_universe(self):
        assert ticker_universe([], []) == []

    def test_ledger_only(self):
        rows = [_lrow(ticker="NVDA"), _lrow(ticker="AMD")]
        assert ticker_universe(rows, []) == ["AMD", "NVDA"]

    def test_positions_only(self):
        positions = [_pos(ticker="MSFT"), _pos(ticker="GOOGL")]
        assert ticker_universe([], positions) == ["GOOGL", "MSFT"]

    def test_union_dedupes(self):
        rows = [_lrow(ticker="NVDA")]
        positions = [_pos(ticker="NVDA"),
                      _pos(ticker="AMD")]
        assert ticker_universe(rows, positions) == ["AMD", "NVDA"]

    def test_cash_excluded(self):
        positions = [_pos(ticker="USD", asset_type="CASH"),
                      _pos(ticker="NVDA")]
        # CASH ticker excluded from the universe.
        assert "USD" not in ticker_universe([], positions)
        assert "NVDA" in ticker_universe([], positions)


# --------------------------------------------------------------------------- #
# Engine — current + historical reads
# --------------------------------------------------------------------------- #
class TestCurrentAndHistoricalReads:
    def test_latest_run_id_wins(self):
        rows = [
            _lrow(ticker="NVDA", read="BULL", run_id="RUN-A"),
            _lrow(ticker="NVDA", read="MIXED", run_id="RUN-B"),
        ]
        view = build_company_detail_view(
            "NVDA", company_ledger_rows=rows,
        )
        assert view.current_company_read == "MIXED"

    def test_historical_reads_newest_first(self):
        rows = [
            _lrow(ticker="NVDA", read="BULL", run_id="RUN-A"),
            _lrow(ticker="NVDA", read="MIXED", run_id="RUN-B"),
            _lrow(ticker="NVDA", read="BROKEN", run_id="RUN-C"),
        ]
        view = build_company_detail_view(
            "NVDA", company_ledger_rows=rows,
        )
        reads = [r.read for r in view.historical_company_reads]
        assert reads == ["BROKEN", "MIXED", "BULL"]

    def test_other_ticker_history_excluded(self):
        rows = [
            _lrow(ticker="NVDA", read="BULL", run_id="RUN-A"),
            _lrow(ticker="AMD", read="MIXED", run_id="RUN-A"),
        ]
        view = build_company_detail_view(
            "NVDA", company_ledger_rows=rows,
        )
        assert len(view.historical_company_reads) == 1
        assert view.historical_company_reads[0].ticker == "NVDA"

    def test_company_or_label_inherits_from_ledger(self):
        rows = [_lrow(ticker="OpenAI",
                       company_or_label="OpenAI (private)",
                       sector="AI")]
        view = build_company_detail_view(
            "OpenAI", company_ledger_rows=rows,
        )
        assert view.company_or_label == "OpenAI (private)"
        assert view.sector == "AI"


# --------------------------------------------------------------------------- #
# Engine — sector signal + aggregation join
# --------------------------------------------------------------------------- #
class TestSectorJoin:
    def test_canonical_signal_picked_up(self):
        view = build_company_detail_view(
            "NVDA",
            company_ledger_rows=[_lrow(ticker="NVDA",
                                         sector="SEMICONDUCTOR")],
            sector_signal_log_rows=[_ssr(signal="SELECTIVE_BUY")],
        )
        assert view.canonical_sector_signal == "SELECTIVE_BUY"

    def test_company_derived_read_picked_up(self):
        view = build_company_detail_view(
            "NVDA",
            company_ledger_rows=[_lrow(ticker="NVDA")],
            sector_aggregation_rows=[_agg(read="CAUTION")],
        )
        assert view.company_derived_sector_read == "CAUTION"

    def test_missing_signal_logs_gap(self):
        view = build_company_detail_view(
            "NVDA",
            company_ledger_rows=[_lrow(ticker="NVDA")],
        )
        assert any("canonical signal log" in g
                   for g in view.data_gap_notes)

    def test_missing_aggregation_logs_gap(self):
        view = build_company_detail_view(
            "NVDA",
            company_ledger_rows=[_lrow(ticker="NVDA")],
            sector_signal_log_rows=[_ssr()],
        )
        assert any("company-derived aggregation" in g
                   for g in view.data_gap_notes)


# --------------------------------------------------------------------------- #
# Engine — position join
# --------------------------------------------------------------------------- #
class TestPositionJoin:
    def test_held_position_populates_fields(self):
        view = build_company_detail_view(
            "NVDA",
            company_ledger_rows=[_lrow(ticker="NVDA")],
            positions=[_pos(ticker="NVDA",
                              market_value="60000",
                              quantity="120",
                              average_cost="450",
                              unrealized_pnl="6000")],
        )
        assert view.position_present is True
        assert view.quantity == "120"
        assert view.market_value == "60000"
        assert view.average_cost == "450"
        assert view.unrealized_pnl == "6000"
        # Single-position book → 100%.
        assert view.portfolio_weight_pct == "100.00"

    def test_not_held_returns_tracked_not_held(self):
        view = build_company_detail_view(
            "NVDA",
            company_ledger_rows=[_lrow(ticker="NVDA")],
            positions=[_pos(ticker="AMD",
                              market_value="40000")],
        )
        assert view.position_present is False
        assert view.quantity == ""
        assert view.market_value == ""
        assert any("tracked, not held" in g
                   for g in view.data_gap_notes)

    def test_weight_with_multiple_positions(self):
        view = build_company_detail_view(
            "NVDA",
            company_ledger_rows=[_lrow(ticker="NVDA")],
            positions=[_pos(ticker="NVDA", market_value="60000"),
                       _pos(ticker="AMD", market_value="40000")],
        )
        # NVDA = 60k / 100k = 60%
        assert view.portfolio_weight_pct == "60.00"

    def test_unparseable_market_value_yields_blank_weight(self):
        view = build_company_detail_view(
            "NVDA",
            company_ledger_rows=[_lrow(ticker="NVDA")],
            positions=[_pos(ticker="NVDA",
                              market_value="not_a_number")],
        )
        assert view.portfolio_weight_pct == ""

    def test_latest_as_of_wins_for_position(self):
        view = build_company_detail_view(
            "NVDA",
            company_ledger_rows=[_lrow(ticker="NVDA")],
            positions=[_pos(ticker="NVDA",
                              as_of="2026-05-01",
                              market_value="50000"),
                       _pos(ticker="NVDA",
                              as_of="2026-06-03",
                              market_value="60000")],
        )
        assert view.market_value == "60000"


# --------------------------------------------------------------------------- #
# Engine — protection / porttech join
# --------------------------------------------------------------------------- #
class TestProtectionAndPortTechJoin:
    def test_protection_label_picked_up(self):
        prot = ProtectionRow(as_of=_DATE, ticker="NVDA",
                              protection_label="CONCENTRATION")
        view = build_company_detail_view(
            "NVDA",
            company_ledger_rows=[_lrow(ticker="NVDA")],
            positions=[_pos(ticker="NVDA")],
            protection_rows=[prot],
        )
        assert view.protection_label == "CONCENTRATION"

    def test_porttech_label_picked_up(self):
        pt = PortTechRow(as_of=_DATE, ticker="NVDA",
                          porttech_label="WATCH")
        view = build_company_detail_view(
            "NVDA",
            company_ledger_rows=[_lrow(ticker="NVDA")],
            positions=[_pos(ticker="NVDA")],
            porttech_rows=[pt],
        )
        assert view.porttech_label == "WATCH"

    def test_held_but_no_protection_logs_gap(self):
        view = build_company_detail_view(
            "NVDA",
            company_ledger_rows=[_lrow(ticker="NVDA")],
            positions=[_pos(ticker="NVDA")],
        )
        assert any("protection row" in g
                   for g in view.data_gap_notes)
        assert any("PortTech row" in g
                   for g in view.data_gap_notes)


# --------------------------------------------------------------------------- #
# Engine — linked catalysts
# --------------------------------------------------------------------------- #
class TestLinkedCatalysts:
    def test_parsed_from_ledger_string(self):
        view = build_company_detail_view(
            "NVDA",
            company_ledger_rows=[_lrow(ticker="NVDA",
                linked_catalysts="A;B;C")],
        )
        assert view.linked_catalysts == ["A", "B", "C"]

    def test_resolved_against_catalyst_list(self):
        view = build_company_detail_view(
            "NVDA",
            company_ledger_rows=[_lrow(ticker="NVDA",
                linked_catalysts="A;B")],
            catalysts=[
                _cat(cid="A", status="BULL"),
                _cat(cid="B", status="BROKEN"),
                _cat(cid="C", status="NEUTRAL"),
            ],
        )
        ids = [c.catalyst_id for c in view.current_catalysts]
        assert ids == ["A", "B"]

    def test_missing_catalyst_details_logged(self):
        view = build_company_detail_view(
            "NVDA",
            company_ledger_rows=[_lrow(ticker="NVDA",
                linked_catalysts="A;MISSING")],
            catalysts=[_cat(cid="A")],
        )
        assert any("missing catalyst details" in g
                   for g in view.data_gap_notes)

    def test_empty_linked_catalysts_string(self):
        view = build_company_detail_view(
            "NVDA",
            company_ledger_rows=[_lrow(ticker="NVDA",
                linked_catalysts="")],
        )
        assert view.linked_catalysts == []
        assert view.current_catalysts == []


# --------------------------------------------------------------------------- #
# Engine — change log + event annotation filter
# --------------------------------------------------------------------------- #
class TestChangeLogAndAnnotations:
    def test_change_log_matches_linked_catalyst(self):
        view = build_company_detail_view(
            "NVDA",
            company_ledger_rows=[_lrow(ticker="NVDA",
                linked_catalysts="A;B")],
            change_log_rows=[
                _change(record_id="A", timestamp="2026-06-01"),
                _change(record_id="C", timestamp="2026-06-02"),
            ],
        )
        assert {c.record_id for c in view.recent_changes} == {"A"}

    def test_change_log_matches_ticker_directly(self):
        view = build_company_detail_view(
            "NVDA",
            company_ledger_rows=[_lrow(ticker="NVDA")],
            change_log_rows=[_change(record_id="NVDA")],
        )
        assert any(c.record_id == "NVDA" for c in view.recent_changes)

    def test_change_log_newest_first(self):
        view = build_company_detail_view(
            "NVDA",
            company_ledger_rows=[_lrow(ticker="NVDA",
                linked_catalysts="A")],
            change_log_rows=[
                _change(record_id="A", timestamp="2026-06-01T01:00:00+00:00"),
                _change(record_id="A", timestamp="2026-06-03T01:00:00+00:00"),
            ],
        )
        # The latest change comes first.
        assert view.recent_changes[0].timestamp.startswith("2026-06-03")

    def test_annotation_matches_ticker(self):
        view = build_company_detail_view(
            "NVDA",
            company_ledger_rows=[_lrow(ticker="NVDA")],
            event_annotations=[
                _annotation(ticker="NVDA",
                              related_id="X",
                              event_type="EARNINGS"),
                _annotation(ticker="AMD",
                              related_id="X",
                              event_type="EARNINGS"),
            ],
        )
        assert {a.ticker for a in view.event_annotations} == {"NVDA"}

    def test_annotation_matches_linked_catalyst(self):
        view = build_company_detail_view(
            "NVDA",
            company_ledger_rows=[_lrow(ticker="NVDA",
                linked_catalysts="SEMI-NVDA-REV-T1")],
            event_annotations=[
                _annotation(ticker="",
                              related_id="SEMI-NVDA-REV-T1",
                              related_type="CATALYST"),
            ],
        )
        assert len(view.event_annotations) == 1

    def test_annotation_matches_company_signal_related_type(self):
        view = build_company_detail_view(
            "NVDA",
            company_ledger_rows=[_lrow(ticker="NVDA")],
            event_annotations=[
                _annotation(ticker="",
                              related_id="NVDA",
                              related_type="COMPANY_SIGNAL"),
            ],
        )
        assert len(view.event_annotations) == 1


# --------------------------------------------------------------------------- #
# Engine — missing inputs / DATA_GAP branches
# --------------------------------------------------------------------------- #
class TestDataGapBranches:
    def test_no_ledger_logs_gap(self):
        view = build_company_detail_view(
            "NVDA", company_ledger_rows=[],
        )
        assert any("ledger row" in g for g in view.data_gap_notes)
        assert view.current_company_read == ""

    def test_no_inputs_at_all(self):
        view = build_company_detail_view("NVDA")
        assert view.ticker == "NVDA"
        # At least one gap reported.
        assert view.data_gap_notes


# --------------------------------------------------------------------------- #
# Platform helpers (with real disk join)
# --------------------------------------------------------------------------- #
class TestPlatformHelpers:
    def test_universe_loader_empty(self, tmp_path: Path, platform):
        out = platform.load_ticker_universe_from_disk(
            positions_path=tmp_path / "p.csv",
            ledger_path=tmp_path / "l.csv",
        )
        assert out == []

    def test_universe_loader_with_real_data(self, platform):
        # Against the committed CSVs — universe should be populated.
        out = platform.load_ticker_universe_from_disk()
        # The V6.7 ledger ships with 27 companies; universe must be non-empty.
        assert len(out) > 0

    def test_group_catalysts_by_status_preserves_order(self, platform):
        cats = [
            _cat(cid="A", status="BULL"),
            _cat(cid="B", status="BROKEN"),
            _cat(cid="C", status="NEUTRAL"),
            _cat(cid="D", status="BULL"),
        ]
        grouped = platform.group_catalysts_by_status(cats)
        assert list(grouped) == ["BROKEN", "NEUTRAL", "BULL"]
        assert {c.catalyst_id for c in grouped["BULL"]} == {"A", "D"}

    def test_build_view_from_disk_against_real_data(self, platform):
        # End-to-end smoke against committed real data. The platform's
        # universe includes "NVDA" — confirm we can build a view.
        view = platform.build_company_detail_view_from_disk("NVDA")
        assert view.ticker == "NVDA"
        # We expect at least a sector to be resolved.
        assert view.sector  # non-empty


# --------------------------------------------------------------------------- #
# Regression — V7.5 must NOT affect anything upstream.
# --------------------------------------------------------------------------- #
class TestNoEffect:
    def test_portfolio_totals_unchanged(self, tmp_path: Path, platform):
        pp = tmp_path / "p.csv"
        tp = tmp_path / "t.csv"
        append_position_rows([
            _pos(ticker="NVDA", market_value="60000"),
            _pos(ticker="AMD", market_value="40000"),
        ], pp)
        ensure_transactions_header(tp)
        before = platform.compute_portfolio_totals(
            platform.load_portfolio_snapshot(pp, tp),
        )
        # Build company-detail views for various tickers; must not mutate.
        for ticker in ("NVDA", "AMD"):
            build_company_detail_view(
                ticker,
                positions=[_pos(ticker="NVDA", market_value="60000"),
                            _pos(ticker="AMD", market_value="40000")],
            )
        after = platform.compute_portfolio_totals(
            platform.load_portfolio_snapshot(pp, tp),
        )
        assert before == after

    def test_protection_rows_unchanged(self):
        positions = [_pos(ticker="NVDA", market_value="60000"),
                     _pos(ticker="AMD", market_value="40000")]
        ledger = {
            "NVDA": _lrow(ticker="NVDA", read="BROKEN"),
            "AMD": _lrow(ticker="AMD", read="BULL"),
        }
        before = [r.to_dict() for r in derive_protection_rows(
            positions,
            company_ledger_by_ticker=ledger,
            sector_signals_by_sector={
                "SEMICONDUCTOR": _ssr(),
            },
        )]
        # Build company-detail views; downstream-only.
        build_company_detail_view("NVDA",
            company_ledger_rows=list(ledger.values()),
            positions=positions,
        )
        after = [r.to_dict() for r in derive_protection_rows(
            positions,
            company_ledger_by_ticker=ledger,
            sector_signals_by_sector={
                "SEMICONDUCTOR": _ssr(),
            },
        )]
        assert before == after

    def test_porttech_rows_unchanged(self):
        positions = [_pos(ticker="NVDA", market_value="60000"),
                     _pos(ticker="AMD", market_value="40000")]
        ledger = {
            "NVDA": _lrow(ticker="NVDA", read="BULL"),
            "AMD": _lrow(ticker="AMD", read="BULL"),
        }
        signals = {"SEMICONDUCTOR": _ssr(signal="ACCUMULATE")}
        before = [r.to_dict() for r in derive_porttech_rows(
            positions,
            company_ledger_by_ticker=ledger,
            sector_signals_by_sector=signals,
        )]
        build_company_detail_view("NVDA",
            company_ledger_rows=list(ledger.values()),
            positions=positions,
        )
        after = [r.to_dict() for r in derive_porttech_rows(
            positions,
            company_ledger_by_ticker=ledger,
            sector_signals_by_sector=signals,
        )]
        assert before == after

    def test_score_sector_untouched(self):
        from quantbot.research.sector_tracker import Catalyst
        cats = [Catalyst(
            catalyst_id="X", sector="SEMICONDUCTOR", subsector="x",
            catalyst_name="x", tier=1, direction="ABOVE",
            threshold="t", current_value="v", status="BULL",
            source_type="SEC_EDGAR", source_detail="ok",
            last_updated="2026-05-28", action_if_broken="x",
        )]
        before = score_sector(cats, [], sector="SEMICONDUCTOR")
        build_company_detail_view("NVDA",
            company_ledger_rows=[_lrow(ticker="NVDA")],
        )
        after = score_sector(cats, [], sector="SEMICONDUCTOR")
        assert before.signal == after.signal
        assert before.normalized_score == after.normalized_score


# --------------------------------------------------------------------------- #
# Regression — V6 / V7.0 / V7.4 / V7.7 surfaces still load cleanly
# --------------------------------------------------------------------------- #
class TestRegression:
    def test_platform_module_imports(self):
        sys.path.insert(0, str(REPO_ROOT / "apps"))
        try:
            mod = importlib.import_module("portfolio_platform")
            for name in (
                "build_company_detail_view_from_disk",
                "load_ticker_universe_from_disk",
                "group_catalysts_by_status",
                "derive_porttech_rows_from_snapshot",
                "load_protection_snapshot",
                "load_portfolio_snapshot",
            ):
                assert hasattr(mod, name), f"missing: {name}"
            assert "Company Detail" in mod.PAGES
        finally:
            if str(REPO_ROOT / "apps") in sys.path:
                sys.path.remove(str(REPO_ROOT / "apps"))

    def test_v6_dashboard_imports(self):
        sys.path.insert(0, str(REPO_ROOT / "apps"))
        try:
            mod = importlib.import_module("sector_thesis_dashboard")
            assert hasattr(mod, "render")
        finally:
            if str(REPO_ROOT / "apps") in sys.path:
                sys.path.remove(str(REPO_ROOT / "apps"))
