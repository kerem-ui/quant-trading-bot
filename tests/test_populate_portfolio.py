"""V7.1 — Tests for the portfolio data-population helper script.

Mirrors V7.8.1's `test_populate_marketpulse.py` shape:

  * Happy-path Python + CLI entry points for each subcommand.
  * Idempotent / strict / append modes.
  * Validation: required non-empty fields, enum violations.
  * Hard guardrails: no broker / IBKR / order / network / ThetaData tokens
    in the script source; ``LIVE_TRADING_ENABLED`` False.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

import quantbot
from quantbot.research.portfolio import (
    PortfolioSchemaError,
    load_positions,
    load_transactions,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def populate():
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        yield importlib.import_module("populate_portfolio")
    finally:
        if str(REPO_ROOT / "scripts") in sys.path:
            sys.path.remove(str(REPO_ROOT / "scripts"))


# --------------------------------------------------------------------------- #
# Guardrails
# --------------------------------------------------------------------------- #
class TestGuardrails:
    SCRIPT_SOURCE = (
        REPO_ROOT / "scripts" / "populate_portfolio.py"
    ).read_text(encoding="utf-8")

    def test_live_trading_disabled(self):
        assert quantbot.LIVE_TRADING_ENABLED is False

    def test_no_broker_or_order_tokens(self):
        for token in ("ib_insync", "place_order", "submit_order",
                      "from broker", "import broker", "ibapi"):
            assert token not in self.SCRIPT_SOURCE, (
                f"forbidden broker token {token!r} in populate_portfolio.py"
            )

    def test_no_network_imports(self):
        for token in ("import requests", "import urllib",
                      "import aiohttp", "import socket",
                      "from requests", "from urllib",
                      "from aiohttp", "from socket"):
            assert token not in self.SCRIPT_SOURCE, (
                f"forbidden network import {token!r} in populate_portfolio.py"
            )

    def test_no_thetadata_imports(self):
        assert "import thetadata" not in self.SCRIPT_SOURCE.lower()
        assert "from thetadata" not in self.SCRIPT_SOURCE.lower()

    def test_no_fred_or_market_fetch(self):
        # V7.1 doesn't need any FRED / market-data integration at all.
        assert "fred_loader" not in self.SCRIPT_SOURCE
        assert "FRED_BASE_URL" not in self.SCRIPT_SOURCE
        assert "yfinance" not in self.SCRIPT_SOURCE.lower()


# --------------------------------------------------------------------------- #
# add-position (Python entry)
# --------------------------------------------------------------------------- #
class TestAddPosition:
    def _kwargs(self, **over):
        base = dict(
            as_of="2026-06-03", account="MAIN", ticker="NVDA",
            company_name="NVIDIA Corp", asset_type="STOCK",
            quantity="100", average_cost="450.00",
            last_price="510.00", market_value="51000.00",
            unrealized_pnl="6000.00", sector="SEMICONDUCTOR",
            theme="AI accelerator", source="MANUAL",
        )
        base.update(over)
        return base

    def test_happy_path(self, tmp_path: Path, populate):
        p = tmp_path / "p.csv"
        result = populate.add_position_row(path=p, **self._kwargs())
        assert result["n_appended"] == 1
        rows = load_positions(p)
        assert rows[0].ticker == "NVDA"
        assert rows[0].sector == "SEMICONDUCTOR"

    def test_idempotent_same_key_noop(self, tmp_path: Path, populate):
        p = tmp_path / "p.csv"
        populate.add_position_row(path=p, **self._kwargs())
        second = populate.add_position_row(path=p, **self._kwargs())
        assert second["n_appended"] == 0
        assert second["n_skipped"] == 1

    def test_strict_mode_raises(self, tmp_path: Path, populate):
        p = tmp_path / "p.csv"
        populate.add_position_row(path=p, **self._kwargs())
        with pytest.raises(PortfolioSchemaError):
            populate.add_position_row(
                path=p, mode="strict", **self._kwargs(),
            )

    def test_append_mode_writes_duplicate(self, tmp_path: Path, populate):
        p = tmp_path / "p.csv"
        populate.add_position_row(path=p, **self._kwargs())
        populate.add_position_row(path=p, mode="append", **self._kwargs())
        assert len(load_positions(p)) == 2

    def test_different_as_of_appends(self, tmp_path: Path, populate):
        # Same account+ticker on a newer date should append a new row.
        p = tmp_path / "p.csv"
        populate.add_position_row(path=p, **self._kwargs(as_of="2026-06-03"))
        result = populate.add_position_row(
            path=p, **self._kwargs(as_of="2026-06-04"),
        )
        assert result["n_appended"] == 1
        assert len(load_positions(p)) == 2

    @pytest.mark.parametrize("missing", ["as_of", "account", "ticker"])
    def test_required_non_empty(self, tmp_path: Path, populate, missing):
        p = tmp_path / "p.csv"
        with pytest.raises(populate.PopulatePortfolioValidationError):
            populate.add_position_row(
                path=p, **self._kwargs(**{missing: ""}),
            )
        assert not p.is_file() or p.stat().st_size == 0

    def test_invalid_asset_type_rejected(self, tmp_path: Path, populate):
        p = tmp_path / "p.csv"
        with pytest.raises(populate.PopulatePortfolioValidationError):
            populate.add_position_row(
                path=p, **self._kwargs(asset_type="WAT"),
            )


# --------------------------------------------------------------------------- #
# add-transaction (Python entry)
# --------------------------------------------------------------------------- #
class TestAddTransaction:
    def _kwargs(self, **over):
        base = dict(
            date="2026-06-03", account="MAIN", ticker="NVDA",
            side="BUY", quantity="100", price="450.00", fees="1.00",
            currency="USD", reason="thesis BULL",
            linked_thesis="SEMI-NVDA-REV-T1", source="MANUAL",
        )
        base.update(over)
        return base

    def test_happy_path(self, tmp_path: Path, populate):
        p = tmp_path / "t.csv"
        result = populate.add_transaction_row(path=p, **self._kwargs())
        assert result["n_appended"] == 1
        rows = load_transactions(p)
        assert rows[0].side == "BUY"

    def test_idempotent_same_composite_key(self, tmp_path: Path, populate):
        p = tmp_path / "t.csv"
        populate.add_transaction_row(path=p, **self._kwargs())
        second = populate.add_transaction_row(path=p, **self._kwargs())
        assert second["n_skipped"] == 1

    def test_invalid_side_rejected(self, tmp_path: Path, populate):
        p = tmp_path / "t.csv"
        with pytest.raises(populate.PopulatePortfolioValidationError):
            populate.add_transaction_row(
                path=p, **self._kwargs(side="WAT"),
            )

    @pytest.mark.parametrize("missing",
                              ["date", "account", "ticker", "side"])
    def test_required_non_empty(self, tmp_path: Path, populate, missing):
        p = tmp_path / "t.csv"
        with pytest.raises(populate.PopulatePortfolioValidationError):
            populate.add_transaction_row(
                path=p, **self._kwargs(**{missing: ""}),
            )

    def test_different_quantity_is_separate_row(self, tmp_path: Path,
                                                  populate):
        # Two BUYs of the same ticker on the same day at different sizes
        # are distinct events.
        p = tmp_path / "t.csv"
        populate.add_transaction_row(path=p, **self._kwargs(quantity="50"))
        result = populate.add_transaction_row(
            path=p, **self._kwargs(quantity="100"),
        )
        assert result["n_appended"] == 1
        assert len(load_transactions(p)) == 2


# --------------------------------------------------------------------------- #
# CLI round-trip
# --------------------------------------------------------------------------- #
class TestCLI:
    def test_add_position_cli(self, tmp_path: Path, populate):
        p = tmp_path / "p.csv"
        rc = populate.cli([
            "add-position",
            "--as-of", "2026-06-03",
            "--account", "MAIN",
            "--ticker", "NVDA",
            "--asset-type", "STOCK",
            "--quantity", "100",
            "--market-value", "51000.00",
            "--sector", "SEMICONDUCTOR",
            "--theme", "AI accelerator",
            "--path", str(p),
        ])
        assert rc == 0
        assert len(load_positions(p)) == 1

    def test_add_transaction_cli(self, tmp_path: Path, populate):
        p = tmp_path / "t.csv"
        rc = populate.cli([
            "add-transaction",
            "--date", "2026-06-03",
            "--account", "MAIN",
            "--ticker", "NVDA",
            "--side", "BUY",
            "--quantity", "100",
            "--price", "450.00",
            "--linked-thesis", "SEMI-NVDA-REV-T1",
            "--path", str(p),
        ])
        assert rc == 0
        assert len(load_transactions(p)) == 1

    def test_invalid_side_rejected_by_argparse(self, tmp_path: Path,
                                                 populate):
        p = tmp_path / "t.csv"
        with pytest.raises(SystemExit):
            populate.cli([
                "add-transaction",
                "--date", "2026-06-03",
                "--account", "MAIN",
                "--ticker", "NVDA",
                "--side", "WAT",
                "--path", str(p),
            ])

    def test_empty_required_returns_nonzero(self, tmp_path: Path,
                                              populate, capsys):
        # argparse may accept empty --account but the CLI checks return 2.
        p = tmp_path / "p.csv"
        rc = populate.cli([
            "add-position",
            "--as-of", "2026-06-03",
            "--account", "",
            "--ticker", "NVDA",
            "--path", str(p),
        ])
        assert rc == 2
        captured = capsys.readouterr()
        assert "rejected" in captured.err.lower()
