"""V6.9 — Tests for the ledger / aggregation substrate audit.

Covers:

  * :class:`LedgerAuditSummary` schema + round-trip.
  * Per-sector helpers: read distribution, ticker counts, run counts.
  * Go/no-go evaluator: thresholds applied correctly; missing canonical log
    surfaces a blocker.
  * Empty-input tolerance: both lists empty -> NO-GO with explicit blockers,
    not a crash.
  * Markdown rendering is deterministic and contains the required sections.
  * Build-script entry point writes a report and never touches the network.
  * Guardrails: no broker / IBKR / order tokens; ``LIVE_TRADING_ENABLED``
    remains False.
  * Audit does not affect canonical ``score_sector`` outputs.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

import quantbot
from quantbot.research.sector_tracker import (
    MIN_AGG_RUNS_FOR_BACKTEST,
    MIN_CALENDAR_DAYS_FOR_BACKTEST,
    MIN_RUNS_PER_SECTOR_FOR_BACKTEST,
    Catalyst,
    CompanyLedgerRow,
    LedgerAuditSchemaError,
    LedgerAuditSummary,
    SectorAggregationRow,
    audit_ledger_substrate,
    render_audit_markdown,
    score_sector,
)
from quantbot.research.sector_tracker.ledger_audit import _evaluate_go_no_go

REPO_ROOT = Path(__file__).resolve().parents[1]
_TS = "2026-05-29T00:00:00+00:00"
_DATE = "2026-05-29"


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def audit_script():
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        mod = importlib.import_module("audit_ledger_history")
    finally:
        if str(REPO_ROOT / "scripts") in sys.path:
            sys.path.remove(str(REPO_ROOT / "scripts"))
    return mod


def _lrow(*, ticker: str, sector: str, read: str = "BULL",
          run_id: str = "RUN-1", date: str = _DATE,
          timestamp: str = _TS,
          is_manual: str = "false") -> CompanyLedgerRow:
    return CompanyLedgerRow(
        run_id=run_id, timestamp=timestamp, date=date,
        ticker=ticker, company_or_label=ticker,
        sector=sector, theme="x", read=read,
        why_short="—", main_risk_short="—",
        linked_catalysts="", n_linked_present=0, n_linked_total=0,
        source_files="", source_dates="",
        is_manual_or_tracked_context=is_manual,
        reason="", notes="",
    )


def _arow(*, sector: str, read: str = "CAUTION",
          run_id: str = "RUN-1") -> SectorAggregationRow:
    return SectorAggregationRow(
        run_id=run_id, timestamp=_TS, date=_DATE,
        sector=sector,
        n_companies=1, n_bull=0, n_mixed=0, n_neutral=0,
        n_near_threshold=0, n_broken=1, n_tracked=0, n_na=0,
        company_derived_read=read,
        top_bull_companies="", top_mixed_or_risk_companies="X",
        tracked_only_companies="",
        notes="x", source_ledger="company_signal_ledger.csv",
    )


def _cat(*, cid: str, sector: str = "SEMICONDUCTOR",
         status: str = "BULL") -> Catalyst:
    return Catalyst(
        catalyst_id=cid, sector=sector, subsector="X",
        catalyst_name=f"name-{cid}", tier=1, direction="ABOVE",
        threshold="t", current_value="+10%", status=status,
        source_type="SEC_EDGAR", source_detail="ok",
        last_updated="2026-05-28", action_if_broken="review", notes="",
    )


# --------------------------------------------------------------------------- #
# Guardrails
# --------------------------------------------------------------------------- #
class TestGuardrails:
    def test_live_trading_disabled(self):
        assert quantbot.LIVE_TRADING_ENABLED is False

    def test_no_broker_or_order_tokens(self):
        for rel in (
            "src/quantbot/research/sector_tracker/ledger_audit.py",
            "scripts/audit_ledger_history.py",
        ):
            path = REPO_ROOT / rel
            text = path.read_text(encoding="utf-8")
            for token in ("ib_insync", "place_order", "submit_order",
                          "ThetaData", "thetadata"):
                assert token not in text, (
                    f"forbidden token {token!r} in {rel}"
                )

    def test_thresholds_are_conservative_constants(self):
        # Sanity: thresholds must be positive integers so the planning doc's
        # go/no-go gate is non-trivial.
        for v in (MIN_RUNS_PER_SECTOR_FOR_BACKTEST,
                  MIN_AGG_RUNS_FOR_BACKTEST,
                  MIN_CALENDAR_DAYS_FOR_BACKTEST):
            assert isinstance(v, int) and v > 0


# --------------------------------------------------------------------------- #
# audit_ledger_substrate — happy path + edge cases
# --------------------------------------------------------------------------- #
class TestAudit:
    def test_empty_inputs_yield_no_go(self):
        s = audit_ledger_substrate([], [])
        assert s.n_ledger_rows == 0
        assert s.n_distinct_runs == 0
        assert s.backtest_viable is False
        # Must report the canonical-log blocker AND the count blockers.
        assert any("canonical-sector-signal" in b
                   for b in s.backtest_blockers)
        assert any("distinct ledger run_id" in b
                   for b in s.backtest_blockers)

    def test_counts_distinct_runs_and_dates(self):
        ledger = [
            _lrow(ticker="NVDA", sector="SEMICONDUCTOR", run_id="R1",
                   date="2026-05-01"),
            _lrow(ticker="AMD", sector="SEMICONDUCTOR", run_id="R1",
                   date="2026-05-01"),
            _lrow(ticker="NVDA", sector="SEMICONDUCTOR", run_id="R2",
                   date="2026-05-02"),
            _lrow(ticker="MSFT", sector="AI", run_id="R2",
                   date="2026-05-02"),
        ]
        s = audit_ledger_substrate(ledger, [])
        assert s.n_ledger_rows == 4
        assert s.n_distinct_runs == 2
        assert s.n_distinct_dates == 2
        assert s.earliest_run_id == "R1"
        assert s.latest_run_id == "R2"
        assert s.earliest_date == "2026-05-01"
        assert s.latest_date == "2026-05-02"
        assert s.per_sector_run_counts == {"SEMICONDUCTOR": 2, "AI": 1}
        assert s.per_sector_ticker_counts == {"SEMICONDUCTOR": 2, "AI": 1}

    def test_per_sector_read_distribution(self):
        ledger = [
            _lrow(ticker="NVDA", sector="SEMICONDUCTOR", read="BULL"),
            _lrow(ticker="AMD", sector="SEMICONDUCTOR", read="MIXED"),
            _lrow(ticker="MU", sector="SEMICONDUCTOR", read="BROKEN"),
            _lrow(ticker="MSFT", sector="AI", read="BULL"),
        ]
        s = audit_ledger_substrate(ledger, [])
        assert s.per_sector_read_distribution == {
            "SEMICONDUCTOR": {"BULL": 1, "MIXED": 1, "BROKEN": 1},
            "AI": {"BULL": 1},
        }

    def test_aggregation_side_counted(self):
        agg = [
            _arow(sector="SEMICONDUCTOR", read="CAUTION", run_id="R1"),
            _arow(sector="AI", read="BULL", run_id="R1"),
            _arow(sector="SEMICONDUCTOR", read="BROKEN", run_id="R2"),
        ]
        s = audit_ledger_substrate([], agg)
        assert s.n_aggregation_rows == 3
        assert s.n_distinct_agg_runs == 2
        assert s.per_sector_agg_run_counts == {
            "SEMICONDUCTOR": 2, "AI": 1,
        }
        assert s.per_sector_company_derived_distribution == {
            "SEMICONDUCTOR": {"CAUTION": 1, "BROKEN": 1},
            "AI": {"BULL": 1},
        }

    def test_corrupted_read_raises(self):
        with pytest.raises(LedgerAuditSchemaError):
            # Bypass dataclass validation to feed an explicitly bad read.
            bad = _lrow(ticker="X", sector="AI")
            object.__setattr__(bad, "read", "WAT")
            audit_ledger_substrate([bad], [])

    def test_summary_round_trips_via_to_dict(self):
        s = audit_ledger_substrate([], [])
        d = s.to_dict()
        # The dict carries enough to reconstruct a summary with the same
        # categorical answer (verdict + blocker list).
        re_summary = LedgerAuditSummary(**d)
        assert re_summary.backtest_viable == s.backtest_viable
        assert re_summary.backtest_blockers == s.backtest_blockers
        assert re_summary.notes == s.notes


# --------------------------------------------------------------------------- #
# Go/no-go evaluator
# --------------------------------------------------------------------------- #
class TestGoNoGo:
    def test_all_blockers_when_empty(self):
        viable, blockers = _evaluate_go_no_go(
            n_distinct_runs=0, n_distinct_dates=0,
            per_sector_run_counts={}, n_distinct_agg_runs=0,
            has_canonical_signal_history=False,
        )
        assert viable is False
        # Expect at least the three count blockers + canonical-log blocker.
        assert len(blockers) >= 4

    def test_viable_when_thresholds_met_and_canonical_log_present(self):
        runs = MIN_AGG_RUNS_FOR_BACKTEST
        days = MIN_CALENDAR_DAYS_FOR_BACKTEST
        per_sec = {s: MIN_RUNS_PER_SECTOR_FOR_BACKTEST
                   for s in ("SEMICONDUCTOR", "AI", "ENERGY")}
        viable, blockers = _evaluate_go_no_go(
            n_distinct_runs=runs, n_distinct_dates=days,
            per_sector_run_counts=per_sec, n_distinct_agg_runs=runs,
            has_canonical_signal_history=True,
        )
        assert viable is True
        assert blockers == []

    def test_canonical_log_alone_blocks(self):
        runs = MIN_AGG_RUNS_FOR_BACKTEST
        days = MIN_CALENDAR_DAYS_FOR_BACKTEST
        per_sec = {s: MIN_RUNS_PER_SECTOR_FOR_BACKTEST
                   for s in ("SEMICONDUCTOR", "AI", "ENERGY")}
        viable, blockers = _evaluate_go_no_go(
            n_distinct_runs=runs, n_distinct_dates=days,
            per_sector_run_counts=per_sec, n_distinct_agg_runs=runs,
            has_canonical_signal_history=False,
        )
        assert viable is False
        assert any("canonical-sector-signal" in b for b in blockers)

    def test_one_sector_below_threshold_blocks(self):
        runs = MIN_AGG_RUNS_FOR_BACKTEST
        per_sec = {"SEMICONDUCTOR": MIN_RUNS_PER_SECTOR_FOR_BACKTEST,
                   "AI": MIN_RUNS_PER_SECTOR_FOR_BACKTEST,
                   "ENERGY": MIN_RUNS_PER_SECTOR_FOR_BACKTEST - 1}
        viable, blockers = _evaluate_go_no_go(
            n_distinct_runs=runs,
            n_distinct_dates=MIN_CALENDAR_DAYS_FOR_BACKTEST,
            per_sector_run_counts=per_sec, n_distinct_agg_runs=runs,
            has_canonical_signal_history=True,
        )
        assert viable is False
        assert any("ENERGY=" in b for b in blockers)


# --------------------------------------------------------------------------- #
# Markdown rendering
# --------------------------------------------------------------------------- #
class TestRender:
    def test_markdown_contains_required_sections(self):
        s = audit_ledger_substrate([], [])
        md = render_audit_markdown(s)
        for section in (
            "# V6.9 — Ledger / aggregation substrate audit",
            "## Headline counts",
            "## Per-sector ledger run counts",
            "## Per-sector ledger read distribution",
            "## Per-sector aggregation run counts",
            "## Substrate gaps",
            "## Backtest go/no-go blockers",
            "LIVE_TRADING_ENABLED = False",
        ):
            assert section in md, f"missing section: {section}"

    def test_no_go_verdict_in_empty_case(self):
        md = render_audit_markdown(audit_ledger_substrate([], []))
        assert "NO-GO" in md
        assert "GO" in md  # the constant string appears either way

    def test_render_is_deterministic(self):
        # Same input -> byte-identical output (goldens-style).
        s = audit_ledger_substrate([
            _lrow(ticker="NVDA", sector="SEMICONDUCTOR", read="BULL"),
            _lrow(ticker="MSFT", sector="AI", read="MIXED"),
        ], [
            _arow(sector="SEMICONDUCTOR", read="BULL"),
        ])
        a = render_audit_markdown(s)
        b = render_audit_markdown(s)
        assert a == b


# --------------------------------------------------------------------------- #
# Build-script entry point
# --------------------------------------------------------------------------- #
class TestAuditScript:
    def test_main_writes_report_when_csvs_missing(self, tmp_path: Path,
                                                    audit_script):
        ddir = tmp_path / "data"
        ddir.mkdir()
        rdir = tmp_path / "reports"
        rdir.mkdir()
        result = audit_script.main(data_dir=ddir, report_dir=rdir)
        rpath = rdir / "V6_9_LEDGER_AUDIT.md"
        assert rpath.is_file()
        assert result["backtest_viable"] is False
        # Report should mention the GO/NO-GO verdict.
        assert "NO-GO" in rpath.read_text(encoding="utf-8")

    def test_main_against_real_data(self, tmp_path: Path, audit_script):
        # Use the real committed CSVs but write the report into tmp_path so
        # the repo file isn't disturbed by this test.
        real_data = REPO_ROOT / "data" / "research" / "sector_tracker"
        rdir = tmp_path / "reports"
        rdir.mkdir()
        result = audit_script.main(data_dir=real_data, report_dir=rdir)
        rpath = rdir / "V6_9_LEDGER_AUDIT.md"
        assert rpath.is_file()
        # Today we know the real ledger has just one run -> NO-GO.
        assert result["backtest_viable"] is False
        # Report should mention the substrate-gap blocker prominently.
        text = rpath.read_text(encoding="utf-8")
        assert "canonical-sector-signal" in text

    def test_canonical_log_detector_returns_false_by_default(
        self, tmp_path: Path, audit_script,
    ):
        ddir = tmp_path / "data"
        ddir.mkdir()
        assert audit_script._detect_canonical_signal_log(ddir) is False

    def test_canonical_log_detector_returns_true_when_present(
        self, tmp_path: Path, audit_script,
    ):
        # V6.6.2 detector requires at least one real data row past the header
        # (header alone does NOT trip the gate). Use the real signal-log
        # writer so the detector and the schema stay in sync.
        from quantbot.research.sector_tracker import (
            SectorSignalLogRow,
            append_sector_signal_log_rows,
        )
        ddir = tmp_path / "data"
        ddir.mkdir()
        row = SectorSignalLogRow(
            run_id="RUN-X", timestamp=_TS, date=_DATE,
            sector="SEMICONDUCTOR", canonical_signal="HOLD",
            normalized_score=0.0, raw_score=0.0, total_weight=0,
            n_catalysts=0, n_bull=0, n_neutral=0,
            n_near_threshold=0, n_broken=0,
            n_emergency_exits=0, n_triggered_exits=0,
        )
        append_sector_signal_log_rows(
            [row], ddir / "sector_signal_log.csv",
        )
        assert audit_script._detect_canonical_signal_log(ddir) is True

    def test_canonical_log_detector_rejects_header_only(
        self, tmp_path: Path, audit_script,
    ):
        # New V6.6.2 tightening: header-only file does NOT count as
        # substrate. The blocker stays surfaced until a real row lands.
        from quantbot.research.sector_tracker import (
            ensure_sector_signal_log_header,
        )
        ddir = tmp_path / "data"
        ddir.mkdir()
        ensure_sector_signal_log_header(ddir / "sector_signal_log.csv")
        assert audit_script._detect_canonical_signal_log(ddir) is False

    def test_cli_returns_zero(self, tmp_path: Path, audit_script):
        ddir = tmp_path / "data"
        ddir.mkdir()
        rdir = tmp_path / "reports"
        rdir.mkdir()
        rc = audit_script.cli([
            "--data-dir", str(ddir),
            "--report-dir", str(rdir),
        ])
        assert rc == 0


# --------------------------------------------------------------------------- #
# V6.9 must NOT affect canonical sector scoring.
# --------------------------------------------------------------------------- #
class TestNoEffectOnScoring:
    def test_score_sector_unchanged_after_audit(self, tmp_path: Path,
                                                  audit_script):
        cats = [
            _cat(cid="SEMI-NVDA-REV-T1", sector="SEMICONDUCTOR",
                 status="BULL"),
            _cat(cid="SEMI-INVENTORY-CYCLE-T2", sector="SEMICONDUCTOR",
                 status="BROKEN"),
        ]
        before = score_sector(cats, [], sector="SEMICONDUCTOR")

        ddir = tmp_path / "data"
        ddir.mkdir()
        rdir = tmp_path / "reports"
        rdir.mkdir()
        # Run the audit multiple times — must not perturb scoring.
        for _ in range(5):
            audit_script.main(data_dir=ddir, report_dir=rdir)

        after = score_sector(cats, [], sector="SEMICONDUCTOR")
        assert before.signal == after.signal
        assert before.normalized_score == after.normalized_score
