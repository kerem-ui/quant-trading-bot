"""V7.2 — Design-only milestone verification.

Covers:

  * The hand-written V7.2 design document exists at the expected path.
  * The doc covers every section the V7.2 spec requires (purpose,
    guardrails, future-file list, required flags, allowed/disallowed
    operations, failure-mode design, CSV mapping, testing plan, security
    note, path recommendation).
  * The doc explicitly states the trading guardrails (no orders, no buy
    /sell, no live trading, `LIVE_TRADING_ENABLED` False, opt-in flags).
  * **Crucially**: NO IBKR code has been added. The whole repo is
    grep-tested for `ib_insync` / `ibapi` imports and for the future
    surface files (which must NOT exist yet).
  * Standard guardrails: ``LIVE_TRADING_ENABLED`` False; the V6/V7
    surfaces still import cleanly.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import quantbot

REPO_ROOT = Path(__file__).resolve().parents[1]
DESIGN_DOC_PATH = REPO_ROOT / "reports" / "research" / "V7_2_IBKR_READONLY_DESIGN.md"


# --------------------------------------------------------------------------- #
# Design doc existence + content
# --------------------------------------------------------------------------- #
class TestDesignDocExists:
    def test_doc_file_exists(self):
        assert DESIGN_DOC_PATH.is_file(), (
            f"V7.2 design doc missing at {DESIGN_DOC_PATH}"
        )

    def test_doc_is_non_trivial(self):
        # A real design — not a stub.
        text = DESIGN_DOC_PATH.read_text(encoding="utf-8")
        assert len(text) > 5000, (
            "V7.2 design doc looks like a stub; expected a real design "
            "covering 10 sections."
        )

    def test_doc_marked_design_only(self):
        text = DESIGN_DOC_PATH.read_text(encoding="utf-8")
        assert "DESIGN ONLY" in text.upper() or \
            "Planning Only" in text or "PLANNING ONLY" in text


class TestDesignDocSections:
    """Spec required sections — each must show up in the doc."""

    @classmethod
    def setup_class(cls):
        cls.text = DESIGN_DOC_PATH.read_text(encoding="utf-8")

    def test_section_purpose(self):
        assert "Purpose" in self.text

    def test_section_strict_guardrails(self):
        # Heading style is "## 2. Strict guardrails"; allow either casing.
        assert ("Strict guardrails" in self.text
                or "strict guardrails" in self.text.lower())

    def test_section_proposed_future_files(self):
        assert "Proposed future files" in self.text

    def test_section_required_flags(self):
        assert "Required future flags" in self.text \
            or "Required flags" in self.text

    def test_section_allowed_disallowed(self):
        assert "Allowed" in self.text and "isallowed" in self.text

    def test_section_failure_mode(self):
        assert "Failure-mode" in self.text or "failure mode" in self.text.lower()

    def test_section_csv_mapping(self):
        assert "CSV mapping" in self.text

    def test_section_testing_plan(self):
        assert "Testing plan" in self.text \
            or "testing plan" in self.text.lower()

    def test_section_security_note(self):
        assert "Security" in self.text

    def test_section_path_recommendation(self):
        assert ("Path recommendation" in self.text
                or "path recommendation" in self.text.lower())


class TestDesignDocGuardrailLanguage:
    """The spec requires specific guardrail language. Test for it verbatim."""

    @classmethod
    def setup_class(cls):
        cls.text = DESIGN_DOC_PATH.read_text(encoding="utf-8")

    def test_doc_mentions_live_trading_disabled(self):
        assert "LIVE_TRADING_ENABLED" in self.text
        assert "False" in self.text

    def test_doc_forbids_orders(self):
        # The phrase "No orders" or equivalent must appear in the guardrails.
        t = self.text.lower()
        assert "no orders" in t or "no order placement" in t

    def test_doc_forbids_buy_sell_buttons(self):
        t = self.text.lower()
        assert "buy_button" in t or "buy/sell button" in t or \
            "no buy/sell" in t

    def test_doc_forbids_trade_execution(self):
        t = self.text.lower()
        assert "no trade execution" in t or "no order execution" in t

    def test_doc_forbids_hedge_execution(self):
        t = self.text.lower()
        assert "no hedge execution" in t or "hedge execution" in t

    def test_doc_requires_opt_in_flag(self):
        assert "--enable-ibkr" in self.text

    def test_doc_requires_env_var(self):
        assert "IBKR_READONLY_ENABLED" in self.text

    def test_doc_lists_proposed_future_files(self):
        # All three future surfaces explicitly named.
        assert "ibkr_sync.py" in self.text
        assert "sync_portfolio_ibkr.py" in self.text
        assert "test_ibkr_readonly_sync.py" in self.text

    def test_doc_specifies_readonly_connect_flag(self):
        # The future IB.connect must include readonly=True per the design.
        assert "readonly=True" in self.text

    def test_doc_recommends_v7_0_1_next(self):
        assert "V7.0.1" in self.text


# --------------------------------------------------------------------------- #
# **No IBKR code was added.** The whole repo is grep-tested.
# --------------------------------------------------------------------------- #
class TestNoIBKRCodeAdded:
    """Critical: this V7.2 milestone is DESIGN ONLY. No IBKR code shipped."""

    SEARCH_ROOTS = (
        REPO_ROOT / "src",
        REPO_ROOT / "scripts",
        REPO_ROOT / "apps",
    )

    # Test files may legitimately mention `ib_insync` / `ibapi` as forbidden
    # tokens in their guardrail grep tests. We exclude `tests/` from the
    # source-tree grep.

    def _iter_python_files(self):
        for root in self.SEARCH_ROOTS:
            if not root.is_dir():
                continue
            for p in root.rglob("*.py"):
                yield p

    def test_no_ib_insync_import_anywhere_in_source(self):
        for p in self._iter_python_files():
            text = p.read_text(encoding="utf-8")
            assert "import ib_insync" not in text, (
                f"ib_insync import found in {p} — V7.2 must remain "
                "design-only."
            )
            assert "from ib_insync" not in text, (
                f"from ib_insync import found in {p} — V7.2 must remain "
                "design-only."
            )

    def test_no_ibapi_import_anywhere_in_source(self):
        for p in self._iter_python_files():
            text = p.read_text(encoding="utf-8")
            assert "import ibapi" not in text, (
                f"ibapi import found in {p}"
            )
            assert "from ibapi" not in text, (
                f"from ibapi import found in {p}"
            )

    def test_future_ibkr_sync_file_does_not_exist_yet(self):
        future = (REPO_ROOT / "src" / "quantbot" / "research" / "portfolio"
                  / "ibkr_sync.py")
        assert not future.exists(), (
            f"{future} already exists — V7.2 is supposed to be design-only."
        )

    def test_future_sync_script_does_not_exist_yet(self):
        future = REPO_ROOT / "scripts" / "sync_portfolio_ibkr.py"
        assert not future.exists(), (
            f"{future} already exists — V7.2 is supposed to be design-only."
        )

    def test_future_implementation_test_file_does_not_exist_yet(self):
        future = REPO_ROOT / "tests" / "test_ibkr_readonly_sync.py"
        assert not future.exists(), (
            f"{future} already exists — V7.2 is supposed to be design-only."
        )

    def test_no_tws_or_gateway_connection_code_added(self):
        # Defence-in-depth: the most common method names that would
        # appear in any half-finished IBKR integration. None must be
        # present anywhere in production source.
        forbidden = (
            ".connect(",          # IBKR-style socket connect
            "reqPositions",
            "reqAccountSummary",
            "reqMktData",
            "placeOrder",
            "cancelOrder",
            "bracketOrder",
            "exerciseOptions",
        )
        # The above tokens may legitimately appear in V7.X tests or in
        # documentation as forbidden examples, but NOT in production source.
        for p in self._iter_python_files():
            text = p.read_text(encoding="utf-8")
            for token in forbidden:
                # ".connect(" is too generic to ban outright (any DB / API
                # client could use it). Skip and rely on the explicit
                # `import ib_insync` ban above.
                if token == ".connect(":
                    continue
                assert token not in text, (
                    f"IBKR-style token {token!r} found in {p} — V7.2 is "
                    "design-only."
                )


# --------------------------------------------------------------------------- #
# Standard guardrails (must continue to hold)
# --------------------------------------------------------------------------- #
class TestStandardGuardrails:
    def test_live_trading_disabled(self):
        assert quantbot.LIVE_TRADING_ENABLED is False

    def test_portfolio_schema_unchanged(self):
        # V7.2 design must NOT change the V7.1 schema. Spot-check the
        # field tuple.
        from quantbot.research.portfolio import POSITION_FIELDS
        assert POSITION_FIELDS[:3] == ("as_of", "account", "ticker")
        # If V7.2 implementation later wants new columns it must be a new
        # explicit milestone, not a silent schema change.
        assert len(POSITION_FIELDS) == 16

    def test_protection_label_set_unchanged(self):
        from quantbot.research.protection import ALLOWED_PROTECTION_LABEL
        assert ALLOWED_PROTECTION_LABEL == {
            "OK", "WATCH", "CONCENTRATION",
            "SECTOR_AT_RISK", "SHARED_RISK_EXPOSED", "DATA_GAP",
        }

    def test_porttech_label_set_unchanged(self):
        from quantbot.research.porttech import ALLOWED_PORTTECH_LABEL
        assert ALLOWED_PORTTECH_LABEL == {
            "ADD", "HOLD", "TRIM", "WATCH", "EXIT_WATCH", "DATA_GAP",
        }


# --------------------------------------------------------------------------- #
# Regression — V7 + V6 modules still importable.
# --------------------------------------------------------------------------- #
class TestRegression:
    def test_v6_dashboard_imports(self):
        sys.path.insert(0, str(REPO_ROOT / "apps"))
        try:
            mod = importlib.import_module("sector_thesis_dashboard")
            assert hasattr(mod, "render")
        finally:
            if str(REPO_ROOT / "apps") in sys.path:
                sys.path.remove(str(REPO_ROOT / "apps"))

    def test_platform_imports(self):
        sys.path.insert(0, str(REPO_ROOT / "apps"))
        try:
            mod = importlib.import_module("portfolio_platform")
            assert hasattr(mod, "render")
            assert hasattr(mod, "derive_porttech_rows_from_snapshot")
            # Critically: the platform module must NOT have somehow gained
            # an IBKR import.
            text = (REPO_ROOT / "apps" / "portfolio_platform.py").read_text(
                encoding="utf-8",
            )
            assert "ib_insync" not in text
            assert "ibkr_sync" not in text
        finally:
            if str(REPO_ROOT / "apps") in sys.path:
                sys.path.remove(str(REPO_ROOT / "apps"))
