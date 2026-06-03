"""S08 - Calendar / Term-Structure Volatility Spread. INACTIVE in v1.

Trade near- vs longer-term IV mispricing with defined-risk calendars. Requires
options chain across expiries + an event calendar. Disabled in
strategy_configs.json.
"""

from __future__ import annotations

import pandas as pd

from .base import Strategy

ACTIVE = False


class S08CalendarVolSpread(Strategy):
    name = "S08_calendar_vol_spread"

    def generate_signals(self, panel):  # pragma: no cover - inactive
        raise NotImplementedError("S08 inactive in v1: needs multi-expiry options chain.")

    def target_weights(self, panel) -> pd.DataFrame:  # pragma: no cover
        raise NotImplementedError("S08 inactive in v1: needs multi-expiry options chain.")
