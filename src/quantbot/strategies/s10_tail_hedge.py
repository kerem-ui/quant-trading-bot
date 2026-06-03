"""S10 - Tail Hedge / Portfolio Insurance Overlay. INACTIVE overlay in v1.

A cost-center overlay (OTM index put spreads / beta reduction) intended to run
*on top of* the core book to cut crash drawdowns - not a standalone alpha. Put
overlay needs an options chain; the dynamic beta-reduction variant could run on
ETFs in a later version. Disabled in strategy_configs.json.
"""

from __future__ import annotations

import pandas as pd

from .base import Strategy

ACTIVE = False
OVERLAY_ONLY = True


class S10TailHedge(Strategy):
    name = "S10_tail_hedge_overlay"

    def generate_signals(self, panel):  # pragma: no cover - inactive overlay
        raise NotImplementedError("S10 inactive in v1: risk overlay, not standalone alpha.")

    def target_weights(self, panel) -> pd.DataFrame:  # pragma: no cover
        raise NotImplementedError("S10 inactive in v1: risk overlay, not standalone alpha.")
