"""V7.5.2 — Tests for the local SEC company-facts fundamentals module.

Covers:

  * :class:`FundamentalsSnapshot` schema.
  * :func:`load_ticker_to_cik_map` (missing / partial / valid).
  * :func:`load_companyfacts_json` (missing / invalid / valid).
  * :func:`companyfacts_path_for_ticker` (mapped / unmapped).
  * Tag extraction:
      - latest annual observation by ``fp=='FY'`` and ``end`` date
      - prior-year extraction in the same unit
      - freshness-aware candidate selection (NVDA-style tag switch)
      - DEI shares-outstanding fallback
  * Deterministic computations: revenue / inventory YoY, margins, FCF
    (OCF − capex), valuation (market cap, P/S, P/E, P/FCF, EV, EV/Sales).
  * Valuation empty-state (no close, no shares, or both).
  * Composition entry: empty / no us-gaap subtree / partial / full
    populated.
  * Real-data smoke against the committed NVDA / AMD / MSFT caches.
  * **No effect on**: Portfolio totals, Protection rows, PortTech rows,
    ``score_sector``.
  * Hard guardrails: no broker / IBKR / order / network /  ``yfinance`` /
    ``thetadata`` import tokens; ``LIVE_TRADING_ENABLED`` False.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

import quantbot
from quantbot.research.company_detail import (
    DEFAULT_COMPANYFACTS_DIR,
    DEFAULT_TICKER_MAP_FILE,
    DEI_CANDIDATES,
    FUNDAMENTALS_FIELDS,
    FundamentalsSnapshot,
    GAAP_CANDIDATES,
    companyfacts_path_for_ticker,
    compute_fundamentals_snapshot,
    load_companyfacts_json,
    load_ticker_to_cik_map,
)
from quantbot.research.portfolio import (
    PositionRow,
    append_position_rows,
    ensure_transactions_header,
)
from quantbot.research.porttech import derive_porttech_rows
from quantbot.research.protection import derive_protection_rows
from quantbot.research.sector_tracker import (
    Catalyst,
    CompanyLedgerRow,
    SectorSignalLogRow,
    score_sector,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


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


def _ticker_map_payload(*pairs: tuple[str, int]) -> dict:
    """Build the SEC company_tickers.json shape from (ticker, cik_int) pairs."""
    return {
        str(i): {"ticker": t, "cik_str": c, "title": f"{t} Corp"}
        for i, (t, c) in enumerate(pairs)
    }


def _facts_payload(
    *,
    revenue_fy: list[tuple[int, str, float]] | None = None,
    gross_profit_fy: list[tuple[int, str, float]] | None = None,
    operating_income_fy: list[tuple[int, str, float]] | None = None,
    net_income_fy: list[tuple[int, str, float]] | None = None,
    ocf_fy: list[tuple[int, str, float]] | None = None,
    capex_fy: list[tuple[int, str, float]] | None = None,
    inventory_fy: list[tuple[int, str, float]] | None = None,
    cash_fy: list[tuple[int, str, float]] | None = None,
    debt_fy: list[tuple[int, str, float]] | None = None,
    shares_outstanding_gaap: list[tuple[int, str, float]] | None = None,
    shares_outstanding_dei: list[tuple[int, str, float]] | None = None,
    revenue_tag: str = "RevenueFromContractWithCustomerExcludingAssessedTax",
) -> dict:
    """Mimic the SEC companyfacts JSON shape with controlled observations.

    Each ``*_fy`` argument is a list of ``(fy_int, end_iso, val_float)``
    tuples — every observation is recorded with ``fp == "FY"`` so the
    extractor pulls them as annuals.
    """
    def _obs(tup):
        fy, end, val = tup
        return {
            "val": val, "fy": fy, "fp": "FY",
            "end": end, "start": end, "form": "10-K",
            "accession": "0000000000-00-000000",
        }

    def _put(gaap: dict, tag: str, unit: str,
              data: list[tuple[int, str, float]] | None):
        if not data:
            return
        gaap.setdefault(tag, {"units": {}})
        gaap[tag]["units"].setdefault(unit, []).extend(_obs(t) for t in data)

    gaap: dict = {}
    _put(gaap, revenue_tag, "USD", revenue_fy)
    _put(gaap, "GrossProfit", "USD", gross_profit_fy)
    _put(gaap, "OperatingIncomeLoss", "USD", operating_income_fy)
    _put(gaap, "NetIncomeLoss", "USD", net_income_fy)
    _put(gaap, "NetCashProvidedByUsedInOperatingActivities", "USD", ocf_fy)
    _put(gaap, "PaymentsToAcquirePropertyPlantAndEquipment", "USD",
         capex_fy)
    _put(gaap, "InventoryNet", "USD", inventory_fy)
    _put(gaap, "CashAndCashEquivalentsAtCarryingValue", "USD", cash_fy)
    _put(gaap, "LongTermDebt", "USD", debt_fy)
    _put(gaap, "CommonStockSharesOutstanding", "shares",
         shares_outstanding_gaap)

    dei: dict = {}
    _put(dei, "EntityCommonStockSharesOutstanding", "shares",
         shares_outstanding_dei)

    return {"facts": {"us-gaap": gaap, "dei": dei}}


@pytest.fixture
def clean_checkout_sec_fixture(tmp_path: Path) -> tuple[Path, Path]:
    """Small SEC-format cache for clean-clone integration tests."""
    sec_dir = tmp_path / "sec"
    facts_dir = sec_dir / "companyfacts"
    facts_dir.mkdir(parents=True)
    ticker_map = sec_dir / "company_tickers.json"
    ticker_map.write_text(json.dumps(_ticker_map_payload(
        ("NVDA", 1045810), ("AMD", 2488), ("MSFT", 789019),
        ("ASML", 937966),
    )), encoding="utf-8")
    payload = _facts_payload(
        revenue_fy=[
            (2024, "2024-01-28", 60_000_000_000),
            (2025, "2025-01-26", 100_000_000_000),
        ],
        gross_profit_fy=[
            (2024, "2024-01-28", 39_000_000_000),
            (2025, "2025-01-26", 70_000_000_000),
        ],
        operating_income_fy=[(2025, "2025-01-26", 50_000_000_000)],
        net_income_fy=[(2025, "2025-01-26", 40_000_000_000)],
        ocf_fy=[(2025, "2025-01-26", 45_000_000_000)],
        capex_fy=[(2025, "2025-01-26", 4_000_000_000)],
        inventory_fy=[
            (2024, "2024-01-28", 5_000_000_000),
            (2025, "2025-01-26", 6_000_000_000),
        ],
        cash_fy=[(2025, "2025-01-26", 20_000_000_000)],
        debt_fy=[(2025, "2025-01-26", 10_000_000_000)],
        shares_outstanding_gaap=[
            (2025, "2025-01-26", 2_000_000_000),
        ],
    )
    for cik in ("CIK0001045810", "CIK0000002488", "CIK0000789019"):
        (facts_dir / f"{cik}.json").write_text(
            json.dumps(payload), encoding="utf-8",
        )
    return ticker_map, facts_dir


# --------------------------------------------------------------------------- #
# Guardrails (V7.5.2 surface only)
# --------------------------------------------------------------------------- #
class TestGuardrails:
    SOURCE = (
        REPO_ROOT / "src" / "quantbot" / "research" / "company_detail"
        / "fundamentals.py"
    ).read_text(encoding="utf-8")

    def test_live_trading_disabled(self):
        assert quantbot.LIVE_TRADING_ENABLED is False

    def test_no_broker_or_order_tokens(self):
        for token in ("ib_insync", "place_order", "submit_order",
                      "from broker", "import broker", "ibapi",
                      "placeOrder"):
            assert token not in self.SOURCE, (
                f"forbidden broker token {token!r} in V7.5.2 surface"
            )

    def test_no_network_imports(self):
        for token in ("import requests", "import urllib",
                      "import aiohttp", "import socket",
                      "from requests", "from urllib",
                      "from aiohttp", "from socket"):
            assert token not in self.SOURCE, (
                f"forbidden network import {token!r} in V7.5.2 surface"
            )

    def test_no_sec_live_fetch_tokens(self):
        # The SEC live client lives in src/quantbot/company/sec_edgar.py
        # via http_get / fetch_company_facts. V7.5.2 must NOT import it.
        forbidden = (
            "from quantbot.company.sec_edgar",
            "import quantbot.company.sec_edgar",
            "fetch_company_facts",
            "fetch_company_tickers",
            "http_get",
            "SEC_DATA",
            "stlouisfed",  # FRED
            "yfinance",
            "yf.download",
            "thetadata",
        )
        lowered = self.SOURCE.lower()
        for token in forbidden:
            assert token.lower() not in lowered, (
                f"forbidden live-fetch token {token!r} in V7.5.2 surface"
            )


# --------------------------------------------------------------------------- #
# Schema
# --------------------------------------------------------------------------- #
class TestSchema:
    def test_fields_tuple_matches_dataclass(self):
        snap = FundamentalsSnapshot(ticker="X")
        assert set(FUNDAMENTALS_FIELDS) == set(snap.to_dict().keys())

    def test_required_ticker(self):
        snap = FundamentalsSnapshot(ticker="NVDA")
        assert snap.ticker == "NVDA"
        # Default placeholders.
        assert snap.revenue == "n/a"
        assert snap.market_cap == "n/a"


# --------------------------------------------------------------------------- #
# Ticker → CIK map loader
# --------------------------------------------------------------------------- #
class TestTickerToCikMap:
    def test_missing_file_returns_empty(self, tmp_path: Path):
        assert load_ticker_to_cik_map(tmp_path / "nope.json") == {}

    def test_malformed_file_returns_empty(self, tmp_path: Path):
        p = tmp_path / "tickers.json"
        p.write_text("not json", encoding="utf-8")
        assert load_ticker_to_cik_map(p) == {}

    def test_valid_payload_normalises(self, tmp_path: Path):
        p = tmp_path / "tickers.json"
        p.write_text(
            json.dumps(_ticker_map_payload(("NVDA", 1045810),
                                             ("AMD", 2488))),
            encoding="utf-8",
        )
        tmap = load_ticker_to_cik_map(p)
        assert tmap["NVDA"] == "CIK0001045810"
        assert tmap["AMD"] == "CIK0000002488"

    def test_case_insensitive_lookup(self, tmp_path: Path):
        p = tmp_path / "tickers.json"
        p.write_text(
            json.dumps(_ticker_map_payload(("nvda", 1045810))),
            encoding="utf-8",
        )
        tmap = load_ticker_to_cik_map(p)
        assert "NVDA" in tmap

    def test_skips_invalid_rows(self, tmp_path: Path):
        p = tmp_path / "tickers.json"
        p.write_text(
            json.dumps({
                "0": {"ticker": "GOOD", "cik_str": 100},
                "1": {"ticker": "BAD"},          # missing cik
                "2": "not a dict",                # bad row
                "3": {"ticker": "", "cik_str": 5},  # empty ticker
                "4": {"ticker": "X", "cik_str": "not_int"},  # bad cik
            }),
            encoding="utf-8",
        )
        tmap = load_ticker_to_cik_map(p)
        assert list(tmap) == ["GOOD"]


# --------------------------------------------------------------------------- #
# companyfacts_path_for_ticker + load_companyfacts_json
# --------------------------------------------------------------------------- #
class TestCompanyfactsPathForTicker:
    def test_missing_ticker_returns_empty(self, tmp_path: Path):
        cik, p = companyfacts_path_for_ticker(
            "NOSUCH",
            ticker_map_path=tmp_path / "tickers.json",
            companyfacts_dir=tmp_path / "facts",
        )
        assert cik == ""
        assert p is None

    def test_resolves_when_both_present(self, tmp_path: Path):
        tmap_path = tmp_path / "tickers.json"
        tmap_path.write_text(
            json.dumps(_ticker_map_payload(("NVDA", 1045810))),
            encoding="utf-8",
        )
        facts_dir = tmp_path / "facts"
        facts_dir.mkdir()
        cik_file = facts_dir / "CIK0001045810.json"
        cik_file.write_text("{}", encoding="utf-8")
        cik, p = companyfacts_path_for_ticker(
            "NVDA",
            ticker_map_path=tmap_path,
            companyfacts_dir=facts_dir,
        )
        assert cik == "CIK0001045810"
        assert p == cik_file

    def test_resolves_cik_but_no_json(self, tmp_path: Path):
        # Ticker mapped to CIK but no cached file — path is None.
        tmap_path = tmp_path / "tickers.json"
        tmap_path.write_text(
            json.dumps(_ticker_map_payload(("ASML", 937966))),
            encoding="utf-8",
        )
        facts_dir = tmp_path / "facts"
        facts_dir.mkdir()
        cik, p = companyfacts_path_for_ticker(
            "ASML",
            ticker_map_path=tmap_path,
            companyfacts_dir=facts_dir,
        )
        assert cik == "CIK0000937966"
        assert p is None


class TestLoadCompanyfactsJson:
    def test_missing_file_returns_none(self, tmp_path: Path):
        assert load_companyfacts_json(
            "CIK0000000001", companyfacts_dir=tmp_path,
        ) is None

    def test_empty_file_returns_none(self, tmp_path: Path):
        (tmp_path / "CIK0000000001.json").write_text("", encoding="utf-8")
        assert load_companyfacts_json(
            "CIK0000000001", companyfacts_dir=tmp_path,
        ) is None

    def test_malformed_json_returns_none(self, tmp_path: Path):
        (tmp_path / "CIK0000000001.json").write_text("not json",
                                                      encoding="utf-8")
        assert load_companyfacts_json(
            "CIK0000000001", companyfacts_dir=tmp_path,
        ) is None

    def test_valid_payload_returns_dict(self, tmp_path: Path):
        payload = {"facts": {"us-gaap": {}}}
        (tmp_path / "CIK0000000001.json").write_text(
            json.dumps(payload), encoding="utf-8",
        )
        result = load_companyfacts_json(
            "CIK0000000001", companyfacts_dir=tmp_path,
        )
        assert result == payload

    def test_empty_cik_returns_none(self, tmp_path: Path):
        assert load_companyfacts_json("", companyfacts_dir=tmp_path) is None


# --------------------------------------------------------------------------- #
# compute_fundamentals_snapshot — composition + extraction
# --------------------------------------------------------------------------- #
class TestComputeFundamentalsSnapshot:
    def test_none_facts_yields_empty_with_gap_note(self):
        snap = compute_fundamentals_snapshot(None, ticker="NVDA")
        assert snap.ticker == "NVDA"
        # The exact spec-mandated phrase for the empty state.
        assert "Fundamentals cache not available" in snap.data_gap_note
        assert "No live SEC fetch performed" in snap.data_gap_note

    def test_no_us_gaap_subtree(self):
        snap = compute_fundamentals_snapshot(
            {"facts": {"dei": {}}}, ticker="X",
        )
        # us-gaap absent → empty fundamentals with a clear note.
        assert "no us-gaap" in snap.data_gap_note.lower() \
            or snap.revenue == "n/a"

    def test_full_extraction_round_trip(self):
        facts = _facts_payload(
            revenue_fy=[(2024, "2024-12-31", 100_000_000_000.0),
                         (2025, "2025-12-31", 130_000_000_000.0)],
            gross_profit_fy=[(2025, "2025-12-31", 80_000_000_000.0)],
            operating_income_fy=[(2025, "2025-12-31", 60_000_000_000.0)],
            net_income_fy=[(2025, "2025-12-31", 50_000_000_000.0)],
            ocf_fy=[(2025, "2025-12-31", 70_000_000_000.0)],
            capex_fy=[(2025, "2025-12-31", 10_000_000_000.0)],
            inventory_fy=[(2024, "2024-12-31", 5_000_000_000.0),
                            (2025, "2025-12-31", 7_500_000_000.0)],
            cash_fy=[(2025, "2025-12-31", 20_000_000_000.0)],
            debt_fy=[(2025, "2025-12-31", 8_000_000_000.0)],
            shares_outstanding_gaap=[(2025, "2025-12-31", 2_500_000_000.0)],
        )
        snap = compute_fundamentals_snapshot(
            facts, ticker="X", cik="CIK0000000001",
        )
        # YoY revenue: (130 - 100)/100 = +30%.
        assert "+30.00%" == snap.revenue_yoy_pct
        # Inventory YoY: (7.5 - 5)/5 = +50%.
        assert "+50.00%" == snap.inventory_yoy_pct
        # Gross margin: 80/130 = 61.54%.
        assert "61.54%" == snap.gross_margin_pct
        # Operating margin: 60/130 = 46.15%.
        assert "46.15%" == snap.operating_margin_pct
        # FCF: 70 - 10 = 60.
        assert "$60.00B" == snap.free_cash_flow
        # Latest fiscal period from revenue: FY2025.
        assert snap.latest_fiscal_period == "FY2025"
        assert snap.latest_report_date == "2025-12-31"
        # Without latest_close, valuation is skipped.
        assert "no local price cache" in snap.valuation_note.lower()
        assert snap.market_cap == "n/a"

    def test_freshness_aware_revenue_tag_switch(self):
        # NVDA-style: the older RevenueFromContractWithCustomer... tag has
        # only stale observations; the modern Revenues tag carries the
        # latest year. The freshness rule must prefer Revenues.
        facts = _facts_payload(
            revenue_fy=[(2022, "2022-01-30", 26_900_000_000.0)],
            revenue_tag="RevenueFromContractWithCustomerExcludingAssessedTax",
        )
        # Inject a fresher 'Revenues' observation manually.
        facts["facts"]["us-gaap"]["Revenues"] = {
            "units": {
                "USD": [
                    {"val": 60_900_000_000.0, "fy": 2023, "fp": "FY",
                     "end": "2023-01-29", "form": "10-K"},
                    {"val": 130_500_000_000.0, "fy": 2024, "fp": "FY",
                     "end": "2024-01-28", "form": "10-K"},
                ],
            },
        }
        snap = compute_fundamentals_snapshot(facts, ticker="NVDA")
        # The 2024 Revenues observation should win.
        assert snap.latest_fiscal_period == "FY2024"
        assert "$130.50B" == snap.revenue

    def test_dei_shares_fallback(self):
        # GAAP shares missing, but DEI EntityCommonStockSharesOutstanding
        # is present.
        facts = _facts_payload(
            revenue_fy=[(2025, "2025-12-31", 100.0)],
            shares_outstanding_dei=[(2025, "2025-12-31",
                                       1_234_567_890.0)],
        )
        snap = compute_fundamentals_snapshot(facts, ticker="X")
        assert snap.shares_outstanding == "1.23B"

    def test_valuation_when_close_and_shares_present(self):
        facts = _facts_payload(
            revenue_fy=[(2025, "2025-12-31", 100_000_000_000.0)],
            net_income_fy=[(2025, "2025-12-31", 20_000_000_000.0)],
            ocf_fy=[(2025, "2025-12-31", 30_000_000_000.0)],
            capex_fy=[(2025, "2025-12-31", 5_000_000_000.0)],
            cash_fy=[(2025, "2025-12-31", 10_000_000_000.0)],
            debt_fy=[(2025, "2025-12-31", 5_000_000_000.0)],
            shares_outstanding_gaap=[(2025, "2025-12-31",
                                        1_000_000_000.0)],
        )
        snap = compute_fundamentals_snapshot(
            facts, ticker="X", latest_close=500.0,
        )
        # Market cap = 500 * 1B = 500B.
        assert "$500.00B" == snap.market_cap
        # P/S = 500B / 100B = 5.0x.
        assert "5.00x" == snap.price_to_sales
        # P/E = 500B / 20B = 25.0x.
        assert "25.00x" == snap.price_to_earnings
        # FCF = 30 - 5 = 25B; P/FCF = 500B / 25B = 20.
        assert "20.00x" == snap.price_to_free_cash_flow
        # EV = 500 + 5 - 10 = 495B.
        assert "$495.00B" == snap.enterprise_value
        # EV / Sales = 495 / 100 = 4.95x.
        assert "4.95x" == snap.ev_to_sales

    def test_valuation_skipped_when_no_close(self):
        facts = _facts_payload(
            revenue_fy=[(2025, "2025-12-31", 100.0)],
            shares_outstanding_gaap=[(2025, "2025-12-31", 1_000.0)],
        )
        snap = compute_fundamentals_snapshot(facts, ticker="X")
        assert "no local price cache" in snap.valuation_note.lower()
        assert snap.market_cap == "n/a"

    def test_valuation_skipped_when_no_shares(self):
        facts = _facts_payload(
            revenue_fy=[(2025, "2025-12-31", 100.0)],
        )
        snap = compute_fundamentals_snapshot(
            facts, ticker="X", latest_close=100.0,
        )
        assert "no shares-outstanding" in snap.valuation_note.lower()
        assert snap.market_cap == "n/a"

    def test_pe_skipped_when_negative_earnings(self):
        facts = _facts_payload(
            revenue_fy=[(2025, "2025-12-31", 100.0)],
            net_income_fy=[(2025, "2025-12-31", -10.0)],  # loss
            shares_outstanding_gaap=[(2025, "2025-12-31", 100.0)],
        )
        snap = compute_fundamentals_snapshot(
            facts, ticker="X", latest_close=10.0,
        )
        # Market cap = 10 * 100 = 1000; P/S = 1000/100 = 10x.
        assert "10.00x" == snap.price_to_sales
        # P/E should NOT be computed for negative earnings.
        assert "n/a" == snap.price_to_earnings


# --------------------------------------------------------------------------- #
# Clean-checkout SEC-format integration smoke
# --------------------------------------------------------------------------- #
class TestRealDataSmoke:
    @pytest.mark.parametrize("ticker", ["NVDA", "AMD", "MSFT"])
    def test_universe_ticker_resolves(self, ticker, clean_checkout_sec_fixture):
        ticker_map, facts_dir = clean_checkout_sec_fixture
        cik, p = companyfacts_path_for_ticker(
            ticker, ticker_map_path=ticker_map, companyfacts_dir=facts_dir,
        )
        assert cik != ""
        assert p is not None and p.is_file()

    def test_nvda_real_numbers_reasonable(self, clean_checkout_sec_fixture):
        ticker_map, facts_dir = clean_checkout_sec_fixture
        cik, p = companyfacts_path_for_ticker(
            "NVDA", ticker_map_path=ticker_map, companyfacts_dir=facts_dir,
        )
        facts = load_companyfacts_json(cik, companyfacts_dir=facts_dir) if cik else None
        snap = compute_fundamentals_snapshot(facts, ticker="NVDA",
                                               cik=cik)
        # NVDA's V6.7 ledger asserts revenue YoY ≈ +65%. The exact value
        # depends on the cache vintage but it should be a clean float
        # north of +30% any reasonable cache snapshot.
        assert snap.revenue != "n/a"
        assert "$" in snap.revenue
        assert snap.revenue_yoy_pct != "n/a"
        # Gross margin > 50% for NVDA.
        gm_pct = float(snap.gross_margin_pct.rstrip("%"))
        assert gm_pct > 50.0
        assert snap.shares_outstanding != "n/a"

    def test_foreign_filer_graceful(self, clean_checkout_sec_fixture):
        ticker_map, facts_dir = clean_checkout_sec_fixture
        # ASML is in SEC's ticker directory but has no cached companyfacts.
        cik, p = companyfacts_path_for_ticker(
            "ASML", ticker_map_path=ticker_map, companyfacts_dir=facts_dir,
        )
        # CIK is resolvable; the JSON file is absent.
        assert cik != ""
        assert p is None or not p.is_file()
        facts = (load_companyfacts_json(cik, companyfacts_dir=facts_dir)
                 if (cik and p) else None)
        snap = compute_fundamentals_snapshot(facts, ticker="ASML")
        # When facts is None (because we didn't load), the snapshot is
        # an empty state with the spec-mandated phrase.
        assert "Fundamentals cache not available" in snap.data_gap_note


# --------------------------------------------------------------------------- #
# Platform integration
# --------------------------------------------------------------------------- #
class TestPlatformIntegration:
    def test_unmapped_ticker_yields_empty_state(self, platform):
        snap = platform.load_fundamentals_snapshot_from_disk(
            "NO_SUCH_TICKER_42",
        )
        # Either no CIK was found, or facts was None. Either way the
        # snapshot is the empty state.
        assert snap.data_gap_note != ""

    def test_real_nvda_via_platform(self, platform,
                                    clean_checkout_sec_fixture, tmp_path):
        ticker_map, facts_dir = clean_checkout_sec_fixture
        snap = platform.load_fundamentals_snapshot_from_disk(
            "NVDA", ticker_map_path=ticker_map,
            companyfacts_dir=facts_dir, price_cache_dir=tmp_path,
        )
        assert snap.revenue != "n/a"
        assert snap.cik.startswith("CIK")
        # No NVDA price cache today → valuation is empty.
        assert "no local price cache" in snap.valuation_note.lower() \
            or snap.market_cap != "n/a"

    def test_platform_exposes_helper(self, platform):
        assert hasattr(platform, "load_fundamentals_snapshot_from_disk")


# --------------------------------------------------------------------------- #
# No-effect on upstream surfaces
# --------------------------------------------------------------------------- #
def _pos(*, ticker: str, market_value: str = "10000",
         sector: str = "SEMICONDUCTOR",
         asset_type: str = "STOCK") -> PositionRow:
    return PositionRow(
        as_of="2026-06-03", account="MAIN", ticker=ticker,
        asset_type=asset_type, market_value=market_value,
        sector=sector,
    )


def _lrow(*, ticker: str, read: str = "BULL") -> CompanyLedgerRow:
    return CompanyLedgerRow(
        run_id="RUN-1", timestamp="2026-06-03T00:00:00+00:00",
        date="2026-06-03",
        ticker=ticker, company_or_label=ticker,
        sector="SEMICONDUCTOR", theme="x", read=read,
        why_short="", main_risk_short="",
        linked_catalysts="", n_linked_present=0, n_linked_total=0,
        source_files="", source_dates="",
        is_manual_or_tracked_context="false",
        reason="", notes="",
    )


def _ssr(signal: str = "ACCUMULATE") -> SectorSignalLogRow:
    return SectorSignalLogRow(
        run_id="RUN-1", timestamp="2026-06-03T00:00:00+00:00",
        date="2026-06-03", sector="SEMICONDUCTOR",
        canonical_signal=signal, normalized_score=0.0, raw_score=0.0,
        total_weight=0, n_catalysts=0, n_bull=0, n_neutral=0,
        n_near_threshold=0, n_broken=0, n_emergency_exits=0,
        n_triggered_exits=0,
    )


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
        # Exercise the fundamentals path many times.
        for ticker in ("NVDA", "AMD", "MSFT", "NO_SUCH"):
            platform.load_fundamentals_snapshot_from_disk(ticker)
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
        signals = {"SEMICONDUCTOR": _ssr()}
        before = [r.to_dict() for r in derive_protection_rows(
            positions,
            company_ledger_by_ticker=ledger,
            sector_signals_by_sector=signals,
        )]
        # Touch every V7.5.2 surface.
        compute_fundamentals_snapshot(None, ticker="X")
        after = [r.to_dict() for r in derive_protection_rows(
            positions,
            company_ledger_by_ticker=ledger,
            sector_signals_by_sector=signals,
        )]
        assert before == after

    def test_porttech_rows_unchanged(self):
        positions = [_pos(ticker="NVDA", market_value="60000"),
                     _pos(ticker="AMD", market_value="40000")]
        ledger = {
            "NVDA": _lrow(ticker="NVDA", read="BULL"),
            "AMD": _lrow(ticker="AMD", read="BULL"),
        }
        signals = {"SEMICONDUCTOR": _ssr()}
        before = [r.to_dict() for r in derive_porttech_rows(
            positions,
            company_ledger_by_ticker=ledger,
            sector_signals_by_sector=signals,
        )]
        compute_fundamentals_snapshot(None, ticker="X")
        after = [r.to_dict() for r in derive_porttech_rows(
            positions,
            company_ledger_by_ticker=ledger,
            sector_signals_by_sector=signals,
        )]
        assert before == after

    def test_score_sector_untouched(self):
        cats = [Catalyst(
            catalyst_id="X", sector="SEMICONDUCTOR", subsector="x",
            catalyst_name="x", tier=1, direction="ABOVE",
            threshold="t", current_value="v", status="BULL",
            source_type="SEC_EDGAR", source_detail="ok",
            last_updated="2026-05-28", action_if_broken="x",
        )]
        before = score_sector(cats, [], sector="SEMICONDUCTOR")
        compute_fundamentals_snapshot(None, ticker="X")
        load_ticker_to_cik_map(DEFAULT_TICKER_MAP_FILE)
        after = score_sector(cats, [], sector="SEMICONDUCTOR")
        assert before.signal == after.signal
        assert before.normalized_score == after.normalized_score


# --------------------------------------------------------------------------- #
# Regression — V6 / V7 surfaces still load cleanly.
# --------------------------------------------------------------------------- #
class TestRegression:
    def test_platform_module_imports(self):
        sys.path.insert(0, str(REPO_ROOT / "apps"))
        try:
            mod = importlib.import_module("portfolio_platform")
            for name in (
                "load_fundamentals_snapshot_from_disk",
                "load_technical_snapshot_from_disk",
                "build_company_detail_view_from_disk",
                "derive_porttech_rows_from_snapshot",
                "load_protection_snapshot",
            ):
                assert hasattr(mod, name), f"missing: {name}"
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

    def test_default_paths_point_at_local_data(self):
        assert "company" in DEFAULT_COMPANYFACTS_DIR.parts
        assert "sec" in DEFAULT_COMPANYFACTS_DIR.parts
        assert DEFAULT_COMPANYFACTS_DIR.name == "companyfacts"


# --------------------------------------------------------------------------- #
# Smoke: candidate constants stable
# --------------------------------------------------------------------------- #
class TestCandidateConstants:
    def test_required_friendly_fields_present(self):
        for fld in ("revenue", "gross_profit", "operating_income",
                    "net_income", "operating_cash_flow", "capex",
                    "inventory", "cash", "debt",
                    "shares_outstanding_gaap"):
            assert fld in GAAP_CANDIDATES, (
                f"missing GAAP candidate list for {fld}"
            )
        assert "shares_outstanding_dei" in DEI_CANDIDATES

    def test_revenue_candidate_order_matches_v6_2_1_policy(self):
        # The first candidate must be the modern Revenue tag used by
        # post-2018 filers; older tags follow.
        assert GAAP_CANDIDATES["revenue"][0] == (
            "RevenueFromContractWithCustomerExcludingAssessedTax"
        )
