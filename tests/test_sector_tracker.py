"""Tests for V6.1 sector thesis tracker framework (read-only, decision-support).

Covers:
  - schema validation (positive + every negative case)
  - scoring math (all-BULL, all-BROKEN, mixed, empty)
  - tier weighting (Tier 1 outweighs Tier 2)
  - emergency-exit override (TRIGGERED forces EXIT_WATCH)
  - CSV round-trip
  - Markdown rendering shape
  - guardrails: LIVE_TRADING_ENABLED False, no broker/IBKR/order imports
    in the sector_tracker package, no SELL / SHORT / order tokens in
    rendered output
"""

from __future__ import annotations

from pathlib import Path

import pytest

import quantbot
from quantbot.research import sector_tracker as st
from quantbot.research.sector_tracker import (
    ALLOWED_SECTORS,
    Catalyst,
    EmergencyExit,
    SchemaError,
    SectorReport,
    SectorScore,
    build_all_sectors,
    build_sector_report,
    load_catalysts,
    load_exits,
    render_markdown,
    save_catalysts,
    save_exits,
    score_sector,
    signal_from_normalized,
)


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
def _make_cat(
    *,
    cid: str = "C1",
    sector: str = "SEMICONDUCTOR",
    tier: int = 1,
    status: str = "BULL",
    direction: str = "ABOVE",
    source_type: str = "MANUAL",
) -> Catalyst:
    return Catalyst(
        catalyst_id=cid,
        sector=sector,
        subsector="HBM",
        catalyst_name=f"name-{cid}",
        tier=tier,
        direction=direction,
        threshold="100",
        current_value="120",
        status=status,
        source_type=source_type,
        source_detail="manual:demo",
        last_updated="2026-05-23",
        action_if_broken="review thesis (no order)",
        notes="",
    )


def _make_exit(
    *,
    eid: str = "E1",
    sector: str = "SEMICONDUCTOR",
    status: str = "MONITORING",
) -> EmergencyExit:
    return EmergencyExit(
        exit_id=eid,
        sector=sector,
        scenario="China export-control shock",
        trigger_condition="new ban announced",
        current_status=status,
        action="re-evaluate sleeve (no order)",
        source="MANUAL",
        last_updated="2026-05-23",
    )


# --------------------------------------------------------------------------- #
# schema validation
# --------------------------------------------------------------------------- #
class TestSchema:
    def test_valid_catalyst_constructs(self):
        c = _make_cat()
        assert c.sector == "SEMICONDUCTOR"
        assert c.tier == 1
        assert c.status == "BULL"

    @pytest.mark.parametrize("bad", [
        {"sector": "NOT_A_SECTOR"},
        {"tier": 3},
        {"tier": 0},
        {"direction": "SIDEWAYS"},
        {"status": "AMAZING"},
        {"source_type": "BLOOMBERG"},
        {"last_updated": "May 23 2026"},
        {"catalyst_id": ""},
        {"catalyst_name": ""},
    ])
    def test_catalyst_validation_rejects_bad(self, bad):
        kwargs = dict(
            catalyst_id="C", sector="AI", subsector="", catalyst_name="x",
            tier=1, direction="ABOVE", threshold="1", current_value="1",
            status="BULL", source_type="MANUAL", source_detail="",
            last_updated="2026-05-23", action_if_broken="", notes="",
        )
        kwargs.update(bad)
        with pytest.raises(SchemaError):
            Catalyst(**kwargs)

    def test_valid_exit_constructs(self):
        e = _make_exit()
        assert e.sector == "SEMICONDUCTOR"
        assert e.current_status == "MONITORING"

    @pytest.mark.parametrize("bad", [
        {"sector": "OTHER"},
        {"current_status": "ARMED"},
        {"exit_id": ""},
        {"scenario": ""},
        {"last_updated": "yesterday"},
    ])
    def test_exit_validation_rejects_bad(self, bad):
        kwargs = dict(
            exit_id="E", sector="AI", scenario="s", trigger_condition="t",
            current_status="MONITORING", action="a", source="MANUAL",
            last_updated="2026-05-23",
        )
        kwargs.update(bad)
        with pytest.raises(SchemaError):
            EmergencyExit(**kwargs)


# --------------------------------------------------------------------------- #
# scoring math
# --------------------------------------------------------------------------- #
class TestScoring:
    def test_all_bull_yields_max_score(self):
        cats = [_make_cat(cid=f"C{i}", tier=1, status="BULL") for i in range(4)]
        s = score_sector(cats, sector="SEMICONDUCTOR")
        assert s.n_total == 4 and s.n_bull == 4
        assert s.raw_score == 4 * 2 * 1  # 4 catalysts * weight2 * +1
        assert s.total_weight == 4 * 2
        assert s.normalized_score == pytest.approx(1.0)
        assert s.signal == "ACCUMULATE"
        assert not s.emergency_triggered

    def test_all_broken_yields_exit_watch(self):
        cats = [_make_cat(cid=f"C{i}", tier=1, status="BROKEN") for i in range(3)]
        s = score_sector(cats, sector="SEMICONDUCTOR")
        assert s.normalized_score == pytest.approx(-2.0)
        assert s.signal == "EXIT_WATCH"

    def test_empty_catalysts_yields_hold(self):
        s = score_sector([], sector="SEMICONDUCTOR")
        assert s.normalized_score == 0.0
        assert s.signal == "HOLD"
        assert s.total_weight == 0 and s.n_total == 0

    def test_tier1_broken_outweighs_tier2_bull(self):
        # 1 x Tier1 BROKEN (weight 2 * -2 = -4)
        # 2 x Tier2 BULL  (weight 1 * +1 = +1 each => +2)
        # raw = -4 + 2 = -2; total_weight = 2 + 2 = 4; norm = -0.5  -> REDUCE
        cats = [
            _make_cat(cid="C1", tier=1, status="BROKEN"),
            _make_cat(cid="C2", tier=2, status="BULL"),
            _make_cat(cid="C3", tier=2, status="BULL"),
        ]
        s = score_sector(cats, sector="SEMICONDUCTOR")
        assert s.raw_score == -2 and s.total_weight == 4
        assert s.normalized_score == pytest.approx(-0.5)
        assert s.signal == "REDUCE"

    def test_signal_band_boundaries(self):
        # Verify each band boundary maps to the right label
        assert signal_from_normalized(1.00) == "ACCUMULATE"
        assert signal_from_normalized(0.50) == "ACCUMULATE"
        assert signal_from_normalized(0.49) == "SELECTIVE_BUY"
        assert signal_from_normalized(0.20) == "SELECTIVE_BUY"
        assert signal_from_normalized(0.19) == "HOLD"
        assert signal_from_normalized(-0.10) == "HOLD"
        assert signal_from_normalized(-0.11) == "AVOID_NEW_BUY"
        assert signal_from_normalized(-0.30) == "AVOID_NEW_BUY"
        assert signal_from_normalized(-0.31) == "REDUCE"
        assert signal_from_normalized(-0.60) == "REDUCE"
        assert signal_from_normalized(-0.61) == "EXIT_WATCH"
        assert signal_from_normalized(-2.00) == "EXIT_WATCH"

    def test_sector_filtering(self):
        cats = [
            _make_cat(cid="A", sector="AI", status="BULL"),
            _make_cat(cid="B", sector="SEMICONDUCTOR", status="BROKEN"),
        ]
        s_ai = score_sector(cats, sector="AI")
        s_semi = score_sector(cats, sector="SEMICONDUCTOR")
        assert s_ai.n_total == 1 and s_ai.signal == "ACCUMULATE"
        assert s_semi.n_total == 1 and s_semi.signal == "EXIT_WATCH"

    def test_top_drivers_and_risks_sorted(self):
        cats = [
            _make_cat(cid="T1B", tier=1, status="BULL"),
            _make_cat(cid="T2B", tier=2, status="BULL"),
            _make_cat(cid="T1X", tier=1, status="BROKEN"),
            _make_cat(cid="T2N", tier=2, status="NEAR_THRESHOLD"),
        ]
        s = score_sector(cats, sector="SEMICONDUCTOR")
        # Tier-1 BULL should come before Tier-2 BULL among bull drivers
        assert s.top_bull_drivers[0] == "name-T1B"
        # BROKEN should rank above NEAR_THRESHOLD among risks
        assert s.top_risks[0] == "name-T1X"


# --------------------------------------------------------------------------- #
# emergency-exit override
# --------------------------------------------------------------------------- #
class TestEmergencyExitOverride:
    def test_triggered_exit_forces_exit_watch_even_with_all_bull(self):
        cats = [_make_cat(cid=f"C{i}", tier=1, status="BULL") for i in range(4)]
        exs = [_make_exit(eid="E1", status="TRIGGERED")]
        s = score_sector(cats, exs, sector="SEMICONDUCTOR")
        assert s.normalized_score == pytest.approx(1.0)  # raw score unchanged
        assert s.emergency_triggered is True
        assert "E1" in s.triggered_exits
        assert s.signal == "EXIT_WATCH"  # overridden

    def test_inactive_or_monitoring_exit_does_not_override(self):
        cats = [_make_cat(cid="C1", status="BULL")]
        for status in ("INACTIVE", "MONITORING"):
            s = score_sector(cats, [_make_exit(status=status)],
                              sector="SEMICONDUCTOR")
            assert s.emergency_triggered is False
            assert s.signal == "ACCUMULATE"

    def test_exit_in_other_sector_does_not_affect(self):
        cats = [_make_cat(cid="C1", sector="AI", status="BULL")]
        exs = [_make_exit(sector="SEMICONDUCTOR", status="TRIGGERED")]
        s = score_sector(cats, exs, sector="AI")
        assert s.emergency_triggered is False
        assert s.signal == "ACCUMULATE"


# --------------------------------------------------------------------------- #
# CSV round-trip + builder + markdown
# --------------------------------------------------------------------------- #
class TestIORoundTrip:
    def test_catalyst_csv_round_trip(self, tmp_path: Path):
        cats = [
            _make_cat(cid="A", sector="AI", status="BULL"),
            _make_cat(cid="B", sector="SEMICONDUCTOR", status="NEUTRAL"),
        ]
        p = save_catalysts(cats, tmp_path / "cats.csv")
        loaded = load_catalysts(p)
        assert len(loaded) == 2
        assert loaded[0].catalyst_id == "A" and loaded[0].sector == "AI"
        assert loaded[1].tier == 1
        # invalid tier in CSV should raise on load
        bad = tmp_path / "bad.csv"
        bad.write_text(
            "catalyst_id,sector,subsector,catalyst_name,tier,direction,threshold,"
            "current_value,status,source_type,source_detail,last_updated,"
            "action_if_broken,notes\n"
            "X,AI,,x,9,ABOVE,1,1,BULL,MANUAL,,2026-05-23,act,\n",
            encoding="utf-8",
        )
        with pytest.raises(SchemaError):
            load_catalysts(bad)

    def test_exit_csv_round_trip(self, tmp_path: Path):
        exs = [_make_exit(eid="E1"), _make_exit(eid="E2", status="TRIGGERED")]
        p = save_exits(exs, tmp_path / "exits.csv")
        loaded = load_exits(p)
        assert [e.exit_id for e in loaded] == ["E1", "E2"]
        assert loaded[1].current_status == "TRIGGERED"

    def test_load_missing_file_returns_empty(self, tmp_path: Path):
        assert load_catalysts(tmp_path / "nope.csv") == []
        assert load_exits(tmp_path / "nope.csv") == []


class TestBuilderAndReport:
    def test_build_sector_report_filters_by_sector(self):
        cats = [
            _make_cat(cid="A1", sector="AI", status="BULL"),
            _make_cat(cid="S1", sector="SEMICONDUCTOR", status="BROKEN"),
        ]
        rep = build_sector_report("AI", cats)
        assert isinstance(rep, SectorReport)
        assert rep.sector == "AI"
        assert rep.score.signal == "ACCUMULATE"
        assert [c.catalyst_id for c in rep.catalysts] == ["A1"]

    def test_build_all_sectors_returns_one_per_sector(self):
        cats = [
            _make_cat(cid="A", sector="AI", status="BULL"),
            _make_cat(cid="S", sector="SEMICONDUCTOR", status="NEUTRAL"),
            _make_cat(cid="E", sector="ENERGY", status="NEAR_THRESHOLD"),
        ]
        out = build_all_sectors(cats)
        assert set(out.keys()) == {"AI", "SEMICONDUCTOR", "ENERGY"}
        assert out["AI"].score.signal == "ACCUMULATE"

    def test_markdown_contains_required_disclaimers_and_signal(self):
        cats = [_make_cat(cid="C1", status="BULL")]
        rep = build_sector_report("SEMICONDUCTOR", cats)
        md = render_markdown(rep)
        assert "Signal: ACCUMULATE" in md
        assert "NOT a trading signal" in md
        assert "NOT a broker order" in md
        assert "LIVE_TRADING_ENABLED = False" in md


# --------------------------------------------------------------------------- #
# guardrails
# --------------------------------------------------------------------------- #
class TestGuardrails:
    def test_live_trading_flag_is_false(self):
        assert quantbot.LIVE_TRADING_ENABLED is False

    def test_sector_tracker_has_no_broker_or_ibkr_imports(self):
        pkg_dir = Path(st.__file__).parent
        forbidden = (
            "ib_insync", "ibapi", "ib_async",
            "from quantbot.backtest.broker", "from ..backtest.broker",
            "place_order", "submit_order", "send_order",
            "from quantbot.backtest.engine", "from ..backtest.engine",
        )
        for src_path in pkg_dir.glob("*.py"):
            text = src_path.read_text(encoding="utf-8")
            for tok in forbidden:
                assert tok not in text, (
                    f"forbidden token {tok!r} found in {src_path.name}"
                )

    def test_rendered_md_does_not_contain_order_tokens(self):
        cats = [
            _make_cat(cid="C1", status="BULL"),
            _make_cat(cid="C2", status="BROKEN"),
        ]
        rep = build_sector_report("SEMICONDUCTOR", cats,
                                  [_make_exit(status="TRIGGERED")])
        md = render_markdown(rep).upper()
        # Decision-support labels like SELECTIVE_BUY are allowed (user-specified).
        # The framework must NOT emit broker-order tokens.
        for forbidden in (" SELL ", " SHORT ", "PLACE_ORDER",
                          "SUBMIT_ORDER", "FILL_ORDER"):
            assert forbidden not in md, (
                f"forbidden order token {forbidden!r} in rendered output"
            )

    def test_signal_labels_are_research_recommendations_only(self):
        # The full set of allowed signal labels — no raw BUY/SELL/SHORT tokens.
        from quantbot.research.sector_tracker import SIGNAL_LABELS
        assert set(SIGNAL_LABELS) == {
            "ACCUMULATE", "SELECTIVE_BUY", "HOLD",
            "AVOID_NEW_BUY", "REDUCE", "EXIT_WATCH",
        }
        # SELECTIVE_BUY is the closest-to-action label and is explicitly a
        # user-specified research label, not an order.
        assert all("SELL" not in lbl or lbl == "" for lbl in SIGNAL_LABELS)
        assert all("SHORT" not in lbl for lbl in SIGNAL_LABELS)


def test_allowed_sectors_are_the_v6_three():
    assert ALLOWED_SECTORS == frozenset({"AI", "SEMICONDUCTOR", "ENERGY"})


def test_sector_score_dataclass_is_immutable():
    s = score_sector([_make_cat(status="BULL")], sector="SEMICONDUCTOR")
    assert isinstance(s, SectorScore)
    with pytest.raises((AttributeError, Exception)):
        s.signal = "ACCUMULATE"  # frozen dataclass — must be read-only
