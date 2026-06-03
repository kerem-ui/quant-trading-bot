"""V7.0 — Tests for the local Streamlit platform shell.

Covers:

  * Clean import (the module loads without invoking streamlit).
  * Page list contains every required page.
  * Disclaimer text contains the required phrase.
  * Glossary contains every required term.
  * Pure helpers handle missing optional CSVs gracefully (empty state).
  * Pure helpers work when the V6 artefacts are present (real data path).
  * Reports listing respects the file-extension allowlist and cap.
  * **Guardrails**: no broker / IBKR / order tokens; no file-write tokens
    anywhere in the platform source. ``LIVE_TRADING_ENABLED`` False.
  * Existing V6 dashboard module still imports cleanly (we did not touch
    it).
"""

from __future__ import annotations

import importlib
import re
import sys
from pathlib import Path

import pytest

import quantbot
from quantbot.research.sector_tracker import (
    Catalyst,
    CompanyLedgerRow,
    EmergencyExit,
    SectorAggregationRow,
    SectorSignalLogRow,
    append_company_ledger_rows,
    append_sector_aggregation_rows,
    append_sector_signal_log_rows,
    save_catalysts,
    save_exits,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
_TS = "2026-05-29T00:00:00+00:00"
_DATE = "2026-05-29"


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture
def platform():
    """Import the V7.0 platform module (apps/ is not a package)."""
    sys.path.insert(0, str(REPO_ROOT / "apps"))
    try:
        yield importlib.import_module("portfolio_platform")
    finally:
        if str(REPO_ROOT / "apps") in sys.path:
            sys.path.remove(str(REPO_ROOT / "apps"))


def _cat(*, cid: str, sector: str, status: str = "BULL") -> Catalyst:
    return Catalyst(
        catalyst_id=cid, sector=sector, subsector="X",
        catalyst_name=f"name-{cid}", tier=1, direction="ABOVE",
        threshold="t", current_value="+10%", status=status,
        source_type="SEC_EDGAR", source_detail="ok",
        last_updated="2026-05-28", action_if_broken="review", notes="",
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


def _arow(*, sector: str, read: str = "BULL",
          run_id: str = "RUN-1") -> SectorAggregationRow:
    return SectorAggregationRow(
        run_id=run_id, timestamp=_TS, date=_DATE, sector=sector,
        n_companies=1, n_bull=1, n_mixed=0, n_neutral=0,
        n_near_threshold=0, n_broken=0, n_tracked=0, n_na=0,
        company_derived_read=read,
        top_bull_companies="A", top_mixed_or_risk_companies="",
        tracked_only_companies="",
        notes="", source_ledger="",
    )


def _slrow(*, sector: str, signal: str = "HOLD",
           run_id: str = "RUN-1") -> SectorSignalLogRow:
    return SectorSignalLogRow(
        run_id=run_id, timestamp=_TS, date=_DATE, sector=sector,
        canonical_signal=signal, normalized_score=0.0, raw_score=0.0,
        total_weight=0, n_catalysts=0, n_bull=0, n_neutral=0,
        n_near_threshold=0, n_broken=0, n_emergency_exits=0,
        n_triggered_exits=0,
    )


# --------------------------------------------------------------------------- #
# Module surface
# --------------------------------------------------------------------------- #
class TestSurface:
    def test_imports_cleanly(self, platform):
        assert hasattr(platform, "render")
        assert hasattr(platform, "PAGES")
        assert hasattr(platform, "DISCLAIMER")
        assert hasattr(platform, "GLOSSARY")
        assert hasattr(platform, "collect_platform_status")
        assert hasattr(platform, "collect_sector_summaries")
        assert hasattr(platform, "latest_ledger_rows_per_company")
        assert hasattr(platform, "list_reports")

    def test_page_list_contains_all_required(self, platform):
        required = {
            "Home", "Portfolio", "PortTech", "Sector Thesis",
            "Company Ledger", "MarketPulse", "Daily Setup",
            "Protection", "Transactions", "Reports",
            "Glossary", "Settings / Guardrails",
        }
        assert required <= set(platform.PAGES)
        # Home first so the default landing page is the overview.
        assert platform.PAGES[0] == "Home"

    def test_disclaimer_text(self, platform):
        d = platform.DISCLAIMER
        assert "Research-only platform" in d
        assert "Not a trading signal" in d
        assert "No order execution" in d
        assert "LIVE_TRADING_ENABLED" in d
        assert "False" in d


# --------------------------------------------------------------------------- #
# Glossary
# --------------------------------------------------------------------------- #
class TestGlossary:
    REQUIRED_TERMS = {
        "Canonical signal",
        "Company-derived read",
        "Catalyst",
        "Emergency exit",
        "Change log",
        "Event annotation",
        "Sector aggregation",
        "Drawdown",
        "Risk-on / Risk-off",
        "Macro regime",
        "Exposure",
        "P&L",
    }

    def test_all_required_terms_present(self, platform):
        terms = {g["term"] for g in platform.glossary_terms()}
        missing = self.REQUIRED_TERMS - terms
        assert not missing, f"missing glossary terms: {missing}"

    def test_glossary_terms_returns_list_of_dicts(self, platform):
        out = platform.glossary_terms()
        assert isinstance(out, list)
        for entry in out:
            assert "term" in entry and "definition" in entry
            assert entry["term"] and entry["definition"]

    def test_glossary_call_is_a_copy(self, platform):
        # Mutating the returned list must not mutate the module-level
        # GLOSSARY constant.
        out = platform.glossary_terms()
        out.clear()
        assert len(platform.glossary_terms()) > 0


# --------------------------------------------------------------------------- #
# Hard guardrails: no broker / IBKR / order / file-write tokens.
# --------------------------------------------------------------------------- #
class TestGuardrails:
    PLATFORM_SOURCE = (
        REPO_ROOT / "apps" / "portfolio_platform.py"
    ).read_text(encoding="utf-8")

    def test_live_trading_disabled(self):
        assert quantbot.LIVE_TRADING_ENABLED is False

    def test_no_broker_or_order_tokens(self):
        for token in ("ib_insync", "place_order", "submit_order",
                      "from broker", "import broker", "ibapi"):
            assert token not in self.PLATFORM_SOURCE, (
                f"forbidden token {token!r} appears in portfolio_platform.py"
            )

    def test_no_obvious_write_operations(self):
        # The platform must NEVER write. Block the common write paths.
        # We use regex so we ignore the literal word in docstrings — only
        # actual call sites count.
        patterns = [
            r"\.write_text\(",
            r"\.write_bytes\(",
            r"csv\.writer\(",
            r"csv\.DictWriter\(",
            r"\.unlink\(",
            r"os\.remove\(",
            r"shutil\.move\(",
            r"shutil\.copy",
            # Catch open("path","w") and friends.
            r"""open\([^)]*,\s*["']w""",
            r"""open\([^)]*,\s*["']a""",
        ]
        for pat in patterns:
            assert not re.search(pat, self.PLATFORM_SOURCE), (
                f"write-related pattern {pat!r} found in portfolio_platform.py"
            )

    def test_no_network_imports(self):
        # No requests / urllib / aiohttp / socket imports.
        for token in ("import requests", "import urllib",
                      "import aiohttp", "import socket",
                      "from requests", "from urllib", "from aiohttp",
                      "from socket"):
            assert token not in self.PLATFORM_SOURCE, (
                f"forbidden network import {token!r} in platform"
            )


# --------------------------------------------------------------------------- #
# collect_platform_status — empty + populated cases
# --------------------------------------------------------------------------- #
class TestPlatformStatus:
    def test_empty_data_dir_yields_no_artefacts(self, tmp_path: Path,
                                                  platform):
        ddir = tmp_path / "data"
        ddir.mkdir()
        rroot = tmp_path / "reports"
        # rroot intentionally missing
        s = platform.collect_platform_status(
            data_dir=ddir, report_root=rroot,
        )
        assert s.has_ledger is False
        assert s.has_aggregation is False
        assert s.has_signal_log is False
        assert s.has_change_log is False
        assert s.has_annotations is False
        assert s.has_reports_root is False
        assert s.n_company_ledger_rows == 0
        assert s.n_aggregation_rows == 0
        assert s.n_signal_log_rows == 0
        assert s.sectors_with_catalysts == []

    def test_populated_data_dir_detects_artefacts(self, tmp_path: Path,
                                                    platform):
        ddir = tmp_path / "data"
        ddir.mkdir()
        rroot = tmp_path / "reports"
        rroot.mkdir()
        # Plant a SEMICONDUCTOR catalyst CSV and a ledger row.
        save_catalysts(
            [_cat(cid="A", sector="SEMICONDUCTOR")],
            ddir / "semiconductor_thesis_tracker.csv",
        )
        append_company_ledger_rows(
            [_lrow(ticker="NVDA", sector="SEMICONDUCTOR")],
            ddir / "company_signal_ledger.csv",
        )
        append_sector_aggregation_rows(
            [_arow(sector="SEMICONDUCTOR")],
            ddir / "company_sector_aggregation.csv",
        )
        append_sector_signal_log_rows(
            [_slrow(sector="SEMICONDUCTOR")],
            ddir / "sector_signal_log.csv",
        )
        s = platform.collect_platform_status(
            data_dir=ddir, report_root=rroot,
        )
        assert s.has_ledger is True
        assert s.has_aggregation is True
        assert s.has_signal_log is True
        assert s.has_reports_root is True
        assert s.n_company_ledger_rows == 1
        assert s.n_aggregation_rows == 1
        assert s.n_signal_log_rows == 1
        assert s.sectors_with_catalysts == ["SEMICONDUCTOR"]


# --------------------------------------------------------------------------- #
# collect_sector_summaries — uses canonical V6.1 score_sector
# --------------------------------------------------------------------------- #
class TestSectorSummaries:
    def test_empty_data_dir(self, tmp_path: Path, platform):
        ddir = tmp_path / "data"
        ddir.mkdir()
        assert platform.collect_sector_summaries(data_dir=ddir) == []

    def test_one_sector_with_catalysts(self, tmp_path: Path, platform):
        ddir = tmp_path / "data"
        ddir.mkdir()
        save_catalysts(
            [_cat(cid="A", sector="SEMICONDUCTOR", status="BULL"),
             _cat(cid="B", sector="SEMICONDUCTOR", status="BROKEN")],
            ddir / "semiconductor_thesis_tracker.csv",
        )
        out = platform.collect_sector_summaries(data_dir=ddir)
        assert len(out) == 1
        s = out[0]
        assert s.sector == "SEMICONDUCTOR"
        assert s.n_catalysts == 2
        assert s.n_bull == 1
        assert s.n_broken == 1
        # signal is whatever the V6.1 scorer returns — we don't re-derive it
        # in this module.
        assert s.signal  # non-empty string

    def test_triggered_exit_propagates_to_summary(self, tmp_path: Path,
                                                    platform):
        ddir = tmp_path / "data"
        ddir.mkdir()
        save_catalysts(
            [_cat(cid="A", sector="AI", status="BULL")],
            ddir / "ai_thesis_tracker.csv",
        )
        save_exits(
            [EmergencyExit(
                exit_id="AI-EX-1", sector="AI",
                scenario="x", trigger_condition="t",
                current_status="TRIGGERED", action="a",
                source="s", last_updated="2026-05-28",
            )],
            ddir / "ai_emergency_exits.csv",
        )
        out = platform.collect_sector_summaries(data_dir=ddir)
        ai = next(s for s in out if s.sector == "AI")
        assert ai.signal == "EXIT_WATCH"
        assert "AI-EX-1" in ai.triggered_exits


# --------------------------------------------------------------------------- #
# Ledger / aggregation / signal log latest-row helpers
# --------------------------------------------------------------------------- #
class TestLatestHelpers:
    def test_ledger_missing_returns_empty(self, tmp_path: Path, platform):
        assert (platform.latest_ledger_rows_per_company(
            ledger_path=tmp_path / "nope.csv",
        ) == [])

    def test_ledger_latest_per_company(self, tmp_path: Path, platform):
        p = tmp_path / "ledger.csv"
        append_company_ledger_rows([
            _lrow(ticker="NVDA", sector="SEMICONDUCTOR", read="BULL",
                  run_id="RUN-1"),
            _lrow(ticker="NVDA", sector="SEMICONDUCTOR", read="MIXED",
                  run_id="RUN-2"),
            _lrow(ticker="AMD", sector="SEMICONDUCTOR", read="BULL",
                  run_id="RUN-1"),
        ], p)
        rows = platform.latest_ledger_rows_per_company(ledger_path=p)
        # Both companies represented, NVDA carries RUN-2.
        assert {(r.sector, r.ticker, r.read) for r in rows} == {
            ("SEMICONDUCTOR", "NVDA", "MIXED"),
            ("SEMICONDUCTOR", "AMD", "BULL"),
        }

    def test_aggregation_missing_returns_empty(self, tmp_path: Path,
                                                 platform):
        assert (platform.latest_aggregation_rows(
            aggregation_path=tmp_path / "x.csv",
        ) == [])

    def test_aggregation_latest_per_sector(self, tmp_path: Path, platform):
        p = tmp_path / "agg.csv"
        append_sector_aggregation_rows([
            _arow(sector="SEMICONDUCTOR", read="BULL", run_id="RUN-1"),
            _arow(sector="SEMICONDUCTOR", read="CAUTION", run_id="RUN-2"),
            _arow(sector="AI", read="BULL", run_id="RUN-2"),
        ], p)
        rows = platform.latest_aggregation_rows(aggregation_path=p)
        by_sector = {r.sector: r for r in rows}
        assert by_sector["SEMICONDUCTOR"].company_derived_read == "CAUTION"
        assert by_sector["SEMICONDUCTOR"].run_id == "RUN-2"

    def test_signal_log_latest_per_sector(self, tmp_path: Path, platform):
        p = tmp_path / "log.csv"
        append_sector_signal_log_rows([
            _slrow(sector="SEMICONDUCTOR", signal="HOLD", run_id="RUN-1"),
            _slrow(sector="SEMICONDUCTOR", signal="SELECTIVE_BUY",
                   run_id="RUN-2"),
        ], p)
        rows = platform.latest_signal_log_rows(signal_log_path=p)
        assert rows[0].canonical_signal == "SELECTIVE_BUY"


# --------------------------------------------------------------------------- #
# Reports listing
# --------------------------------------------------------------------------- #
class TestReportsListing:
    def test_missing_root_returns_empty(self, tmp_path: Path, platform):
        assert platform.list_reports(
            report_root=tmp_path / "absent",
        ) == []

    def test_lists_allowed_extensions_only(self, tmp_path: Path, platform):
        root = tmp_path / "reports"
        root.mkdir()
        (root / "a.md").write_text("a", encoding="utf-8")
        (root / "b.csv").write_text("b", encoding="utf-8")
        (root / "c.txt").write_text("c", encoding="utf-8")
        (root / "d.bin").write_text("d", encoding="utf-8")
        (root / "e.png").write_text("e", encoding="utf-8")
        files = platform.list_reports(report_root=root)
        names = sorted(f.name for f in files)
        assert names == ["a.md", "b.csv", "c.txt"]

    def test_research_subdir_classified_separately(self, tmp_path: Path,
                                                     platform):
        root = tmp_path / "reports"
        sub = root / "research"
        sub.mkdir(parents=True)
        (root / "top.md").write_text("x", encoding="utf-8")
        (sub / "deep.md").write_text("y", encoding="utf-8")
        files = platform.list_reports(report_root=root)
        kinds = {f.name: f.kind for f in files}
        assert kinds["top.md"] == "report"
        assert kinds["deep.md"] == "research"

    def test_max_files_cap_respected(self, tmp_path: Path, platform):
        root = tmp_path / "reports"
        root.mkdir()
        for i in range(10):
            (root / f"r{i:02d}.md").write_text("x", encoding="utf-8")
        files = platform.list_reports(report_root=root, max_files=4)
        assert len(files) == 4


# --------------------------------------------------------------------------- #
# Transactions detector
# --------------------------------------------------------------------------- #
class TestTransactions:
    def test_missing_returns_none(self, tmp_path: Path, platform):
        assert platform.find_transactions_file(
            path=tmp_path / "nope.csv",
        ) is None

    def test_present_returns_path(self, tmp_path: Path, platform):
        p = tmp_path / "tx.csv"
        p.write_text("date,sym,qty\n", encoding="utf-8")
        assert platform.find_transactions_file(path=p) == p


# --------------------------------------------------------------------------- #
# Existing V6 dashboard still importable
# --------------------------------------------------------------------------- #
class TestDashboardStillWorks:
    def test_v6_dashboard_imports_cleanly(self):
        sys.path.insert(0, str(REPO_ROOT / "apps"))
        try:
            dash = importlib.import_module("sector_thesis_dashboard")
            assert hasattr(dash, "render")
            assert hasattr(dash, "SECTORS")
        finally:
            if str(REPO_ROOT / "apps") in sys.path:
                sys.path.remove(str(REPO_ROOT / "apps"))
