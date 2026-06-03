"""V6.8 — Company-derived sector aggregation tests.

Covers:

  * :class:`SectorAggregationRow` schema validation (required fields,
    allowed reads, count consistency).
  * :func:`derive_company_derived_read` rule priority — the worst-bucket
    rules and the "many MIXED → CAUTION not forced bullish" guarantee.
  * Top-tickers field composition (BULL / risk / tracked).
  * Full :func:`build_sector_aggregation_rows` against hand-crafted ledger
    fixtures: bull-heavy → BULL, tracked-heavy → TRACKED_HEAVY,
    broken-heavy → BROKEN, single broken with bull majority → CAUTION,
    only-N/A → N_A.
  * Append-only behaviour: prior bytes preserved across runs.
  * Idempotent mode by ``(run_id, sector)``; ``strict`` raises; ``append``
    duplicates.
  * Round-trip via :func:`load_sector_aggregation`.
  * Build-script: latest-run-by-default, ``--all-runs`` backfills, missing
    ledger is handled gracefully (exit-0 no-op), explicit ``run_id``.
  * **No effect on canonical sector scoring** — multiple aggregation builds
    leave ``score_sector`` outputs untouched.
  * Guardrails: no broker / IBKR / order tokens; ``LIVE_TRADING_ENABLED``
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
    AGGREGATION_FIELDS,
    ALLOWED_COMPANY_DERIVED_READ,
    Catalyst,
    CompanyAggregationSchemaError,
    CompanyLedgerRow,
    SectorAggregationRow,
    aggregate_sector,
    append_sector_aggregation_rows,
    build_sector_aggregation_rows,
    derive_company_derived_read,
    ensure_sector_aggregation_header,
    load_sector_aggregation,
    score_sector,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
_TS = "2026-05-29T00:00:00+00:00"
_RUN_ID = "2026-05-29T00-00-00Z"
_DATE = "2026-05-29"


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def build_script():
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        mod = importlib.import_module("build_company_sector_aggregation")
    finally:
        if str(REPO_ROOT / "scripts") in sys.path:
            sys.path.remove(str(REPO_ROOT / "scripts"))
    return mod


@pytest.fixture(scope="module")
def ledger_script():
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        mod = importlib.import_module("build_company_signal_ledger")
    finally:
        if str(REPO_ROOT / "scripts") in sys.path:
            sys.path.remove(str(REPO_ROOT / "scripts"))
    return mod


def _lrow(*, ticker: str, sector: str, read: str,
          run_id: str = _RUN_ID, timestamp: str = _TS,
          date: str = _DATE, theme: str = "x",
          is_manual: str = "false") -> CompanyLedgerRow:
    return CompanyLedgerRow(
        run_id=run_id, timestamp=timestamp, date=date,
        ticker=ticker, company_or_label=ticker,
        sector=sector, theme=theme, read=read,
        why_short="—", main_risk_short="—",
        linked_catalysts="", n_linked_present=0, n_linked_total=0,
        source_files="", source_dates="",
        is_manual_or_tracked_context=is_manual,
        reason="", notes="",
    )


def _cat(*, cid: str, sector: str = "SEMICONDUCTOR", status: str = "BULL",
         current_value: str = "+10%") -> Catalyst:
    return Catalyst(
        catalyst_id=cid, sector=sector, subsector="X",
        catalyst_name=f"name-{cid}", tier=1, direction="ABOVE",
        threshold="t", current_value=current_value, status=status,
        source_type="SEC_EDGAR", source_detail="ok",
        last_updated="2026-05-28", action_if_broken="review", notes="",
    )


# --------------------------------------------------------------------------- #
# Module surface + guardrails
# --------------------------------------------------------------------------- #
class TestSurface:
    def test_live_trading_disabled(self):
        assert quantbot.LIVE_TRADING_ENABLED is False

    def test_no_broker_or_order_tokens(self):
        for rel in (
            "src/quantbot/research/sector_tracker/company_aggregation.py",
            "scripts/build_company_sector_aggregation.py",
        ):
            path = REPO_ROOT / rel
            text = path.read_text(encoding="utf-8")
            for token in ("ib_insync", "place_order", "submit_order",
                          "ThetaData", "thetadata"):
                assert token not in text, (
                    f"forbidden token {token!r} found in {rel}"
                )

    def test_allowed_company_derived_read(self):
        assert ALLOWED_COMPANY_DERIVED_READ == {
            "BULL", "MIXED", "NEUTRAL", "CAUTION",
            "BROKEN", "TRACKED_HEAVY", "N_A",
        }

    def test_aggregation_fields_stable(self):
        # Key contract: run_id + timestamp lead the file so newest rows are
        # sortable, and the categorical read is exposed verbatim.
        assert AGGREGATION_FIELDS[:2] == ("run_id", "timestamp")
        for f in ("sector", "n_companies", "company_derived_read",
                  "top_bull_companies", "top_mixed_or_risk_companies",
                  "tracked_only_companies", "source_ledger"):
            assert f in AGGREGATION_FIELDS


# --------------------------------------------------------------------------- #
# Schema validation
# --------------------------------------------------------------------------- #
class TestSchema:
    def _row(self, **over) -> dict:
        base = dict(
            run_id=_RUN_ID, timestamp=_TS, date=_DATE,
            sector="SEMICONDUCTOR",
            n_companies=3, n_bull=2, n_mixed=0, n_neutral=0,
            n_near_threshold=0, n_broken=1, n_tracked=0, n_na=0,
            company_derived_read="CAUTION",
            top_bull_companies="NVDA;AMD",
            top_mixed_or_risk_companies="MU",
            tracked_only_companies="",
            notes="x", source_ledger="company_signal_ledger.csv",
        )
        base.update(over)
        return base

    def test_valid_row_constructs(self):
        r = SectorAggregationRow(**self._row())
        assert r.company_derived_read == "CAUTION"
        assert r.n_companies == 3

    @pytest.mark.parametrize("missing", ["run_id", "timestamp", "sector"])
    def test_required_non_empty(self, missing):
        with pytest.raises(CompanyAggregationSchemaError):
            SectorAggregationRow(**self._row(**{missing: ""}))

    def test_invalid_sector_rejected(self):
        with pytest.raises(CompanyAggregationSchemaError):
            SectorAggregationRow(**self._row(sector="WAT"))

    def test_invalid_read_rejected(self):
        with pytest.raises(CompanyAggregationSchemaError):
            SectorAggregationRow(**self._row(company_derived_read="X"))

    def test_negative_counts_rejected(self):
        with pytest.raises(CompanyAggregationSchemaError):
            SectorAggregationRow(**self._row(n_bull=-1, n_companies=2))

    def test_non_int_counts_rejected(self):
        with pytest.raises(CompanyAggregationSchemaError):
            SectorAggregationRow(**self._row(n_bull="2"))  # type: ignore[arg-type]

    def test_internal_consistency_enforced(self):
        # buckets must sum to n_companies
        with pytest.raises(CompanyAggregationSchemaError):
            SectorAggregationRow(**self._row(
                n_companies=5, n_bull=2, n_broken=1,  # sum=3, n_companies=5
            ))


# --------------------------------------------------------------------------- #
# Derivation rules
# --------------------------------------------------------------------------- #
class TestDerivation:
    def test_all_na_returns_na(self):
        assert derive_company_derived_read({"n_na": 4}) == "N_A"

    def test_empty_counts_returns_na(self):
        assert derive_company_derived_read({}) == "N_A"

    def test_all_bull_no_negatives_is_bull(self):
        assert derive_company_derived_read({"n_bull": 5}) == "BULL"

    def test_all_neutral_is_neutral(self):
        assert derive_company_derived_read({"n_neutral": 4}) == "NEUTRAL"

    def test_all_tracked_is_tracked_heavy(self):
        assert derive_company_derived_read({"n_tracked": 3}) == "TRACKED_HEAVY"

    def test_all_broken_is_broken(self):
        assert derive_company_derived_read({"n_broken": 3}) == "BROKEN"

    def test_all_mixed_is_caution(self):
        # "many MIXED -> caution" per spec.
        assert derive_company_derived_read({"n_mixed": 4}) == "CAUTION"

    def test_one_broken_in_bull_majority_is_caution(self):
        # Single BROKEN in a fleet of bulls -> CAUTION, not BROKEN.
        assert derive_company_derived_read(
            {"n_bull": 4, "n_broken": 1}
        ) == "CAUTION"

    def test_two_broken_two_bull_is_broken(self):
        # Broken ties bulls -> BROKEN (broken dominates ties).
        assert derive_company_derived_read(
            {"n_bull": 2, "n_broken": 2}
        ) == "BROKEN"

    def test_one_mixed_one_bull_is_caution(self):
        # n_neg=1 >= n_bull=1 -> CAUTION.
        assert derive_company_derived_read(
            {"n_bull": 1, "n_mixed": 1}
        ) == "CAUTION"

    def test_one_mixed_two_bull_is_mixed(self):
        # n_neg=1 < n_bull=2 -> MIXED (surface mixed, not full caution).
        assert derive_company_derived_read(
            {"n_bull": 2, "n_mixed": 1}
        ) == "MIXED"

    def test_near_threshold_treated_as_negative(self):
        assert derive_company_derived_read(
            {"n_bull": 1, "n_near_threshold": 1}
        ) == "CAUTION"

    def test_bull_with_tracked_minority_is_bull(self):
        assert derive_company_derived_read(
            {"n_bull": 3, "n_tracked": 1}
        ) == "BULL"

    def test_tracked_with_neutral_minority_is_tracked_heavy(self):
        assert derive_company_derived_read(
            {"n_tracked": 3, "n_neutral": 1}
        ) == "TRACKED_HEAVY"

    def test_na_does_not_affect_active_buckets(self):
        # The presence of N/A rows should not change a clean-bull read.
        assert derive_company_derived_read(
            {"n_bull": 3, "n_na": 10}
        ) == "BULL"


# --------------------------------------------------------------------------- #
# aggregate_sector / build_sector_aggregation_rows
# --------------------------------------------------------------------------- #
class TestAggregateSector:
    def test_bull_heavy_sector(self):
        rows = [
            _lrow(ticker="NVDA", sector="SEMICONDUCTOR", read="BULL"),
            _lrow(ticker="AMD", sector="SEMICONDUCTOR", read="BULL"),
            _lrow(ticker="AVGO", sector="SEMICONDUCTOR", read="BULL"),
        ]
        agg = aggregate_sector(
            "SEMICONDUCTOR", rows,
            run_id=_RUN_ID, timestamp=_TS, date=_DATE,
        )
        assert agg.company_derived_read == "BULL"
        assert agg.n_companies == 3
        assert agg.n_bull == 3
        assert agg.top_bull_companies == "AMD;AVGO;NVDA"

    def test_mixed_distribution_produces_caution(self):
        # 1 BROKEN + 3 MIXED + 2 BULL = n_broken=1, n_mixed=3, n_bull=2
        # Step 2: n_broken (1) < n_bull (2) -> CAUTION (broken+bull-majority)
        rows = [
            _lrow(ticker="MU", sector="SEMICONDUCTOR", read="BROKEN"),
            _lrow(ticker="NVDA", sector="SEMICONDUCTOR", read="MIXED"),
            _lrow(ticker="AMD", sector="SEMICONDUCTOR", read="MIXED"),
            _lrow(ticker="AVGO", sector="SEMICONDUCTOR", read="MIXED"),
            _lrow(ticker="TSM", sector="SEMICONDUCTOR", read="BULL"),
            _lrow(ticker="ASML", sector="SEMICONDUCTOR", read="BULL"),
        ]
        agg = aggregate_sector(
            "SEMICONDUCTOR", rows,
            run_id=_RUN_ID, timestamp=_TS, date=_DATE,
        )
        assert agg.company_derived_read == "CAUTION"
        # MU is a real BROKEN; NVDA/AMD/AVGO are risks.
        assert "MU" in agg.top_mixed_or_risk_companies
        assert "NVDA" in agg.top_mixed_or_risk_companies

    def test_tracked_heavy_sector(self):
        rows = [
            _lrow(ticker="OpenAI", sector="AI", read="TRACKED",
                  is_manual="true"),
            _lrow(ticker="Anthropic", sector="AI", read="TRACKED",
                  is_manual="true"),
            _lrow(ticker="MSFT", sector="AI", read="NEUTRAL"),
        ]
        agg = aggregate_sector(
            "AI", rows, run_id=_RUN_ID, timestamp=_TS, date=_DATE,
        )
        assert agg.company_derived_read == "TRACKED_HEAVY"
        assert agg.tracked_only_companies == "Anthropic;OpenAI"

    def test_all_na_sector(self):
        agg = aggregate_sector(
            "ENERGY", [], run_id=_RUN_ID, timestamp=_TS, date=_DATE,
        )
        assert agg.company_derived_read == "N_A"
        assert agg.n_companies == 0
        assert agg.notes  # non-empty diagnostic

    def test_broken_dominates_is_broken(self):
        rows = [
            _lrow(ticker="A", sector="SEMICONDUCTOR", read="BROKEN"),
            _lrow(ticker="B", sector="SEMICONDUCTOR", read="BROKEN"),
            _lrow(ticker="C", sector="SEMICONDUCTOR", read="BULL"),
        ]
        agg = aggregate_sector(
            "SEMICONDUCTOR", rows,
            run_id=_RUN_ID, timestamp=_TS, date=_DATE,
        )
        assert agg.company_derived_read == "BROKEN"

    def test_top_tickers_capped(self):
        # 7 bull tickers; only top 5 should be surfaced.
        rows = [
            _lrow(ticker=f"T{i}", sector="SEMICONDUCTOR", read="BULL")
            for i in range(7)
        ]
        agg = aggregate_sector(
            "SEMICONDUCTOR", rows,
            run_id=_RUN_ID, timestamp=_TS, date=_DATE,
        )
        # Sorted alphabetically; T0..T4 are the first 5.
        assert agg.top_bull_companies == "T0;T1;T2;T3;T4"

    def test_rejects_wrong_sector_in_rows(self):
        with pytest.raises(CompanyAggregationSchemaError):
            aggregate_sector(
                "SEMICONDUCTOR",
                [_lrow(ticker="X", sector="AI", read="BULL")],
                run_id=_RUN_ID, timestamp=_TS, date=_DATE,
            )

    def test_rejects_wrong_run_id_in_rows(self):
        with pytest.raises(CompanyAggregationSchemaError):
            aggregate_sector(
                "SEMICONDUCTOR",
                [_lrow(ticker="X", sector="SEMICONDUCTOR", read="BULL",
                       run_id="OTHER")],
                run_id=_RUN_ID, timestamp=_TS, date=_DATE,
            )

    def test_rejects_unknown_sector(self):
        with pytest.raises(CompanyAggregationSchemaError):
            aggregate_sector("WAT", [], run_id=_RUN_ID,
                              timestamp=_TS, date=_DATE)


class TestBuildSectorAggregationRows:
    def test_emits_one_row_per_allowed_sector(self):
        rows = [
            _lrow(ticker="NVDA", sector="SEMICONDUCTOR", read="BULL"),
            _lrow(ticker="MSFT", sector="AI", read="BULL"),
            # ENERGY intentionally missing.
        ]
        out = build_sector_aggregation_rows(rows, run_id=_RUN_ID)
        secs = {r.sector for r in out}
        assert secs == {"AI", "ENERGY", "SEMICONDUCTOR"}
        energy = next(r for r in out if r.sector == "ENERGY")
        assert energy.company_derived_read == "N_A"

    def test_empty_input_raises(self):
        with pytest.raises(CompanyAggregationSchemaError):
            build_sector_aggregation_rows([], run_id=_RUN_ID)

    def test_mixed_run_ids_rejected(self):
        rows = [
            _lrow(ticker="A", sector="SEMICONDUCTOR", read="BULL"),
            _lrow(ticker="B", sector="AI", read="BULL", run_id="OTHER"),
        ]
        with pytest.raises(CompanyAggregationSchemaError):
            build_sector_aggregation_rows(rows, run_id=_RUN_ID)

    def test_deterministic_output(self):
        rows = [
            _lrow(ticker="NVDA", sector="SEMICONDUCTOR", read="BULL"),
            _lrow(ticker="AMD", sector="SEMICONDUCTOR", read="MIXED"),
        ]
        first = build_sector_aggregation_rows(rows, run_id=_RUN_ID)
        second = build_sector_aggregation_rows(rows, run_id=_RUN_ID)
        assert [r.to_dict() for r in first] == [r.to_dict() for r in second]


# --------------------------------------------------------------------------- #
# I/O — append-only, idempotent
# --------------------------------------------------------------------------- #
class TestAggregationIO:
    def _rows(self, run_id: str = _RUN_ID) -> list[SectorAggregationRow]:
        return build_sector_aggregation_rows(
            [_lrow(ticker="NVDA", sector="SEMICONDUCTOR", read="BULL",
                   run_id=run_id)],
            run_id=run_id,
        )

    def test_ensure_header(self, tmp_path: Path):
        p = tmp_path / "agg.csv"
        ensure_sector_aggregation_header(p)
        assert p.is_file()
        with p.open("r", encoding="utf-8") as fh:
            header = next(csv.reader(fh))
        assert header == list(AGGREGATION_FIELDS)

    def test_load_missing_returns_empty(self, tmp_path: Path):
        assert load_sector_aggregation(tmp_path / "absent.csv") == []

    def test_append_then_load_round_trip(self, tmp_path: Path):
        p = tmp_path / "agg.csv"
        result = append_sector_aggregation_rows(self._rows(), p)
        assert result["n_appended"] == 3  # one row per sector
        rows = load_sector_aggregation(p)
        assert len(rows) == 3
        assert {r.sector for r in rows} == {"AI", "ENERGY", "SEMICONDUCTOR"}

    def test_idempotent_same_run_is_noop(self, tmp_path: Path):
        p = tmp_path / "agg.csv"
        rows = self._rows()
        append_sector_aggregation_rows(rows, p)
        size_first = p.stat().st_size
        result = append_sector_aggregation_rows(rows, p)
        assert result["n_appended"] == 0
        assert result["n_skipped"] == 3
        assert p.stat().st_size == size_first

    def test_idempotent_different_run_appends(self, tmp_path: Path):
        p = tmp_path / "agg.csv"
        append_sector_aggregation_rows(self._rows("RUN-1"), p)
        result = append_sector_aggregation_rows(self._rows("RUN-2"), p)
        assert result["n_appended"] == 3
        loaded = load_sector_aggregation(p)
        assert {r.run_id for r in loaded} == {"RUN-1", "RUN-2"}

    def test_strict_mode_raises(self, tmp_path: Path):
        p = tmp_path / "agg.csv"
        rows = self._rows()
        append_sector_aggregation_rows(rows, p)
        with pytest.raises(CompanyAggregationSchemaError):
            append_sector_aggregation_rows(rows, p, mode="strict")

    def test_append_mode_duplicates(self, tmp_path: Path):
        p = tmp_path / "agg.csv"
        rows = self._rows()
        append_sector_aggregation_rows(rows, p)
        result = append_sector_aggregation_rows(rows, p, mode="append")
        assert result["n_appended"] == 3
        assert len(load_sector_aggregation(p)) == 6

    def test_invalid_mode_rejected(self, tmp_path: Path):
        with pytest.raises(ValueError):
            append_sector_aggregation_rows(self._rows(),
                                             tmp_path / "x.csv", mode="bogus")

    def test_append_only_preserves_prior_bytes(self, tmp_path: Path):
        p = tmp_path / "agg.csv"
        append_sector_aggregation_rows(self._rows("RUN-1"), p)
        original = p.read_bytes()
        append_sector_aggregation_rows(self._rows("RUN-2"), p)
        append_sector_aggregation_rows(self._rows("RUN-1"), p,
                                         mode="idempotent")
        assert p.read_bytes().startswith(original)


# --------------------------------------------------------------------------- #
# Build script
# --------------------------------------------------------------------------- #
class TestBuildScript:
    def _write_ledger(self, ddir: Path, ledger_script,
                       rows_by_run: dict[str, list]):
        """Helper: write a ledger CSV containing every ``run_id`` we supply."""
        # Use the V6.7 ledger writer to be sure the file format is the real
        # one the aggregator will see in production.
        from quantbot.research.sector_tracker import (
            append_company_ledger_rows,
            ensure_company_ledger_header,
        )
        lpath = ddir / "company_signal_ledger.csv"
        ensure_company_ledger_header(lpath)
        for rid, rows in rows_by_run.items():
            append_company_ledger_rows(rows, lpath)
        return lpath

    def test_missing_ledger_is_graceful_noop(self, tmp_path: Path,
                                              build_script):
        ddir = tmp_path / "data"
        ddir.mkdir()
        apath = tmp_path / "agg.csv"
        result = build_script.main(
            data_dir=ddir, aggregation_path=apath,
        )
        assert result["ledger_missing"] is True
        assert result["n_appended"] == 0
        assert not apath.is_file()

    def test_default_aggregates_latest_run(self, tmp_path: Path,
                                            build_script, ledger_script):
        ddir = tmp_path / "data"
        ddir.mkdir()
        apath = tmp_path / "agg.csv"

        # Build a ledger with TWO runs.
        self._write_ledger(ddir, ledger_script, {
            "RUN-1": [
                _lrow(ticker="NVDA", sector="SEMICONDUCTOR", read="BULL",
                      run_id="RUN-1"),
            ],
            "RUN-2": [
                _lrow(ticker="NVDA", sector="SEMICONDUCTOR", read="BROKEN",
                      run_id="RUN-2"),
            ],
        })

        result = build_script.main(
            data_dir=ddir, aggregation_path=apath,
        )
        assert result["n_runs_processed"] == 1
        # 3 rows (one per allowed sector) for RUN-2 only.
        assert result["n_appended"] == 3
        rows = load_sector_aggregation(apath)
        assert {r.run_id for r in rows} == {"RUN-2"}
        semi = next(r for r in rows if r.sector == "SEMICONDUCTOR")
        assert semi.company_derived_read == "BROKEN"

    def test_all_runs_backfills(self, tmp_path: Path, build_script,
                                 ledger_script):
        ddir = tmp_path / "data"
        ddir.mkdir()
        apath = tmp_path / "agg.csv"
        self._write_ledger(ddir, ledger_script, {
            "RUN-1": [_lrow(ticker="NVDA", sector="SEMICONDUCTOR",
                            read="BULL", run_id="RUN-1")],
            "RUN-2": [_lrow(ticker="NVDA", sector="SEMICONDUCTOR",
                            read="BROKEN", run_id="RUN-2")],
        })
        result = build_script.main(
            data_dir=ddir, aggregation_path=apath, all_runs=True,
        )
        assert result["n_runs_processed"] == 2
        assert result["n_appended"] == 6  # 2 runs * 3 sectors

    def test_explicit_run_id(self, tmp_path: Path, build_script,
                              ledger_script):
        ddir = tmp_path / "data"
        ddir.mkdir()
        apath = tmp_path / "agg.csv"
        self._write_ledger(ddir, ledger_script, {
            "RUN-A": [_lrow(ticker="NVDA", sector="SEMICONDUCTOR",
                             read="BULL", run_id="RUN-A")],
            "RUN-B": [_lrow(ticker="NVDA", sector="SEMICONDUCTOR",
                             read="BROKEN", run_id="RUN-B")],
        })
        result = build_script.main(
            data_dir=ddir, aggregation_path=apath, run_id="RUN-A",
        )
        rows = load_sector_aggregation(apath)
        assert {r.run_id for r in rows} == {"RUN-A"}
        semi = next(r for r in rows if r.sector == "SEMICONDUCTOR")
        assert semi.company_derived_read == "BULL"

    def test_main_is_idempotent_by_default(self, tmp_path: Path,
                                            build_script, ledger_script):
        ddir = tmp_path / "data"
        ddir.mkdir()
        apath = tmp_path / "agg.csv"
        self._write_ledger(ddir, ledger_script, {
            "RUN-1": [_lrow(ticker="NVDA", sector="SEMICONDUCTOR",
                            read="BULL", run_id="RUN-1")],
        })
        first = build_script.main(data_dir=ddir, aggregation_path=apath)
        second = build_script.main(data_dir=ddir, aggregation_path=apath)
        assert first["n_appended"] == 3
        assert second["n_appended"] == 0
        assert second["n_skipped"] == 3

    def test_cli_runs_without_error(self, tmp_path: Path, build_script,
                                     ledger_script):
        ddir = tmp_path / "data"
        ddir.mkdir()
        apath = tmp_path / "agg.csv"
        self._write_ledger(ddir, ledger_script, {
            "RUN-1": [_lrow(ticker="NVDA", sector="SEMICONDUCTOR",
                            read="BULL", run_id="RUN-1")],
        })
        rc = build_script.cli([
            "--data-dir", str(ddir),
            "--aggregation", str(apath),
        ])
        assert rc == 0
        assert apath.is_file()


# --------------------------------------------------------------------------- #
# V6.8 must NOT affect canonical sector scoring.
# --------------------------------------------------------------------------- #
class TestNoEffectOnScoring:
    def test_score_sector_unchanged_after_many_aggregations(
        self, tmp_path: Path, build_script, ledger_script,
    ):
        cats = [
            _cat(cid="SEMI-NVDA-REV-T1", sector="SEMICONDUCTOR",
                 status="BULL", current_value="+65%"),
            _cat(cid="SEMI-NVDA-GM-T1", sector="SEMICONDUCTOR",
                 status="BULL", current_value="73%"),
            _cat(cid="SEMI-INVENTORY-CYCLE-T2", sector="SEMICONDUCTOR",
                 status="BROKEN", current_value="-30%"),
        ]
        before = score_sector(cats, [], sector="SEMICONDUCTOR")

        # Build many aggregations against many fake runs.
        ddir = tmp_path / "data"
        ddir.mkdir()
        apath = tmp_path / "agg.csv"
        from quantbot.research.sector_tracker import (
            append_company_ledger_rows, ensure_company_ledger_header,
        )
        lpath = ddir / "company_signal_ledger.csv"
        ensure_company_ledger_header(lpath)
        for i in range(5):
            rid = f"RUN-{i}"
            rows = [
                _lrow(ticker="NVDA", sector="SEMICONDUCTOR",
                      read="MIXED", run_id=rid),
                _lrow(ticker="MU", sector="SEMICONDUCTOR",
                      read="BROKEN", run_id=rid),
            ]
            append_company_ledger_rows(rows, lpath)
            build_script.main(data_dir=ddir, aggregation_path=apath)

        after = score_sector(cats, [], sector="SEMICONDUCTOR")
        assert before.signal == after.signal
        assert before.normalized_score == after.normalized_score
        assert before.n_broken == after.n_broken
        assert before.n_bull == after.n_bull
