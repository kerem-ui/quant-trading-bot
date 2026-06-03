"""V4 options-chain loader contract tests (synthetic only - no network)."""

import pandas as pd
import pytest

from quantbot.data.options_chain_loader import (
    REQUIRED_COLS,
    available_loaders,
    get_loader,
)
from quantbot.data.options_providers.synthetic import SyntheticOptionsLoader
from quantbot.options.chain import OptionsChain


def test_synthetic_loader_registered():
    assert "synthetic" in available_loaders()


def test_get_loader_returns_synthetic_instance():
    loader = get_loader("synthetic")
    assert isinstance(loader, SyntheticOptionsLoader)
    assert loader.name == "synthetic"


def test_loader_canonical_schema_on_small_range():
    loader = SyntheticOptionsLoader()
    df = loader.load("SPY", "2022-01-03", "2022-01-07")
    assert not df.empty
    for c in REQUIRED_COLS:
        assert c in df.columns
    # The date range covers 5 business days.
    assert df["date"].nunique() == 5
    # bid <= ask invariant.
    assert (df["bid"] <= df["ask"] + 1e-12).all()
    # underlying_price > 0.
    assert (df["underlying_price"] > 0).all()


def test_loader_respects_dte_and_type_filters():
    loader = SyntheticOptionsLoader()
    df = loader.load("SPY", "2022-01-03", "2022-01-07",
                     dte_min=35, dte_max=45, option_type="put")
    assert (df["option_type"].str.lower() == "put").all()
    assert df["dte"].between(35, 45).all()


def test_loader_deterministic():
    a = SyntheticOptionsLoader().load("SPY", "2022-01-03", "2022-01-05")
    b = SyntheticOptionsLoader().load("SPY", "2022-01-03", "2022-01-05")
    # same seed defaults -> identical outputs
    pd.testing.assert_frame_equal(a, b)


def test_options_chain_wrapper_helpers():
    loader = SyntheticOptionsLoader()
    chain = OptionsChain(loader.load("SPY", "2022-01-03", "2022-01-07"))
    assert len(chain) > 0
    assert chain.underlying("SPY").df["underlying"].str.upper().eq("SPY").all()
    # ATM lookup on a known date / expiration
    d = chain.df["date"].iloc[0]
    e = chain.df["expiration"].iloc[0]
    row = chain.atm(d, e, "call")
    assert row is not None
    spot = chain.df.loc[chain.df["date"] == d, "underlying_price"].iloc[0]
    sub = chain.on_date(d).for_expiration(e).type("call").df
    expected_strike = sub.iloc[(sub["strike"] - spot).abs().argsort()].iloc[0]["strike"]
    assert row["strike"] == expected_strike


def test_options_chain_surface_slice_nonempty():
    loader = SyntheticOptionsLoader()
    chain = OptionsChain(loader.load("SPY", "2022-01-03", "2022-01-05"))
    s = chain.surface_slice(chain.df["date"].iloc[0])
    assert not s.empty
    # rows = strikes, cols = dte buckets
    assert s.index.name == "strike"


def test_unknown_provider_raises():
    with pytest.raises(KeyError):
        get_loader("not_a_real_provider")


# --------------------------------------------------------------------------- #
# ThetaData adapter - structure-only checks (no network)
# --------------------------------------------------------------------------- #
def test_thetadata_loader_registered():
    assert "thetadata" in available_loaders()


def test_thetadata_dry_run_returns_canonical_schema(monkeypatch):
    from quantbot.data.options_providers.thetadata import ThetaDataLoader
    monkeypatch.delenv("THETADATA_API_KEY", raising=False)
    monkeypatch.delenv("THETADATA_BASE_URL", raising=False)
    loader = ThetaDataLoader(dry_run=True)
    # Default base URL is the local Terminal -> creds.txt handles auth.
    assert loader.is_local_terminal is True
    assert loader.has_credentials is True
    df = loader.load("SPY", "2022-01-03", "2022-01-05")
    for c in REQUIRED_COLS:
        assert c in df.columns
    assert df.attrs.get("dry_run") is True


def test_thetadata_default_url_is_v3_local_terminal(monkeypatch):
    """Default base URL must be the local Theta Terminal v3, port 25503."""
    from quantbot.data.options_providers.thetadata import ThetaDataLoader
    monkeypatch.delenv("THETADATA_BASE_URL", raising=False)
    loader = ThetaDataLoader()
    assert "127.0.0.1:25503" in loader._base_url
    assert loader.api_version == "v3"
    # Constructed URLs use /v3/* (NOT /v2/*).
    assert loader._url("hist/stock/eod").endswith("/v3/hist/stock/eod")
    assert "/v2/" not in loader._url("hist/stock/eod")


def test_thetadata_localhost_does_not_require_env_key(monkeypatch):
    """Local Terminal authenticates via creds.txt - no env key needed."""
    from quantbot.data.options_providers.thetadata import ThetaDataLoader
    monkeypatch.delenv("THETADATA_API_KEY", raising=False)
    loader = ThetaDataLoader(base_url="http://127.0.0.1:25503")
    assert loader.is_local_terminal
    assert loader.has_credentials is True
    assert loader._api_key is None  # never sourced or stored


def test_thetadata_remote_url_requires_env_key(monkeypatch):
    """A non-local base URL still requires a key."""
    from quantbot.data.options_providers.thetadata import ThetaDataLoader
    monkeypatch.delenv("THETADATA_API_KEY", raising=False)
    loader = ThetaDataLoader(base_url="https://remote.example.com",
                              dry_run=False)
    assert loader.is_local_terminal is False
    assert loader.has_credentials is False
    with pytest.raises(RuntimeError, match="credentials"):
        loader.load("SPY", "2022-01-03", "2022-01-05")


def test_thetadata_real_fetch_uses_only_option_endpoint(monkeypatch):
    """V4 with Options Standard subscription: the adapter must NOT call
    /v3/stock/history/eod (that requires the Stocks Value subscription). It
    must call /v3/option/history/eod with v3 params, and pull the underlying
    spot from the local ETF cache via :func:`_spot_from_local_cache`.

    We monkeypatch the HTTP helper AND the spot helper to verify behaviour
    without any network IO.
    """
    from quantbot.data.options_providers import thetadata as td
    from quantbot.data.options_providers.thetadata import ThetaDataLoader
    monkeypatch.delenv("THETADATA_API_KEY", raising=False)
    seen: list[tuple[str, dict]] = []

    def fake_get_json(self, path, params):
        seen.append((path, dict(params or {})))
        if path == "option/history/eod":
            return [
                {"symbol": "SPY", "expiration": "2022-01-07", "strike": 470.0,
                 "right": "call", "created": "2022-01-03T22:15:00.000Z",
                 "last_trade": "2022-01-03T21:00:00.000Z",
                 "bid": 12.10, "ask": 12.30, "close": 12.20, "volume": 1234},
                {"symbol": "SPY", "expiration": "2022-01-07", "strike": 470.0,
                 "right": "put", "created": "2022-01-04T22:15:00.000Z",
                 "last_trade": "2022-01-04T21:00:00.000Z",
                 "bid": 4.95, "ask": 5.05, "close": 5.00, "volume": 7},
            ]
        # If anything calls stock/history/eod, fail loudly.
        if path == "stock/history/eod":
            raise AssertionError(
                "Adapter must not call /v3/stock/history/eod under "
                "Options Standard - spot must come from local cache."
            )
        return []

    monkeypatch.setattr(ThetaDataLoader, "_get_json", fake_get_json)
    monkeypatch.setattr(
        td, "_spot_from_local_cache",
        lambda u, s, e: {
            pd.Timestamp("2022-01-03"): 477.71,
            pd.Timestamp("2022-01-04"): 477.55,
        },
    )

    loader = ThetaDataLoader(dry_run=False)
    df = loader.load("SPY", "2022-01-03", "2022-01-04", dte_min=0, dte_max=10)

    paths = [p for p, _ in seen]
    # Only the option history endpoint should be hit.
    assert "option/history/eod" in paths
    assert "stock/history/eod" not in paths
    # No legacy v2 paths or v2 parameter names anywhere.
    assert all("/v2/" not in p for p in paths)
    assert all("bulk_hist" not in p for p in paths)
    for _p, params in seen:
        assert "root" not in params       # v3 uses 'symbol'

    opt_params = next(pa for p, pa in seen if p == "option/history/eod")
    assert opt_params.get("symbol") == "SPY"
    assert str(opt_params.get("expiration")) == "*"
    assert "max_dte" in opt_params

    # Canonical schema + spot wired from local cache.
    assert not df.empty
    for c in REQUIRED_COLS:
        assert c in df.columns
    assert df.attrs.get("dry_run") is False
    assert set(df["date"].dt.strftime("%Y-%m-%d")) <= {"2022-01-03", "2022-01-04"}
    assert set(df["option_type"].unique()).issubset({"call", "put"})
    assert df["underlying_price"].notna().all()
    # Spot for 2022-01-03 must be 477.71 from the monkeypatched local cache.
    row = df[df["date"] == pd.Timestamp("2022-01-03")].iloc[0]
    assert row["underlying_price"] == pytest.approx(477.71)


def test_thetadata_repr_masks_key_when_remote(monkeypatch):
    from quantbot.data.options_providers.thetadata import ThetaDataLoader
    monkeypatch.setenv("THETADATA_API_KEY", "ABCDEFGHIJ1234567890")
    loader = ThetaDataLoader(base_url="https://remote.example.com")
    rep = repr(loader)
    assert "ABCDEFGHIJ1234567890" not in rep
    assert "***" in rep


def test_v3_greeks_eod_normalizer_canonical_mapping():
    """The V4.1 greeks/eod normalizer maps implied_vol -> implied_volatility,
    pulls Greeks straight from the row, and uses the row's underlying_price
    when present."""
    from quantbot.data.options_providers.thetadata import (
        normalize_thetadata_v3_greeks_eod,
    )
    rows = [
        {"symbol": "SPY", "expiration": "2022-01-07", "strike": 470.0,
         "right": "CALL", "timestamp": "2022-01-03T00:00:00.000",
         "last_trade": "2022-01-03T21:00:00.000",
         "underlying_timestamp": "2022-01-03T17:15:00.000",
         "bid": 12.10, "ask": 12.30, "close": 12.20, "volume": 1234,
         "implied_vol": 0.21, "delta": 0.56, "gamma": 0.04,
         "theta": -0.08, "vega": 0.10, "rho": 0.02,
         "underlying_price": 477.71, "iv_error": 0.0001,
         "charm": 0.01, "vanna": 0.0},  # higher-order Greeks present -> ignored
        {"symbol": "SPY", "expiration": "2022-01-07", "strike": 470.0,
         "right": "PUT", "timestamp": "2022-01-04T00:00:00.000",
         "last_trade": "2022-01-04T21:00:00.000",
         "underlying_timestamp": "2022-01-04T17:15:00.000",
         "bid": 4.95, "ask": 5.05, "close": 5.00, "volume": 7,
         "implied_vol": 0.18, "delta": -0.44, "gamma": 0.04,
         "theta": -0.07, "vega": 0.10, "rho": -0.02,
         "underlying_price": 477.55, "iv_error": 0.0002},
    ]
    df = normalize_thetadata_v3_greeks_eod(rows, underlying="SPY")
    for c in REQUIRED_COLS:
        assert c in df.columns
    # IV mapped from 'implied_vol'.
    assert df["implied_volatility"].tolist() == [0.21, 0.18]
    # Greeks straight from row.
    assert df["delta"].tolist() == [0.56, -0.44]
    assert df["theta"].tolist() == [-0.08, -0.07]
    assert df["rho"].tolist() == [0.02, -0.02]
    # underlying_price comes from the row, not the local cache.
    assert df["underlying_price"].tolist() == [477.71, 477.55]
    # option_type lower-cased; canonical column set has no higher-order Greeks.
    assert df["option_type"].tolist() == ["call", "put"]
    for hi in ("charm", "vanna", "vomma", "iv_error"):
        assert hi not in df.columns
    # dates parsed correctly (date == last_trade.date()).
    assert df["date"].dt.strftime("%Y-%m-%d").tolist() == ["2022-01-03",
                                                              "2022-01-04"]


def test_v3_greeks_eod_uses_spot_fallback_when_row_spot_zero():
    """If the row's underlying_price is 0/NaN, the normalizer must fall back
    to the spot_by_date map (provided from the local ETF cache)."""
    from quantbot.data.options_providers.thetadata import (
        normalize_thetadata_v3_greeks_eod,
    )
    rows = [{
        "symbol": "SPY", "expiration": "2022-01-07", "strike": 470.0,
        "right": "call", "timestamp": "2022-01-03T00:00:00.000",
        "last_trade": "2022-01-03T21:00:00.000",
        "bid": 12.10, "ask": 12.30, "close": 12.20, "volume": 0,
        "implied_vol": 0.21, "delta": 0.56, "gamma": 0.04,
        "theta": -0.08, "vega": 0.10, "rho": 0.02,
        "underlying_price": 0.0,   # provider returned a zero spot here
    }]
    df = normalize_thetadata_v3_greeks_eod(
        rows, underlying="SPY",
        spot_by_date={pd.Timestamp("2022-01-03"): 477.71},
    )
    assert df["underlying_price"].iloc[0] == pytest.approx(477.71)


def test_thetadata_repr_local_terminal_does_not_mention_key(monkeypatch):
    from quantbot.data.options_providers.thetadata import ThetaDataLoader
    monkeypatch.setenv("THETADATA_API_KEY", "ABCDEFGHIJ1234567890")
    loader = ThetaDataLoader()  # default localhost
    rep = repr(loader)
    # Local terminal repr says 'local-terminal', not the key/mask form.
    assert "local-terminal" in rep
    assert "ABCDEFGHIJ1234567890" not in rep


def test_thetadata_normalizer_maps_to_canonical():
    from quantbot.data.options_providers.thetadata import normalize_thetadata_eod
    rows = [
        # ThetaData-style raw rows (strikes as int * 1000; exp as YYYYMMDD).
        {"exp": 20220218, "strike": 450000, "right": "C", "bid": 5.5, "ask": 5.7,
         "volume": 1234, "open_interest": 9999, "iv": 0.22,
         "delta": 0.55, "gamma": 0.04, "theta": -0.08, "vega": 0.10},
        {"exp": 20220218, "strike": 450000, "right": "P", "bid": 4.9, "ask": 5.1,
         "volume": 88, "open_interest": 7777, "iv": 0.24,
         "delta": -0.45, "gamma": 0.04, "theta": -0.07, "vega": 0.10},
    ]
    df = normalize_thetadata_eod(
        rows, underlying="SPY", snapshot_date="2022-01-03", spot=460.0,
    )
    for c in REQUIRED_COLS:
        assert c in df.columns
    assert df["strike"].tolist() == [450.0, 450.0]
    assert df["expiration"].iloc[0] == pd.Timestamp("2022-02-18")
    assert df["option_type"].tolist() == ["call", "put"]
    assert (df["mid"] == (df["bid"] + df["ask"]) / 2).all()
    assert df["dte"].tolist() == [46, 46]
    assert (df["underlying_price"] == 460.0).all()
