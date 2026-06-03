"""Tests for the V6.2 Semiconductor sector tracker driver.

Validates:
  - the driver runs deterministically against existing local caches,
  - the generated CSVs can be loaded by the V6.1 framework,
  - the generated report contains the required disclaimer and a valid signal,
  - re-running produces byte-identical output (determinism),
  - guardrails: LIVE_TRADING_ENABLED False, driver makes no network call,
    no broker / IBKR / order tokens in the driver source.

The driver is run with tmp_path overrides so the real `data/` and `reports/`
files are not touched by this test.
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


@pytest.fixture(scope="module")
def driver():
    """Import the driver module from the scripts/ dir."""
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        mod = importlib.import_module("run_sector_tracker_semi")
    finally:
        if str(REPO_ROOT / "scripts") in sys.path:
            sys.path.remove(str(REPO_ROOT / "scripts"))
    return mod


@pytest.fixture
def run_output(tmp_path, driver):
    """Invoke driver.main into tmp_path and return its summary + artefacts."""
    data_dir = tmp_path / "data"
    rep_dir = tmp_path / "reports"
    summary = driver.main(data_dir=data_dir, report_dir=rep_dir)
    return {
        "summary": summary,
        "cat_path": data_dir / "semiconductor_thesis_tracker.csv",
        "exit_path": data_dir / "semiconductor_emergency_exits.csv",
        "rpt_path": rep_dir / "semiconductor_signal.md",
    }


# --------------------------------------------------------------------------- #
# happy-path
# --------------------------------------------------------------------------- #
class TestDriverOutputs:
    def test_three_artifacts_written(self, run_output):
        for k in ("cat_path", "exit_path", "rpt_path"):
            assert run_output[k].is_file(), f"missing artefact: {k}"

    def test_catalyst_csv_loadable_via_v61_framework(self, run_output):
        cats = load_catalysts(run_output["cat_path"])
        assert len(cats) >= 10, "expected >=10 catalysts for the semi sector"
        assert all(c.sector == "SEMICONDUCTOR" for c in cats)
        # The two auto-derived MU catalysts must be present and BULL given the
        # MU FY2025 record results in the cached companyfacts.
        ids = {c.catalyst_id for c in cats}
        assert "SEMI-MU-HBM-REV-T1" in ids
        assert "SEMI-MU-MEMCYCLE-NI-T1" in ids
        mu_bull = [c for c in cats if c.catalyst_id.startswith("SEMI-MU-")
                   and c.status == "BULL"]
        assert len(mu_bull) == 2, (
            "MU cycle catalysts should be auto-derived BULL given FY2025 data"
        )

    def test_exit_csv_loadable_and_all_monitoring_by_default(self, run_output):
        exits = load_exits(run_output["exit_path"])
        assert len(exits) == 6, "spec calls for 6 emergency-exit scenarios"
        # None should default to TRIGGERED — only MONITORING/INACTIVE allowed.
        assert all(e.current_status == "MONITORING" for e in exits)
        # Sanity: the six required scenarios are covered
        ids = {e.exit_id for e in exits}
        required = {
            "SEMI-EXIT-NVDA-DC-SEQ-DECLINE",
            "SEMI-EXIT-HYPERSCALER-CAPEX-CUT",
            "SEMI-EXIT-HBM-ASP-DETERIORATION",
            "SEMI-EXIT-CHINA-EXPORT-SHOCK",
            "SEMI-EXIT-CUSTOM-SILICON-DISPLACE",
            "SEMI-EXIT-INVENTORY-SHARP-NEG",
        }
        assert required.issubset(ids)

    def test_report_has_disclaimer_and_valid_signal(self, run_output):
        text = run_output["rpt_path"].read_text(encoding="utf-8")
        # Required research-only disclaimer (exact phrase from the spec).
        assert ("research signal, not a trading signal, not investment advice, "
                "and not order execution") in text
        assert "LIVE_TRADING_ENABLED = False" in text
        # The rendered signal label must be one of the six V6.1 labels.
        signal = run_output["summary"]["signal"]
        assert signal in SIGNAL_LABELS
        assert signal in text

    def test_report_has_data_gaps_and_next_step_sections(self, run_output):
        text = run_output["rpt_path"].read_text(encoding="utf-8")
        assert "## Data gaps" in text
        assert "## Next recommended step" in text
        assert "## Future roadmap" in text  # roadmap-only note for V6.6+


# --------------------------------------------------------------------------- #
# determinism
# --------------------------------------------------------------------------- #
class TestDeterminism:
    def test_regeneration_is_byte_identical(self, tmp_path, driver):
        d1, r1 = tmp_path / "a/data", tmp_path / "a/reports"
        d2, r2 = tmp_path / "b/data", tmp_path / "b/reports"
        driver.main(data_dir=d1, report_dir=r1)
        driver.main(data_dir=d2, report_dir=r2)

        def sha(p: Path) -> str:
            return hashlib.sha256(p.read_bytes()).hexdigest()

        for fname in ("semiconductor_thesis_tracker.csv",
                      "semiconductor_emergency_exits.csv"):
            assert sha(d1 / fname) == sha(d2 / fname), (
                f"{fname} differs between two runs — driver is not deterministic"
            )
        assert sha(r1 / "semiconductor_signal.md") == sha(r2 / "semiconductor_signal.md")


# --------------------------------------------------------------------------- #
# guardrails
# --------------------------------------------------------------------------- #
class TestGuardrails:
    def test_live_trading_flag_remains_false(self):
        assert quantbot.LIVE_TRADING_ENABLED is False

    def test_driver_makes_no_network_call(self, monkeypatch, tmp_path, driver):
        """Patch urlopen so any network attempt raises; driver must still succeed."""
        from urllib import request as _urllib_request

        def _no_net(*a, **kw):
            raise AssertionError(
                "V6.2 semi driver attempted a network call — must be local-only"
            )

        monkeypatch.setattr(_urllib_request, "urlopen", _no_net)
        # also patch in the SEC module's reference, in case it was imported by name
        try:
            import quantbot.company.sec_edgar as sec_mod
            monkeypatch.setattr(sec_mod, "urlopen", _no_net, raising=False)
        except Exception:
            pass
        # Run — local caches must satisfy the driver entirely.
        out = driver.main(data_dir=tmp_path / "data", report_dir=tmp_path / "reports")
        assert out["signal"] in SIGNAL_LABELS

    def test_driver_source_has_no_broker_or_order_tokens(self):
        src_path = REPO_ROOT / "scripts" / "run_sector_tracker_semi.py"
        text = src_path.read_text(encoding="utf-8")
        for forbidden in (
            "ib_insync", "ibapi", "ib_async",
            "from quantbot.backtest.broker", "from quantbot.backtest.engine",
            "place_order", "submit_order", "send_order", "fill_order",
        ):
            assert forbidden not in text, (
                f"forbidden token {forbidden!r} found in semi driver source"
            )

    def test_signal_is_research_label_not_order(self, run_output):
        # Belt-and-suspenders: ensure the generated report does not contain
        # raw broker-order tokens, even though SELECTIVE_BUY is allowed.
        text = run_output["rpt_path"].read_text(encoding="utf-8").upper()
        for forbidden in (" SELL ", " SHORT ", "PLACE_ORDER",
                          "SUBMIT_ORDER", "FILL_ORDER"):
            assert forbidden not in text, (
                f"forbidden order token {forbidden!r} in generated report"
            )


# --------------------------------------------------------------------------- #
# scoring sanity vs framework
# --------------------------------------------------------------------------- #
def test_score_matches_independent_recompute(run_output, driver):
    """Sanity: re-score the loaded CSV via the V6.1 framework and confirm the
    driver's reported signal matches the framework's signal (this guards against
    accidental driver-side score logic outside the framework)."""
    from quantbot.research.sector_tracker import score_sector
    cats = load_catalysts(run_output["cat_path"])
    exits = load_exits(run_output["exit_path"])
    s = score_sector(cats, exits, sector="SEMICONDUCTOR")
    assert s.signal == run_output["summary"]["signal"]
    assert s.normalized_score == pytest.approx(
        run_output["summary"]["normalized_score"]
    )


# --------------------------------------------------------------------------- #
# V6.2.1 — auto-derived catalyst coverage when SEC cache is present.
# These tests skip gracefully on environments without the pre-populated cache,
# so they don't fail on fresh CI checkouts.
# --------------------------------------------------------------------------- #
def _cache_present(ticker: str) -> bool:
    from quantbot.company.sec_edgar import (
        ticker_to_cik, company_cache_dir,
    )
    cik = ticker_to_cik(ticker)
    if not cik:
        return False
    return (company_cache_dir() / "companyfacts" / f"CIK{cik}.json").is_file()


class TestV621AutoDerivation:
    def test_three_new_company_revenue_catalysts_present(self, run_output):
        cats = load_catalysts(run_output["cat_path"])
        ids = {c.catalyst_id for c in cats}
        for cid in ("SEMI-NVDA-REV-T1", "SEMI-AMD-REV-T2", "SEMI-AVGO-REV-T2"):
            assert cid in ids, f"V6.2.1 catalyst {cid} missing"

    def test_two_upgrades_and_one_rename_present(self, run_output):
        cats = load_catalysts(run_output["cat_path"])
        ids = {c.catalyst_id for c in cats}
        # NVDA-GM and INVENTORY-CYCLE upgraded in place; CAPEX-ORDERS renamed
        # to EQUIPMENT-DEMAND (more accurate label for what it measures).
        assert "SEMI-NVDA-GM-T1" in ids
        assert "SEMI-INVENTORY-CYCLE-T2" in ids
        assert "SEMI-EQUIPMENT-DEMAND-T2" in ids
        assert "SEMI-CAPEX-ORDERS-T2" not in ids  # renamed away

    @pytest.mark.skipif(not _cache_present("NVDA"),
                        reason="NVDA SEC cache not pre-populated")
    def test_nvda_revenue_is_auto_derived_when_cached(self, run_output):
        cats = {c.catalyst_id: c for c in load_catalysts(run_output["cat_path"])}
        c = cats["SEMI-NVDA-REV-T1"]
        assert c.source_type == "SEC_EDGAR"
        assert "auto-derived" in c.source_detail.lower()
        # The stale-tag bug fix ensures NVDA revenue reaches the freshness
        # window; status should not be NEUTRAL purely due to stale data.
        assert c.status in {"BULL", "NEAR_THRESHOLD", "BROKEN", "NEUTRAL"}
        assert c.current_value != "n/a"

    @pytest.mark.skipif(not _cache_present("NVDA"),
                        reason="NVDA SEC cache not pre-populated")
    def test_nvda_gross_margin_is_auto_derived_when_cached(self, run_output):
        cats = {c.catalyst_id: c for c in load_catalysts(run_output["cat_path"])}
        c = cats["SEMI-NVDA-GM-T1"]
        assert c.source_type == "SEC_EDGAR"
        assert "GrossProfit/Revenue" in c.source_detail

    @pytest.mark.skipif(not (_cache_present("AMAT") and _cache_present("LRCX")
                              and _cache_present("KLAC")),
                        reason="Equipment-maker SEC cache not pre-populated")
    def test_equipment_demand_aggregate_is_auto_derived(self, run_output):
        cats = {c.catalyst_id: c for c in load_catalysts(run_output["cat_path"])}
        c = cats["SEMI-EQUIPMENT-DEMAND-T2"]
        assert c.source_type == "SEC_EDGAR"
        assert "AMAT+LRCX+KLAC" in c.source_detail

    @pytest.mark.skipif(not (_cache_present("NVDA") and _cache_present("AMD")
                              and _cache_present("MU") and _cache_present("AVGO")),
                        reason="Inventory-cohort SEC cache not pre-populated")
    def test_inventory_cycle_aggregate_is_auto_derived(self, run_output):
        cats = {c.catalyst_id: c for c in load_catalysts(run_output["cat_path"])}
        c = cats["SEMI-INVENTORY-CYCLE-T2"]
        assert c.source_type == "SEC_EDGAR"
        assert "InventoryNet" in c.source_detail

    @pytest.mark.skipif(not _cache_present("NVDA"),
                        reason="SEC cache not pre-populated")
    def test_auto_derived_count_increased_vs_v62(self, run_output):
        """V6.2 produced 5 auto-derived (MU x2 + 3 macro). V6.2.1 should produce
        at least 8 auto-derived when the full US-filer cache is populated."""
        n_auto = run_output["summary"]["n_auto_derived"]
        assert n_auto >= 8, (
            f"expected V6.2.1 to auto-derive >=8 catalysts post-pre-fetch; got {n_auto}"
        )

    def test_total_catalyst_count_is_v621_size(self, run_output):
        """V6.2.1 totals 17 catalysts (V6.2 had 14: 3 new revenue catalysts
        added; NVDA-GM/INVENTORY/EQUIPMENT upgraded in place)."""
        cats = load_catalysts(run_output["cat_path"])
        assert len(cats) == 17, f"expected 17 V6.2.1 catalysts, got {len(cats)}"

    def test_v621_report_includes_autoderived_section(self, run_output):
        text = run_output["rpt_path"].read_text(encoding="utf-8")
        assert "## Auto-derived catalysts (V6.2.1)" in text


# --------------------------------------------------------------------------- #
# V6.2.1 — guardrail: the company_facts.py extension must not import broker
# / IBKR / live trading. The driver inherits that constraint via its existing
# `test_driver_has_no_broker_or_order_tokens` test.
# --------------------------------------------------------------------------- #
def test_company_facts_extension_has_no_broker_imports():
    src = (REPO_ROOT / "src" / "quantbot" / "company" /
           "company_facts.py").read_text(encoding="utf-8")
    for forbidden in ("ib_insync", "ibapi", "ib_async",
                       "from quantbot.backtest.broker",
                       "place_order", "submit_order", "send_order"):
        assert forbidden not in src, (
            f"forbidden token {forbidden!r} in company_facts.py"
        )
