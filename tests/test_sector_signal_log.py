"""V6.6.2 — Tests for the canonical sector signal log + refresh integration.

Covers:

  * :class:`SectorSignalLogRow` schema (required fields, enums, count
    consistency).
  * :func:`row_from_score` faithfully projects a :class:`SectorScore` into a
    log row (no recomputation, no inventive fields).
  * :func:`build_sector_signal_log_rows` handles missing sector payloads
    gracefully (no row emitted when no catalysts on disk).
  * Append-only I/O with the three writer modes (idempotent / append /
    strict), keyed on ``(run_id, sector)``.
  * Refresh integration: default-on writes 3 sector rows on a full refresh;
    ``--no-sector-signal-log`` (i.e. ``with_sector_signal_log=False``)
    skips. Idempotent re-runs are silent no-ops.
  * V6.9 audit detects ``sector_signal_log.csv`` once it has at least one
    data row; header-only files do NOT trip the gate.
  * Guardrails: ``score_sector`` outputs unchanged after the log is
    written; no broker / IBKR / order tokens; ``LIVE_TRADING_ENABLED``
    remains False.
"""

from __future__ import annotations

import csv
import importlib
import sys
from pathlib import Path

import pytest

import quantbot
from quantbot.research.sector_tracker import (
    SECTOR_SIGNAL_LOG_FIELDS,
    Catalyst,
    EmergencyExit,
    SectorSignalLogRow,
    SectorSignalLogSchemaError,
    append_sector_signal_log_rows,
    build_sector_signal_log_rows,
    ensure_sector_signal_log_header,
    load_sector_signal_log,
    row_from_score,
    save_catalysts,
    save_exits,
    score_sector,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
_TS = "2026-05-29T00:00:00+00:00"
_DATE = "2026-05-29"
_RUN_ID = "RUN-1"


# --------------------------------------------------------------------------- #
# fixtures + helpers
# --------------------------------------------------------------------------- #
@pytest.fixture
def refresh_mod():
    # ``yield`` keeps ``scripts/`` on sys.path for the full lifetime of each
    # test — the refresh module lazy-imports ``build_company_signal_ledger``
    # at runtime when ``with_company_ledger=True``.
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        yield importlib.import_module("refresh_sector_trackers")
    finally:
        if str(REPO_ROOT / "scripts") in sys.path:
            sys.path.remove(str(REPO_ROOT / "scripts"))


@pytest.fixture
def audit_script():
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        yield importlib.import_module("audit_ledger_history")
    finally:
        if str(REPO_ROOT / "scripts") in sys.path:
            sys.path.remove(str(REPO_ROOT / "scripts"))


def _cat(*, cid: str, sector: str, status: str = "BULL",
         tier: int = 1) -> Catalyst:
    return Catalyst(
        catalyst_id=cid, sector=sector, subsector="X",
        catalyst_name=f"name-{cid}", tier=tier, direction="ABOVE",
        threshold="t", current_value="+10%", status=status,
        source_type="SEC_EDGAR", source_detail="ok",
        last_updated="2026-05-28", action_if_broken="review", notes="",
    )


def _exit(*, eid: str, sector: str,
          status: str = "MONITORING") -> EmergencyExit:
    return EmergencyExit(
        exit_id=eid, sector=sector, scenario="scenario", trigger_condition="t",
        current_status=status, action="a", source="src",
        last_updated="2026-05-28",
    )


def _row(**over) -> dict:
    base = dict(
        run_id=_RUN_ID, timestamp=_TS, date=_DATE,
        sector="SEMICONDUCTOR", canonical_signal="SELECTIVE_BUY",
        normalized_score=0.28, raw_score=4.5, total_weight=16,
        n_catalysts=4, n_bull=3, n_neutral=0, n_near_threshold=0,
        n_broken=1, n_emergency_exits=2, n_triggered_exits=0,
        source_catalyst_file="semiconductor_thesis_tracker.csv",
        source_exit_file="semiconductor_emergency_exits.csv",
        notes="x",
    )
    base.update(over)
    return base


# --------------------------------------------------------------------------- #
# Guardrails
# --------------------------------------------------------------------------- #
class TestGuardrails:
    def test_live_trading_disabled(self):
        assert quantbot.LIVE_TRADING_ENABLED is False

    def test_no_broker_or_order_tokens(self):
        for rel in (
            "src/quantbot/research/sector_tracker/sector_signal_log.py",
            "scripts/refresh_sector_trackers.py",
        ):
            path = REPO_ROOT / rel
            text = path.read_text(encoding="utf-8")
            for token in ("ib_insync", "place_order", "submit_order"):
                assert token not in text, (
                    f"forbidden token {token!r} in {rel}"
                )

    def test_signal_log_fields_stable(self):
        assert SECTOR_SIGNAL_LOG_FIELDS[:4] == (
            "run_id", "timestamp", "date", "sector",
        )
        for f in ("canonical_signal", "normalized_score", "raw_score",
                  "total_weight", "n_catalysts", "n_bull",
                  "n_emergency_exits", "n_triggered_exits",
                  "source_catalyst_file", "source_exit_file"):
            assert f in SECTOR_SIGNAL_LOG_FIELDS


# --------------------------------------------------------------------------- #
# Schema
# --------------------------------------------------------------------------- #
class TestSchema:
    def test_valid_row_constructs(self):
        r = SectorSignalLogRow(**_row())
        assert r.canonical_signal == "SELECTIVE_BUY"
        assert r.normalized_score == pytest.approx(0.28)

    @pytest.mark.parametrize("missing", ["run_id", "timestamp", "sector"])
    def test_required_non_empty(self, missing):
        with pytest.raises(SectorSignalLogSchemaError):
            SectorSignalLogRow(**_row(**{missing: ""}))

    def test_invalid_sector_rejected(self):
        with pytest.raises(SectorSignalLogSchemaError):
            SectorSignalLogRow(**_row(sector="WAT"))

    def test_invalid_canonical_signal_rejected(self):
        with pytest.raises(SectorSignalLogSchemaError):
            SectorSignalLogRow(**_row(canonical_signal="LOL"))

    def test_non_float_score_rejected(self):
        with pytest.raises(SectorSignalLogSchemaError):
            SectorSignalLogRow(**_row(normalized_score="0.28"))  # type: ignore[arg-type]

    def test_negative_counts_rejected(self):
        with pytest.raises(SectorSignalLogSchemaError):
            SectorSignalLogRow(**_row(n_bull=-1))

    def test_internal_consistency_enforced(self):
        # status counts must sum to n_catalysts
        with pytest.raises(SectorSignalLogSchemaError):
            SectorSignalLogRow(**_row(n_catalysts=5,
                                       n_bull=2, n_broken=1))


# --------------------------------------------------------------------------- #
# row_from_score + build_sector_signal_log_rows
# --------------------------------------------------------------------------- #
class TestRowConstruction:
    def test_row_from_score_copies_fields_verbatim(self):
        cats = [
            _cat(cid="A", sector="SEMICONDUCTOR", status="BULL"),
            _cat(cid="B", sector="SEMICONDUCTOR", status="BULL"),
            _cat(cid="C", sector="SEMICONDUCTOR", status="BROKEN"),
        ]
        score = score_sector(cats, [], sector="SEMICONDUCTOR")
        r = row_from_score(
            score,
            run_id=_RUN_ID, timestamp=_TS, date=_DATE,
            n_emergency_exits=2, n_triggered_exits=0,
        )
        assert r.sector == score.sector
        assert r.canonical_signal == score.signal
        assert r.normalized_score == pytest.approx(score.normalized_score)
        assert r.raw_score == pytest.approx(score.raw_score)
        assert r.total_weight == score.total_weight
        assert r.n_bull == score.n_bull == 2
        assert r.n_broken == score.n_broken == 1
        assert r.n_catalysts == score.n_total == 3

    def test_build_skips_sectors_without_catalysts(self):
        payloads = {
            "SEMICONDUCTOR": {
                "catalysts": [_cat(cid="A", sector="SEMICONDUCTOR",
                                   status="BULL")],
                "exits": [], "catalyst_file": "semi.csv",
                "exit_file": "semi_exit.csv",
            },
            "AI": {"catalysts": [], "exits": [],
                   "catalyst_file": "ai.csv", "exit_file": ""},
            "ENERGY": None,
        }
        rows = build_sector_signal_log_rows(
            payloads, run_id=_RUN_ID, timestamp=_TS, date=_DATE,
        )
        assert {r.sector for r in rows} == {"SEMICONDUCTOR"}

    def test_build_includes_triggered_exit_counts(self):
        payloads = {
            "SEMICONDUCTOR": {
                "catalysts": [_cat(cid="A", sector="SEMICONDUCTOR",
                                   status="BULL")],
                "exits": [
                    _exit(eid="E1", sector="SEMICONDUCTOR",
                          status="TRIGGERED"),
                    _exit(eid="E2", sector="SEMICONDUCTOR",
                          status="MONITORING"),
                ],
                "catalyst_file": "x.csv", "exit_file": "y.csv",
            },
        }
        rows = build_sector_signal_log_rows(
            payloads, run_id=_RUN_ID, timestamp=_TS, date=_DATE,
        )
        assert rows[0].n_emergency_exits == 2
        assert rows[0].n_triggered_exits == 1
        # A triggered exit forces canonical signal to EXIT_WATCH.
        assert rows[0].canonical_signal == "EXIT_WATCH"


# --------------------------------------------------------------------------- #
# I/O — append-only with idempotent / append / strict modes
# --------------------------------------------------------------------------- #
class TestSignalLogIO:
    def _row(self, **over) -> SectorSignalLogRow:
        return SectorSignalLogRow(**_row(**over))

    def test_ensure_header(self, tmp_path: Path):
        p = tmp_path / "log.csv"
        ensure_sector_signal_log_header(p)
        assert p.is_file()
        with p.open("r", encoding="utf-8") as fh:
            header = next(csv.reader(fh))
        assert header == list(SECTOR_SIGNAL_LOG_FIELDS)

    def test_load_missing_returns_empty(self, tmp_path: Path):
        assert load_sector_signal_log(tmp_path / "absent.csv") == []

    def test_append_round_trip(self, tmp_path: Path):
        p = tmp_path / "log.csv"
        r1 = self._row()
        r2 = self._row(sector="AI", canonical_signal="HOLD")
        result = append_sector_signal_log_rows([r1, r2], p)
        assert result["n_appended"] == 2
        rows = load_sector_signal_log(p)
        assert len(rows) == 2
        assert {r.sector for r in rows} == {"SEMICONDUCTOR", "AI"}

    def test_idempotent_same_keys_noop(self, tmp_path: Path):
        p = tmp_path / "log.csv"
        rows = [self._row(), self._row(sector="AI",
                                       canonical_signal="HOLD")]
        append_sector_signal_log_rows(rows, p)
        first_size = p.stat().st_size
        result = append_sector_signal_log_rows(rows, p)
        assert result["n_appended"] == 0
        assert result["n_skipped"] == 2
        assert p.stat().st_size == first_size

    def test_strict_mode_raises(self, tmp_path: Path):
        p = tmp_path / "log.csv"
        rows = [self._row()]
        append_sector_signal_log_rows(rows, p)
        with pytest.raises(SectorSignalLogSchemaError):
            append_sector_signal_log_rows(rows, p, mode="strict")

    def test_append_mode_duplicates(self, tmp_path: Path):
        p = tmp_path / "log.csv"
        rows = [self._row()]
        append_sector_signal_log_rows(rows, p)
        result = append_sector_signal_log_rows(rows, p, mode="append")
        assert result["n_appended"] == 1
        assert len(load_sector_signal_log(p)) == 2

    def test_invalid_mode_rejected(self, tmp_path: Path):
        with pytest.raises(ValueError):
            append_sector_signal_log_rows([self._row()],
                                           tmp_path / "x.csv", mode="bogus")

    def test_append_only_preserves_prior_bytes(self, tmp_path: Path):
        p = tmp_path / "log.csv"
        append_sector_signal_log_rows([self._row(run_id="RUN-1")], p)
        original = p.read_bytes()
        append_sector_signal_log_rows([self._row(run_id="RUN-2")], p)
        append_sector_signal_log_rows([self._row(run_id="RUN-1")], p,
                                       mode="idempotent")
        assert p.read_bytes().startswith(original)


# --------------------------------------------------------------------------- #
# Refresh integration — default-on; --no flag opts out; idempotent re-runs
# --------------------------------------------------------------------------- #
def _seed_sector_csvs(ddir: Path):
    """Write a tiny set of catalyst + exit CSVs for each of the three sectors.

    Lets us drive ``refresh.main(skip_driver_run=True)`` against a known
    state — the signal log should land 3 rows regardless of driver behaviour.
    """
    fixtures = {
        "SEMICONDUCTOR": (
            "semiconductor_thesis_tracker.csv",
            "semiconductor_emergency_exits.csv",
            [_cat(cid="SEMI-A", sector="SEMICONDUCTOR", status="BULL"),
             _cat(cid="SEMI-B", sector="SEMICONDUCTOR", status="BROKEN")],
            [_exit(eid="SEMI-EX-1", sector="SEMICONDUCTOR")],
        ),
        "AI": (
            "ai_thesis_tracker.csv",
            "ai_emergency_exits.csv",
            [_cat(cid="AI-A", sector="AI", status="BULL"),
             _cat(cid="AI-B", sector="AI", status="NEUTRAL")],
            [_exit(eid="AI-EX-1", sector="AI")],
        ),
        "ENERGY": (
            "energy_thesis_tracker.csv",
            "energy_emergency_exits.csv",
            [_cat(cid="ENER-A", sector="ENERGY", status="NEUTRAL")],
            [],
        ),
    }
    for cat_name, exit_name, cats, exits in fixtures.values():
        save_catalysts(cats, ddir / cat_name)
        save_exits(exits, ddir / exit_name)


class TestRefreshIntegration:
    def test_default_on_writes_three_rows(self, tmp_path: Path,
                                            refresh_mod):
        ddir = tmp_path / "data"
        ddir.mkdir()
        rdir = tmp_path / "reports"
        rdir.mkdir()
        _seed_sector_csvs(ddir)
        slpath = ddir / "sector_signal_log.csv"

        result = refresh_mod.main(
            data_dir=ddir, report_dir=rdir,
            change_log_path=ddir / "change_log.csv",
            annotations_path=ddir / "event_annotations.csv",
            run_id="RUN-SL-1", skip_driver_run=True,
            sector_signal_log_path=slpath,
        )
        summary = result["sector_signal_log_summary"]
        assert summary is not None
        assert summary["n_rows_built"] == 3
        assert summary["n_appended"] == 3
        rows = load_sector_signal_log(slpath)
        assert {r.sector for r in rows} == {"SEMICONDUCTOR", "AI", "ENERGY"}

    def test_no_flag_skips(self, tmp_path: Path, refresh_mod):
        ddir = tmp_path / "data"
        ddir.mkdir()
        rdir = tmp_path / "reports"
        rdir.mkdir()
        _seed_sector_csvs(ddir)
        slpath = ddir / "sector_signal_log.csv"

        result = refresh_mod.main(
            data_dir=ddir, report_dir=rdir,
            change_log_path=ddir / "change_log.csv",
            annotations_path=ddir / "event_annotations.csv",
            run_id="RUN-SL-NO", skip_driver_run=True,
            with_sector_signal_log=False,
            sector_signal_log_path=slpath,
        )
        assert result["sector_signal_log_summary"] is None
        assert not slpath.is_file()

    def test_idempotent_rerun_noop(self, tmp_path: Path, refresh_mod):
        ddir = tmp_path / "data"
        ddir.mkdir()
        rdir = tmp_path / "reports"
        rdir.mkdir()
        _seed_sector_csvs(ddir)
        slpath = ddir / "sector_signal_log.csv"
        first = refresh_mod.main(
            data_dir=ddir, report_dir=rdir,
            change_log_path=ddir / "change_log.csv",
            annotations_path=ddir / "event_annotations.csv",
            run_id="RUN-SAME", skip_driver_run=True,
            sector_signal_log_path=slpath,
        )
        second = refresh_mod.main(
            data_dir=ddir, report_dir=rdir,
            change_log_path=ddir / "change_log.csv",
            annotations_path=ddir / "event_annotations.csv",
            run_id="RUN-SAME", skip_driver_run=True,
            sector_signal_log_path=slpath,
        )
        assert first["sector_signal_log_summary"]["n_appended"] == 3
        assert second["sector_signal_log_summary"]["n_appended"] == 0
        assert second["sector_signal_log_summary"]["n_skipped"] == 3

    def test_independent_of_company_ledger_flag(self, tmp_path: Path,
                                                  refresh_mod):
        # Turning company-ledger on does not affect signal-log behaviour.
        ddir = tmp_path / "data"
        ddir.mkdir()
        rdir = tmp_path / "reports"
        rdir.mkdir()
        _seed_sector_csvs(ddir)
        slpath = ddir / "sector_signal_log.csv"
        clpath = ddir / "company_signal_ledger.csv"
        result = refresh_mod.main(
            data_dir=ddir, report_dir=rdir,
            change_log_path=ddir / "change_log.csv",
            annotations_path=ddir / "event_annotations.csv",
            run_id="RUN-BOTH", skip_driver_run=True,
            with_company_ledger=True,
            company_ledger_path=clpath,
            sector_signal_log_path=slpath,
        )
        assert result["sector_signal_log_summary"]["n_appended"] == 3
        assert result["company_ledger_summary"]["n_appended"] >= 0
        assert slpath.is_file()


# --------------------------------------------------------------------------- #
# Audit detection
# --------------------------------------------------------------------------- #
class TestAuditDetection:
    def test_missing_log_not_detected(self, tmp_path: Path, audit_script):
        ddir = tmp_path / "data"
        ddir.mkdir()
        assert audit_script._detect_canonical_signal_log(ddir) is False

    def test_header_only_log_not_detected(self, tmp_path: Path, audit_script):
        ddir = tmp_path / "data"
        ddir.mkdir()
        ensure_sector_signal_log_header(ddir / "sector_signal_log.csv")
        assert audit_script._detect_canonical_signal_log(ddir) is False

    def test_log_with_one_data_row_detected(self, tmp_path: Path,
                                              audit_script):
        ddir = tmp_path / "data"
        ddir.mkdir()
        p = ddir / "sector_signal_log.csv"
        append_sector_signal_log_rows(
            [SectorSignalLogRow(**_row())], p,
        )
        assert audit_script._detect_canonical_signal_log(ddir) is True

    def test_audit_resolves_canonical_blocker(self, tmp_path: Path,
                                                audit_script):
        # End-to-end: an audit against a tmp dir that has a populated signal
        # log should NOT carry the canonical-signal-history blocker.
        ddir = tmp_path / "data"
        ddir.mkdir()
        rdir = tmp_path / "reports"
        rdir.mkdir()
        p = ddir / "sector_signal_log.csv"
        append_sector_signal_log_rows(
            [SectorSignalLogRow(**_row())], p,
        )
        result = audit_script.main(data_dir=ddir, report_dir=rdir)
        # has_canonical_signal_history is now True; the substrate-gap
        # blocker line should not appear in the report.
        assert result["has_canonical_signal_history"] is True
        text = (rdir / "V6_9_LEDGER_AUDIT.md").read_text(encoding="utf-8")
        assert "no historical canonical-sector-signal log" not in text


# --------------------------------------------------------------------------- #
# Canonical scoring untouched
# --------------------------------------------------------------------------- #
class TestNoEffectOnScoring:
    def test_score_sector_unchanged_after_logging(self, tmp_path: Path,
                                                    refresh_mod):
        ddir = tmp_path / "data"
        ddir.mkdir()
        rdir = tmp_path / "reports"
        rdir.mkdir()
        _seed_sector_csvs(ddir)

        # Load the seeded catalysts and score them BEFORE any refresh run.
        from quantbot.research.sector_tracker import load_catalysts
        cats = load_catalysts(ddir / "semiconductor_thesis_tracker.csv")
        before = score_sector(cats, [], sector="SEMICONDUCTOR")

        slpath = ddir / "sector_signal_log.csv"
        for i in range(3):
            refresh_mod.main(
                data_dir=ddir, report_dir=rdir,
                change_log_path=ddir / "change_log.csv",
                annotations_path=ddir / "event_annotations.csv",
                run_id=f"RUN-{i}", skip_driver_run=True,
                sector_signal_log_path=slpath,
            )

        after_cats = load_catalysts(ddir / "semiconductor_thesis_tracker.csv")
        after = score_sector(after_cats, [], sector="SEMICONDUCTOR")
        assert before.signal == after.signal
        assert before.normalized_score == after.normalized_score
        assert before.raw_score == after.raw_score
