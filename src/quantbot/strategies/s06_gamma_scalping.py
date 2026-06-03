"""S06 - Long Gamma Scalping. INACTIVE in v1.

Buy cheap options (IV percentile low, forecast RV > IV), delta-hedge to
monetise realized movement. Requires options chain + intraday/daily underlying
and a hedging simulator. Disabled in strategy_configs.json. Long premium only
(defined risk); no naked shorts.
"""

from __future__ import annotations

import pandas as pd

from .base import Strategy

ACTIVE = False


class S06GammaScalping(Strategy):
    name = "S06_long_gamma_scalping"

    def generate_signals(self, panel):  # pragma: no cover - inactive
        raise NotImplementedError("S06 inactive in v1: needs options chain + hedging sim.")

    def target_weights(self, panel) -> pd.DataFrame:  # pragma: no cover
        raise NotImplementedError("S06 inactive in v1: needs options chain + hedging sim.")
