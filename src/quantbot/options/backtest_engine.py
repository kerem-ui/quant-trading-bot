"""V5.0 options backtest engine (proof-of-engine).

Mechanics, not strategy quality. The engine is intentionally minimal:

  - Decisions on bar ``t`` use ONLY chain rows where ``date == t``.
  - Orders submitted on bar ``t`` execute on the NEXT trading bar.
  - Open positions are marked-to-market each bar using conservative quotes
    (longs at BID, shorts at ASK).
  - On a leg's expiration date the position settles to intrinsic value
    using a validated same-underlying spot on that exact date (research cash
    settlement, not physical American exercise/assignment).
  - Defined-risk only: candidates flagged ``is_naked`` are rejected.
  - Costs (entry + close) are charged through ``OptionsCostModel``.
  - At the final bar any still-open position is force-closed at the
    executable bid/ask (with fees), under the normal spread gate. A missing
    required mark or unexecutable terminal close aborts explicitly.

Causality guarantee
-------------------
* ``decision_date < fill_date`` is asserted for every executed open and
  every executed close (never same-day).
* The decision step receives a ``chain_today`` slice; it cannot ask the
  engine for any other date.

This engine is the only component that touches the date axis; strategies
remain pure decision functions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from ..costs.transaction_costs import OptionsCostModel
from . import contract_selector as cs
from .fill_model import close_leg, fill_structure
from .position import BacktestLeg, BacktestPosition
from .risk import OptionsRiskLimits, evaluate_candidate
from .spreads import Candidate
from .strategy_base import OptionsStrategy


# --------------------------------------------------------------------------- #
@dataclass
class PendingOpen:
    decision_date: pd.Timestamp
    candidate: Candidate


@dataclass
class PendingClose:
    decision_date: pd.Timestamp
    position: BacktestPosition
    reason: str


@dataclass
class Rejection:
    date: pd.Timestamp
    stage: str                   # 'candidate' | 'risk' | 'fill_open' | 'fill_close'
    reason: str
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class TradeRecord:
    structure: str
    underlying: str
    decision_open: pd.Timestamp
    fill_open: pd.Timestamp
    decision_close: pd.Timestamp | None
    fill_close: pd.Timestamp
    close_reason: str
    net_entry_cash: float        # signed; negative = debit
    open_cost: float
    close_cost: float
    realized_pnl: float
    width: float
    max_profit: float
    max_loss: float
    legs: list[dict] = field(default_factory=list)
    net_exit_cash: float = 0.0
    open_commission: float = 0.0
    open_slippage: float = 0.0
    close_commission: float = 0.0
    close_slippage: float = 0.0


@dataclass
class OptionsBacktestResult:
    initial_capital: float
    equity_curve: pd.Series
    daily_returns: pd.Series
    cash_curve: pd.Series
    daily_greeks: pd.DataFrame
    trades: list[TradeRecord]
    orders: list[dict]           # open/close orders log
    rejections: list[Rejection]
    total_cost: float
    config: dict = field(default_factory=dict)
    event_ledger: list[dict] = field(default_factory=list)

    # --- metrics ------------------------------------------------------- #
    @property
    def total_return(self) -> float:
        if len(self.equity_curve) == 0:
            return 0.0
        return float(self.equity_curve.iloc[-1] / self.initial_capital - 1.0)

    @property
    def n_trades(self) -> int:
        return len(self.trades)

    def win_rate(self) -> float:
        pnls = [t.realized_pnl for t in self.trades]
        if not pnls:
            return float("nan")
        wins = sum(1 for p in pnls if p > 0)
        return wins / len(pnls)

    def avg_win_loss(self) -> tuple[float, float]:
        pnls = [t.realized_pnl for t in self.trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        return (
            float(np.mean(wins)) if wins else float("nan"),
            float(np.mean(losses)) if losses else float("nan"),
        )

    def worst_trade(self) -> TradeRecord | None:
        if not self.trades:
            return None
        return min(self.trades, key=lambda t: t.realized_pnl)

    def max_drawdown(self) -> float:
        eq = self.equity_curve
        if len(eq) == 0:
            return 0.0
        peak = eq.cummax()
        dd = eq / peak - 1.0
        return float(dd.min())

    def to_trades_frame(self) -> pd.DataFrame:
        rows = []
        for t in self.trades:
            rows.append({
                "structure": t.structure,
                "underlying": t.underlying,
                "decision_open": t.decision_open,
                "fill_open": t.fill_open,
                "fill_close": t.fill_close,
                "close_reason": t.close_reason,
                "width": t.width,
                "net_entry_cash": t.net_entry_cash,
                "open_cost": t.open_cost,
                "close_cost": t.close_cost,
                "max_profit": t.max_profit,
                "max_loss": t.max_loss,
                "realized_pnl": t.realized_pnl,
                "net_exit_cash": t.net_exit_cash,
                "open_commission": t.open_commission,
                "open_slippage": t.open_slippage,
                "close_commission": t.close_commission,
                "close_slippage": t.close_slippage,
            })
        return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
@dataclass
class _PortfolioView:
    """Read-only view passed to the strategy hook (no engine internals)."""

    cash: float
    equity: float
    open_positions: int
    portfolio_defined_loss: float


# --------------------------------------------------------------------------- #
class OptionsBacktestEngine:
    """Run a single options strategy on a canonical chain DataFrame.

    Parameters
    ----------
    chain : pd.DataFrame
        Canonical-schema chain (see :mod:`quantbot.data.options_chain_loader`).
    strategy : OptionsStrategy
    initial_capital : float
    limits : OptionsRiskLimits
    cost_model : OptionsCostModel | None
    """

    def __init__(
        self,
        chain: pd.DataFrame,
        strategy: OptionsStrategy,
        *,
        initial_capital: float = 100_000.0,
        limits: OptionsRiskLimits | None = None,
        cost_model: OptionsCostModel | None = None,
    ):
        if "date" not in chain.columns:
            raise ValueError("chain must have a 'date' column")
        self.chain = chain.copy()
        self.chain["date"] = pd.to_datetime(self.chain["date"]).dt.normalize()
        self.chain["expiration"] = pd.to_datetime(self.chain["expiration"]).dt.normalize()
        self.strategy = strategy
        self.initial_capital = float(initial_capital)
        self.limits = limits or OptionsRiskLimits()
        self.cost_model = cost_model or OptionsCostModel()

        self._dates: list[pd.Timestamp] = sorted(self.chain["date"].unique().tolist())
        self._cash: float = self.initial_capital
        self._open_positions: list[BacktestPosition] = []
        self._pending_opens: list[PendingOpen] = []
        self._pending_closes: list[PendingClose] = []
        self._trades: list[TradeRecord] = []
        self._orders: list[dict] = []
        self._rejections: list[Rejection] = []
        self._equity_records: list[dict] = []
        self._greeks_records: list[dict] = []
        self._total_cost: float = 0.0
        self._event_ledger: list[dict] = []

    def _record_event(self, t: pd.Timestamp, event: str) -> None:
        """Snapshot cash and signed holdings at their latest valid marks.

        Each mark carries its own date; end-of-day marks are always current.
        Reconcile both the balance sheet and cumulative position P&L.
        """
        active = [p for p in self._open_positions if not p.closed]
        holdings = [dict(underlying=l.underlying, expiration=l.expiration,
                         option_type=l.option_type, strike=l.strike, qty=l.qty,
                         multiplier=l.multiplier, mark_price=l.mark_price,
                         mark_date=l.mark_date) for p in active for l in p.legs]
        equity = self._cash + sum(p.last_mtm_value for p in active)
        realized = sum(tr.realized_pnl for tr in self._trades)
        unrealized = sum(p.paper_pnl for p in active)
        marked = sum(l["qty"] * l["multiplier"] * l["mark_price"] for l in holdings)
        if not (np.isfinite(equity)
                and np.isclose(self._cash + marked, equity, rtol=1e-12, atol=1e-8)
                and np.isclose(self.initial_capital + realized + unrealized, equity,
                               rtol=1e-12, atol=1e-8)):
            raise ValueError(f"option accounting reconciliation failed on {t.date()}: {event}")
        self._event_ledger.append(dict(date=t, event=event, cash=self._cash,
            equity=equity, holdings=holdings, realized_pnl=realized,
            unrealized_pnl=unrealized))

    @staticmethod
    def _leg_records(pos: BacktestPosition, fills=None, *, spot=None) -> list[dict]:
        """Executed premium/settlement details; qty is signed transaction quantity."""
        records = []
        for i, leg in enumerate(pos.legs):
            qty, price = leg.qty, leg.fill_price
            if fills is not None:
                qty, price = -qty, fills[i].fill_price
            elif spot is not None:
                qty = -qty
                price = max(0.0, spot-leg.strike) if leg.option_type == "call" else max(0.0, leg.strike-spot)
            records.append(dict(underlying=leg.underlying, expiration=leg.expiration,
                option_type=leg.option_type, strike=leg.strike, qty=qty,
                multiplier=leg.multiplier, fill_price=price,
                side="buy" if qty > 0 else "sell", notional=abs(qty)*price*leg.multiplier,
                cash_flow=-qty*price*leg.multiplier))
        return records

    def _record_trade(self, pos: BacktestPosition, decision_date) -> None:
        self._trades.append(TradeRecord(
            structure=pos.structure_name, underlying=pos.underlying,
            decision_open=pos.decision_date, fill_open=pos.fill_date,
            decision_close=decision_date, fill_close=pos.close_date,
            close_reason=pos.close_reason, net_entry_cash=pos.net_entry_cash,
            open_cost=pos.open_cost, close_cost=pos.close_cost,
            realized_pnl=pos.realized_pnl, width=pos.width,
            max_profit=pos.max_profit, max_loss=pos.max_loss,
            legs=self._leg_records(pos), net_exit_cash=pos.net_exit_cash,
            open_commission=pos.open_commission, open_slippage=pos.open_slippage,
            close_commission=pos.close_commission, close_slippage=pos.close_slippage))

    # ---------------------------------------------------------------- #
    @property
    def _portfolio_defined_loss(self) -> float:
        return float(sum(abs(p.max_loss) for p in self._open_positions if not p.closed))

    def _portfolio_view(self) -> _PortfolioView:
        active = [p for p in self._open_positions if not p.closed]
        equity = self._cash + sum(p.last_mtm_value for p in active)
        return _PortfolioView(
            cash=self._cash, equity=equity,
            open_positions=len(active),
            portfolio_defined_loss=self._portfolio_defined_loss,
        )

    # ---------------------------------------------------------------- #
    def _chain_on(self, date: pd.Timestamp) -> pd.DataFrame:
        return self.chain[self.chain["date"] == pd.Timestamp(date).normalize()]

    # ---------------------------------------------------------------- #
    def _execute_pending_opens(self, t: pd.Timestamp,
                                chain_today: pd.DataFrame) -> None:
        """Open every queued candidate using TODAY's quotes."""
        still_pending: list[PendingOpen] = []
        for po in self._pending_opens:
            # Hard causality assertion - never same-day.
            assert po.decision_date < t, (
                f"causality violation: open decided {po.decision_date} "
                f"cannot fill {t}"
            )
            cand = po.candidate
            if cand.expiration <= t:
                self._rejections.append(Rejection(
                    t, "fill_open", "expiration_on_or_before_fill",
                    {"underlying": cand.underlying, "expiration": str(cand.expiration)}))
                continue
            if any(leg["underlying"] != cand.underlying
                   or leg["expiration"] != cand.expiration
                   or leg["multiplier"] != 100 for leg in cand.legs):
                self._rejections.append(Rejection(t, "fill_open",
                    "unsupported_or_mismatched_contract_identity",
                    {"underlying": cand.underlying, "legs": cand.legs}))
                continue

            # Re-fill at TODAY's quotes (the spread-builder fill was a
            # decision-day snapshot used only to size risk; the real
            # execution uses next-bar quotes).
            rows: list[pd.Series] = []
            ok = True
            for leg in cand.legs:
                row = cs.lookup_row(
                    chain_today, underlying=cand.underlying, expiration=cand.expiration,
                    option_type=leg["option_type"], strike=leg["strike"],
                )
                if row is None:
                    ok = False
                    self._rejections.append(Rejection(
                        date=t, stage="fill_open",
                        reason="leg_missing_on_fill_day",
                        meta={"leg": leg, "underlying": cand.underlying,
                              "expiration": str(cand.expiration.date())},
                    ))
                    break
                rows.append(row)
            if not ok:
                continue

            fill = fill_structure(
                cand.legs, rows,
                spread_max_pct=self.limits.spread_max_pct,
                cost_model=self.cost_model,
            )
            if not fill.accepted:
                self._rejections.append(Rejection(
                    date=t, stage="fill_open",
                    reason=fill.reject_reason,
                    meta={"structure": cand.structure_name},
                ))
                continue

            # Recompute risk metrics from the actual fill quotes.
            net_cash = float(fill.net_cash)
            debit = max(0.0, -net_cash)
            credit = max(0.0, net_cash)
            # Bull call spread is debit; max_profit = width*100 - debit
            # max_loss = -debit. For a credit spread the engine still works
            # but the strategy/spread builder owns those formulas; here we
            # rebuild the canonical defined-risk numbers from the candidate's
            # ``width`` and net cash, matching ``build_bull_call_spread``.
            width_cash = cand.width * 100.0 * abs(cand.legs[0]["qty"])
            if debit > 0:
                max_loss = -debit
                max_profit = max(0.0, width_cash - debit)
            else:
                max_loss = -(width_cash - credit)
                max_profit = credit

            # Risk re-check against the actual fill.
            class _C:
                pass
            ctmp = _C()
            ctmp.net_cash = net_cash
            ctmp.max_loss = max_loss
            ctmp.width = cand.width
            ctmp.is_naked = bool(cand.is_naked)
            decision = evaluate_candidate(
                ctmp, self.limits,
                current_open_positions=sum(not p.closed for p in self._open_positions),
                initial_capital=self.initial_capital,
                current_portfolio_defined_loss=self._portfolio_defined_loss,
            )
            if not decision.accepted:
                self._rejections.append(Rejection(
                    date=t, stage="risk",
                    reason=decision.reason,
                    meta={"structure": cand.structure_name, "stage": "post_fill"},
                ))
                continue

            # Build position.
            legs_state: list[BacktestLeg] = []
            for leg, fr in zip(cand.legs, fill.legs):
                legs_state.append(BacktestLeg(
                    option_type=leg["option_type"],
                    expiration=cand.expiration,
                    strike=float(leg["strike"]),
                    qty=int(leg["qty"]),
                    fill_price=float(fr.fill_price),
                    underlying=cand.underlying,
                ))
            pos = BacktestPosition(
                structure_name=cand.structure_name,
                underlying=cand.underlying,
                decision_date=po.decision_date,
                fill_date=t,
                expiration=cand.expiration,
                legs=legs_state,
                open_cost=float(fill.cost),
                net_entry_cash=net_cash,
                max_profit=float(max_profit),
                max_loss=float(max_loss),
                width=float(cand.width),
                is_naked=bool(cand.is_naked),
                open_commission=fill.commission,
                open_slippage=fill.slippage,
            )
            # Establish a complete valid mark before booking any cash/holdings.
            pos.mark(chain_today, t)
            # Cash flow at open: net_cash is signed; cost is always a debit.
            self._cash += net_cash - fill.cost
            self._total_cost += float(fill.cost)
            self._open_positions.append(pos)
            self._orders.append({
                "type": "open",
                "decision_date": po.decision_date,
                "fill_date": t,
                "structure": cand.structure_name,
                "net_cash": net_cash,
                "cost": fill.cost,
                "commission": fill.commission,
                "slippage": fill.slippage,
                "spread_cost": 0.0,
                "legs": self._leg_records(pos),
                "underlying": pos.underlying,
                "expiration": cand.expiration,
                "meta": dict(cand.meta),
            })
            self._record_event(t, "open")
        # All processed; clear queue.
        self._pending_opens = still_pending  # always empty here

    # ---------------------------------------------------------------- #
    def _execute_pending_closes(self, t: pd.Timestamp,
                                 chain_today: pd.DataFrame) -> None:
        for pc in self._pending_closes:
            assert pc.decision_date < t, (
                f"causality violation: close decided {pc.decision_date} "
                f"cannot fill {t}"
            )
            pos = pc.position
            if pos.closed:
                continue
            # Try to fill all legs conservatively.
            results = []
            close_cash = 0.0
            cost_legs = []
            failed_reason = ""
            for leg in pos.legs:
                row = cs.lookup_row(
                    chain_today, underlying=pos.underlying, expiration=leg.expiration,
                    option_type=leg.option_type, strike=leg.strike,
                )
                if row is None:
                    failed_reason = f"leg_missing_on_close_day: {leg.identity} on {t.date()}"
                    break
                fr = close_leg(row, leg.qty,
                                spread_max_pct=self.limits.spread_max_pct,
                                multiplier=leg.multiplier)
                if not fr.accepted:
                    failed_reason = f"{fr.reject_reason}: {leg.identity} on {t.date()}"
                    break
                results.append(fr)
                close_cash += leg.qty * fr.fill_price * leg.multiplier
                cost_legs.append({"contracts": abs(leg.qty),
                                   "bid": fr.bid, "ask": fr.ask})
            if failed_reason:
                # Could not close cleanly; defer to next bar by re-queueing.
                self._rejections.append(Rejection(
                    date=t, stage="fill_close",
                    reason=failed_reason,
                    meta={"structure": pos.structure_name,
                          "decision_date": str(pc.decision_date.date())},
                ))
                # Re-queue with decision_date=t so it fires next bar.
                self._pending_closes_next.append(PendingClose(
                    decision_date=t, position=pos, reason=pc.reason,
                ))
                continue

            costs = self.cost_model.execution_costs(cost_legs)
            cost = costs["total"]
            pos.close_at(results, t, cost=cost, reason=pc.reason)
            pos.close_commission = costs["commission"]
            pos.close_slippage = costs["slippage"]
            self._cash += close_cash - cost
            self._total_cost += float(cost)
            self._orders.append({
                "type": "close",
                "decision_date": pc.decision_date,
                "fill_date": t,
                "structure": pos.structure_name,
                "close_cash": close_cash,
                "cost": cost,
                "commission": costs["commission"],
                "slippage": costs["slippage"],
                "spread_cost": 0.0,
                "reason": pc.reason,
                "underlying": pos.underlying,
                "legs": self._leg_records(pos, results),
            })
            self._record_trade(pos, pc.decision_date)
            self._record_event(t, "close")
        # Reset queue: only carry the deferrals.
        self._pending_closes = self._pending_closes_next
        self._pending_closes_next = []

    # ---------------------------------------------------------------- #
    def _settle_expirations(self, t: pd.Timestamp,
                             chain_today: pd.DataFrame) -> None:
        """For any open position whose expiration == t, settle intrinsic."""
        for pos in list(self._open_positions):
            if pos.closed:
                continue
            if pd.Timestamp(pos.expiration) < pd.Timestamp(t):
                raise ValueError(f"missing expiration observation for {pos.underlying} "
                                 f"{pos.expiration.date()} before {t.date()}")
            if pd.Timestamp(pos.expiration).normalize() != pd.Timestamp(t).normalize():
                continue
            spot, terminal_cash = pos.expiration_value(chain_today, t)
            pos.settle_at_expiration(chain_today, t)
            self._cash += terminal_cash
            self._orders.append({
                "type": "expire",
                "decision_date": None,
                "fill_date": t,
                "structure": pos.structure_name,
                "terminal_cash": terminal_cash,
                "spot": spot,
                "reason": "expiration",
                "underlying": pos.underlying,
                "legs": self._leg_records(pos, spot=spot),
                "cost": 0.0, "commission": 0.0, "slippage": 0.0, "spread_cost": 0.0,
                "settlement_convention": "intrinsic_cash",
            })
            self._record_trade(pos, None)
            self._record_event(t, "expire")

    # ---------------------------------------------------------------- #
    def _mark_all(self, t: pd.Timestamp, chain_today: pd.DataFrame) -> dict:
        """Mark MTM for every open position; aggregate daily Greeks."""
        net_d = net_g = net_t = net_v = 0.0
        for pos in self._open_positions:
            if pos.closed:
                continue
            rec = pos.mark(chain_today, t)
            net_d += rec["delta"]
            net_g += rec["gamma"]
            net_t += rec["theta"]
            net_v += rec["vega"]
        return {"date": t, "delta": net_d, "gamma": net_g,
                "theta": net_t, "vega": net_v}

    # ---------------------------------------------------------------- #
    def _record_equity(self, t: pd.Timestamp) -> None:
        open_mtm = sum(p.last_mtm_value for p in self._open_positions
                        if not p.closed)
        equity = self._cash + open_mtm
        self._equity_records.append({
            "date": t, "cash": self._cash,
            "open_mtm": open_mtm, "equity": equity,
        })

    # ---------------------------------------------------------------- #
    def _force_close_remaining(self, t: pd.Timestamp,
                                chain_today: pd.DataFrame) -> None:
        """Final bar: close everything still open at conservative MTM."""
        for pos in list(self._open_positions):
            if pos.closed:
                continue
            # If expiration == today, settlement already handled it.
            if pd.Timestamp(pos.expiration).normalize() == pd.Timestamp(t).normalize():
                continue
            results = []
            close_cash = 0.0
            cost_legs = []
            failed = False
            for leg in pos.legs:
                row = cs.lookup_row(
                    chain_today, underlying=pos.underlying, expiration=leg.expiration,
                    option_type=leg.option_type, strike=leg.strike,
                )
                if row is None:
                    failed = True
                    failed_reason = "missing quote"
                    break
                fr = close_leg(row, leg.qty,
                                spread_max_pct=self.limits.spread_max_pct,
                                multiplier=leg.multiplier)
                if not fr.accepted:
                    failed = True
                    failed_reason = fr.reject_reason
                    break
                results.append(fr)
                close_cash += leg.qty * fr.fill_price * leg.multiplier
                cost_legs.append({"contracts": abs(leg.qty),
                                   "bid": fr.bid, "ask": fr.ask})
            if failed:
                self._rejections.append(Rejection(
                    date=t, stage="fill_close",
                    reason=failed_reason,
                    meta={"structure": pos.structure_name, "contract": leg.identity},
                ))
                raise ValueError(f"terminal exit failed for {leg.identity} on {t.date()}: "
                                 f"{failed_reason}; entire structure remains open")
            costs = self.cost_model.execution_costs(cost_legs)
            cost = costs["total"]
            pos.close_at(results, t, cost=cost, reason="force_close_final_bar")
            pos.close_commission = costs["commission"]
            pos.close_slippage = costs["slippage"]
            self._cash += close_cash - cost
            self._total_cost += float(cost)
            self._orders.append({
                "type": "close",
                "decision_date": None,
                "fill_date": t,
                "structure": pos.structure_name,
                "close_cash": close_cash,
                "cost": cost,
                "commission": costs["commission"],
                "slippage": costs["slippage"],
                "spread_cost": 0.0,
                "reason": "force_close_final_bar",
                "underlying": pos.underlying,
                "legs": self._leg_records(pos, results),
            })
            self._record_trade(pos, None)
            self._record_event(t, "close")

    # ---------------------------------------------------------------- #
    def run(self) -> OptionsBacktestResult:
        """Execute the backtest and return an :class:`OptionsBacktestResult`."""
        self._pending_closes_next: list[PendingClose] = []
        if not self._dates:
            return self._materialize_result()

        for i, t in enumerate(self._dates):
            chain_today = self._chain_on(t)
            is_last = (i == len(self._dates) - 1)

            # Expired contracts cannot execute on a later bar. Expiry is an
            # intrinsic cash event, before queued orders at the daily quote.
            self._settle_expirations(t, chain_today)

            # 1) Execute orders queued from prior decision dates.
            #    Opens use today's quotes; closes use today's quotes.
            #    (decision_date < t is asserted inside.)
            if self._pending_opens:
                self._execute_pending_opens(t, chain_today)
            if self._pending_closes:
                self._execute_pending_closes(t, chain_today)

            # 3) Mark every open position to market.
            greeks_rec = self._mark_all(t, chain_today)
            self._greeks_records.append(greeks_rec)
            self._record_event(t, "mark")

            # 4) Strategy decisions for the NEXT bar (closes first, opens
            #    second -- so a same-day exit signal does not block a new
            #    open candidate). Closes always evaluated for all open
            #    positions; opens only when capacity exists.
            for pos in self._open_positions:
                if pos.closed:
                    continue
                want, reason = self.strategy.on_decision_close(
                    pos, chain_today, t,
                )
                if want:
                    self._pending_closes.append(PendingClose(
                        decision_date=t, position=pos, reason=reason,
                    ))

            # Strategy-level open decision (one candidate per bar by design).
            # Skip on the last bar (no next bar to fill on).
            if not is_last:
                portfolio = self._portfolio_view()
                cand = self.strategy.on_decision_open(t, chain_today, portfolio)
                if cand is not None:
                    if cand.reject_reason:
                        self._rejections.append(Rejection(
                            date=t, stage="candidate",
                            reason=cand.reject_reason,
                            meta={"structure": cand.structure_name},
                        ))
                    else:
                        decision = evaluate_candidate(
                            cand, self.limits,
                            current_open_positions=len(
                                [p for p in self._open_positions if not p.closed]
                            ),
                            initial_capital=self.initial_capital,
                            current_portfolio_defined_loss=self._portfolio_defined_loss,
                        )
                        if not decision.accepted:
                            self._rejections.append(Rejection(
                                date=t, stage="risk",
                                reason=decision.reason,
                                meta={"structure": cand.structure_name},
                            ))
                        else:
                            self._pending_opens.append(PendingOpen(
                                decision_date=t, candidate=cand,
                            ))

            # 5) Force-close remaining positions on the final bar.
            if is_last:
                self._force_close_remaining(t, chain_today)
                # Re-mark to update equity after force close.
                self._greeks_records[-1] = self._mark_all(t, chain_today)
                self._record_event(t, "mark")

            # 6) Record equity at end of bar.
            self._record_equity(t)

            # 7) Prune closed positions out of the open list.
            self._open_positions = [p for p in self._open_positions if not p.closed]

        return self._materialize_result()

    # ---------------------------------------------------------------- #
    def _materialize_result(self) -> OptionsBacktestResult:
        if self._equity_records:
            eq_df = pd.DataFrame(self._equity_records).set_index("date")
            equity_curve = eq_df["equity"]
            cash_curve = eq_df["cash"]
            daily_returns = equity_curve.pct_change().fillna(0.0)
        else:
            equity_curve = pd.Series(dtype=float)
            cash_curve = pd.Series(dtype=float)
            daily_returns = pd.Series(dtype=float)
        greeks_df = (pd.DataFrame(self._greeks_records).set_index("date")
                       if self._greeks_records else pd.DataFrame())
        return OptionsBacktestResult(
            initial_capital=self.initial_capital,
            equity_curve=equity_curve,
            daily_returns=daily_returns,
            cash_curve=cash_curve,
            daily_greeks=greeks_df,
            trades=list(self._trades),
            orders=list(self._orders),
            rejections=list(self._rejections),
            total_cost=float(self._total_cost),
            event_ledger=list(self._event_ledger),
            config={
                "strategy": getattr(self.strategy, "name", "unknown"),
                "underlying": getattr(self.strategy, "underlying", ""),
                "limits": self.limits.__dict__,
                "cost_model": {
                    "per_contract_fee": self.cost_model.per_contract_fee,
                    "bid_ask_fraction": self.cost_model.bid_ask_fraction,
                    "multi_leg_penalty": self.cost_model.multi_leg_penalty,
                },
                "n_dates": len(self._dates),
                "settlement": "exact-expiry intrinsic cash research convention",
                "missing_marks": "raise; preserve last valid state; no completed result",
                "terminal_exit": "normal bid/ask gates or raise; never midpoint",
                "execution_costs": "commission + multi_leg_penalty; spread already in fills",
            },
        )
