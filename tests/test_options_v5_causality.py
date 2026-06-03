"""V5.0: causality and no-look-ahead invariants.

These tests guard the engine's hard contract: a decision on bar ``t`` may
only use ``chain[date == t]`` and may only fill on a STRICTLY later bar.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import pytest

from quantbot.options.backtest_engine import OptionsBacktestEngine
from quantbot.options.spreads import build_bull_call_spread
from quantbot.options.strategy_base import OptionsStrategy

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).parent))
from test_options_backtest_engine import _make_chain  # noqa: E402


@dataclass
class _Spy(OptionsStrategy):
    """Records the decision-day dates it was called on, and asserts that the
    chain slice it gets contains ONLY rows for that date."""
    name: str = "spy"
    underlying: str = "SPY"
    seen_dates: list = None
    chain_dates_per_call: list = None
    _fired: bool = False

    def __post_init__(self):
        self.seen_dates = []
        self.chain_dates_per_call = []

    def on_decision_open(self, t, chain_today, portfolio):
        self.seen_dates.append(t)
        # Capture EVERY unique date the strategy "sees" on this call.
        dates_seen = sorted(pd.to_datetime(chain_today["date"]).unique().tolist())
        self.chain_dates_per_call.append(dates_seen)
        if self._fired:
            return None
        self._fired = True
        return build_bull_call_spread(chain_today, dte_min=25, dte_max=40)

    def on_decision_close(self, position, chain_today, t):
        # The chain_today passed here must also be single-day.
        dates_seen = sorted(pd.to_datetime(chain_today["date"]).unique().tolist())
        assert len(dates_seen) <= 1, (
            f"close decision saw multiple chain dates: {dates_seen}"
        )
        return False, ""


# --------------------------------------------------------------------------- #
def test_strategy_only_ever_sees_single_day_chain():
    chain = _make_chain(n_days=15)
    spy = _Spy()
    eng = OptionsBacktestEngine(chain, spy)
    eng.run()
    assert len(spy.seen_dates) >= 1
    for t, dates_seen in zip(spy.seen_dates, spy.chain_dates_per_call):
        assert dates_seen == [pd.Timestamp(t)], (
            f"on decision date {t}, strategy saw {dates_seen}"
        )


def test_no_order_fills_on_decision_day():
    chain = _make_chain(n_days=20)
    spy = _Spy()
    eng = OptionsBacktestEngine(chain, spy)
    res = eng.run()
    assert res.n_trades >= 1
    for o in res.orders:
        dd = o.get("decision_date")
        fd = o.get("fill_date")
        if dd is None:
            continue   # expiration / force-close has no decision_date
        assert pd.Timestamp(dd) < pd.Timestamp(fd), (
            f"order filled same-day or earlier: decision={dd} fill={fd}"
        )


def test_open_decision_skipped_on_final_bar():
    """The engine never queues an open on the last bar (no next bar to fill on)."""
    chain = _make_chain(n_days=8)
    last_date = chain["date"].max()
    spy = _Spy()
    eng = OptionsBacktestEngine(chain, spy)
    eng.run()
    assert last_date not in spy.seen_dates


def test_decisions_run_in_date_order():
    chain = _make_chain(n_days=12)
    spy = _Spy()
    eng = OptionsBacktestEngine(chain, spy)
    eng.run()
    # seen_dates is strictly monotonically increasing.
    for a, b in zip(spy.seen_dates, spy.seen_dates[1:]):
        assert a < b


def test_engine_asserts_on_same_day_open(monkeypatch):
    """Tampering with a queued open to set decision_date == fill_date must
    trip the engine's hard causality assertion."""
    chain = _make_chain(n_days=10)
    spy = _Spy()
    eng = OptionsBacktestEngine(chain, spy)

    real_execute = eng._execute_pending_opens

    def tampered(t, chain_today):
        # Move every pending open's decision date forward to today (illegal).
        for po in eng._pending_opens:
            po.decision_date = pd.Timestamp(t)
        return real_execute(t, chain_today)

    monkeypatch.setattr(eng, "_execute_pending_opens", tampered)
    with pytest.raises(AssertionError, match="causality"):
        eng.run()
