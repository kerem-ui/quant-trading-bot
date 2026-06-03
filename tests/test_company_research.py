"""Company / fundamentals research layer tests (toy data only -- NEVER network).

Covers the SEC EDGAR client's pure + cache paths, the pure transforms
(filing index, company facts, filing text/sections), the offline + cached
report orchestration, and the no-broker / no-live guardrails.

Network is neutralised by monkeypatching ``sec_edgar.http_get`` to return
``None`` (simulating offline); cache-hit paths are exercised with seeded
files under a tmp root.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from quantbot.company import company_facts as CF
from quantbot.company import company_report as CR
from quantbot.company import filing_index as FI
from quantbot.company import sec_edgar as SEC
from quantbot.company.filing_parser import (
    extract_sections,
    html_to_text,
    summarize_filing_text,
)
from quantbot.company.lseg_placeholder import is_available as lseg_available


# --------------------------------------------------------------------------- #
# Toy fixtures
# --------------------------------------------------------------------------- #
TOY_TICKERS = {
    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "1": {"cik_str": 789019, "ticker": "MSFT", "title": "MICROSOFT CORP"},
}

TOY_SUBMISSIONS = {
    "cik": "320193",
    "name": "Apple Inc.",
    "filings": {
        "recent": {
            "accessionNumber": ["0000320193-23-000106", "0000320193-23-000077",
                                "0000320193-22-000108"],
            "form": ["10-K", "10-Q", "8-K"],
            "filingDate": ["2023-11-03", "2023-08-04", "2022-10-28"],
            "reportDate": ["2023-09-30", "2023-07-01", "2022-10-27"],
            "primaryDocument": ["aapl-20230930.htm", "aapl-20230701.htm", "ea01.htm"],
            "primaryDocDescription": ["10-K", "10-Q", "8-K"],
            "items": ["", "", "2.02,9.01"],
            "size": [111, 222, 333],
            "isXBRL": [1, 1, 0],
        }
    },
}

TOY_FACTS = {
    "cik": 320193,
    "entityName": "Apple Inc.",
    "facts": {
        "us-gaap": {
            "Assets": {"label": "Assets", "units": {"USD": [
                {"end": "2022-09-24", "val": 352755000000, "fy": 2022, "fp": "FY",
                 "form": "10-K", "accn": "x"},
                {"end": "2023-09-30", "val": 352583000000, "fy": 2023, "fp": "FY",
                 "form": "10-K", "accn": "y"},
            ]}},
            "Liabilities": {"units": {"USD": [
                {"end": "2023-09-30", "val": 290437000000, "fy": 2023, "fp": "FY",
                 "form": "10-K", "accn": "y"}]}},
            "NetIncomeLoss": {"units": {"USD": [
                {"end": "2023-09-30", "val": 96995000000, "fy": 2023, "fp": "FY",
                 "form": "10-K", "accn": "y"}]}},
            "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": [
                {"end": "2023-09-30", "val": 383285000000, "fy": 2023, "fp": "FY",
                 "form": "10-K", "accn": "y"}]}},
            "CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": [
                {"end": "2023-09-30", "val": 29965000000, "fy": 2023, "fp": "FY",
                 "form": "10-K", "accn": "y"}]}},
            "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [
                {"end": "2023-09-30", "val": 110543000000, "fy": 2023, "fp": "FY",
                 "form": "10-K", "accn": "y"}]}},
            # NOTE: no debt tag -> total_debt must be reported unavailable.
        }
    },
}


@pytest.fixture
def offline(monkeypatch):
    """Force every SEC HTTP GET to fail (simulate offline)."""
    monkeypatch.setattr(SEC, "http_get", lambda *a, **k: None)


def _seed(root: Path, rel: str, payload: dict) -> None:
    p = SEC.company_cache_dir(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload), encoding="utf-8")


# --------------------------------------------------------------------------- #
# CIK normalisation + ticker map
# --------------------------------------------------------------------------- #
def test_normalize_cik_pads_and_strips():
    assert SEC.normalize_cik(320193) == "0000320193"
    assert SEC.normalize_cik("CIK0000320193") == "0000320193"
    assert SEC.normalize_cik("320193") == "0000320193"
    assert SEC.cik_int("0000320193") == 320193


def test_normalize_cik_rejects_nonnumeric():
    with pytest.raises(ValueError):
        SEC.normalize_cik("ABC")


def test_build_ticker_map_and_lookup():
    tmap = SEC.build_ticker_map(TOY_TICKERS)
    assert tmap["AAPL"]["cik"] == "0000320193"
    assert tmap["MSFT"]["title"] == "MICROSOFT CORP"
    assert SEC.ticker_to_cik("aapl", tickers=TOY_TICKERS) == "0000320193"
    assert SEC.ticker_to_cik("NOPE", tickers=TOY_TICKERS) is None


def test_build_ticker_map_handles_garbage():
    assert SEC.build_ticker_map(None) == {}
    assert SEC.build_ticker_map({"0": {"no_ticker": 1}}) == {}


# --------------------------------------------------------------------------- #
# Cache-first fetchers (no network)
# --------------------------------------------------------------------------- #
def test_fetch_company_tickers_uses_cache(offline, tmp_path):
    _seed(tmp_path, "company_tickers.json", TOY_TICKERS)
    got = SEC.fetch_company_tickers(root=tmp_path)
    assert got == TOY_TICKERS
    assert SEC.ticker_to_cik("AAPL", root=tmp_path) == "0000320193"


def test_fetch_company_tickers_offline_no_cache_returns_none(offline, tmp_path):
    assert SEC.fetch_company_tickers(root=tmp_path) is None


def test_fetch_submissions_uses_cache(offline, tmp_path):
    _seed(tmp_path, "submissions/CIK0000320193.json", TOY_SUBMISSIONS)
    # resolve AAPL -> CIK needs the tickers map too
    _seed(tmp_path, "company_tickers.json", TOY_TICKERS)
    got = SEC.fetch_submissions("AAPL", root=tmp_path)
    assert got is not None and got["name"] == "Apple Inc."


def test_fetch_submissions_offline_unresolved_returns_none(offline, tmp_path):
    assert SEC.fetch_submissions("AAPL", root=tmp_path) is None


def test_fetch_company_facts_uses_cache_by_numeric_cik(offline, tmp_path):
    _seed(tmp_path, "companyfacts/CIK0000320193.json", TOY_FACTS)
    got = SEC.fetch_company_facts("320193", root=tmp_path)
    assert got is not None and "facts" in got


# --------------------------------------------------------------------------- #
# User-Agent config (never exposes value)
# --------------------------------------------------------------------------- #
def test_user_agent_default_and_custom(monkeypatch):
    monkeypatch.delenv("QUANTBOT_SEC_USER_AGENT", raising=False)
    assert SEC.has_custom_user_agent() is False
    assert SEC.default_user_agent() == SEC.DEFAULT_USER_AGENT
    monkeypatch.setenv("QUANTBOT_SEC_USER_AGENT", "Tester test@example.com")
    assert SEC.has_custom_user_agent() is True
    assert SEC.default_user_agent() == "Tester test@example.com"


# --------------------------------------------------------------------------- #
# Filing index
# --------------------------------------------------------------------------- #
def test_build_filing_index_columns_sort_and_url():
    idx = FI.build_filing_index(TOY_SUBMISSIONS)
    assert list(idx.columns) == FI.INDEX_COLUMNS
    assert len(idx) == 3
    # Sorted by filing_date desc -> 10-K (2023-11-03) first.
    assert idx.iloc[0]["form"] == "10-K"
    url = idx.iloc[0]["document_url"]
    assert "Archives/edgar/data/320193/000032019323000106/aapl-20230930.htm" in url


def test_build_filing_index_empty_inputs():
    assert FI.build_filing_index(None).empty
    assert FI.build_filing_index({"filings": {"recent": {}}}).empty
    assert list(FI.build_filing_index(None).columns) == FI.INDEX_COLUMNS


def test_filter_filings_by_form_and_date():
    idx = FI.build_filing_index(TOY_SUBMISSIONS)
    only_10k = FI.filter_filings(idx, forms=["10-K"])
    assert set(only_10k["form"]) == {"10-K"}
    in_2023 = FI.filter_filings(idx, start="2023-01-01", end="2023-12-31")
    assert len(in_2023) == 2  # 10-K + 10-Q
    assert (in_2023["filing_date"] >= pd.Timestamp("2023-01-01")).all()


def test_filter_filings_amendments_toggle():
    subs = json.loads(json.dumps(TOY_SUBMISSIONS))
    subs["filings"]["recent"]["form"][1] = "10-K/A"
    idx = FI.build_filing_index(subs)
    assert len(FI.filter_filings(idx, forms=["10-K"], include_amendments=True)) == 2
    assert len(FI.filter_filings(idx, forms=["10-K"], include_amendments=False)) == 1


def test_filings_near_target_date():
    idx = FI.build_filing_index(TOY_SUBMISSIONS)
    near = FI.filings_near(idx, "2023-10-15", window_days=45)
    assert "10-K" in set(near["form"])  # 2023-11-03 is 19 days out
    assert "days_from_target" in near.columns


# --------------------------------------------------------------------------- #
# Company facts
# --------------------------------------------------------------------------- #
def test_extract_company_facts_fields_present():
    obs = CF.extract_company_facts(TOY_FACTS)
    fields = set(obs["field"])
    assert {"revenue", "net_income", "total_assets", "total_liabilities",
            "cash_and_equivalents", "operating_cash_flow"} <= fields
    assert "total_debt" not in fields  # no debt tag in toy data


def test_company_facts_availability_flags_missing():
    avail = CF.company_facts_availability(TOY_FACTS)
    debt = avail[avail["field"] == "total_debt"].iloc[0]
    assert bool(debt["available"]) is False
    assert debt["matched_tag"] == ""
    assets = avail[avail["field"] == "total_assets"].iloc[0]
    assert bool(assets["available"]) is True
    assert assets["matched_tag"] == "Assets"


def test_latest_annual_facts_picks_latest_fy():
    obs = CF.extract_company_facts(TOY_FACTS)
    latest = CF.latest_annual_facts(obs)
    a = latest[latest["field"] == "total_assets"].iloc[0]
    assert a["end"] == "2023-09-30"
    assert a["val"] == 352583000000


def test_company_facts_empty_inputs():
    assert CF.extract_company_facts(None).empty
    assert CF.extract_company_facts({"facts": {}}).empty
    avail = CF.company_facts_availability(None)
    assert (~avail["available"]).all()  # nothing available


# --------------------------------------------------------------------------- #
# V6.2.1: additional standard us-gaap concepts (gross_profit / cost_of_revenue
# / rd_expense / operating_income / inventory_net / capex). Purely additive —
# existing 7-field tests above continue to pass.
# --------------------------------------------------------------------------- #
TOY_FACTS_V621 = {
    "cik": 1045810,
    "entityName": "NVIDIA-like toy filer",
    "facts": {
        "us-gaap": {
            "GrossProfit": {"units": {"USD": [
                {"end": "2024-01-28", "val": 44301000000, "fy": 2024, "fp": "FY",
                 "form": "10-K", "accn": "a"}]}},
            "CostOfRevenue": {"units": {"USD": [
                {"end": "2024-01-28", "val": 16621000000, "fy": 2024, "fp": "FY",
                 "form": "10-K", "accn": "a"}]}},
            "ResearchAndDevelopmentExpense": {"units": {"USD": [
                {"end": "2024-01-28", "val": 8675000000, "fy": 2024, "fp": "FY",
                 "form": "10-K", "accn": "a"}]}},
            "OperatingIncomeLoss": {"units": {"USD": [
                {"end": "2024-01-28", "val": 32972000000, "fy": 2024, "fp": "FY",
                 "form": "10-K", "accn": "a"}]}},
            "InventoryNet": {"units": {"USD": [
                {"end": "2024-01-28", "val": 5282000000, "fy": 2024, "fp": "FY",
                 "form": "10-K", "accn": "a"}]}},
            "PaymentsToAcquirePropertyPlantAndEquipment": {"units": {"USD": [
                {"end": "2024-01-28", "val": 1069000000, "fy": 2024, "fp": "FY",
                 "form": "10-K", "accn": "a"}]}},
        }
    },
}


def test_v621_target_concepts_added():
    """The V6.2.1 standard us-gaap concepts are registered in TARGET_CONCEPTS."""
    for field in ("gross_profit", "cost_of_revenue", "rd_expense",
                  "operating_income", "inventory_net", "capex"):
        assert field in CF.TARGET_CONCEPTS, f"missing field {field!r}"
        # Each candidate tag list must be non-empty.
        assert CF.TARGET_CONCEPTS[field], f"empty candidates for {field!r}"


def test_v621_extract_new_concepts_from_toy():
    obs = CF.extract_company_facts(TOY_FACTS_V621)
    fields = set(obs["field"])
    expected = {"gross_profit", "cost_of_revenue", "rd_expense",
                "operating_income", "inventory_net", "capex"}
    assert expected <= fields, f"missing {expected - fields}"
    # Spot-check a value: GrossProfit picks the matched tag and the right val.
    gp = obs[obs["field"] == "gross_profit"].iloc[0]
    assert gp["concept_tag"] == "GrossProfit"
    assert int(gp["val"]) == 44_301_000_000
    capex = obs[obs["field"] == "capex"].iloc[0]
    assert capex["concept_tag"] == "PaymentsToAcquirePropertyPlantAndEquipment"


def test_v621_availability_reports_new_fields():
    avail = CF.company_facts_availability(TOY_FACTS_V621)
    new_fields = {"gross_profit", "cost_of_revenue", "rd_expense",
                  "operating_income", "inventory_net", "capex"}
    for f in new_fields:
        row = avail[avail["field"] == f]
        assert not row.empty, f"availability row missing for {f}"
        assert bool(row.iloc[0]["available"]) is True
        assert row.iloc[0]["matched_tag"] != ""


def test_v621_cost_of_revenue_falls_back_to_alt_tag():
    """If CostOfRevenue is absent but CostOfGoodsAndServicesSold is present,
    the field should still resolve via the second candidate tag."""
    facts = {"facts": {"us-gaap": {
        "CostOfGoodsAndServicesSold": {"units": {"USD": [
            {"end": "2024-12-31", "val": 1234, "fy": 2024, "fp": "FY",
             "form": "10-K", "accn": "z"}]}}}}}
    obs = CF.extract_company_facts(facts)
    assert "cost_of_revenue" in set(obs["field"])
    assert obs[obs["field"] == "cost_of_revenue"].iloc[0]["concept_tag"] \
        == "CostOfGoodsAndServicesSold"


def test_v621_existing_tests_unchanged_behaviour():
    """Adding new concepts must not affect extraction of the original 7 fields
    on the original toy fixture (regression guard for the additive change)."""
    obs = CF.extract_company_facts(TOY_FACTS)
    fields = set(obs["field"])
    assert {"revenue", "net_income", "total_assets", "total_liabilities",
            "cash_and_equivalents", "operating_cash_flow"} <= fields
    # TOY_FACTS has none of the V6.2.1 tags -> those fields stay absent here.
    assert "gross_profit" not in fields
    assert "inventory_net" not in fields


def test_v621_first_matching_tag_prefers_freshest_observation():
    """When a filer switches concept tags over time and both candidates carry
    observations, the loader must pick the one with the FRESHEST `end` date
    (not just the first candidate present). This was the V6.2.1 bug-class
    that left NVDA revenue stuck at FY2022 even though FY2023+ data lived on
    an alternate revenue tag."""
    # Two revenue candidates BOTH present but with different latest-end dates.
    # Default candidate order: RevenueFromContractWithCustomerExcludingAssessedTax
    # then Revenues. We give the alt ("Revenues") fresher data, so it must win.
    facts = {"facts": {"us-gaap": {
        "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": [
            {"end": "2022-01-30", "val": 26_914_000_000, "fy": 2022, "fp": "FY",
             "form": "10-K", "accn": "old"}]}},
        "Revenues": {"units": {"USD": [
            {"end": "2026-01-25", "val": 130_000_000_000, "fy": 2026, "fp": "FY",
             "form": "10-K", "accn": "new"}]}},
    }}}
    obs = CF.extract_company_facts(facts)
    rev = obs[obs["field"] == "revenue"]
    assert not rev.empty
    # The chosen tag should be the one whose latest end is most recent.
    assert rev.iloc[0]["concept_tag"] == "Revenues"
    # And the row must reflect the fresh value, not the stale one.
    assert int(rev.iloc[0]["val"]) == 130_000_000_000


def test_v621_first_matching_tag_falls_back_to_order_when_no_data_difference():
    """When only the FIRST candidate has data, the policy still returns it
    (so single-tag filers like the original TOY_FACTS continue to work)."""
    obs = CF.extract_company_facts(TOY_FACTS)
    rev = obs[obs["field"] == "revenue"].iloc[0]
    # TOY_FACTS only has the modern tag -> it should be selected.
    assert rev["concept_tag"] == "RevenueFromContractWithCustomerExcludingAssessedTax"


# --------------------------------------------------------------------------- #
# Filing text parsing
# --------------------------------------------------------------------------- #
def test_html_to_text_strips_tags_and_scripts():
    html = ("<html><head><title>x</title></head><body>"
            "<p>Item 1A. Risk Factors</p><script>var x=1;</script>"
            "<p>We face risks &amp; uncertainties.</p></body></html>")
    text = html_to_text(html)
    assert "Item 1A. Risk Factors" in text
    assert "We face risks & uncertainties." in text
    assert "var x" not in text


def test_html_to_text_handles_plain_and_empty():
    assert html_to_text("") == ""
    assert "hello world" in html_to_text("hello   world")


def test_extract_sections_finds_risk_factors():
    text = ("Item 1. Business We make phones. " * 3
            + "Item 1A. Risk Factors Markets are volatile. " * 3
            + "Item 7. Management's Discussion and Analysis revenue grew. " * 3)
    sections = extract_sections(text, "10-K")
    assert "risk_factors" in sections
    assert "Risk Factors" in sections["risk_factors"]


def test_summarize_filing_text_robust_on_junk():
    summ = summarize_filing_text("", "10-K")
    assert summ["n_chars"] == 0
    assert summ["detected_sections"] == []


# --------------------------------------------------------------------------- #
# Report orchestration (offline + cached)
# --------------------------------------------------------------------------- #
def test_build_company_research_offline_writes_availability(offline, tmp_path,
                                                            monkeypatch):
    monkeypatch.setattr(CR, "_load_prices", lambda *a, **k: None)
    out = tmp_path / "reports"
    summary = CR.build_company_research(
        "AAPL", start="2019-01-01", end="2024-12-31",
        root=tmp_path, out_dir=out)
    assert summary["online_submissions"] is False
    assert summary["n_filings_total"] == 0
    assert (out / "company_data_availability.md").is_file()
    assert (out / "AAPL_filing_index.csv").is_file()


def test_build_company_research_with_cached_data(offline, tmp_path, monkeypatch):
    _seed(tmp_path, "company_tickers.json", TOY_TICKERS)
    _seed(tmp_path, "submissions/CIK0000320193.json", TOY_SUBMISSIONS)
    _seed(tmp_path, "companyfacts/CIK0000320193.json", TOY_FACTS)

    # toy price series so strongest-move context is computed without yfinance
    idx = pd.bdate_range("2022-01-03", periods=400)
    close = pd.Series(range(1, 401), index=idx, dtype=float)
    monkeypatch.setattr(CR, "_load_prices",
                        lambda tkr, *a, **k: close if tkr == "AAPL" else None)

    out = tmp_path / "reports"
    summary = CR.build_company_research(
        "AAPL", start="2022-01-01", end="2023-12-31",
        root=tmp_path, out_dir=out, max_filings_to_parse=0)

    assert summary["online_submissions"] is True
    assert summary["n_filings_in_scope"] >= 1
    assert summary["n_facts_fields_available"] == 6  # all but total_debt
    fidx = pd.read_csv(out / "AAPL_filing_index.csv")
    assert len(fidx) >= 1
    assert (out / "AAPL_macro_company_context.md").is_file()
    assert (out / "AAPL_recent_filings_summary.md").is_file()


# --------------------------------------------------------------------------- #
# Guardrails
# --------------------------------------------------------------------------- #
def test_lseg_placeholder_is_not_available():
    assert lseg_available() is False


def test_company_package_has_no_broker_or_options_data_imports():
    """Scan for ACTUAL import statements, not docstring mentions (the module
    docstrings legitimately state the 'no broker / no ThetaData' invariant)."""
    pkg = Path(SEC.__file__).resolve().parent
    forbidden_imports = (
        "import ib_insync", "from ib_insync",
        "import ibapi", "from ibapi",
        "import interactivebrokers", "from interactivebrokers",
        "import thetadata", "from thetadata", "options_providers.thetadata",
        "from ..backtest", "import quantbot.backtest",
        "from ..strategies", "import quantbot.strategies",
        "from ..options", "import quantbot.options",
    )
    for f in pkg.rglob("*.py"):
        src = f.read_text(encoding="utf-8")
        for needle in forbidden_imports:
            assert needle not in src, f"{needle!r} found in {f.name}"


def test_live_trading_remains_false():
    import quantbot
    assert quantbot.LIVE_TRADING_ENABLED is False
