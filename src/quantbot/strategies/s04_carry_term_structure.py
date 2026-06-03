"""S04 - Carry / Futures Term Structure. INACTIVE in v1.

Requires a real futures chain (front/next contracts, expiries, roll schedule,
settlements). No free source is wired in v1, so ``enabled=false`` in
strategy_configs.json. Module kept so the data contract is explicit.
"""

from __future__ import annotations

import pandas as pd

from .base import Strategy

ACTIVE = False


def compute_annualized_carry(front_price, next_price, days_between):
    """(front/next - 1) * (365 / days_between). Pure helper, usable in research."""
    if days_between <= 0:
        return float("nan")
    return (front_price / next_price - 1.0) * (365.0 / days_between)


class S04CarryTermStructure(Strategy):
    name = "S04_carry_term_structure"

    def generate_signals(self, panel):  # pragma: no cover - inactive
        raise NotImplementedError(
            "S04 inactive in v1: requires futures-chain data (see futures_loader)."
        )

    def target_weights(self, panel) -> pd.DataFrame:  # pragma: no cover
        raise NotImplementedError(
            "S04 inactive in v1: requires futures-chain data (see futures_loader)."
        )
