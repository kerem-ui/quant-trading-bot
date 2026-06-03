"""V5.7 macro research layer (read-only).

Submodules:
  - fred_loader      : FRED series fetch with env-var key, graceful fallback
  - market_proxies   : yfinance-based proxies (VIX, HYG/LQD, etc.) with cache
  - macro_indicators : derived features (MAs, returns, spreads, vol)
  - regime_classifier: simple, transparent regime labels (trend/vol/rates/credit)

This package is RESEARCH-ONLY. It does not connect to a broker, never places
orders, never feeds back into strategy decisions. ``quantbot.LIVE_TRADING_ENABLED``
must remain ``False``.
"""

from __future__ import annotations
