"""BacktestEngine v1 - weight-based, no look-ahead.

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
from .broker import SimulatedBroker
from .order import Order, OrderStatus
from .position import Portfolio

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
    # total_cost == trading_cost + borrow_cost (kept for back-compat).
    trading_cost: float = 0.0
    borrow_cost: float = 0.0

    @property
    def turnover_series(self) -> pd.Series:
        """Per-rebalance one-way turnover (sum |Δw|)."""
        w = self.weights.fillna(0.0)
        return w.diff().abs().sum(axis=1)

    @property
    def annual_turnover(self) -> float:
        years = max(len(self.equity_curve) / TRADING_DAYS_PER_YEAR, 1e-9)
        return float(self.turnover_series.sum() / years)

    def turnover_attribution(self) -> dict:
        """Decompose one-way turnover into entries / exits / resizing.

        entry  : a name moving from flat into a position (|prev|~0 -> |new|>0)
        exit   : a name moving from a position to flat
        resize : change between two non-flat states (incl. pair rotation / sign
                 flips for the dollar-neutral book)
        Values are summed |Δw| and also annualised.
        """
        w = self.weights.fillna(0.0)
        prev = w.shift().fillna(0.0)  # day 0 prev = flat (avoids NaN poisoning)
        eps = 1e-9
        d = (w - prev).abs()
        was_flat = prev.abs() <= eps
        now_flat = w.abs() <= eps
        entry = d.where(was_flat & ~now_flat, 0.0).to_numpy().sum()
        exit_ = d.where(~was_flat & now_flat, 0.0).to_numpy().sum()
        resize = d.where(~was_flat & ~now_flat, 0.0).to_numpy().sum()
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
            if o.status.name == "FILLED" and o.delta_weight >= 0
        )
        sell = sum(
            o.cost for o in self.orders
            if o.status.name == "FILLED" and o.delta_weight < 0
        )
        return {
            "trading_cost": float(self.trading_cost),
            "borrow_cost": float(self.borrow_cost),
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
    ):
        self.cost_model = cost_model or EquityCostModel()
        self.risk_manager = risk_manager
        self.execution = execution
        self.initial_capital = initial_capital
        self.borrow_cost_bps_annual = borrow_cost_bps_annual
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
        # --- Build aligned price / return frames -------------------------- #
        close = pd.DataFrame(
            {s: df["adjusted_close"] for s, df in panel.items()}
        ).sort_index()
        dates = close.index
        if len(dates) < 60:
            raise ValueError("Not enough data to backtest (need >= 60 bars).")
        asset_returns = close.pct_change()  # pandas 3.0: no implicit ffill
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
        broker = SimulatedBroker(panel, self.cost_model, self.execution)

        equity_hist: list[float] = []
        ret_hist: list[float] = []
        weight_rows: dict[pd.Timestamp, pd.Series] = {}
        orders: list[Order] = []
        risk_events: list[dict] = []
        strat_equity_hist: list[float] = []

        pending: dict | None = None
        prev_day_ret = 0.0
        borrow_paid = 0.0  # V2.1: cumulative $ borrow cost (for attribution)
        trading_paid = 0.0  # V2.1: cumulative $ trading cost

        for i, date in enumerate(dates):
            # 1. Mark-to-market held weights with today's asset returns.
            day_ret = portfolio.apply_market_return(asset_returns.loc[date]) if i > 0 else 0.0

            # 1b. Daily borrow cost on short exposure (S03 short leg, etc.).
            if self.borrow_cost_bps_annual and not portfolio.weights.empty:
                short_gross = float(portfolio.weights.clip(upper=0.0).abs().sum())
                if short_gross > 0:
                    daily_borrow = (
                        short_gross * self.borrow_cost_bps_annual / 1e4
                    ) / TRADING_DAYS_PER_YEAR
                    borrow_paid += daily_borrow * portfolio.equity
                    portfolio.charge_cost(daily_borrow)

            # 2. Execute orders that were signalled on the previous rebalance.
            if pending is not None and pending["exec_date"] == date:
                eq_before = portfolio.equity
                filled_cost = 0.0
                for od in pending["orders"]:
                    broker.fill(od, eq_before)
                    if od.status == OrderStatus.FILLED:
                        filled_cost += od.cost
                    orders.append(od)
                trading_paid += filled_cost
                if eq_before > 0:
                    portfolio.charge_cost(filled_cost / eq_before)
                portfolio.set_weights(pending["weights"])
                pending = None

            equity_hist.append(portfolio.equity)
            ret_hist.append(day_ret)
            weight_rows[date] = portfolio.weights.reindex(close.columns).fillna(0.0)
            strat_equity_hist.append(portfolio.equity)

            # 3. On a rebalance date, generate the next target (executes t+1).
            if date in rb_set and i < len(dates) - 1:
                tw_raw = raw_weights.loc[date]
                if tw_raw.isna().all():
                    prev_day_ret = day_ret
                    continue
                tw_raw = tw_raw.fillna(0.0)

                if self.risk_manager is not None:
                    eq_series = pd.Series(equity_hist, index=dates[: i + 1])
                    strat_eq = pd.Series(strat_equity_hist, index=dates[: i + 1])
                    tw_adj, rstate = self.risk_manager.process(
                        tw_raw,
                        portfolio_equity=eq_series,
                        strategy_equity=strat_eq,
                        prev_day_return=prev_day_ret,
                        asset_vols=trailing_vol.loc[date],
                        sector_map=sector_map,
                        market_neutral=market_neutral,
                        allow_leverage_up=allow_leverage_up,
                    )
                    if rstate.notes:
                        risk_events.append({"date": date, "notes": list(rstate.notes)})
                else:
                    tw_adj, rstate = tw_raw, RiskState()

                exec_date = dates[i + 1]
                prev_w = portfolio.weights
                new_orders: list[Order] = []
                all_syms = sorted(set(prev_w.index) | set(tw_adj.index))
                # Build the EFFECTIVE target: names whose change is inside the
                # no-trade band keep their previous weight (no order, no cost),
                # so weights / turnover / cost stay mutually consistent. A move
                # to flat (tw == 0) is always executed so positions can close.
                effective_w = pd.Series(0.0, index=close.columns)
                for sym in all_syms:
                    pw = float(prev_w.get(sym, 0.0))
                    tw = float(tw_adj.get(sym, 0.0))
                    delta = tw - pw
                    skip_small = (
                        self.rebalance_band > 0.0
                        and abs(delta) < self.rebalance_band
                        and tw != 0.0
                    )
                    if abs(delta) < 1e-9 or skip_small:
                        if sym in effective_w.index:
                            effective_w[sym] = pw  # hold prior weight
                        continue
                    if sym in effective_w.index:
                        effective_w[sym] = tw
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
                        "weights": effective_w.reindex(close.columns).fillna(0.0),
                        "orders": new_orders,
                    }

            prev_day_ret = day_ret

        equity_curve = pd.Series(equity_hist, index=dates, name="equity")
        returns = pd.Series(ret_hist, index=dates, name="returns")
        weights_df = pd.DataFrame(weight_rows).T.reindex(index=dates)
        weights_df.index.name = "date"

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
            config={
                "execution": self.execution,
                "rebalance": freq,
                "borrow_cost_bps_annual": self.borrow_cost_bps_annual,
            },
        )
