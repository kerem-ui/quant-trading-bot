"""V7.1 — Tests for the portfolio CSV schema, readers, and platform helpers.

Covers:

  * :class:`PositionRow` / :class:`TransactionRow` schema validation
    (required fields, enums, ISO date check).
  * Readers handle missing / header-only / populated CSVs.
  * ``ensure_*_header`` idempotence; ``append_*_rows`` modes.
  * Platform helpers: ``load_portfolio_snapshot``,
    ``compute_portfolio_totals``, ``compute_allocations``,
    ``latest_positions``, ``portfolio_data_gaps``.
  * Numeric-parsing fallback: any unparseable string in a contributing
    row yields ``"n/a"`` rather than silently skipping or fabricating.
  * Guardrails: no broker / IBKR / network / ThetaData tokens in the new
    surfaces; ``LIVE_TRADING_ENABLED`` False.
"""

from __future__ import annotations

import csv
import importlib
import sys
from pathlib import Path

import pytest

import quantbot
from quantbot.research.portfolio import (
    ALLOWED_ASSET_TYPE,
    ALLOWED_TRANSACTION_SIDE,
    POSITION_FIELDS,
    TRANSACTION_FIELDS,
    PortfolioSchemaError,
    PositionRow,
    TransactionRow,
    append_position_rows,
    append_transaction_rows,
    ensure_positions_header,
    ensure_transactions_header,
    load_positions,
    load_transactions,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture
def platform():
    sys.path.insert(0, str(REPO_ROOT / "apps"))
    try:
        yield importlib.import_module("portfolio_platform")
    finally:
        if str(REPO_ROOT / "apps") in sys.path:
            sys.path.remove(str(REPO_ROOT / "apps"))


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #
class TestEnums:
    def test_asset_types(self):
        assert ALLOWED_ASSET_TYPE == {
            "STOCK", "ETF", "OPTION", "FUTURE", "BOND",
            "CASH", "OTHER", "N_A",
        }

    def test_transaction_sides(self):
        assert ALLOWED_TRANSACTION_SIDE == {
            "BUY", "SELL", "DIVIDEND", "FEE",
            "TRANSFER_IN", "TRANSFER_OUT", "OTHER",
        }

    def test_fields_stable(self):
        assert POSITION_FIELDS[:3] == ("as_of", "account", "ticker")
        for f in ("asset_type", "quantity", "market_value",
                  "unrealized_pnl", "sector", "theme"):
            assert f in POSITION_FIELDS
        assert TRANSACTION_FIELDS[:4] == ("date", "account",
                                            "ticker", "side")
        for f in ("quantity", "price", "fees", "linked_thesis"):
            assert f in TRANSACTION_FIELDS


# --------------------------------------------------------------------------- #
# PositionRow
# --------------------------------------------------------------------------- #
class TestPositionRow:
    def _kwargs(self, **over):
        base = dict(
            as_of="2026-06-03", account="MAIN", ticker="NVDA",
            company_name="NVIDIA Corp", asset_type="STOCK",
            quantity="100", average_cost="450.00",
            last_price="510.00", market_value="51000.00",
            unrealized_pnl="6000.00", realized_pnl="0.00",
            currency="USD", sector="SEMICONDUCTOR",
            theme="AI accelerator", source="MANUAL",
            notes="",
        )
        base.update(over)
        return base

    def test_valid_constructs(self):
        r = PositionRow(**self._kwargs())
        assert r.ticker == "NVDA"
        assert r.asset_type == "STOCK"

    @pytest.mark.parametrize("missing",
                              ["as_of", "account", "ticker"])
    def test_required_non_empty(self, missing):
        with pytest.raises(PortfolioSchemaError):
            PositionRow(**self._kwargs(**{missing: ""}))

    def test_invalid_asset_type_rejected(self):
        with pytest.raises(PortfolioSchemaError):
            PositionRow(**self._kwargs(asset_type="WAT"))

    def test_invalid_iso_date_rejected(self):
        with pytest.raises(PortfolioSchemaError):
            PositionRow(**self._kwargs(as_of="2026-13-99"))

    def test_defaults_safe(self):
        # Only the three required fields supplied — everything else
        # defaults to safe blank / N_A / USD.
        r = PositionRow(as_of="2026-06-03", account="MAIN", ticker="X")
        assert r.asset_type == "N_A"
        assert r.currency == "USD"


# --------------------------------------------------------------------------- #
# TransactionRow
# --------------------------------------------------------------------------- #
class TestTransactionRow:
    def _kwargs(self, **over):
        base = dict(
            date="2026-06-03", account="MAIN", ticker="NVDA",
            side="BUY", quantity="100", price="450.00",
            fees="1.00", currency="USD",
            reason="thesis BULL", linked_thesis="SEMI-NVDA-REV-T1",
            source="MANUAL", notes="",
        )
        base.update(over)
        return base

    def test_valid_constructs(self):
        r = TransactionRow(**self._kwargs())
        assert r.side == "BUY"
        assert r.linked_thesis == "SEMI-NVDA-REV-T1"

    @pytest.mark.parametrize("missing",
                              ["date", "account", "ticker", "side"])
    def test_required_non_empty(self, missing):
        with pytest.raises(PortfolioSchemaError):
            TransactionRow(**self._kwargs(**{missing: ""}))

    def test_invalid_side_rejected(self):
        with pytest.raises(PortfolioSchemaError):
            TransactionRow(**self._kwargs(side="WAT"))

    def test_invalid_iso_date_rejected(self):
        with pytest.raises(PortfolioSchemaError):
            TransactionRow(**self._kwargs(date="not a date"))


# --------------------------------------------------------------------------- #
# Readers
# --------------------------------------------------------------------------- #
class TestReaders:
    def test_missing_returns_empty(self, tmp_path: Path):
        assert load_positions(tmp_path / "nope.csv") == []
        assert load_transactions(tmp_path / "nope.csv") == []

    def test_header_only_returns_empty(self, tmp_path: Path):
        pp = tmp_path / "p.csv"
        tp = tmp_path / "t.csv"
        ensure_positions_header(pp)
        ensure_transactions_header(tp)
        assert load_positions(pp) == []
        assert load_transactions(tp) == []

    def test_round_trip_positions(self, tmp_path: Path):
        p = tmp_path / "p.csv"
        ensure_positions_header(p)
        with p.open("a", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(POSITION_FIELDS))
            writer.writerow({
                "as_of": "2026-06-03", "account": "MAIN",
                "ticker": "NVDA", "company_name": "NVIDIA",
                "asset_type": "STOCK", "quantity": "100",
                "average_cost": "450.00", "last_price": "510.00",
                "market_value": "51000.00", "unrealized_pnl": "6000.00",
                "realized_pnl": "0.00", "currency": "USD",
                "sector": "SEMICONDUCTOR", "theme": "AI accelerator",
                "source": "MANUAL", "notes": "",
            })
        rows = load_positions(p)
        assert len(rows) == 1
        assert rows[0].sector == "SEMICONDUCTOR"

    def test_ensure_header_idempotent(self, tmp_path: Path):
        p = tmp_path / "p.csv"
        ensure_positions_header(p)
        original = p.read_bytes()
        ensure_positions_header(p)  # second call -> no-op
        assert p.read_bytes() == original


# --------------------------------------------------------------------------- #
# Append helpers
# --------------------------------------------------------------------------- #
class TestAppendHelpers:
    def test_invalid_mode(self, tmp_path: Path):
        with pytest.raises(ValueError):
            append_position_rows(
                [PositionRow(as_of="2026-06-03",
                              account="MAIN", ticker="X")],
                tmp_path / "p.csv", mode="bogus",
            )

    def test_idempotent_position_by_as_of_account_ticker(
        self, tmp_path: Path,
    ):
        p = tmp_path / "p.csv"
        rows = [PositionRow(as_of="2026-06-03",
                              account="MAIN", ticker="NVDA")]
        append_position_rows(rows, p)
        r2 = append_position_rows(rows, p)
        assert r2["n_skipped"] == 1

    def test_idempotent_transaction_by_composite_key(self, tmp_path: Path):
        p = tmp_path / "t.csv"
        rows = [TransactionRow(date="2026-06-03",
                                  account="MAIN", ticker="NVDA",
                                  side="BUY", quantity="100")]
        append_transaction_rows(rows, p)
        r2 = append_transaction_rows(rows, p)
        assert r2["n_skipped"] == 1

    def test_strict_mode_raises(self, tmp_path: Path):
        p = tmp_path / "p.csv"
        rows = [PositionRow(as_of="2026-06-03",
                              account="MAIN", ticker="NVDA")]
        append_position_rows(rows, p)
        with pytest.raises(PortfolioSchemaError):
            append_position_rows(rows, p, mode="strict")

    def test_append_mode_duplicates(self, tmp_path: Path):
        p = tmp_path / "p.csv"
        rows = [PositionRow(as_of="2026-06-03",
                              account="MAIN", ticker="NVDA")]
        append_position_rows(rows, p)
        append_position_rows(rows, p, mode="append")
        assert len(load_positions(p)) == 2

    def test_append_only_preserves_prior_bytes(self, tmp_path: Path):
        p = tmp_path / "p.csv"
        append_position_rows(
            [PositionRow(as_of="2026-06-03",
                          account="MAIN", ticker="NVDA")],
            p,
        )
        original = p.read_bytes()
        append_position_rows(
            [PositionRow(as_of="2026-06-04",
                          account="MAIN", ticker="NVDA")],
            p,
        )
        append_position_rows(
            [PositionRow(as_of="2026-06-03",
                          account="MAIN", ticker="NVDA")],
            p,
        )
        assert p.read_bytes().startswith(original)


# --------------------------------------------------------------------------- #
# Platform helpers — totals & allocations
# --------------------------------------------------------------------------- #
class TestPlatformHelpers:
    def _seed(self, tmp_path: Path,
               position_rows: list[PositionRow],
               transaction_rows: list[TransactionRow] | None = None,
               ) -> tuple[Path, Path]:
        pp = tmp_path / "p.csv"
        tp = tmp_path / "t.csv"
        if position_rows:
            append_position_rows(position_rows, pp)
        else:
            ensure_positions_header(pp)
        if transaction_rows:
            append_transaction_rows(transaction_rows, tp)
        else:
            ensure_transactions_header(tp)
        return pp, tp

    def test_empty_snapshot_totals_are_na(self, tmp_path: Path, platform):
        pp, tp = self._seed(tmp_path, [], [])
        snap = platform.load_portfolio_snapshot(pp, tp)
        totals = platform.compute_portfolio_totals(snap)
        assert totals.total_market_value == "n/a"
        assert totals.cash == "n/a"
        assert totals.n_positions == 0
        assert totals.n_transactions == 0

    def test_latest_positions_filter_by_as_of(self, tmp_path: Path,
                                                platform):
        pp, tp = self._seed(tmp_path, [
            PositionRow(as_of="2026-06-01", account="MAIN",
                         ticker="NVDA", market_value="40000",
                         asset_type="STOCK"),
            PositionRow(as_of="2026-06-03", account="MAIN",
                         ticker="NVDA", market_value="51000",
                         asset_type="STOCK"),
            PositionRow(as_of="2026-06-03", account="MAIN",
                         ticker="AMD", market_value="20000",
                         asset_type="STOCK"),
        ], [])
        snap = platform.load_portfolio_snapshot(pp, tp)
        assert snap.latest_as_of == "2026-06-03"
        latest = platform.latest_positions(snap)
        # The 2026-06-01 NVDA row is excluded.
        assert {(p.ticker, p.market_value) for p in latest} == {
            ("NVDA", "51000"), ("AMD", "20000"),
        }

    def test_totals_clean_numeric(self, tmp_path: Path, platform):
        pp, tp = self._seed(tmp_path, [
            PositionRow(as_of="2026-06-03", account="MAIN",
                         ticker="NVDA", market_value="51000.00",
                         unrealized_pnl="6000.00",
                         realized_pnl="0",
                         asset_type="STOCK", currency="USD"),
            PositionRow(as_of="2026-06-03", account="MAIN",
                         ticker="AMD", market_value="20000.00",
                         unrealized_pnl="1000.00",
                         realized_pnl="0",
                         asset_type="STOCK", currency="USD"),
            PositionRow(as_of="2026-06-03", account="MAIN",
                         ticker="USD", market_value="5000.00",
                         asset_type="CASH", currency="USD"),
        ], [])
        snap = platform.load_portfolio_snapshot(pp, tp)
        totals = platform.compute_portfolio_totals(snap)
        # Non-cash market value totals: 51000 + 20000 = 71000
        assert "71,000.00" in totals.total_market_value
        # Unrealized PnL: 6000 + 1000 = 7000
        assert "7,000.00" in totals.total_unrealized_pnl
        # Cash: 5000
        assert "5,000.00" in totals.cash
        # 3 positions total (2 non-cash + 1 cash).
        assert totals.n_positions == 3
        assert totals.n_non_cash_positions == 2
        assert totals.currency_hint == "USD"

    def test_totals_na_when_any_field_unparseable(self, tmp_path: Path,
                                                    platform):
        pp, tp = self._seed(tmp_path, [
            PositionRow(as_of="2026-06-03", account="MAIN",
                         ticker="NVDA", market_value="51000",
                         asset_type="STOCK"),
            PositionRow(as_of="2026-06-03", account="MAIN",
                         ticker="AMD", market_value="not_a_number",
                         asset_type="STOCK"),
        ], [])
        snap = platform.load_portfolio_snapshot(pp, tp)
        totals = platform.compute_portfolio_totals(snap)
        # One row didn't parse cleanly -> aggregate is n/a (never invented).
        assert totals.total_market_value == "n/a"

    def test_money_format_handles_commas_and_dollar_signs(self, tmp_path: Path,
                                                            platform):
        pp, tp = self._seed(tmp_path, [
            PositionRow(as_of="2026-06-03", account="MAIN",
                         ticker="NVDA", market_value="$51,000.00",
                         asset_type="STOCK"),
        ], [])
        snap = platform.load_portfolio_snapshot(pp, tp)
        totals = platform.compute_portfolio_totals(snap)
        assert "51,000.00" in totals.total_market_value

    def test_allocations_by_sector_and_theme(self, tmp_path: Path,
                                               platform):
        pp, tp = self._seed(tmp_path, [
            PositionRow(as_of="2026-06-03", account="MAIN",
                         ticker="NVDA", market_value="60000",
                         asset_type="STOCK",
                         sector="SEMICONDUCTOR", theme="AI accelerator"),
            PositionRow(as_of="2026-06-03", account="MAIN",
                         ticker="MSFT", market_value="40000",
                         asset_type="STOCK",
                         sector="AI", theme="hyperscaler"),
        ], [])
        snap = platform.load_portfolio_snapshot(pp, tp)
        allocs = platform.compute_allocations(snap)
        assert allocs["by_sector"]["SEMICONDUCTOR"] == pytest.approx(0.60)
        assert allocs["by_sector"]["AI"] == pytest.approx(0.40)
        assert allocs["by_theme"]["AI accelerator"] == pytest.approx(0.60)

    def test_allocations_empty_when_any_market_value_blank(
        self, tmp_path: Path, platform,
    ):
        pp, tp = self._seed(tmp_path, [
            PositionRow(as_of="2026-06-03", account="MAIN",
                         ticker="NVDA", market_value="60000",
                         asset_type="STOCK"),
            PositionRow(as_of="2026-06-03", account="MAIN",
                         ticker="MSFT", market_value="",
                         asset_type="STOCK"),
        ], [])
        snap = platform.load_portfolio_snapshot(pp, tp)
        allocs = platform.compute_allocations(snap)
        assert allocs == {"by_sector": {}, "by_theme": {}}

    def test_allocations_excludes_cash(self, tmp_path: Path, platform):
        pp, tp = self._seed(tmp_path, [
            PositionRow(as_of="2026-06-03", account="MAIN",
                         ticker="NVDA", market_value="60000",
                         asset_type="STOCK", sector="SEMICONDUCTOR"),
            PositionRow(as_of="2026-06-03", account="MAIN",
                         ticker="USD", market_value="40000",
                         asset_type="CASH"),
        ], [])
        snap = platform.load_portfolio_snapshot(pp, tp)
        allocs = platform.compute_allocations(snap)
        # Cash is excluded so NVDA is 100% of allocatable book.
        assert allocs["by_sector"]["SEMICONDUCTOR"] == pytest.approx(1.0)

    def test_unlabelled_bucket(self, tmp_path: Path, platform):
        pp, tp = self._seed(tmp_path, [
            PositionRow(as_of="2026-06-03", account="MAIN",
                         ticker="X", market_value="100",
                         asset_type="STOCK"),
        ], [])
        snap = platform.load_portfolio_snapshot(pp, tp)
        allocs = platform.compute_allocations(snap)
        assert "(unlabelled)" in allocs["by_sector"]
        assert "(unlabelled)" in allocs["by_theme"]

    def test_data_gaps_progression(self, tmp_path: Path, platform):
        # nothing on disk -> two missing-file gaps
        snap = platform.load_portfolio_snapshot(
            tmp_path / "nope_p.csv", tmp_path / "nope_t.csv",
        )
        assert len(platform.portfolio_data_gaps(snap)) == 2

        # header-only -> two "no rows yet" gaps
        pp, tp = self._seed(tmp_path, [], [])
        snap = platform.load_portfolio_snapshot(pp, tp)
        gaps = platform.portfolio_data_gaps(snap)
        assert len(gaps) == 2
        assert any("header-only" in g for g in gaps)

        # populated -> no gaps
        append_position_rows([PositionRow(
            as_of="2026-06-03", account="MAIN", ticker="X",
            market_value="100", asset_type="STOCK",
        )], pp, mode="append")
        append_transaction_rows([TransactionRow(
            date="2026-06-03", account="MAIN", ticker="X", side="BUY",
            quantity="1", price="100",
        )], tp, mode="append")
        snap = platform.load_portfolio_snapshot(pp, tp)
        assert platform.portfolio_data_gaps(snap) == []


# --------------------------------------------------------------------------- #
# Guardrails
# --------------------------------------------------------------------------- #
class TestGuardrails:
    SCHEMA_SOURCE = (
        REPO_ROOT / "src" / "quantbot" / "research" / "portfolio"
        / "schema.py"
    ).read_text(encoding="utf-8")
    READERS_SOURCE = (
        REPO_ROOT / "src" / "quantbot" / "research" / "portfolio"
        / "readers.py"
    ).read_text(encoding="utf-8")

    def test_live_trading_disabled(self):
        assert quantbot.LIVE_TRADING_ENABLED is False

    def test_no_broker_or_order_tokens(self):
        for src in (self.SCHEMA_SOURCE, self.READERS_SOURCE):
            for token in ("ib_insync", "place_order", "submit_order",
                          "from broker", "import broker", "ibapi"):
                assert token not in src, (
                    f"forbidden broker token {token!r} in V7.1 surface"
                )

    def test_no_network_imports(self):
        for src in (self.SCHEMA_SOURCE, self.READERS_SOURCE):
            for token in ("import requests", "import urllib",
                          "import aiohttp", "import socket",
                          "from requests", "from urllib",
                          "from aiohttp", "from socket"):
                assert token not in src, (
                    f"forbidden network import {token!r} in V7.1 surface"
                )

    def test_no_thetadata_imports(self):
        for src in (self.SCHEMA_SOURCE, self.READERS_SOURCE):
            assert "import thetadata" not in src.lower()
            assert "from thetadata" not in src.lower()


# --------------------------------------------------------------------------- #
# Regression: V7.8 / V7.0 / V6 surfaces still load cleanly
# --------------------------------------------------------------------------- #
class TestRegression:
    def test_platform_module_still_imports(self):
        sys.path.insert(0, str(REPO_ROOT / "apps"))
        try:
            mod = importlib.import_module("portfolio_platform")
            for name in ("load_portfolio_snapshot",
                         "compute_portfolio_totals",
                         "compute_allocations",
                         "portfolio_data_gaps",
                         "load_marketpulse_snapshot",
                         "PAGES"):
                assert hasattr(mod, name), f"missing: {name}"
        finally:
            if str(REPO_ROOT / "apps") in sys.path:
                sys.path.remove(str(REPO_ROOT / "apps"))

    def test_v6_dashboard_still_imports(self):
        sys.path.insert(0, str(REPO_ROOT / "apps"))
        try:
            mod = importlib.import_module("sector_thesis_dashboard")
            assert hasattr(mod, "render")
        finally:
            if str(REPO_ROOT / "apps") in sys.path:
                sys.path.remove(str(REPO_ROOT / "apps"))
