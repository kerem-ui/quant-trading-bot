"""Defined-risk option structures (research).

No naked short options anywhere in v1: every short leg must be covered by a
long wing, so ``max_loss`` is always finite for the provided structures.

Each structure computes: net debit/credit, max profit / max loss (grid-based,
robust for arbitrary defined-risk combos), breakevens, net Greeks (BS at the
current spot), and scenario PnL.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .greeks import bs_greeks
from .payoff import call_payoff, put_payoff


@dataclass
class OptionLeg:
    option_type: str          # 'call' | 'put'
    strike: float
    qty: int                  # +long / -short (number of contracts)
    price: float              # premium per share (mid/exec price)
    iv: float = 0.20
    T: float = 30 / 365       # years to expiry
    multiplier: int = 100

    def intrinsic(self, S):
        f = call_payoff if self.option_type == "call" else put_payoff
        return f(S, self.strike)

    def entry_cash(self) -> float:
        """Cash flow to open (positive = you pay, negative = you receive)."""
        return self.qty * self.price * self.multiplier

    def greeks(self, S: float, r: float = 0.03) -> dict:
        g = bs_greeks(S, self.strike, self.T, r, self.iv, self.option_type)
        scale = self.qty * self.multiplier
        return {k: v * scale for k, v in g.items()}


@dataclass
class OptionStructure:
    legs: list[OptionLeg] = field(default_factory=list)
    spot: float = 100.0
    r: float = 0.03
    name: str = "structure"

    # --- economics ---------------------------------------------------------
    def net_entry_cash(self) -> float:
        return sum(l.entry_cash() for l in self.legs)

    def net_debit(self) -> float:
        """Positive => net debit paid to open."""
        return max(0.0, self.net_entry_cash())

    def net_credit(self) -> float:
        """Positive => net credit received to open."""
        return max(0.0, -self.net_entry_cash())

    def expiry_pnl(self, S):
        S = np.asarray(S, dtype=float)
        val = np.zeros_like(S)
        for l in self.legs:
            val = val + l.qty * l.intrinsic(S) * l.multiplier
        return val - self.net_entry_cash()

    def _grid(self):
        ks = [l.strike for l in self.legs]
        hi = max(ks) * 2.0 + self.spot
        return np.linspace(0.0, hi, 4001)

    def max_profit(self) -> float:
        return float(np.max(self.expiry_pnl(self._grid())))

    def max_loss(self) -> float:
        """Most negative expiry PnL (>=0 magnitude returned as a negative #)."""
        return float(np.min(self.expiry_pnl(self._grid())))

    def breakevens(self) -> list[float]:
        S = self._grid()
        pnl = self.expiry_pnl(S)
        roots: list[float] = []
        for i in range(len(S) - 1):
            y0, y1 = pnl[i], pnl[i + 1]
            if y0 == 0.0:
                roots.append(float(S[i]))
            elif y0 * y1 < 0.0:  # strict sign change -> interpolate
                roots.append(float(S[i] - y0 * (S[i + 1] - S[i]) / (y1 - y0)))
        if pnl[-1] == 0.0:
            roots.append(float(S[-1]))
        # Merge near-duplicate roots (exact-zero grid points create pairs).
        roots.sort()
        tol = (S[1] - S[0]) * 3.0
        merged: list[float] = []
        for r in roots:
            if not merged or abs(r - merged[-1]) > tol:
                merged.append(r)
        return merged

    def net_greeks(self) -> dict:
        agg = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0}
        for l in self.legs:
            for k, v in l.greeks(self.spot, self.r).items():
                agg[k] += v
        return agg

    def scenario_pnl(self, pct_moves=(-0.05, -0.02, -0.01, 0.01, 0.02, 0.05)) -> dict:
        """Terminal PnL if the underlying finishes at spot*(1+move)."""
        return {
            f"{m:+.0%}": float(self.expiry_pnl(self.spot * (1 + m))) for m in pct_moves
        }

    def summary(self) -> dict:
        return {
            "name": self.name,
            "net_debit": round(self.net_debit(), 2),
            "net_credit": round(self.net_credit(), 2),
            "max_profit": round(self.max_profit(), 2),
            "max_loss": round(self.max_loss(), 2),
            "breakevens": [round(b, 2) for b in self.breakevens()],
            "net_greeks": {k: round(v, 4) for k, v in self.net_greeks().items()},
        }


# --- convenience constructors --------------------------------------------- #
def VerticalSpread(option_type, long_strike, short_strike, long_price, short_price,
                   spot=100.0, iv=0.2, T=30 / 365, r=0.03) -> OptionStructure:
    return OptionStructure(
        legs=[
            OptionLeg(option_type, long_strike, +1, long_price, iv, T),
            OptionLeg(option_type, short_strike, -1, short_price, iv, T),
        ],
        spot=spot, r=r, name=f"{option_type}_vertical",
    )


def Straddle(strike, call_price, put_price, qty=1, spot=100.0, iv=0.2,
             T=30 / 365, r=0.03) -> OptionStructure:
    return OptionStructure(
        legs=[
            OptionLeg("call", strike, qty, call_price, iv, T),
            OptionLeg("put", strike, qty, put_price, iv, T),
        ],
        spot=spot, r=r, name="straddle",
    )


def Strangle(put_strike, call_strike, put_price, call_price, qty=1, spot=100.0,
             iv=0.2, T=30 / 365, r=0.03) -> OptionStructure:
    return OptionStructure(
        legs=[
            OptionLeg("put", put_strike, qty, put_price, iv, T),
            OptionLeg("call", call_strike, qty, call_price, iv, T),
        ],
        spot=spot, r=r, name="strangle",
    )


def IronCondor(put_long_K, put_short_K, call_short_K, call_long_K,
               prices: dict, spot=100.0, iv=0.2, T=30 / 365, r=0.03) -> OptionStructure:
    """Defined-risk: long wings cover short body. ``prices`` keys:
    put_long, put_short, call_short, call_long."""
    return OptionStructure(
        legs=[
            OptionLeg("put", put_long_K, +1, prices["put_long"], iv, T),
            OptionLeg("put", put_short_K, -1, prices["put_short"], iv, T),
            OptionLeg("call", call_short_K, -1, prices["call_short"], iv, T),
            OptionLeg("call", call_long_K, +1, prices["call_long"], iv, T),
        ],
        spot=spot, r=r, name="iron_condor",
    )


@dataclass
class CalendarSpread:
    """Approximate calendar (different expiries, same strike).

    A single-expiry terminal payoff is NOT valid for calendars; this exposes a
    BS-model net value/Greeks approximation and is explicitly labelled
    approximate (no auto-trading).
    """

    strike: float
    near_T: float
    far_T: float
    iv_near: float
    iv_far: float
    spot: float = 100.0
    r: float = 0.03
    option_type: str = "call"
    qty: int = 1
    multiplier: int = 100
    approximate: bool = field(default=True, init=False)

    def model_value(self) -> float:
        from .pricing import bs_price
        near = bs_price(self.spot, self.strike, self.near_T, self.r, self.iv_near, self.option_type)
        far = bs_price(self.spot, self.strike, self.far_T, self.r, self.iv_far, self.option_type)
        # Long calendar = short near, long far.
        return float((far - near) * self.qty * self.multiplier)

    def net_greeks(self) -> dict:
        gn = bs_greeks(self.spot, self.strike, self.near_T, self.r, self.iv_near, self.option_type)
        gf = bs_greeks(self.spot, self.strike, self.far_T, self.r, self.iv_far, self.option_type)
        scale = self.qty * self.multiplier
        return {k: (gf[k] - gn[k]) * scale for k in gn}
