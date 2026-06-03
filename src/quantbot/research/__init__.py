"""V5.7 research analysis layer (read-only).

Submodules:
  - price_moves    : detect strongest / weakest return windows for a ticker
  - trade_context  : annotate strategy trades with macro/market context
  - reporting      : write CSV/Markdown research artifacts

This package is RESEARCH-ONLY. It never mutates strategy outputs, never
runs a backtest, never connects to a broker, never feeds context back into
strategy decisions. ``quantbot.LIVE_TRADING_ENABLED`` stays ``False``.
"""

from __future__ import annotations
