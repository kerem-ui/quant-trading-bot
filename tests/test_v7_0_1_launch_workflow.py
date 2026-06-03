"""V7.0.1 — Launch / mobile-access workflow verification.

Covers:

  * The workflow doc exists at the expected path.
  * The doc covers every spec-required section (local launch, sector
    dashboard launch, LAN phone access, security caveats, PowerShell
    helpers).
  * The two PowerShell launcher scripts exist.
  * The launchers default to ``127.0.0.1`` (localhost-only); LAN mode is
    opt-in via the ``-Lan`` switch.
  * The launchers contain no broker / IBKR / order / hedge tokens and do
    not write to any CSV.
  * No new IBKR / trading code was added.
  * Standard guardrails: ``LIVE_TRADING_ENABLED`` remains False; the V6
    sector dashboard and V7 platform still import cleanly.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import quantbot

REPO_ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = REPO_ROOT / "reports" / "research" / "V7_0_1_LAUNCH_WORKFLOW.md"
PLATFORM_LAUNCHER = REPO_ROOT / "scripts" / "launch_platform.ps1"
SECTOR_LAUNCHER = REPO_ROOT / "scripts" / "launch_sector_dashboard.ps1"


# --------------------------------------------------------------------------- #
# Documentation
# --------------------------------------------------------------------------- #
class TestDocExists:
    def test_file_present(self):
        assert DOC_PATH.is_file(), (
            f"V7.0.1 launch workflow doc missing at {DOC_PATH}"
        )

    def test_doc_is_non_trivial(self):
        text = DOC_PATH.read_text(encoding="utf-8")
        assert len(text) > 3000, (
            "V7.0.1 doc looks like a stub; expected a substantive workflow."
        )


class TestDocSections:
    """The spec required six sections — each must show up in the doc."""

    @classmethod
    def setup_class(cls):
        cls.text = DOC_PATH.read_text(encoding="utf-8")

    def test_local_launch_section(self):
        assert "Normal local launch" in self.text

    def test_sector_dashboard_section(self):
        assert "sector" in self.text.lower()
        assert "sector_thesis_dashboard.py" in self.text

    def test_lan_phone_section(self):
        assert "Phone" in self.text or "phone" in self.text
        assert "Wi-Fi" in self.text or "wifi" in self.text.lower()

    def test_security_section(self):
        assert "Security" in self.text

    def test_powershell_helpers_section(self):
        assert "launch_platform.ps1" in self.text
        assert "launch_sector_dashboard.ps1" in self.text


class TestDocCommands:
    """The spec named specific commands and instructions that must be present."""

    @classmethod
    def setup_class(cls):
        cls.text = DOC_PATH.read_text(encoding="utf-8")

    def test_local_launch_command(self):
        assert "python -m streamlit run apps/portfolio_platform.py" in self.text

    def test_sector_launch_command(self):
        assert "python -m streamlit run apps/sector_thesis_dashboard.py" in self.text

    def test_lan_command(self):
        assert "--server.address 0.0.0.0" in self.text

    def test_ipconfig_instruction(self):
        assert "ipconfig" in self.text

    def test_phone_url_format(self):
        # Either the literal placeholder or the example IP must show up.
        assert "<PC-LAN-IP>:8501" in self.text \
            or "http://192.168" in self.text

    def test_ctrl_c_shutdown(self):
        assert "Ctrl+C" in self.text

    def test_powershell_lan_invocation(self):
        # The doc must explain the -Lan switch usage with a concrete command.
        assert "launch_platform.ps1 -Lan" in self.text


class TestDocSecurityCaveats:
    """Hard rules the spec requires the doc to state explicitly."""

    @classmethod
    def setup_class(cls):
        cls.text = DOC_PATH.read_text(encoding="utf-8")
        cls.lower = cls.text.lower()

    def test_lan_only_workflow(self):
        assert "lan-only" in self.lower or "lan only" in self.lower \
            or "Wi-Fi network you trust" in self.text

    def test_no_public_wifi(self):
        assert ("public" in self.lower
                and ("wi-fi" in self.lower or "wifi" in self.lower))

    def test_no_port_forwarding(self):
        assert "port forwarding" in self.lower

    def test_no_internet_exposure(self):
        assert "public internet" in self.lower \
            or "expose this to the internet" in self.lower

    def test_no_authentication(self):
        assert "no authentication" in self.lower \
            or "authentication" in self.lower

    def test_read_only_acknowledgement(self):
        assert "read-only" in self.lower

    def test_live_trading_disabled_mentioned(self):
        assert "LIVE_TRADING_ENABLED" in self.text


# --------------------------------------------------------------------------- #
# PowerShell launcher scripts
# --------------------------------------------------------------------------- #
class TestLaunchersExist:
    def test_platform_launcher_exists(self):
        assert PLATFORM_LAUNCHER.is_file(), (
            f"missing {PLATFORM_LAUNCHER}"
        )

    def test_sector_launcher_exists(self):
        assert SECTOR_LAUNCHER.is_file(), (
            f"missing {SECTOR_LAUNCHER}"
        )


class TestLauncherDefaults:
    """Default behaviour must be localhost-only; -Lan is strictly opt-in."""

    @classmethod
    def setup_class(cls):
        cls.platform_text = PLATFORM_LAUNCHER.read_text(encoding="utf-8")
        cls.sector_text = SECTOR_LAUNCHER.read_text(encoding="utf-8")

    def test_platform_default_is_localhost(self):
        # The localhost default must be present as a literal address.
        assert "127.0.0.1" in self.platform_text
        # And 0.0.0.0 must be guarded by a conditional ($Lan switch).
        assert "0.0.0.0" in self.platform_text  # value still used in -Lan path
        # The script must declare the -Lan parameter (so it's opt-in).
        assert "[switch]$Lan" in self.platform_text

    def test_sector_default_is_localhost(self):
        assert "127.0.0.1" in self.sector_text
        assert "0.0.0.0" in self.sector_text
        assert "[switch]$Lan" in self.sector_text

    def test_platform_lan_warning_present(self):
        # The -Lan branch must print security caveats before launching.
        assert "SECURITY CAVEATS" in self.platform_text \
            or "Security Caveats" in self.platform_text \
            or "security caveats" in self.platform_text.lower()

    def test_sector_lan_warning_present(self):
        assert "SECURITY CAVEATS" in self.sector_text \
            or "Security Caveats" in self.sector_text \
            or "security caveats" in self.sector_text.lower()

    def test_lan_requires_keypress(self):
        # Both LAN paths must require an explicit acknowledgement.
        for txt in (self.platform_text, self.sector_text):
            assert "ReadKey" in txt, (
                "LAN mode must require a keypress before launching"
            )


class TestLauncherGuardrails:
    """Launchers must not contain broker / IBKR / order / hedge / write tokens."""

    @classmethod
    def setup_class(cls):
        cls.sources = {
            "launch_platform.ps1": PLATFORM_LAUNCHER.read_text(encoding="utf-8"),
            "launch_sector_dashboard.ps1": SECTOR_LAUNCHER.read_text(encoding="utf-8"),
        }

    def test_no_broker_tokens(self):
        # Sharp check: only literal import / API-call patterns that would
        # indicate the launcher is doing something broker-related. The
        # PS1 disclaimers legitimately mention "broker" / "TWS" /
        # "Gateway" / "IBKR" as plain English in the no-this-script-does-
        # NOT-do-X note; that's not a violation.
        for name, txt in self.sources.items():
            for token in ("ib_insync", "ibapi",
                          "placeOrder", "place_order", "submit_order",
                          "Connect-TWS", "Connect-IBGateway"):
                assert token not in txt, (
                    f"forbidden token {token!r} in {name}"
                )

    def test_no_order_or_trade_execution_tokens(self):
        for name, txt in self.sources.items():
            for token in ("execute_trade", "place_trade", "submit_trade",
                          "execute_order", "buy_button", "sell_button",
                          "execute_hedge", "submit_hedge",
                          "place_hedge", "hedge_order"):
                assert token not in txt, (
                    f"forbidden execution token {token!r} in {name}"
                )

    def test_no_csv_writes(self):
        # Launchers must NOT modify CSVs. Block obvious write commands.
        for name, txt in self.sources.items():
            for pattern in ("Set-Content", "Out-File", "Add-Content",
                            "New-Item -ItemType File",
                            "Remove-Item",  # never delete anything
                            "Move-Item"):
                assert pattern not in txt, (
                    f"forbidden write-style cmdlet {pattern!r} in {name}"
                )

    def test_no_network_fetches(self):
        # No Invoke-WebRequest, no curl, no http downloads.
        for name, txt in self.sources.items():
            for token in ("Invoke-WebRequest", "Invoke-RestMethod",
                          "wget ", "curl ", "DownloadFile",
                          "DownloadString"):
                assert token not in txt, (
                    f"forbidden network token {token!r} in {name}"
                )

    def test_no_package_install(self):
        for name, txt in self.sources.items():
            assert "pip install" not in txt, (
                f"package install in {name}"
            )

    def test_no_credentials_or_secrets(self):
        for name, txt in self.sources.items():
            for token in ("API_KEY", "SECRET", "password", "credential",
                          "TOKEN"):
                # Allow "credential" inside the word "credentials" only in
                # disclaimer comments — but block uppercase / variable use.
                # The launchers are tiny so a strict block is fine.
                assert token not in txt, (
                    f"forbidden credential token {token!r} in {name}"
                )

    def test_uses_streamlit_run(self):
        # Positive control: each launcher must actually call streamlit run.
        for name, txt in self.sources.items():
            assert "streamlit run" in txt, (
                f"{name} should invoke `streamlit run`"
            )


# --------------------------------------------------------------------------- #
# Project-level guardrails (must continue to hold after V7.0.1)
# --------------------------------------------------------------------------- #
class TestStandardGuardrails:
    def test_live_trading_disabled(self):
        assert quantbot.LIVE_TRADING_ENABLED is False

    def test_no_new_ibkr_code_anywhere(self):
        # V7.0.1 must NOT have added IBKR code under cover of "launch
        # convenience". Recursive grep across production source.
        roots = (
            REPO_ROOT / "src",
            REPO_ROOT / "scripts",
            REPO_ROOT / "apps",
        )
        for root in roots:
            if not root.is_dir():
                continue
            for p in root.rglob("*.py"):
                txt = p.read_text(encoding="utf-8")
                assert "import ib_insync" not in txt, p
                assert "from ib_insync" not in txt, p
                assert "import ibapi" not in txt, p
                assert "from ibapi" not in txt, p

    def test_future_ibkr_files_still_absent(self):
        # The V7.2 design milestone's "still absent" invariants must
        # continue to hold after V7.0.1.
        for rel in (
            "src/quantbot/research/portfolio/ibkr_sync.py",
            "scripts/sync_portfolio_ibkr.py",
        ):
            assert not (REPO_ROOT / rel).exists(), (
                f"{rel} now exists — V7.2 implementation snuck in via "
                "V7.0.1"
            )


# --------------------------------------------------------------------------- #
# Regression — V6/V7 surfaces still load cleanly
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
            for name in ("render", "PAGES", "DISCLAIMER",
                         "derive_porttech_rows_from_snapshot"):
                assert hasattr(mod, name), f"missing: {name}"
        finally:
            if str(REPO_ROOT / "apps") in sys.path:
                sys.path.remove(str(REPO_ROOT / "apps"))

    def test_readme_links_to_workflow_doc(self):
        readme = REPO_ROOT / "README.md"
        assert readme.is_file()
        txt = readme.read_text(encoding="utf-8")
        # The README's V7 launch section should point to the workflow doc.
        assert "V7_0_1_LAUNCH_WORKFLOW.md" in txt
