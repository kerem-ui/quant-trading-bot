"""V5.0 options fill model (conservative).

Backtest fills are always **conservative**: buy at ASK, sell at BID. The
`last` field of an option quote is NEVER used as a fill price (it is often
hours/days stale on illiquid contracts).

We model the spread, not the queue. If a contract fails liquidity gates
(`bid <= 0` or `(ask-bid)/mid > spread_max_pct`), the candidate is REJECTED.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

from ..costs.transaction_costs import OptionsCostModel


@dataclass(frozen=True)
class FillResult:
    """One leg's fill outcome."""

    accepted: bool
    fill_price: float           # per-share premium paid (long) or received (short)
    side: str                   # 'buy' / 'sell'
    bid: float
    ask: float
    spread_pct: float
    reject_reason: str = ""


@dataclass(frozen=True)
class StructureFillResult:
    """Whole-structure fill outcome."""

    accepted: bool
    legs: tuple[FillResult, ...]
    net_cash: float             # signed: negative = cash paid (debit)
    cost: float                 # OptionsCostModel charge in $
    reject_reason: str = ""
    commission: float = 0.0
    slippage: float = 0.0


def quote_prices(chain_row: pd.Series) -> tuple[float, float]:
    """Return finite, nonnegative, non-crossed marks; zero bids may be marked.

    Executions additionally require a positive bid and the spread gate.
    """
    try:
        bid, ask = float(chain_row["bid"]), float(chain_row["ask"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("missing_or_invalid_quote") from exc
    if not np.isfinite([bid, ask]).all():
        raise ValueError("nonfinite_quote")
    if bid < 0 or ask < 0:
        raise ValueError("negative_quote")
    if bid > ask:
        raise ValueError("crossed_quote")
    return bid, ask


# --------------------------------------------------------------------------- #
def _spread_pct(bid: float, ask: float) -> float:
    mid = (bid + ask) / 2.0
    if mid <= 0:
        return float("inf")
    return float(abs(ask - bid) / mid)


def fill_leg(
    chain_row: pd.Series, qty: int, *,
    spread_max_pct: float = 0.25,
) -> FillResult:
    """Conservative fill for one leg.

    ``chain_row`` must include ``bid`` and ``ask``. ``qty > 0`` -> buy at ASK;
    ``qty < 0`` -> sell at BID. Rejects on ``bid <= 0`` or a too-wide spread.
    """
    if not np.isfinite(qty) or qty == 0 or int(qty) != qty:
        raise ValueError("qty must be a non-zero integer")
    try:
        bid, ask = quote_prices(chain_row)
    except ValueError as exc:
        return FillResult(False, np.nan, "buy" if qty > 0 else "sell",
                          np.nan, np.nan, np.nan, reject_reason=str(exc))
    sp_pct = _spread_pct(bid, ask)
    if bid <= 0:
        return FillResult(False, np.nan, "buy" if qty >= 0 else "sell",
                          bid, ask, sp_pct, reject_reason="zero_bid")
    if sp_pct > spread_max_pct:
        return FillResult(False, np.nan, "buy" if qty >= 0 else "sell",
                          bid, ask, sp_pct,
                          reject_reason=f"spread_too_wide({sp_pct:.2%})")
    if qty > 0:
        # Long open: pay ASK.
        return FillResult(True, ask, "buy", bid, ask, sp_pct)
    elif qty < 0:
        # Short open: receive BID.
        return FillResult(True, bid, "sell", bid, ask, sp_pct)
    raise ValueError("qty must be non-zero")


def fill_structure(
    legs: Iterable[dict], chain_rows: Iterable[pd.Series], *,
    spread_max_pct: float = 0.25,
    cost_model: OptionsCostModel | None = None,
    multiplier: int = 100,
) -> StructureFillResult:
    """Fill every leg conservatively; reject the WHOLE structure if any leg
    fails (defined-risk integrity: never have a half-opened spread)."""
    cost_model = cost_model or OptionsCostModel()
    results: list[FillResult] = []
    legs = list(legs)
    chain_rows = list(chain_rows)
    if len(legs) != len(chain_rows):
        raise ValueError("legs and chain_rows length mismatch")
    if not legs:
        return StructureFillResult(False, (), 0.0, 0.0, "empty_structure")
    for key in ("underlying", "expiration", "date"):
        if len({row.get(key) for row in chain_rows}) > 1:
            return StructureFillResult(False, (), 0.0, 0.0, f"mixed_{key}_unsupported")
    for leg, row in zip(legs, chain_rows):
        # Never silently substitute another contract/deliverable. Legacy
        # primitive callers may omit identity; the engine supplies it fully.
        mismatch = any(key in leg and leg[key] != row.get(key)
                       for key in ("underlying", "expiration", "option_type", "strike"))
        mismatch |= leg.get("multiplier", multiplier) != multiplier
        mismatch |= row.get("contract_multiplier", multiplier) != multiplier
        if mismatch:
            return StructureFillResult(False, (), 0.0, 0.0,
                                       "contract_identity_or_multiplier_mismatch")
        results.append(fill_leg(row, leg["qty"], spread_max_pct=spread_max_pct))

    if any(not r.accepted for r in results):
        reason = next(r.reject_reason for r in results if not r.accepted)
        return StructureFillResult(False, tuple(results), 0.0, 0.0,
                                    reject_reason=f"leg_rejected:{reason}")

    # Net cash. Negative = cash leaves the account (debit / long premium paid).
    # Convention: cash_flow = -sum(qty * fill_price * multiplier).
    net_cash = -sum(leg["qty"] * r.fill_price * multiplier
                     for leg, r in zip(legs, results))
    costs = cost_model.execution_costs([
        {"contracts": abs(leg["qty"]), "bid": r.bid, "ask": r.ask}
        for leg, r in zip(legs, results)
    ])
    return StructureFillResult(True, tuple(results), float(net_cash),
                                costs["total"], commission=costs["commission"],
                                slippage=costs["slippage"])


def close_leg(
    chain_row: pd.Series, qty_to_close: int, *,
    spread_max_pct: float = 0.25,
    multiplier: int = 100,
) -> FillResult:
    """Closing fill: invert sign of the held qty.

    Held long (qty>0) -> sell at BID (close).  Held short (qty<0) -> buy at
    ASK. Same rejection rules as open.
    """
    if chain_row.get("contract_multiplier", multiplier) != multiplier:
        return FillResult(False, np.nan, "sell" if qty_to_close > 0 else "buy",
                          np.nan, np.nan, np.nan, "contract_multiplier_mismatch")
    # Closing a +qty long means selling -qty contracts (passing qty=-1).
    return fill_leg(chain_row, -qty_to_close, spread_max_pct=spread_max_pct)
