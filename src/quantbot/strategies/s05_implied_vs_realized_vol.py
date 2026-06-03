"""S05 - Implied-vs-Realized Volatility. INACTIVE strategy in v1 (research only).

Logic (documented for later): compare an EWMA realized-vol forecast with ATM
implied vol from an options chain; if IV percentile is high and the volatility
risk premium exceeds a threshold, propose a DEFINED-RISK short-vol structure
(iron condor / credit spread). No naked shorts, ever. Reject wide bid/ask.

No free historical options chain is wired in v1, so this is disabled in
strategy_configs.json. The options utilities (payoff/greeks/structures) and a
synthetic chain exist so this can be prototyped; any such result is approximate.
"""

from __future__ import annotations

import pandas as pd

from .base import Strategy

ACTIVE = False


class S05ImpliedVsRealizedVol(Strategy):
    name = "S05_implied_vs_realized_vol"

    def generate_signals(self, panel):  # pragma: no cover - inactive
        raise NotImplementedError(
            "S05 inactive in v1: requires options-chain data. "
            "Use options.* utilities + data.options_loader.synthetic_option_chain "
            "for approximate research."
        )

    def target_weights(self, panel) -> pd.DataFrame:  # pragma: no cover
        raise NotImplementedError("S05 inactive in v1 (defined-risk options, no chain data).")
