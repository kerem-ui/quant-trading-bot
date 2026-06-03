"""``OptionsChain`` - a lightweight DataFrame-backed container for canonical
options chain data, with convenience accessors used by V5+ research.

Read-only: methods return new chains (no mutation). All operations remain
causal (no row reaches forward in time).
"""

from __future__ import annotations

import pandas as pd

from . import filters as F


class OptionsChain:
    """Wraps a canonical-schema options-chain DataFrame.

    Construct with ``OptionsChain(df)``; the DataFrame is stored as ``.df``.
    """

    def __init__(self, df: pd.DataFrame):
        self.df = df.reset_index(drop=True)

    def __len__(self) -> int:
        return len(self.df)

    def __repr__(self) -> str:  # pragma: no cover
        if self.df.empty:
            return "<OptionsChain empty>"
        u = sorted(self.df["underlying"].unique())
        d = (str(self.df["date"].min().date()), str(self.df["date"].max().date()))
        return f"<OptionsChain rows={len(self.df)} underlyings={u} dates={d}>"

    # --- filtering ------------------------------------------------------
    def underlying(self, underlying: str | list[str]) -> "OptionsChain":
        return OptionsChain(F.filter_underlying(self.df, underlying))

    def type(self, option_type: str | None) -> "OptionsChain":
        return OptionsChain(F.filter_option_type(self.df, option_type))

    def dte(self, dte_min: int | None = None, dte_max: int | None = None) -> "OptionsChain":
        return OptionsChain(F.filter_dte(self.df, dte_min, dte_max))

    def delta(self, min_abs: float | None = None, max_abs: float | None = None) -> "OptionsChain":
        return OptionsChain(F.filter_delta(self.df, min_abs, max_abs))

    def moneyness(self, lo: float, hi: float) -> "OptionsChain":
        return OptionsChain(F.filter_moneyness(self.df, lo, hi))

    def liquid(self, min_volume: int = 0, min_open_interest: int = 0) -> "OptionsChain":
        return OptionsChain(F.filter_liquidity(self.df, min_volume, min_open_interest))

    def tight(self, max_spread_pct: float) -> "OptionsChain":
        return OptionsChain(F.filter_spread(self.df, max_spread_pct))

    def on_date(self, date) -> "OptionsChain":
        d = pd.Timestamp(date).normalize()
        return OptionsChain(self.df[self.df["date"] == d].copy())

    def for_expiration(self, expiration) -> "OptionsChain":
        e = pd.Timestamp(expiration).normalize()
        return OptionsChain(self.df[self.df["expiration"] == e].copy())

    # --- selectors ------------------------------------------------------
    def atm(self, date, expiration, option_type: str = "call") -> pd.Series | None:
        """Nearest-strike row to the underlying spot on the given date / expiry."""
        sub = self.on_date(date).for_expiration(expiration).type(option_type).df
        if sub.empty:
            return None
        spot = sub["underlying_price"].iloc[0]
        return sub.iloc[(sub["strike"] - spot).abs().argsort()].iloc[0]

    def nearest_delta(self, date, expiration, target_delta: float,
                      option_type: str = "call") -> pd.Series | None:
        sub = self.on_date(date).for_expiration(expiration).type(option_type).df
        sub = sub.dropna(subset=["delta"])
        if sub.empty:
            return None
        return sub.iloc[(sub["delta"] - target_delta).abs().argsort()].iloc[0]

    def surface_slice(self, date) -> pd.DataFrame:
        """Return strike-by-dte IV table for a given date (calls only)."""
        sub = self.on_date(date).type("call").df
        if sub.empty:
            return pd.DataFrame()
        return sub.pivot_table(index="strike", columns="dte",
                                values="implied_volatility", aggfunc="mean")

    def expirations(self) -> list[pd.Timestamp]:
        return sorted(pd.to_datetime(self.df["expiration"].unique()).tolist())

    def dtes(self) -> list[int]:
        return sorted(self.df["dte"].dropna().astype(int).unique().tolist())
