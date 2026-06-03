"""V7.8 — Tests for the MarketPulse macro shell.

Covers:

  * Schema validation for :class:`RegimeRow`, :class:`SectorETFRow`,
    :class:`EventCalendarRow` (required fields, enums, ISO date check).
  * Readers handle missing / header-only / populated CSVs.
  * ``ensure_*_header`` is idempotent (does not rewrite existing rows).
  * Platform helpers: ``load_marketpulse_snapshot``,
    ``compute_pulse_overview``, ``group_regime_by_panel``, ``data_gaps``.
  * **Hard guardrails**: the marketpulse package has no broker / IBKR /
    network / ThetaData imports; the platform module still has no
    file-write or network tokens; ``LIVE_TRADING_ENABLED`` False.
  * Existing V6 sector dashboard still imports cleanly (V7.8 added a new
    module path but did not change V6).
"""

from __future__ import annotations

import csv
import importlib
import re
import sys
from pathlib import Path

import pytest

import quantbot
from quantbot.research.marketpulse import (
    ALLOWED_EVENT_IMPACT,
    ALLOWED_REGIME_PANELS,
    ALLOWED_REGIME_STATUS,
    ALLOWED_TREND_STATUS,
    EVENT_CALENDAR_FIELDS,
    EventCalendarRow,
    MarketPulseSchemaError,
    REGIME_DASHBOARD_FIELDS,
    RegimeRow,
    SECTOR_ETF_FIELDS,
    SectorETFRow,
    ensure_event_calendar_header,
    ensure_regime_dashboard_header,
    ensure_sector_etf_scoreboard_header,
    load_event_calendar,
    load_regime_dashboard,
    load_sector_etf_scoreboard,
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
# Schema — enums
# --------------------------------------------------------------------------- #
class TestEnums:
    def test_panels_set(self):
        assert ALLOWED_REGIME_PANELS == {
            "RATES", "INFLATION", "LABOR", "GROWTH",
            "VOLATILITY", "CREDIT_RISK", "RISK_ON_OFF",
        }

    def test_regime_status_set(self):
        assert ALLOWED_REGIME_STATUS == {
            "BULLISH", "NEUTRAL", "BEARISH", "MIXED", "N_A",
        }

    def test_trend_status_set(self):
        assert ALLOWED_TREND_STATUS == {
            "UPTREND", "DOWNTREND", "SIDEWAYS", "N_A",
        }

    def test_event_impact_set(self):
        assert ALLOWED_EVENT_IMPACT == {"LOW", "MEDIUM", "HIGH", "N_A"}

    def test_csv_field_orders_stable(self):
        assert REGIME_DASHBOARD_FIELDS[0] == "panel"
        assert "status" in REGIME_DASHBOARD_FIELDS
        assert "last_updated" in REGIME_DASHBOARD_FIELDS
        assert SECTOR_ETF_FIELDS[0] == "ticker"
        assert "trend_status" in SECTOR_ETF_FIELDS
        assert EVENT_CALENDAR_FIELDS[0] == "date"
        assert "impact" in EVENT_CALENDAR_FIELDS


# --------------------------------------------------------------------------- #
# RegimeRow
# --------------------------------------------------------------------------- #
class TestRegimeRow:
    def _row(self, **over):
        base = dict(
            panel="RATES", indicator="10Y Treasury yield",
            value="4.45", status="NEUTRAL",
            interpretation="mid-range", source="FRED",
            source_file="dgs10.csv", last_updated="2026-06-01",
        )
        base.update(over)
        return base

    def test_valid_constructs(self):
        r = RegimeRow(**self._row())
        assert r.panel == "RATES"
        assert r.status == "NEUTRAL"

    @pytest.mark.parametrize("missing", ["panel", "indicator", "status"])
    def test_required_non_empty(self, missing):
        with pytest.raises(MarketPulseSchemaError):
            RegimeRow(**self._row(**{missing: ""}))

    def test_invalid_panel_rejected(self):
        with pytest.raises(MarketPulseSchemaError):
            RegimeRow(**self._row(panel="WAT"))

    def test_invalid_status_rejected(self):
        with pytest.raises(MarketPulseSchemaError):
            RegimeRow(**self._row(status="LOL"))

    def test_invalid_iso_date_rejected(self):
        with pytest.raises(MarketPulseSchemaError):
            RegimeRow(**self._row(last_updated="not a date"))

    def test_empty_iso_date_allowed(self):
        # Operator may leave last_updated blank when first staging a row.
        r = RegimeRow(**self._row(last_updated=""))
        assert r.last_updated == ""


# --------------------------------------------------------------------------- #
# SectorETFRow
# --------------------------------------------------------------------------- #
class TestSectorETFRow:
    def _row(self, **over):
        base = dict(
            ticker="SPY", sector="BROAD",
            theme="benchmark", price="500.00",
            return_1d="+0.5%", return_1w="+1.0%", return_1m="+3.0%",
            trend_status="UPTREND", risk_note="",
            source="MANUAL", last_updated="2026-06-01",
        )
        base.update(over)
        return base

    def test_valid_constructs(self):
        r = SectorETFRow(**self._row())
        assert r.ticker == "SPY"
        assert r.trend_status == "UPTREND"

    @pytest.mark.parametrize("missing", ["ticker", "sector"])
    def test_required_non_empty(self, missing):
        with pytest.raises(MarketPulseSchemaError):
            SectorETFRow(**self._row(**{missing: ""}))

    def test_invalid_trend_status_rejected(self):
        with pytest.raises(MarketPulseSchemaError):
            SectorETFRow(**self._row(trend_status="WAT"))

    def test_trend_status_defaults_to_na(self):
        r = SectorETFRow(ticker="SPY", sector="BROAD")
        assert r.trend_status == "N_A"


# --------------------------------------------------------------------------- #
# EventCalendarRow
# --------------------------------------------------------------------------- #
class TestEventCalendarRow:
    def _row(self, **over):
        base = dict(
            date="2026-06-11", event="CPI YoY",
            time="08:30", country="US",
            expected="2.7%", actual="", prior="2.8%",
            impact="HIGH", notes="", source="MANUAL",
            last_updated="2026-06-01",
        )
        base.update(over)
        return base

    def test_valid_constructs(self):
        r = EventCalendarRow(**self._row())
        assert r.event == "CPI YoY"
        assert r.impact == "HIGH"

    @pytest.mark.parametrize("missing", ["date", "event"])
    def test_required_non_empty(self, missing):
        with pytest.raises(MarketPulseSchemaError):
            EventCalendarRow(**self._row(**{missing: ""}))

    def test_invalid_impact_rejected(self):
        with pytest.raises(MarketPulseSchemaError):
            EventCalendarRow(**self._row(impact="WAT"))

    def test_invalid_date_rejected(self):
        with pytest.raises(MarketPulseSchemaError):
            EventCalendarRow(**self._row(date="2026-99-99"))


# --------------------------------------------------------------------------- #
# Readers
# --------------------------------------------------------------------------- #
class TestReaders:
    def test_missing_file_returns_empty(self, tmp_path: Path):
        assert load_regime_dashboard(tmp_path / "nope.csv") == []
        assert load_sector_etf_scoreboard(tmp_path / "nope.csv") == []
        assert load_event_calendar(tmp_path / "nope.csv") == []

    def test_header_only_returns_empty(self, tmp_path: Path):
        rp = tmp_path / "regime.csv"
        ensure_regime_dashboard_header(rp)
        sp = tmp_path / "etf.csv"
        ensure_sector_etf_scoreboard_header(sp)
        ep = tmp_path / "events.csv"
        ensure_event_calendar_header(ep)
        assert load_regime_dashboard(rp) == []
        assert load_sector_etf_scoreboard(sp) == []
        assert load_event_calendar(ep) == []

    def test_populated_regime_round_trip(self, tmp_path: Path):
        p = tmp_path / "regime.csv"
        ensure_regime_dashboard_header(p)
        with p.open("a", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(
                fh, fieldnames=list(REGIME_DASHBOARD_FIELDS),
            )
            writer.writerow({
                "panel": "RATES", "indicator": "10Y", "value": "4.45",
                "status": "NEUTRAL", "interpretation": "mid",
                "source": "FRED", "source_file": "dgs10.csv",
                "last_updated": "2026-06-01",
            })
            writer.writerow({
                "panel": "INFLATION", "indicator": "CPI YoY",
                "value": "2.7%", "status": "BEARISH",
                "interpretation": "above target",
                "source": "FRED", "source_file": "cpi.csv",
                "last_updated": "2026-06-01",
            })
        rows = load_regime_dashboard(p)
        assert len(rows) == 2
        assert rows[0].panel == "RATES"
        assert rows[1].status == "BEARISH"

    def test_ensure_header_is_idempotent(self, tmp_path: Path):
        p = tmp_path / "regime.csv"
        ensure_regime_dashboard_header(p)
        original = p.read_bytes()
        # Add a real row.
        with p.open("a", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(
                fh, fieldnames=list(REGIME_DASHBOARD_FIELDS),
            )
            writer.writerow({
                "panel": "GROWTH", "indicator": "ISM",
                "value": "52", "status": "BULLISH",
                "interpretation": "expansion", "source": "MANUAL",
                "source_file": "", "last_updated": "2026-06-01",
            })
        # Second ensure_header MUST NOT rewrite or truncate the file.
        ensure_regime_dashboard_header(p)
        new = p.read_bytes()
        assert new.startswith(original)  # header still there
        # And the data row survived.
        assert len(load_regime_dashboard(p)) == 1


# --------------------------------------------------------------------------- #
# Platform helpers
# --------------------------------------------------------------------------- #
class TestPlatformHelpers:
    def test_empty_snapshot_yields_no_data_label(self, tmp_path: Path,
                                                   platform):
        snap = platform.load_marketpulse_snapshot(
            regime_path=tmp_path / "r.csv",
            sector_etf_path=tmp_path / "s.csv",
            event_calendar_path=tmp_path / "e.csv",
        )
        assert snap.regime_path_exists is False
        assert snap.sector_etf_path_exists is False
        assert snap.event_calendar_path_exists is False
        assert snap.regime_rows == []
        ov = platform.compute_pulse_overview(snap)
        assert ov.label == "no data yet"
        assert ov.panels_populated == 0
        assert ov.panels_total == 7

    def test_header_only_snapshot_still_no_data(self, tmp_path: Path,
                                                  platform):
        rp = tmp_path / "r.csv"
        sp = tmp_path / "s.csv"
        ep = tmp_path / "e.csv"
        ensure_regime_dashboard_header(rp)
        ensure_sector_etf_scoreboard_header(sp)
        ensure_event_calendar_header(ep)
        snap = platform.load_marketpulse_snapshot(
            regime_path=rp, sector_etf_path=sp, event_calendar_path=ep,
        )
        assert snap.regime_path_exists is True
        assert snap.regime_rows == []
        ov = platform.compute_pulse_overview(snap)
        assert ov.label == "no data yet"

    def test_partial_snapshot(self, tmp_path: Path, platform):
        rp = tmp_path / "r.csv"
        sp = tmp_path / "s.csv"
        ep = tmp_path / "e.csv"
        ensure_regime_dashboard_header(rp)
        ensure_sector_etf_scoreboard_header(sp)
        ensure_event_calendar_header(ep)
        with rp.open("a", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(
                fh, fieldnames=list(REGIME_DASHBOARD_FIELDS),
            )
            writer.writerow({
                "panel": "RATES", "indicator": "10Y", "value": "4.45",
                "status": "NEUTRAL", "interpretation": "mid",
                "source": "FRED", "source_file": "",
                "last_updated": "2026-06-01",
            })
            writer.writerow({
                "panel": "INFLATION", "indicator": "CPI", "value": "2.7%",
                "status": "BEARISH", "interpretation": "above",
                "source": "FRED", "source_file": "",
                "last_updated": "2026-06-01",
            })
        snap = platform.load_marketpulse_snapshot(
            regime_path=rp, sector_etf_path=sp, event_calendar_path=ep,
        )
        ov = platform.compute_pulse_overview(snap)
        assert ov.label == "partial"
        assert ov.panels_populated == 2
        assert ov.n_regime_rows == 2

    def test_fully_populated_snapshot(self, tmp_path: Path, platform):
        rp = tmp_path / "r.csv"
        sp = tmp_path / "s.csv"
        ep = tmp_path / "e.csv"
        ensure_regime_dashboard_header(rp)
        ensure_sector_etf_scoreboard_header(sp)
        ensure_event_calendar_header(ep)
        with rp.open("a", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(
                fh, fieldnames=list(REGIME_DASHBOARD_FIELDS),
            )
            for panel in ALLOWED_REGIME_PANELS:
                writer.writerow({
                    "panel": panel, "indicator": "x", "value": "y",
                    "status": "NEUTRAL", "interpretation": "",
                    "source": "MANUAL", "source_file": "",
                    "last_updated": "2026-06-01",
                })
        with sp.open("a", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(SECTOR_ETF_FIELDS))
            writer.writerow({
                "ticker": "SPY", "sector": "BROAD", "theme": "",
                "price": "500", "return_1d": "", "return_1w": "",
                "return_1m": "", "trend_status": "UPTREND",
                "risk_note": "", "source": "MANUAL",
                "last_updated": "2026-06-01",
            })
        snap = platform.load_marketpulse_snapshot(
            regime_path=rp, sector_etf_path=sp, event_calendar_path=ep,
        )
        ov = platform.compute_pulse_overview(snap)
        assert ov.label == "fully populated"
        assert ov.panels_populated == 7

    def test_group_regime_by_panel(self, tmp_path: Path, platform):
        rows = [
            RegimeRow(panel="RATES", indicator="A", value="1",
                       status="NEUTRAL"),
            RegimeRow(panel="RATES", indicator="B", value="2",
                       status="NEUTRAL"),
            RegimeRow(panel="GROWTH", indicator="C", value="3",
                       status="BULLISH"),
        ]
        grouped = platform.group_regime_by_panel(rows)
        assert sorted(grouped) == ["GROWTH", "RATES"]
        assert len(grouped["RATES"]) == 2

    def test_data_gaps_lists_empty_panels(self, tmp_path: Path, platform):
        snap = platform.load_marketpulse_snapshot(
            regime_path=tmp_path / "r.csv",
            sector_etf_path=tmp_path / "s.csv",
            event_calendar_path=tmp_path / "e.csv",
        )
        gaps = platform.data_gaps(snap)
        # 7 panels + sector ETF + calendar = 9 gaps.
        assert len(gaps) == 9
        for panel in ALLOWED_REGIME_PANELS:
            assert any(panel in g for g in gaps)


# --------------------------------------------------------------------------- #
# Guardrails (marketpulse package + platform-side additions)
# --------------------------------------------------------------------------- #
class TestGuardrails:
    PLATFORM_SOURCE = (
        REPO_ROOT / "apps" / "portfolio_platform.py"
    ).read_text(encoding="utf-8")
    SCHEMA_SOURCE = (
        REPO_ROOT / "src" / "quantbot" / "research"
        / "marketpulse" / "schema.py"
    ).read_text(encoding="utf-8")
    READERS_SOURCE = (
        REPO_ROOT / "src" / "quantbot" / "research"
        / "marketpulse" / "readers.py"
    ).read_text(encoding="utf-8")

    def test_live_trading_disabled(self):
        assert quantbot.LIVE_TRADING_ENABLED is False

    def test_no_broker_or_order_tokens_in_marketpulse(self):
        for src in (self.SCHEMA_SOURCE, self.READERS_SOURCE):
            for token in ("ib_insync", "place_order", "submit_order",
                          "from broker", "import broker", "ibapi"):
                assert token not in src, (
                    f"forbidden broker token {token!r} in marketpulse"
                )

    def test_no_thetadata_tokens(self):
        for src in (self.SCHEMA_SOURCE, self.READERS_SOURCE,
                    self.PLATFORM_SOURCE):
            # ThetaData is intentionally absent from V7.8. Mention is only
            # allowed in the "deferred" expander text inside the platform —
            # and that text says ThetaData with a capital T explicitly so
            # we check for an *import* shape instead.
            assert "import thetadata" not in src.lower(), (
                "thetadata import found"
            )
            assert "from thetadata" not in src.lower(), (
                "thetadata import found"
            )

    def test_no_network_imports(self):
        for src in (self.SCHEMA_SOURCE, self.READERS_SOURCE):
            for token in ("import requests", "import urllib",
                          "import aiohttp", "import socket",
                          "from requests", "from urllib", "from aiohttp",
                          "from socket"):
                assert token not in src, (
                    f"forbidden network import {token!r} in marketpulse"
                )

    def test_platform_still_no_write_operations(self):
        # V7.8 only added READ helpers to the platform. Re-run the
        # write-op grep from the V7.0 test as a regression check.
        patterns = [
            r"\.write_text\(",
            r"\.write_bytes\(",
            r"csv\.writer\(",
            r"csv\.DictWriter\(",
            r"\.unlink\(",
            r"os\.remove\(",
            r"shutil\.move\(",
            r"shutil\.copy",
            r"""open\([^)]*,\s*["']w""",
            r"""open\([^)]*,\s*["']a""",
        ]
        for pat in patterns:
            assert not re.search(pat, self.PLATFORM_SOURCE), (
                f"write-related pattern {pat!r} in portfolio_platform.py"
            )

    def test_platform_still_no_network_imports(self):
        for token in ("import requests", "import urllib",
                      "import aiohttp", "import socket",
                      "from requests", "from urllib", "from aiohttp",
                      "from socket"):
            assert token not in self.PLATFORM_SOURCE, (
                f"forbidden network import {token!r} in platform"
            )


# --------------------------------------------------------------------------- #
# V6 dashboard regression — still importable
# --------------------------------------------------------------------------- #
class TestV6Untouched:
    def test_v6_dashboard_still_imports_cleanly(self):
        sys.path.insert(0, str(REPO_ROOT / "apps"))
        try:
            dash = importlib.import_module("sector_thesis_dashboard")
            assert hasattr(dash, "render")
            assert hasattr(dash, "SECTORS")
        finally:
            if str(REPO_ROOT / "apps") in sys.path:
                sys.path.remove(str(REPO_ROOT / "apps"))
