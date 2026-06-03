"""V6.6.1 — Tests for the operator event-annotation helper.

Covers:

  * The new ``append_event_annotations`` writer (append-only).
  * The ``COMPANY_SIGNAL`` related_type added in V6.6.1.
  * The ``add_event_annotation`` Python entry point — required-field
    validation (related_id / title / note / source non-empty), enum checks,
    default UTC timestamp.
  * The ``cli`` entry point — argparse round-trip, choices, non-zero exit
    on validation failure.
  * Append-only guarantee: prior bytes are preserved across multiple
    appends; header is created on the first run.
  * No-effect-on-scoring guarantee: writing many annotations does not change
    ``score_sector`` outputs.
  * Company ledger reads are not affected by annotations.
  * Guardrails: ``LIVE_TRADING_ENABLED`` stays False; the new script source
    contains no forbidden broker / order tokens.
"""

from __future__ import annotations

import csv
import importlib
import sys
from pathlib import Path

import pytest

import quantbot
from quantbot.research.sector_tracker import (
    ALLOWED_READ,
    Catalyst,
    ChangeLogSchemaError,
    EVENT_ANNOTATION_FIELDS,
    EventAnnotation,
    append_event_annotations,
    build_company_ledger_rows,
    ensure_event_annotations_header,
    load_event_annotations,
    score_sector,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def helper():
    """Import scripts/add_event_annotation.py (scripts/ is not a package)."""
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        mod = importlib.import_module("add_event_annotation")
    finally:
        if str(REPO_ROOT / "scripts") in sys.path:
            sys.path.remove(str(REPO_ROOT / "scripts"))
    return mod


def _cat(*, cid: str, sector: str = "SEMICONDUCTOR", status: str = "BULL",
         current_value: str = "+10%",
         source_type: str = "SEC_EDGAR") -> Catalyst:
    return Catalyst(
        catalyst_id=cid, sector=sector, subsector="X",
        catalyst_name=f"name-{cid}", tier=1, direction="ABOVE",
        threshold="t", current_value=current_value, status=status,
        source_type=source_type, source_detail="ok",
        last_updated="2026-05-28", action_if_broken="review", notes="",
    )


_TS = "2026-05-29T00:00:00+00:00"
_RUN_ID = "2026-05-29T00-00-00Z"
_DATE = "2026-05-29"


# --------------------------------------------------------------------------- #
# Module surface + guardrails
# --------------------------------------------------------------------------- #
class TestSurface:
    def test_live_trading_disabled(self):
        assert quantbot.LIVE_TRADING_ENABLED is False

    def test_no_broker_or_order_tokens_in_helper(self):
        path = REPO_ROOT / "scripts" / "add_event_annotation.py"
        text = path.read_text(encoding="utf-8")
        forbidden = ("ib_insync", "place_order", "submit_order",
                     "ThetaData", "thetadata")
        for token in forbidden:
            assert token not in text, (
                f"forbidden token {token!r} appears in add_event_annotation.py"
            )

    def test_company_signal_now_allowed(self):
        # COMPANY_SIGNAL must be accepted by the V6.6 dataclass after the
        # V6.6.1 schema extension.
        a = EventAnnotation(
            timestamp=_TS, sector="SEMICONDUCTOR", related_id="NVDA",
            related_type="COMPANY_SIGNAL", ticker="NVDA",
            event_type="EARNINGS", title="t", note="n", source="s",
            source_url_or_file="", added_by="", confidence="",
        )
        assert a.related_type == "COMPANY_SIGNAL"


# --------------------------------------------------------------------------- #
# append_event_annotations writer
# --------------------------------------------------------------------------- #
class TestAppender:
    def _annotation(self, **over) -> EventAnnotation:
        base = dict(
            timestamp=_TS, sector="AI", related_id="AI-MSFT-REV-T1",
            related_type="CATALYST", ticker="MSFT",
            event_type="SEC_FILING", title="t", note="n", source="s",
            source_url_or_file="u", added_by="op", confidence="HIGH",
        )
        base.update(over)
        return EventAnnotation(**base)

    def test_creates_file_with_header_when_missing(self, tmp_path: Path):
        p = tmp_path / "ann.csv"
        n = append_event_annotations([self._annotation()], p)
        assert n == 1
        assert p.is_file()
        with p.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.reader(fh)
            header = next(reader)
        assert header == list(EVENT_ANNOTATION_FIELDS)

    def test_subsequent_appends_do_not_duplicate_header(self, tmp_path: Path):
        p = tmp_path / "ann.csv"
        ensure_event_annotations_header(p)
        append_event_annotations([self._annotation()], p)
        append_event_annotations([self._annotation(related_id="X2")], p)
        with p.open("r", encoding="utf-8", newline="") as fh:
            lines = list(csv.reader(fh))
        # 1 header + 2 data rows.
        assert len(lines) == 3
        assert lines[0] == list(EVENT_ANNOTATION_FIELDS)

    def test_append_only_preserves_prior_bytes(self, tmp_path: Path):
        p = tmp_path / "ann.csv"
        append_event_annotations([self._annotation()], p)
        original = p.read_bytes()
        append_event_annotations([self._annotation(related_id="X2")], p)
        append_event_annotations([self._annotation(related_id="X3")], p)
        assert p.read_bytes().startswith(original)

    def test_roundtrips_via_load(self, tmp_path: Path):
        p = tmp_path / "ann.csv"
        append_event_annotations([
            self._annotation(),
            self._annotation(related_id="X2", related_type="COMPANY_SIGNAL",
                             ticker="NVDA", event_type="EARNINGS"),
        ], p)
        rows = load_event_annotations(p)
        assert len(rows) == 2
        assert rows[1].related_type == "COMPANY_SIGNAL"


# --------------------------------------------------------------------------- #
# add_event_annotation (Python entry point)
# --------------------------------------------------------------------------- #
class TestAddEventAnnotation:
    def _kwargs(self, **over) -> dict:
        base = dict(
            sector="AI", related_id="AI-MSFT-REV-T1",
            related_type="CATALYST", ticker="MSFT",
            event_type="SEC_FILING",
            title="Q3 FY26 10-Q filed",
            note="Azure +30% YoY; cloud capex guide raised.",
            source="SEC_EDGAR",
            source_url_or_file="edgar:0001234-26-000045",
            added_by="kerem", confidence="HIGH",
            timestamp=_TS,
        )
        base.update(over)
        return base

    def test_happy_path_catalyst(self, tmp_path: Path, helper):
        p = tmp_path / "ann.csv"
        result = helper.add_event_annotation(
            annotations_path=p, **self._kwargs(),
        )
        assert result["n_appended"] == 1
        rows = load_event_annotations(p)
        assert len(rows) == 1
        assert rows[0].related_id == "AI-MSFT-REV-T1"
        assert rows[0].related_type == "CATALYST"

    def test_happy_path_company_signal(self, tmp_path: Path, helper):
        p = tmp_path / "ann.csv"
        result = helper.add_event_annotation(
            annotations_path=p,
            **self._kwargs(
                sector="SEMICONDUCTOR", related_id="NVDA",
                related_type="COMPANY_SIGNAL", ticker="NVDA",
                event_type="EARNINGS",
                title="FY27Q1 print",
                note="DC revenue +110% YoY; inventory days +18%.",
                source="PRESS_RELEASE",
                source_url_or_file="https://investor.nvidia.com/2026-05-29",
                confidence="MEDIUM",
            ),
        )
        assert result["n_appended"] == 1
        rows = load_event_annotations(p)
        assert rows[0].related_type == "COMPANY_SIGNAL"
        assert rows[0].ticker == "NVDA"

    def test_default_timestamp_is_iso(self, tmp_path: Path, helper):
        p = tmp_path / "ann.csv"
        kw = self._kwargs()
        kw.pop("timestamp")
        result = helper.add_event_annotation(annotations_path=p, **kw)
        # ISO timestamps with "+00:00" tz are valid and parseable.
        from datetime import datetime
        ts = result["timestamp"]
        assert ts.endswith("+00:00")
        # Round-trip parse.
        datetime.fromisoformat(ts)

    @pytest.mark.parametrize("blank_field", ["related_id", "title", "note",
                                              "source"])
    def test_required_non_empty_fields(self, tmp_path: Path, helper,
                                        blank_field):
        p = tmp_path / "ann.csv"
        kw = self._kwargs(**{blank_field: ""})
        with pytest.raises(helper.AnnotationValidationError):
            helper.add_event_annotation(annotations_path=p, **kw)
        # No CSV bytes should have been written on rejection.
        assert not p.is_file() or p.stat().st_size == 0

    def test_whitespace_only_source_rejected(self, tmp_path: Path, helper):
        p = tmp_path / "ann.csv"
        with pytest.raises(helper.AnnotationValidationError):
            helper.add_event_annotation(
                annotations_path=p, **self._kwargs(source="   "),
            )

    @pytest.mark.parametrize("bad_field,bad_value", [
        ("sector", "NOPE"),
        ("related_type", "WAT"),
        ("event_type", "TWEET"),
        ("confidence", "VERY"),
    ])
    def test_enum_violations_rejected(self, tmp_path: Path, helper,
                                       bad_field, bad_value):
        p = tmp_path / "ann.csv"
        with pytest.raises(helper.AnnotationValidationError):
            helper.add_event_annotation(
                annotations_path=p,
                **self._kwargs(**{bad_field: bad_value}),
            )

    def test_blank_sector_allowed(self, tmp_path: Path, helper):
        # Operator may leave sector blank (e.g. cross-sector macro note).
        p = tmp_path / "ann.csv"
        result = helper.add_event_annotation(
            annotations_path=p,
            **self._kwargs(sector="", related_type="SECTOR",
                           related_id="AI-MACRO"),
        )
        assert result["n_appended"] == 1


# --------------------------------------------------------------------------- #
# cli (argparse) round-trip
# --------------------------------------------------------------------------- #
class TestCLI:
    def _argv(self, p: Path, **over) -> list[str]:
        base = {
            "--sector": "AI",
            "--related-id": "AI-MSFT-REV-T1",
            "--related-type": "CATALYST",
            "--ticker": "MSFT",
            "--event-type": "SEC_FILING",
            "--title": "Q3 FY26 10-Q filed",
            "--note": "Azure +30% YoY; cloud capex guide raised.",
            "--source": "SEC_EDGAR",
            "--source-url-or-file": "edgar:0001234-26-000045",
            "--added-by": "kerem",
            "--confidence": "HIGH",
            "--timestamp": _TS,
            "--annotations": str(p),
        }
        base.update(over)
        flat: list[str] = []
        for k, v in base.items():
            flat += [k, v]
        return flat

    def test_cli_appends_row(self, tmp_path: Path, helper):
        p = tmp_path / "ann.csv"
        rc = helper.cli(self._argv(p))
        assert rc == 0
        assert len(load_event_annotations(p)) == 1

    def test_cli_company_signal_round_trip(self, tmp_path: Path, helper):
        p = tmp_path / "ann.csv"
        rc = helper.cli(self._argv(
            p,
            **{
                "--sector": "SEMICONDUCTOR",
                "--related-id": "NVDA",
                "--related-type": "COMPANY_SIGNAL",
                "--event-type": "EARNINGS",
                "--ticker": "NVDA",
                "--source": "PRESS_RELEASE",
            },
        ))
        assert rc == 0
        rows = load_event_annotations(p)
        assert rows[0].related_type == "COMPANY_SIGNAL"

    def test_cli_rejects_empty_title_with_nonzero_exit(self, tmp_path: Path,
                                                       helper, capsys):
        p = tmp_path / "ann.csv"
        rc = helper.cli(self._argv(p, **{"--title": ""}))
        assert rc == 2
        captured = capsys.readouterr()
        assert "annotation rejected" in captured.err

    def test_cli_argparse_rejects_unknown_related_type(self, tmp_path: Path,
                                                       helper):
        p = tmp_path / "ann.csv"
        with pytest.raises(SystemExit):
            helper.cli(self._argv(p, **{"--related-type": "WAT"}))


# --------------------------------------------------------------------------- #
# Annotations are context only — must not affect scoring or company ledger.
# --------------------------------------------------------------------------- #
class TestNoEffectOnScoring:
    def test_sector_score_unchanged_after_many_annotations(
        self, tmp_path: Path, helper,
    ):
        cats = [
            _cat(cid="SEMI-NVDA-REV-T1", status="BULL", current_value="+65%"),
            _cat(cid="SEMI-NVDA-GM-T1", status="BULL", current_value="73%"),
            _cat(cid="SEMI-INVENTORY-CYCLE-T2", status="BROKEN",
                 current_value="-30%"),
        ]
        before = score_sector(cats, [], sector="SEMICONDUCTOR")

        p = tmp_path / "ann.csv"
        for i in range(10):
            helper.add_event_annotation(
                annotations_path=p,
                sector="SEMICONDUCTOR",
                related_id="SEMI-NVDA-REV-T1",
                related_type="CATALYST",
                ticker="NVDA",
                event_type="EARNINGS",
                title=f"note {i}",
                note=f"context note number {i}",
                source="MANUAL",
                source_url_or_file="",
                added_by="op",
                confidence="LOW",
                timestamp=_TS,
            )

        after = score_sector(cats, [], sector="SEMICONDUCTOR")
        assert before.signal == after.signal
        assert before.normalized_score == after.normalized_score
        assert before.n_broken == after.n_broken
        assert before.n_bull == after.n_bull

    def test_company_ledger_rows_unchanged_after_annotations(
        self, tmp_path: Path, helper,
    ):
        cats_by_sec = {
            "SEMICONDUCTOR": [
                _cat(cid="SEMI-NVDA-REV-T1", status="BULL",
                     current_value="+65%"),
                _cat(cid="SEMI-INVENTORY-CYCLE-T2", status="BROKEN",
                     current_value="-30%"),
            ],
            "AI": [],
            "ENERGY": [],
        }
        before = build_company_ledger_rows(
            cats_by_sec, run_id=_RUN_ID, timestamp=_TS, as_of_date=_DATE,
        )

        p = tmp_path / "ann.csv"
        helper.add_event_annotation(
            annotations_path=p,
            sector="SEMICONDUCTOR", related_id="NVDA",
            related_type="COMPANY_SIGNAL", ticker="NVDA",
            event_type="EARNINGS", title="t", note="n", source="s",
            source_url_or_file="", added_by="op", confidence="",
            timestamp=_TS,
        )

        after = build_company_ledger_rows(
            cats_by_sec, run_id=_RUN_ID, timestamp=_TS, as_of_date=_DATE,
        )
        assert [r.to_dict() for r in before] == [r.to_dict() for r in after]
        # Sanity: the company-ledger reads are still derived purely from
        # catalyst statuses; the read enum hasn't been polluted.
        for r in after:
            assert r.read in ALLOWED_READ


# --------------------------------------------------------------------------- #
# Smoke: ChangeLogSchemaError surfaces if a schema-illegal value is supplied
# AFTER passing CLI checks (defence-in-depth — the dataclass re-validates).
# --------------------------------------------------------------------------- #
class TestDefenceInDepth:
    def test_dataclass_revalidates(self, tmp_path: Path, helper,
                                    monkeypatch):
        # Bypass the CLI-level enum check by patching it out, then prove the
        # underlying dataclass still rejects the bad value.
        monkeypatch.setattr(
            helper, "ALLOWED_RELATED_TYPE",
            frozenset(helper.ALLOWED_RELATED_TYPE | {"WAT"}),
        )
        p = tmp_path / "ann.csv"
        with pytest.raises(ChangeLogSchemaError):
            helper.add_event_annotation(
                annotations_path=p,
                sector="AI", related_id="X", related_type="WAT",
                ticker="", event_type="OTHER",
                title="t", note="n", source="s",
                source_url_or_file="", added_by="", confidence="",
                timestamp=_TS,
            )
