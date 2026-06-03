"""Tests for the V6.3 AI / cloud / software-infrastructure sector tracker.

Mirrors the V6.2.1 semi-driver test structure. Validates:
  - three artefacts written; CSVs loadable by V6.1 framework
  - report contains the exact required disclaimer + a valid signal
  - driver is deterministic (re-run is byte-identical)
  - no network call required when SEC caches are present
  - no broker / IBKR / order tokens in the driver source
  - LIVE_TRADING_ENABLED stays False
  - V6.3-specific catalyst IDs are present and auto-derived when caches exist
  - driver_utils helpers exposed for sector drivers
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
        mod = importlib.import_module("run_sector_tracker_ai")
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
        "cat_path": data_dir / "ai_thesis_tracker.csv",
        "exit_path": data_dir / "ai_emergency_exits.csv",
        "rpt_path": rep_dir / "ai_signal.md",
    }


def _facts_cached(ticker: str) -> bool:
    from quantbot.company.sec_edgar import (
        ticker_to_cik, company_cache_dir,
    )
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
        assert len(cats) >= 15, "expected >=15 catalysts for the AI sector"
        assert all(c.sector == "AI" for c in cats)
        ids = {c.catalyst_id for c in cats}
        # Headline AI signals must be present
        for cid in ("AI-MSFT-REV-T1", "AI-GOOGL-REV-T1", "AI-AMZN-REV-T1",
                    "AI-META-REV-T1", "AI-ORCL-REV-T1",
                    "AI-HYPERSCALER-CAPEX-T1",
                    "AI-PLTR-REV-T2",
                    "AI-RD-GROWTH-T2",
                    "AI-OPENAI-ARR-T1", "AI-ANTHROPIC-ARR-T1",
                    "AI-REGULATION-RISK-T1"):
            assert cid in ids, f"AI catalyst {cid} missing"

    def test_exit_csv_loadable_six_required_scenarios(self, run_output):
        exits = load_exits(run_output["exit_path"])
        assert len(exits) == 6
        assert all(e.current_status == "MONITORING" for e in exits)
        ids = {e.exit_id for e in exits}
        required = {
            "AI-EXIT-HYPERSCALER-CAPEX-CUT",
            "AI-EXIT-CLOUD-DECEL",
            "AI-EXIT-INFRA-FINANCING-STRESS",
            "AI-EXIT-LAB-SCALING-PULLBACK",
            "AI-EXIT-MODEL-PRICING-COLLAPSE",
            "AI-EXIT-REGULATION-SHOCK",
        }
        assert required.issubset(ids)

    def test_report_has_disclaimer_and_valid_signal(self, run_output):
        text = run_output["rpt_path"].read_text(encoding="utf-8")
        assert ("research signal, not a trading signal, not investment advice, "
                "and not order execution") in text
        assert "LIVE_TRADING_ENABLED = False" in text
        signal = run_output["summary"]["signal"]
        assert signal in SIGNAL_LABELS
        assert signal in text

    def test_report_has_data_gaps_and_autoderived_sections(self, run_output):
        text = run_output["rpt_path"].read_text(encoding="utf-8")
        assert "## Data gaps" in text
        assert "## Auto-derived catalysts (V6.3)" in text
        assert "## Next recommended step" in text
        assert "## Future roadmap" in text


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

        for fname in ("ai_thesis_tracker.csv", "ai_emergency_exits.csv"):
            assert sha(d1 / fname) == sha(d2 / fname), (
                f"{fname} differs between two runs — driver is not deterministic"
            )
        assert sha(r1 / "ai_signal.md") == sha(r2 / "ai_signal.md")


def test_score_matches_independent_recompute(run_output):
    from quantbot.research.sector_tracker import score_sector
    cats = load_catalysts(run_output["cat_path"])
    exits = load_exits(run_output["exit_path"])
    s = score_sector(cats, exits, sector="AI")
    assert s.signal == run_output["summary"]["signal"]
    assert s.normalized_score == pytest.approx(
        run_output["summary"]["normalized_score"]
    )


# --------------------------------------------------------------------------- #
# auto-derivation specifics (skip cleanly if SEC cache absent)
# --------------------------------------------------------------------------- #
class TestV63AutoDerivation:
    @pytest.mark.skipif(not _facts_cached("MSFT"),
                        reason="MSFT SEC cache not pre-populated")
    def test_msft_revenue_auto_derived_when_cached(self, run_output):
        cats = {c.catalyst_id: c for c in load_catalysts(run_output["cat_path"])}
        c = cats["AI-MSFT-REV-T1"]
        assert c.source_type == "SEC_EDGAR"
        assert "auto-derived" in c.source_detail.lower()
        assert c.current_value != "n/a"

    @pytest.mark.skipif(not (_facts_cached("MSFT") and _facts_cached("GOOGL")
                              and _facts_cached("META")),
                        reason="hyperscaler SEC cache not pre-populated")
    def test_hyperscaler_capex_aggregate_is_auto_derived(self, run_output):
        cats = {c.catalyst_id: c for c in load_catalysts(run_output["cat_path"])}
        c = cats["AI-HYPERSCALER-CAPEX-T1"]
        assert c.source_type == "SEC_EDGAR"
        assert "MSFT+GOOGL+META" in c.source_detail
        # AMZN exclusion must be documented in the notes
        assert "AMZN" in c.notes

    @pytest.mark.skipif(not _facts_cached("MSFT"),
                        reason="MSFT SEC cache not pre-populated")
    def test_msft_operating_margin_is_auto_derived(self, run_output):
        cats = {c.catalyst_id: c for c in load_catalysts(run_output["cat_path"])}
        c = cats["AI-MSFT-OPMARGIN-T2"]
        assert c.source_type == "SEC_EDGAR"
        assert "OpInc/Revenue" in c.source_detail

    @pytest.mark.skipif(not (_facts_cached("MSFT") and _facts_cached("GOOGL")
                              and _facts_cached("META") and _facts_cached("ORCL")),
                        reason="R&D cohort SEC cache not pre-populated")
    def test_rd_growth_aggregate_is_auto_derived(self, run_output):
        cats = {c.catalyst_id: c for c in load_catalysts(run_output["cat_path"])}
        c = cats["AI-RD-GROWTH-T2"]
        assert c.source_type == "SEC_EDGAR"
        assert "MSFT+GOOGL+META+ORCL" in c.source_detail

    def test_macro_catalysts_present(self, run_output):
        cats = {c.catalyst_id: c for c in load_catalysts(run_output["cat_path"])}
        # AI prefix from sector[:4] (sector is "AI", only 2 chars)
        for cid in ("AI-MACRO-RATES-T2", "AI-MACRO-VOL-T2", "AI-MACRO-CURVE-T2"):
            assert cid in cats, f"macro catalyst {cid} missing"

    def test_private_company_catalysts_remain_manual(self, run_output):
        cats = {c.catalyst_id: c for c in load_catalysts(run_output["cat_path"])}
        # OpenAI / Anthropic must NEVER be auto-derived (no public source)
        for cid in ("AI-OPENAI-ARR-T1", "AI-ANTHROPIC-ARR-T1"):
            assert cats[cid].source_type == "MANUAL"
            assert cats[cid].status == "NEUTRAL"

    @pytest.mark.skipif(not _facts_cached("MSFT"),
                        reason="SEC cache not pre-populated")
    def test_auto_derived_count_is_substantial(self, run_output):
        """With the full US-filer cache, V6.3 should auto-derive a majority."""
        n_auto = run_output["summary"]["n_auto_derived"]
        n_total = run_output["summary"]["n_catalysts"]
        assert n_auto >= 10, (
            f"expected V6.3 to auto-derive >=10 catalysts; got {n_auto}/{n_total}"
        )


# --------------------------------------------------------------------------- #
# guardrails
# --------------------------------------------------------------------------- #
class TestGuardrails:
    def test_live_trading_flag_remains_false(self):
        assert quantbot.LIVE_TRADING_ENABLED is False

    def test_driver_makes_no_network_call(self, monkeypatch, tmp_path, driver):
        """Patch urlopen so any network attempt raises; driver must still succeed
        because the SEC + FRED + VIX caches are all populated locally."""
        from urllib import request as _urllib_request

        def _no_net(*a, **kw):
            raise AssertionError(
                "V6.3 AI driver attempted a network call — must be local-only"
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
        src = (REPO_ROOT / "scripts" / "run_sector_tracker_ai.py").read_text(
            encoding="utf-8"
        )
        for forbidden in (
            "ib_insync", "ibapi", "ib_async",
            "from quantbot.backtest.broker", "from quantbot.backtest.engine",
            "place_order", "submit_order", "send_order", "fill_order",
        ):
            assert forbidden not in src, (
                f"forbidden token {forbidden!r} in AI driver source"
            )

    def test_driver_utils_source_has_no_broker_or_order_tokens(self):
        src = (REPO_ROOT / "src" / "quantbot" / "research" / "sector_tracker"
               / "driver_utils.py").read_text(encoding="utf-8")
        for forbidden in (
            "ib_insync", "ibapi", "ib_async",
            "from quantbot.backtest.broker",
            "place_order", "submit_order", "send_order",
        ):
            assert forbidden not in src

    def test_rendered_md_has_no_order_tokens(self, run_output):
        text = run_output["rpt_path"].read_text(encoding="utf-8").upper()
        for forbidden in (" SELL ", " SHORT ", "PLACE_ORDER",
                          "SUBMIT_ORDER", "FILL_ORDER"):
            assert forbidden not in text


# --------------------------------------------------------------------------- #
# driver_utils sanity (the new shared module)
# --------------------------------------------------------------------------- #
class TestDriverUtilsModule:
    def test_imports_and_exposes_helpers(self):
        from quantbot.research.sector_tracker import driver_utils as du
        for name in ("REV_YOY_BANDS", "OPERATING_MARGIN_BANDS_30",
                     "VIX_BANDS", "DGS10_BANDS", "T10Y2Y_BANDS_HIGHER_IS_BETTER",
                     "bucket_higher_better", "bucket_lower_better", "is_fresh",
                     "facts_cached", "company_annual_flow_yoy",
                     "fred_latest", "vix_latest",
                     "make_catalyst", "company_revenue_catalyst",
                     "macro_catalysts", "DISCLAIMER",
                     "data_gap_section", "autoderived_section",
                     "count_auto_derived"):
            assert hasattr(du, name), f"driver_utils missing {name}"

    def test_bucket_higher_better_boundaries(self):
        from quantbot.research.sector_tracker.driver_utils import (
            REV_YOY_BANDS, bucket_higher_better,
        )
        assert bucket_higher_better(20.0, REV_YOY_BANDS) == "BULL"
        assert bucket_higher_better(19.9, REV_YOY_BANDS) == "NEUTRAL"
        assert bucket_higher_better(-10.0, REV_YOY_BANDS) == "NEUTRAL"
        assert bucket_higher_better(-10.01, REV_YOY_BANDS) == "NEAR_THRESHOLD"
        assert bucket_higher_better(-26.0, REV_YOY_BANDS) == "BROKEN"

    def test_macro_catalyst_id_prefix_matches_sector(self):
        from quantbot.research.sector_tracker.driver_utils import macro_catalysts
        out = macro_catalysts(sector="AI", report_date="2026-05-28", tier=2)
        ids = {c.catalyst_id for c in out}
        assert ids == {"AI-MACRO-RATES-T2", "AI-MACRO-VOL-T2", "AI-MACRO-CURVE-T2"}

    def test_is_fresh(self):
        from quantbot.research.sector_tracker.driver_utils import is_fresh
        import pandas as pd
        # within 540 days
        assert is_fresh(pd.Timestamp("2025-12-31"), report_date="2026-05-28")
        # 600 days ago -> not fresh
        old = pd.Timestamp("2026-05-28") - pd.Timedelta(days=600)
        assert not is_fresh(old, report_date="2026-05-28")
        # None / NaT -> not fresh
        assert not is_fresh(None, report_date="2026-05-28")
        assert not is_fresh(pd.NaT, report_date="2026-05-28")
