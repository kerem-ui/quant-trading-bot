"""S07 - Volatility Skew / Risk Reversal. INACTIVE in v1.

Trade abnormal option skew with DEFINED-RISK structures (e.g. sell rich OTM
put spread when put-skew percentile is extreme and trend is non-panic). No
naked short puts. Requires an IV surface (chain by strike/maturity). Disabled
in strategy_configs.json.
"""

from __future__ import annotations

import pandas as pd

from .base import Strategy

ACTIVE = False


class S07SkewStrategy(Strategy):
    name = "S07_skew_strategy"

    def generate_signals(self, panel):  # pragma: no cover - inactive
        raise NotImplementedError("S07 inactive in v1: needs options IV surface.")

    def target_weights(self, panel) -> pd.DataFrame:  # pragma: no cover
        raise NotImplementedError("S07 inactive in v1: needs options IV surface.")
