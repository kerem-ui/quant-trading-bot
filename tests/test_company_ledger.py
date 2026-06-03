"""V6.7 — Company signal ledger tests.

Covers:

  * :class:`CompanyLedgerRow` schema validation (read enum, required fields)
  * derivation logic — matches the dashboard's ``derive_company_read`` and
    ``company_view_strings`` exactly (parity test against the dashboard module)
  * MIXED rule (BULL + BROKEN coexist) and TRACKED rule (manual placeholders)
  * append-only behaviour: prior rows are never rewritten
  * idempotent mode: re-running with the same ``run_id`` is a no-op for
    already-written (run_id, sector, ticker) tuples
  * strict mode: a colliding key raises
  * append mode: collisions are written anyway
  * deterministic output: same inputs → byte-identical rows / CSV
  * missing catalyst files handled gracefully (rows still emitted as N/A)
  * the ledger is not consulted by the sector scorer
  * no broker / IBKR / order imports
  * dashboard's existing tests still pass (i.e. the ledger does not mutate
    the dashboard's public surface — sanity check via importlib)
  * the build-script ``main()`` writes a CSV the schema can re-read
  * LIVE_TRADING_ENABLED remains False
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
    COMPANY_LEDGER_UNIVERSE,
    LEDGER_FIELDS,
    Catalyst,
    CompanyLedgerRow,
    CompanyLedgerSchemaError,
    append_company_ledger_rows,
    build_company_ledger_rows,
    derive_read_for_company,
    ensure_company_ledger_header,
    load_company_ledger,
    score_sector,
    short_phrases_for_company,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- #
# fixtures + builders
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def dashboard():
    """Import the dashboard module (apps/ is not a package)."""
    sys.path.insert(0, str(REPO_ROOT / "apps"))
    try:
        mod = importlib.import_module("sector_thesis_dashboard")
    finally:
        if str(REPO_ROOT / "apps") in sys.path:
            sys.path.remove(str(REPO_ROOT / "apps"))
    return mod


@pytest.fixture(scope="module")
def build_script():
    """Import scripts/build_company_signal_ledger.py."""
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        mod = importlib.import_module("build_company_signal_ledger")
    finally:
        if str(REPO_ROOT / "scripts") in sys.path:
            sys.path.remove(str(REPO_ROOT / "scripts"))
    return mod


def _cat(*, cid: str, sector: str = "SEMICONDUCTOR", subsector: str = "X",
         tier: int = 1, status: str = "BULL",
         current_value: str = "+10%",
         source_type: str = "SEC_EDGAR",
         source_detail: str = "ok",
         last_updated: str = "2026-05-28") -> Catalyst:
    return Catalyst(
        catalyst_id=cid, sector=sector, subsector=subsector,
        catalyst_name=f"name-{cid}", tier=tier, direction="ABOVE",
        threshold="t", current_value=current_value, status=status,
        source_type=source_type, source_detail=source_detail,
        last_updated=last_updated, action_if_broken="review", notes="",
    )


_RUN_ID = "2026-05-29T00-00-00Z"
_TS = "2026-05-29T00:00:00+00:00"
_DATE = "2026-05-29"


# --------------------------------------------------------------------------- #
# Module-surface guardrails
# --------------------------------------------------------------------------- #
class TestModuleSurface:
    def test_live_trading_disabled(self):
        assert quantbot.LIVE_TRADING_ENABLED is False

    def test_no_broker_or_ibkr_in_module_source(self):
        path = REPO_ROOT / "src" / "quantbot" / "research" / \
            "sector_tracker" / "company_ledger.py"
        text = path.read_text(encoding="utf-8")
        forbidden = ("ib_insync", "place_order", "submit_order")
        for token in forbidden:
            assert token not in text, (
                f"forbidden token {token!r} present in company_ledger.py"
            )
        # The word "ibkr" appears only in disclaimers/comments. Ensure no
        # functional broker import lives in this module.
        assert "import broker" not in text
        assert "from broker" not in text

    def test_allowed_read_values(self):
        assert ALLOWED_READ == {
            "BULL", "NEUTRAL", "NEAR_THRESHOLD", "BROKEN",
            "MIXED", "TRACKED", "N/A",
        }

    def test_ledger_fields_stable(self):
        # First two fields are run_id + timestamp so newest rows are sortable.
        assert LEDGER_FIELDS[:2] == ("run_id", "timestamp")
        assert "date" in LEDGER_FIELDS
        assert "ticker" in LEDGER_FIELDS
        assert "sector" in LEDGER_FIELDS
        assert "read" in LEDGER_FIELDS
        assert "linked_catalysts" in LEDGER_FIELDS
        assert "source_files" in LEDGER_FIELDS
        assert "source_dates" in LEDGER_FIELDS
        assert "is_manual_or_tracked_context" in LEDGER_FIELDS


# --------------------------------------------------------------------------- #
# Schema validation
# --------------------------------------------------------------------------- #
class TestSchema:
    def _row(self, **over) -> dict:
        base = dict(
            run_id=_RUN_ID, timestamp=_TS, date=_DATE,
            ticker="NVDA", company_or_label="NVDA",
            sector="SEMICONDUCTOR", theme="AI accelerator",
            read="BULL", why_short="x", main_risk_short="—",
            linked_catalysts="A;B", n_linked_present=1, n_linked_total=2,
            source_files="SEC_EDGAR:ok", source_dates="2026-05-28",
            is_manual_or_tracked_context="false",
            reason="r", notes="n",
        )
        base.update(over)
        return base

    def test_valid_row_constructs(self):
        r = CompanyLedgerRow(**self._row())
        assert r.read == "BULL"
        assert r.ticker == "NVDA"

    @pytest.mark.parametrize("missing", ["run_id", "timestamp", "ticker",
                                          "sector"])
    def test_required_fields(self, missing):
        with pytest.raises(CompanyLedgerSchemaError):
            CompanyLedgerRow(**self._row(**{missing: ""}))

    def test_invalid_read_rejected(self):
        with pytest.raises(CompanyLedgerSchemaError):
            CompanyLedgerRow(**self._row(read="WAT"))

    def test_invalid_tracked_flag_rejected(self):
        with pytest.raises(CompanyLedgerSchemaError):
            CompanyLedgerRow(**self._row(is_manual_or_tracked_context="yes"))

    def test_negative_counts_rejected(self):
        with pytest.raises(CompanyLedgerSchemaError):
            CompanyLedgerRow(**self._row(n_linked_present=-1))

    def test_non_int_counts_rejected(self):
        with pytest.raises(CompanyLedgerSchemaError):
            CompanyLedgerRow(**self._row(n_linked_present="1"))  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Derivation rules (mirror the V6.5.2 dashboard logic)
# --------------------------------------------------------------------------- #
class TestDerivation:
    def test_no_catalysts_loaded_returns_na(self):
        read, _, n = derive_read_for_company({}, ["X1", "X2"])
        assert read == "N/A"
        assert n == 0

    def test_manual_neutral_only_is_tracked(self):
        m = _cat(cid="M1", status="NEUTRAL", source_type="MANUAL")
        read, reason, n = derive_read_for_company({"M1": m}, ["M1"])
        assert read == "TRACKED"
        assert n == 1
        assert "tracked context" in reason

    def test_bull_plus_broken_is_mixed_not_broken(self):
        # The V6.5.2 rule the user emphasized: do not hide bull behind one
        # shared broken risk (e.g. NVDA revenue BULL + semi inventory BROKEN).
        bull = _cat(cid="B", status="BULL", current_value="+65%")
        broken = _cat(cid="X", status="BROKEN", current_value="-30%")
        neutral = _cat(cid="N", status="NEUTRAL", current_value="+0%")
        read, reason, _ = derive_read_for_company(
            {"B": bull, "X": broken, "N": neutral}, ["B", "X", "N"]
        )
        assert read == "MIXED"
        assert "BULL" in reason
        assert "BROKEN" in reason

    def test_broken_only_is_broken(self):
        x = _cat(cid="X", status="BROKEN")
        n_ = _cat(cid="N", status="NEUTRAL")
        read, _, _ = derive_read_for_company({"X": x, "N": n_}, ["X", "N"])
        assert read == "BROKEN"

    def test_bull_plus_near_is_mixed(self):
        b = _cat(cid="B", status="BULL")
        n = _cat(cid="N", status="NEAR_THRESHOLD")
        read, _, _ = derive_read_for_company({"B": b, "N": n}, ["B", "N"])
        assert read == "MIXED"

    def test_all_bull_is_bull(self):
        b1 = _cat(cid="B1", status="BULL")
        b2 = _cat(cid="B2", status="BULL")
        read, _, _ = derive_read_for_company({"B1": b1, "B2": b2}, ["B1", "B2"])
        assert read == "BULL"

    def test_all_neutral_auto_is_neutral(self):
        # NEUTRAL from a non-MANUAL source is a real "in-band" read.
        n1 = _cat(cid="N1", status="NEUTRAL", source_type="SEC_EDGAR")
        n2 = _cat(cid="N2", status="NEUTRAL", source_type="FRED")
        read, _, _ = derive_read_for_company({"N1": n1, "N2": n2}, ["N1", "N2"])
        assert read == "NEUTRAL"

    def test_bull_plus_neutral_no_negatives_is_mixed(self):
        b = _cat(cid="B", status="BULL")
        n = _cat(cid="N", status="NEUTRAL")
        read, _, _ = derive_read_for_company({"B": b, "N": n}, ["B", "N"])
        assert read == "MIXED"

    def test_n_present_counts_only_loaded(self):
        p = _cat(cid="P", status="BULL")
        _, _, n_pres = derive_read_for_company(
            {"P": p}, ["P", "MISSING-1", "MISSING-2"]
        )
        assert n_pres == 1

    def test_short_phrases_no_catalysts(self):
        why, risk = short_phrases_for_company([])
        assert "no linked" in why
        assert risk == "—"

    def test_short_phrases_tracked(self):
        m = _cat(cid="M1", status="NEUTRAL", source_type="MANUAL")
        why, risk = short_phrases_for_company([m])
        assert "tracked context" in why
        assert risk == "—"


# --------------------------------------------------------------------------- #
# Dashboard parity — proves V6.7 derivation matches the V6.5.x Company Lens.
# --------------------------------------------------------------------------- #
class TestDashboardParity:
    def test_universe_matches_dashboard(self, dashboard):
        d_uni = dashboard.COMPANY_CATALYSTS
        # Same sectors, same ticker order, same catalyst-id lists, same themes.
        assert set(COMPANY_LEDGER_UNIVERSE) == set(d_uni)
        for sec in COMPANY_LEDGER_UNIVERSE:
            l_comps = COMPANY_LEDGER_UNIVERSE[sec]
            d_comps = d_uni[sec]
            assert len(l_comps) == len(d_comps), \
                f"company count differs for {sec}"
            for lc, dc in zip(l_comps, d_comps):
                assert lc["ticker"] == dc["ticker"]
                assert lc["theme"] == dc["subsector_theme"]
                assert lc["catalysts"] == dc["catalysts"]

    @pytest.mark.parametrize("scenario", [
        # (linked_ids, builders) -> expected dashboard agreement
        (["B", "X", "N"],
         lambda: [_cat(cid="B", status="BULL"),
                  _cat(cid="X", status="BROKEN"),
                  _cat(cid="N", status="NEUTRAL")]),
        (["X", "N"],
         lambda: [_cat(cid="X", status="BROKEN"),
                  _cat(cid="N", status="NEUTRAL")]),
        (["B1", "B2"],
         lambda: [_cat(cid="B1", status="BULL"),
                  _cat(cid="B2", status="BULL")]),
        (["M1"],
         lambda: [_cat(cid="M1", status="NEUTRAL", source_type="MANUAL")]),
        (["B", "N"],
         lambda: [_cat(cid="B", status="BULL"),
                  _cat(cid="N", status="NEAR_THRESHOLD")]),
        (["MISSING-1", "MISSING-2"], lambda: []),
    ])
    def test_derive_read_matches_dashboard(self, dashboard, scenario):
        linked, builder = scenario
        cats = builder()
        by_id = {c.catalyst_id: c for c in cats}
        l_read, _, l_n = derive_read_for_company(by_id, linked)
        d_read, _, d_n = dashboard.derive_company_read(by_id, linked)
        assert l_read == d_read
        assert l_n == d_n

    def test_short_phrases_match_dashboard(self, dashboard):
        bull = _cat(cid="SEMI-NVDA-REV-T1", status="BULL", current_value="+65%")
        broken = _cat(cid="SEMI-INVENTORY-CYCLE-T2",
                      status="BROKEN", current_value="-30%")
        l_why, l_risk = short_phrases_for_company([bull, broken])
        d_why, d_risk = dashboard.company_view_strings([bull, broken])
        assert l_why == d_why
        assert l_risk == d_risk


# --------------------------------------------------------------------------- #
# build_company_ledger_rows
# --------------------------------------------------------------------------- #
class TestBuildRows:
    def test_universe_covers_full_set(self):
        rows = build_company_ledger_rows(
            {"SEMICONDUCTOR": [], "AI": [], "ENERGY": []},
            run_id=_RUN_ID, timestamp=_TS, as_of_date=_DATE,
        )
        # 9 semi + 8 AI + 10 energy = 27 companies in the dashboard universe.
        assert len(rows) == 27
        assert all(r.read == "N/A" for r in rows)
        assert all(r.is_manual_or_tracked_context == "true" for r in rows)

    def test_missing_sector_keys_treated_as_empty(self):
        # Energy missing — should still emit those rows as N/A, not crash.
        rows = build_company_ledger_rows(
            {"SEMICONDUCTOR": [], "AI": []},
            run_id=_RUN_ID, timestamp=_TS, as_of_date=_DATE,
        )
        energy_rows = [r for r in rows if r.sector == "ENERGY"]
        assert len(energy_rows) == 10
        assert all(r.read == "N/A" for r in energy_rows)

    def test_mixed_row_for_nvda_with_inventory_break(self):
        # NVDA revenue BULL + inventory cycle BROKEN -> MIXED, surfacing both.
        cats = [
            _cat(cid="SEMI-NVDA-REV-T1", sector="SEMICONDUCTOR",
                 status="BULL", current_value="+65.5%"),
            _cat(cid="SEMI-NVDA-GM-T1", sector="SEMICONDUCTOR",
                 status="BULL", current_value="73%"),
            _cat(cid="SEMI-NVDA-DC-REV-T1", sector="SEMICONDUCTOR",
                 status="BULL", current_value="+90%"),
            _cat(cid="SEMI-INVENTORY-CYCLE-T2", sector="SEMICONDUCTOR",
                 status="BROKEN", current_value="-30%",
                 source_type="YFINANCE"),
        ]
        rows = build_company_ledger_rows(
            {"SEMICONDUCTOR": cats, "AI": [], "ENERGY": []},
            run_id=_RUN_ID, timestamp=_TS, as_of_date=_DATE,
        )
        nvda = next(r for r in rows if r.ticker == "NVDA")
        assert nvda.read == "MIXED"
        assert "BULL" in nvda.reason and "BROKEN" in nvda.reason
        assert nvda.n_linked_present == 4
        assert nvda.is_manual_or_tracked_context == "false"
        assert "SEC_EDGAR" in nvda.source_files
        assert "YFINANCE" in nvda.source_files

    def test_manual_only_company_is_tracked(self):
        # OpenAI uses a single MANUAL placeholder catalyst.
        cats = [_cat(cid="AI-OPENAI-ARR-T1", sector="AI",
                     status="NEUTRAL", source_type="MANUAL")]
        rows = build_company_ledger_rows(
            {"SEMICONDUCTOR": [], "AI": cats, "ENERGY": []},
            run_id=_RUN_ID, timestamp=_TS, as_of_date=_DATE,
        )
        openai = next(r for r in rows if r.ticker == "OpenAI")
        assert openai.read == "TRACKED"
        assert openai.is_manual_or_tracked_context == "true"

    def test_deterministic_output(self):
        # Same inputs -> identical row sequences (no time-of-day side effects).
        cats = [_cat(cid="SEMI-NVDA-REV-T1", sector="SEMICONDUCTOR",
                     status="BULL")]
        first = build_company_ledger_rows(
            {"SEMICONDUCTOR": cats, "AI": [], "ENERGY": []},
            run_id=_RUN_ID, timestamp=_TS, as_of_date=_DATE,
        )
        second = build_company_ledger_rows(
            {"SEMICONDUCTOR": cats, "AI": [], "ENERGY": []},
            run_id=_RUN_ID, timestamp=_TS, as_of_date=_DATE,
        )
        assert [r.to_dict() for r in first] == [r.to_dict() for r in second]


# --------------------------------------------------------------------------- #
# I/O — append-only, idempotent / append / strict modes
# --------------------------------------------------------------------------- #
class TestLedgerIO:
    def _build(self, run_id: str = _RUN_ID) -> list[CompanyLedgerRow]:
        return build_company_ledger_rows(
            {"SEMICONDUCTOR": [], "AI": [], "ENERGY": []},
            run_id=run_id, timestamp=_TS, as_of_date=_DATE,
        )

    def test_ensure_header_creates_file(self, tmp_path: Path):
        p = tmp_path / "ledger.csv"
        ensure_company_ledger_header(p)
        assert p.is_file()
        text = p.read_text(encoding="utf-8")
        assert "run_id" in text and "ticker" in text

    def test_load_missing_file_returns_empty_list(self, tmp_path: Path):
        assert load_company_ledger(tmp_path / "absent.csv") == []

    def test_append_writes_header_and_rows(self, tmp_path: Path):
        p = tmp_path / "ledger.csv"
        rows = self._build()
        result = append_company_ledger_rows(rows, p)
        assert result["n_appended"] == 27
        assert result["n_skipped"] == 0
        reloaded = load_company_ledger(p)
        assert len(reloaded) == 27

    def test_idempotent_same_run_id_is_noop(self, tmp_path: Path):
        p = tmp_path / "ledger.csv"
        rows = self._build()
        append_company_ledger_rows(rows, p)
        size_after_first = p.stat().st_size
        result = append_company_ledger_rows(rows, p)
        assert result["n_appended"] == 0
        assert result["n_skipped"] == 27
        # Prior rows untouched.
        assert p.stat().st_size == size_after_first

    def test_idempotent_different_run_id_appends(self, tmp_path: Path):
        p = tmp_path / "ledger.csv"
        append_company_ledger_rows(self._build(run_id="RUN-1"), p)
        result = append_company_ledger_rows(self._build(run_id="RUN-2"), p)
        assert result["n_appended"] == 27
        all_rows = load_company_ledger(p)
        run_ids = {r.run_id for r in all_rows}
        assert run_ids == {"RUN-1", "RUN-2"}

    def test_strict_mode_raises_on_collision(self, tmp_path: Path):
        p = tmp_path / "ledger.csv"
        rows = self._build()
        append_company_ledger_rows(rows, p)
        with pytest.raises(CompanyLedgerSchemaError):
            append_company_ledger_rows(rows, p, mode="strict")

    def test_append_mode_writes_duplicates(self, tmp_path: Path):
        p = tmp_path / "ledger.csv"
        rows = self._build()
        append_company_ledger_rows(rows, p)
        result = append_company_ledger_rows(rows, p, mode="append")
        assert result["n_appended"] == 27
        assert len(load_company_ledger(p)) == 54

    def test_invalid_mode_rejected(self, tmp_path: Path):
        with pytest.raises(ValueError):
            append_company_ledger_rows(
                self._build(), tmp_path / "x.csv", mode="bogus",
            )

    def test_append_only_never_rewrites_existing_bytes(self, tmp_path: Path):
        p = tmp_path / "ledger.csv"
        first_rows = self._build(run_id="RUN-1")
        append_company_ledger_rows(first_rows, p)
        original_bytes = p.read_bytes()
        # Multiple subsequent appends, mixed modes — original prefix preserved.
        append_company_ledger_rows(self._build(run_id="RUN-2"), p)
        append_company_ledger_rows(first_rows, p, mode="idempotent")
        new_bytes = p.read_bytes()
        assert new_bytes.startswith(original_bytes)


# --------------------------------------------------------------------------- #
# Build-script integration
# --------------------------------------------------------------------------- #
class TestBuildScript:
    def test_main_writes_ledger_with_no_catalyst_files(
        self, tmp_path: Path, build_script,
    ):
        # data_dir is empty -> every company emits N/A but the script still
        # produces a valid ledger CSV that round-trips.
        ddir = tmp_path / "data"
        ddir.mkdir()
        lpath = tmp_path / "company_signal_ledger.csv"
        result = build_script.main(
            data_dir=ddir, ledger_path=lpath, run_id="RUN-X",
            timestamp=_TS, as_of_date=_DATE,
        )
        assert result["n_rows_built"] == 27
        assert result["n_appended"] == 27
        assert result["n_skipped"] == 0
        assert result["n_sectors_loaded"] == 0
        rows = load_company_ledger(lpath)
        assert {r.ticker for r in rows} == {
            t for sec in COMPANY_LEDGER_UNIVERSE.values()
            for t in (c["ticker"] for c in sec)
        }
        assert all(r.read == "N/A" for r in rows)

    def test_main_is_idempotent_by_default(self, tmp_path: Path, build_script):
        ddir = tmp_path / "data"
        ddir.mkdir()
        lpath = tmp_path / "company_signal_ledger.csv"
        build_script.main(data_dir=ddir, ledger_path=lpath, run_id="RUN-1",
                          timestamp=_TS, as_of_date=_DATE)
        second = build_script.main(data_dir=ddir, ledger_path=lpath,
                                    run_id="RUN-1", timestamp=_TS,
                                    as_of_date=_DATE)
        assert second["n_appended"] == 0
        assert second["n_skipped"] == 27


# --------------------------------------------------------------------------- #
# V6.7 must NOT affect sector scoring.
# --------------------------------------------------------------------------- #
class TestNoEffectOnSectorScoring:
    def test_scorer_signature_unaware_of_ledger(self):
        # score_sector still takes only catalysts + exits + sector; building
        # the ledger does not interact with scoring at all.
        cats = [_cat(cid="SEMI-NVDA-REV-T1", sector="SEMICONDUCTOR",
                     status="BULL")]
        score_before = score_sector(cats, [], sector="SEMICONDUCTOR")
        # Build (and discard) a ledger.
        _ = build_company_ledger_rows(
            {"SEMICONDUCTOR": cats, "AI": [], "ENERGY": []},
            run_id=_RUN_ID, timestamp=_TS, as_of_date=_DATE,
        )
        score_after = score_sector(cats, [], sector="SEMICONDUCTOR")
        assert score_before.signal == score_after.signal
        assert score_before.normalized_score == score_after.normalized_score


# --------------------------------------------------------------------------- #
# Refresh-script opt-in integration
# --------------------------------------------------------------------------- #
class TestRefreshIntegration:
    @pytest.fixture
    def refresh_mod(self):
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        try:
            yield importlib.import_module("refresh_sector_trackers")
        finally:
            if str(REPO_ROOT / "scripts") in sys.path:
                sys.path.remove(str(REPO_ROOT / "scripts"))

    def test_refresh_default_does_not_write_company_ledger(
        self, tmp_path: Path, refresh_mod,
    ):
        ddir = tmp_path / "data"
        ddir.mkdir()
        rdir = tmp_path / "reports"
        rdir.mkdir()
        result = refresh_mod.main(
            data_dir=ddir, report_dir=rdir,
            change_log_path=ddir / "change_log.csv",
            annotations_path=ddir / "event_annotations.csv",
            run_id="RUN-NL", skip_driver_run=True,
        )
        assert result["company_ledger_summary"] is None
        assert not (ddir / "company_signal_ledger.csv").exists()

    def test_refresh_with_flag_writes_company_ledger(
        self, tmp_path: Path, refresh_mod,
    ):
        ddir = tmp_path / "data"
        ddir.mkdir()
        rdir = tmp_path / "reports"
        rdir.mkdir()
        lpath = ddir / "company_signal_ledger.csv"
        result = refresh_mod.main(
            data_dir=ddir, report_dir=rdir,
            change_log_path=ddir / "change_log.csv",
            annotations_path=ddir / "event_annotations.csv",
            run_id="RUN-WITH", skip_driver_run=True,
            with_company_ledger=True,
            company_ledger_path=lpath,
        )
        summary = result["company_ledger_summary"]
        assert summary is not None
        assert summary["n_rows_built"] == 27
        assert summary["n_appended"] == 27
        assert lpath.is_file()


# --------------------------------------------------------------------------- #
# Real-data smoke (uses the per-sector CSVs already committed in the repo)
# --------------------------------------------------------------------------- #
class TestRealDataSmoke:
    def test_build_from_committed_catalyst_csvs(self, tmp_path: Path,
                                                 build_script):
        # Build against the real data/research/sector_tracker/ catalyst CSVs
        # but write into tmp_path so the repo isn't mutated.
        real_data = REPO_ROOT / "data" / "research" / "sector_tracker"
        lpath = tmp_path / "ledger.csv"
        result = build_script.main(
            data_dir=real_data, ledger_path=lpath, run_id="RUN-SMOKE",
            timestamp=_TS, as_of_date=_DATE,
        )
        assert result["n_rows_built"] == 27
        rows = load_company_ledger(lpath)
        assert len(rows) == 27
        # Spec: NVDA / AMD / AVGO / MU should read MIXED (BULL revenue +
        # shared inventory cycle BROKEN). At least one of them must be MIXED
        # to confirm the rule fires against real data.
        semis = {r.ticker: r.read for r in rows if r.sector == "SEMICONDUCTOR"}
        assert any(semis.get(t) == "MIXED" for t in ("NVDA", "AMD", "AVGO",
                                                       "MU"))
