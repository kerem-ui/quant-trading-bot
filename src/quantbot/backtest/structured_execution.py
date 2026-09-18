"""Daily atomic execution of price-spread pair targets; no broker integration."""
from __future__ import annotations
import pandas as pd
from .order import OrderStatus
from ..strategies.s03_pairs_mean_reversion import build_pair_orders


def reject_atomic(orders, reason):
    """Cancel all trial fills before they reach the cash/quantity ledger."""
    for order in orders:
        order.status = OrderStatus.REJECTED
        order.executed_quantity = order.notional = order.cost = 0.
        order.cost_components = {}
        order.fill_price = None
        order.execution_outcome = 'rejected_atomic'
        order.note = reason


def reprice_pairs(pending, broker, equity, risk_manager, sector_map, max_weight):
    """Rebuild pair weights at execution prices, preserving each frozen beta.

    Overlapping pairs net at instrument level, with one common book scale. This
    conservative policy preserves every component pair and avoids independent
    clipping. An unavailable leg rejects the complete batch, including exits.
    """
    date = pending['exec_date']
    orders = pending['orders']
    weights = pd.Series(0.,index=[o.symbol for o in orders])
    plans = []
    for spec in pending['pairs']:
        a,b = spec['a'],spec['b']
        pa,pb = broker.execution_price(a,date),broker.execution_price(b,date)
        if pa is None or pb is None:
            reject_atomic(orders,f'missing pair execution price: {a}/{b} {date.date()}')
            return []
        # Signal beta is in adjusted research units. Raw-share mode converts
        # these units explicitly before constructing raw ledger quantities.
        fa = broker.panel[a].at[date,'adjusted_close']/broker.panel[a].at[date,'close'] if broker.price_mode == 'raw' else 1.
        fb = broker.panel[b].at[date,'adjusted_close']/broker.panel[b].at[date,'close'] if broker.price_mode == 'raw' else 1.
        if pending.get('fixed_pairs'):
            leg = {'a':spec['quantity_a']*pa/equity,'b':spec['quantity_b']*pb/equity}
        else:
            leg = build_pair_orders(spec['signal'],spec['beta'],spec['gross']/2,
                                   price_a=pa*fa,price_b=pb*fb)
        weights[a] += leg['a']
        weights[b] += leg['b']
        plans.append(spec | {'quantity_a':leg['a']*equity/pa,'quantity_b':leg['b']*equity/pb,
                             'adjustment_a':fa,'adjustment_b':fb})
    approved = risk_manager.proportional_caps(weights,sector_map=sector_map,
                strategy_max_weight=max_weight) if risk_manager is not None else weights
    scale = float(approved.abs().sum()/weights.abs().sum()) if weights.abs().sum() else 0.
    for plan in plans:
        plan['quantity_a'] *= scale
        plan['quantity_b'] *= scale
        plan['execution_risk_scale'] = scale
    for order in orders:
        order.target_weight = float(approved[order.symbol])
    return plans
