"""Options chain loader (interface + synthetic generator).

Historical options-chain data is not bundled (free daily OHLCV only, per
constraints). This module defines the schema and a synthetic chain generator so
the options utilities and S05+ can be exercised and tested. Any result built on
the synthetic chain is explicitly approximate.

Real options backtests must use chain snapshots, never theoretical prices only,
and never the options *last* price as an executable price.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..options.pricing import bs_price
from ..options.greeks import bs_greeks

OPTIONS_SCHEMA = (
    "date", "underlying", "expiration", "dte", "option_type", "strike",
    "bid", "ask", "mid", "volume", "open_interest", "implied_volatility",
    "delta", "gamma", "theta", "vega", "contract_multiplier",
)


def synthetic_option_chain(
    underlying: str,
    spot: float,
    as_of: pd.Timestamp,
    *,
    dtes: tuple[int, ...] = (30, 45, 60),
    rate: float = 0.03,
    base_iv: float = 0.20,
    skew: float = 0.06,
    spread_frac: float = 0.04,
    seed: int = 0,
) -> pd.DataFrame:
    """Build an approximate options chain priced with Black-Scholes + a skew.

    Labelled approximate: real chains have a richer surface and microstructure.
    """
    rng = np.random.default_rng(seed)
    rows = []
    for dte in dtes:
        T = dte / 365.0
        strikes = np.round(spot * np.arange(0.80, 1.21, 0.05), 2)
        for K in strikes:
            moneyness = np.log(K / spot)
            iv = max(0.05, base_iv - skew * moneyness + rng.normal(0, 0.005))
            for opt in ("call", "put"):
                fair = bs_price(spot, K, T, rate, iv, opt)
                half = max(0.01, fair * spread_frac)
                bid = max(0.0, fair - half)
                ask = fair + half
                g = bs_greeks(spot, K, T, rate, iv, opt)
                rows.append(
                    {
                        "date": as_of,
                        "underlying": underlying,
                        "expiration": as_of + pd.Timedelta(days=dte),
                        "dte": dte,
                        "option_type": opt,
                        "strike": float(K),
                        "bid": round(bid, 2),
                        "ask": round(ask, 2),
                        "mid": round((bid + ask) / 2, 2),
                        "volume": int(rng.integers(0, 5000)),
                        "open_interest": int(rng.integers(0, 20000)),
                        "implied_volatility": round(iv, 4),
                        "delta": g["delta"],
                        "gamma": g["gamma"],
                        "theta": g["theta"],
                        "vega": g["vega"],
                        "contract_multiplier": 100,
                    }
                )
    return pd.DataFrame(rows, columns=list(OPTIONS_SCHEMA))


def load_options_chain(*args, **kwargs) -> pd.DataFrame:
    """Placeholder for a real historical options loader.

    No free historical chain source is wired in v1. Use
    :func:`synthetic_option_chain` for research, and treat output as approximate.
    """
    raise NotImplementedError(
        "Historical options-chain loading is not available in v1. "
        "Use synthetic_option_chain() for research (approximate)."
    )
