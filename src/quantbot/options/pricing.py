"""Black-Scholes-Merton pricing (European, research approximation).

Limitations (explicit): European-style only; constant vol/rate; continuous
dividend yield. American early exercise and discrete dividends are NOT modelled.
Do not use as an executable price - always use chain bid/ask for execution.
"""

from __future__ import annotations

import numpy as np
from scipy.stats import norm


def _d1_d2(S, K, T, r, sigma, q=0.0):
    S, K, T, r, sigma, q = map(float, (S, K, T, r, sigma, q))
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return None, None
    d1 = (np.log(S / K) + (r - q + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    return d1, d2


def bs_price(
    S: float, K: float, T: float, r: float, sigma: float,
    option_type: str = "call", q: float = 0.0,
) -> float:
    """Black-Scholes price. ``T`` in years. ``option_type`` in {call, put}.

    Degenerate inputs (T<=0 or sigma<=0) fall back to discounted intrinsic.
    """
    option_type = option_type.lower()
    if option_type not in ("call", "put"):
        raise ValueError("option_type must be 'call' or 'put'")
    d1, d2 = _d1_d2(S, K, T, r, sigma, q)
    if d1 is None:  # intrinsic value at expiry / degenerate
        intrinsic = max(S - K, 0.0) if option_type == "call" else max(K - S, 0.0)
        return float(intrinsic * np.exp(-r * max(T, 0.0)))
    if option_type == "call":
        px = S * np.exp(-q * T) * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    else:
        px = K * np.exp(-r * T) * norm.cdf(-d2) - S * np.exp(-q * T) * norm.cdf(-d1)
    return float(px)


def implied_vol(
    price: float, S: float, K: float, T: float, r: float,
    option_type: str = "call", q: float = 0.0,
    tol: float = 1e-6, max_iter: int = 100,
) -> float:
    """Implied vol via bisection (robust, no derivative needed)."""
    intrinsic = max(S - K, 0.0) if option_type == "call" else max(K - S, 0.0)
    if price < intrinsic - 1e-8 or T <= 0:
        return float("nan")
    lo, hi = 1e-4, 5.0
    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        diff = bs_price(S, K, T, r, mid, option_type, q) - price
        if abs(diff) < tol:
            return float(mid)
        if diff > 0:
            hi = mid
        else:
            lo = mid
    return float(0.5 * (lo + hi))
