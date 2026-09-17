"""Synthetic options-chain loader.

Deterministic, offline, no-network. Used for tests and pipeline smoke-runs.
Wraps the existing single-date generator in :mod:`quantbot.data.options_loader`
and stacks daily snapshots into the canonical V4 schema.

Results are illustrative ONLY (Black-Scholes prices on a synthetic spot walk).
Anything built on this data must be labelled approximate.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..options_chain_loader import (
    OptionsChainLoader,
    REQUIRED_COLS,
    add_derived_columns,
    register_loader,
)
from ..options_loader import synthetic_option_chain

# Plausible starting spots for known liquid ETFs; otherwise default 100.
_DEFAULT_SPOTS = {"SPY": 400.0, "QQQ": 350.0, "IWM": 180.0, "DIA": 350.0}


class SyntheticOptionsLoader(OptionsChainLoader):
    name = "synthetic"

    def __init__(self, *, seed: int = 42, base_iv: float = 0.20,
                 dtes: tuple[int, ...] = (30, 45, 60), rate: float = 0.03):
        self.seed = int(seed)
        self.base_iv = float(base_iv)
        self.dtes = tuple(dtes)
        self.rate = float(rate)

    # ------------------------------------------------------------------ #
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
        underlying = underlying.upper()
        dates = pd.bdate_range(pd.Timestamp(start), pd.Timestamp(end))
        if len(dates) == 0:
            return pd.DataFrame(columns=list(REQUIRED_COLS))

        # Deterministic spot path (small GBM seeded by symbol+seed).
        rng = np.random.default_rng(self.seed + abs(hash(underlying)) % (1 << 20))
        spot0 = _DEFAULT_SPOTS.get(underlying, 100.0)
        rets = rng.normal(0.0003, 0.011, len(dates))
        spots = spot0 * np.exp(np.cumsum(rets))

        frames: list[pd.DataFrame] = []
        for d, s in zip(dates, spots):
            sub = synthetic_option_chain(
                underlying=underlying, spot=float(s), as_of=pd.Timestamp(d),
                dtes=self.dtes, rate=self.rate, base_iv=self.base_iv,
                seed=int(rng.integers(0, 2**31 - 1)),
            )
            sub["underlying_price"] = float(s)
            sub["exercise_style"] = "american"
            sub["last"] = np.nan       # optional column populated as NaN
            sub["rho"] = np.nan
            frames.append(sub)

        df = pd.concat(frames, ignore_index=True)
        # Strip un-needed columns and enforce canonical order.
        for col in REQUIRED_COLS:
            if col not in df.columns:
                df[col] = np.nan
        df = df[list(REQUIRED_COLS) + ["last", "rho"]]
        df = add_derived_columns(df)

        # Apply server-side-ish filters cheaply.
        if dte_min is not None:
            df = df[df["dte"] >= dte_min]
        if dte_max is not None:
            df = df[df["dte"] <= dte_max]
        if option_type is not None:
            df = df[df["option_type"].str.lower() == option_type.lower()]
        return df.reset_index(drop=True)


# Side-effect: register on import so get_loader('synthetic') works.
register_loader("synthetic", SyntheticOptionsLoader)
