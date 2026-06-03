"""Tests for the V6.5 Sector Thesis Tracker dashboard (apps/sector_thesis_dashboard.py).

These tests exercise the **pure helpers** in the dashboard module — the
streamlit-driven ``render()`` and per-card renderers are excluded by
``# pragma: no cover`` and are not invoked here. The helpers must be safe to
import, deterministic, read-only, and handle missing files gracefully.
"""

from __future__ import annotations

import importlib
import sys
from datetime import date
from pathlib import Path

import pytest

import quantbot
from quantbot.research.sector_tracker import Catalyst, EmergencyExit

REPO_ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def dashboard():
    """Import the dashboard module by absolute path (apps/ is not a package)."""
    sys.path.insert(0, str(REPO_ROOT / "apps"))
    try:
        mod = importlib.import_module("sector_thesis_dashboard")
    finally:
        if str(REPO_ROOT / "apps") in sys.path:
            sys.path.remove(str(REPO_ROOT / "apps"))
    return mod


def _make_cat(*, cid: str, sector: str, tier: int, status: str,
              subsector: str = "X", source: str = "SEC_EDGAR",
              detail: str = "ok") -> Catalyst:
    return Catalyst(
        catalyst_id=cid, sector=sector, subsector=subsector,
        catalyst_name=f"name-{cid}", tier=tier, direction="ABOVE",
        threshold="t", current_value="v", status=status,
        source_type=source, source_detail=detail,
        last_updated="2026-05-28", action_if_broken="review", notes="",
    )


# --------------------------------------------------------------------------- #
# module surface + smoke
# --------------------------------------------------------------------------- #
class TestModuleSurface:
    def test_imports_cleanly(self, dashboard):
        # Importing the module must not call render() or touch the network.
        assert hasattr(dashboard, "render")
        assert hasattr(dashboard, "load_sector")
        assert hasattr(dashboard, "load_all_sectors")
        assert hasattr(dashboard, "filter_catalysts")
        assert hasattr(dashboard, "top_bull_drivers")
        assert hasattr(dashboard, "top_risks")
        assert hasattr(dashboard, "manual_gaps")
        assert hasattr(dashboard, "cross_sector_links")
        assert hasattr(dashboard, "signal_color")
        assert hasattr(dashboard, "status_color")
        assert hasattr(dashboard, "exit_color")
        assert hasattr(dashboard, "aggregate_status_counts")
        assert hasattr(dashboard, "DISCLAIMER")

    def test_sectors_constant(self, dashboard):
        assert dashboard.SECTORS == ("SEMICONDUCTOR", "AI", "ENERGY")

    def test_disclaimer_contains_required_phrase(self, dashboard):
        text = dashboard.DISCLAIMER
        assert ("research signal, not a trading signal, not investment advice, "
                "and not order execution") in text
        assert "LIVE_TRADING_ENABLED" in text


# --------------------------------------------------------------------------- #
# color helpers
# --------------------------------------------------------------------------- #
class TestColorHelpers:
    def test_signal_color_returns_hex_for_every_label(self, dashboard):
        from quantbot.research.sector_tracker import SIGNAL_LABELS
        for lbl in SIGNAL_LABELS:
            c = dashboard.signal_color(lbl)
            assert c.startswith("#") and len(c) == 7, f"bad colour for {lbl}: {c}"

    def test_status_color_for_every_status(self, dashboard):
        for s in ("BULL", "NEUTRAL", "NEAR_THRESHOLD", "BROKEN"):
            c = dashboard.status_color(s)
            assert c.startswith("#") and len(c) == 7

    def test_unknown_label_falls_back(self, dashboard):
        assert dashboard.signal_color("UNKNOWN").startswith("#")
        assert dashboard.status_color("WAT").startswith("#")
        assert dashboard.exit_color("BLAH").startswith("#")


# --------------------------------------------------------------------------- #
# filter / aggregation helpers
# --------------------------------------------------------------------------- #
class TestFilters:
    def test_filter_by_each_axis(self, dashboard):
        cats = [
            _make_cat(cid="A1", sector="AI", tier=1, status="BULL"),
            _make_cat(cid="A2", sector="AI", tier=2, status="NEUTRAL"),
            _make_cat(cid="S1", sector="SEMICONDUCTOR", tier=1, status="BROKEN"),
            _make_cat(cid="E1", sector="ENERGY", tier=2, status="BULL"),
        ]
        assert {c.catalyst_id for c in dashboard.filter_catalysts(cats, sectors={"AI"})} == {"A1", "A2"}
        assert {c.catalyst_id for c in dashboard.filter_catalysts(cats, tiers={1})} == {"A1", "S1"}
        assert {c.catalyst_id for c in dashboard.filter_catalysts(cats, statuses={"BULL"})} == {"A1", "E1"}
        assert {c.catalyst_id for c in dashboard.filter_catalysts(cats, source_types={"SEC_EDGAR"})} == {"A1", "A2", "S1", "E1"}
        assert dashboard.filter_catalysts(cats, sectors={"AI"}, statuses={"BULL"})[0].catalyst_id == "A1"

    def test_no_filters_returns_all(self, dashboard):
        cats = [_make_cat(cid="A", sector="AI", tier=1, status="BULL")]
        assert dashboard.filter_catalysts(cats) == cats

    def test_aggregate_status_counts(self, dashboard):
        cats = [
            _make_cat(cid=f"C{i}", sector="AI", tier=1, status="BULL")
            for i in range(3)
        ] + [_make_cat(cid="X", sector="AI", tier=1, status="BROKEN")]
        counts = dashboard.aggregate_status_counts(cats)
        assert counts == {"BULL": 3, "NEUTRAL": 0, "NEAR_THRESHOLD": 0, "BROKEN": 1}


# --------------------------------------------------------------------------- #
# top drivers / risks / manual gaps
# --------------------------------------------------------------------------- #
class TestTopDriversAndRisks:
    def test_top_bull_drivers_returns_bulls_in_tier_order(self, dashboard):
        cats = [
            _make_cat(cid="T2B", sector="AI", tier=2, status="BULL"),
            _make_cat(cid="T1B", sector="AI", tier=1, status="BULL"),
            _make_cat(cid="N", sector="AI", tier=1, status="NEUTRAL"),
        ]
        out = dashboard.top_bull_drivers(cats)
        assert [c.catalyst_id for c in out] == ["T1B", "T2B"]
        assert all(c.status == "BULL" for c in out)

    def test_top_risks_broken_before_near(self, dashboard):
        cats = [
            _make_cat(cid="N", sector="AI", tier=1, status="NEAR_THRESHOLD"),
            _make_cat(cid="B", sector="AI", tier=2, status="BROKEN"),
        ]
        out = dashboard.top_risks(cats)
        # BROKEN should come first even though Tier 2
        assert [c.catalyst_id for c in out] == ["B", "N"]

    def test_manual_gaps_includes_manual_and_stale(self, dashboard):
        cats = [
            _make_cat(cid="M", sector="AI", tier=1, status="NEUTRAL",
                      source="MANUAL", detail="no data"),
            _make_cat(cid="OK", sector="AI", tier=1, status="BULL",
                      source="SEC_EDGAR", detail="auto-derived"),
            _make_cat(cid="STALE", sector="AI", tier=1, status="NEUTRAL",
                      source="SEC_EDGAR", detail="stale: latest FYE 2012-..."),
        ]
        out = dashboard.manual_gaps(cats)
        ids = {c.catalyst_id for c in out}
        assert "M" in ids and "STALE" in ids
        assert "OK" not in ids

    def test_top_k_caps_results(self, dashboard):
        cats = [_make_cat(cid=f"C{i}", sector="AI", tier=1, status="BULL")
                for i in range(20)]
        assert len(dashboard.top_bull_drivers(cats, top_k=5)) == 5


# --------------------------------------------------------------------------- #
# load_sector — real artefacts + missing-file safety
# --------------------------------------------------------------------------- #
class TestLoadSector:
    def test_load_real_sectors_when_present(self, dashboard):
        data = dashboard.load_all_sectors()
        # SEMICONDUCTOR / AI / ENERGY all have artefacts in this repo state
        for sec in dashboard.SECTORS:
            sd = data[sec]
            if not sd.missing_files:
                assert sd.score is not None
                assert len(sd.catalysts) > 0
                # The dashboard recomputed score must match the loaded CSV
                from quantbot.research.sector_tracker import score_sector
                expected = score_sector(sd.catalysts, sd.exits, sector=sec)
                assert sd.score.signal == expected.signal

    def test_missing_files_handled_gracefully(self, dashboard, tmp_path):
        empty_data = tmp_path / "data"
        empty_rep = tmp_path / "reports"
        empty_data.mkdir(); empty_rep.mkdir()
        sd = dashboard.load_sector("SEMICONDUCTOR",
                                   data_dir=empty_data, report_dir=empty_rep)
        assert sd.catalysts == []
        assert sd.exits == []
        assert sd.score is None
        # Three artefacts are expected per sector; all should be reported missing
        assert len(sd.missing_files) == 3
        for path in sd.missing_files:
            assert "semiconductor" in path.lower() or "SEMICONDUCTOR" in path

    def test_unknown_sector_returns_safe_default(self, dashboard, tmp_path):
        sd = dashboard.load_sector("NOT_A_SECTOR",
                                    data_dir=tmp_path, report_dir=tmp_path)
        assert sd.catalysts == [] and sd.exits == []
        assert sd.score is None
        assert sd.missing_files

    def test_load_sector_does_not_write_anything(self, dashboard, tmp_path):
        """Read-only invariant — running load_sector must not create any files
        under the supplied directories."""
        empty_data = tmp_path / "data"
        empty_rep = tmp_path / "reports"
        empty_data.mkdir(); empty_rep.mkdir()
        dashboard.load_sector("SEMICONDUCTOR",
                              data_dir=empty_data, report_dir=empty_rep)
        # Nothing should have been written
        assert list(empty_data.iterdir()) == []
        assert list(empty_rep.iterdir()) == []


# --------------------------------------------------------------------------- #
# cross-sector links sanity
# --------------------------------------------------------------------------- #
class TestCrossSectorLinks:
    def test_links_non_empty_and_well_formed(self, dashboard):
        links = dashboard.cross_sector_links()
        assert len(links) >= 1
        for ln in links:
            for key in ("left_sector", "left_id", "right_sector",
                        "right_id", "note"):
                assert key in ln
            assert ln["left_sector"] in dashboard.SECTORS
            assert ln["right_sector"] in dashboard.SECTORS
            assert ln["left_sector"] != ln["right_sector"]


# --------------------------------------------------------------------------- #
# guardrails
# --------------------------------------------------------------------------- #
class TestGuardrails:
    def test_live_trading_remains_false(self):
        assert quantbot.LIVE_TRADING_ENABLED is False

    def test_dashboard_source_has_no_broker_or_order_tokens(self):
        src = (REPO_ROOT / "apps" /
               "sector_thesis_dashboard.py").read_text(encoding="utf-8")
        for forbidden in (
            "ib_insync", "ibapi", "ib_async",
            "from quantbot.backtest.broker",
            "from quantbot.backtest.engine",
            "place_order", "submit_order", "send_order", "fill_order",
            "ThetaDataLoader",
        ):
            assert forbidden not in src, (
                f"forbidden token {forbidden!r} in dashboard source"
            )

    def test_dashboard_source_has_no_file_write_operations(self):
        """Read-only guarantee: the dashboard must not write any files."""
        src = (REPO_ROOT / "apps" /
               "sector_thesis_dashboard.py").read_text(encoding="utf-8")
        # Open with writing modes / Path.write_* / shutil.copy / os.replace
        for forbidden in (
            '"w"', "'w'", '"a"', "'a'", '"x"', "'x'",
            ".write_text(", ".write_bytes(",
            "shutil.copy", "shutil.move", "os.replace", "os.rename",
        ):
            # Allow them only if they appear inside a docstring / comment;
            # rather than parsing, we check that none of these patterns appear
            # outside a controlled allowlist. Simple substring check is fine
            # for this read-only enforcement.
            assert forbidden not in src, (
                f"forbidden write token {forbidden!r} in dashboard source"
            )

    def test_dashboard_does_not_import_broker_modules(self, dashboard):
        # Inspect imported names on the loaded module
        mod_dict = vars(dashboard)
        for forbidden in ("place_order", "submit_order", "send_order",
                          "ThetaDataLoader"):
            assert forbidden not in mod_dict


# --------------------------------------------------------------------------- #
# end-to-end smoke: rendering helpers operate on real data without raising
# --------------------------------------------------------------------------- #
def test_helpers_on_real_data_do_not_raise(dashboard):
    data = dashboard.load_all_sectors()
    all_cats = []
    for sd in data.values():
        all_cats.extend(sd.catalysts)
    # No assertion on contents — just that these complete without error
    dashboard.top_bull_drivers(all_cats)
    dashboard.top_risks(all_cats)
    dashboard.manual_gaps(all_cats)
    dashboard.aggregate_status_counts(all_cats)
    dashboard.filter_catalysts(all_cats, sectors={"AI"})


# --------------------------------------------------------------------------- #
# V6.5.1 — Executive view + Company lens
# --------------------------------------------------------------------------- #
class TestExecutiveSummary:
    def test_returns_signal_interpretation_for_every_label(self, dashboard):
        """Every V6.1 signal label has a pre-declared interpretation."""
        from quantbot.research.sector_tracker import SIGNAL_LABELS
        for lbl in SIGNAL_LABELS:
            assert lbl in dashboard.SIGNAL_INTERPRETATION
            assert dashboard.SIGNAL_INTERPRETATION[lbl]  # non-empty

    def test_executive_summary_on_real_sector(self, dashboard):
        data = dashboard.load_all_sectors()
        for sec, sd in data.items():
            es = dashboard.make_executive_summary(sd)
            assert es.sector == sec
            if sd.score is None:
                # Friendly placeholder, not crash
                assert es.signal == "N/A"
                assert es.interpretation
                assert es.what_to_watch
                continue
            # Driver-recomputed score matches the executive summary signal
            assert es.signal == sd.score.signal
            assert es.normalized_score == pytest.approx(
                sd.score.normalized_score)
            # Top drivers / risks limited to <=2 entries
            assert len(es.top_bull_drivers) <= 2
            assert len(es.top_risks) <= 2
            # Interpretation must be the pre-declared text for the label
            assert es.interpretation == dashboard.SIGNAL_INTERPRETATION[
                es.signal]
            # "What to watch" should be a non-empty plain-English string
            assert isinstance(es.what_to_watch, str) and es.what_to_watch

    def test_what_to_watch_targets_broken_first(self, dashboard):
        """When the sector has any BROKEN catalyst, 'what to watch' must
        reference that catalyst (worst-bucket priority)."""
        cats = [
            _make_cat(cid="C1", sector="AI", tier=1, status="BULL"),
            _make_cat(cid="C2", sector="AI", tier=1, status="BROKEN"),
            _make_cat(cid="C3", sector="AI", tier=2, status="NEAR_THRESHOLD"),
        ]
        from quantbot.research.sector_tracker import score_sector
        score = score_sector(cats, [], sector="AI")
        sd = dashboard.SectorData(sector="AI", catalysts=cats, exits=[],
                                   score=score)
        es = dashboard.make_executive_summary(sd)
        assert "C2" in es.what_to_watch
        assert "BROKEN" in es.what_to_watch.upper()

    def test_what_to_watch_clean_sector(self, dashboard):
        """No BROKEN, no NEAR_THRESHOLD → friendly all-clear message."""
        cats = [_make_cat(cid=f"C{i}", sector="AI", tier=1, status="BULL")
                for i in range(3)]
        from quantbot.research.sector_tracker import score_sector
        score = score_sector(cats, [], sector="AI")
        sd = dashboard.SectorData(sector="AI", catalysts=cats, exits=[],
                                   score=score)
        es = dashboard.make_executive_summary(sd)
        assert "near-threshold" in es.what_to_watch.lower() \
            or "monthly" in es.what_to_watch.lower()


# --------------------------------------------------------------------------- #
# derive_company_read pure logic
# --------------------------------------------------------------------------- #
class TestDeriveCompanyRead:
    def _by_id(self, *catalysts) -> dict:
        return {c.catalyst_id: c for c in catalysts}

    def test_no_linked_catalysts_loaded_returns_na(self, dashboard):
        read, reason, n = dashboard.derive_company_read({}, ["X1", "X2"])
        assert read == "N/A" and n == 0
        assert "no linked catalysts" in reason

    def test_all_manual_neutral_is_tracked(self, dashboard):
        cats = self._by_id(
            _make_cat(cid="M1", sector="AI", tier=1, status="NEUTRAL",
                       source="MANUAL"),
        )
        read, reason, n = dashboard.derive_company_read(cats, ["M1"])
        assert read == "TRACKED" and n == 1
        assert "manual placeholder" in reason.lower() \
            or "no direct signal" in reason.lower()

    def test_bull_plus_broken_is_mixed_v652(self, dashboard):
        """V6.5.2 rule: when BULL coexists with BROKEN the read is MIXED, not
        BROKEN. The composed reason MUST surface both sides so bullish
        evidence is never hidden."""
        cats = self._by_id(
            _make_cat(cid="B", sector="AI", tier=1, status="BULL"),
            _make_cat(cid="X", sector="AI", tier=1, status="BROKEN"),
            _make_cat(cid="N", sector="AI", tier=1, status="NEAR_THRESHOLD"),
        )
        read, reason, _ = dashboard.derive_company_read(cats, ["B", "X", "N"])
        assert read == "MIXED"
        # Both BULL and BROKEN must be visible in the reason text.
        assert "BULL" in reason
        assert "BROKEN" in reason

    def test_broken_only_no_counterweight_is_broken(self, dashboard):
        """Without any BULL counterweight, the worst-bucket headline still
        applies — BROKEN reads BROKEN."""
        cats = self._by_id(
            _make_cat(cid="X", sector="AI", tier=1, status="BROKEN"),
            _make_cat(cid="N", sector="AI", tier=1, status="NEAR_THRESHOLD"),
        )
        read, _, _ = dashboard.derive_company_read(cats, ["X", "N"])
        assert read == "BROKEN"

    def test_bull_plus_near_threshold_is_mixed_v652(self, dashboard):
        """V6.5.2 also escalates BULL+NEAR_THRESHOLD → MIXED (was
        NEAR_THRESHOLD-only under V6.5.1)."""
        cats = self._by_id(
            _make_cat(cid="B", sector="AI", tier=1, status="BULL"),
            _make_cat(cid="N", sector="AI", tier=1, status="NEAR_THRESHOLD"),
        )
        read, reason, _ = dashboard.derive_company_read(cats, ["B", "N"])
        assert read == "MIXED"
        assert "BULL" in reason and "NEAR_THRESHOLD" in reason

    def test_near_threshold_only_no_bull_is_near(self, dashboard):
        """Without BULL counterweight, NEAR_THRESHOLD stands."""
        cats = self._by_id(
            _make_cat(cid="N", sector="AI", tier=1, status="NEAR_THRESHOLD"),
            _make_cat(cid="U", sector="AI", tier=1, status="NEUTRAL"),
        )
        read, _, _ = dashboard.derive_company_read(cats, ["N", "U"])
        assert read == "NEAR_THRESHOLD"

    def test_all_bull_returns_bull(self, dashboard):
        cats = self._by_id(
            _make_cat(cid="B1", sector="AI", tier=1, status="BULL"),
            _make_cat(cid="B2", sector="AI", tier=1, status="BULL"),
        )
        read, _, _ = dashboard.derive_company_read(cats, ["B1", "B2"])
        assert read == "BULL"

    def test_all_neutral_returns_neutral(self, dashboard):
        cats = self._by_id(
            _make_cat(cid="N1", sector="AI", tier=1, status="NEUTRAL"),
            _make_cat(cid="N2", sector="AI", tier=1, status="NEUTRAL"),
        )
        read, _, _ = dashboard.derive_company_read(cats, ["N1", "N2"])
        assert read == "NEUTRAL"

    def test_bull_plus_neutral_no_negatives_is_mixed(self, dashboard):
        cats = self._by_id(
            _make_cat(cid="B", sector="AI", tier=1, status="BULL"),
            _make_cat(cid="N", sector="AI", tier=1, status="NEUTRAL"),
        )
        read, _, _ = dashboard.derive_company_read(cats, ["B", "N"])
        assert read == "MIXED"

    def test_partial_load_counts_present_only(self, dashboard):
        """When some linked IDs are missing from the loaded data, the
        helper reports the correct ``n_present`` and uses only the loaded ones."""
        cats = self._by_id(
            _make_cat(cid="P", sector="AI", tier=1, status="BULL"),
        )
        read, _, n = dashboard.derive_company_read(cats, ["P", "MISSING"])
        assert read == "BULL"
        assert n == 1


# --------------------------------------------------------------------------- #
# build_company_lens — uses existing catalyst data only, no invention
# --------------------------------------------------------------------------- #
class TestCompanyLens:
    def test_company_catalyst_map_covers_every_sector(self, dashboard):
        assert set(dashboard.COMPANY_CATALYSTS) == set(dashboard.SECTORS)

    def test_user_specified_mapping_present(self, dashboard):
        """Spot-check the user's V6.5.1 mapping."""
        m = dashboard.COMPANY_CATALYSTS
        # SEMI
        semi = {c["ticker"]: c for c in m["SEMICONDUCTOR"]}
        assert "NVDA" in semi
        assert "SEMI-NVDA-REV-T1" in semi["NVDA"]["catalysts"]
        assert "SEMI-NVDA-DC-REV-T1" in semi["NVDA"]["catalysts"]
        assert "SEMI-INVENTORY-CYCLE-T2" in semi["NVDA"]["catalysts"]
        for eq in ("AMAT", "LRCX", "KLAC"):
            assert "SEMI-EQUIPMENT-DEMAND-T2" in semi[eq]["catalysts"]
        # AI
        ai = {c["ticker"]: c for c in m["AI"]}
        for hs in ("MSFT", "GOOGL", "AMZN", "META"):
            assert "AI-HYPERSCALER-CAPEX-T1" in ai[hs]["catalysts"]
        assert "OpenAI" in ai and "Anthropic" in ai
        # Energy
        en = {c["ticker"]: c for c in m["ENERGY"]}
        for oil in ("XOM", "CVX", "COP"):
            assert "ENER-OILGAS-OCF-T2" in en[oil]["catalysts"]

    def test_lens_on_real_data_covers_every_mapped_company(self, dashboard):
        data = dashboard.load_all_sectors()
        rows = dashboard.build_company_lens(data)
        # Every (sector, ticker) in the mapping appears in the lens
        in_universe = set(dashboard.company_lens_companies_in_universe())
        produced = {(r.sector, r.ticker) for r in rows}
        assert in_universe == produced, (
            f"missing rows: {in_universe - produced}; "
            f"extra rows: {produced - in_universe}"
        )

    def test_lens_filters_by_sector(self, dashboard):
        data = dashboard.load_all_sectors()
        rows = dashboard.build_company_lens(data, sectors={"AI"})
        assert all(r.sector == "AI" for r in rows)
        ai_tickers = {c["ticker"] for c in dashboard.COMPANY_CATALYSTS["AI"]}
        assert {r.ticker for r in rows} == ai_tickers

    def test_lens_uses_only_existing_catalyst_data(self, dashboard):
        """Each row's ``current_read`` must be derivable purely from the
        loaded catalysts' statuses — no synthesised score. We verify by
        recomputing the read via ``derive_company_read`` from the same loaded
        data and confirming agreement."""
        data = dashboard.load_all_sectors()
        rows = dashboard.build_company_lens(data)
        for r in rows:
            sd = data[r.sector]
            by_id = {c.catalyst_id: c for c in sd.catalysts}
            expected_read, _, expected_n = dashboard.derive_company_read(
                by_id, r.linked_catalyst_ids
            )
            assert r.current_read == expected_read, (
                f"{r.ticker} disagrees: row says {r.current_read} but "
                f"derive_company_read says {expected_read}"
            )
            assert r.n_linked_present == expected_n

    def test_lens_handles_missing_catalyst_ids_gracefully(self, dashboard,
                                                          monkeypatch):
        """If an ID in the mapping isn't present in the loaded data, the
        company still appears in the lens but with the count of present links
        reflecting that fact — never crashes."""
        data = dashboard.load_all_sectors()
        # Inject a synthetic company with a deliberately missing catalyst ID.
        fake_map = dict(dashboard.COMPANY_CATALYSTS)
        fake_map["AI"] = list(fake_map["AI"]) + [
            {"ticker": "FAKECO", "subsector_theme": "test",
             "catalysts": ["AI-DOES-NOT-EXIST-T9"]}
        ]
        monkeypatch.setattr(dashboard, "COMPANY_CATALYSTS", fake_map)
        rows = dashboard.build_company_lens(data, sectors={"AI"})
        fake_row = next(r for r in rows if r.ticker == "FAKECO")
        assert fake_row.current_read == "N/A"
        assert fake_row.n_linked_present == 0

    def test_company_lens_row_does_not_carry_a_score(self, dashboard):
        """A CompanyLensRow exposes a categorical read + textual reason —
        NEVER a numeric score. (Guards against accidental V6.7-style
        company-level scoring leaking in here.)"""
        data = dashboard.load_all_sectors()
        rows = dashboard.build_company_lens(data)
        for r in rows:
            # No numeric score field exists on the row
            row_dict = r.__dict__
            assert "normalized_score" not in row_dict
            assert "raw_score" not in row_dict
            assert "score" not in row_dict
            # current_read is the categorical label, not a number
            assert r.current_read in dashboard.READ_ORDER


# --------------------------------------------------------------------------- #
# V6.5.1 — guardrails update
# --------------------------------------------------------------------------- #
class TestV651Guardrails:
    def test_dashboard_still_has_no_broker_or_order_tokens(self):
        src = (REPO_ROOT / "apps" /
               "sector_thesis_dashboard.py").read_text(encoding="utf-8")
        for forbidden in (
            "ib_insync", "ibapi", "ib_async",
            "from quantbot.backtest.broker",
            "from quantbot.backtest.engine",
            "place_order", "submit_order", "send_order", "fill_order",
            "ThetaDataLoader",
        ):
            assert forbidden not in src

    def test_dashboard_v651_additions_have_no_writes_or_fetches(self):
        """V6.5.1 must remain read-only — no file writes, no network calls."""
        src = (REPO_ROOT / "apps" /
               "sector_thesis_dashboard.py").read_text(encoding="utf-8")
        for forbidden in (
            ".write_text(", ".write_bytes(",
            "shutil.copy", "shutil.move", "os.replace", "os.rename",
            "urlopen(", "requests.get(",
            "append_changes(", "ensure_change_log_header(",
            "ensure_event_annotations_header(",
        ):
            assert forbidden not in src

    def test_live_trading_flag_unchanged(self):
        assert quantbot.LIVE_TRADING_ENABLED is False


# --------------------------------------------------------------------------- #
# V6.5.2 — visible-vs-detail field separation, watch list, mixed wording
# --------------------------------------------------------------------------- #
class TestV652VisibleVsDetailFields:
    """The simplified V6.5.2 catalyst card body must not expose long
    threshold strings or operator-only fields. Tests use the pure helpers
    that shape the visible-body dict and the detail-expander dict so this is
    independent of streamlit rendering."""

    def test_visible_fields_exclude_threshold_and_action(self, dashboard):
        c = _make_cat(cid="X", sector="AI", tier=1, status="BULL")
        visible = dashboard.catalyst_card_visible_fields(c)
        # Keys explicitly omitted from the V6.5.2 visible body:
        for hidden in ("threshold", "source_detail", "action_if_broken",
                       "notes", "last_updated"):
            assert hidden not in visible, (
                f"V6.5.2 visible card must not expose {hidden!r} — "
                f"that belongs in the Details expander"
            )
        # Keys that DO stay visible:
        for shown in ("catalyst_id", "catalyst_name", "subsector", "tier",
                      "status", "source_type", "current_value"):
            assert shown in visible

    def test_detail_fields_include_threshold(self, dashboard):
        c = _make_cat(cid="X", sector="AI", tier=1, status="BULL")
        det = dashboard.catalyst_card_detail_fields(c)
        for shown in ("threshold", "source_detail", "action_if_broken",
                      "notes", "last_updated"):
            assert shown in det
        # The Details expander never duplicates the visible-body keys
        for not_here in ("catalyst_id", "catalyst_name", "status",
                          "current_value"):
            assert not_here not in det

    def test_company_visible_row_hides_catalyst_ids(self, dashboard):
        """The V6.5.2 simple company view's visible row deliberately
        omits the linked catalyst ID list — that detail moves to the per-row
        expander surfaced by :func:`company_row_detail_columns`."""
        data = dashboard.load_all_sectors()
        rows = dashboard.build_company_lens(data)
        nvda = next(r for r in rows
                    if r.ticker == "NVDA" and r.sector == "SEMICONDUCTOR")
        visible = dashboard.company_row_visible_columns(nvda)
        labels = [k for k, _ in visible]
        assert labels == ["Ticker", "Sector", "Theme", "Read",
                          "Why it matters", "Main risk / note"]
        # No catalyst-ID-shaped string should leak into any visible cell.
        joined_visible = " ".join(v for _, v in visible)
        for cid in nvda.linked_catalyst_ids:
            assert cid not in joined_visible, (
                f"visible row leaked catalyst ID {cid}"
            )

    def test_company_detail_row_includes_catalyst_ids(self, dashboard):
        data = dashboard.load_all_sectors()
        rows = dashboard.build_company_lens(data)
        nvda = next(r for r in rows
                    if r.ticker == "NVDA" and r.sector == "SEMICONDUCTOR")
        det = dashboard.company_row_detail_columns(nvda)
        det_text = " ".join(v for _, v in det)
        for cid in nvda.linked_catalyst_ids:
            assert cid in det_text


class TestV652MixedWording:
    """When a company has both BULL and BROKEN linked catalysts, the lens
    row's read is MIXED (not BROKEN) AND the visible 'Why it matters' /
    'Main risk' columns surface both sides briefly. See the V6.5.2 spec
    example: "Revenue strong, but inventory-cycle risk is BROKEN"."""

    def test_company_view_strings_surface_both_sides(self, dashboard):
        bull = _make_cat(cid="SEMI-NVDA-REV-T1", sector="SEMICONDUCTOR",
                         tier=1, status="BULL")
        broken = _make_cat(cid="SEMI-INVENTORY-CYCLE-T2",
                           sector="SEMICONDUCTOR", tier=2, status="BROKEN")
        why, risk = dashboard.company_view_strings([bull, broken])
        # The bullish side appears in `why`
        assert "Revenue" in why or "v" in why  # current_value placeholder is "v"
        # The risk side appears in `main_risk_short` with the BROKEN label
        assert "BROKEN" in risk
        assert "Inventory cycle" in risk

    def test_real_data_nvda_reads_mixed_not_broken(self, dashboard):
        """Regression: under V6.5.1 NVDA read BROKEN (the shared inventory
        catalyst dominated). Under V6.5.2 the same company reads MIXED, with
        both Revenue +65.5% and the inventory BROKEN call visible."""
        data = dashboard.load_all_sectors()
        rows = dashboard.build_company_lens(data)
        nvda = next(r for r in rows
                    if r.ticker == "NVDA" and r.sector == "SEMICONDUCTOR")
        assert nvda.current_read == "MIXED"
        # Why: the BULL revenue side
        assert "Revenue" in nvda.why_short or "+" in nvda.why_short
        # Main risk: the BROKEN inventory side
        assert "BROKEN" in nvda.main_risk_short
        assert ("Inventory" in nvda.main_risk_short
                or "inventory" in nvda.main_risk_short.lower())


class TestThingsWorthWatching:
    """The curated list is derived strictly from existing catalyst data —
    no invented numbers."""

    def test_returns_watchitem_dataclass(self, dashboard):
        data = dashboard.load_all_sectors()
        out = dashboard.things_worth_watching(data)
        assert all(isinstance(w, dashboard.WatchItem) for w in out)
        # Every item carries a sector + level + non-empty text.
        for w in out:
            assert w.sector in (set(dashboard.SECTORS) | {"CROSS"})
            assert w.level in {"broken", "near", "bull", "linkage"}
            assert w.text

    def test_broken_items_appear_before_bulls(self, dashboard):
        data = dashboard.load_all_sectors()
        items = dashboard.things_worth_watching(data)
        # Within the same sector, BROKEN comes before BULL.
        for sec in dashboard.SECTORS:
            sec_items = [w for w in items if w.sector == sec]
            levels = [w.level for w in sec_items]
            broken_idx = [i for i, l in enumerate(levels) if l == "broken"]
            bull_idx = [i for i, l in enumerate(levels) if l == "bull"]
            if broken_idx and bull_idx:
                assert max(broken_idx) < min(bull_idx)

    def test_text_only_uses_existing_catalyst_current_value(self, dashboard):
        """Every emitted text must be composable from existing catalyst
        names + current_values. We verify by checking each item's text
        contains a substring of either catalyst_name or current_value from
        the loaded sectors."""
        data = dashboard.load_all_sectors()
        out = dashboard.things_worth_watching(data)
        all_catalysts: list = []
        for sd in data.values():
            all_catalysts.extend(sd.catalysts)
        names = {c.catalyst_name for c in all_catalysts}
        values = {(c.current_value or "").strip() for c in all_catalysts
                  if c.current_value}
        for w in out:
            if w.level == "linkage":
                continue  # cross-sector linkage is composed prose
            # Each per-sector item must reference an actual catalyst name OR
            # an actual current_value (no invention).
            ok = any(name and name in w.text for name in names) \
                or any(val and val in w.text for val in values)
            assert ok, f"could not match watch item to any loaded data: {w.text}"

    def test_cross_sector_linkage_appears_when_conditions_met(self, dashboard):
        """When SEMI inventory cycle is BROKEN AND AI hyperscaler capex is
        BULL (the current real state), the cross-sector linkage item must
        appear."""
        data = dashboard.load_all_sectors()
        items = dashboard.things_worth_watching(data)
        sec_data_semi = data.get("SEMICONDUCTOR")
        sec_data_ai = data.get("AI")
        if not sec_data_semi or not sec_data_ai:
            pytest.skip("artefacts missing — can't test linkage")
        # Check the precondition (real data should match this today)
        semi_broken = any(c.catalyst_id == "SEMI-INVENTORY-CYCLE-T2"
                          and c.status == "BROKEN"
                          for c in sec_data_semi.catalysts)
        ai_bull = any(c.catalyst_id == "AI-HYPERSCALER-CAPEX-T1"
                      and c.status == "BULL"
                      for c in sec_data_ai.catalysts)
        if not (semi_broken and ai_bull):
            pytest.skip("precondition for linkage not met in current data")
        # The linkage item must be present
        linkage_items = [w for w in items if w.level == "linkage"]
        assert linkage_items
        # The linkage text must mention BOTH catalysts' current values
        # (no invention).
        capex_val = next(c.current_value for c in sec_data_ai.catalysts
                         if c.catalyst_id == "AI-HYPERSCALER-CAPEX-T1")
        inv_val = next(c.current_value for c in sec_data_semi.catalysts
                       if c.catalyst_id == "SEMI-INVENTORY-CYCLE-T2")
        text = linkage_items[0].text
        assert capex_val in text
        assert inv_val in text

    def test_sector_filter(self, dashboard):
        data = dashboard.load_all_sectors()
        only_ai = dashboard.things_worth_watching(data, sectors={"AI"})
        # All emitted sectors must be AI (no CROSS linkage since we filtered)
        assert all(w.sector == "AI" for w in only_ai)


# --------------------------------------------------------------------------- #
# V6.5.3 — Exit-watch summary helpers
# --------------------------------------------------------------------------- #
def _make_exit(*, eid: str, sector: str, status: str,
               scenario: str = "scenario",
               trigger: str = "trigger condition",
               action: str = "research-only: review sleeve",
               source: str = "manual",
               last_updated: str = "2026-05-29") -> EmergencyExit:
    return EmergencyExit(
        exit_id=eid, sector=sector, scenario=scenario,
        trigger_condition=trigger, current_status=status,
        action=action, source=source, last_updated=last_updated,
    )


def _sd(sector: str, *, exits: list[EmergencyExit] | None = None,
        catalysts: list[Catalyst] | None = None):
    """Build a SectorData stub for helper tests (no on-disk artefacts)."""
    from quantbot.research.sector_tracker import score_sector
    cats = catalysts or []
    exits = exits or []
    score = (score_sector(cats, exits, sector=sector)
             if cats or exits else None)
    # Use the dashboard module's SectorData (imported at top of file)
    return None  # placeholder; real value created inside each test via dashboard


class TestExitWatchSummary:
    """Pure helper tests for the V6.5.3 exit-watch summary."""

    def _sectors_with(self, dashboard, exits_by_sec: dict[str, list]):
        return {
            sec: dashboard.SectorData(
                sector=sec, catalysts=[], exits=ex,
            )
            for sec, ex in exits_by_sec.items()
        }

    def test_empty_scope_returns_friendly_message(self, dashboard):
        sectors_data = self._sectors_with(dashboard, {
            "SEMICONDUCTOR": [], "AI": [], "ENERGY": [],
        })
        s = dashboard.make_exit_watch_summary(sectors_data)
        assert s.n_total == 0
        assert s.n_triggered == 0
        assert "No emergency exits" in s.interpretation
        assert s.top_exits == []

    def test_all_monitoring_gives_continue_monitoring_message(self, dashboard):
        sectors_data = self._sectors_with(dashboard, {
            "AI": [_make_exit(eid="AI-EXIT-X", sector="AI",
                              status="MONITORING")],
            "SEMICONDUCTOR": [], "ENERGY": [],
        })
        s = dashboard.make_exit_watch_summary(sectors_data)
        assert s.n_triggered == 0 and s.n_monitoring == 1
        assert "No exits triggered" in s.interpretation
        assert "Continue monitoring" in s.interpretation

    def test_triggered_exits_yield_immediate_review_message(self, dashboard):
        sectors_data = self._sectors_with(dashboard, {
            "AI": [
                _make_exit(eid="AI-EXIT-T1", sector="AI", status="TRIGGERED"),
                _make_exit(eid="AI-EXIT-M1", sector="AI",
                           status="MONITORING"),
            ],
            "SEMICONDUCTOR": [], "ENERGY": [],
        })
        s = dashboard.make_exit_watch_summary(sectors_data)
        assert s.n_triggered == 1
        assert "1 exit triggered" in s.interpretation
        assert "Review sector exposure immediately" in s.interpretation

    def test_multiple_triggered_uses_plural(self, dashboard):
        sectors_data = self._sectors_with(dashboard, {
            "AI": [
                _make_exit(eid="AI-EXIT-T1", sector="AI", status="TRIGGERED"),
                _make_exit(eid="AI-EXIT-T2", sector="AI", status="TRIGGERED"),
            ],
            "SEMICONDUCTOR": [], "ENERGY": [],
        })
        s = dashboard.make_exit_watch_summary(sectors_data)
        assert s.n_triggered == 2
        assert "2 exits triggered" in s.interpretation

    def test_triggered_exits_sort_before_monitoring(self, dashboard):
        """Worst-bucket ordering: TRIGGERED first, then MONITORING, then
        INACTIVE; ties broken by exit_id alphabetically."""
        sectors_data = self._sectors_with(dashboard, {
            "AI": [
                _make_exit(eid="AI-EXIT-A-MON", sector="AI",
                           status="MONITORING"),
                _make_exit(eid="AI-EXIT-Z-TRIG", sector="AI",
                           status="TRIGGERED"),
                _make_exit(eid="AI-EXIT-B-INACT", sector="AI",
                           status="INACTIVE"),
            ],
            "SEMICONDUCTOR": [], "ENERGY": [],
        })
        s = dashboard.make_exit_watch_summary(sectors_data, top_k=5)
        statuses = [e.current_status for e in s.top_exits]
        assert statuses == ["TRIGGERED", "MONITORING", "INACTIVE"]
        # Even Z-prefixed TRIGGERED comes before A-prefixed MONITORING.
        assert s.top_exits[0].exit_id == "AI-EXIT-Z-TRIG"

    def test_per_sector_counts_correct_for_all_scope(self, dashboard):
        sectors_data = self._sectors_with(dashboard, {
            "SEMICONDUCTOR": [
                _make_exit(eid="SEMI-EXIT-A", sector="SEMICONDUCTOR",
                           status="MONITORING"),
                _make_exit(eid="SEMI-EXIT-B", sector="SEMICONDUCTOR",
                           status="MONITORING"),
            ],
            "AI": [
                _make_exit(eid="AI-EXIT-T", sector="AI", status="TRIGGERED"),
            ],
            "ENERGY": [],
        })
        s = dashboard.make_exit_watch_summary(sectors_data)
        assert s.scope == "ALL"
        assert s.per_sector_triggered == {
            "SEMICONDUCTOR": 0, "AI": 1, "ENERGY": 0,
        }
        assert s.per_sector_monitoring == {
            "SEMICONDUCTOR": 2, "AI": 0, "ENERGY": 0,
        }

    def test_per_sector_scope_filters_correctly(self, dashboard):
        sectors_data = self._sectors_with(dashboard, {
            "SEMICONDUCTOR": [
                _make_exit(eid="SEMI-EXIT-A", sector="SEMICONDUCTOR",
                           status="MONITORING"),
            ],
            "AI": [
                _make_exit(eid="AI-EXIT-T", sector="AI", status="TRIGGERED"),
            ],
            "ENERGY": [],
        })
        # Querying SEMICONDUCTOR ignores the AI TRIGGERED entirely.
        s = dashboard.make_exit_watch_summary(
            sectors_data, sector="SEMICONDUCTOR"
        )
        assert s.scope == "SEMICONDUCTOR"
        assert s.n_triggered == 0 and s.n_monitoring == 1
        # The per-sector breakdown dict is only populated for the ALL scope.
        assert s.per_sector_triggered == {}
        assert s.per_sector_monitoring == {}

    def test_top_k_cap(self, dashboard):
        sectors_data = self._sectors_with(dashboard, {
            "AI": [
                _make_exit(eid=f"AI-EXIT-{i}", sector="AI",
                           status="MONITORING")
                for i in range(10)
            ],
            "SEMICONDUCTOR": [], "ENERGY": [],
        })
        s = dashboard.make_exit_watch_summary(sectors_data, top_k=3)
        assert len(s.top_exits) == 3

    def test_real_data_smoke(self, dashboard):
        """Against the real V6.4 emergency_exits CSVs (6 + 6 + 10 = 22, all
        MONITORING under today's state), the summary must report 0 triggered
        and produce a stable Continue-monitoring interpretation."""
        data = dashboard.load_all_sectors()
        s = dashboard.make_exit_watch_summary(data)
        assert s.scope == "ALL"
        assert s.n_total == 22
        assert s.n_triggered == 0
        assert s.n_monitoring == 22
        assert "Continue monitoring" in s.interpretation


class TestExitShortHelpers:
    def test_short_trigger_truncates_long_text(self, dashboard):
        e = _make_exit(eid="X", sector="AI", status="MONITORING",
                       trigger="A" * 200)
        out = dashboard.exit_short_trigger(e, max_chars=50)
        assert len(out) <= 51
        assert out.endswith("…")

    def test_short_trigger_uses_first_or_clause(self, dashboard):
        e = _make_exit(eid="X", sector="AI", status="MONITORING",
                       trigger=("First clause is short OR Second clause is "
                                "much longer and would otherwise be truncated"))
        out = dashboard.exit_short_trigger(e, max_chars=40)
        # The first clause appears in the surfaced phrase
        assert "First clause is short" in out

    def test_short_action_takes_first_semicolon_clause(self, dashboard):
        e = _make_exit(eid="X", sector="AI", status="MONITORING",
                       action=("research-only: re-evaluate sector sleeve; "
                               "consider defined-risk hedges; NO order"))
        out = dashboard.exit_short_action(e, max_chars=80)
        # The first clause is below 80 chars, so we get it directly.
        assert out.startswith("research-only:")
        # The trailing clauses about hedges / NO order are NOT in the short.
        assert "consider defined-risk hedges" not in out
        assert "NO order" not in out

    def test_empty_fields_return_em_dash(self, dashboard):
        e = _make_exit(eid="X", sector="AI", status="MONITORING",
                       trigger="", action="")
        assert dashboard.exit_short_trigger(e) == "—"
        assert dashboard.exit_short_action(e) == "—"


class TestExitVisibleVsDetailFields:
    """V6.5.3 — the compact exit row must not expose the long
    trigger_condition / action / source / last_updated in the visible body."""

    def test_visible_fields_exclude_full_text(self, dashboard):
        e = _make_exit(eid="X", sector="AI", status="MONITORING",
                       trigger="A" * 200, action="B" * 200,
                       source="src", last_updated="2026-05-29")
        vis = dashboard.exit_summary_visible_fields(e)
        for hidden in ("trigger_condition", "action",
                       "source", "last_updated"):
            assert hidden not in vis, (
                f"V6.5.3 visible exit row must not expose {hidden!r}"
            )
        for shown in ("exit_id", "scenario", "current_status",
                      "short_trigger", "short_action"):
            assert shown in vis
        # Short fields must actually be shorter than the originals.
        assert len(vis["short_trigger"]) < 200
        assert len(vis["short_action"]) < 200

    def test_detail_fields_include_full_text(self, dashboard):
        e = _make_exit(eid="X", sector="AI", status="MONITORING",
                       trigger="A" * 200, action="B" * 200)
        det = dashboard.exit_summary_detail_fields(e)
        # Detail row carries the full strings unmodified.
        assert det["trigger_condition"] == "A" * 200
        assert det["action"] == "B" * 200
        # And explicitly NOT the visible-body keys.
        for not_here in ("scenario", "current_status",
                         "short_trigger", "short_action"):
            assert not_here not in det


class TestV653LayoutSourceConventions:
    """Loose-couple tests on the dashboard source verifying the V6.5.3
    layout choices: compact exit-watch summary is visible (not inside an
    expander) AND the full per-exit emergency expander still exists."""

    def test_compact_exit_watch_section_visible_in_all_tab(self):
        src = (REPO_ROOT / "apps" /
               "sector_thesis_dashboard.py").read_text(encoding="utf-8")
        # The All tab header text appears before the technical expanders block
        assert 'st.subheader("Exit watch / safety valves")' in src
        # The compact summary renderer is invoked in the All tab body
        assert "_render_exit_watch_summary(" in src

    def test_per_sector_exit_watch_section_present(self):
        src = (REPO_ROOT / "apps" /
               "sector_thesis_dashboard.py").read_text(encoding="utf-8")
        assert 'st.subheader("Exit watch — this sector")' in src

    def test_full_emergency_exits_expander_still_present(self):
        """The original collapsed Emergency-exits expander in
        ``_render_sector_tab`` must remain — V6.5.3 ADDS the compact summary,
        it does not remove the existing full detail surface."""
        src = (REPO_ROOT / "apps" /
               "sector_thesis_dashboard.py").read_text(encoding="utf-8")
        assert "with st.expander(exit_label" in src
        assert '"Emergency exits (' in src

    def test_no_broker_or_order_tokens(self):
        src = (REPO_ROOT / "apps" /
               "sector_thesis_dashboard.py").read_text(encoding="utf-8")
        for forbidden in (
            "ib_insync", "ibapi", "ib_async",
            "from quantbot.backtest.broker",
            "place_order", "submit_order", "send_order", "fill_order",
        ):
            assert forbidden not in src

    def test_live_trading_flag_unchanged(self):
        assert quantbot.LIVE_TRADING_ENABLED is False


class TestV652LayoutSourceConventions:
    """Loose-couple tests on the dashboard source verifying the V6.5.2
    layout choices: technical sections sit behind expanders rather than
    being rendered inline at top-level."""

    def test_technical_sections_use_collapsed_expanders(self):
        src = (REPO_ROOT / "apps" /
               "sector_thesis_dashboard.py").read_text(encoding="utf-8")
        # Catalyst details / emergency exits / recent changes / raw report /
        # cross-sector breakdown / cross-sector scenario links all live under
        # st.expander(...) in the V6.5.2 layout.
        for fragment in (
            'st.expander("Cross-sector detailed breakdown',
            'st.expander("Cross-sector scenario links"',
            'st.expander(f"Catalyst details',
            'st.expander(exit_label',
            'st.expander(f"View raw',
            'st.expander(f"Recent changes',
            'st.expander(',
        ):
            assert fragment in src, f"missing expander pattern: {fragment!r}"

    def test_top_summary_cards_row_removed(self):
        """The V6.5.1 prominent 4-card 'Sector signal + raw score' row is
        no longer rendered (the new layout leads with the Executive view)."""
        src = (REPO_ROOT / "apps" /
               "sector_thesis_dashboard.py").read_text(encoding="utf-8")
        # The prior row built columns via `cols = st.columns(len(SECTORS) + 1)`
        # and emitted "All catalysts" totals — those text fragments must be gone.
        assert "<h3>All catalysts</h3>" not in src
        # And the prior compact "norm X · raw Y / w Z" header card must be
        # gone from the top of render() (the same data still appears, smaller,
        # inside the Executive cards).
        assert "raw {sd.score.raw_score" not in src
