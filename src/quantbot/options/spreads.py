"""V5.0 defined-risk spread builders.

Each builder returns a ``Candidate`` (or ``None`` with an explicit rejection
reason). The candidate is then risk-evaluated and queued by the engine for a
NEXT-day fill - we never fill the spread on the decision day.

Phase 1 supports the bull call spread; bear put / bull put / bear call follow
the same pattern and can be added without changing the engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from ..costs.transaction_costs import OptionsCostModel
from . import contract_selector as cs
from .fill_model import StructureFillResult, fill_structure


@dataclass
class Candidate:
    """Provisional structure: legs + fill snapshot + risk metrics.

    Net cash is signed: negative = debit paid. ``max_loss`` is signed
    (<=0). ``width`` is the dollar gap between long/short strikes.
    """

    structure_name: str
    underlying: str
    expiration: pd.Timestamp
    legs: list[dict]                    # [{option_type, strike, qty}]
    fill: StructureFillResult
    net_cash: float
    max_profit: float
    max_loss: float
    width: float
    is_naked: bool = False
    reject_reason: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


def _reject(name: str, reason: str, **meta: Any) -> Candidate:
    """Helper to emit a rejected candidate (engine logs the reason)."""
    return Candidate(
        structure_name=name, underlying="", expiration=pd.NaT,
        legs=[], fill=StructureFillResult(False, (), 0.0, 0.0, reason),
        net_cash=0.0, max_profit=0.0, max_loss=0.0, width=0.0,
        reject_reason=reason, meta=dict(meta),
    )


# --------------------------------------------------------------------------- #
# Bull call spread (debit). max_loss = -debit, max_profit = width - debit.
# Both bounded -> DEFINED RISK by construction.
# --------------------------------------------------------------------------- #
def build_bull_call_spread(
    chain_today: pd.DataFrame, *,
    underlying: str = "SPY",
    dte_min: int = 30, dte_max: int = 45,
    long_delta: float = 0.50, short_delta: float = 0.30,
    max_width: float = 10.0,
    spread_max_pct: float = 0.25,
    cost_model: OptionsCostModel | None = None,
    multiplier: int = 100,
) -> Candidate:
    if chain_today.empty:
        return _reject("bull_call_spread", "empty_chain")

    exp = cs.select_expiration(chain_today, dte_min, dte_max)
    if exp is None:
        return _reject("bull_call_spread", "no_expiration")

    long_row = cs.select_by_delta(
        chain_today, expiration=exp, option_type="call",
        target_delta=long_delta, spread_max_pct=spread_max_pct,
    )
    if long_row is None:
        return _reject("bull_call_spread", "no_long_leg",
                        expiration=str(pd.Timestamp(exp).date()))

    short_row = cs.select_by_delta(
        chain_today, expiration=exp, option_type="call",
        target_delta=short_delta, spread_max_pct=spread_max_pct,
        min_strike=float(long_row["strike"]),   # must be HIGHER than long
        max_strike=float(long_row["strike"]) + max_width,
    )
    if short_row is None:
        return _reject("bull_call_spread", "no_short_leg",
                        expiration=str(pd.Timestamp(exp).date()),
                        long_strike=float(long_row["strike"]))

    width = float(short_row["strike"] - long_row["strike"])
    if width <= 0 or width > max_width:
        return _reject("bull_call_spread", f"width_out_of_band({width})")

    legs = [
        {"option_type": "call", "strike": float(long_row["strike"]),  "qty": +1},
        {"option_type": "call", "strike": float(short_row["strike"]), "qty": -1},
    ]
    fill = fill_structure(legs, [long_row, short_row],
                           spread_max_pct=spread_max_pct,
                           cost_model=cost_model, multiplier=multiplier)
    if not fill.accepted:
        return _reject("bull_call_spread", fill.reject_reason)

    # Net cash: negative = debit. fill.net_cash already uses the
    # cash-flow convention.
    net_cash = float(fill.net_cash)
    debit = -net_cash    # debit > 0 if we paid
    if debit <= 0:
        # Bull call spread is supposed to be a debit; refuse the (rare) inverted case.
        return _reject("bull_call_spread", "non_debit_pricing")

    max_loss = -debit                                   # bounded
    max_profit = float(width * multiplier - debit)      # bounded
    if max_profit < 0:
        return _reject("bull_call_spread", "debit_exceeds_width")

    return Candidate(
        structure_name="bull_call_spread", underlying=underlying,
        expiration=pd.Timestamp(exp), legs=legs, fill=fill,
        net_cash=net_cash, max_profit=max_profit, max_loss=max_loss,
        width=width, is_naked=False,
        meta={
            "long_strike": float(long_row["strike"]),
            "short_strike": float(short_row["strike"]),
            "long_delta": float(long_row.get("delta", float("nan"))),
            "short_delta": float(short_row.get("delta", float("nan"))),
            "long_dte": int(long_row["dte"]),
            "short_dte": int(short_row["dte"]),
            "spot": float(long_row["underlying_price"]),
        },
    )


# --------------------------------------------------------------------------- #
# Bear put spread (debit). max_loss = -debit, max_profit = width - debit.
# Both bounded -> DEFINED RISK by construction.
#
# Structure (puts; same expiration):
#   long  put at HIGHER strike (closer to ATM, e.g. delta ~ -0.50)
#   short put at LOWER  strike (further OTM, e.g. delta ~ -0.30)
# Debit because the long (higher-strike) put costs more than the short.
# --------------------------------------------------------------------------- #
def build_bear_put_spread(
    chain_today: pd.DataFrame, *,
    underlying: str = "SPY",
    dte_min: int = 30, dte_max: int = 45,
    long_delta: float = -0.50, short_delta: float = -0.30,
    max_width: float = 10.0,
    spread_max_pct: float = 0.25,
    cost_model: OptionsCostModel | None = None,
    multiplier: int = 100,
) -> Candidate:
    """Defined-risk bearish DEBIT vertical built from two puts.

    Returns a ``Candidate`` or a rejected candidate. NEVER naked.
    """
    if chain_today.empty:
        return _reject("bear_put_spread", "empty_chain")

    exp = cs.select_expiration(chain_today, dte_min, dte_max)
    if exp is None:
        return _reject("bear_put_spread", "no_expiration")

    # Long put first: the higher-strike (closer to ATM) put.
    long_row = cs.select_by_delta(
        chain_today, expiration=exp, option_type="put",
        target_delta=long_delta, spread_max_pct=spread_max_pct,
    )
    if long_row is None:
        return _reject("bear_put_spread", "no_long_leg",
                        expiration=str(pd.Timestamp(exp).date()))

    # Short put must be at a LOWER strike than the long (and bounded by
    # max_width). For puts, "lower strike" == "further OTM" == "less
    # negative delta" (e.g. -0.30 vs -0.50).
    short_row = cs.select_by_delta(
        chain_today, expiration=exp, option_type="put",
        target_delta=short_delta, spread_max_pct=spread_max_pct,
        min_strike=float(long_row["strike"]) - max_width,
        max_strike=float(long_row["strike"]),
    )
    if short_row is None:
        return _reject("bear_put_spread", "no_short_leg",
                        expiration=str(pd.Timestamp(exp).date()),
                        long_strike=float(long_row["strike"]))

    # width = long_strike - short_strike  (positive)
    width = float(long_row["strike"] - short_row["strike"])
    if width <= 0 or width > max_width:
        return _reject("bear_put_spread", f"width_out_of_band({width})")

    legs = [
        {"option_type": "put", "strike": float(long_row["strike"]),  "qty": +1},
        {"option_type": "put", "strike": float(short_row["strike"]), "qty": -1},
    ]
    fill = fill_structure(legs, [long_row, short_row],
                           spread_max_pct=spread_max_pct,
                           cost_model=cost_model, multiplier=multiplier)
    if not fill.accepted:
        return _reject("bear_put_spread", fill.reject_reason)

    net_cash = float(fill.net_cash)
    debit = -net_cash    # debit > 0 if we paid
    if debit <= 0:
        # Bear put is a debit by construction; refuse the (rare) inverted case.
        return _reject("bear_put_spread", "non_debit_pricing")

    max_loss = -debit                                   # bounded
    max_profit = float(width * multiplier - debit)      # bounded
    if max_profit < 0:
        return _reject("bear_put_spread", "debit_exceeds_width")

    return Candidate(
        structure_name="bear_put_spread", underlying=underlying,
        expiration=pd.Timestamp(exp), legs=legs, fill=fill,
        net_cash=net_cash, max_profit=max_profit, max_loss=max_loss,
        width=width, is_naked=False,
        meta={
            "long_strike": float(long_row["strike"]),
            "short_strike": float(short_row["strike"]),
            "long_delta": float(long_row.get("delta", float("nan"))),
            "short_delta": float(short_row.get("delta", float("nan"))),
            "long_dte": int(long_row["dte"]),
            "short_dte": int(short_row["dte"]),
            "spot": float(long_row["underlying_price"]),
        },
    )


# --------------------------------------------------------------------------- #
# Bull put spread (CREDIT). max_loss = -(width - credit), max_profit = credit.
# Both bounded -> DEFINED RISK by construction.
#
# Structure (puts; same expiration):
#   short put at HIGHER strike (closer to ATM, e.g. delta ~ -0.30)
#   long  put at LOWER  strike (further OTM, e.g. delta ~ -0.15)
# Credit received because the short (higher-strike) put earns more than the
# long (lower-strike) put costs. Net cash > 0 at open.
# --------------------------------------------------------------------------- #
def build_bull_put_spread(
    chain_today: pd.DataFrame, *,
    underlying: str = "SPY",
    dte_min: int = 30, dte_max: int = 45,
    short_delta: float = -0.30, long_delta: float = -0.15,
    max_width: float = 10.0,
    spread_max_pct: float = 0.25,
    cost_model: OptionsCostModel | None = None,
    multiplier: int = 100,
) -> Candidate:
    """Defined-risk bullish CREDIT vertical built from two puts.

    The SHORT leg is the higher-strike put. The LONG leg is a lower-strike
    "wing" that caps downside loss -- WITHOUT it this would be a naked
    short put, which the risk gate rejects. NEVER naked.
    """
    if chain_today.empty:
        return _reject("bull_put_spread", "empty_chain")

    exp = cs.select_expiration(chain_today, dte_min, dte_max)
    if exp is None:
        return _reject("bull_put_spread", "no_expiration")

    # Pick the SHORT (higher-strike) put first.
    short_row = cs.select_by_delta(
        chain_today, expiration=exp, option_type="put",
        target_delta=short_delta, spread_max_pct=spread_max_pct,
    )
    if short_row is None:
        return _reject("bull_put_spread", "no_short_leg",
                        expiration=str(pd.Timestamp(exp).date()))

    # Long (protective) put must be at a strictly LOWER strike than the
    # short, bounded by max_width. Without this leg the structure becomes
    # naked short put (unbounded loss), which is forbidden.
    long_row = cs.select_by_delta(
        chain_today, expiration=exp, option_type="put",
        target_delta=long_delta, spread_max_pct=spread_max_pct,
        min_strike=float(short_row["strike"]) - max_width,
        max_strike=float(short_row["strike"]),
    )
    if long_row is None:
        return _reject("bull_put_spread", "no_long_leg",
                        expiration=str(pd.Timestamp(exp).date()),
                        short_strike=float(short_row["strike"]))

    # width = short_strike - long_strike  (positive)
    width = float(short_row["strike"] - long_row["strike"])
    if width <= 0 or width > max_width:
        return _reject("bull_put_spread", f"width_out_of_band({width})")

    legs = [
        # Long (protective) wing first by convention -- order does not affect
        # cash flow since net_cash uses signed qty.
        {"option_type": "put", "strike": float(long_row["strike"]),  "qty": +1},
        {"option_type": "put", "strike": float(short_row["strike"]), "qty": -1},
    ]
    fill = fill_structure(legs, [long_row, short_row],
                           spread_max_pct=spread_max_pct,
                           cost_model=cost_model, multiplier=multiplier)
    if not fill.accepted:
        return _reject("bull_put_spread", fill.reject_reason)

    # Net cash convention: positive == credit received at open.
    net_cash = float(fill.net_cash)
    credit = net_cash
    if credit <= 0:
        # Bull put is a credit by construction; refuse non-credit case.
        return _reject("bull_put_spread", "non_credit_pricing")

    max_profit = credit                                       # bounded
    max_loss = -(width * multiplier - credit)                 # bounded, <= 0
    if max_loss >= 0:
        # Defensive: a credit larger than the width-cash would imply
        # arbitrage / bad quotes; refuse rather than book.
        return _reject("bull_put_spread", "credit_exceeds_width")

    return Candidate(
        structure_name="bull_put_spread", underlying=underlying,
        expiration=pd.Timestamp(exp), legs=legs, fill=fill,
        net_cash=net_cash, max_profit=float(max_profit), max_loss=float(max_loss),
        width=width, is_naked=False,
        meta={
            "long_strike": float(long_row["strike"]),
            "short_strike": float(short_row["strike"]),
            "long_delta": float(long_row.get("delta", float("nan"))),
            "short_delta": float(short_row.get("delta", float("nan"))),
            "long_dte": int(long_row["dte"]),
            "short_dte": int(short_row["dte"]),
            "spot": float(short_row["underlying_price"]),
        },
    )
