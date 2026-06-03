"""V6.8.1 — Tests for the collapsed company-derived sector roll-up wiring.

Covers:

  * :func:`load_latest_aggregation_per_sector` — returns the latest
    ``run_id`` per sector, handles a missing file as an empty dict, never
    writes anything.
  * :func:`aggregation_divergence` — the categorical comparison helper
    (aligned / more cautious / more bullish / N/A branches).
  * :func:`build_aggregation_roll_up_rows` — composes one row per
    :data:`SECTORS` entry, graceful when canonical or aggregation data is
    missing.
  * The dashboard remains read-only: importing the module and exercising
    every pure helper writes nothing to disk and touches no network.
  * Canonical sector scoring is unaffected by every V6.8.1 helper call.
  * Guardrails: no broker / IBKR / order / ThetaData tokens in any new
    code; ``LIVE_TRADING_ENABLED`` remains False.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

import quantbot
from quantbot.research.sector_tracker import (
    Catalyst,
    SectorAggregationRow,
    aggregate_sector,
    append_sector_aggregation_rows,
    build_sector_aggregation_rows,
    ensure_sector_aggregation_header,
    load_latest_aggregation_per_sector,
    score_sector,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
_TS = "2026-05-29T00:00:00+00:00"
_DATE = "2026-05-29"


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def dashboard():
    sys.path.insert(0, str(REPO_ROOT / "apps"))
    try:
        mod = importlib.import_module("sector_thesis_dashboard")
    finally:
        if str(REPO_ROOT / "apps") in sys.path:
            sys.path.remove(str(REPO_ROOT / "apps"))
    return mod


def _cat(*, cid: str, sector: str, status: str = "BULL",
         current_value: str = "+10%") -> Catalyst:
    return Catalyst(
        catalyst_id=cid, sector=sector, subsector="X",
        catalyst_name=f"name-{cid}", tier=1, direction="ABOVE",
        threshold="t", current_value=current_value, status=status,
        source_type="SEC_EDGAR", source_detail="ok",
        last_updated="2026-05-28", action_if_broken="review", notes="",
    )


def _agg_row(*, sector: str, read: str = "CAUTION",
             run_id: str = "RUN-1",
             n_companies: int = 4, n_bull: int = 2, n_mixed: int = 1,
             n_broken: int = 1, n_neutral: int = 0,
             n_near_threshold: int = 0, n_tracked: int = 0,
             n_na: int = 0, top_bull: str = "NVDA;AMD",
             top_risk: str = "MU", tracked_only: str = "",
             notes: str = "x") -> SectorAggregationRow:
    return SectorAggregationRow(
        run_id=run_id, timestamp=_TS, date=_DATE, sector=sector,
        n_companies=n_companies, n_bull=n_bull, n_mixed=n_mixed,
        n_neutral=n_neutral, n_near_threshold=n_near_threshold,
        n_broken=n_broken, n_tracked=n_tracked, n_na=n_na,
        company_derived_read=read,
        top_bull_companies=top_bull,
        top_mixed_or_risk_companies=top_risk,
        tracked_only_companies=tracked_only,
        notes=notes, source_ledger="company_signal_ledger.csv",
    )


# --------------------------------------------------------------------------- #
# Guardrails
# --------------------------------------------------------------------------- #
class TestGuardrails:
    def test_live_trading_disabled(self):
        assert quantbot.LIVE_TRADING_ENABLED is False

    def test_no_broker_or_order_tokens_in_v681_additions(self):
        # Re-check the dashboard file overall — V6.8.1 added lines must not
        # introduce any broker / order / ThetaData token.
        path = REPO_ROOT / "apps" / "sector_thesis_dashboard.py"
        text = path.read_text(encoding="utf-8")
        for token in ("ib_insync", "place_order", "submit_order",
                      "ThetaData", "thetadata"):
            assert token not in text, (
                f"forbidden token {token!r} now present in dashboard"
            )

    def test_v681_helpers_exposed(self, dashboard):
        for name in ("aggregation_divergence",
                     "build_aggregation_roll_up_rows",
                     "AggregationRollUpRow",
                     "DIVERGENCE_ALIGNED",
                     "DIVERGENCE_MORE_CAUTIOUS",
                     "DIVERGENCE_MORE_BULLISH",
                     "DIVERGENCE_NA_AGG",
                     "DIVERGENCE_NA_CANONICAL",
                     "DEFAULT_AGGREGATION_PATH"):
            assert hasattr(dashboard, name), f"missing helper: {name}"

    def test_v681_marker_text_uses_warn_glyph(self, dashboard):
        # Spec mandates the ⚠ glyph on the cautious / bullish markers.
        warn = chr(0x26A0)  # ⚠
        assert dashboard.DIVERGENCE_MORE_CAUTIOUS.startswith(warn)
        assert dashboard.DIVERGENCE_MORE_BULLISH.startswith(warn)
        assert dashboard.DIVERGENCE_ALIGNED == "aligned"


# --------------------------------------------------------------------------- #
# load_latest_aggregation_per_sector
# --------------------------------------------------------------------------- #
class TestLoadLatestAggregationPerSector:
    def test_missing_file_returns_empty_dict(self, tmp_path: Path):
        assert load_latest_aggregation_per_sector(tmp_path / "nope.csv") == {}

    def test_empty_file_returns_empty_dict(self, tmp_path: Path):
        p = tmp_path / "agg.csv"
        ensure_sector_aggregation_header(p)
        assert load_latest_aggregation_per_sector(p) == {}

    def test_returns_latest_run_per_sector(self, tmp_path: Path):
        p = tmp_path / "agg.csv"
        # Two runs, ordered by chronological run_id.
        for rid, read in (("2026-05-28T00-00-00Z", "BULL"),
                          ("2026-05-29T00-00-00Z", "CAUTION")):
            agg_row = aggregate_sector(
                "SEMICONDUCTOR",
                [],  # empty rows -> N_A read; we override read below by
                       # constructing the row directly instead.
                run_id=rid, timestamp=_TS, date=_DATE,
            )
            # Replace with a row that captures the read we want for the test.
            overridden = SectorAggregationRow(
                run_id=rid, timestamp=_TS, date=_DATE,
                sector="SEMICONDUCTOR",
                n_companies=1, n_bull=(1 if read == "BULL" else 0),
                n_mixed=0, n_neutral=0, n_near_threshold=0,
                n_broken=(1 if read == "CAUTION" else 0),
                n_tracked=0, n_na=0,
                company_derived_read=read,
                top_bull_companies="NVDA" if read == "BULL" else "",
                top_mixed_or_risk_companies="MU" if read == "CAUTION" else "",
                tracked_only_companies="",
                notes="", source_ledger="",
            )
            append_sector_aggregation_rows([overridden], p)
            del agg_row  # unused, but keeps the construction obvious

        latest = load_latest_aggregation_per_sector(p)
        assert set(latest) == {"SEMICONDUCTOR"}
        assert latest["SEMICONDUCTOR"].run_id == "2026-05-29T00-00-00Z"
        assert latest["SEMICONDUCTOR"].company_derived_read == "CAUTION"

    def test_latest_per_sector_independent(self, tmp_path: Path):
        # Two sectors with different latest runs — each surfaces its own
        # newest row.
        p = tmp_path / "agg.csv"
        rows = [
            _agg_row(sector="AI", read="BULL", run_id="2026-05-28T00-00-00Z"),
            _agg_row(sector="AI", read="CAUTION",
                     run_id="2026-05-29T00-00-00Z"),
            _agg_row(sector="SEMICONDUCTOR", read="MIXED",
                     run_id="2026-05-27T00-00-00Z"),
        ]
        append_sector_aggregation_rows(rows, p)
        latest = load_latest_aggregation_per_sector(p)
        assert latest["AI"].run_id == "2026-05-29T00-00-00Z"
        assert latest["AI"].company_derived_read == "CAUTION"
        assert latest["SEMICONDUCTOR"].company_derived_read == "MIXED"

    def test_load_helper_never_writes(self, tmp_path: Path):
        p = tmp_path / "agg.csv"
        assert load_latest_aggregation_per_sector(p) == {}
        # The helper must not create the file when the file does not exist.
        assert not p.exists()


# --------------------------------------------------------------------------- #
# aggregation_divergence — categorical comparison
# --------------------------------------------------------------------------- #
class TestAggregationDivergence:
    def test_selective_buy_vs_caution_is_more_cautious(self, dashboard):
        # The user's headline example from V6.8.1 spec.
        assert dashboard.aggregation_divergence(
            "SELECTIVE_BUY", "CAUTION",
        ) == dashboard.DIVERGENCE_MORE_CAUTIOUS

    def test_hold_vs_neutral_is_aligned(self, dashboard):
        assert dashboard.aggregation_divergence(
            "HOLD", "NEUTRAL",
        ) == dashboard.DIVERGENCE_ALIGNED

    def test_accumulate_vs_bull_is_aligned(self, dashboard):
        assert dashboard.aggregation_divergence(
            "ACCUMULATE", "BULL",
        ) == dashboard.DIVERGENCE_ALIGNED

    def test_hold_vs_bull_is_more_bullish(self, dashboard):
        assert dashboard.aggregation_divergence(
            "HOLD", "BULL",
        ) == dashboard.DIVERGENCE_MORE_BULLISH

    def test_reduce_vs_broken_is_aligned(self, dashboard):
        assert dashboard.aggregation_divergence(
            "REDUCE", "BROKEN",
        ) == dashboard.DIVERGENCE_ALIGNED

    def test_exit_watch_vs_bull_is_more_bullish(self, dashboard):
        assert dashboard.aggregation_divergence(
            "EXIT_WATCH", "BULL",
        ) == dashboard.DIVERGENCE_MORE_BULLISH

    def test_selective_buy_vs_mixed_is_aligned(self, dashboard):
        # diff = 1 - 0 = 1 → aligned (mixed is treated as neutral-sentiment).
        assert dashboard.aggregation_divergence(
            "SELECTIVE_BUY", "MIXED",
        ) == dashboard.DIVERGENCE_ALIGNED

    def test_selective_buy_vs_broken_is_more_cautious(self, dashboard):
        assert dashboard.aggregation_divergence(
            "SELECTIVE_BUY", "BROKEN",
        ) == dashboard.DIVERGENCE_MORE_CAUTIOUS

    def test_tracked_heavy_treated_as_neutral_sentiment(self, dashboard):
        assert dashboard.aggregation_divergence(
            "HOLD", "TRACKED_HEAVY",
        ) == dashboard.DIVERGENCE_ALIGNED

    def test_none_canonical_returns_na_canonical(self, dashboard):
        assert dashboard.aggregation_divergence(
            None, "BULL",
        ) == dashboard.DIVERGENCE_NA_CANONICAL

    def test_none_company_returns_na_agg(self, dashboard):
        assert dashboard.aggregation_divergence(
            "HOLD", None,
        ) == dashboard.DIVERGENCE_NA_AGG

    def test_n_a_company_returns_na_agg(self, dashboard):
        assert dashboard.aggregation_divergence(
            "HOLD", "N_A",
        ) == dashboard.DIVERGENCE_NA_AGG

    def test_unknown_label_defaults_to_na_agg(self, dashboard):
        # Defensive: unknown labels never crash the render.
        assert dashboard.aggregation_divergence(
            "WAT", "BULL",
        ) == dashboard.DIVERGENCE_NA_AGG
        assert dashboard.aggregation_divergence(
            "HOLD", "WAT",
        ) == dashboard.DIVERGENCE_NA_AGG


# --------------------------------------------------------------------------- #
# build_aggregation_roll_up_rows
# --------------------------------------------------------------------------- #
class TestBuildAggregationRollUpRows:
    def test_full_three_sector_roll_up(self, dashboard):
        # Build sectors_data the same way the dashboard does — by hand.
        # Each sector gets a SectorData with a real SectorScore.
        from quantbot.research.sector_tracker import score_sector as _score

        SD = dashboard.SectorData
        semi_cats = [_cat(cid="SEMI-A", sector="SEMICONDUCTOR", status="BULL")]
        semi_sd = SD(sector="SEMICONDUCTOR", catalysts=semi_cats, exits=[],
                     score=_score(semi_cats, [], sector="SEMICONDUCTOR"),
                     missing_files=[])
        ai_cats = [_cat(cid="AI-A", sector="AI", status="BULL")]
        ai_sd = SD(sector="AI", catalysts=ai_cats, exits=[],
                   score=_score(ai_cats, [], sector="AI"),
                   missing_files=[])
        # ENERGY: no canonical data at all.
        energy_sd = SD(sector="ENERGY", catalysts=[], exits=[],
                       score=None, missing_files=["missing.csv"])

        sectors_data = {"SEMICONDUCTOR": semi_sd, "AI": ai_sd,
                        "ENERGY": energy_sd}
        aggregations = {
            "SEMICONDUCTOR": _agg_row(sector="SEMICONDUCTOR", read="CAUTION"),
            "AI": _agg_row(sector="AI", read="BULL",
                            n_companies=2, n_bull=2, n_mixed=0,
                            n_broken=0, top_bull="MSFT;META", top_risk=""),
            # ENERGY missing from aggregations.
        }
        rows = dashboard.build_aggregation_roll_up_rows(sectors_data,
                                                          aggregations)
        assert [r.sector for r in rows] == list(dashboard.SECTORS)
        rows_by_sector = {r.sector: r for r in rows}

        semi = rows_by_sector["SEMICONDUCTOR"]
        assert semi.company_derived_read == "CAUTION"
        assert "BULL" in semi.top_bull_companies or semi.top_bull_companies

        ai_row = rows_by_sector["AI"]
        assert ai_row.company_derived_read == "BULL"

        energy_row = rows_by_sector["ENERGY"]
        # Canonical missing AND aggregation missing — both branches exercised.
        assert energy_row.canonical_signal == "N/A"
        assert energy_row.canonical_score == "n/a"
        assert energy_row.company_derived_read == "N/A"
        assert energy_row.divergence == dashboard.DIVERGENCE_NA_CANONICAL

    def test_aggregation_only_missing(self, dashboard):
        SD = dashboard.SectorData
        from quantbot.research.sector_tracker import score_sector as _score
        cats = [_cat(cid="SEMI-A", sector="SEMICONDUCTOR", status="BULL")]
        sd = SD(sector="SEMICONDUCTOR", catalysts=cats, exits=[],
                score=_score(cats, [], sector="SEMICONDUCTOR"),
                missing_files=[])
        rows = dashboard.build_aggregation_roll_up_rows(
            {"SEMICONDUCTOR": sd, "AI": sd, "ENERGY": sd},
            aggregations={},
        )
        for r in rows:
            assert r.divergence == dashboard.DIVERGENCE_NA_AGG
            assert r.company_derived_read == "N/A"
            # Canonical side is populated; only aggregation is the N/A side.
            assert r.canonical_signal != "N/A"

    def test_selective_buy_vs_caution_propagates(self, dashboard):
        # End-to-end: a SELECTIVE_BUY canonical paired with a CAUTION
        # aggregation surfaces the "more cautious" marker in the row.
        SD = dashboard.SectorData

        class _FakeScore:
            signal = "SELECTIVE_BUY"
            normalized_score = 0.28
            emergency_triggered = False
            triggered_exits: list = []
            n_broken = 1
            n_near_threshold = 0
            n_bull = 3

        sd = SD(sector="SEMICONDUCTOR", catalysts=[], exits=[],
                score=_FakeScore(), missing_files=[])
        rows = dashboard.build_aggregation_roll_up_rows(
            {"SEMICONDUCTOR": sd, "AI": sd, "ENERGY": sd},
            aggregations={
                "SEMICONDUCTOR": _agg_row(sector="SEMICONDUCTOR",
                                            read="CAUTION"),
                "AI": _agg_row(sector="AI", read="CAUTION"),
                "ENERGY": _agg_row(sector="ENERGY", read="CAUTION"),
            },
        )
        for r in rows:
            assert r.divergence == dashboard.DIVERGENCE_MORE_CAUTIOUS
            assert r.canonical_signal == "SELECTIVE_BUY"
            assert r.canonical_score == "+0.280"


# --------------------------------------------------------------------------- #
# V6.8.1 must NOT mutate canonical scoring.
# --------------------------------------------------------------------------- #
class TestNoEffectOnScoring:
    def test_score_sector_unchanged_after_v681_helpers(self, tmp_path: Path,
                                                         dashboard):
        cats = [
            _cat(cid="SEMI-NVDA-REV-T1", sector="SEMICONDUCTOR",
                 status="BULL", current_value="+65%"),
            _cat(cid="SEMI-INVENTORY-CYCLE-T2", sector="SEMICONDUCTOR",
                 status="BROKEN", current_value="-30%"),
        ]
        before = score_sector(cats, [], sector="SEMICONDUCTOR")

        # Exercise every V6.8.1 helper many times.
        p = tmp_path / "agg.csv"
        for i in range(10):
            row = _agg_row(sector="SEMICONDUCTOR", read="CAUTION",
                           run_id=f"RUN-{i}")
            append_sector_aggregation_rows([row], p)
            latest = load_latest_aggregation_per_sector(p)
            dashboard.build_aggregation_roll_up_rows(
                {s: dashboard.SectorData(sector=s, catalysts=[],
                                          exits=[], score=None,
                                          missing_files=[])
                 for s in dashboard.SECTORS},
                latest,
            )
            dashboard.aggregation_divergence("HOLD", "CAUTION")

        after = score_sector(cats, [], sector="SEMICONDUCTOR")
        assert before.signal == after.signal
        assert before.normalized_score == after.normalized_score


# --------------------------------------------------------------------------- #
# Dashboard remains read-only (importing module does no I/O beyond the
# render() call which we never invoke in tests).
# --------------------------------------------------------------------------- #
class TestReadOnly:
    def test_helpers_do_not_touch_disk(self, tmp_path: Path, dashboard):
        p = tmp_path / "agg.csv"
        # Calling load on a missing path must not create the file.
        load_latest_aggregation_per_sector(p)
        assert not p.exists()

        # build_aggregation_roll_up_rows is purely in-memory.
        SD = dashboard.SectorData
        sd = SD(sector="SEMICONDUCTOR", catalysts=[], exits=[],
                score=None, missing_files=[])
        dashboard.build_aggregation_roll_up_rows(
            {"SEMICONDUCTOR": sd, "AI": sd, "ENERGY": sd}, {},
        )
        assert not p.exists()
