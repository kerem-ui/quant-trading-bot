"""Black-Scholes Greeks (research approximation, European).

Conventions: theta is per-calendar-day, vega per 1 vol point (0.01), rho per
1% rate move. Approximation only - see pricing.py limitations.
"""

from __future__ import annotations

import numpy as np
from scipy.stats import norm

from .pricing import _d1_d2


def bs_greeks(
    S: float, K: float, T: float, r: float, sigma: float,
    option_type: str = "call", q: float = 0.0,
) -> dict:
    """Return delta, gamma, theta (per day), vega (per 1 vol pt), rho (per 1%)."""
    option_type = option_type.lower()
    d1, d2 = _d1_d2(S, K, T, r, sigma, q)
    if d1 is None:
        return {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0}
    pdf = norm.pdf(d1)
    disc_q = np.exp(-q * T)
    sqrtT = np.sqrt(T)
    if option_type == "call":
        delta = disc_q * norm.cdf(d1)
        theta = (
            -S * disc_q * pdf * sigma / (2 * sqrtT)
            - r * K * np.exp(-r * T) * norm.cdf(d2)
            + q * S * disc_q * norm.cdf(d1)
        )
        rho = K * T * np.exp(-r * T) * norm.cdf(d2) / 100.0
    else:
        delta = -disc_q * norm.cdf(-d1)
        theta = (
            -S * disc_q * pdf * sigma / (2 * sqrtT)
            + r * K * np.exp(-r * T) * norm.cdf(-d2)
            - q * S * disc_q * norm.cdf(-d1)
        )
        rho = -K * T * np.exp(-r * T) * norm.cdf(-d2) / 100.0
    gamma = disc_q * pdf / (S * sigma * sqrtT)
    vega = S * disc_q * pdf * sqrtT / 100.0
    return {
        "delta": float(delta),
        "gamma": float(gamma),
        "theta": float(theta / 365.0),
        "vega": float(vega),
        "rho": float(rho),
    }
