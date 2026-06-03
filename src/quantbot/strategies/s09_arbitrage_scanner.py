"""S09 - Synthetic Arbitrage Scanner. RESEARCH SCANNER ONLY (never auto-trades).

Flags apparent put-call parity / box / butterfly-convexity violations after
costs + financing + a safety buffer. v1 is report-only by design; it routes no
orders. The actual scanning logic lives in :mod:`quantbot.options.parity`; this
module is a thin strategy-shaped wrapper kept inactive on the trading path.
"""

from __future__ import annotations

import pandas as pd

from .base import Strategy

ACTIVE = False
DO_NOT_AUTO_TRADE = True


class S09ArbitrageScanner(Strategy):
    name = "S09_arbitrage_scanner"

    def generate_signals(self, panel):  # pragma: no cover - scanner only
        raise NotImplementedError(
            "S09 is a research scanner, not a trading strategy. "
            "Use options.parity.scan_parity_violations()."
        )

    def target_weights(self, panel) -> pd.DataFrame:  # pragma: no cover
        raise NotImplementedError("S09 never produces tradable weights in v1 (scanner only).")
