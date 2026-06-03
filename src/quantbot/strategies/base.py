"""Strategy base class.

Contract with the engine:
  - ``rebalance_frequency``: 'daily' | 'weekly' | 'monthly'
  - ``target_weights(panel) -> DataFrame`` indexed by date, columns = symbols,
    where **every row uses only data up to that row's date** (causal). The
    engine additionally enforces next-bar execution, so look-ahead is
    prevented at two independent layers.
  - ``explain_signal(symbol, date)`` for human-readable diagnostics.

Strategies output *raw* target weights. Volatility targeting, exposure caps and
kill switches are applied centrally by the RiskManager inside the engine.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class Strategy(ABC):
    name: str = "base"
    rebalance_frequency: str = "weekly"
    long_only: bool = True
    # V2 risk hooks read by the engine -> RiskManager:
    #   market_neutral=True  -> vol targeting may lever the (hedged) book up
    #                           toward target, bounded by the gross cap.
    #   allow_leverage_up    -> directional opt-in for two-sided vol targeting
    #                           (None = use RiskManager default = off).
    market_neutral: bool = False
    allow_leverage_up: bool | None = None

    def __init__(self, config: dict | None = None, sector_map: dict | None = None):
        self.config = config or {}
        self.sector_map = sector_map
        self._signals: pd.DataFrame | None = None
        self._explain: dict = {}

    # --- helpers ------------------------------------------------------------
    @staticmethod
    def _wide(panel: dict[str, pd.DataFrame], field: str = "adjusted_close") -> pd.DataFrame:
        return pd.DataFrame({s: df[field] for s, df in panel.items()}).sort_index()

    def prepare_data(self, panel: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
        """Hook for per-strategy cleaning. Default: require adjusted_close."""
        for s, df in panel.items():
            if "adjusted_close" not in df.columns:
                raise ValueError(f"{s}: adjusted_close required (corporate actions).")
        return panel

    # --- interface ----------------------------------------------------------
    @abstractmethod
    def generate_signals(self, panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
        """Causal signal panel (date x symbol)."""

    @abstractmethod
    def target_weights(self, panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
        """Causal raw target-weight panel (date x symbol). Engine entrypoint."""

    def explain_signal(self, symbol: str, date) -> dict:
        """Default explainability payload; strategies may enrich ``_explain``."""
        date = pd.Timestamp(date)
        info = {
            "strategy": self.name,
            "symbol": symbol,
            "date": str(date.date()),
        }
        if self._signals is not None and date in self._signals.index:
            info["signal"] = float(self._signals.at[date, symbol]) if symbol in self._signals.columns else None
        info.update(self._explain.get((symbol, date), {}))
        return info

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Strategy {self.name} rebalance={self.rebalance_frequency} long_only={self.long_only}>"
