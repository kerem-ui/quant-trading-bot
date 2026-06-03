"""V5.7 research layer tests (toy data only -- NEVER hits the network).

Covers:
  - regime classifier outputs on synthetic price/vol/yield/credit series
  - strongest-move detection on a toy series with known extremes
  - trade-context annotation does NOT mutate the input trades frame
  - missing FRED_API_KEY behaviour is silent + cache-aware
  - manual events loader handles missing file gracefully
  - no broker / live / IBKR / order-execution imports anywhere in the
    new research modules
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quantbot.events.manual_events import (
    build_event_flag_panel,
    default_events_path,
    load_events,
    load_events_detailed,
)
from quantbot.macro import fred_loader
from quantbot.macro.macro_indicators import (
    credit_proxy_trend,
    level_and_change,
    moving_averages,
    realized_vol,
    returns_over,
    yield_inversion_flag,
)
from quantbot.macro.regime_classifier import (
    RegimeThresholds,
    build_regime_panel,
    classify_credit,
    classify_rates,
    classify_trend,
    classify_vol,
)
from quantbot.research.price_moves import (
    rolling_returns,
    strongest_moves,
    strongest_moves_panel,
)
from quantbot.research.trade_context import (
    annotate_event_overlap,
    annotate_trades,
    summarize_event_overlap,
    summarize_winners_vs_losers,
)


# --------------------------------------------------------------------------- #
# Helpers / fixtures
# --------------------------------------------------------------------------- #
def _bdates(start="2022-01-03", n=120):
    return pd.bdate_range(start, periods=n, name="date")


def _toy_spy(start="2022-01-03", n=120, seed=0):
    rng = np.random.default_rng(seed)
    dates = _bdates(start, n)
    drift = np.full(n, -0.0005)        # mild downward trend
    drift[40:60] = +0.005              # short up-leg
    rets = drift + rng.normal(0, 0.01, n)
    px = 400.0 * np.cumprod(1.0 + rets)
    return pd.Series(px, index=dates, name="close")


# --------------------------------------------------------------------------- #
# Regime classifier
# --------------------------------------------------------------------------- #
def test_regime_thresholds_defaults_sane():
    th = RegimeThresholds()
    assert th.trend_up_pct > 0 > th.trend_down_pct
    assert th.vol_low_max < th.vol_high_min
    assert th.rates_up_bp > 0 > th.rates_down_bp


def test_classify_trend_responds_to_drift():
    spy = _toy_spy()
    trend = classify_trend(spy)
    # The synthetic up-leg should produce at least one "up" label.
    assert (trend == "up").sum() >= 1
    # The downward drift should produce at least one "down" label.
    assert (trend == "down").sum() >= 1


def test_classify_vol_buckets_are_low_mid_high():
    vix = pd.Series([10, 15, 18, 22, 28, 35],
                     index=pd.bdate_range("2022-01-03", periods=6))
    out = classify_vol(vix)
    assert out.iloc[0] == "low"
    assert out.iloc[3] == "mid"
    assert out.iloc[-1] == "high"


def test_classify_rates_returns_three_buckets():
    # Strong up move in DGS10 -> "up"; flat -> "stable"; strong down -> "down"
    n = 60
    dgs10 = pd.Series(
        np.concatenate([
            np.linspace(2.0, 2.5, 22),     # ramping up
            np.full(22, 2.5),              # flat
            np.linspace(2.5, 2.0, 16),     # ramping down
        ]),
        index=pd.bdate_range("2022-01-03", periods=n),
    )
    out = classify_rates(dgs10)
    # First 21 rows are "unknown" because diff(21) is NaN there -- expected.
    labelled = out[out != "unknown"]
    assert set(labelled.unique()) <= {"up", "stable", "down"}
    assert (labelled == "up").sum() >= 1
    assert (labelled == "down").sum() >= 1


def test_classify_credit_returns_none_when_inputs_missing():
    assert classify_credit(None, None) is None
    assert classify_credit(pd.Series([1, 2, 3]), None) is None


def test_build_regime_panel_skips_missing_inputs():
    spy = _toy_spy()
    panel = build_regime_panel(spy_close=spy)         # only trend available
    assert "trend" in panel.columns
    assert "vol" not in panel.columns and "rates" not in panel.columns
    assert "combined" in panel.columns


# --------------------------------------------------------------------------- #
# Macro indicators
# --------------------------------------------------------------------------- #
def test_moving_averages_and_returns_over_have_expected_columns():
    spy = _toy_spy()
    ma = moving_averages(spy, windows=(5, 21))
    assert list(ma.columns) == ["ma_5", "ma_21"]
    ro = returns_over(spy, periods=(5, 21))
    assert list(ro.columns) == ["ret_5d", "ret_21d"]
    # 5-day return is exactly close/close.shift(5)-1
    expected = (spy / spy.shift(5) - 1.0).dropna()
    pd.testing.assert_series_equal(
        ro["ret_5d"].dropna(), expected.rename("ret_5d"),
    )


def test_realized_vol_positive_and_finite():
    rets = pd.Series(np.random.default_rng(0).normal(0, 0.01, 252),
                      index=pd.bdate_range("2022-01-03", periods=252))
    rv = realized_vol(rets, window=21)
    assert (rv.dropna() > 0).all()
    assert np.isfinite(rv.dropna()).all()


def test_yield_inversion_flag_detects_inversion():
    dgs10 = pd.Series([2.0, 1.5, 3.0])
    dgs2 = pd.Series([1.5, 2.0, 2.5])
    out = yield_inversion_flag(dgs10, dgs2)
    assert out.tolist() == [False, True, False]


# --------------------------------------------------------------------------- #
# Price moves
# --------------------------------------------------------------------------- #
def test_strongest_moves_finds_known_extremes():
    # Construct a series with a deterministic +20% spike over 21 days.
    n = 100
    px = np.full(n, 100.0)
    # Days 40-60: linear ramp from 100 -> 120
    px[40:61] = np.linspace(100, 120, 21)
    # Days 70-90: drawdown to 90
    px[70:91] = np.linspace(120, 90, 21)
    series = pd.Series(px, index=pd.bdate_range("2022-01-03", periods=n))
    ups = strongest_moves(series, window=21, top_k=3, direction="up")
    assert any(m.return_pct > 15 for m in ups)
    downs = strongest_moves(series, window=21, top_k=3, direction="down")
    assert any(m.return_pct < -10 for m in downs)


def test_strongest_moves_panel_runs_all_windows():
    series = _toy_spy()
    df = strongest_moves_panel(series, windows=(5, 21, 63), top_k=3)
    assert set(df["window_days"].unique()) == {5, 21, 63}
    assert len(df) == 9   # 3 windows x 3 picks each


def test_rolling_returns_rejects_bad_window():
    with pytest.raises(ValueError):
        rolling_returns(_toy_spy(), 0)


# --------------------------------------------------------------------------- #
# Trade context annotation
# --------------------------------------------------------------------------- #
def _toy_trades():
    return pd.DataFrame({
        "fill_open":  pd.to_datetime(["2022-01-05", "2022-02-10", "2022-03-15"]),
        "fill_close": pd.to_datetime(["2022-01-20", "2022-02-25", "2022-03-31"]),
        "realized_pnl": [120.0, -80.0, 50.0],
        "structure":   ["bear_put", "bear_put", "bear_put"],
    })


def test_annotate_trades_does_not_mutate_input():
    trades = _toy_trades()
    snapshot = trades.copy(deep=True)
    spy = _toy_spy()
    out = annotate_trades(trades, spy_close=spy)
    # Original frame untouched.
    pd.testing.assert_frame_equal(trades, snapshot)
    # Realized P&L verbatim in the output.
    assert out["realized_pnl"].tolist() == trades["realized_pnl"].tolist()
    # Added at least one annotation column.
    assert "spy_return_in_trade_pct" in out.columns
    assert "vix_at_entry" in out.columns


def test_annotate_trades_handles_missing_context_with_nans():
    trades = _toy_trades()
    out = annotate_trades(trades)  # all proxies None
    # All annotation columns exist, just with NaN values.
    assert "vix_at_entry" in out.columns
    assert out["vix_at_entry"].isna().all()
    assert out["spy_return_in_trade_pct"].isna().all()


def test_summarize_winners_vs_losers_groups_by_pnl_sign():
    spy = _toy_spy()
    annotated = annotate_trades(_toy_trades(), spy_close=spy)
    summary = summarize_winners_vs_losers(annotated)
    assert set(summary["pnl_bucket"]) == {"win", "loss"}
    assert summary["n_trades"].sum() == len(annotated)


def test_annotate_trades_requires_fill_open_and_fill_close():
    bad = pd.DataFrame({"x": [1, 2]})
    with pytest.raises(KeyError):
        annotate_trades(bad)


# --------------------------------------------------------------------------- #
# FRED loader (no live calls -- we use tmp dirs + monkey-patched env)
# --------------------------------------------------------------------------- #
def test_fred_has_api_key_reflects_env(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    assert fred_loader.has_api_key() is False
    monkeypatch.setenv("FRED_API_KEY", "DUMMY_TEST_KEY")
    assert fred_loader.has_api_key() is True


def test_fred_fetch_returns_none_without_key_and_without_cache(monkeypatch, tmp_path):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    # Custom root so we don't touch the real cache.
    df = fred_loader.fetch_series("FAKE_SERIES", root=tmp_path)
    assert df is None


def test_fred_fetch_uses_cache_when_present(monkeypatch, tmp_path):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    cache_dir = tmp_path / "fred"
    cache_dir.mkdir(parents=True)
    toy = pd.DataFrame({
        "date": pd.to_datetime(["2022-01-01", "2022-02-01"]),
        "value": [3.5, 4.0],
    })
    toy.to_csv(cache_dir / "TESTSERIES.csv", index=False)
    out = fred_loader.fetch_series("TESTSERIES", root=tmp_path)
    assert out is not None
    assert out["value"].tolist() == [3.5, 4.0]


def test_fred_module_does_not_import_broker_or_live_modules():
    """Scan for ACTUAL imports / function calls, not docstring mentions
    of forbidden names (docstrings legitimately mention 'IBKR' to declare
    the no-broker invariant)."""
    src = Path(fred_loader.__file__).read_text(encoding="utf-8")
    forbidden_imports = (
        "import ib_insync", "from ib_insync",
        "import ibapi", "from ibapi",
        "import interactivebrokers", "from interactivebrokers",
    )
    for needle in forbidden_imports:
        assert needle not in src


# --------------------------------------------------------------------------- #
# Manual events loader
# --------------------------------------------------------------------------- #
def test_manual_events_missing_file_returns_empty(tmp_path):
    bogus = tmp_path / "does_not_exist.csv"
    df = load_events(bogus)
    assert df.empty
    assert list(df.columns) == ["date", "event_type", "note"]


def test_manual_events_loads_and_builds_flag_panel(tmp_path):
    p = tmp_path / "manual_events.csv"
    p.write_text(
        "date,event_type,note\n"
        "2022-01-12,CPI,Dec 2021 CPI\n"
        "2022-01-26,FOMC,FOMC statement\n",
        encoding="utf-8",
    )
    ev = load_events(p)
    assert len(ev) == 2
    assert set(ev["event_type"].tolist()) == {"CPI", "FOMC"}
    idx = pd.bdate_range("2022-01-03", "2022-02-04")
    panel = build_event_flag_panel(ev, date_index=idx)
    assert panel.loc[pd.Timestamp("2022-01-12"), "CPI"] is np.True_ \
        or bool(panel.loc[pd.Timestamp("2022-01-12"), "CPI"]) is True
    assert bool(panel.loc[pd.Timestamp("2022-01-26"), "FOMC"]) is True
    assert bool(panel.loc[pd.Timestamp("2022-01-13"), "CPI"]) is False


# --------------------------------------------------------------------------- #
# Detailed events loader + event-overlap annotation
# --------------------------------------------------------------------------- #
def test_load_events_detailed_missing_file_returns_typed_empty(tmp_path):
    df = load_events_detailed(tmp_path / "nope.csv")
    assert df.empty
    assert list(df.columns) == ["date", "event_type", "event_name",
                                  "source", "importance", "note"]


def test_load_events_detailed_preserves_rich_columns(tmp_path):
    p = tmp_path / "manual_events.csv"
    p.write_text(
        "date,event_type,event_name,source,importance,note\n"
        "2022-01-12,CPI,CPI release,cal,high,Dec 2021 CPI\n"
        "2022-01-26,fomc,FOMC statement,fed,HIGH,Jan FOMC\n",
        encoding="utf-8",
    )
    df = load_events_detailed(p)
    assert len(df) == 2
    # event_type upper-cased, importance lower-cased
    assert df["event_type"].tolist() == ["CPI", "FOMC"]
    assert df["importance"].tolist() == ["high", "high"]
    assert df["event_name"].tolist() == ["CPI release", "FOMC statement"]


def test_load_events_detailed_accepts_notes_alias(tmp_path):
    p = tmp_path / "manual_events.csv"
    p.write_text(
        "date,event_type,notes\n"
        "2022-03-16,FOMC,first hike\n",
        encoding="utf-8",
    )
    df = load_events_detailed(p)
    assert df["note"].tolist() == ["first hike"]


def _toy_trades_for_events():
    return pd.DataFrame({
        "strategy": ["bear_put", "bear_put", "bull_call"],
        "fill_open":  pd.to_datetime(["2022-01-10", "2022-02-09", "2022-03-20"]),
        "fill_close": pd.to_datetime(["2022-01-20", "2022-02-18", "2022-03-30"]),
        "realized_pnl": [120.0, -80.0, 50.0],
    })


def _toy_events_detailed():
    return pd.DataFrame({
        "date": pd.to_datetime(["2022-01-12", "2022-01-26", "2022-02-16"]),
        "event_type": ["CPI", "FOMC", "FOMC_MINUTES"],
        "event_name": ["CPI release", "FOMC statement", "Jan minutes"],
        "source": ["cal", "fed", "fed"],
        "importance": ["high", "high", "medium"],
        "note": ["", "", ""],
    })


def test_annotate_event_overlap_flags_and_counts():
    trades = _toy_trades_for_events()
    ev = _toy_events_detailed()
    out = annotate_event_overlap(trades, ev)
    # Trade 1 (Jan 10-20) overlaps CPI Jan 12 -> count 1, cpi True, fomc False
    assert out.loc[0, "event_count_during_trade"] == 1
    assert bool(out.loc[0, "cpi_event_during_trade"]) is True
    assert bool(out.loc[0, "fomc_event_during_trade"]) is False
    assert bool(out.loc[0, "high_importance_event_during_trade"]) is True
    # Trade 2 (Feb 9-18) overlaps FOMC_MINUTES Feb 16 -> fomc True (grouped)
    assert out.loc[1, "event_count_during_trade"] == 1
    assert bool(out.loc[1, "fomc_event_during_trade"]) is True
    assert bool(out.loc[1, "cpi_event_during_trade"]) is False
    # FOMC_MINUTES is 'medium' importance -> high flag False
    assert bool(out.loc[1, "high_importance_event_during_trade"]) is False
    # Trade 3 (Mar 20-30) overlaps nothing
    assert out.loc[2, "event_count_during_trade"] == 0
    assert out.loc[2, "events_during_trade"] == ""


def test_annotate_event_overlap_does_not_mutate_input_or_pnl():
    trades = _toy_trades_for_events()
    snapshot = trades.copy(deep=True)
    out = annotate_event_overlap(trades, _toy_events_detailed())
    pd.testing.assert_frame_equal(trades, snapshot)
    assert out["realized_pnl"].tolist() == trades["realized_pnl"].tolist()


def test_annotate_event_overlap_empty_events_neutral_defaults():
    trades = _toy_trades_for_events()
    out = annotate_event_overlap(
        trades, pd.DataFrame(columns=["date", "event_type", "event_name",
                                       "source", "importance", "note"]))
    assert (out["event_count_during_trade"] == 0).all()
    assert (~out["cpi_event_during_trade"]).all()
    assert (~out["fomc_event_during_trade"]).all()


def test_annotate_event_overlap_nearest_before_entry():
    trades = _toy_trades_for_events()
    out = annotate_event_overlap(trades, _toy_events_detailed())
    # Trade 3 entry 2022-03-20; nearest event before is FOMC_MINUTES 2022-02-16
    assert "2022-02-16" in out.loc[2, "nearest_event_before_entry"]
    assert out.loc[2, "days_since_nearest_event_before_entry"] == 32.0
    # Trade 1 entry 2022-01-10; no event before -> empty / NaN
    assert out.loc[0, "nearest_event_before_entry"] == ""
    assert pd.isna(out.loc[0, "days_since_nearest_event_before_entry"])


def test_summarize_event_overlap_groups_by_strategy_and_bucket():
    trades = _toy_trades_for_events()
    out = annotate_event_overlap(trades, _toy_events_detailed())
    summ = summarize_event_overlap(out)
    assert "trades_with_cpi" in summ.columns
    assert "trades_with_fomc" in summ.columns
    assert summ["n_trades"].sum() == len(out)


def test_annotate_event_overlap_requires_fill_columns():
    with pytest.raises(KeyError):
        annotate_event_overlap(pd.DataFrame({"x": [1]}), _toy_events_detailed())


# --------------------------------------------------------------------------- #
# Cross-cutting guardrails
# --------------------------------------------------------------------------- #
def test_research_modules_have_no_broker_imports():
    """Static scan: none of the V5.7 research/macro/events files
    actually import broker / live-trading libraries. We look for real
    import statements rather than docstring text (which legitimately
    states the no-broker invariant)."""
    pkg = Path(fred_loader.__file__).resolve().parents[1]  # quantbot/
    targets = [
        pkg / "macro",
        pkg / "research",
        pkg / "events",
    ]
    forbidden_imports = (
        "import ib_insync", "from ib_insync",
        "import ibapi", "from ibapi",
        "import interactivebrokers", "from interactivebrokers",
    )
    for d in targets:
        for f in d.rglob("*.py"):
            src = f.read_text(encoding="utf-8")
            for needle in forbidden_imports:
                assert needle not in src, f"{needle!r} found in {f}"


def test_quantbot_live_trading_enabled_is_false():
    import quantbot
    assert quantbot.LIVE_TRADING_ENABLED is False
