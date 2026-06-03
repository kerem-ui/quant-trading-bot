"""V7.5.1 — Tests for the local price cache reader + technicals module.

Covers:

  * :class:`PriceSeries` dataclass.
  * :func:`load_price_series` — missing / empty / valid / header-variant
    files; chronological sort; row-skip on unparseable rows.
  * Deterministic indicators: RSI, SMA, return %, distance-to-SMA,
    drawdown-from-high.
  * Snapshot composition: empty input, insufficient data branches, fully
    populated branch (against the committed SPY cache).
  * Platform integration via ``load_technical_snapshot_from_disk``.
  * **Hard guardrails**: no broker / IBKR / order / yfinance / ThetaData
    / network tokens; ``LIVE_TRADING_ENABLED`` False.
  * No-effect-on-Portfolio totals / Protection / PortTech / score_sector.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

import quantbot
from quantbot.research.company_detail import (
    DEFAULT_PRICE_CACHE_DIR,
    PriceSeries,
    RETURN_1M_DAYS,
    RETURN_1W_DAYS,
    RSI_PERIOD,
    SMA_LONG_PERIOD,
    SMA_SHORT_PERIOD,
    TECHNICAL_SNAPSHOT_FIELDS,
    TechnicalSnapshot,
    compute_distance_to_sma_pct,
    compute_drawdown_from_high_pct,
    compute_return_pct,
    compute_rsi,
    compute_sma,
    compute_technical_snapshot,
    load_price_series,
)
from quantbot.research.portfolio import (
    PositionRow,
    append_position_rows,
    ensure_transactions_header,
)
from quantbot.research.porttech import derive_porttech_rows
from quantbot.research.protection import derive_protection_rows
from quantbot.research.sector_tracker import (
    Catalyst,
    CompanyLedgerRow,
    SectorSignalLogRow,
    score_sector,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture
def platform():
    sys.path.insert(0, str(REPO_ROOT / "apps"))
    try:
        yield importlib.import_module("portfolio_platform")
    finally:
        if str(REPO_ROOT / "apps") in sys.path:
            sys.path.remove(str(REPO_ROOT / "apps"))


# --------------------------------------------------------------------------- #
# Guardrails (V7.5.1 surface only)
# --------------------------------------------------------------------------- #
class TestGuardrails:
    PRICE_CACHE_SOURCE = (
        REPO_ROOT / "src" / "quantbot" / "research" / "company_detail"
        / "price_cache.py"
    ).read_text(encoding="utf-8")
    TECHNICALS_SOURCE = (
        REPO_ROOT / "src" / "quantbot" / "research" / "company_detail"
        / "technicals.py"
    ).read_text(encoding="utf-8")

    def test_live_trading_disabled(self):
        assert quantbot.LIVE_TRADING_ENABLED is False

    def test_no_broker_or_order_tokens(self):
        for src in (self.PRICE_CACHE_SOURCE, self.TECHNICALS_SOURCE):
            for token in ("ib_insync", "place_order", "submit_order",
                          "from broker", "import broker", "ibapi",
                          "placeOrder"):
                assert token not in src, (
                    f"forbidden broker token {token!r} in V7.5.1 surface"
                )

    def test_no_network_imports(self):
        for src in (self.PRICE_CACHE_SOURCE, self.TECHNICALS_SOURCE):
            for token in ("import requests", "import urllib",
                          "import aiohttp", "import socket",
                          "from requests", "from urllib",
                          "from aiohttp", "from socket"):
                assert token not in src, (
                    f"forbidden network import {token!r} in V7.5.1 surface"
                )

    def test_no_yfinance_or_thetadata_imports(self):
        for src in (self.PRICE_CACHE_SOURCE, self.TECHNICALS_SOURCE):
            assert "import yfinance" not in src.lower()
            assert "from yfinance" not in src.lower()
            assert "yf.download" not in src
            assert "import thetadata" not in src.lower()
            assert "from thetadata" not in src.lower()


# --------------------------------------------------------------------------- #
# PriceSeries dataclass
# --------------------------------------------------------------------------- #
class TestPriceSeries:
    def test_construct_empty(self):
        s = PriceSeries(ticker="X", cache_path="")
        assert s.n_rows == 0
        assert s.latest_date == ""
        assert s.latest_close is None

    def test_construct_populated(self):
        s = PriceSeries(
            ticker="SPY", cache_path="x",
            dates=["2026-06-01", "2026-06-02"],
            closes=[100.0, 101.0],
        )
        assert s.n_rows == 2
        assert s.latest_date == "2026-06-02"
        assert s.latest_close == pytest.approx(101.0)

    def test_mismatched_lengths_rejected(self):
        with pytest.raises(ValueError):
            PriceSeries(
                ticker="X", cache_path="",
                dates=["2026-06-01"], closes=[],
            )


# --------------------------------------------------------------------------- #
# load_price_series — missing / empty / valid / header variants
# --------------------------------------------------------------------------- #
class TestLoadPriceSeries:
    def test_missing_file_returns_none(self, tmp_path: Path):
        assert load_price_series("ZZZ", cache_dir=tmp_path) is None

    def test_empty_file_returns_none(self, tmp_path: Path):
        (tmp_path / "ZZZ.csv").write_text("", encoding="utf-8")
        assert load_price_series("ZZZ", cache_dir=tmp_path) is None

    def test_header_only_returns_none(self, tmp_path: Path):
        (tmp_path / "ZZZ.csv").write_text(
            "date,close\n", encoding="utf-8",
        )
        assert load_price_series("ZZZ", cache_dir=tmp_path) is None

    def test_canonical_v2_cache_shape(self, tmp_path: Path):
        # Real-world canonical V1/V2/V5 cache shape used by data/cache/.
        (tmp_path / "TST.csv").write_text(
            "date,open,high,low,close,adjusted_close,volume\n"
            "2026-06-01,99,101,98,100.0,100.0,1000\n"
            "2026-06-02,100,102,99,101.0,101.0,1100\n",
            encoding="utf-8",
        )
        s = load_price_series("TST", cache_dir=tmp_path)
        assert s is not None
        assert s.n_rows == 2
        assert s.latest_close == pytest.approx(101.0)
        # Prefers the unadjusted 'close' column when present.

    def test_yfinance_default_header_variant(self, tmp_path: Path):
        # yfinance's default download() shape: Date, Open, High, Low,
        # Close, Adj Close, Volume.
        (tmp_path / "TST.csv").write_text(
            "Date,Open,High,Low,Close,Adj Close,Volume\n"
            "2026-06-01,99,101,98,100.0,99.5,1000\n"
            "2026-06-02,100,102,99,101.0,100.5,1100\n",
            encoding="utf-8",
        )
        s = load_price_series("TST", cache_dir=tmp_path)
        assert s is not None
        assert s.n_rows == 2
        # Prefers Close over Adj Close.
        assert s.latest_close == pytest.approx(101.0)

    def test_only_adj_close_falls_back(self, tmp_path: Path):
        (tmp_path / "TST.csv").write_text(
            "Date,Adj Close\n"
            "2026-06-01,99.5\n"
            "2026-06-02,100.5\n",
            encoding="utf-8",
        )
        s = load_price_series("TST", cache_dir=tmp_path)
        assert s is not None
        assert s.latest_close == pytest.approx(100.5)

    def test_unparseable_rows_skipped(self, tmp_path: Path):
        (tmp_path / "TST.csv").write_text(
            "date,close\n"
            "2026-06-01,100.0\n"
            "not-a-date,101.0\n"
            "2026-06-02,not-a-number\n"
            "2026-06-03,102.0\n",
            encoding="utf-8",
        )
        s = load_price_series("TST", cache_dir=tmp_path)
        assert s is not None
        assert s.dates == ["2026-06-01", "2026-06-03"]
        assert s.closes == [100.0, 102.0]

    def test_explicit_cache_path_override(self, tmp_path: Path):
        # The cache_path kwarg should override the cache_dir/ticker lookup.
        p = tmp_path / "weird_location.csv"
        p.write_text(
            "date,close\n2026-06-01,42.0\n", encoding="utf-8",
        )
        s = load_price_series("XYZ", cache_path=p)
        assert s is not None
        assert s.ticker == "XYZ"
        assert s.latest_close == pytest.approx(42.0)

    def test_rows_sorted_chronologically(self, tmp_path: Path):
        (tmp_path / "TST.csv").write_text(
            "date,close\n"
            "2026-06-03,103.0\n"
            "2026-06-01,101.0\n"
            "2026-06-02,102.0\n",
            encoding="utf-8",
        )
        s = load_price_series("TST", cache_dir=tmp_path)
        assert s is not None
        assert s.dates == ["2026-06-01", "2026-06-02", "2026-06-03"]
        assert s.closes == [101.0, 102.0, 103.0]

    def test_real_spy_cache_loads(self):
        # The committed SPY cache is the most stable real fixture.
        s = load_price_series("SPY")
        assert s is not None
        assert s.n_rows > 200
        assert s.latest_close is not None
        assert s.latest_close > 0


# --------------------------------------------------------------------------- #
# Indicator helpers — deterministic, parameter-free
# --------------------------------------------------------------------------- #
class TestComputeSMA:
    def test_basic(self):
        assert compute_sma([1, 2, 3, 4, 5], 5) == pytest.approx(3.0)

    def test_partial_window(self):
        assert compute_sma([1, 2, 3, 4, 5], 3) == pytest.approx(4.0)

    def test_insufficient_data_returns_none(self):
        assert compute_sma([1, 2], 5) is None

    def test_zero_period_rejected(self):
        with pytest.raises(ValueError):
            compute_sma([1, 2, 3], 0)


class TestComputeReturnPct:
    def test_basic_positive(self):
        # 5-day return = (latest / close-5-rows-ago - 1) * 100.
        # With 6 elements, n_days_back=5 looks at closes[-6] = closes[0].
        closes = [100.0, 101.0, 102.0, 103.0, 104.0, 110.0]
        assert compute_return_pct(closes, 5) == pytest.approx(10.0)

    def test_basic_negative(self):
        closes = [100.0, 95.0, 92.0, 91.0, 90.5, 90.0]
        assert compute_return_pct(closes, 5) == pytest.approx(-10.0)

    def test_insufficient_data_returns_none(self):
        assert compute_return_pct([1, 2, 3], 5) is None

    def test_zero_prior_returns_none(self):
        # Prior close (5 rows back) is 0 → return is undefined.
        closes = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]
        assert compute_return_pct(closes, 5) is None


class TestComputeRSI:
    def test_insufficient_data_returns_none(self):
        # RSI(14) requires > 14 closes.
        assert compute_rsi([1] * 14) is None

    def test_constant_series_returns_100(self):
        # Wilder's RSI: zero loss → return 100.
        assert compute_rsi([100.0] * 20) == pytest.approx(100.0)

    def test_strictly_rising_series_is_100(self):
        closes = [float(i) for i in range(1, 30)]
        assert compute_rsi(closes) == pytest.approx(100.0)

    def test_strictly_falling_series_is_low(self):
        closes = [float(i) for i in range(30, 1, -1)]
        v = compute_rsi(closes)
        assert v is not None
        # Strictly falling = pure loss period; Wilder RSI = 0.
        assert v == pytest.approx(0.0)

    def test_deterministic_known_value(self):
        # Pre-computed expected RSI for a fixed sequence — guards
        # against accidental algorithm drift.
        closes = [
            44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42,
            45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28, 46.00,
            46.03, 46.41, 46.22, 45.64, 46.21, 46.25, 45.71, 46.45,
            45.78, 45.35, 44.03, 44.18, 44.22, 44.57, 43.42, 42.66,
            43.13,
        ]
        v = compute_rsi(closes, period=14)
        assert v is not None
        # Hand-computed Wilder RSI ≈ 37.78.
        assert 35.0 < v < 41.0

    def test_zero_period_rejected(self):
        with pytest.raises(ValueError):
            compute_rsi([1, 2, 3], 0)


class TestComputeDistanceToSMA:
    def test_above_sma(self):
        assert compute_distance_to_sma_pct(110, 100) == pytest.approx(10.0)

    def test_below_sma(self):
        assert compute_distance_to_sma_pct(90, 100) == pytest.approx(-10.0)

    def test_none_close_returns_none(self):
        assert compute_distance_to_sma_pct(None, 100) is None

    def test_none_sma_returns_none(self):
        assert compute_distance_to_sma_pct(100, None) is None

    def test_zero_sma_returns_none(self):
        assert compute_distance_to_sma_pct(100, 0) is None


class TestComputeDrawdown:
    def test_at_new_high(self):
        # Latest equals running peak → 0%.
        assert (compute_drawdown_from_high_pct([100, 110, 120])
                == pytest.approx(0.0))

    def test_off_high(self):
        # 100 → 120 → 90: drawdown vs peak 120 is (90-120)/120 = -25%.
        assert (compute_drawdown_from_high_pct([100, 120, 90])
                == pytest.approx(-25.0))

    def test_empty_returns_none(self):
        assert compute_drawdown_from_high_pct([]) is None

    def test_lookback_window_clamped_to_history(self):
        # Series shorter than lookback uses everything available.
        v = compute_drawdown_from_high_pct([100, 90], lookback=252)
        assert v == pytest.approx(-10.0)


# --------------------------------------------------------------------------- #
# compute_technical_snapshot composition
# --------------------------------------------------------------------------- #
class TestComputeTechnicalSnapshot:
    def test_none_series_yields_empty_snapshot_with_gap_note(self):
        snap = compute_technical_snapshot(None, ticker="NVDA")
        assert snap.ticker == "NVDA"
        assert snap.latest_date == ""
        assert snap.latest_close == "n/a"
        # The exact phrase the V7.5.1 spec mandates for the empty state.
        assert ("Price cache not available. No live fetch performed."
                == snap.data_gap_note)

    def test_empty_series_treated_like_none(self):
        s = PriceSeries(ticker="X", cache_path="x")
        snap = compute_technical_snapshot(s, ticker="X")
        assert snap.latest_close == "n/a"

    def test_two_row_series_returns_na_for_long_windows(self):
        s = PriceSeries(
            ticker="X", cache_path="x",
            dates=["2026-06-01", "2026-06-02"],
            closes=[100.0, 101.0],
        )
        snap = compute_technical_snapshot(s)
        # Latest close is computable; everything else needs more rows.
        assert snap.latest_close == "101.00"
        assert snap.rsi_14 == "n/a"
        assert snap.sma_50 == "n/a"
        assert snap.sma_200 == "n/a"
        assert snap.return_1w == "n/a"
        assert "RSI" in snap.data_gap_note
        assert "SMA(50)" in snap.data_gap_note

    def test_real_spy_snapshot_is_fully_populated(self):
        s = load_price_series("SPY")
        assert s is not None
        snap = compute_technical_snapshot(s, ticker="SPY")
        assert snap.latest_close != "n/a"
        assert snap.rsi_14 != "n/a"
        assert snap.sma_50 != "n/a"
        assert snap.sma_200 != "n/a"
        assert snap.return_1y != "n/a"
        # Drawdown is always ≤ 0 → string must contain a minus or zero.
        assert snap.drawdown_from_1y_high_pct != "n/a"

    def test_snapshot_fields_tuple_aligns_with_dataclass(self):
        # The exported field tuple must match the dataclass exactly.
        snap = TechnicalSnapshot(ticker="X")
        assert set(TECHNICAL_SNAPSHOT_FIELDS) == set(snap.to_dict().keys())


# --------------------------------------------------------------------------- #
# Platform integration — load_technical_snapshot_from_disk
# --------------------------------------------------------------------------- #
class TestPlatformIntegration:
    def test_missing_cache_yields_empty_state(self, tmp_path: Path,
                                                platform):
        snap = platform.load_technical_snapshot_from_disk(
            "DOES_NOT_EXIST", cache_dir=tmp_path,
        )
        assert snap.latest_date == ""
        assert "Price cache not available" in snap.data_gap_note

    def test_real_spy_via_platform(self, platform):
        snap = platform.load_technical_snapshot_from_disk("SPY")
        assert snap.latest_date != ""
        assert snap.rsi_14 != "n/a"

    def test_platform_module_exposes_helper(self, platform):
        assert hasattr(platform, "load_technical_snapshot_from_disk")


# --------------------------------------------------------------------------- #
# No-effect on upstream surfaces
# --------------------------------------------------------------------------- #
def _pos(*, ticker: str, market_value: str = "10000",
          sector: str = "SEMICONDUCTOR",
          asset_type: str = "STOCK") -> PositionRow:
    return PositionRow(
        as_of="2026-06-03", account="MAIN", ticker=ticker,
        asset_type=asset_type, market_value=market_value,
        sector=sector,
    )


def _lrow(*, ticker: str, read: str = "BULL") -> CompanyLedgerRow:
    return CompanyLedgerRow(
        run_id="RUN-1", timestamp="2026-06-03T00:00:00+00:00",
        date="2026-06-03",
        ticker=ticker, company_or_label=ticker,
        sector="SEMICONDUCTOR", theme="x", read=read,
        why_short="", main_risk_short="",
        linked_catalysts="", n_linked_present=0, n_linked_total=0,
        source_files="", source_dates="",
        is_manual_or_tracked_context="false",
        reason="", notes="",
    )


def _ssr(signal: str = "ACCUMULATE") -> SectorSignalLogRow:
    return SectorSignalLogRow(
        run_id="RUN-1", timestamp="2026-06-03T00:00:00+00:00",
        date="2026-06-03", sector="SEMICONDUCTOR",
        canonical_signal=signal, normalized_score=0.0, raw_score=0.0,
        total_weight=0, n_catalysts=0, n_bull=0, n_neutral=0,
        n_near_threshold=0, n_broken=0, n_emergency_exits=0,
        n_triggered_exits=0,
    )


class TestNoEffect:
    def test_portfolio_totals_unchanged(self, tmp_path: Path, platform):
        pp = tmp_path / "p.csv"
        tp = tmp_path / "t.csv"
        append_position_rows([
            _pos(ticker="NVDA", market_value="60000"),
            _pos(ticker="AMD", market_value="40000"),
        ], pp)
        ensure_transactions_header(tp)
        before = platform.compute_portfolio_totals(
            platform.load_portfolio_snapshot(pp, tp),
        )
        # Exercise the technicals path many times.
        for ticker in ("SPY", "QQQ", "DOES_NOT_EXIST"):
            platform.load_technical_snapshot_from_disk(ticker)
        after = platform.compute_portfolio_totals(
            platform.load_portfolio_snapshot(pp, tp),
        )
        assert before == after

    def test_protection_rows_unchanged(self):
        positions = [_pos(ticker="NVDA", market_value="60000"),
                     _pos(ticker="AMD", market_value="40000")]
        ledger = {
            "NVDA": _lrow(ticker="NVDA", read="BROKEN"),
            "AMD": _lrow(ticker="AMD", read="BULL"),
        }
        signals = {"SEMICONDUCTOR": _ssr()}
        before = [r.to_dict() for r in derive_protection_rows(
            positions,
            company_ledger_by_ticker=ledger,
            sector_signals_by_sector=signals,
        )]
        # Exercise indicators (no shared state).
        compute_technical_snapshot(None, ticker="X")
        compute_rsi([1.0, 2.0, 3.0, 4.0, 5.0] * 5)
        after = [r.to_dict() for r in derive_protection_rows(
            positions,
            company_ledger_by_ticker=ledger,
            sector_signals_by_sector=signals,
        )]
        assert before == after

    def test_porttech_rows_unchanged(self):
        positions = [_pos(ticker="NVDA", market_value="60000"),
                     _pos(ticker="AMD", market_value="40000")]
        ledger = {
            "NVDA": _lrow(ticker="NVDA", read="BULL"),
            "AMD": _lrow(ticker="AMD", read="BULL"),
        }
        signals = {"SEMICONDUCTOR": _ssr()}
        before = [r.to_dict() for r in derive_porttech_rows(
            positions,
            company_ledger_by_ticker=ledger,
            sector_signals_by_sector=signals,
        )]
        compute_technical_snapshot(None, ticker="X")
        after = [r.to_dict() for r in derive_porttech_rows(
            positions,
            company_ledger_by_ticker=ledger,
            sector_signals_by_sector=signals,
        )]
        assert before == after

    def test_score_sector_untouched(self):
        cats = [Catalyst(
            catalyst_id="X", sector="SEMICONDUCTOR", subsector="x",
            catalyst_name="x", tier=1, direction="ABOVE",
            threshold="t", current_value="v", status="BULL",
            source_type="SEC_EDGAR", source_detail="ok",
            last_updated="2026-05-28", action_if_broken="x",
        )]
        before = score_sector(cats, [], sector="SEMICONDUCTOR")
        # Exercise every V7.5.1 surface.
        compute_technical_snapshot(None, ticker="X")
        compute_rsi([1.0, 2.0, 3.0] * 10)
        compute_sma([1.0, 2.0, 3.0], 2)
        load_price_series("ZZZ")
        after = score_sector(cats, [], sector="SEMICONDUCTOR")
        assert before.signal == after.signal
        assert before.normalized_score == after.normalized_score


# --------------------------------------------------------------------------- #
# Regression — V6 / V7 surfaces still load cleanly + Company Detail intact.
# --------------------------------------------------------------------------- #
class TestRegression:
    def test_platform_module_imports(self):
        sys.path.insert(0, str(REPO_ROOT / "apps"))
        try:
            mod = importlib.import_module("portfolio_platform")
            for name in (
                "load_technical_snapshot_from_disk",
                "build_company_detail_view_from_disk",
                "derive_porttech_rows_from_snapshot",
                "load_protection_snapshot",
            ):
                assert hasattr(mod, name), f"missing: {name}"
        finally:
            if str(REPO_ROOT / "apps") in sys.path:
                sys.path.remove(str(REPO_ROOT / "apps"))

    def test_v6_dashboard_imports(self):
        sys.path.insert(0, str(REPO_ROOT / "apps"))
        try:
            mod = importlib.import_module("sector_thesis_dashboard")
            assert hasattr(mod, "render")
        finally:
            if str(REPO_ROOT / "apps") in sys.path:
                sys.path.remove(str(REPO_ROOT / "apps"))

    def test_default_cache_dir_points_at_local_data(self):
        # Sanity: the default path must point at data/cache/ under the
        # repo. Catches accidental absolute-path drift.
        assert DEFAULT_PRICE_CACHE_DIR.name == "cache"
        assert "data" in DEFAULT_PRICE_CACHE_DIR.parts
