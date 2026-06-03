"""V7.7 — Tests for the Protection risk surface.

Covers:

  * :class:`ProtectionRow` schema validation.
  * :func:`worst_label` priority ordering across the six label values.
  * :func:`derive_protection_rows` — the categorical rule set:
      - concentration threshold (CONCENTRATION ≥ 25 %, WATCH 15–25 %)
      - MIXED company read → WATCH
      - BROKEN company read → SHARED_RISK_EXPOSED
      - REDUCE / EXIT_WATCH canonical → SECTOR_AT_RISK
      - AVOID_NEW_BUY canonical → WATCH
      - Positive canonical + CAUTION company-derived → WATCH ("more cautious")
      - Missing inputs → DATA_GAP
      - Cash positions are excluded from the investable book
  * Platform helpers: ``load_protection_snapshot``,
    ``derive_protection_rows_from_snapshot``,
    ``compute_protection_summary``,
    ``protection_concentration_panel``, ``protection_data_gaps``.
  * Portfolio totals unchanged by Protection rendering — Protection reads
    are a downstream derivation that never mutates positions.
  * Hard guardrails: no broker / IBKR / order / network / ThetaData tokens
    in any V7.7 surface; ``LIVE_TRADING_ENABLED`` False.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

import quantbot
from quantbot.research.portfolio import (
    PositionRow,
    append_position_rows,
    ensure_positions_header,
)
from quantbot.research.protection import (
    ALLOWED_PROTECTION_LABEL,
    CONCENTRATION_THRESHOLD_PCT,
    LABEL_PRIORITY,
    PROTECTION_ROW_FIELDS,
    ProtectionRow,
    ProtectionSchemaError,
    WATCH_CONCENTRATION_THRESHOLD_PCT,
    derive_protection_rows,
    worst_label,
)
from quantbot.research.sector_tracker import (
    CompanyLedgerRow,
    SectorAggregationRow,
    SectorSignalLogRow,
    score_sector,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
_TS = "2026-06-03T00:00:00+00:00"
_DATE = "2026-06-03"


# --------------------------------------------------------------------------- #
# fixtures + helpers
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
         currency: str = "USD") -> PositionRow:
    return PositionRow(
        as_of=as_of, account=account, ticker=ticker,
        asset_type=asset_type, market_value=market_value,
        sector=sector, theme=theme, currency=currency,
    )


def _lrow(*, ticker: str, sector: str, read: str = "BULL",
          run_id: str = "RUN-1") -> CompanyLedgerRow:
    return CompanyLedgerRow(
        run_id=run_id, timestamp=_TS, date=_DATE,
        ticker=ticker, company_or_label=ticker,
        sector=sector, theme="theme", read=read,
        why_short="why", main_risk_short="risk",
        linked_catalysts="", n_linked_present=0, n_linked_total=0,
        source_files="", source_dates="",
        is_manual_or_tracked_context="false",
        reason="", notes="",
    )


def _ssr(*, sector: str, signal: str = "HOLD",
         run_id: str = "RUN-1") -> SectorSignalLogRow:
    return SectorSignalLogRow(
        run_id=run_id, timestamp=_TS, date=_DATE, sector=sector,
        canonical_signal=signal, normalized_score=0.0, raw_score=0.0,
        total_weight=0, n_catalysts=0, n_bull=0, n_neutral=0,
        n_near_threshold=0, n_broken=0, n_emergency_exits=0,
        n_triggered_exits=0,
    )


def _agg(*, sector: str, read: str = "BULL",
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


# --------------------------------------------------------------------------- #
# Module surface + guardrails
# --------------------------------------------------------------------------- #
class TestGuardrails:
    SCHEMA_SOURCE = (
        REPO_ROOT / "src" / "quantbot" / "research" / "protection"
        / "schema.py"
    ).read_text(encoding="utf-8")
    ENGINE_SOURCE = (
        REPO_ROOT / "src" / "quantbot" / "research" / "protection"
        / "engine.py"
    ).read_text(encoding="utf-8")

    def test_live_trading_disabled(self):
        assert quantbot.LIVE_TRADING_ENABLED is False

    def test_no_broker_or_order_tokens(self):
        for src in (self.SCHEMA_SOURCE, self.ENGINE_SOURCE):
            for token in ("ib_insync", "place_order", "submit_order",
                          "from broker", "import broker", "ibapi"):
                assert token not in src, (
                    f"forbidden broker token {token!r} in V7.7 surface"
                )

    def test_no_network_imports(self):
        for src in (self.SCHEMA_SOURCE, self.ENGINE_SOURCE):
            for token in ("import requests", "import urllib",
                          "import aiohttp", "import socket",
                          "from requests", "from urllib",
                          "from aiohttp", "from socket"):
                assert token not in src, (
                    f"forbidden network import {token!r} in V7.7 surface"
                )

    def test_no_thetadata_imports(self):
        for src in (self.SCHEMA_SOURCE, self.ENGINE_SOURCE):
            assert "import thetadata" not in src.lower()
            assert "from thetadata" not in src.lower()

    def test_no_hedge_execution_tokens(self):
        # Belt-and-braces: V7.7 must never mention execution / hedge orders.
        for src in (self.SCHEMA_SOURCE, self.ENGINE_SOURCE):
            for token in ("execute_hedge", "submit_hedge",
                          "place_hedge", "hedge_order"):
                assert token not in src, (
                    f"forbidden execution token {token!r} in V7.7 surface"
                )


# --------------------------------------------------------------------------- #
# Schema
# --------------------------------------------------------------------------- #
class TestSchema:
    def test_allowed_labels(self):
        assert ALLOWED_PROTECTION_LABEL == {
            "OK", "WATCH", "CONCENTRATION",
            "SECTOR_AT_RISK", "SHARED_RISK_EXPOSED", "DATA_GAP",
        }

    def test_label_priority_real_risks_first(self):
        # SECTOR_AT_RISK is the worst real risk; OK is the safest bucket.
        # DATA_GAP sits one above OK so a real risk on any axis always
        # wins the headline, but a row with no real risk + missing inputs
        # surfaces as DATA_GAP rather than OK.
        assert LABEL_PRIORITY[0] == "SECTOR_AT_RISK"
        assert LABEL_PRIORITY[-1] == "OK"
        assert LABEL_PRIORITY[-2] == "DATA_GAP"

    def test_fields_stable(self):
        for name in (
            "as_of", "ticker", "sector", "theme", "market_value",
            "portfolio_weight_pct", "company_read",
            "canonical_sector_signal", "company_derived_sector_read",
            "concentration_label", "sector_risk_label",
            "company_risk_label", "protection_label",
            "why_short", "action_short",
        ):
            assert name in PROTECTION_ROW_FIELDS

    def test_valid_row_constructs(self):
        r = ProtectionRow(as_of=_DATE, ticker="NVDA",
                            sector="SEMICONDUCTOR")
        assert r.ticker == "NVDA"
        assert r.protection_label == "OK"

    def test_missing_ticker_rejected(self):
        with pytest.raises(ProtectionSchemaError):
            ProtectionRow(as_of=_DATE, ticker="")

    @pytest.mark.parametrize("label_field", [
        "concentration_label", "sector_risk_label",
        "company_risk_label", "protection_label",
    ])
    def test_invalid_label_rejected(self, label_field):
        kwargs = dict(as_of=_DATE, ticker="X")
        kwargs[label_field] = "WAT"
        with pytest.raises(ProtectionSchemaError):
            ProtectionRow(**kwargs)


# --------------------------------------------------------------------------- #
# worst_label priority
# --------------------------------------------------------------------------- #
class TestWorstLabel:
    def test_empty_returns_ok(self):
        assert worst_label() == "OK"

    def test_all_ok(self):
        assert worst_label("OK", "OK", "OK") == "OK"

    def test_real_risk_beats_data_gap(self):
        # The whole point of the new priority — when one axis has a real
        # risk and another has a gap, the real risk is the headline.
        assert worst_label("WATCH", "DATA_GAP") == "WATCH"
        assert worst_label("DATA_GAP", "CONCENTRATION") == "CONCENTRATION"

    def test_data_gap_still_beats_ok(self):
        # And when nothing real surfaces, DATA_GAP wins over OK so the
        # operator sees a gap rather than a false "all clear".
        assert worst_label("OK", "OK", "DATA_GAP") == "DATA_GAP"

    def test_sector_at_risk_beats_concentration(self):
        assert worst_label("CONCENTRATION", "SECTOR_AT_RISK",
                            "OK") == "SECTOR_AT_RISK"

    def test_concentration_beats_shared_risk(self):
        assert worst_label("CONCENTRATION", "SHARED_RISK_EXPOSED",
                            "OK") == "CONCENTRATION"

    def test_shared_risk_beats_watch(self):
        assert worst_label("WATCH", "SHARED_RISK_EXPOSED",
                            "OK") == "SHARED_RISK_EXPOSED"

    def test_unknown_label_treated_as_data_gap(self):
        assert worst_label("WAT", "OK") == "DATA_GAP"


# --------------------------------------------------------------------------- #
# Engine — categorical rule set
# --------------------------------------------------------------------------- #
class TestEngineConcentration:
    def test_single_position_is_concentration(self):
        # A one-position book is 100% concentrated by definition.
        rows = derive_protection_rows(
            [_pos(ticker="NVDA", market_value="10000")],
        )
        assert rows[0].concentration_label == "CONCENTRATION"
        assert rows[0].portfolio_weight_pct == "100.00"

    def test_below_watch_threshold_is_ok(self):
        # Spread 7 positions equally → ~14.3% each, below 15% watch band.
        positions = [_pos(ticker=f"T{i}", market_value="10000")
                     for i in range(7)]
        rows = derive_protection_rows(positions)
        assert all(r.concentration_label == "OK" for r in rows)

    def test_watch_band_emits_watch(self):
        # 5 positions, one is 20% → WATCH; others 20% each too.
        positions = [_pos(ticker=f"T{i}", market_value="20000")
                     for i in range(5)]
        rows = derive_protection_rows(positions)
        # All 20%; each is in 15-25 band so WATCH.
        assert all(r.concentration_label == "WATCH" for r in rows)

    def test_above_threshold_concentration(self):
        positions = [
            _pos(ticker="NVDA", market_value="60000"),
            _pos(ticker="AMD", market_value="40000"),
        ]
        rows = derive_protection_rows(positions)
        nvda = next(r for r in rows if r.ticker == "NVDA")
        amd = next(r for r in rows if r.ticker == "AMD")
        assert nvda.concentration_label == "CONCENTRATION"   # 60%
        assert amd.concentration_label == "CONCENTRATION"    # 40%

    def test_cash_excluded_from_book(self):
        positions = [
            _pos(ticker="NVDA", market_value="100000"),
            _pos(ticker="USD", market_value="50000",
                  asset_type="CASH"),
        ]
        rows = derive_protection_rows(positions)
        # Only NVDA emitted — cash is excluded from investable book.
        assert len(rows) == 1
        assert rows[0].ticker == "NVDA"
        # NVDA is 100% of the investable book (CASH excluded).
        assert rows[0].portfolio_weight_pct == "100.00"

    def test_unparseable_weight_is_data_gap(self):
        positions = [_pos(ticker="NVDA", market_value="not_a_number")]
        rows = derive_protection_rows(positions)
        assert rows[0].concentration_label == "DATA_GAP"
        assert rows[0].portfolio_weight_pct == ""


class TestEngineSectorRisk:
    def test_reduce_is_sector_at_risk(self):
        rows = derive_protection_rows(
            [_pos(ticker="NVDA", sector="SEMICONDUCTOR")],
            sector_signals_by_sector={
                "SEMICONDUCTOR": _ssr(sector="SEMICONDUCTOR",
                                        signal="REDUCE"),
            },
        )
        assert rows[0].sector_risk_label == "SECTOR_AT_RISK"

    def test_exit_watch_is_sector_at_risk(self):
        rows = derive_protection_rows(
            [_pos(ticker="NVDA", sector="SEMICONDUCTOR")],
            sector_signals_by_sector={
                "SEMICONDUCTOR": _ssr(sector="SEMICONDUCTOR",
                                        signal="EXIT_WATCH"),
            },
        )
        assert rows[0].sector_risk_label == "SECTOR_AT_RISK"

    def test_avoid_new_buy_is_watch(self):
        rows = derive_protection_rows(
            [_pos(ticker="NVDA", sector="SEMICONDUCTOR")],
            sector_signals_by_sector={
                "SEMICONDUCTOR": _ssr(sector="SEMICONDUCTOR",
                                        signal="AVOID_NEW_BUY"),
            },
        )
        assert rows[0].sector_risk_label == "WATCH"

    def test_positive_canonical_with_caution_aggregation_is_watch(self):
        # The spec's headline: canonical SELECTIVE_BUY but company-derived
        # CAUTION should mention "company roll-up more cautious".
        rows = derive_protection_rows(
            [_pos(ticker="NVDA", sector="SEMICONDUCTOR")],
            sector_signals_by_sector={
                "SEMICONDUCTOR": _ssr(sector="SEMICONDUCTOR",
                                        signal="SELECTIVE_BUY"),
            },
            company_aggregations_by_sector={
                "SEMICONDUCTOR": _agg(sector="SEMICONDUCTOR",
                                        read="CAUTION"),
            },
        )
        assert rows[0].sector_risk_label == "WATCH"
        assert "more cautious" in rows[0].why_short.lower()

    def test_positive_canonical_with_bull_aggregation_is_ok(self):
        rows = derive_protection_rows(
            [_pos(ticker="NVDA", sector="SEMICONDUCTOR")],
            sector_signals_by_sector={
                "SEMICONDUCTOR": _ssr(sector="SEMICONDUCTOR",
                                        signal="SELECTIVE_BUY"),
            },
            company_aggregations_by_sector={
                "SEMICONDUCTOR": _agg(sector="SEMICONDUCTOR",
                                        read="BULL"),
            },
        )
        assert rows[0].sector_risk_label == "OK"

    def test_missing_sector_signal_is_data_gap(self):
        rows = derive_protection_rows(
            [_pos(ticker="NVDA", sector="SEMICONDUCTOR")],
        )
        # No signals supplied → DATA_GAP on the sector axis.
        assert rows[0].sector_risk_label == "DATA_GAP"


class TestEngineCompanyRisk:
    def test_bull_is_ok(self):
        rows = derive_protection_rows(
            [_pos(ticker="NVDA")],
            company_ledger_by_ticker={
                "NVDA": _lrow(ticker="NVDA", sector="SEMICONDUCTOR",
                                read="BULL"),
            },
        )
        assert rows[0].company_risk_label == "OK"

    def test_mixed_is_watch(self):
        rows = derive_protection_rows(
            [_pos(ticker="NVDA")],
            company_ledger_by_ticker={
                "NVDA": _lrow(ticker="NVDA", sector="SEMICONDUCTOR",
                                read="MIXED"),
            },
        )
        assert rows[0].company_risk_label == "WATCH"

    def test_broken_is_shared_risk_exposed(self):
        rows = derive_protection_rows(
            [_pos(ticker="NVDA")],
            company_ledger_by_ticker={
                "NVDA": _lrow(ticker="NVDA", sector="SEMICONDUCTOR",
                                read="BROKEN"),
            },
        )
        assert rows[0].company_risk_label == "SHARED_RISK_EXPOSED"

    def test_near_threshold_is_watch(self):
        rows = derive_protection_rows(
            [_pos(ticker="NVDA")],
            company_ledger_by_ticker={
                "NVDA": _lrow(ticker="NVDA", sector="SEMICONDUCTOR",
                                read="NEAR_THRESHOLD"),
            },
        )
        assert rows[0].company_risk_label == "WATCH"

    def test_missing_ledger_is_data_gap(self):
        rows = derive_protection_rows([_pos(ticker="NVDA")])
        assert rows[0].company_risk_label == "DATA_GAP"

    def test_na_ledger_read_is_data_gap(self):
        rows = derive_protection_rows(
            [_pos(ticker="NVDA")],
            company_ledger_by_ticker={
                "NVDA": _lrow(ticker="NVDA", sector="SEMICONDUCTOR",
                                read="N/A"),
            },
        )
        assert rows[0].company_risk_label == "DATA_GAP"


class TestEngineHeadlineLabel:
    """Composite tests where multiple risk axes interact."""

    def test_concentration_plus_broken_picks_concentration(self):
        # Per LABEL_PRIORITY, CONCENTRATION is worse than SHARED_RISK.
        rows = derive_protection_rows(
            [_pos(ticker="NVDA", market_value="60000"),
             _pos(ticker="AMD", market_value="40000")],
            company_ledger_by_ticker={
                "NVDA": _lrow(ticker="NVDA", sector="SEMICONDUCTOR",
                                read="BROKEN"),
            },
        )
        nvda = next(r for r in rows if r.ticker == "NVDA")
        assert nvda.protection_label == "CONCENTRATION"

    def test_sector_at_risk_beats_concentration(self):
        # SECTOR_AT_RISK comes before CONCENTRATION in priority.
        rows = derive_protection_rows(
            [_pos(ticker="NVDA", sector="SEMICONDUCTOR",
                  market_value="60000"),
             _pos(ticker="AMD", sector="SEMICONDUCTOR",
                  market_value="40000")],
            sector_signals_by_sector={
                "SEMICONDUCTOR": _ssr(sector="SEMICONDUCTOR",
                                        signal="REDUCE"),
            },
        )
        nvda = next(r for r in rows if r.ticker == "NVDA")
        assert nvda.protection_label == "SECTOR_AT_RISK"

    def test_data_gap_dominates_everything(self):
        # Missing weight (unparseable market_value) makes the whole row
        # a DATA_GAP regardless of clean signal inputs.
        rows = derive_protection_rows(
            [_pos(ticker="NVDA", market_value="not_a_number",
                  sector="SEMICONDUCTOR")],
            sector_signals_by_sector={
                "SEMICONDUCTOR": _ssr(sector="SEMICONDUCTOR",
                                        signal="SELECTIVE_BUY"),
            },
            company_ledger_by_ticker={
                "NVDA": _lrow(ticker="NVDA", sector="SEMICONDUCTOR",
                                read="BULL"),
            },
        )
        assert rows[0].protection_label == "DATA_GAP"

    def test_clean_low_weight_bull_is_ok(self):
        positions = [_pos(ticker=f"T{i}", market_value="10000")
                     for i in range(10)]
        signals = {
            "SEMICONDUCTOR": _ssr(sector="SEMICONDUCTOR",
                                    signal="SELECTIVE_BUY"),
        }
        ledger = {p.ticker: _lrow(
            ticker=p.ticker, sector="SEMICONDUCTOR", read="BULL",
        ) for p in positions}
        rows = derive_protection_rows(
            positions,
            company_ledger_by_ticker=ledger,
            sector_signals_by_sector=signals,
        )
        # 10% each → below the 15% watch band → OK across the board.
        for r in rows:
            assert r.protection_label == "OK"
            assert r.why_short == "no risk flags active"
            assert r.action_short == "—"

    def test_why_short_mentions_threshold_value(self):
        # CONCENTRATION row's why_short must call out the threshold.
        rows = derive_protection_rows(
            [_pos(ticker="NVDA", market_value="100000")],
        )
        assert f"{CONCENTRATION_THRESHOLD_PCT:.0f}%" in rows[0].why_short

    def test_action_short_is_advisory_only(self):
        # Make sure the action text never reads like an order instruction.
        rows = derive_protection_rows(
            [_pos(ticker="NVDA", market_value="100000")],
            sector_signals_by_sector={
                "SEMICONDUCTOR": _ssr(sector="SEMICONDUCTOR",
                                        signal="REDUCE"),
            },
            company_ledger_by_ticker={
                "NVDA": _lrow(ticker="NVDA", sector="SEMICONDUCTOR",
                                read="BROKEN"),
            },
        )
        forbidden = ("sell", "buy", "place", "execute",
                     "submit", "order")
        for r in rows:
            t = r.action_short.lower()
            for token in forbidden:
                assert token not in t, (
                    f"action_short {r.action_short!r} reads like an order"
                )


# --------------------------------------------------------------------------- #
# Platform helpers
# --------------------------------------------------------------------------- #
class TestPlatformHelpers:
    def _seed_positions(self, tmp_path: Path,
                         rows: list[PositionRow]) -> Path:
        pp = tmp_path / "p.csv"
        if rows:
            append_position_rows(rows, pp)
        else:
            ensure_positions_header(pp)
        return pp

    def test_load_protection_snapshot_empty(self, tmp_path: Path,
                                              platform):
        pp = tmp_path / "p.csv"
        snap = platform.load_protection_snapshot(
            positions_path=pp,
            ledger_path=tmp_path / "ledger.csv",
            signal_log_path=tmp_path / "log.csv",
            aggregation_path=tmp_path / "agg.csv",
        )
        assert snap.positions == []
        assert snap.positions_present is False
        assert snap.ledger_present is False
        assert snap.signal_log_present is False
        assert snap.aggregation_present is False

    def test_snapshot_picks_latest_as_of(self, tmp_path: Path, platform):
        pp = self._seed_positions(tmp_path, [
            _pos(ticker="NVDA", as_of="2026-06-01",
                  market_value="10000"),
            _pos(ticker="NVDA", as_of="2026-06-03",
                  market_value="60000"),
            _pos(ticker="AMD", as_of="2026-06-03",
                  market_value="40000"),
        ])
        snap = platform.load_protection_snapshot(
            positions_path=pp,
            ledger_path=tmp_path / "ledger.csv",
            signal_log_path=tmp_path / "log.csv",
            aggregation_path=tmp_path / "agg.csv",
        )
        assert snap.latest_as_of == "2026-06-03"
        assert {(p.ticker, p.market_value) for p in snap.positions} == {
            ("NVDA", "60000"), ("AMD", "40000"),
        }

    def test_compute_summary_counts(self, tmp_path: Path, platform):
        pp = self._seed_positions(tmp_path, [
            _pos(ticker="NVDA", market_value="60000"),
            _pos(ticker="AMD", market_value="40000"),
        ])
        snap = platform.load_protection_snapshot(
            positions_path=pp,
            ledger_path=tmp_path / "ledger.csv",
            signal_log_path=tmp_path / "log.csv",
            aggregation_path=tmp_path / "agg.csv",
        )
        rows = platform.derive_protection_rows_from_snapshot(snap)
        summary = platform.compute_protection_summary(snap, rows)
        assert summary.n_positions == 2
        # Both >25% -> both CONCENTRATION. Per the V7.7 headline policy,
        # a real risk on the concentration axis wins the headline even
        # when the other two axes are DATA_GAP (missing inputs).
        assert summary.n_concentration == 2
        assert summary.n_data_gap == 0

    def test_concentration_panel_top_n(self, platform):
        rows = [
            ProtectionRow(as_of=_DATE, ticker="A", sector="X",
                           portfolio_weight_pct="60.00"),
            ProtectionRow(as_of=_DATE, ticker="B", sector="X",
                           portfolio_weight_pct="30.00"),
            ProtectionRow(as_of=_DATE, ticker="C", sector="Y",
                           portfolio_weight_pct="10.00"),
        ]
        panel = platform.protection_concentration_panel(
            rows, top_n_positions=2, top_n_sectors=2,
        )
        assert panel["top_positions"] == [("A", 60.0), ("B", 30.0)]
        assert panel["top_sectors"] == [("X", 90.0), ("Y", 10.0)]

    def test_data_gaps_listed_when_missing(self, tmp_path: Path,
                                             platform):
        snap = platform.load_protection_snapshot(
            positions_path=tmp_path / "p.csv",
            ledger_path=tmp_path / "ledger.csv",
            signal_log_path=tmp_path / "log.csv",
            aggregation_path=tmp_path / "agg.csv",
        )
        gaps = platform.protection_data_gaps(snap)
        # All four sources missing → 4 gap entries.
        assert len(gaps) == 4
        assert any("positions" in g for g in gaps)
        assert any("company signal ledger" in g for g in gaps)
        assert any("sector signal log" in g for g in gaps)
        assert any("aggregation" in g for g in gaps)


# --------------------------------------------------------------------------- #
# Portfolio totals must not change because of Protection rendering.
# --------------------------------------------------------------------------- #
class TestNoEffectOnPortfolio:
    def test_compute_portfolio_totals_untouched(self, tmp_path: Path,
                                                  platform):
        from quantbot.research.portfolio import ensure_transactions_header
        pp = tmp_path / "p.csv"
        tp = tmp_path / "t.csv"
        append_position_rows([
            _pos(ticker="NVDA", market_value="60000"),
            _pos(ticker="AMD", market_value="40000"),
        ], pp)
        ensure_transactions_header(tp)
        snap = platform.load_portfolio_snapshot(pp, tp)
        before = platform.compute_portfolio_totals(snap)

        # Exercise Protection end-to-end repeatedly.
        for _ in range(5):
            psnap = platform.load_protection_snapshot(
                positions_path=pp,
                ledger_path=tmp_path / "ledger.csv",
                signal_log_path=tmp_path / "log.csv",
                aggregation_path=tmp_path / "agg.csv",
            )
            platform.derive_protection_rows_from_snapshot(psnap)

        after = platform.compute_portfolio_totals(
            platform.load_portfolio_snapshot(pp, tp),
        )
        assert before == after

    def test_score_sector_untouched(self):
        # Sanity: the canonical V6.1 score_sector signature and outputs are
        # not affected by any protection import or call.
        from quantbot.research.sector_tracker import Catalyst
        cats = [
            Catalyst(
                catalyst_id="X", sector="SEMICONDUCTOR", subsector="x",
                catalyst_name="x", tier=1, direction="ABOVE",
                threshold="t", current_value="v", status="BULL",
                source_type="SEC_EDGAR", source_detail="ok",
                last_updated="2026-05-28", action_if_broken="x",
            ),
        ]
        before = score_sector(cats, [], sector="SEMICONDUCTOR")
        # Touch every protection surface.
        derive_protection_rows([_pos(ticker="NVDA",
                                       sector="SEMICONDUCTOR")])
        after = score_sector(cats, [], sector="SEMICONDUCTOR")
        assert before.signal == after.signal
        assert before.normalized_score == after.normalized_score


# --------------------------------------------------------------------------- #
# Regression — V6 / V7.8 / V7.1 still load
# --------------------------------------------------------------------------- #
class TestRegression:
    def test_platform_module_imports(self):
        sys.path.insert(0, str(REPO_ROOT / "apps"))
        try:
            mod = importlib.import_module("portfolio_platform")
            for name in (
                "load_protection_snapshot",
                "derive_protection_rows_from_snapshot",
                "compute_protection_summary",
                "protection_concentration_panel",
                "protection_data_gaps",
                "load_portfolio_snapshot",
                "load_marketpulse_snapshot",
            ):
                assert hasattr(mod, name), f"missing helper: {name}"
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
