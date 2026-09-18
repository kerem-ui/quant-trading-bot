"""ETF cash-and-quantity backtester with target-weight strategy inputs.

Timeline guarantee
------------------
For every rebalance date ``t``:
  1. The strategy produces target weights using ONLY data up to and including
     ``t`` (the strategy precomputes a causal weight panel; this is also
     unit-tested independently).
  2. The RiskManager adjusts those weights using the equity curve known at
     ``t`` (no future equity).
  3. Orders are created with ``signal_date = t`` and
     ``execution_date = t+1`` (the next trading bar). ``Order.__post_init__``
     hard-asserts ``execution_date > signal_date``.
  4. Fills occur at ``t+1``'s open or close (config) via SimulatedBroker.

Costs are charged on every executed trade. The short leg of dollar-neutral
strategies (S03) is additionally charged a daily borrow cost.

This is research/backtest only. No broker connectivity exists anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..costs.transaction_costs import EquityCostModel
from ..risk.risk_manager import RiskManager, RiskState
from ..utils.dates import rebalance_dates
from ..utils.logging import get_logger
from ..utils.math import TRADING_DAYS_PER_YEAR
from ..utils.market_calendar import USMarketCalendar
from .market_mechanics import CashBalanceModel, CorporateActionBook
from .broker import SimulatedBroker
from .order import Order, OrderStatus
from .position import Portfolio, required_mark

log = get_logger("backtest.engine")


@dataclass
class BacktestResult:
    equity_curve: pd.Series
    returns: pd.Series
    weights: pd.DataFrame
    orders: list[Order]
    risk_events: list[dict]
    total_cost: float
    initial_capital: float
    config: dict = field(default_factory=dict)
    # V2.1: split total_cost into its components for cost attribution.
    # total_cost == trading_cost + borrow_cost + financing_cost.
    trading_cost: float = 0.0
    borrow_cost: float = 0.0
    cash: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    quantities: pd.DataFrame = field(default_factory=pd.DataFrame)
    marks: pd.DataFrame = field(default_factory=pd.DataFrame)
    gross_pnl: pd.DataFrame = field(default_factory=pd.DataFrame)
    trading_costs: pd.DataFrame = field(default_factory=pd.DataFrame)
    borrow_costs: pd.DataFrame = field(default_factory=pd.DataFrame)
    ledger: list[dict] = field(default_factory=list)
    dividends: pd.DataFrame = field(default_factory=pd.DataFrame)
    cash_interest: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    financing_costs: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    financing_cost: float = 0.0
    pnl_components: pd.DataFrame = field(default_factory=pd.DataFrame)
    sessions: pd.DataFrame = field(default_factory=pd.DataFrame)

    @property
    def turnover_by_symbol(self) -> pd.DataFrame:
        """Executed absolute notional / pre-cost batch equity; price drift is not trading."""
        out = pd.DataFrame(0.0, index=self.weights.index, columns=self.weights.columns)
        for order in self.orders:
            if order.status == OrderStatus.FILLED:
                out.at[order.execution_date, order.symbol] += order.notional / order.allocation_equity
        return out

    @property
    def turnover_series(self) -> pd.Series:
        """Daily one-way turnover from actual executed fills."""
        return self.turnover_by_symbol.sum(axis=1)

    @property
    def annual_turnover(self) -> float:
        years = max(len(self.equity_curve) / TRADING_DAYS_PER_YEAR, 1e-9)
        return float(self.turnover_series.sum() / years)

    def turnover_attribution(self) -> dict:
        """Attribute executed turnover to entries, exits and resizing (including flips)."""
        entry = exit_ = resize = 0.0
        for order in self.orders:
            if order.status != OrderStatus.FILLED:
                continue
            turnover = order.notional / order.allocation_equity
            if order.quantity_before == 0:
                entry += turnover
            elif order.quantity_before + order.executed_quantity == 0:
                exit_ += turnover
            else:
                resize += turnover
        years = max(len(self.equity_curve) / TRADING_DAYS_PER_YEAR, 1e-9)
        tot = entry + exit_ + resize
        return {
            "entry": float(entry),
            "exit": float(exit_),
            "resize": float(resize),
            "total_oneway": float(tot),
            "annual_entry": float(entry / years),
            "annual_exit": float(exit_ / years),
            "annual_resize": float(resize / years),
            "entry_pct": float(entry / tot) if tot > 0 else 0.0,
            "exit_pct": float(exit_ / tot) if tot > 0 else 0.0,
            "resize_pct": float(resize / tot) if tot > 0 else 0.0,
        }

    def cost_attribution(self) -> dict:
        """Trading vs borrow split, and trading cost by side (buy/sell)."""
        buy = sum(
            o.cost for o in self.orders
            if o.status == OrderStatus.FILLED and o.executed_quantity >= 0
        )
        sell = sum(
            o.cost for o in self.orders
            if o.status == OrderStatus.FILLED and o.executed_quantity < 0
        )
        return {
            "trading_cost": float(self.trading_cost),
            "borrow_cost": float(self.borrow_cost),
            "financing_cost": float(self.financing_cost),
            "total_cost": float(self.total_cost),
            "trading_buy_cost": float(buy),
            "trading_sell_cost": float(sell),
            "borrow_pct_of_total": float(self.borrow_cost / self.total_cost)
            if self.total_cost > 0 else 0.0,
        }

    def exposure_diagnostics(self, eps: float = 1e-6) -> dict:
        """All-day vs active-day exposure (key for opportunistic books / S03)."""
        w = self.weights.fillna(0.0)
        gross = w.abs().sum(axis=1)
        net = w.sum(axis=1)
        active = gross > eps
        n_active = int(active.sum())
        out = {
            "all_day_avg_gross": float(gross.mean()),
            "all_day_avg_net": float(net.mean()),
            "n_days": int(len(gross)),
            "n_active_days": n_active,
            "active_day_fraction": float(active.mean()),
        }
        if n_active:
            ga, na = gross[active], net[active]
            out.update(
                {
                    "active_avg_gross": float(ga.mean()),
                    "active_median_gross": float(ga.median()),
                    "active_max_gross": float(ga.max()),
                    "active_avg_net": float(na.mean()),
                    "active_abs_net_over_gross": float((na.abs() / ga).mean()),
                }
            )
        return out


class BacktestEngine:
    def __init__(
        self,
        cost_model: EquityCostModel | None = None,
        risk_manager: RiskManager | None = None,
        execution: str = "next_open",
        initial_capital: float = 1_000_000.0,
        borrow_cost_bps_annual: float = 0.0,
        rebalance_band: float = 0.0,
        *,
        calendar: USMarketCalendar | None = None,
        price_mode: str = "adjusted",
        corporate_actions: CorporateActionBook | None = None,
        cash_interest_rate: float = 0.0,
        financing_rate: float | None = None,
        borrow_day_count: str = "sessions_252",
    ):
        self.cost_model = cost_model or EquityCostModel()
        self.risk_manager = risk_manager
        self.execution = execution
        self.initial_capital = initial_capital
        self.borrow_cost_bps_annual = borrow_cost_bps_annual
        self.calendar = calendar or USMarketCalendar()
        if price_mode not in ('adjusted','raw'):
            raise ValueError('price_mode must be adjusted or raw')
        if price_mode == 'adjusted' and corporate_actions is not None:
            raise ValueError('adjusted accounting cannot include explicit corporate actions')
        if price_mode == 'raw' and corporate_actions is None:
            raise ValueError('raw accounting requires a complete corporate-action book')
        if borrow_day_count not in ('sessions_252','actual_365'):
            raise ValueError('Unknown short borrow day count')
        if not np.isfinite(borrow_cost_bps_annual) or borrow_cost_bps_annual < 0:
            raise ValueError('Borrow rate must be finite nonnegative annual basis points')
        self.price_mode = price_mode
        self.corporate_actions = corporate_actions
        self.cash_model = CashBalanceModel(cash_interest_rate, financing_rate)
        self.borrow_day_count = borrow_day_count
        # V2 no-trade band: skip a name's order when the target vs current
        # weight change is below this absolute threshold. Kills the micro-churn
        # from continuously-varying inverse-vol weights being rebalanced every
        # period (a major V1 turnover/cost driver). 0.0 disables it.
        self.rebalance_band = float(rebalance_band)

    def _trailing_vol(self, returns: pd.DataFrame, window: int = 20) -> pd.DataFrame:
        return returns.rolling(window, min_periods=window // 2).std(ddof=1) * np.sqrt(
            TRADING_DAYS_PER_YEAR
        )

    def run(
        self,
        strategy,
        panel: dict[str, pd.DataFrame],
        *,
        sector_map: dict[str, str] | None = None,
    ) -> BacktestResult:
        """Run one explicit daily accounting basis; see docs/phase3a_market_mechanics.md."""
        # --- Build aligned price / return frames -------------------------- #
        close = pd.DataFrame(
            {s: df["adjusted_close" if self.price_mode == 'adjusted' else 'close']
             for s, df in panel.items()}
        ).sort_index()
        dates = close.index
        for symbol, df in panel.items():
            if df.index.has_duplicates or not df.index.is_monotonic_increasing:
                raise ValueError(f'{symbol}: daily bars must be unique and increasing')
        self.calendar.validate_index(dates)
        if self.corporate_actions is not None:
            self.corporate_actions.validate(panel,dates,self.calendar)
        if len(dates) < 60:
            raise ValueError("Not enough data to backtest (need >= 60 bars).")
        # Strategy/risk features retain their adjusted-price input even when the
        # execution ledger uses raw shares. They are never booked as raw P&L.
        asset_returns = pd.DataFrame({s:df['adjusted_close'] for s,df in panel.items()}).pct_change(fill_method=None)
        trailing_vol = self._trailing_vol(asset_returns)

        # --- Strategy precomputes a CAUSAL raw weight panel --------------- #
        raw_weights = strategy.target_weights(panel)
        raw_weights = raw_weights.reindex(index=dates).reindex(columns=close.columns)

        freq = getattr(strategy, "rebalance_frequency", "weekly")
        rb_set = set(rebalance_dates(dates, freq))
        sector_map = sector_map or getattr(strategy, "sector_map", None)
        # V2: market-neutral books (S03) get auto leverage-up toward the vol
        # target; directional books only if they opt in.
        market_neutral = bool(getattr(strategy, "market_neutral", False))
        allow_leverage_up = getattr(strategy, "allow_leverage_up", None)

        portfolio = Portfolio(initial_capital=self.initial_capital)
        broker = SimulatedBroker(panel, self.cost_model, self.execution, self.price_mode)

        equity_hist: list[float] = []
        ret_hist: list[float] = []
        weight_rows: dict[pd.Timestamp, pd.Series] = {}
        orders: list[Order] = []
        risk_events: list[dict] = []
        strat_equity_hist: list[float] = []
        cash_hist: list[float] = []
        quantity_rows: list[dict] = []
        mark_rows: list[dict] = []
        pnl_rows: list[dict] = []
        trading_rows: list[dict] = []
        borrow_rows: list[dict] = []
        ledger: list[dict] = []
        dividend_rows: list[dict] = []
        component_rows: list[dict] = []
        session_rows: list[dict] = []

        pending: dict | None = None
        borrow_paid = 0.0  # V2.1: cumulative $ borrow cost (for attribution)
        trading_paid = 0.0  # V2.1: cumulative $ trading cost

        for i, date in enumerate(dates):
            starting_equity = portfolio.equity
            carried_quantities = portfolio.quantities.copy()
            pnl: dict[str, float] = {}
            trading: dict[str, float] = {}
            borrowing: dict[str, float] = {}
            dividends: dict[str, float] = {}
            days = (date-dates[i-1]).days if i else 0
            short_collateral = sum(-q*portfolio.marks[s] for s,q in carried_quantities.items() if q < 0)
            interest, financing = self.cash_model.accrual(portfolio.cash,short_collateral,days)
            if interest:
                portfolio.cash_flow(interest)
                ledger.append(portfolio.snapshot(date,'cash_interest') | {'cash_flow':interest})
            if financing:
                portfolio.charge_cost(financing)
                ledger.append(portfolio.snapshot(date,'financing',cost=financing))
            # ACT/365 uses the preceding interval's actual positions and marks.
            # Covering today does not erase the overnight borrowing liability.
            if self.borrow_day_count == 'actual_365' and self.borrow_cost_bps_annual:
                for symbol, quantity in carried_quantities.items():
                    if quantity < 0:
                        amount = -quantity*portfolio.marks[symbol]*self.borrow_cost_bps_annual/1e4*days/365
                        portfolio.charge_cost(amount)
                        borrowing[symbol] = amount
                        ledger.append(portfolio.snapshot(date,'borrow',symbol=symbol,cost=amount))
            if self.corporate_actions is not None:
                for action in self.corporate_actions.on(date):
                    quantity = portfolio.quantities.get(action.symbol,0.0)
                    if action.kind == 'split':
                        portfolio.split(action.symbol,action.value)
                        ledger.append(portfolio.snapshot(date,'split',symbol=action.symbol)
                                      | {'ratio':action.value})
                    else:
                        amount = quantity*action.value
                        portfolio.cash_flow(amount)
                        self.cash_model.validate_cash(portfolio.cash)
                        dividends[action.symbol] = amount
                        ledger.append(portfolio.snapshot(date,action.kind,symbol=action.symbol)
                                      | {'cash_flow':amount,'per_share':action.value})
            # Legacy borrow uses post-split carried shares and today's close.
            carried_quantities = portfolio.quantities.copy()

            # Mark carried holdings at execution time, before converting any targets.
            if pending is not None and pending["exec_date"] == date:
                execution_marks = {s: broker.execution_price(s, date)
                                   for s in portfolio.quantities}
                pnl.update(portfolio.mark(execution_marks, date))
                ledger.append(portfolio.snapshot(date, "execution_mark"))
                eq_before = portfolio.equity
                batch = []
                for od in pending["orders"]:
                    current_quantity = portfolio.quantities.get(od.symbol, 0.0)
                    price = broker.execution_price(od.symbol, date)
                    if price is not None and eq_before > 0:
                        current_weight = current_quantity * price / eq_before
                        delta = od.target_weight - current_weight
                        # The no-trade band retains quantities, never target weights.
                        if (od.target_weight != 0 and (
                            abs(delta) < 1e-12 or (
                                self.rebalance_band > 0 and abs(delta) < self.rebalance_band
                            )
                        )):
                            continue
                    broker.fill(od, eq_before, current_quantity=current_quantity)
                    batch.append(od)
                cash_after_batch = portfolio.cash - sum(
                    od.executed_quantity*od.fill_price+od.cost
                    for od in batch if od.status == OrderStatus.FILLED)
                self.cash_model.validate_cash(cash_after_batch)
                # Common allocation equity is already fixed. Book cash-releasing
                # fills first so an unfinanced rotation never borrows transiently.
                batch.sort(key=lambda od: -(od.executed_quantity*od.fill_price+od.cost)
                           if od.status == OrderStatus.FILLED else 0.0, reverse=True)
                for od in batch:
                    if od.status == OrderStatus.FILLED:
                        portfolio.apply_fill(od)
                        trading[od.symbol] = trading.get(od.symbol, 0.0) + od.cost
                    ledger.append(portfolio.snapshot(
                        date, "fill" if od.status == OrderStatus.FILLED else "rejected",
                        symbol=od.symbol, quantity=od.executed_quantity, cost=od.cost))
                    orders.append(od)
                pending = None

            # Only the post-fill quantities earn the remaining move to the close.
            closing_marks = close.loc[date].to_dict()
            for symbol, amount in portfolio.mark(closing_marks, date).items():
                pnl[symbol] = pnl.get(symbol, 0.0) + amount
            ledger.append(portfolio.snapshot(date, "close_mark"))

            # Retain the existing carried-short, annual-bps/252 convention.
            # Value post-split carried quantities at today's selected closing
            # basis, including exit days; no entry-day/intraday borrow accrual.
            if self.borrow_cost_bps_annual and self.borrow_day_count == 'sessions_252':
                for symbol, quantity in carried_quantities.items():
                    if quantity < 0:
                        price = required_mark(closing_marks.get(symbol), symbol, date)
                        amount = -quantity * price * self.borrow_cost_bps_annual / 1e4 / TRADING_DAYS_PER_YEAR
                        portfolio.charge_cost(amount)
                        borrowing[symbol] = amount
                        ledger.append(portfolio.snapshot(date, "borrow", symbol=symbol, cost=amount))

            if not np.isfinite(portfolio.equity) or portfolio.equity <= 0:
                raise ValueError(f"Non-positive/non-finite portfolio equity on {date.date()}")
            self.cash_model.validate_cash(portfolio.cash)
            components = dict(market_pnl=sum(pnl.values()),
                dividends=sum(dividends.values()), cash_interest=interest,
                financing_cost=-financing, short_borrow_cost=-sum(borrowing.values()),
                transaction_cost=-sum(trading.values()))
            components['total_net_pnl'] = sum(components.values())
            if not np.isclose(components['total_net_pnl'],portfolio.equity-starting_equity,
                              rtol=1e-10,atol=max(1e-8,abs(starting_equity)*1e-12)):
                raise ValueError(f'P&L components do not reconcile on {date.date()}')
            component_rows.append(components)
            dividend_rows.append(dividends)
            session = self.calendar.session(date)
            session_rows.append(dict(signal_time=session.close,valuation_time=session.close,
                execution_time=session.open if self.execution == 'next_open' else session.close))
            day_ret = portfolio.equity / starting_equity - 1.0
            trading_paid += sum(trading.values())
            borrow_paid += sum(borrowing.values())
            equity_hist.append(portfolio.equity)
            ret_hist.append(day_ret)
            weight_rows[date] = portfolio.weights.reindex(close.columns).fillna(0.0)
            strat_equity_hist.append(portfolio.equity)
            cash_hist.append(portfolio.cash)
            quantity_rows.append(portfolio.quantities.copy())
            mark_rows.append({s: portfolio.marks[s] for s in portfolio.quantities})
            pnl_rows.append(pnl)
            trading_rows.append(trading)
            borrow_rows.append(borrowing)

            # 3. On a rebalance date, generate the next target (executes t+1).
            if date in rb_set and i < len(dates) - 1:
                tw_raw = raw_weights.loc[date]
                if tw_raw.isna().all():
                    continue
                tw_raw = tw_raw.fillna(0.0)

                if self.risk_manager is not None:
                    eq_series = pd.Series(equity_hist, index=dates[: i + 1])
                    strat_eq = pd.Series(strat_equity_hist, index=dates[: i + 1])
                    tw_adj, rstate = self.risk_manager.process(
                        tw_raw,
                        portfolio_equity=eq_series,
                        strategy_equity=strat_eq,
                        prev_day_return=day_ret,
                        asset_vols=trailing_vol.loc[date],
                        sector_map=sector_map,
                        market_neutral=market_neutral,
                        allow_leverage_up=allow_leverage_up,
                        strategy_max_weight=getattr(strategy, "max_weight", None),
                        long_only=bool(getattr(strategy, "long_only", False)),
                    )
                    if rstate.notes:
                        risk_events.append({"date": date, "notes": list(rstate.notes)})
                else:
                    tw_adj, rstate = tw_raw, RiskState()

                exec_date = self.calendar.next_session(date)
                if exec_date != dates[i+1]:
                    raise ValueError(f'missing next execution session after {date.date()}')
                prev_w = portfolio.weights
                new_orders: list[Order] = []
                all_syms = sorted(set(prev_w.index) | set(tw_adj.index))
                # Submit targets, including unchanged nonzero targets: overnight
                # drift may require a real trade to reach them at execution time.
                for sym in all_syms:
                    pw = float(prev_w.get(sym, 0.0))
                    tw = float(tw_adj.get(sym, 0.0))
                    if not np.isfinite(tw):
                        raise ValueError(f"Non-finite target for {sym} on {date.date()}")
                    if pw == 0 and tw == 0:
                        continue
                    new_orders.append(
                        Order(
                            symbol=sym,
                            signal_date=date,
                            execution_date=exec_date,
                            prev_weight=pw,
                            target_weight=tw,
                        )
                    )
                if new_orders:
                    pending = {
                        "exec_date": exec_date,
                        "orders": new_orders,
                    }

        equity_curve = pd.Series(equity_hist, index=dates, name="equity")
        returns = pd.Series(ret_hist, index=dates, name="returns")
        weights_df = pd.DataFrame(weight_rows).T.reindex(index=dates)
        weights_df.index.name = "date"
        components_df = pd.DataFrame(component_rows,index=dates)

        log.info(
            "Backtest done: %d bars, final equity %.2f, total cost %.2f",
            len(dates),
            portfolio.equity,
            portfolio.cumulative_cost,
        )
        return BacktestResult(
            equity_curve=equity_curve,
            returns=returns,
            weights=weights_df,
            orders=orders,
            risk_events=risk_events,
            total_cost=portfolio.cumulative_cost,
            initial_capital=self.initial_capital,
            trading_cost=trading_paid,
            borrow_cost=borrow_paid,
            cash=pd.Series(cash_hist, index=dates, name="cash"),
            quantities=pd.DataFrame(quantity_rows, index=dates).reindex(columns=close.columns).fillna(0.0),
            marks=pd.DataFrame(mark_rows, index=dates).reindex(columns=close.columns),
            gross_pnl=pd.DataFrame(pnl_rows, index=dates).reindex(columns=close.columns).fillna(0.0),
            trading_costs=pd.DataFrame(trading_rows, index=dates).reindex(columns=close.columns).fillna(0.0),
            borrow_costs=pd.DataFrame(borrow_rows, index=dates).reindex(columns=close.columns).fillna(0.0),
            ledger=ledger,
            dividends=pd.DataFrame(dividend_rows,index=dates).reindex(columns=close.columns).fillna(0.0),
            cash_interest=components_df.cash_interest,
            financing_costs=-components_df.financing_cost,
            financing_cost=float(-components_df.financing_cost.sum()),
            pnl_components=components_df,
            sessions=pd.DataFrame(session_rows,index=dates),
            config={
                "execution": self.execution,
                "rebalance": freq,
                "borrow_cost_bps_annual": self.borrow_cost_bps_annual,
                "price_basis": self.price_mode,
                "calendar": self.calendar.name,
                "corporate_action_convention": 'none (adjusted)' if self.price_mode == 'adjusted' else 'prior_close_ex_date_cash',
                "corporate_action_source": self.corporate_actions.source if self.corporate_actions else None,
                "corporate_actions": self.corporate_actions.metadata() if self.corporate_actions else None,
                "cash_interest_rate": self.cash_model.interest_rate,
                "financing_rate": self.cash_model.financing_rate,
                "cash_accrual": 'prior closing balances, ACT/365F; marked short collateral excluded from credit',
                "borrow_convention": self.borrow_day_count,
            },
        )
