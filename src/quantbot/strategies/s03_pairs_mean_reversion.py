"""S03 - Pairs / Statistical-Arbitrage Mean Reversion.

Hedge-ratio matched (quantities proportional to +1, -beta), weekly rebalance with
**monthly walk-forward pair reselection**. ETF universe only.

Anti-look-ahead:
  - Pair reselection at month start uses ``find_candidate_pairs`` on price
    history sliced to that date only.
  - Hedge ratio and spread z-score use trailing rolling windows.
  - The engine still executes every weight change on the next bar.

Borrow cost for the short leg is modelled by the engine
(``borrow_cost_bps_annual``); the S03 runner sets it.

Position state machine per pair (z = z-score of spread = A - hedge*B):
  enter SHORT spread when z >= +entry_z   (short A, long B)
  enter LONG  spread when z <= -entry_z   (long A, short B)
  exit when |z| <= exit_z
  stop when |z| >= stop_z, correlation breaks, or max holding days exceeded
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..indicators.pairs import (
    compute_spread,
    find_candidate_pairs,
    rolling_correlation,
    rolling_hedge_ratio,
    spread_zscore,
)
from ..utils.dates import month_starts
from .base import Strategy


def generate_pair_signals(
    z: pd.Series,
    entry_z: float = 2.0,
    exit_z: float = 0.5,
    stop_z: float = 3.5,
    max_holding_days: int = 20,
    corr: pd.Series | None = None,
    min_corr: float = 0.50,
) -> pd.Series:
    """Causal position path for one pair.

    +1 = long spread (long A / short B), -1 = short spread, 0 = flat.
    """
    pos = np.zeros(len(z), dtype=int)
    state = 0
    held = 0
    ready = True  # re-arm flag: must see |z| <= exit_z before a new entry
    zz = z.to_numpy()
    cc = corr.to_numpy() if corr is not None else None
    for i in range(len(z)):
        zi = zz[i]
        if np.isnan(zi):
            pos[i] = state
            continue
        if state != 0:
            held += 1
            corr_break = cc is not None and not np.isnan(cc[i]) and cc[i] < min_corr
            if abs(zi) <= exit_z or abs(zi) >= stop_z or held >= max_holding_days or corr_break:
                state = 0
                held = 0
                # Only re-arm immediately if the spread has actually reverted
                # into the exit band. A stop / max-holding exit while the
                # spread is still extreme must NOT re-enter on the same move.
                ready = abs(zi) <= exit_z
        else:
            if not ready and abs(zi) <= exit_z:
                ready = True
            if ready and zi >= entry_z:
                state = -1  # short spread
                held = 0
            elif ready and zi <= -entry_z:
                state = 1  # long spread
                held = 0
        pos[i] = state
    return pd.Series(pos, index=z.index)


def build_pair_orders(
    pair_signal: int, hedge_ratio: float, risk_per_pair: float,
    *, price_a: float = 1.0, price_b: float = 1.0,
) -> dict[str, float]:
    """Allocate gross weight 2*risk_per_pair to quantities k*(signal,-signal*beta).

    Prices must use the signal's adjusted units. Unit-price defaults are only
    for standalone algebra; the strategy and execution layer supply prices.
    Positive beta is required for this long/short ETF strategy. The allocation
    parameter retains its legacy gross budget, not a claimed stop-loss amount.
    """
    if not np.isfinite(hedge_ratio) or hedge_ratio <= 0:
        raise ValueError('S03 beta must be finite and positive')
    if pair_signal not in (-1,0,1):
        raise ValueError('pair signal must be -1, 0 or 1')
    if any(not np.isfinite(x) or x <= 0 for x in (price_a,price_b)):
        raise ValueError('pair prices must be finite and positive')
    if not np.isfinite(risk_per_pair) or risk_per_pair < 0:
        raise ValueError('pair allocation must be finite and nonnegative')
    if pair_signal == 0:
        return {"a": 0.0, "b": 0.0}
    k = 2*risk_per_pair / (price_a + hedge_ratio*price_b)
    return {"a": k*pair_signal*price_a, "b": -k*pair_signal*hedge_ratio*price_b}


class S03PairsMeanReversion(Strategy):
    name = "S03_pairs_mean_reversion"
    long_only = False
    # The hedged volatility hint is separate from exact net neutrality.
    # Common book scaling preserves each component pair's quantity ratio.
    market_neutral = False
    hedged = True
    preserve_ratios = True

    def __init__(self, config: dict | None = None, sector_map: dict | None = None):
        super().__init__(config, sector_map)
        c = config or {}
        self.rebalance_frequency = "weekly"  # per project constraint
        self.pair_selection_frequency = c.get("pair_selection_frequency", "monthly")
        self.correlation_window = int(c.get("correlation_window", 252))
        self.min_corr = float(c.get("min_rolling_correlation", 0.70))
        self.coint_p = float(c.get("cointegration_pvalue_threshold", 0.05))
        self.hedge_window = int(c.get("hedge_ratio_window", 252))
        self.z_window = int(c.get("zscore_window", 60))
        self.entry_z = float(c.get("entry_z", 2.0))
        self.exit_z = float(c.get("exit_z", 0.5))
        self.stop_z = float(c.get("stop_z", 3.5))
        self.max_holding_days = int(c.get("max_holding_days", 20))
        self.risk_per_pair = float(c.get("risk_per_pair", 0.005))
        self.max_active_pairs = int(c.get("max_active_pairs", 20))
        self.max_pairs_per_symbol = int(c.get("max_pairs_per_symbol", 3))
        # ``target_gross`` scales the whole hedge-matched book
        # book to a meaningful gross each rebalance; longs and shorts are scaled
        # by the SAME factor, preserving every pair's hedge ratio.
        self.target_gross = float(c.get("target_gross", 0.0))  # 0 -> off (V1)
        self.min_half_life = float(c.get("min_half_life", 3.0))
        self.max_half_life = float(c.get("max_half_life", 30.0))

    def _select_pairs(self, prices_to_date: pd.DataFrame) -> list[tuple[str, str]]:
        cands = find_candidate_pairs(
            prices_to_date,
            self.sector_map or {},
            min_correlation=self.min_corr,
            coint_pvalue_threshold=self.coint_p,
            correlation_window=self.correlation_window,
            half_life_window=self.hedge_window,
            min_half_life=self.min_half_life,
            max_half_life=self.max_half_life,
        )
        chosen: list[tuple[str, str]] = []
        per_symbol: dict[str, int] = {}
        for ps in cands:
            if len(chosen) >= self.max_active_pairs:
                break
            if per_symbol.get(ps.sym_a, 0) >= self.max_pairs_per_symbol:
                continue
            if per_symbol.get(ps.sym_b, 0) >= self.max_pairs_per_symbol:
                continue
            chosen.append((ps.sym_a, ps.sym_b))
            per_symbol[ps.sym_a] = per_symbol.get(ps.sym_a, 0) + 1
            per_symbol[ps.sym_b] = per_symbol.get(ps.sym_b, 0) + 1
        return chosen

    def generate_signals(self, panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
        # Signals are pair-level; expose per-symbol net signed signal for
        # explainability/tests.
        return self.target_weights(panel).apply(np.sign)

    def target_weights(self, panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
        panel = self.prepare_data(panel)
        prices = self._wide(panel, "adjusted_close")
        dates = prices.index
        symbols = list(prices.columns)
        weights = pd.DataFrame(0.0, index=dates, columns=symbols)
        self.pair_targets = {}

        reselect_dates = sorted(set(month_starts(dates)))
        active_pairs: list[tuple[str, str]] = []
        # Precompute per-pair series lazily as pairs become active.
        cache: dict[tuple[str, str], dict] = {}
        next_reselect_idx = 0

        # Walk-forward: only ever look at prices up to the current date.
        for i, date in enumerate(dates):
            self.pair_targets[date] = []
            if (
                next_reselect_idx < len(reselect_dates)
                and date >= reselect_dates[next_reselect_idx]
            ):
                hist = prices.loc[:date]
                if len(hist) >= self.correlation_window:
                    active_pairs = self._select_pairs(hist)
                next_reselect_idx += 1

            if not active_pairs:
                continue

            row = pd.Series(0.0, index=symbols)
            specs = []
            for (a, b) in active_pairs:
                key = (a, b)
                if key not in cache:
                    pa, pb = prices[a], prices[b]
                    hr = rolling_hedge_ratio(pa, pb, self.hedge_window)
                    spread = compute_spread(pa, pb, hr)
                    z = spread_zscore(spread, self.z_window)
                    corr = rolling_correlation(pa, pb, self.correlation_window)
                    sig = generate_pair_signals(
                        z,
                        self.entry_z,
                        self.exit_z,
                        self.stop_z,
                        self.max_holding_days,
                        corr,
                        0.50,
                    )
                    cache[key] = {"sig": sig, "hr": hr}
                sig_i = int(cache[key]["sig"].iloc[i])
                hr_i = cache[key]["hr"].iloc[i]
                if sig_i == 0:
                    continue
                legs = build_pair_orders(sig_i, float(hr_i), self.risk_per_pair,
                                         price_a=prices.at[date,a], price_b=prices.at[date,b])
                specs.append(dict(a=a,b=b,beta=float(hr_i),signal=sig_i,gross=2*self.risk_per_pair))
                row[a] += legs["a"]
                row[b] += legs["b"]
            # Scale the netted book uniformly; all component pair allocations
            # receive the same multiplier. Net exposure need not be zero.
            gross = float(row.abs().sum())
            if self.target_gross > 0.0 and gross > 1e-12:
                row = row * (self.target_gross / gross)
                for spec in specs:
                    spec['gross'] *= self.target_gross/gross
            self.pair_targets[date] = specs
            weights.loc[date] = row.values

        self._signals = weights.apply(np.sign)
        return weights
