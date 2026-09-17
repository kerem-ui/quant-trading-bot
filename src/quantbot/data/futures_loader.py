"""Futures chain loader placeholder.

S04 (carry / term structure) requires a real futures chain (front/next
contracts, expiries, roll schedule, settlements). No such free source is wired
in v1, so S04 is disabled in strategy_configs.json. This module documents the
required schema so the data contract is explicit.
"""

from __future__ import annotations

import pandas as pd

FUTURES_SCHEMA = (
    "date", "root_symbol", "contract", "expiration", "settlement",
    "volume", "open_interest",
)
FUTURES_OPTIONAL = ("bid", "ask", "first_notice_date", "roll_date")


def load_futures_chain(*args, **kwargs) -> pd.DataFrame:
    raise NotImplementedError(
        "Futures-chain data is unavailable in v1; S04 is inactive. "
        f"Required schema: {FUTURES_SCHEMA}."
    )
