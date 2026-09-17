"""Provider-agnostic options chain loader interface.

Defines the canonical schema every loader must emit and an abstract base class
that providers (synthetic, ThetaData, ...) implement. Adapters register
themselves so the rest of the codebase only ever sees the canonical schema.

V4 is OFFLINE / READ-ONLY plumbing. Loaders may talk to a historical data
provider, but never to a broker or live feed.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import pandas as pd

OPTIONS_SCHEMA_VERSION = 1

# Canonical column order + dtypes. Every loader returns DataFrames with these
# columns (extras allowed but ignored by the validator). Optional columns may
# contain NaN; required columns may not.
REQUIRED_COLS: tuple[str, ...] = (
    "date", "underlying", "expiration", "dte", "option_type", "strike",
    "bid", "ask", "mid",
    "volume", "open_interest",
    "implied_volatility",
    "delta", "gamma", "theta", "vega",
    "underlying_price", "contract_multiplier", "exercise_style",
)
OPTIONAL_COLS: tuple[str, ...] = ("last", "rho", "moneyness", "log_moneyness",
                                   "time_to_expiry_years")
ALL_COLS: tuple[str, ...] = REQUIRED_COLS + OPTIONAL_COLS


def add_derived_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Add ``moneyness``, ``log_moneyness``, ``time_to_expiry_years`` if not
    already present. Idempotent and side-effect free on the caller."""
    out = df.copy()
    if "moneyness" not in out.columns:
        out["moneyness"] = out["strike"] / out["underlying_price"].replace(0, pd.NA)
    if "log_moneyness" not in out.columns:
        import numpy as np
        out["log_moneyness"] = np.log(out["moneyness"].astype(float))
    if "time_to_expiry_years" not in out.columns:
        out["time_to_expiry_years"] = out["dte"].astype(float) / 365.0
    return out


# --------------------------------------------------------------------------- #
# Loader contract
# --------------------------------------------------------------------------- #
class OptionsChainLoader(ABC):
    """Every provider implements ``.load(...)`` returning the canonical schema.

    Loaders must be:
      - causal: data for date t only depends on date <= t,
      - read-only: no order placement, no broker connection,
      - offline-capable in tests (dry-run / synthetic mode).
    """

    name: str = "base"

    @abstractmethod
    def load(
        self,
        underlying: str,
        start: str | pd.Timestamp,
        end: str | pd.Timestamp,
        *,
        dte_min: int | None = None,
        dte_max: int | None = None,
        option_type: str | None = None,
    ) -> pd.DataFrame:
        """Return a canonical-schema options-chain DataFrame for the range."""

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"<{type(self).__name__} provider={self.name!r}>"


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
_LOADERS: dict[str, type[OptionsChainLoader]] = {}


def register_loader(name: str, cls: type[OptionsChainLoader]) -> None:
    _LOADERS[name.lower()] = cls


def get_loader(name: str, **kwargs: Any) -> OptionsChainLoader:
    key = name.lower()
    if key not in _LOADERS:
        raise KeyError(
            f"Unknown options data provider {name!r}. "
            f"Available: {sorted(_LOADERS)}. "
            "Adapters register themselves on import - did you import the provider module?"
        )
    return _LOADERS[key](**kwargs)


def available_loaders() -> list[str]:
    return sorted(_LOADERS)
