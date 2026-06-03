"""V5.0: backtest engine mechanics tests.

Uses a small synthetic chain so the test has no external dependency. The
strategies under test are minimal stand-ins (open one spread, close on
DTE<=21) -- the goal is to exercise engine plumbing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd
import pytest

from quantbot.costs.transaction_costs import OptionsCostModel
from quantbot.options.backtest_engine import OptionsBacktestEngine
from quantbot.options.risk import OptionsRiskLimits
from quantbot.options.spreads import Candidate, build_bull_call_spread
from quantbot.options.strategy_base import OptionsStrategy


# --------------------------------------------------------------------------- #
# Synthetic chain helpers
# --------------------------------------------------------------------------- #
def _make_chain(
    *, n_days: int = 25,
    start: str = "2022-01-03",
    spot_path: list[float] | None = None,
    expirations_after: tuple[int, ...] = (30, 45),
) -> pd.DataFrame:
    """Build a deterministic SPY-style chain.

    Each trading day has the same call ladder (4 strikes around the initial
    spot, FIXED for the run) for a FIXED set of expirations (snapped to the
    requested DTEs relative to the START date, like real exchange-listed
    series). Quotes are intrinsic + a small time-value component that decays
    with DTE.
    """
    dates = pd.bdate_range(start, periods=n_days)
    if spot_path is None:
        spot_path = [400.0 + 0.5 * i for i in range(n_days)]   # gentle uptrend
    assert len(spot_path) == n_days

    # Fixed expiration calendar relative to start (real exchange behaviour).
    start_ts = pd.Timestamp(start)
    fixed_expirations = [start_ts + pd.Timedelta(days=off)
                          for off in expirations_after]
    # Fixed strike ladder, centred on the starting spot.
    base_strikes_by_exp: dict[pd.Timestamp, list[float]] = {
        exp: [float(round(spot_path[0] + k_off))
              for k_off in (-5, 0, 5, 10)]
        for exp in fixed_expirations
    }

    rows = []
    for date, spot in zip(dates, spot_path):
        for exp in fixed_expirations:
            dte = (exp - date).days
            if dte < 0:
                continue
            time_value = max(0.5, dte * 0.05)
            for strike in base_strikes_by_exp[exp]:
                k_off = strike - spot   # used only for the synthetic delta
                intrinsic = max(0.0, spot - strike)
                mid = intrinsic + time_value * (1.0 - 0.04 * abs(k_off))
                mid = max(mid, 0.10)
                half = 0.05
                bid = round(mid - half, 2)
                ask = round(mid + half, 2)
                # Crude monotonic delta in strike-space (calls).
                delta = max(0.05, min(0.95,
                                       0.50 - 0.04 * k_off))
                rows.append({
                    "date": pd.Timestamp(date),
                    "underlying": "SPY",
                    "expiration": pd.Timestamp(exp),
                    "dte": int(dte),
                    "option_type": "call",
                    "strike": strike,
                    "bid": bid, "ask": ask, "mid": (bid + ask) / 2,
                    "volume": 100, "open_interest": 1000,
                    "implied_volatility": 0.20,
                    "delta": delta, "gamma": 0.02,
                    "theta": -0.05, "vega": 0.10,
                    "underlying_price": float(spot),
                    "contract_multiplier": 100,
                    "exercise_style": "american",
                })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Tiny test strategies
# --------------------------------------------------------------------------- #
@dataclass
class _OneShotBullCall(OptionsStrategy):
    """Opens exactly one bull call spread on the first call, never again."""
    name: str = "test_one_shot"
    underlying: str = "SPY"
    _fired: bool = False
    exit_dte: int = 21

    def on_decision_open(self, t, chain_today, portfolio):
        if self._fired or chain_today.empty:
            return None
        self._fired = True
        return build_bull_call_spread(
            chain_today, underlying="SPY", dte_min=25, dte_max=40,
            long_delta=0.50, short_delta=0.30, max_width=10.0,
        )

    def on_decision_close(self, position, chain_today, t):
        if position.dte(t) <= self.exit_dte:
            return True, "dte_exit"
        return False, ""


@dataclass
class _NeverTrade(OptionsStrategy):
    name: str = "never_trade"
    underlying: str = "SPY"

    def on_decision_open(self, t, chain_today, portfolio):
        return None

    def on_decision_close(self, position, chain_today, t):
        return False, ""


@dataclass
class _OpenOpenOpen(OptionsStrategy):
    """Tries to open every bar (max_concurrent_positions=1 test)."""
    name: str = "open_every_bar"
    underlying: str = "SPY"

    def on_decision_open(self, t, chain_today, portfolio):
        if chain_today.empty:
            return None
        return build_bull_call_spread(
            chain_today, underlying="SPY", dte_min=25, dte_max=40,
            long_delta=0.50, short_delta=0.30, max_width=10.0,
        )

    def on_decision_close(self, position, chain_today, t):
        return False, ""


@dataclass
class _NakedCandidate(OptionsStrategy):
    """Submits an is_naked candidate -> must be rejected by risk."""
    name: str = "naked_test"
    underlying: str = "SPY"
    _fired: bool = False

    def on_decision_open(self, t, chain_today, portfolio):
        if self._fired or chain_today.empty:
            return None
        self._fired = True
        cand = build_bull_call_spread(chain_today, dte_min=25, dte_max=40)
        if cand.reject_reason:
            return cand
        return Candidate(
            structure_name=cand.structure_name,
            underlying=cand.underlying,
            expiration=cand.expiration, legs=cand.legs,
            fill=cand.fill, net_cash=cand.net_cash,
            max_profit=cand.max_profit, max_loss=cand.max_loss,
            width=cand.width, is_naked=True,
        )

    def on_decision_close(self, position, chain_today, t):
        return False, ""


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #
def test_engine_runs_without_strategy_activity():
    chain = _make_chain(n_days=10)
    eng = OptionsBacktestEngine(chain, _NeverTrade())
    res = eng.run()
    assert res.n_trades == 0
    assert len(res.equity_curve) == 10
    # Equity is flat == initial capital.
    assert (res.equity_curve == res.initial_capital).all()
    assert res.total_cost == 0.0


def test_engine_opens_and_closes_round_trip():
    chain = _make_chain(n_days=25)
    eng = OptionsBacktestEngine(chain, _OneShotBullCall())
    res = eng.run()
    assert res.n_trades == 1
    t = res.trades[0]
    # Open cash flow: net_entry_cash is negative (debit). Cash dropped by
    # |net_entry_cash| + open_cost on the fill_open day; on fill_close we
    # got close_cash back minus close_cost. Realized P&L identity:
    #   realized_pnl = net_entry_cash + (close_cash) - open_cost - close_cost
    # We can't observe close_cash externally here but realized_pnl is fully
    # captured.
    assert t.fill_open > t.decision_open       # next-bar fill
    assert t.fill_close > t.decision_close     # next-bar close fill
    assert t.fill_close > t.fill_open
    # Equity ended at initial + realized_pnl (single round-trip).
    assert float(res.equity_curve.iloc[-1]) == pytest.approx(
        res.initial_capital + t.realized_pnl, abs=1.0,
    )


def test_engine_marks_to_market_daily():
    chain = _make_chain(n_days=20)
    eng = OptionsBacktestEngine(chain, _OneShotBullCall())
    res = eng.run()
    g = res.daily_greeks
    assert not g.empty
    # On days the spread was live, |delta| > 0; on flat days, delta == 0.
    nonzero = (g["delta"].abs() > 1e-9).sum()
    assert nonzero >= 1, "MTM Greeks should be non-zero on at least one day"


def test_engine_respects_max_concurrent_positions():
    chain = _make_chain(n_days=30)
    eng = OptionsBacktestEngine(
        chain, _OpenOpenOpen(),
        limits=OptionsRiskLimits(max_concurrent_positions=1, max_debit_per_trade=1e9,
                                  max_loss_per_trade=1e9,
                                  max_portfolio_defined_loss_pct=1.0),
    )
    res = eng.run()
    # At least one rejection due to the position cap.
    rej = [r for r in res.rejections
           if r.reason == "max_concurrent_positions"]
    assert len(rej) >= 1


def test_engine_rejects_naked_candidate():
    chain = _make_chain(n_days=15)
    eng = OptionsBacktestEngine(chain, _NakedCandidate())
    res = eng.run()
    assert res.n_trades == 0
    rej = [r for r in res.rejections if r.reason == "naked_not_allowed"]
    assert len(rej) == 1


def test_engine_force_closes_open_position_on_final_bar():
    """Long-DTE spread opened near end -> still open at final bar -> forced close."""
    # 10 days, expirations 30/45 days out -> position cannot expire in-window.
    chain = _make_chain(n_days=10, expirations_after=(30, 45))

    @dataclass
    class _NeverExit(OptionsStrategy):
        name: str = "never_exit"; underlying: str = "SPY"
        _fired: bool = False
        def on_decision_open(self, t, chain_today, portfolio):
            if self._fired:
                return None
            self._fired = True
            return build_bull_call_spread(chain_today, dte_min=25, dte_max=40)
        def on_decision_close(self, position, chain_today, t):
            return False, ""

    eng = OptionsBacktestEngine(chain, _NeverExit())
    res = eng.run()
    assert res.n_trades == 1
    assert res.trades[0].close_reason == "force_close_final_bar"
    # Final bar fill date == last chain date.
    assert res.trades[0].fill_close == chain["date"].max()


def test_engine_settles_at_expiration():
    """If expiration falls inside the test window, position settles to
    intrinsic and close_reason == 'expiration'."""
    # 60 days so a 30-DTE expiration lands inside the window.
    chain = _make_chain(n_days=60, expirations_after=(30,))

    @dataclass
    class _OpenAndHold(OptionsStrategy):
        name: str = "open_and_hold"; underlying: str = "SPY"
        _fired: bool = False
        def on_decision_open(self, t, chain_today, portfolio):
            if self._fired:
                return None
            self._fired = True
            return build_bull_call_spread(chain_today, dte_min=25, dte_max=40)
        def on_decision_close(self, position, chain_today, t):
            return False, ""

    eng = OptionsBacktestEngine(chain, _OpenAndHold())
    res = eng.run()
    assert res.n_trades >= 1
    # First trade should expire (no force close needed inside the window).
    reasons = [t.close_reason for t in res.trades]
    assert "expiration" in reasons


def test_engine_costs_reduce_returns():
    """Compare zero-cost vs default cost on the same chain/strategy."""
    chain = _make_chain(n_days=25)
    eng_costly = OptionsBacktestEngine(
        chain, _OneShotBullCall(),
        cost_model=OptionsCostModel(per_contract_fee=2.0, bid_ask_fraction=0.5,
                                     multi_leg_penalty=2.0),
    )
    eng_free = OptionsBacktestEngine(
        chain, _OneShotBullCall(),
        cost_model=OptionsCostModel(per_contract_fee=0.0, bid_ask_fraction=0.0,
                                     multi_leg_penalty=0.0),
    )
    r_costly = eng_costly.run()
    r_free = eng_free.run()
    # Both should make a trade; the costly path must have a worse realized PnL.
    assert r_costly.n_trades == 1 and r_free.n_trades == 1
    assert r_costly.trades[0].realized_pnl < r_free.trades[0].realized_pnl
    assert r_costly.total_cost > r_free.total_cost
