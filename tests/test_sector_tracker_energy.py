"""Tests for the V6.4 Energy / power-infrastructure sector tracker.

Mirrors the V6.3 AI driver tests and adds checks for the AI_POWER_INFRA vs
TRADITIONAL_ENERGY subsector split (the user-required deliverable).
"""

from __future__ import annotations

import hashlib
import importlib
import sys
from pathlib import Path

import pytest

import quantbot
from quantbot.research.sector_tracker import (
    SIGNAL_LABELS,
    load_catalysts,
    load_exits,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def driver():
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        mod = importlib.import_module("run_sector_tracker_energy")
    finally:
        if str(REPO_ROOT / "scripts") in sys.path:
            sys.path.remove(str(REPO_ROOT / "scripts"))
    return mod


@pytest.fixture
def run_output(tmp_path, driver):
    data_dir = tmp_path / "data"
    rep_dir = tmp_path / "reports"
    summary = driver.main(data_dir=data_dir, report_dir=rep_dir)
    return {
        "summary": summary,
        "cat_path": data_dir / "energy_thesis_tracker.csv",
        "exit_path": data_dir / "energy_emergency_exits.csv",
        "rpt_path": rep_dir / "energy_signal.md",
    }


def _cached(ticker: str) -> bool:
    from quantbot.company.sec_edgar import ticker_to_cik, company_cache_dir
    cik = ticker_to_cik(ticker)
    if not cik:
        return False
    return (company_cache_dir() / "companyfacts" / f"CIK{cik}.json").is_file()


# --------------------------------------------------------------------------- #
# artefacts + framework compatibility
# --------------------------------------------------------------------------- #
class TestDriverOutputs:
    def test_three_artifacts_written(self, run_output):
        for k in ("cat_path", "exit_path", "rpt_path"):
            assert run_output[k].is_file(), f"missing artefact: {k}"

    def test_catalyst_csv_loadable_via_v61_framework(self, run_output):
        cats = load_catalysts(run_output["cat_path"])
        assert len(cats) >= 15, "expected >=15 catalysts for the Energy sector"
        assert all(c.sector == "ENERGY" for c in cats)
        ids = {c.catalyst_id for c in cats}
        for cid in (
            # AI_POWER_INFRA per-name revenue
            "ENER-GEV-REV-T1", "ENER-ETN-REV-T1", "ENER-VRT-REV-T1",
            "ENER-PWR-REV-T1", "ENER-CEG-REV-T1",
            "ENER-NEE-REV-T2", "ENER-SO-REV-T2",
            # TRADITIONAL_ENERGY per-name revenue
            "ENER-XOM-REV-T1", "ENER-CVX-REV-T1", "ENER-COP-REV-T2",
            "ENER-OILGAS-OCF-T2",
            # MANUAL Tier-1 anchors
            "ENER-DATACENTER-POWER-DEMAND-T1",
            "ENER-COMMODITY-OIL-T1",
            # Tier-2 MANUAL
            "ENER-NUCLEAR-SMR-T2", "ENER-REGULATORY-RATECASE-T2",
            "ENER-LNG-CONTRACTS-T2",
        ):
            assert cid in ids, f"Energy catalyst {cid} missing"

    def test_exit_csv_loadable_ten_required_scenarios(self, run_output):
        exits = load_exits(run_output["exit_path"])
        assert len(exits) == 10
        assert all(e.current_status == "MONITORING" for e in exits)
        ids = {e.exit_id for e in exits}
        # AI_POWER_INFRA — 6 required
        ai_required = {
            "ENER-EXIT-DATACENTER-CAPEX-CUT",
            "ENER-EXIT-GRID-ORDERS-SLOW",
            "ENER-EXIT-UTILITY-LOAD-MISS",
            "ENER-EXIT-TURBINE-BACKLOG-DETERIORATE",
            "ENER-EXIT-REGULATORY-SHOCK",
            "ENER-EXIT-AI-POWER-NARRATIVE-REVERSAL",
        }
        # TRADITIONAL_ENERGY — 4 required
        trad_required = {
            "ENER-EXIT-OIL-DEMAND-SHOCK",
            "ENER-EXIT-COMMODITY-PRICE-COLLAPSE",
            "ENER-EXIT-CAPEX-DISCIPLINE-BREAK",
            "ENER-EXIT-DIVIDEND-COVERAGE-STRESS",
        }
        assert ai_required.issubset(ids)
        assert trad_required.issubset(ids)

    def test_report_has_disclaimer_and_valid_signal(self, run_output):
        text = run_output["rpt_path"].read_text(encoding="utf-8")
        assert ("research signal, not a trading signal, not investment advice, "
                "and not order execution") in text
        assert "LIVE_TRADING_ENABLED = False" in text
        signal = run_output["summary"]["signal"]
        assert signal in SIGNAL_LABELS
        assert signal in text

    def test_report_has_subsector_split_section(self, run_output):
        text = run_output["rpt_path"].read_text(encoding="utf-8")
        # User-required deliverable: split between AI_POWER_INFRA and
        # TRADITIONAL_ENERGY (plus MACRO as a third group).
        assert ("## Subsector split (AI_POWER_INFRA vs TRADITIONAL_ENERGY "
                "vs MACRO)") in text
        assert "### AI_POWER_INFRA" in text
        assert "### TRADITIONAL_ENERGY" in text
        assert "### MACRO" in text

    def test_report_has_data_gaps_and_autoderived_sections(self, run_output):
        text = run_output["rpt_path"].read_text(encoding="utf-8")
        assert "## Data gaps" in text
        assert "## Auto-derived catalysts (V6.4)" in text
        assert "## Next recommended step" in text
        assert "## Future roadmap" in text


# --------------------------------------------------------------------------- #
# subsector split correctness
# --------------------------------------------------------------------------- #
class TestSubsectorSplit:
    def test_catalysts_assigned_to_correct_subsectors(self, run_output):
        cats = {c.catalyst_id: c for c in load_catalysts(run_output["cat_path"])}
        # AI_POWER_INFRA constituents
        for cid in ("ENER-GEV-REV-T1", "ENER-ETN-REV-T1", "ENER-VRT-REV-T1",
                    "ENER-PWR-REV-T1", "ENER-CEG-REV-T1", "ENER-NEE-REV-T2",
                    "ENER-SO-REV-T2", "ENER-DATACENTER-POWER-DEMAND-T1",
                    "ENER-NUCLEAR-SMR-T2", "ENER-REGULATORY-RATECASE-T2"):
            assert cats[cid].subsector == "AI_POWER_INFRA", \
                f"{cid} should be AI_POWER_INFRA"
        # TRADITIONAL_ENERGY constituents
        for cid in ("ENER-XOM-REV-T1", "ENER-CVX-REV-T1", "ENER-COP-REV-T2",
                    "ENER-OILGAS-OCF-T2", "ENER-COMMODITY-OIL-T1",
                    "ENER-LNG-CONTRACTS-T2"):
            assert cats[cid].subsector == "TRADITIONAL_ENERGY", \
                f"{cid} should be TRADITIONAL_ENERGY"
        # MACRO constituents
        for cid in ("ENER-MACRO-RATES-T2", "ENER-MACRO-VOL-T2",
                    "ENER-MACRO-CURVE-T2"):
            assert cats[cid].subsector == "MACRO", f"{cid} should be MACRO"

    def test_summary_subsector_counts_match_csv(self, run_output):
        s = run_output["summary"]
        cats = load_catalysts(run_output["cat_path"])
        ai = sum(1 for c in cats if c.subsector == "AI_POWER_INFRA")
        trad = sum(1 for c in cats if c.subsector == "TRADITIONAL_ENERGY")
        macro = sum(1 for c in cats if c.subsector == "MACRO")
        assert s["n_ai_power_infra"] == ai
        assert s["n_traditional_energy"] == trad
        assert s["n_macro"] == macro
        # The three groups should account for every catalyst (no orphans).
        assert ai + trad + macro == len(cats)


# --------------------------------------------------------------------------- #
# determinism + framework agreement
# --------------------------------------------------------------------------- #
class TestDeterminism:
    def test_regeneration_is_byte_identical(self, tmp_path, driver):
        d1, r1 = tmp_path / "a/data", tmp_path / "a/reports"
        d2, r2 = tmp_path / "b/data", tmp_path / "b/reports"
        driver.main(data_dir=d1, report_dir=r1)
        driver.main(data_dir=d2, report_dir=r2)

        def sha(p: Path) -> str:
            return hashlib.sha256(p.read_bytes()).hexdigest()

        for fname in ("energy_thesis_tracker.csv",
                      "energy_emergency_exits.csv"):
            assert sha(d1 / fname) == sha(d2 / fname), (
                f"{fname} differs between two runs — driver not deterministic"
            )
        assert sha(r1 / "energy_signal.md") == sha(r2 / "energy_signal.md")


def test_score_matches_independent_recompute(run_output):
    from quantbot.research.sector_tracker import score_sector
    cats = load_catalysts(run_output["cat_path"])
    exits = load_exits(run_output["exit_path"])
    s = score_sector(cats, exits, sector="ENERGY")
    assert s.signal == run_output["summary"]["signal"]
    assert s.normalized_score == pytest.approx(
        run_output["summary"]["normalized_score"]
    )


# --------------------------------------------------------------------------- #
# auto-derivation specifics (skip cleanly if SEC cache absent)
# --------------------------------------------------------------------------- #
class TestV64AutoDerivation:
    @pytest.mark.skipif(not _cached("VRT"),
                        reason="VRT SEC cache not pre-populated")
    def test_vrt_revenue_auto_derived(self, run_output):
        cats = {c.catalyst_id: c for c in load_catalysts(run_output["cat_path"])}
        c = cats["ENER-VRT-REV-T1"]
        assert c.source_type == "SEC_EDGAR"
        assert "auto-derived" in c.source_detail.lower()
        assert c.current_value != "n/a"

    @pytest.mark.skipif(not _cached("XOM"),
                        reason="XOM SEC cache not pre-populated")
    def test_xom_revenue_auto_derived(self, run_output):
        cats = {c.catalyst_id: c for c in load_catalysts(run_output["cat_path"])}
        c = cats["ENER-XOM-REV-T1"]
        assert c.source_type == "SEC_EDGAR"
        assert "auto-derived" in c.source_detail.lower()

    @pytest.mark.skipif(not (_cached("XOM") and _cached("CVX") and _cached("COP")),
                        reason="Oil-major OCF cohort not pre-populated")
    def test_oilgas_ocf_aggregate_auto_derived(self, run_output):
        cats = {c.catalyst_id: c for c in load_catalysts(run_output["cat_path"])}
        c = cats["ENER-OILGAS-OCF-T2"]
        assert c.source_type == "SEC_EDGAR"
        assert "XOM+CVX+COP" in c.source_detail

    def test_manual_anchors_remain_manual(self, run_output):
        """The data-center demand, commodity-oil, SMR, regulatory, LNG
        catalysts must NEVER be auto-derived from this repo's local data."""
        cats = {c.catalyst_id: c for c in load_catalysts(run_output["cat_path"])}
        for cid in ("ENER-DATACENTER-POWER-DEMAND-T1",
                    "ENER-COMMODITY-OIL-T1",
                    "ENER-NUCLEAR-SMR-T2",
                    "ENER-REGULATORY-RATECASE-T2",
                    "ENER-LNG-CONTRACTS-T2"):
            assert cats[cid].source_type == "MANUAL"
            assert cats[cid].status == "NEUTRAL"

    @pytest.mark.skipif(not (_cached("VRT") and _cached("XOM")),
                        reason="SEC cache not pre-populated")
    def test_auto_derived_count_is_substantial(self, run_output):
        """With full US-filer cache, V6.4 should auto-derive a majority."""
        n_auto = run_output["summary"]["n_auto_derived"]
        n_total = run_output["summary"]["n_catalysts"]
        assert n_auto >= 10, (
            f"expected V6.4 to auto-derive >=10 catalysts; got {n_auto}/{n_total}"
        )

    def test_macro_catalysts_present_with_ener_prefix(self, run_output):
        ids = {c.catalyst_id for c in load_catalysts(run_output["cat_path"])}
        # sector[:4] = "ENER" for "ENERGY"
        for cid in ("ENER-MACRO-RATES-T2", "ENER-MACRO-VOL-T2",
                    "ENER-MACRO-CURVE-T2"):
            assert cid in ids

    def test_emergency_exit_ids_indicate_subsector_via_naming(self, run_output):
        """Exits don't carry a subsector field in V6.1 — the AI vs TRAD split
        is communicated through the exit_id naming convention. Sanity-check it
        so a reader can group them by prefix without ambiguity."""
        exits = {e.exit_id: e for e in load_exits(run_output["exit_path"])}
        ai_named = {"ENER-EXIT-DATACENTER-CAPEX-CUT",
                    "ENER-EXIT-GRID-ORDERS-SLOW",
                    "ENER-EXIT-UTILITY-LOAD-MISS",
                    "ENER-EXIT-TURBINE-BACKLOG-DETERIORATE",
                    "ENER-EXIT-REGULATORY-SHOCK",
                    "ENER-EXIT-AI-POWER-NARRATIVE-REVERSAL"}
        trad_named = {"ENER-EXIT-OIL-DEMAND-SHOCK",
                      "ENER-EXIT-COMMODITY-PRICE-COLLAPSE",
                      "ENER-EXIT-CAPEX-DISCIPLINE-BREAK",
                      "ENER-EXIT-DIVIDEND-COVERAGE-STRESS"}
        assert ai_named.issubset(exits)
        assert trad_named.issubset(exits)
        # Six + four = ten total, matching the user spec.
        assert len(ai_named) + len(trad_named) == 10


# --------------------------------------------------------------------------- #
# guardrails
# --------------------------------------------------------------------------- #
class TestGuardrails:
    def test_live_trading_flag_remains_false(self):
        assert quantbot.LIVE_TRADING_ENABLED is False

    def test_driver_makes_no_network_call(self, monkeypatch, tmp_path, driver):
        from urllib import request as _urllib_request

        def _no_net(*a, **kw):
            raise AssertionError(
                "V6.4 ENERGY driver attempted a network call — must be local-only"
            )

        monkeypatch.setattr(_urllib_request, "urlopen", _no_net)
        try:
            import quantbot.company.sec_edgar as sec_mod
            monkeypatch.setattr(sec_mod, "urlopen", _no_net, raising=False)
        except Exception:
            pass
        out = driver.main(data_dir=tmp_path / "data",
                          report_dir=tmp_path / "reports")
        assert out["signal"] in SIGNAL_LABELS

    def test_driver_source_has_no_broker_or_order_tokens(self):
        src = (REPO_ROOT / "scripts" /
               "run_sector_tracker_energy.py").read_text(encoding="utf-8")
        for forbidden in (
            "ib_insync", "ibapi", "ib_async",
            "from quantbot.backtest.broker", "from quantbot.backtest.engine",
            "place_order", "submit_order", "send_order", "fill_order",
        ):
            assert forbidden not in src, (
                f"forbidden token {forbidden!r} in energy driver source"
            )

    def test_rendered_md_has_no_order_tokens(self, run_output):
        text = run_output["rpt_path"].read_text(encoding="utf-8").upper()
        for forbidden in (" SELL ", " SHORT ", "PLACE_ORDER",
                          "SUBMIT_ORDER", "FILL_ORDER"):
            assert forbidden not in text
