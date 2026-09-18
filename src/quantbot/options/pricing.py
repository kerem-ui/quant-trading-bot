"""European Black-Scholes-Merton, continuous yield; never an executable quote.

Prices are per share; T is ACT/365 years, r/q continuously compounded annual
fractions, sigma annualized decimal volatility. American use is an explicitly
labelled approximation via analytics.py, not an early-exercise model.
"""
from __future__ import annotations
from dataclasses import dataclass
import math
import numpy as np
from scipy.stats import norm


def _validate(S, K, T, r, sigma, q, option_type="call"):
    values = tuple(map(float, (S, K, T, r, sigma, q)))
    if not all(math.isfinite(v) for v in values):
        raise ValueError("model inputs must be finite")
    if S <= 0 or K <= 0 or T < 0 or sigma < 0:
        raise ValueError("S/K must be positive; T/sigma must be nonnegative")
    if option_type not in ("call", "put"):
        raise ValueError("option_type must be 'call' or 'put'")
    return values


def _d1_d2(S, K, T, r, sigma, q=0.0):
    S, K, T, r, sigma, q = _validate(S, K, T, r, sigma, q)
    if T == 0 or sigma == 0:
        return None, None
    width = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + (r - q) * T) / width + width / 2
    return d1, d1 - width


def price_bounds(S, K, T, r, option_type="call", q=0.0):
    """European no-arbitrage bounds, not American spot-intrinsic bounds."""
    option_type = option_type.lower()
    _validate(S, K, T, r, 0., q, option_type)
    a, b = S * math.exp(-q * T), K * math.exp(-r * T)
    return (max(a - b, 0.), a) if option_type == "call" else (max(b - a, 0.), b)


def bs_price(S: float, K: float, T: float, r: float, sigma: float,
             option_type: str = "call", q: float = 0.0) -> float:
    """Per-share European value; expiry is intrinsic, sigma=0 is forward payoff."""
    option_type = option_type.lower()
    S, K, T, r, sigma, q = _validate(S, K, T, r, sigma, q, option_type)
    lo, hi = price_bounds(S, K, T, r, option_type, q)
    if T == 0 or sigma == 0:
        return lo
    d1, d2 = _d1_d2(S, K, T, r, sigma, q)
    a, b = S * math.exp(-q * T), K * math.exp(-r * T)
    # Compute the OTM side directly, then parity, avoiding ITM cancellation.
    if a >= b:
        put = b * norm.cdf(-d2) - a * norm.cdf(-d1)
        value = put + a - b if option_type == "call" else put
    else:
        call = a * norm.cdf(d1) - b * norm.cdf(d2)
        value = call if option_type == "call" else call + b - a
    return float(min(hi, max(lo, value)))


@dataclass(frozen=True)
class IVResult:
    """Explicit inversion outcome; failed/underidentified values are NaN."""
    volatility: float
    status: str
    residual: float
    iterations: int
    lower: float
    upper: float


def solve_iv(price, S, K, T, r, option_type="call", q=0.0, *,
             lower=0.0, upper=5.0, tol=1e-8, max_iter=200) -> IVResult:
    """Bracketed price inversion with absolute per-share residual tolerance.

    Boundary prices (time value <= tolerance) do not identify a unique sigma
    at this precision. They are explicitly unavailable, not invented zero IV.
    Bounds apply to the solver domain, not to the universe of possible IVs.
    """
    option_type = option_type.lower()
    _validate(S, K, T, r, 0., q, option_type)
    if (not all(math.isfinite(v) for v in (lower, upper, tol)) or
            not 0 <= lower < upper or tol <= 0 or
            not isinstance(max_iter, int) or max_iter < 1):
        raise ValueError("invalid IV solver controls")
    def fail(status):
        return IVResult(float("nan"), status, float("nan"), 0, lower, upper)
    if not math.isfinite(price) or price < 0:
        return fail("invalid_price")
    if T == 0:
        return fail("expired_unidentifiable")
    floor, ceiling = price_bounds(S, K, T, r, option_type, q)
    if price < floor or price >= ceiling:
        return fail("outside_price_bounds")
    if price - floor <= tol:
        return fail("boundary_unidentifiable")
    lo_px = bs_price(S, K, T, r, lower, option_type, q)
    hi_px = bs_price(S, K, T, r, upper, option_type, q)
    if price < lo_px or price > hi_px:
        return fail("outside_volatility_bracket")
    lo, hi = lower, upper
    for i in range(1, max_iter + 1):
        mid = (lo + hi) / 2
        residual = bs_price(S, K, T, r, mid, option_type, q) - price
        if abs(residual) <= tol:
            return IVResult(mid, "ok", residual, i, lower, upper)
        if residual > 0:
            hi = mid
        else:
            lo = mid
    return fail("not_converged")


def implied_vol(price: float, S: float, K: float, T: float, r: float,
                option_type: str = "call", q: float = 0.0,
                tol: float = 1e-6, max_iter: int = 100, *,
                lower: float = 0.0, upper: float = 5.0) -> float:
    """Compatibility scalar API; NaN on failure. Use solve_iv for the reason."""
    return solve_iv(price, S, K, T, r, option_type, q, lower=lower,
                    upper=upper, tol=tol, max_iter=max_iter).volatility
