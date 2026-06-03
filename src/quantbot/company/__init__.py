"""Company / fundamentals research layer (read-only).

RESEARCH ONLY. This package fetches and indexes public company filings and
fundamentals from official/free sources (SEC EDGAR first). It produces
research reports and descriptive context. It NEVER:

  - emits a trading signal,
  - connects filings to any strategy or backtest decision,
  - touches a broker / live / IBKR path,
  - fetches options/ThetaData,
  - requires or prints credentials.

Everything here is additive and labelled "not a trading signal", mirroring
the V5.7 macro/event annotation layer. ``quantbot.LIVE_TRADING_ENABLED``
stays False.
"""

from __future__ import annotations

from . import company_facts, company_report, filing_index, filing_parser, sec_edgar

__all__ = [
    "sec_edgar",
    "filing_index",
    "company_facts",
    "filing_parser",
    "company_report",
]
