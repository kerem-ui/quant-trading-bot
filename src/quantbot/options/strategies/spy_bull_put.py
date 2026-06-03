"""V5.3 SPY bull put CREDIT spread (defined-risk).

Cross-checks the engine's credit-side path. The protective long-put wing is
always included -- the spread builder refuses to construct (and the risk
gate refuses to accept) a naked short put.

Defaults mirror the debit verticals in cadence and exit rules; the only
material differences are the leg signs (credit instead of debit) and the
delta targets (-0.30 short / -0.15 long wing) which are conservative
out-of-the-money picks consistent with the "no naked / no unlimited risk"
rule.

  - SPY only
  - DTE band [30, 45]
  - short put delta ~ -0.30, long put wing delta ~ -0.15
  - max width $10  -> max defined loss = (width*100 - credit) <= $1000
  - weekly entry on the first trading day of each ISO week
  - exit: DTE <= 21 OR paper_pnl >= 50% credit OR paper_pnl <= -|max_loss|

Purpose: cross-validate the engine's credit-side accounting. NOT a
recommendation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from ..spreads import Candidate, build_bull_put_spread
from ..strategy_base import OptionsStrategy


@dataclass
class SPYBullPutSpread(OptionsStrategy):
    name: str = "spy_bull_put_spread_v53"
    underlying: str = "SPY"
    dte_min: int = 30
    dte_max: int = 45
    short_delta: float = -0.30
    long_delta: float = -0.15
    max_width: float = 10.0
    spread_max_pct: float = 0.25
    exit_dte: int = 21
    profit_target_frac: float = 0.50          # exit at 50% of max profit (credit)
    stop_loss_frac: float = 1.0               # exit at full defined-loss
    entry_weekday: int | None = 0              # Monday only

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
        return build_bull_put_spread(
            sub, underlying=self.underlying,
            dte_min=self.dte_min, dte_max=self.dte_max,
            short_delta=self.short_delta, long_delta=self.long_delta,
            max_width=self.max_width,
            spread_max_pct=self.spread_max_pct,
        )

    def on_decision_close(self, position, chain_today, t):
        # DTE-based exit
        dte_now = position.dte(t)
        if dte_now <= self.exit_dte:
            return True, "dte_exit"
        # Profit target on paper P&L (credit shrinks toward 0 = profit).
        if position.max_profit > 0 and position.paper_pnl >= (
                self.profit_target_frac * position.max_profit):
            return True, "profit_target"
        # Stop-loss: lose the full defined max-loss
        if position.paper_pnl <= self.stop_loss_frac * position.max_loss:
            return True, "stop_loss"
        return False, ""
