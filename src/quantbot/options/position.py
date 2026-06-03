"""V5.0 options backtest position state.

Tracks one open structure through time: per-leg fill prices, current
conservative MTM, realised vs unrealised P&L, daily net Greeks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

import numpy as np
import pandas as pd

from . import contract_selector as cs
from .payoff import call_payoff, put_payoff


@dataclass
class BacktestLeg:
    """One leg in an open structure (after fill)."""

    option_type: str            # 'call' / 'put'
    expiration: pd.Timestamp
    strike: float
    qty: int                    # +1 long, -1 short (per spread)
    fill_price: float           # per-share premium at entry
    multiplier: int = 100


@dataclass
class BacktestPosition:
    structure_name: str
    underlying: str
    decision_date: pd.Timestamp
    fill_date: pd.Timestamp
    expiration: pd.Timestamp
    legs: list[BacktestLeg]
    open_cost: float            # transaction cost charged at entry ($)
    net_entry_cash: float       # signed: negative = debit paid out
    max_profit: float           # absolute $ at expiration (>=0)
    max_loss: float             # signed; <=0
    width: float                # $ between long/short strikes (0 if single leg)

    # mutable state
    closed: bool = False
    close_date: pd.Timestamp | None = None
    close_reason: str = ""
    realized_pnl: float = 0.0       # final P&L after the position closes
    paper_pnl: float = 0.0          # current conservative-close P&L (MTM)
    close_cost: float = 0.0
    last_mtm_value: float = 0.0     # net cash if closed today (conservative)
    daily_records: list[dict] = field(default_factory=list)
    is_naked: bool = False          # defined-risk only by construction

    # ------------------------------------------------------------------ #
    def mark(self, chain_today: pd.DataFrame, as_of: pd.Timestamp) -> dict:
        """Update conservative MTM + capture today's Greeks snapshot.

        Returns the daily-record dict.
        """
        net_close_cash = 0.0
        delta = gamma = theta = vega = 0.0
        for leg in self.legs:
            row = cs.lookup_row(chain_today, expiration=leg.expiration,
                                 option_type=leg.option_type, strike=leg.strike)
            if row is None:
                # No quote today for this leg; carry last paper P&L.
                continue
            # Conservative close price: longs sell at BID, shorts buy at ASK.
            close_px = float(row["bid"]) if leg.qty > 0 else float(row["ask"])
            net_close_cash += leg.qty * close_px * leg.multiplier
            # Provider Greeks are per-1-contract delta etc.; aggregate to
            # position scale (qty * multiplier).
            for nm, accum in (("delta", "d"), ("gamma", "g"),
                              ("theta", "t"), ("vega", "v")):
                v = row.get(nm)
                if pd.isna(v):
                    continue
                if nm == "delta":
                    delta += leg.qty * float(v) * leg.multiplier
                elif nm == "gamma":
                    gamma += leg.qty * float(v) * leg.multiplier
                elif nm == "theta":
                    theta += leg.qty * float(v) * leg.multiplier
                elif nm == "vega":
                    vega += leg.qty * float(v) * leg.multiplier

        # Paper P&L = cash received from closing now + cash paid at open.
        self.last_mtm_value = float(net_close_cash)
        self.paper_pnl = float(net_close_cash + self.net_entry_cash
                                - self.open_cost)
        record = {
            "date": pd.Timestamp(as_of),
            "paper_pnl": self.paper_pnl,
            "mtm_close_cash": self.last_mtm_value,
            "delta": float(delta), "gamma": float(gamma),
            "theta": float(theta), "vega": float(vega),
        }
        self.daily_records.append(record)
        return record

    # ------------------------------------------------------------------ #
    def settle_at_expiration(self, chain_today: pd.DataFrame,
                              expiration_date: pd.Timestamp) -> float:
        """Intrinsic-payoff settlement using the chain's underlying_price on
        the expiration date. Returns final realized P&L (the engine still
        charges any exit cost separately; expiration here is free)."""
        # Spot at expiry from any row on this date.
        if chain_today.empty:
            spot = float(self.legs[0].strike)   # degenerate fallback
        else:
            spot = float(chain_today["underlying_price"].iloc[0])
        terminal_cash = 0.0
        for leg in self.legs:
            f = call_payoff if leg.option_type == "call" else put_payoff
            intrinsic = float(f(spot, leg.strike))
            terminal_cash += leg.qty * intrinsic * leg.multiplier
        # Realised P&L = open cash + terminal value - open cost.
        self.realized_pnl = float(terminal_cash + self.net_entry_cash
                                    - self.open_cost)
        self.closed = True
        self.close_date = pd.Timestamp(expiration_date)
        self.close_reason = "expiration"
        return self.realized_pnl

    def close_at(self, fill_results: Iterable["FillResult"],  # noqa: F821
                  close_date: pd.Timestamp, *, cost: float,
                  reason: str) -> float:
        """Close every leg at today's conservative fills. Realised P&L =
        open cash + close cash - open_cost - close_cost."""
        close_cash = 0.0
        fill_results = list(fill_results)
        if len(fill_results) != len(self.legs):
            raise ValueError("fill_results length must match legs")
        for leg, fr in zip(self.legs, fill_results):
            # Sign on close: long sold (cash IN at bid * qty * mult);
            # short bought back (cash OUT = -|qty| * ask * mult). The
            # generic formula: qty * close_price * mult where close_price
            # is bid for long (qty>0, fill side='sell') and ask for short
            # (qty<0, fill side='buy').
            close_cash += leg.qty * fr.fill_price * leg.multiplier
        self.realized_pnl = float(close_cash + self.net_entry_cash
                                    - self.open_cost - cost)
        self.close_cost = float(cost)
        self.closed = True
        self.close_date = pd.Timestamp(close_date)
        self.close_reason = reason
        return self.realized_pnl

    # ------------------------------------------------------------------ #
    def dte(self, as_of: pd.Timestamp) -> int:
        return int((pd.Timestamp(self.expiration) - pd.Timestamp(as_of)).days)
