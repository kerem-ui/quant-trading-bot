"""V5.3 SPY bear put debit spread (defined-risk).

Mirrors :class:`SPYBullCallSpread` exactly:
  - SPY only
  - DTE band [30, 45]  (engine's selector soft-falls back to closest)
  - long put delta ~ -0.50, short put delta ~ -0.30, max width $10
  - weekly entry on the first trading day of each ISO week
  - exit: DTE <= 21 OR paper_pnl >= 50% max_profit OR paper_pnl <= -|debit|

Purpose: cross-check the engine on a bearish DEBIT vertical using the same
defaults, parameters, and lifecycle hooks as the bull call proof strategy.
NOT a strategy recommendation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from ..spreads import Candidate, build_bear_put_spread
from ..strategy_base import OptionsStrategy


@dataclass
class SPYBearPutSpread(OptionsStrategy):
    name: str = "spy_bear_put_spread_v53"
    underlying: str = "SPY"
    dte_min: int = 30
    dte_max: int = 45
    long_delta: float = -0.50
    short_delta: float = -0.30
    max_width: float = 10.0
    spread_max_pct: float = 0.25
    exit_dte: int = 21
    profit_target_frac: float = 0.50          # exit at 50% of max profit
    stop_loss_frac: float = 1.0               # exit at full debit lost
    entry_weekday: int | None = 0              # Monday only; None = any day

    _weeks_attempted: set = field(default_factory=set)

    # --- lifecycle ----------------------------------------------------- #
    def _new_week(self, t: pd.Timestamp) -> bool:
        iso = (t.isocalendar().year, t.isocalendar().week)
        if iso in self._weeks_attempted:
            return False
        self._weeks_attempted.add(iso)
        return True

    def on_decision_open(self, t, chain_today, portfolio):
        if chain_today.empty:
            return None
        if not self._new_week(t):
            return None
        sub = chain_today[chain_today["underlying"].str.upper()
                          == self.underlying.upper()]
        if sub.empty:
            return None
        return build_bear_put_spread(
            sub, underlying=self.underlying,
            dte_min=self.dte_min, dte_max=self.dte_max,
            long_delta=self.long_delta, short_delta=self.short_delta,
            max_width=self.max_width,
            spread_max_pct=self.spread_max_pct,
        )

    def on_decision_close(self, position, chain_today, t):
        # DTE-based exit (avoid gamma cliff)
        dte_now = position.dte(t)
        if dte_now <= self.exit_dte:
            return True, "dte_exit"
        # Profit target on paper P&L
        if position.max_profit > 0 and position.paper_pnl >= (
                self.profit_target_frac * position.max_profit):
            return True, "profit_target"
        # Stop-loss: lose the full debit (max_loss is signed <= 0).
        if position.paper_pnl <= self.stop_loss_frac * position.max_loss:
            return True, "stop_loss"
        return False, ""
