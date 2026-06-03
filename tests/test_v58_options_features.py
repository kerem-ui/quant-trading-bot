"""V5.8 options research feature tests (toy data only -- no network, no fetch).

Covers realized vol, causal IV rank/percentile, IV summary, skew, term
structure, liquidity, missing-IV / missing-OI handling, input non-mutation,
causality assertions, and the no-broker / LIVE_TRADING_ENABLED guardrails.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quantbot.options import features as F


# --------------------------------------------------------------------------- #
# Toy chain helpers
# --------------------------------------------------------------------------- #
def _row(date, exp, dte, option_type, strike, *, bid, ask, iv, delta,
         volume=100, oi=0, spot=400.0):
    return {
        "date": pd.Timestamp(date), "underlying": "SPY",
        "expiration": pd.Timestamp(exp), "dte": int(dte),
        "option_type": option_type, "strike": float(strike),
        "bid": float(bid), "ask": float(ask), "mid": (bid + ask) / 2,
        "volume": int(volume), "open_interest": int(oi),
        "implied_volatility": iv, "delta": delta,
        "gamma": 0.01, "theta": -0.05, "vega": 0.10,
        "underlying_price": float(spot), "contract_multiplier": 100,
        "exercise_style": "american",
    }


def _smile(date, exp, dte, *, spot=400.0, atm_iv=0.20, put_skew=0.04,
           call_skew=-0.03, volume=100, oi=0):
    """One expiration's smile: ATM call/put at delta +/-0.50, 25d wings."""
    rows = [
        _row(date, exp, dte, "call", spot,     bid=4.0, ask=4.1, iv=atm_iv,        delta=0.50, volume=volume, oi=oi, spot=spot),
        _row(date, exp, dte, "put",  spot,     bid=4.0, ask=4.1, iv=atm_iv,        delta=-0.50, volume=volume, oi=oi, spot=spot),
        _row(date, exp, dte, "call", spot + 8, bid=1.0, ask=1.1, iv=atm_iv + call_skew, delta=0.25, volume=volume, oi=oi, spot=spot),
        _row(date, exp, dte, "put",  spot - 8, bid=1.0, ask=1.1, iv=atm_iv + put_skew,  delta=-0.25, volume=volume, oi=oi, spot=spot),
        _row(date, exp, dte, "call", spot + 6, bid=1.4, ask=1.5, iv=atm_iv + call_skew, delta=0.30, volume=volume, oi=oi, spot=spot),
        _row(date, exp, dte, "put",  spot - 6, bid=1.4, ask=1.5, iv=atm_iv + put_skew,  delta=-0.30, volume=volume, oi=oi, spot=spot),
    ]
    return rows


# --------------------------------------------------------------------------- #
# Realized vol
# --------------------------------------------------------------------------- #
def test_realized_vol_positive_and_causal():
    dates = pd.bdate_range("2022-01-03", periods=80)
    rng = np.random.default_rng(0)
    spot = pd.Series(400 * np.cumprod(1 + rng.normal(0, 0.01, 80)),
                      index=dates, name="underlying_price")
    rv = F.realized_vol_features(spot, windows=(5, 21, 63))
    assert "rv_21d_annualized" in rv.columns
    assert (rv["rv_21d_annualized"].dropna() > 0).all()
    # ret_5d equals pct_change(5) exactly (causal); compare values only.
    expected = spot.pct_change(5).to_numpy()
    np.testing.assert_allclose(rv["ret_5d"].to_numpy(), expected,
                                rtol=1e-12, equal_nan=True)


def test_realized_vol_does_not_use_future():
    # If we truncate the series at t, the RV at the last common date must be
    # identical to the full-series RV at that date (no look-ahead).
    dates = pd.bdate_range("2022-01-03", periods=60)
    spot = pd.Series(np.linspace(400, 360, 60) + np.sin(np.arange(60)),
                      index=dates)
    full = F.realized_vol_features(spot)
    cut = F.realized_vol_features(spot.iloc[:40])
    t = dates[39]
    assert full.loc[t, "rv_21d_annualized"] == pytest.approx(
        cut.loc[t, "rv_21d_annualized"], nan_ok=True)


# --------------------------------------------------------------------------- #
# IV summary + skew
# --------------------------------------------------------------------------- #
def _toy_chain_one_date(date="2022-03-01", spot=400.0):
    rows = _smile(date, "2022-03-31", 30, spot=spot, atm_iv=0.20,
                  put_skew=0.04, call_skew=-0.03)
    return pd.DataFrame(rows)


def test_iv_summary_atm_and_wings():
    chain = _toy_chain_one_date()
    s = F.iv_summary_for_date(chain, target_dte=30, dte_band=(25, 45))
    assert s["atm_iv"] == pytest.approx(0.20)
    assert s["iv_25d_call"] == pytest.approx(0.17)   # 0.20 - 0.03
    assert s["iv_25d_put"] == pytest.approx(0.24)    # 0.20 + 0.04
    assert s["iv_dte"] == 30
    assert s["iv_coverage"] == pytest.approx(1.0)


def test_skew_features_equity_shape():
    iv = F.iv_summary_panel(_toy_chain_one_date())
    sk = F.skew_features(iv)
    r = sk.iloc[0]
    assert r["put_skew"] == pytest.approx(0.04)
    assert r["call_skew"] == pytest.approx(-0.03)
    assert r["put_call_skew"] == pytest.approx(0.07)
    assert r["skew_delta_basis"] == "25d"


def test_iv_summary_handles_missing_iv():
    # NaN out ALL non-ATM rows (both 0.25 and 0.30 wings). ATM IV (|delta|=0.50)
    # is still computed; with no valid wing delta the wing IVs become NaN.
    rows = _smile("2022-03-01", "2022-03-31", 30)
    df = pd.DataFrame(rows)
    df.loc[df["delta"].abs() != 0.50, "implied_volatility"] = np.nan
    s = F.iv_summary_for_date(df)
    assert not np.isnan(s["atm_iv"])
    assert np.isnan(s["iv_25d_call"]) and np.isnan(s["iv_25d_put"])
    assert np.isnan(s["iv_30d_call"]) and np.isnan(s["iv_30d_put"])


# --------------------------------------------------------------------------- #
# IV rank / percentile causality
# --------------------------------------------------------------------------- #
def test_iv_rank_is_causal_and_bounded():
    dates = pd.bdate_range("2022-01-03", periods=120)
    rng = np.random.default_rng(1)
    iv = pd.Series(0.20 + rng.normal(0, 0.02, 120).cumsum() * 0.01,
                    index=dates).clip(0.05, 0.6)
    out = F.iv_rank_features(iv, windows=(63,), min_periods=20)
    rank = out["iv_rank_63d"].dropna()
    assert ((rank >= 0) & (rank <= 1)).all()
    # Early dates (< min_periods) must be NaN (no future use, no fabrication).
    assert out["iv_rank_63d"].iloc[:19].isna().all()
    assert out["insufficient_history_63d"].iloc[:19].all()


def test_iv_percentile_truncation_invariance():
    # Percentile at date t must not change if future data is removed.
    dates = pd.bdate_range("2022-01-03", periods=100)
    iv = pd.Series(np.linspace(0.15, 0.35, 100), index=dates)
    full = F.iv_rank_features(iv, windows=(63,), min_periods=20)
    cut = F.iv_rank_features(iv.iloc[:70], windows=(63,), min_periods=20)
    t = dates[69]
    assert full.loc[t, "iv_percentile_63d"] == pytest.approx(
        cut.loc[t, "iv_percentile_63d"], nan_ok=True)


# --------------------------------------------------------------------------- #
# Term structure
# --------------------------------------------------------------------------- #
def test_term_structure_buckets():
    d = "2022-03-01"
    rows = []
    rows += _smile(d, "2022-03-11", 10, atm_iv=0.25)   # near (7-14)
    rows += _smile(d, "2022-03-26", 25, atm_iv=0.22)   # mid (21-30)
    rows += _smile(d, "2022-04-15", 45, atm_iv=0.20)   # far (30-45)
    ts = F.term_structure_for_date(pd.DataFrame(rows))
    assert ts["atm_iv_near"] == pytest.approx(0.25)
    assert ts["atm_iv_mid"] == pytest.approx(0.22)
    assert ts["atm_iv_far"] == pytest.approx(0.20)
    assert ts["ts_slope"] == pytest.approx(0.20 - 0.25)  # backwardation
    assert ts["ts_ratio"] == pytest.approx(0.20 / 0.25)


def test_term_structure_missing_far_bucket():
    d = "2022-03-01"
    rows = _smile(d, "2022-03-11", 10, atm_iv=0.25)  # only near
    ts = F.term_structure_for_date(pd.DataFrame(rows))
    assert ts["atm_iv_near"] == pytest.approx(0.25)
    assert np.isnan(ts["atm_iv_far"])
    assert np.isnan(ts["ts_slope"])


# --------------------------------------------------------------------------- #
# Liquidity / missing OI
# --------------------------------------------------------------------------- #
def test_liquidity_features_and_missing_oi():
    rows = _smile("2022-03-01", "2022-03-31", 30, oi=0, volume=50)
    # add a zero-bid wide-spread row
    rows.append(_row("2022-03-01", "2022-03-31", 30, "put", 300,
                     bid=0.0, ask=0.05, iv=np.nan, delta=-0.02, volume=0, oi=0))
    df = pd.DataFrame(rows)
    liq = F.liquidity_features_for_date(df)
    assert liq["open_interest_missing"] is True
    assert liq["share_zero_bid"] > 0
    assert liq["share_zero_volume"] > 0
    assert liq["usable_contracts"] <= liq["n_contracts"]
    assert liq["total_volume"] == int(df["volume"].sum())


def test_liquidity_detects_present_oi():
    rows = _smile("2022-03-01", "2022-03-31", 30, oi=500)
    liq = F.liquidity_features_for_date(pd.DataFrame(rows))
    assert liq["open_interest_missing"] is False


# --------------------------------------------------------------------------- #
# Non-mutation + causality assertion
# --------------------------------------------------------------------------- #
def test_feature_functions_do_not_mutate_input():
    chain = _toy_chain_one_date()
    snap = chain.copy(deep=True)
    _ = F.iv_summary_for_date(chain)
    _ = F.liquidity_features_for_date(chain)
    _ = F.term_structure_for_date(chain)
    pd.testing.assert_frame_equal(chain, snap)


def test_assert_causal_panel_rejects_unsorted_or_dup():
    good = pd.DataFrame({"date": pd.to_datetime(["2022-01-03", "2022-01-04"])})
    F.assert_causal_panel(good)  # no raise
    bad_order = pd.DataFrame({"date": pd.to_datetime(["2022-01-04", "2022-01-03"])})
    with pytest.raises(AssertionError):
        F.assert_causal_panel(bad_order)
    dup = pd.DataFrame({"date": pd.to_datetime(["2022-01-03", "2022-01-03"])})
    with pytest.raises(AssertionError):
        F.assert_causal_panel(dup)


# --------------------------------------------------------------------------- #
# Guardrails
# --------------------------------------------------------------------------- #
def test_features_module_has_no_broker_imports():
    src = Path(F.__file__).read_text(encoding="utf-8")
    for needle in ("import ib_insync", "from ib_insync", "import ibapi",
                    "from ibapi", "interactivebrokers", "place_order",
                    "submit_order"):
        assert needle not in src


def test_live_trading_disabled():
    import quantbot
    assert quantbot.LIVE_TRADING_ENABLED is False
