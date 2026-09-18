"""V5.0 options strategy base.

Strategies expose two lifecycle hooks called by the backtest engine:
  - ``on_decision_open(t, chain_today, portfolio)`` -> Candidate | None
  - ``on_decision_close(position, chain_today, t)`` -> (bool, reason)

Causality: a strategy receives only ``chain_today`` (= chain rows where
``date == t``) plus its prior internal state. It MUST NOT peek at future
rows. The engine enforces fill-on-next-bar regardless of strategy intent.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

from .spreads import Candidate
from .risk import RiskDecision


class OptionsStrategy(ABC):
    name: str = "base"
    underlying: str = ""

    @abstractmethod
    def on_decision_open(
        self, t: pd.Timestamp, chain_today: pd.DataFrame, portfolio,
    ) -> Candidate | None:
        """Return a Candidate to open at the NEXT bar, or ``None`` to skip."""

    @abstractmethod
    def on_decision_close(
        self, position, chain_today: pd.DataFrame, t: pd.Timestamp,
    ) -> tuple[bool, str]:
        """Return (True, reason) to schedule a close at the next bar."""

    def admit_execution(self, candidate, fill, t, chain_today, portfolio, initial_capital):
        """Optional stricter strategy checks after actual quotes, before ledger mutation.

        Existing strategies retain their central risk decisions unchanged.
        """
        return RiskDecision(True)
