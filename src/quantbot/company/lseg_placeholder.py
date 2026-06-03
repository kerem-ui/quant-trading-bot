"""LSEG / Refinitiv Datastream connector -- DESIGN PLACEHOLDER ONLY.

Nothing here connects to anything. This stage (read-only company/fundamentals
research) is built entirely on the free, official SEC EDGAR source and does
NOT require LSEG. This module exists only to record the future design so the
intent is discoverable in code.

Future scope (only if a license + API access are CONFIRMED separately):
  - Company fundamentals beyond SEC XBRL (normalised, point-in-time).
  - Reuters news / headlines for event context.
  - Analyst estimates / consensus (revenue, EPS).
  - Broader/cleaner macro series than the FRED set.

Constraints that would still apply:
  - Read-only, additive, "not a trading signal" (same as the V5.7 macro layer
    and the SEC layer here).
  - Credentials via environment variables only, never hardcoded or printed.
  - Local caching + graceful degradation, like ``sec_edgar`` / ``fred_loader``.
  - No broker / live / IBKR. ``LIVE_TRADING_ENABLED`` stays False.
"""

from __future__ import annotations

LSEG_DESIGN_NOTE = (
    "LSEG/Datastream is a future, optional enrichment (fundamentals, Reuters "
    "news, analyst estimates, macro). Not implemented; not required for the "
    "SEC EDGAR company research stage. Would be read-only, env-var auth, "
    "cached, no broker, LIVE_TRADING_ENABLED stays False."
)


def is_available() -> bool:
    """Always False -- the connector is not implemented in this stage."""
    return False
