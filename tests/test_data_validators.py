"""Spec test 1: data validation catches impossible OHLC values."""

import numpy as np
import pandas as pd
import pytest

from quantbot.data.validators import (
    DataValidationError,
    validate_ohlcv,
    validate_panel,
)


def _good_frame(n=120):
    idx = pd.bdate_range("2020-01-01", periods=n, name="date")
    close = pd.Series(np.linspace(100, 130, n), index=idx)
    return pd.DataFrame(
        {
            "open": close * 0.999,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "adjusted_close": close,
            "volume": 1_000_000.0,
        },
        index=idx,
    )


def test_valid_frame_passes():
    rep = validate_ohlcv(_good_frame(), "GOOD")
    assert rep.ok
    assert not rep.errors


def test_high_below_low_is_error():
    df = _good_frame()
    df.iloc[10, df.columns.get_loc("high")] = df.iloc[10]["low"] - 5
    rep = validate_ohlcv(df, "BADHL")
    assert not rep.ok
    assert any("high < low" in e for e in rep.errors)


def test_negative_volume_and_nonpositive_adjclose():
    df = _good_frame()
    df.iloc[5, df.columns.get_loc("volume")] = -1
    df.iloc[6, df.columns.get_loc("adjusted_close")] = 0.0
    rep = validate_ohlcv(df, "BADV")
    assert not rep.ok
    assert any("negative volume" in e for e in rep.errors)
    assert any("adjusted_close <= 0" in e for e in rep.errors)


def test_duplicate_dates_error():
    df = _good_frame(50)
    df = pd.concat([df, df.iloc[[0]]])
    rep = validate_ohlcv(df, "DUP")
    assert any("duplicate dates" in e for e in rep.errors)


def test_missing_required_column():
    df = _good_frame().drop(columns=["adjusted_close"])
    rep = validate_ohlcv(df, "MISS")
    assert not rep.ok
    assert any("missing required columns" in e for e in rep.errors)


def test_raise_on_error():
    df = _good_frame()
    df.iloc[0, df.columns.get_loc("high")] = -1
    with pytest.raises(DataValidationError):
        validate_ohlcv(df, "RAISE", raise_on_error=True)


def test_missing_values_not_silently_zeroed():
    df = _good_frame()
    df.iloc[20:40, df.columns.get_loc("close")] = np.nan
    rep = validate_ohlcv(df, "NAN")
    # >5% missing -> error, and it is reported, never coerced to 0.
    assert any("missing price data" in (e) for e in rep.errors)
    assert df["close"].isna().sum() == 20  # untouched


def test_validate_panel(panel):
    reports = validate_panel(panel)
    assert set(reports) == set(panel)
    assert all(r.ok for r in reports.values())
