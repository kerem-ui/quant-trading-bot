"""V4 options schema, validators, filters, and cache tests."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quantbot.data import options_cache as oc
from quantbot.data.options_chain_loader import REQUIRED_COLS, add_derived_columns
from quantbot.data.options_providers.synthetic import SyntheticOptionsLoader
from quantbot.data.options_validators import (
    DataValidationError,
    OptionsQualityThresholds,
    rejection_reasons,
    validate_canonical_chain,
    validate_quality,
    validate_schema,
)
from quantbot.options import filters as F


@pytest.fixture(scope="module")
def sample_chain():
    loader = SyntheticOptionsLoader()
    return loader.load("SPY", "2022-01-03", "2022-01-07")


# --------------------------------------------------------------------------- #
# schema
# --------------------------------------------------------------------------- #
def test_synthetic_loader_emits_canonical_schema(sample_chain):
    for col in REQUIRED_COLS:
        assert col in sample_chain.columns
    assert validate_schema(sample_chain).ok


def test_derived_columns_added(sample_chain):
    df = add_derived_columns(sample_chain)
    for c in ("moneyness", "log_moneyness", "time_to_expiry_years"):
        assert c in df.columns
    # moneyness ~ strike / spot
    expected = sample_chain["strike"] / sample_chain["underlying_price"]
    assert np.allclose(df["moneyness"].fillna(0), expected.fillna(0))


def test_schema_validator_catches_missing_columns():
    df = pd.DataFrame({"date": [pd.Timestamp("2022-01-03")]})
    rep = validate_schema(df)
    assert not rep.ok
    assert any("missing required columns" in e for e in rep.errors)


# --------------------------------------------------------------------------- #
# quality validator
# --------------------------------------------------------------------------- #
def test_quality_validator_clean_chain(sample_chain):
    rep = validate_canonical_chain(sample_chain)
    assert rep.ok, rep.errors


def test_quality_validator_catches_bid_gt_ask(sample_chain):
    bad = sample_chain.copy()
    bad.iloc[0, bad.columns.get_loc("bid")] = bad.iloc[0]["ask"] + 1.0
    rep = validate_quality(bad)
    assert not rep.ok
    assert any("bid > ask" in e for e in rep.errors)


def test_quality_validator_catches_negative_bid_and_iv(sample_chain):
    bad = sample_chain.copy()
    bad.iloc[0, bad.columns.get_loc("bid")] = -0.5
    bad.iloc[1, bad.columns.get_loc("implied_volatility")] = -0.01
    rep = validate_quality(bad)
    assert any("bid < 0" in e for e in rep.errors)
    assert any("implied_volatility out of" in e for e in rep.errors)


def test_quality_validator_catches_impossible_delta(sample_chain):
    bad = sample_chain.copy()
    bad.iloc[0, bad.columns.get_loc("delta")] = 1.5
    rep = validate_quality(bad)
    assert any("|delta| > 1" in e for e in rep.errors)


def test_quality_validator_raises_on_error(sample_chain):
    bad = sample_chain.copy()
    bad.iloc[0, bad.columns.get_loc("bid")] = -1.0
    with pytest.raises(DataValidationError):
        validate_canonical_chain(bad, raise_on_error=True)


def test_rejection_reasons_per_row(sample_chain):
    bad = sample_chain.copy()
    bad.iloc[0, bad.columns.get_loc("bid")] = bad.iloc[0]["ask"] + 1.0
    bad.iloc[1, bad.columns.get_loc("delta")] = 2.0
    rr = rejection_reasons(bad)
    assert rr["bid_gt_ask"].iloc[0]
    assert rr["delta_out_of_range"].iloc[1]
    assert rr["any_reject"].iloc[:2].all()
    assert not rr["any_reject"].iloc[5:].all()  # most clean rows pass


def test_threshold_override(sample_chain):
    # Tight spread threshold should produce a warning but not an error.
    rep = validate_quality(sample_chain,
                            OptionsQualityThresholds(spread_max_pct=1e-9))
    assert rep.ok  # spread is a warning, not error
    assert any("spread" in w for w in rep.warnings)


# --------------------------------------------------------------------------- #
# filters
# --------------------------------------------------------------------------- #
def test_filters_compose(sample_chain):
    out = F.filter_option_type(sample_chain, "call")
    assert (out["option_type"].str.lower() == "call").all()
    out2 = F.filter_dte(out, dte_min=30, dte_max=45)
    assert out2["dte"].between(30, 45).all()
    out3 = F.filter_moneyness(out2, 0.9, 1.1)
    m = out3["strike"] / out3["underlying_price"]
    assert m.between(0.9, 1.1).all()
    out4 = F.filter_delta(out3, min_abs_delta=0.1, max_abs_delta=0.7)
    assert out4["delta"].abs().between(0.1, 0.7).all()
    out5 = F.filter_spread(out4, max_spread_pct=0.5)
    assert ((out5["ask"] - out5["bid"]) / out5["mid"].replace(0, np.nan)
            ).abs().max() <= 0.5 + 1e-12


def test_filter_underlying_string_and_list(sample_chain):
    a = F.filter_underlying(sample_chain, "SPY")
    b = F.filter_underlying(sample_chain, ["spy", "QQQ"])
    assert not a.empty and not b.empty


def test_filter_liquidity_drops_low(sample_chain):
    # All synthetic rows have volume >= 0; min_volume=10**9 should empty it
    assert F.filter_liquidity(sample_chain, min_volume=10**9).empty


# --------------------------------------------------------------------------- #
# cache  (uses tmp_path - does NOT touch the real data/options dir)
# --------------------------------------------------------------------------- #
def test_cache_write_read_roundtrip(sample_chain, tmp_path):
    p = oc.write_raw(sample_chain[sample_chain["date"] == sample_chain["date"].min()],
                      "synthetic", "SPY", sample_chain["date"].min(),
                      root=tmp_path)
    assert p.exists()
    back = oc.read_raw("synthetic", "SPY", sample_chain["date"].min(),
                        root=tmp_path)
    assert back is not None
    assert len(back) > 0
    for c in REQUIRED_COLS:
        assert c in back.columns


def test_cache_refuses_silent_overwrite(sample_chain, tmp_path):
    d = sample_chain["date"].min()
    sub = sample_chain[sample_chain["date"] == d]
    oc.write_raw(sub, "synthetic", "SPY", d, root=tmp_path)
    with pytest.raises(FileExistsError):
        oc.write_raw(sub, "synthetic", "SPY", d, root=tmp_path)
    # force=True does overwrite.
    p2 = oc.write_raw(sub, "synthetic", "SPY", d, root=tmp_path, force=True)
    assert p2.exists()


def test_cache_metadata_update(sample_chain, tmp_path):
    dates = sample_chain["date"].unique()
    oc.update_metadata("synthetic", "SPY", dates, len(sample_chain),
                        root=tmp_path, note="phase1-smoke")
    meta = json.loads(oc.metadata_path(tmp_path).read_text())
    assert meta["schema_version"] >= 1
    u = meta["providers"]["synthetic"]["underlyings"]["SPY"]
    assert u["n_rows_total"] == len(sample_chain)
    assert u["fetch_events"][0]["note"] == "phase1-smoke"


def test_processed_path_layout(tmp_path):
    p = oc.processed_path("SPY", 2022, 3, root=tmp_path)
    assert p.parts[-3:] == ("SPY", "2022", "2022-03.csv.gz")
