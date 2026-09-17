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
from .fill_model import quote_prices


@dataclass
class BacktestLeg:
    """One leg in an open structure (after fill)."""

    option_type: str            # 'call' / 'put'
    expiration: pd.Timestamp
    strike: float
    qty: int                    # +1 long, -1 short (per spread)
    fill_price: float           # per-share premium at entry
    multiplier: int = 100
    underlying: str = ""
    mark_price: float | None = None
    mark_date: pd.Timestamp | None = None

    @property
    def identity(self) -> str:
        """Full contract identity for errors and audit records."""
        return (f"{self.underlying} {pd.Timestamp(self.expiration).date()} "
                f"{self.option_type} {self.strike:g}")


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
    net_exit_cash: float = 0.0
    open_commission: float = 0.0
    open_slippage: float = 0.0
    close_commission: float = 0.0
    close_slippage: float = 0.0

    def __post_init__(self) -> None:
        for leg in self.legs:
            if leg.underlying and leg.underlying != self.underlying:
                raise ValueError("mixed underlying structure is unsupported")
            if pd.Timestamp(leg.expiration) != pd.Timestamp(self.expiration):
                raise ValueError("mixed expiration structure is unsupported")
            leg.underlying = self.underlying

    # ------------------------------------------------------------------ #
    def mark(self, chain_today: pd.DataFrame, as_of: pd.Timestamp) -> dict:
        """Update conservative MTM + capture today's Greeks snapshot.

        Returns the daily-record dict.
        """
        if self.closed:
            raise ValueError("cannot mark a closed position")
        if pd.Timestamp(as_of) >= self.expiration:
            raise ValueError(f"expiration settlement required for {self.underlying} "
                             f"{self.expiration.date()} before mark on {as_of.date()}")
        net_close_cash = 0.0
        marks = []
        delta = gamma = theta = vega = 0.0
        for leg in self.legs:
            context = f"{leg.identity} on {pd.Timestamp(as_of).date()}"
            try:
                row = cs.lookup_row(chain_today, expiration=leg.expiration,
                                    underlying=self.underlying,
                                    option_type=leg.option_type, strike=leg.strike)
                if row is None or pd.Timestamp(row["date"]) != pd.Timestamp(as_of):
                    raise ValueError("missing current quote")
                if row.get("contract_multiplier", leg.multiplier) != leg.multiplier:
                    raise ValueError("contract multiplier changed or unsupported")
                bid, ask = quote_prices(row)
            except (ValueError, KeyError, TypeError) as exc:
                raise ValueError(f"required option mark {context}: {exc}") from exc
            # Conservative close price: longs sell at BID, shorts buy at ASK.
            close_px = bid if leg.qty > 0 else ask
            marks.append(close_px)
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
        for leg, price in zip(self.legs, marks):
            leg.mark_price, leg.mark_date = price, pd.Timestamp(as_of)
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
    def expiration_value(self, chain_today: pd.DataFrame,
                         expiration_date: pd.Timestamp) -> tuple[float, float]:
        """Validate expiry-day spot and compute intrinsic cash without mutation.

        Research cash settlement only: no physical delivery/early assignment.
        The input spot must be the intended settlement observation; it is not
        assumed to be an official exchange settlement fixing.
        """
        context = f"expiration {self.underlying} {self.expiration.date()}"
        if self.closed:
            raise ValueError(f"{context}: already closed")
        if pd.Timestamp(expiration_date) != pd.Timestamp(self.expiration):
            raise ValueError(f"{context}: missing exact expiration date")
        sub = chain_today[
            (chain_today["underlying"] == self.underlying)
            & (pd.to_datetime(chain_today["date"]) == pd.Timestamp(expiration_date))
        ]
        spots = pd.to_numeric(sub["underlying_price"], errors="coerce").to_numpy()
        if (len(spots) == 0 or not np.isfinite(spots).all() or (spots < 0).any()
                or not np.allclose(spots, spots[0], rtol=0, atol=1e-8)):
            raise ValueError(f"{context}: missing, invalid or conflicting settlement spot")
        spot = float(spots[0])
        terminal_cash = 0.0
        for leg in self.legs:
            f = call_payoff if leg.option_type == "call" else put_payoff
            intrinsic = float(f(spot, leg.strike))
            terminal_cash += leg.qty * intrinsic * leg.multiplier
        return spot, float(terminal_cash)

    def settle_at_expiration(self, chain_today: pd.DataFrame,
                              expiration_date: pd.Timestamp) -> float:
        """Settle all legs atomically to intrinsic cash; no expiration fee."""
        _, terminal_cash = self.expiration_value(chain_today, expiration_date)
        # Realised P&L = open cash + terminal value - open cost.
        self.realized_pnl = float(terminal_cash + self.net_entry_cash
                                    - self.open_cost)
        self.closed = True
        self.close_date = pd.Timestamp(expiration_date)
        self.close_reason = "expiration"
        self.net_exit_cash = terminal_cash
        self.last_mtm_value = self.paper_pnl = 0.0
        return self.realized_pnl

    def close_at(self, fill_results: Iterable["FillResult"],  # noqa: F821
                  close_date: pd.Timestamp, *, cost: float,
                  reason: str) -> float:
        """Close every leg at today's conservative fills. Realised P&L =
        open cash + close cash - open_cost - close_cost."""
        if self.closed:
            raise ValueError("position already closed")
        close_cash = 0.0
        fill_results = list(fill_results)
        if len(fill_results) != len(self.legs):
            raise ValueError("fill_results length must match legs")
        for leg, fr in zip(self.legs, fill_results):
            if (not fr.accepted or not np.isfinite(fr.fill_price) or fr.fill_price < 0
                    or fr.side != ("sell" if leg.qty > 0 else "buy")):
                raise ValueError(f"invalid closing fill for {leg.identity}")
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
        self.net_exit_cash = float(close_cash)
        self.last_mtm_value = self.paper_pnl = 0.0
        return self.realized_pnl

    # ------------------------------------------------------------------ #
    def dte(self, as_of: pd.Timestamp) -> int:
        return int((pd.Timestamp(self.expiration) - pd.Timestamp(as_of)).days)
