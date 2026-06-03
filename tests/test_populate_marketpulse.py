"""V7.8.1 — Tests for the MarketPulse data-population helper.

Covers:

  * Each of ``add_regime_row`` / ``add_etf_row`` / ``add_event_row`` (and
    the matching CLI subcommands) appends one validated row to the right
    CSV, creates a header on first call, and round-trips via the V7.8
    readers.
  * Idempotent / append / strict modes behave per spec.
  * Required-field and enum validation: rejections come back through
    ``PopulateMarketPulseValidationError`` (or the V7.8 dataclass
    ``MarketPulseSchemaError`` as defence in depth).
  * Cache-only ``from-fred`` subcommand reads an existing local cache file
    and refuses to fall back to anything network-like when the cache is
    missing.
  * **Hard guardrails**: no broker / IBKR / order tokens; no network
    imports; no ThetaData import; ``LIVE_TRADING_ENABLED`` False.
  * The new append helpers in ``marketpulse/readers.py`` are append-only
    and never rewrite existing rows.
  * MarketPulse platform page still loads cleanly with the new helpers.
"""

from __future__ import annotations

import csv
import importlib
import sys
from pathlib import Path

import pytest

import quantbot
from quantbot.research.marketpulse import (
    REGIME_DASHBOARD_FIELDS,
    SECTOR_ETF_FIELDS,
    EVENT_CALENDAR_FIELDS,
    RegimeRow,
    SectorETFRow,
    EventCalendarRow,
    MarketPulseSchemaError,
    append_event_calendar_rows,
    append_regime_rows,
    append_sector_etf_rows,
    load_event_calendar,
    load_regime_dashboard,
    load_sector_etf_scoreboard,
    ensure_event_calendar_header,
    ensure_regime_dashboard_header,
    ensure_sector_etf_scoreboard_header,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture
def populate():
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        yield importlib.import_module("populate_marketpulse")
    finally:
        if str(REPO_ROOT / "scripts") in sys.path:
            sys.path.remove(str(REPO_ROOT / "scripts"))


# --------------------------------------------------------------------------- #
# Guardrails (script-level + new helpers)
# --------------------------------------------------------------------------- #
class TestGuardrails:
    SCRIPT_SOURCE = (
        REPO_ROOT / "scripts" / "populate_marketpulse.py"
    ).read_text(encoding="utf-8")
    READERS_SOURCE = (
        REPO_ROOT / "src" / "quantbot" / "research"
        / "marketpulse" / "readers.py"
    ).read_text(encoding="utf-8")

    def test_live_trading_disabled(self):
        assert quantbot.LIVE_TRADING_ENABLED is False

    def test_no_broker_or_order_tokens(self):
        for src in (self.SCRIPT_SOURCE, self.READERS_SOURCE):
            for token in ("ib_insync", "place_order", "submit_order",
                          "from broker", "import broker", "ibapi"):
                assert token not in src, (
                    f"forbidden broker token {token!r} in V7.8.1 surface"
                )

    def test_no_thetadata_imports(self):
        for src in (self.SCRIPT_SOURCE, self.READERS_SOURCE):
            assert "import thetadata" not in src.lower()
            assert "from thetadata" not in src.lower()

    def test_no_network_imports(self):
        for src in (self.SCRIPT_SOURCE, self.READERS_SOURCE):
            for token in ("import requests", "import urllib",
                          "import aiohttp", "import socket",
                          "from requests", "from urllib", "from aiohttp",
                          "from socket"):
                assert token not in src, (
                    f"forbidden network import {token!r} in V7.8.1 surface"
                )

    def test_script_has_no_live_fred_fetch(self):
        # FRED loader uses urllib + http; V7.8.1 must NOT import it.
        # Cache reading is via csv.DictReader on a local file path only.
        assert "fred_loader" not in self.SCRIPT_SOURCE
        assert "FRED_BASE_URL" not in self.SCRIPT_SOURCE


# --------------------------------------------------------------------------- #
# add-regime
# --------------------------------------------------------------------------- #
class TestAddRegimeRow:
    def _kwargs(self, **over):
        base = dict(
            panel="RATES", indicator="10Y Treasury yield",
            value="4.45", status="NEUTRAL",
            interpretation="mid", source="FRED",
            source_file="dgs10.csv", last_updated="2026-06-03",
        )
        base.update(over)
        return base

    def test_happy_path_appends(self, tmp_path: Path, populate):
        p = tmp_path / "regime.csv"
        result = populate.add_regime_row(path=p, **self._kwargs())
        assert result["row_kind"] == "regime"
        assert result["n_appended"] == 1
        rows = load_regime_dashboard(p)
        assert len(rows) == 1
        assert rows[0].panel == "RATES"
        assert rows[0].status == "NEUTRAL"

    def test_creates_header_when_missing(self, tmp_path: Path, populate):
        p = tmp_path / "regime.csv"
        assert not p.is_file()
        populate.add_regime_row(path=p, **self._kwargs())
        with p.open("r", encoding="utf-8") as fh:
            header = next(csv.reader(fh))
        assert header == list(REGIME_DASHBOARD_FIELDS)

    def test_idempotent_same_key_is_noop(self, tmp_path: Path, populate):
        p = tmp_path / "regime.csv"
        populate.add_regime_row(path=p, **self._kwargs())
        first_size = p.stat().st_size
        second = populate.add_regime_row(path=p, **self._kwargs())
        assert second["n_appended"] == 0
        assert second["n_skipped"] == 1
        assert p.stat().st_size == first_size

    def test_strict_mode_raises_on_duplicate(self, tmp_path: Path, populate):
        p = tmp_path / "regime.csv"
        populate.add_regime_row(path=p, **self._kwargs())
        with pytest.raises(MarketPulseSchemaError):
            populate.add_regime_row(
                path=p, mode="strict", **self._kwargs(),
            )

    def test_append_mode_writes_duplicate(self, tmp_path: Path, populate):
        p = tmp_path / "regime.csv"
        populate.add_regime_row(path=p, **self._kwargs())
        populate.add_regime_row(path=p, mode="append", **self._kwargs())
        assert len(load_regime_dashboard(p)) == 2

    def test_different_last_updated_is_not_duplicate(self, tmp_path: Path,
                                                       populate):
        # Same panel+indicator but newer date should append a new row.
        p = tmp_path / "regime.csv"
        populate.add_regime_row(
            path=p, **self._kwargs(last_updated="2026-06-03"),
        )
        result = populate.add_regime_row(
            path=p, **self._kwargs(last_updated="2026-06-04"),
        )
        assert result["n_appended"] == 1
        assert len(load_regime_dashboard(p)) == 2

    @pytest.mark.parametrize("missing", ["panel", "indicator",
                                          "value", "status"])
    def test_required_non_empty_fields(self, tmp_path: Path, populate,
                                         missing):
        p = tmp_path / "regime.csv"
        kw = self._kwargs(**{missing: ""})
        with pytest.raises(populate.PopulateMarketPulseValidationError):
            populate.add_regime_row(path=p, **kw)
        assert not p.is_file() or p.stat().st_size == 0

    def test_invalid_panel_rejected(self, tmp_path: Path, populate):
        p = tmp_path / "regime.csv"
        with pytest.raises(populate.PopulateMarketPulseValidationError):
            populate.add_regime_row(path=p, **self._kwargs(panel="WAT"))

    def test_invalid_status_rejected(self, tmp_path: Path, populate):
        p = tmp_path / "regime.csv"
        with pytest.raises(populate.PopulateMarketPulseValidationError):
            populate.add_regime_row(
                path=p, **self._kwargs(status="LOL"),
            )


# --------------------------------------------------------------------------- #
# add-etf
# --------------------------------------------------------------------------- #
class TestAddETFRow:
    def _kwargs(self, **over):
        base = dict(
            ticker="SPY", sector="BROAD", theme="benchmark",
            price="500.00", return_1d="+0.5%", return_1w="+1.0%",
            return_1m="+3.0%", trend_status="UPTREND",
            risk_note="", source="MANUAL", last_updated="2026-06-03",
        )
        base.update(over)
        return base

    def test_happy_path(self, tmp_path: Path, populate):
        p = tmp_path / "etf.csv"
        result = populate.add_etf_row(path=p, **self._kwargs())
        assert result["n_appended"] == 1
        rows = load_sector_etf_scoreboard(p)
        assert rows[0].ticker == "SPY"
        assert rows[0].trend_status == "UPTREND"

    def test_idempotent_same_ticker_date(self, tmp_path: Path, populate):
        p = tmp_path / "etf.csv"
        populate.add_etf_row(path=p, **self._kwargs())
        second = populate.add_etf_row(path=p, **self._kwargs())
        assert second["n_skipped"] == 1
        assert len(load_sector_etf_scoreboard(p)) == 1

    def test_invalid_trend_status(self, tmp_path: Path, populate):
        p = tmp_path / "etf.csv"
        with pytest.raises(populate.PopulateMarketPulseValidationError):
            populate.add_etf_row(
                path=p, **self._kwargs(trend_status="WAT"),
            )

    @pytest.mark.parametrize("missing", ["ticker", "sector"])
    def test_required_non_empty(self, tmp_path: Path, populate, missing):
        p = tmp_path / "etf.csv"
        with pytest.raises(populate.PopulateMarketPulseValidationError):
            populate.add_etf_row(path=p, **self._kwargs(**{missing: ""}))


# --------------------------------------------------------------------------- #
# add-event
# --------------------------------------------------------------------------- #
class TestAddEventRow:
    def _kwargs(self, **over):
        base = dict(
            date="2026-06-11", event="CPI YoY", time="08:30",
            country="US", expected="2.7%", actual="", prior="2.8%",
            impact="HIGH", notes="core focus", source="MANUAL",
            last_updated="2026-06-03",
        )
        base.update(over)
        return base

    def test_happy_path(self, tmp_path: Path, populate):
        p = tmp_path / "events.csv"
        result = populate.add_event_row(path=p, **self._kwargs())
        assert result["n_appended"] == 1
        rows = load_event_calendar(p)
        assert rows[0].event == "CPI YoY"

    def test_idempotent_same_date_event_country(self, tmp_path: Path,
                                                  populate):
        p = tmp_path / "events.csv"
        populate.add_event_row(path=p, **self._kwargs())
        second = populate.add_event_row(path=p, **self._kwargs())
        assert second["n_skipped"] == 1
        assert len(load_event_calendar(p)) == 1

    def test_invalid_impact(self, tmp_path: Path, populate):
        p = tmp_path / "events.csv"
        with pytest.raises(populate.PopulateMarketPulseValidationError):
            populate.add_event_row(
                path=p, **self._kwargs(impact="WAT"),
            )

    @pytest.mark.parametrize("missing", ["date", "event"])
    def test_required_non_empty(self, tmp_path: Path, populate, missing):
        p = tmp_path / "events.csv"
        with pytest.raises(populate.PopulateMarketPulseValidationError):
            populate.add_event_row(path=p, **self._kwargs(**{missing: ""}))


# --------------------------------------------------------------------------- #
# from-fred (cache-only)
# --------------------------------------------------------------------------- #
class TestFromFred:
    def _make_cache(self, tmp_path: Path) -> Path:
        cdir = tmp_path / "macro" / "fred"
        cdir.mkdir(parents=True)
        p = cdir / "DGS10.csv"
        p.write_text(
            "date,value\n"
            "2026-05-28,4.61\n"
            "2026-05-29,4.67\n"
            "2026-06-01,4.57\n",
            encoding="utf-8",
        )
        return p

    def test_appends_from_cache(self, tmp_path: Path, populate):
        self._make_cache(tmp_path)
        rp = tmp_path / "regime.csv"
        result = populate.from_fred(
            series="DGS10", panel="RATES",
            indicator="10Y Treasury yield", status="NEUTRAL",
            interpretation="latest cache",
            cache_dir=tmp_path / "macro" / "fred",
            path=rp,
        )
        assert result["n_appended"] == 1
        rows = load_regime_dashboard(rp)
        assert rows[0].value == "4.57"
        # Cache date populates last_updated by default.
        assert rows[0].last_updated == "2026-06-01"
        assert rows[0].source == "FRED_CACHE"

    def test_missing_cache_fails_clearly(self, tmp_path: Path, populate):
        rp = tmp_path / "regime.csv"
        with pytest.raises(populate.PopulateMarketPulseValidationError) as ei:
            populate.from_fred(
                series="DGS_NOPE", panel="RATES",
                indicator="missing", status="N_A",
                cache_dir=tmp_path / "absent",
                path=rp,
            )
        # The error message must make it clear we do NOT fetch from FRED.
        assert "does NOT fetch" in str(ei.value) or "not found" in str(ei.value)
        assert not rp.is_file()

    def test_empty_cache_fails_clearly(self, tmp_path: Path, populate):
        cdir = tmp_path / "macro" / "fred"
        cdir.mkdir(parents=True)
        (cdir / "DGS10.csv").write_text("date,value\n", encoding="utf-8")
        rp = tmp_path / "regime.csv"
        with pytest.raises(populate.PopulateMarketPulseValidationError):
            populate.from_fred(
                series="DGS10", panel="RATES",
                indicator="10Y", status="N_A",
                cache_dir=cdir, path=rp,
            )

    def test_explicit_cache_path_override(self, tmp_path: Path, populate):
        # Operator passes --cache to point at a file outside the default
        # data/macro/fred/ layout.
        cp = tmp_path / "weird_location.csv"
        cp.write_text("date,value\n2026-06-02,3.50\n", encoding="utf-8")
        rp = tmp_path / "regime.csv"
        result = populate.from_fred(
            series="CUSTOM", panel="INFLATION",
            indicator="custom indicator", status="MIXED",
            cache_path=cp,
            path=rp,
        )
        assert result["n_appended"] == 1
        rows = load_regime_dashboard(rp)
        assert rows[0].value == "3.50"
        assert rows[0].last_updated == "2026-06-02"

    def test_malformed_cache_fails(self, tmp_path: Path, populate):
        cp = tmp_path / "weird.csv"
        cp.write_text("foo,bar\n1,2\n", encoding="utf-8")
        rp = tmp_path / "regime.csv"
        with pytest.raises(populate.PopulateMarketPulseValidationError) as ei:
            populate.from_fred(
                series="X", panel="RATES",
                indicator="x", status="N_A",
                cache_path=cp, path=rp,
            )
        assert "date,value" in str(ei.value) or "columns" in str(ei.value)


# --------------------------------------------------------------------------- #
# CLI round-trip
# --------------------------------------------------------------------------- #
class TestCLI:
    def test_add_regime_cli(self, tmp_path: Path, populate):
        p = tmp_path / "regime.csv"
        rc = populate.cli([
            "add-regime",
            "--panel", "RATES",
            "--indicator", "10Y Treasury yield",
            "--value", "4.45",
            "--status", "NEUTRAL",
            "--last-updated", "2026-06-03",
            "--path", str(p),
        ])
        assert rc == 0
        assert len(load_regime_dashboard(p)) == 1

    def test_add_etf_cli(self, tmp_path: Path, populate):
        p = tmp_path / "etf.csv"
        rc = populate.cli([
            "add-etf",
            "--ticker", "SPY",
            "--sector", "BROAD",
            "--trend-status", "UPTREND",
            "--last-updated", "2026-06-03",
            "--path", str(p),
        ])
        assert rc == 0
        assert len(load_sector_etf_scoreboard(p)) == 1

    def test_add_event_cli(self, tmp_path: Path, populate):
        p = tmp_path / "events.csv"
        rc = populate.cli([
            "add-event",
            "--date", "2026-06-11",
            "--event", "CPI YoY",
            "--impact", "HIGH",
            "--last-updated", "2026-06-03",
            "--path", str(p),
        ])
        assert rc == 0
        assert len(load_event_calendar(p)) == 1

    def test_invalid_panel_returns_nonzero(self, tmp_path: Path,
                                             populate):
        p = tmp_path / "regime.csv"
        # argparse rejects unknown --panel choices before our code runs.
        with pytest.raises(SystemExit):
            populate.cli([
                "add-regime",
                "--panel", "WAT",
                "--indicator", "x",
                "--value", "1",
                "--status", "NEUTRAL",
                "--path", str(p),
            ])

    def test_empty_value_returns_nonzero(self, tmp_path: Path,
                                          populate, capsys):
        p = tmp_path / "regime.csv"
        # argparse may accept --value "" (empty string); our CLI checks
        # surface a clean exit code 2 with a friendly message.
        rc = populate.cli([
            "add-regime",
            "--panel", "RATES",
            "--indicator", "x",
            "--value", "",
            "--status", "NEUTRAL",
            "--path", str(p),
        ])
        assert rc == 2
        captured = capsys.readouterr()
        assert "rejected" in captured.err.lower()


# --------------------------------------------------------------------------- #
# Append helpers — append-only & mode-correctness
# --------------------------------------------------------------------------- #
class TestAppendHelpers:
    def test_invalid_mode_rejected(self, tmp_path: Path):
        with pytest.raises(ValueError):
            append_regime_rows(
                [RegimeRow(panel="RATES", indicator="x",
                            value="1", status="NEUTRAL")],
                tmp_path / "r.csv", mode="bogus",
            )

    def test_append_only_preserves_prior_bytes(self, tmp_path: Path):
        p = tmp_path / "r.csv"
        append_regime_rows(
            [RegimeRow(panel="RATES", indicator="a",
                        value="1", status="NEUTRAL",
                        last_updated="2026-06-01")],
            p,
        )
        original = p.read_bytes()
        append_regime_rows(
            [RegimeRow(panel="RATES", indicator="b",
                        value="2", status="NEUTRAL",
                        last_updated="2026-06-01")],
            p,
        )
        # Re-append the original row idempotently — bytes still preserved.
        append_regime_rows(
            [RegimeRow(panel="RATES", indicator="a",
                        value="1", status="NEUTRAL",
                        last_updated="2026-06-01")],
            p,
        )
        assert p.read_bytes().startswith(original)

    def test_etf_idempotence_by_ticker_and_date(self, tmp_path: Path):
        p = tmp_path / "etf.csv"
        rows = [SectorETFRow(ticker="SPY", sector="BROAD",
                              last_updated="2026-06-01")]
        append_sector_etf_rows(rows, p)
        r2 = append_sector_etf_rows(rows, p)
        assert r2["n_skipped"] == 1

    def test_event_idempotence_by_date_event_country(self, tmp_path: Path):
        p = tmp_path / "ev.csv"
        rows = [EventCalendarRow(
            date="2026-06-11", event="CPI YoY", country="US",
            impact="HIGH",
        )]
        append_event_calendar_rows(rows, p)
        r2 = append_event_calendar_rows(rows, p)
        assert r2["n_skipped"] == 1

    def test_strict_mode_raises(self, tmp_path: Path):
        p = tmp_path / "ev.csv"
        rows = [EventCalendarRow(
            date="2026-06-11", event="CPI YoY", country="US",
            impact="HIGH",
        )]
        append_event_calendar_rows(rows, p)
        with pytest.raises(MarketPulseSchemaError):
            append_event_calendar_rows(rows, p, mode="strict")


# --------------------------------------------------------------------------- #
# Regression: V7.8 platform module still loads cleanly with V7.8.1 helpers
# --------------------------------------------------------------------------- #
class TestPlatformRegression:
    def test_platform_module_still_imports(self):
        sys.path.insert(0, str(REPO_ROOT / "apps"))
        try:
            mod = importlib.import_module("portfolio_platform")
            assert hasattr(mod, "load_marketpulse_snapshot")
            assert hasattr(mod, "compute_pulse_overview")
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
