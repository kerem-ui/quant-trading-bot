"""V7.4 — Tests for the PortTech portfolio brain.

Covers:

  * :class:`PortTechRow` schema validation.
  * Base recommendation lookup is complete across the company-read ×
    canonical-signal grid.
  * Caution modifier (BULL + cautious agg → HOLD).
  * Concentration cap (≥ 25 % weight clamps ADD to HOLD).
  * Protection override (SECTOR_AT_RISK / SHARED_RISK_EXPOSED /
    CONCENTRATION / WATCH downgrades).
  * Missing inputs → DATA_GAP with a populated ``data_gap_note``.
  * Divergence panel surfaces the two spec'd cases.
  * Platform helpers: snapshot adapter, summary, divergences, gaps.
  * **No effect on**: Portfolio totals, Protection rows, ``score_sector``.
  * Guardrails: no broker / IBKR / order / hedge-execution / network /
    ThetaData tokens; ``LIVE_TRADING_ENABLED`` False.
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
    ensure_transactions_header,
)
from quantbot.research.porttech import (
    ALLOWED_PORTTECH_LABEL,
    BASE_RECOMMENDATION,
    CONCENTRATION_CAP_PCT,
    LABEL_PRIORITY,
    PORTTECH_ROW_FIELDS,
    PortTechRow,
    PortTechSchemaError,
    derive_porttech_rows,
)
from quantbot.research.protection import (
    ProtectionRow,
    derive_protection_rows,
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
# Guardrails (V7.4 surface only)
# --------------------------------------------------------------------------- #
class TestGuardrails:
    SCHEMA_SOURCE = (
        REPO_ROOT / "src" / "quantbot" / "research" / "porttech"
        / "schema.py"
    ).read_text(encoding="utf-8")
    ENGINE_SOURCE = (
        REPO_ROOT / "src" / "quantbot" / "research" / "porttech"
        / "engine.py"
    ).read_text(encoding="utf-8")

    def test_live_trading_disabled(self):
        assert quantbot.LIVE_TRADING_ENABLED is False

    def test_no_broker_or_order_tokens(self):
        for src in (self.SCHEMA_SOURCE, self.ENGINE_SOURCE):
            for token in ("ib_insync", "place_order", "submit_order",
                          "from broker", "import broker", "ibapi"):
                assert token not in src, (
                    f"forbidden broker token {token!r} in V7.4 surface"
                )

    def test_no_network_imports(self):
        for src in (self.SCHEMA_SOURCE, self.ENGINE_SOURCE):
            for token in ("import requests", "import urllib",
                          "import aiohttp", "import socket",
                          "from requests", "from urllib",
                          "from aiohttp", "from socket"):
                assert token not in src, (
                    f"forbidden network import {token!r} in V7.4 surface"
                )

    def test_no_thetadata_imports(self):
        for src in (self.SCHEMA_SOURCE, self.ENGINE_SOURCE):
            assert "import thetadata" not in src.lower()
            assert "from thetadata" not in src.lower()

    def test_no_hedge_or_buy_sell_execution_tokens(self):
        # PortTech is research-only; the spec forbids any execution path.
        for src in (self.SCHEMA_SOURCE, self.ENGINE_SOURCE):
            for token in ("execute_hedge", "submit_hedge",
                          "place_hedge", "hedge_order",
                          "execute_trade", "place_trade",
                          "submit_trade", "execute_order",
                          "buy_button", "sell_button"):
                assert token not in src, (
                    f"forbidden execution token {token!r} in V7.4 surface"
                )


# --------------------------------------------------------------------------- #
# Schema
# --------------------------------------------------------------------------- #
class TestSchema:
    def test_allowed_labels(self):
        assert ALLOWED_PORTTECH_LABEL == {
            "ADD", "HOLD", "TRIM", "WATCH", "EXIT_WATCH", "DATA_GAP",
        }

    def test_fields_stable(self):
        for name in (
            "as_of", "ticker", "sector", "theme", "market_value",
            "portfolio_weight_pct", "company_read",
            "canonical_sector_signal", "company_derived_sector_read",
            "protection_label", "porttech_label",
            "why_short", "action_short", "data_gap_note",
        ):
            assert name in PORTTECH_ROW_FIELDS

    def test_valid_row(self):
        r = PortTechRow(as_of=_DATE, ticker="NVDA",
                          sector="SEMICONDUCTOR",
                          porttech_label="HOLD")
        assert r.porttech_label == "HOLD"

    def test_missing_ticker_rejected(self):
        with pytest.raises(PortTechSchemaError):
            PortTechRow(as_of=_DATE, ticker="")

    def test_invalid_label_rejected(self):
        with pytest.raises(PortTechSchemaError):
            PortTechRow(as_of=_DATE, ticker="X",
                          porttech_label="WAT")

    def test_label_priority_includes_all_labels(self):
        assert set(LABEL_PRIORITY) == ALLOWED_PORTTECH_LABEL


# --------------------------------------------------------------------------- #
# Base recommendation lookup
# --------------------------------------------------------------------------- #
class TestBaseRecommendation:
    """Sanity-check pre-declared lookup table against the V7.4 spec."""

    def test_bull_accumulate_is_add(self):
        assert BASE_RECOMMENDATION[("BULL", "ACCUMULATE")] == "ADD"

    def test_bull_selective_buy_is_add(self):
        assert BASE_RECOMMENDATION[("BULL", "SELECTIVE_BUY")] == "ADD"

    def test_bull_hold_is_hold(self):
        assert BASE_RECOMMENDATION[("BULL", "HOLD")] == "HOLD"

    def test_bull_reduce_is_trim(self):
        assert BASE_RECOMMENDATION[("BULL", "REDUCE")] == "TRIM"

    def test_bull_exit_watch_is_exit_watch(self):
        assert BASE_RECOMMENDATION[("BULL", "EXIT_WATCH")] == "EXIT_WATCH"

    def test_mixed_constructive_is_watch_not_add(self):
        # Spec: MIXED never aggressive ADD.
        assert BASE_RECOMMENDATION[("MIXED", "ACCUMULATE")] == "WATCH"
        assert BASE_RECOMMENDATION[("MIXED", "SELECTIVE_BUY")] == "WATCH"

    def test_broken_anywhere_is_trim_or_exit(self):
        for sig in ("ACCUMULATE", "SELECTIVE_BUY", "HOLD",
                    "AVOID_NEW_BUY"):
            assert BASE_RECOMMENDATION[("BROKEN", sig)] == "TRIM"
        for sig in ("REDUCE", "EXIT_WATCH"):
            assert BASE_RECOMMENDATION[("BROKEN", sig)] == "EXIT_WATCH"

    def test_tracked_conservative_hold(self):
        # Tracked = manual placeholders; conservative HOLD.
        assert BASE_RECOMMENDATION[("TRACKED", "ACCUMULATE")] == "HOLD"

    def test_table_covers_full_grid(self):
        # Every combination of the six canonical signals × seven company
        # reads (BULL / NEUTRAL / MIXED / NEAR_THRESHOLD / BROKEN /
        # TRACKED) must be defined.
        signals = {"ACCUMULATE", "SELECTIVE_BUY", "HOLD",
                    "AVOID_NEW_BUY", "REDUCE", "EXIT_WATCH"}
        reads = {"BULL", "NEUTRAL", "MIXED", "NEAR_THRESHOLD",
                 "BROKEN", "TRACKED"}
        for r in reads:
            for s in signals:
                assert (r, s) in BASE_RECOMMENDATION, (
                    f"missing base recommendation for ({r}, {s})"
                )

    def test_every_base_label_in_enum(self):
        for v in BASE_RECOMMENDATION.values():
            assert v in ALLOWED_PORTTECH_LABEL


# --------------------------------------------------------------------------- #
# Engine — caution modifier
# --------------------------------------------------------------------------- #
class TestCautionModifier:
    def test_bull_plus_constructive_caution_is_hold(self):
        # NVDA BULL + SELECTIVE_BUY canonical + CAUTION aggregation →
        # base ADD would otherwise apply, but caution forces HOLD.
        rows = derive_porttech_rows(
            [_pos(ticker="NVDA", market_value="10000"),
             _pos(ticker="AMD", market_value="10000")],   # second position
            company_ledger_by_ticker={
                "NVDA": _lrow(ticker="NVDA",
                                sector="SEMICONDUCTOR", read="BULL"),
                "AMD": _lrow(ticker="AMD",
                                sector="SEMICONDUCTOR", read="BULL"),
            },
            sector_signals_by_sector={
                "SEMICONDUCTOR": _ssr(sector="SEMICONDUCTOR",
                                        signal="SELECTIVE_BUY"),
            },
            company_aggregations_by_sector={
                "SEMICONDUCTOR": _agg(sector="SEMICONDUCTOR",
                                        read="CAUTION"),
            },
        )
        nvda = next(r for r in rows if r.ticker == "NVDA")
        assert nvda.porttech_label == "HOLD"
        assert "company roll-up" in nvda.why_short.lower()

    def test_bull_plus_bull_aggregation_stays_add(self):
        # 5 equal positions × 20 % each → below the 25 % concentration
        # cap, so ADD survives all three downstream steps.
        positions = [_pos(ticker=f"T{i}", market_value="10000",
                            sector="SEMICONDUCTOR")
                     for i in range(5)]
        ledger = {p.ticker: _lrow(
            ticker=p.ticker, sector="SEMICONDUCTOR", read="BULL",
        ) for p in positions}
        rows = derive_porttech_rows(
            positions,
            company_ledger_by_ticker=ledger,
            sector_signals_by_sector={
                "SEMICONDUCTOR": _ssr(sector="SEMICONDUCTOR",
                                        signal="ACCUMULATE"),
            },
            company_aggregations_by_sector={
                "SEMICONDUCTOR": _agg(sector="SEMICONDUCTOR",
                                        read="BULL"),
            },
        )
        assert all(r.porttech_label == "ADD" for r in rows)

    def test_caution_does_not_downgrade_below_hold(self):
        # base is HOLD already → no further change.
        rows = derive_porttech_rows(
            [_pos(ticker="NVDA", market_value="10000"),
             _pos(ticker="AMD", market_value="10000")],
            company_ledger_by_ticker={
                "NVDA": _lrow(ticker="NVDA",
                                sector="SEMICONDUCTOR", read="NEUTRAL"),
                "AMD": _lrow(ticker="AMD",
                                sector="SEMICONDUCTOR", read="NEUTRAL"),
            },
            sector_signals_by_sector={
                "SEMICONDUCTOR": _ssr(sector="SEMICONDUCTOR",
                                        signal="ACCUMULATE"),
            },
            company_aggregations_by_sector={
                "SEMICONDUCTOR": _agg(sector="SEMICONDUCTOR",
                                        read="CAUTION"),
            },
        )
        nvda = next(r for r in rows if r.ticker == "NVDA")
        assert nvda.porttech_label == "HOLD"


# --------------------------------------------------------------------------- #
# Engine — concentration cap
# --------------------------------------------------------------------------- #
class TestConcentrationCap:
    def test_single_position_bull_caps_to_hold(self):
        # 100% weight → ADD must be capped to HOLD.
        rows = derive_porttech_rows(
            [_pos(ticker="NVDA", market_value="10000")],
            company_ledger_by_ticker={
                "NVDA": _lrow(ticker="NVDA",
                                sector="SEMICONDUCTOR", read="BULL"),
            },
            sector_signals_by_sector={
                "SEMICONDUCTOR": _ssr(sector="SEMICONDUCTOR",
                                        signal="ACCUMULATE"),
            },
        )
        assert rows[0].porttech_label == "HOLD"
        assert "caps ADD to HOLD" in rows[0].why_short

    def test_below_cap_keeps_add(self):
        # 5 positions × 20 % each → below 25 % cap. ADD survives.
        positions = [_pos(ticker=f"T{i}", market_value="20000",
                            sector="SEMICONDUCTOR")
                     for i in range(5)]
        ledger = {p.ticker: _lrow(
            ticker=p.ticker, sector="SEMICONDUCTOR", read="BULL",
        ) for p in positions}
        rows = derive_porttech_rows(
            positions,
            company_ledger_by_ticker=ledger,
            sector_signals_by_sector={
                "SEMICONDUCTOR": _ssr(sector="SEMICONDUCTOR",
                                        signal="ACCUMULATE"),
            },
        )
        # 20% < 25% → ADD passes; no cap fires.
        assert all(r.porttech_label == "ADD" for r in rows)

    def test_cap_only_affects_add(self):
        # Single MIXED position would be WATCH (base) — cap shouldn't
        # touch it.
        rows = derive_porttech_rows(
            [_pos(ticker="NVDA", market_value="10000")],
            company_ledger_by_ticker={
                "NVDA": _lrow(ticker="NVDA",
                                sector="SEMICONDUCTOR", read="MIXED"),
            },
            sector_signals_by_sector={
                "SEMICONDUCTOR": _ssr(sector="SEMICONDUCTOR",
                                        signal="SELECTIVE_BUY"),
            },
        )
        assert rows[0].porttech_label == "WATCH"


# --------------------------------------------------------------------------- #
# Engine — protection override
# --------------------------------------------------------------------------- #
class TestProtectionOverride:
    def _prot(self, *, ticker: str, label: str,
              sector: str = "SEMICONDUCTOR") -> ProtectionRow:
        return ProtectionRow(
            as_of=_DATE, ticker=ticker, sector=sector,
            protection_label=label,
        )

    def test_sector_at_risk_downgrades_add_to_watch(self):
        # Build a scenario where base would be ADD: BULL + ACCUMULATE.
        # Then inject a SECTOR_AT_RISK protection label → WATCH.
        rows = derive_porttech_rows(
            [_pos(ticker="NVDA", market_value="10000"),
             _pos(ticker="AMD", market_value="10000")],   # avoid 100% cap
            company_ledger_by_ticker={
                "NVDA": _lrow(ticker="NVDA",
                                sector="SEMICONDUCTOR", read="BULL"),
                "AMD": _lrow(ticker="AMD",
                                sector="SEMICONDUCTOR", read="BULL"),
            },
            sector_signals_by_sector={
                "SEMICONDUCTOR": _ssr(sector="SEMICONDUCTOR",
                                        signal="ACCUMULATE"),
            },
            protection_rows_by_ticker={
                "NVDA": self._prot(ticker="NVDA",
                                     label="SECTOR_AT_RISK"),
            },
        )
        nvda = next(r for r in rows if r.ticker == "NVDA")
        assert nvda.porttech_label == "WATCH"

    def test_shared_risk_exposed_downgrades_add_to_trim(self):
        # 5 equal positions × 20 % each → NVDA stays under the
        # concentration cap; the only override is SHARED_RISK_EXPOSED.
        positions = [_pos(ticker=f"T{i}", market_value="10000",
                            sector="SEMICONDUCTOR")
                     for i in range(5)]
        ledger = {p.ticker: _lrow(
            ticker=p.ticker, sector="SEMICONDUCTOR", read="BULL",
        ) for p in positions}
        rows = derive_porttech_rows(
            positions,
            company_ledger_by_ticker=ledger,
            sector_signals_by_sector={
                "SEMICONDUCTOR": _ssr(sector="SEMICONDUCTOR",
                                        signal="ACCUMULATE"),
            },
            protection_rows_by_ticker={
                "T0": self._prot(ticker="T0",
                                    label="SHARED_RISK_EXPOSED"),
            },
        )
        t0 = next(r for r in rows if r.ticker == "T0")
        assert t0.porttech_label == "TRIM"
        # Other positions stay ADD (no protection override applied).
        for r in rows:
            if r.ticker != "T0":
                assert r.porttech_label == "ADD"

    def test_concentration_protection_caps_add(self):
        rows = derive_porttech_rows(
            [_pos(ticker="NVDA", market_value="10000"),
             _pos(ticker="AMD", market_value="10000")],
            company_ledger_by_ticker={
                "NVDA": _lrow(ticker="NVDA",
                                sector="SEMICONDUCTOR", read="BULL"),
                "AMD": _lrow(ticker="AMD",
                                sector="SEMICONDUCTOR", read="BULL"),
            },
            sector_signals_by_sector={
                "SEMICONDUCTOR": _ssr(sector="SEMICONDUCTOR",
                                        signal="ACCUMULATE"),
            },
            protection_rows_by_ticker={
                "NVDA": self._prot(ticker="NVDA",
                                     label="CONCENTRATION"),
            },
        )
        nvda = next(r for r in rows if r.ticker == "NVDA")
        assert nvda.porttech_label == "HOLD"

    def test_ok_protection_does_not_change(self):
        # 5 equal positions × 20 % each → no concentration cap fires.
        positions = [_pos(ticker=f"T{i}", market_value="10000",
                            sector="SEMICONDUCTOR")
                     for i in range(5)]
        ledger = {p.ticker: _lrow(
            ticker=p.ticker, sector="SEMICONDUCTOR", read="BULL",
        ) for p in positions}
        rows = derive_porttech_rows(
            positions,
            company_ledger_by_ticker=ledger,
            sector_signals_by_sector={
                "SEMICONDUCTOR": _ssr(sector="SEMICONDUCTOR",
                                        signal="ACCUMULATE"),
            },
            protection_rows_by_ticker={
                "T0": self._prot(ticker="T0", label="OK"),
            },
        )
        t0 = next(r for r in rows if r.ticker == "T0")
        assert t0.porttech_label == "ADD"


# --------------------------------------------------------------------------- #
# Engine — DATA_GAP branches
# --------------------------------------------------------------------------- #
class TestDataGap:
    def test_missing_company_read_is_data_gap(self):
        rows = derive_porttech_rows(
            [_pos(ticker="NVDA", market_value="10000"),
             _pos(ticker="AMD", market_value="10000")],
            sector_signals_by_sector={
                "SEMICONDUCTOR": _ssr(sector="SEMICONDUCTOR",
                                        signal="ACCUMULATE"),
            },
        )
        assert all(r.porttech_label == "DATA_GAP" for r in rows)
        assert all("company ledger read" in r.data_gap_note
                   for r in rows)

    def test_missing_canonical_signal_is_data_gap(self):
        rows = derive_porttech_rows(
            [_pos(ticker="NVDA", market_value="10000"),
             _pos(ticker="AMD", market_value="10000")],
            company_ledger_by_ticker={
                "NVDA": _lrow(ticker="NVDA",
                                sector="SEMICONDUCTOR", read="BULL"),
                "AMD": _lrow(ticker="AMD",
                                sector="SEMICONDUCTOR", read="BULL"),
            },
        )
        assert all(r.porttech_label == "DATA_GAP" for r in rows)
        assert all("canonical sector signal" in r.data_gap_note
                   for r in rows)

    def test_unparseable_market_value_is_data_gap(self):
        rows = derive_porttech_rows(
            [_pos(ticker="NVDA", market_value="not_a_number")],
            company_ledger_by_ticker={
                "NVDA": _lrow(ticker="NVDA",
                                sector="SEMICONDUCTOR", read="BULL"),
            },
            sector_signals_by_sector={
                "SEMICONDUCTOR": _ssr(sector="SEMICONDUCTOR",
                                        signal="ACCUMULATE"),
            },
        )
        assert rows[0].porttech_label == "DATA_GAP"
        assert "portfolio weight" in rows[0].data_gap_note

    def test_na_company_read_is_data_gap(self):
        rows = derive_porttech_rows(
            [_pos(ticker="OpenAI", market_value="10000"),
             _pos(ticker="Anthropic", market_value="10000")],
            company_ledger_by_ticker={
                "OpenAI": _lrow(ticker="OpenAI",
                                  sector="SEMICONDUCTOR", read="N/A"),
                "Anthropic": _lrow(ticker="Anthropic",
                                     sector="SEMICONDUCTOR", read="N/A"),
            },
            sector_signals_by_sector={
                "SEMICONDUCTOR": _ssr(sector="SEMICONDUCTOR",
                                        signal="ACCUMULATE"),
            },
        )
        for r in rows:
            assert r.porttech_label == "DATA_GAP"


# --------------------------------------------------------------------------- #
# Engine — composite scenarios
# --------------------------------------------------------------------------- #
class TestComposite:
    def test_cash_excluded(self):
        rows = derive_porttech_rows(
            [_pos(ticker="NVDA", market_value="60000"),
             _pos(ticker="USD", market_value="40000",
                  asset_type="CASH")],
            company_ledger_by_ticker={
                "NVDA": _lrow(ticker="NVDA",
                                sector="SEMICONDUCTOR", read="BULL"),
            },
            sector_signals_by_sector={
                "SEMICONDUCTOR": _ssr(sector="SEMICONDUCTOR",
                                        signal="ACCUMULATE"),
            },
        )
        assert len(rows) == 1
        assert rows[0].ticker == "NVDA"

    def test_action_short_advisory_only(self):
        # Spec: action_short must NEVER read like an order instruction.
        rows = derive_porttech_rows(
            [_pos(ticker="NVDA", market_value="10000"),
             _pos(ticker="AMD", market_value="10000")],
            company_ledger_by_ticker={
                "NVDA": _lrow(ticker="NVDA",
                                sector="SEMICONDUCTOR", read="BROKEN"),
                "AMD": _lrow(ticker="AMD",
                                sector="SEMICONDUCTOR", read="BULL"),
            },
            sector_signals_by_sector={
                "SEMICONDUCTOR": _ssr(sector="SEMICONDUCTOR",
                                        signal="ACCUMULATE"),
            },
        )
        for r in rows:
            assert "research-only" in r.action_short.lower() or \
                r.action_short.startswith("populate")
            # No order verbs.
            forbidden = ("place ", "submit ", "execute ",
                         "buy ", "sell ")
            t = r.action_short.lower()
            for token in forbidden:
                assert token not in t, (
                    f"action_short {r.action_short!r} reads like an order"
                )

    def test_broken_company_in_constructive_sector_is_trim(self):
        # Even SELECTIVE_BUY canonical can't save a BROKEN ledger row.
        rows = derive_porttech_rows(
            [_pos(ticker="NVDA", market_value="10000"),
             _pos(ticker="AMD", market_value="10000")],
            company_ledger_by_ticker={
                "NVDA": _lrow(ticker="NVDA",
                                sector="SEMICONDUCTOR", read="BROKEN"),
                "AMD": _lrow(ticker="AMD",
                                sector="SEMICONDUCTOR", read="BULL"),
            },
            sector_signals_by_sector={
                "SEMICONDUCTOR": _ssr(sector="SEMICONDUCTOR",
                                        signal="SELECTIVE_BUY"),
            },
        )
        nvda = next(r for r in rows if r.ticker == "NVDA")
        assert nvda.porttech_label == "TRIM"

    def test_reduce_canonical_pushes_bull_to_trim(self):
        rows = derive_porttech_rows(
            [_pos(ticker="NVDA", market_value="10000"),
             _pos(ticker="AMD", market_value="10000")],
            company_ledger_by_ticker={
                "NVDA": _lrow(ticker="NVDA",
                                sector="SEMICONDUCTOR", read="BULL"),
                "AMD": _lrow(ticker="AMD",
                                sector="SEMICONDUCTOR", read="BULL"),
            },
            sector_signals_by_sector={
                "SEMICONDUCTOR": _ssr(sector="SEMICONDUCTOR",
                                        signal="REDUCE"),
            },
        )
        for r in rows:
            assert r.porttech_label == "TRIM"

    def test_real_v77_protection_integration(self):
        # End-to-end with a real ProtectionRow (not a synthetic one).
        positions = [_pos(ticker="NVDA", market_value="60000"),
                      _pos(ticker="AMD", market_value="40000")]
        ledger = {
            "NVDA": _lrow(ticker="NVDA",
                            sector="SEMICONDUCTOR", read="BROKEN"),
            "AMD": _lrow(ticker="AMD",
                            sector="SEMICONDUCTOR", read="BULL"),
        }
        signals = {
            "SEMICONDUCTOR": _ssr(sector="SEMICONDUCTOR",
                                    signal="SELECTIVE_BUY"),
        }
        prot_rows = derive_protection_rows(
            positions,
            company_ledger_by_ticker=ledger,
            sector_signals_by_sector=signals,
        )
        prot_by_ticker = {r.ticker: r for r in prot_rows}
        # NVDA: BROKEN + over-25% weight → SHARED_RISK_EXPOSED in V7.7.
        # PortTech: base TRIM (BROKEN + SELECTIVE_BUY).
        rows = derive_porttech_rows(
            positions,
            company_ledger_by_ticker=ledger,
            sector_signals_by_sector=signals,
            protection_rows_by_ticker=prot_by_ticker,
        )
        nvda = next(r for r in rows if r.ticker == "NVDA")
        # NVDA gets TRIM either way (base + SHARED_RISK doesn't push it
        # below TRIM).
        assert nvda.porttech_label == "TRIM"


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

    def test_summary_counts(self, tmp_path: Path, platform):
        pp = self._seed_positions(tmp_path, [
            _pos(ticker="NVDA", market_value="20000"),
            _pos(ticker="AMD", market_value="20000"),
        ])
        snap = platform.load_protection_snapshot(
            positions_path=pp,
            ledger_path=tmp_path / "ledger.csv",
            signal_log_path=tmp_path / "log.csv",
            aggregation_path=tmp_path / "agg.csv",
        )
        rows = platform.derive_porttech_rows_from_snapshot(snap, None)
        summary = platform.compute_porttech_summary(rows)
        # No ledger / no signal → DATA_GAP for both.
        assert summary.n_data_gap == 2

    def test_divergence_constructive_vs_cautious(self, platform):
        rows = [
            PortTechRow(
                as_of=_DATE, ticker="NVDA", sector="SEMICONDUCTOR",
                company_read="BULL",
                canonical_sector_signal="SELECTIVE_BUY",
                company_derived_sector_read="CAUTION",
                porttech_label="HOLD",
            ),
            PortTechRow(
                as_of=_DATE, ticker="MSFT", sector="AI",
                company_read="BULL",
                canonical_sector_signal="ACCUMULATE",
                company_derived_sector_read="BULL",
                porttech_label="ADD",
            ),
        ]
        divs = platform.porttech_divergences(rows)
        case_a = divs["constructive_canonical_cautious_company_derived"]
        assert {r.ticker for r in case_a} == {"NVDA"}

    def test_divergence_company_disagrees_with_sector(self, platform):
        rows = [
            PortTechRow(
                as_of=_DATE, ticker="NVDA", sector="SEMICONDUCTOR",
                company_read="BROKEN",
                canonical_sector_signal="SELECTIVE_BUY",
                company_derived_sector_read="BULL",
                porttech_label="TRIM",
            ),
            PortTechRow(
                as_of=_DATE, ticker="MSFT", sector="AI",
                company_read="BULL",
                canonical_sector_signal="ACCUMULATE",
                porttech_label="ADD",
            ),
        ]
        divs = platform.porttech_divergences(rows)
        case_b = divs["company_disagrees_with_sector"]
        assert {r.ticker for r in case_b} == {"NVDA"}

    def test_gaps_listed(self, platform):
        rows = [
            PortTechRow(
                as_of=_DATE, ticker="X",
                porttech_label="DATA_GAP",
                data_gap_note="missing: company ledger read",
            ),
        ]
        gaps = platform.porttech_data_gaps(rows)
        assert any("DATA_GAP" in g for g in gaps)
        assert any("missing" in g for g in gaps)

    def test_empty_rows_have_no_gap_lines(self, platform):
        assert platform.porttech_data_gaps([]) == []


# --------------------------------------------------------------------------- #
# Regression: V7.4 must not affect Portfolio totals, Protection rows, or
# canonical sector scoring.
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
        # Exercise PortTech end-to-end repeatedly.
        for _ in range(5):
            snap = platform.load_protection_snapshot(
                positions_path=pp,
                ledger_path=tmp_path / "ledger.csv",
                signal_log_path=tmp_path / "log.csv",
                aggregation_path=tmp_path / "agg.csv",
            )
            prot = platform.derive_protection_rows_from_snapshot(snap)
            platform.derive_porttech_rows_from_snapshot(snap, prot)
        after = platform.compute_portfolio_totals(
            platform.load_portfolio_snapshot(pp, tp),
        )
        assert before == after

    def test_protection_rows_unchanged(self, tmp_path: Path, platform):
        pp = tmp_path / "p.csv"
        append_position_rows([
            _pos(ticker="NVDA", market_value="60000"),
            _pos(ticker="AMD", market_value="40000"),
        ], pp)
        snap = platform.load_protection_snapshot(
            positions_path=pp,
            ledger_path=tmp_path / "ledger.csv",
            signal_log_path=tmp_path / "log.csv",
            aggregation_path=tmp_path / "agg.csv",
        )
        prot_before = [
            r.to_dict() for r in
            platform.derive_protection_rows_from_snapshot(snap)
        ]
        # Build a PortTech result; this must NOT mutate the snapshot.
        platform.derive_porttech_rows_from_snapshot(snap, None)
        prot_after = [
            r.to_dict() for r in
            platform.derive_protection_rows_from_snapshot(snap)
        ]
        assert prot_before == prot_after

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
        derive_porttech_rows(
            [_pos(ticker="NVDA", market_value="10000"),
             _pos(ticker="AMD", market_value="10000")],
            company_ledger_by_ticker={
                "NVDA": _lrow(ticker="NVDA",
                                sector="SEMICONDUCTOR", read="BULL"),
                "AMD": _lrow(ticker="AMD",
                                sector="SEMICONDUCTOR", read="BULL"),
            },
            sector_signals_by_sector={
                "SEMICONDUCTOR": _ssr(sector="SEMICONDUCTOR",
                                        signal="ACCUMULATE"),
            },
        )
        after = score_sector(cats, [], sector="SEMICONDUCTOR")
        assert before.signal == after.signal
        assert before.normalized_score == after.normalized_score


# --------------------------------------------------------------------------- #
# Regression — V6 / V7.8 / V7.1 / V7.7 still load
# --------------------------------------------------------------------------- #
class TestRegression:
    def test_platform_module_imports(self):
        sys.path.insert(0, str(REPO_ROOT / "apps"))
        try:
            mod = importlib.import_module("portfolio_platform")
            for name in (
                "derive_porttech_rows_from_snapshot",
                "compute_porttech_summary",
                "porttech_divergences",
                "porttech_data_gaps",
                "load_protection_snapshot",
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
