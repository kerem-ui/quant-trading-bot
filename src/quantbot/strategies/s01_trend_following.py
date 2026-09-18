"""S01 - Multi-Asset Volatility-Targeted Trend Following.

LONG-ONLY in this v1 (per project constraint), weekly rebalance, ETF universe.

Per-symbol state machine (all causal):
  Entry  : trend_score >= entry_threshold
  Exit   : trend_score <  exit_threshold (hysteresis), OR
           close below EMA50 for 3 consecutive sessions, OR
           trailing stop: close < highest_close_since_entry - atr_mult * ATR14
Sizing   : inverse-volatility, w_i = target_vol / realized_vol_i, capped at
           max_weight_per_symbol. Portfolio vol targeting and exposure caps are
           applied centrally by the RiskManager in the engine.

A cost filter suppresses entries whose expected edge does not clear
``cost_filter_multiplier * round_trip_cost``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..costs.transaction_costs import EquityCostModel
from ..indicators.trend import (
    compute_trend_score,
    consecutive_below_ema,
)
from ..indicators.volatility import atr, adjusted_ohlc, daily_returns, realized_vol
from .base import Strategy


def generate_trend_signals(
    trend_score: pd.Series,
    entry_threshold: float = 1.0,
    exit_threshold: float = 0.25,
) -> pd.Series:
    """Long-only 0/1 path with hysteresis (enter >= entry, exit < exit)."""
    pos = np.zeros(len(trend_score), dtype=int)
    holding = False
    vals = trend_score.to_numpy()
    for i, sc in enumerate(vals):
        if np.isnan(sc):
            pos[i] = 1 if holding else 0
            continue
        if not holding and sc >= entry_threshold:
            holding = True
        elif holding and sc < exit_threshold:
            holding = False
        pos[i] = 1 if holding else 0
    return pd.Series(pos, index=trend_score.index)


def size_by_volatility(
    signals: pd.Series,
    vol: pd.Series,
    target_vol: float = 0.10,
    max_weight: float = 0.15,
) -> pd.Series:
    """Inverse-vol position sizing with a per-symbol cap. Long-only."""
    w = pd.Series(0.0, index=signals.index)
    active = signals > 0
    v = vol.where(vol > 1e-6)
    w[active] = (target_vol / v[active]).clip(upper=max_weight)
    return w.fillna(0.0)


def size_by_conviction(
    conviction: pd.Series,
    vol: pd.Series,
    target_vol: float = 0.10,
    max_weight: float = 0.15,
) -> pd.Series:
    """Continuous-conviction sizing: ``w = conviction * inverse-vol``, capped.

    ``conviction`` in [0, 1] scales the same inverse-vol target used by the
    binary path, so the two modes are directly comparable. Long-only.
    """
    v = vol.where(vol > 1e-6)
    base = (target_vol / v).clip(upper=max_weight)
    return (conviction.clip(lower=0.0, upper=1.0) * base).fillna(0.0)


class S01TrendFollowing(Strategy):
    name = "S01_trend_following"
    daily_exits = True

    def __init__(self, config: dict | None = None, sector_map: dict | None = None,
                 cost_model: EquityCostModel | None = None):
        super().__init__(config, sector_map)
        c = config or {}
        self.rebalance_frequency = c.get("rebalance_frequency", "weekly")
        self.lookbacks = tuple(c.get("lookbacks", (20, 60, 120)))
        self.entry_threshold = float(c.get("trend_entry_threshold", 1.0))
        self.exit_threshold = float(c.get("trend_exit_threshold", 0.25))
        self.vol_window = int(c.get("vol_window", 20))
        self.atr_window = int(c.get("atr_window", 14))
        self.atr_mult = float(c.get("trailing_stop_atr_multiple", 3.0))
        self.target_vol = float(c.get("target_vol_annual", 0.10))
        self.max_weight = float(c.get("max_weight_per_symbol", 0.15))
        self.cost_filter_multiplier = float(c.get("cost_filter_multiplier", 3.0))
        # V2: minimum holding period damps trend whipsaw (the dominant residual
        # turnover source - full cap-in/cap-out round trips). Soft exits (weak
        # trend / below-EMA) are deferred until this many sessions have passed;
        # the hard ATR trailing stop is NEVER deferred (risk guardrail intact).
        self.min_holding_days = int(c.get("min_holding_days", 0))
        self.long_only = True  # enforced per project constraint
        self.cost_model = cost_model or EquityCostModel()
        # V2.3 OPT-IN execution experiment. Default "binary" => the existing
        # code path runs unchanged (bit-identical). "conviction" only:
        #   - uses slower lookbacks (drop the noisy 20d term),
        #   - requires the score >= entry for confirm_days consecutive sessions
        #     before entering (slower confirmation -> fewer weak entries),
        #   - emits a continuous conviction weight in [0,1] instead of 0/1
        #     (fewer binary flips). ATR hard stop + min-hold are preserved.
        self.execution_mode = str(c.get("s01_execution_mode", "binary"))
        self.confirm_days = int(c.get("s01_confirm_days", 1))
        self.conviction_lookbacks = tuple(c.get("s01_conviction_lookbacks", (60, 120)))

    def execution_exit(self, symbol, date, df, entry_index, current_index):
        """Daily exit guard on actual holdings, with a fill-based minimum hold.

        Hard ATR stops use the peak since the executed entry. Soft exits keep
        the existing trend/EMA thresholds and wait the configured sessions.
        """
        inputs = self._execution_exit_inputs[symbol]
        close = df.at[date,'adjusted_close']
        held_sessions = current_index-entry_index+1
        peak = df.loc[:date,'adjusted_close'].iloc[-held_sessions:].max()
        a = inputs['atr'].loc[date]
        hard = np.isfinite(a) and close < peak-self.atr_mult*a
        soft = inputs['soft'].loc[date]
        return bool(hard or (soft and current_index-entry_index >= self.min_holding_days))

    # --- per-symbol causal position path -----------------------------------
    def _position_path(self, df: pd.DataFrame) -> pd.Series:
        score = compute_trend_score(df, self.lookbacks)
        base = generate_trend_signals(score, self.entry_threshold, self.exit_threshold)
        below3 = consecutive_below_ema(df, 50) >= 3
        atr14 = atr(adjusted_ohlc(df), self.atr_window)
        close = df["adjusted_close"]

        # V2: the cost filter gates ENTRIES only. A held position is no longer
        # dropped just because the recent move shrank - that on/off toggling
        # was a major turnover/cost source in V1. Causal proxy: trailing 20d
        # absolute move (bps) must clear cost_filter_multiplier x round-trip.
        rt_bps = self.cost_model.round_trip_bps()
        edge_bps = close.pct_change(20).abs() * 1e4
        edge_ok = (
            edge_bps > self.cost_filter_multiplier * rt_bps
        ).fillna(False).to_numpy()

        pos = np.zeros(len(df), dtype=int)
        holding = False
        peak = -np.inf
        held_days = 0
        b = base.to_numpy()
        c = close.to_numpy()
        a = atr14.to_numpy()
        bel = below3.to_numpy()
        for i in range(len(df)):
            if holding:
                held_days += 1
                peak = max(peak, c[i])
                stop_hit = (
                    not np.isnan(a[i]) and c[i] < peak - self.atr_mult * a[i]
                )
                soft_exit = (b[i] == 0) or bel[i]
                # Hard ATR stop always fires; soft exits wait out min-hold.
                if stop_hit or (soft_exit and held_days >= self.min_holding_days):
                    holding = False
                    peak = -np.inf
                    held_days = 0
            else:
                if b[i] == 1 and edge_ok[i]:
                    holding = True
                    peak = c[i]
                    held_days = 0
            pos[i] = 1 if holding else 0
        return pd.Series(pos, index=df.index)

    # --- OPT-IN conviction path (only used when execution_mode=="conviction")
    def _conviction_path(self, df: pd.DataFrame) -> pd.Series:
        """Causal continuous conviction in [0,1] with slower confirmation.

        Same exit/stop logic as the binary path (ATR hard stop + min-hold
        preserved); differs only in: slower lookbacks, a confirm_days entry
        delay, and a continuous output instead of 0/1.
        """
        # Equal weights matched to the (slower) conviction lookbacks so
        # compute_trend_score's lookback/weight lengths agree.
        lbs = tuple(self.conviction_lookbacks)
        eq_w = tuple([1.0 / len(lbs)] * len(lbs))
        score = compute_trend_score(df, lbs, weights=eq_w)
        base = generate_trend_signals(score, self.entry_threshold, self.exit_threshold)
        below3 = consecutive_below_ema(df, 50) >= 3
        atr14 = atr(adjusted_ohlc(df), self.atr_window)
        close = df["adjusted_close"]

        rt_bps = self.cost_model.round_trip_bps()
        edge_bps = close.pct_change(20).abs() * 1e4
        edge_ok = (
            edge_bps > self.cost_filter_multiplier * rt_bps
        ).fillna(False).to_numpy()

        sc = score.to_numpy()
        b = base.to_numpy()
        c = close.to_numpy()
        a = atr14.to_numpy()
        bel = below3.to_numpy()
        denom = max(self.entry_threshold - self.exit_threshold, 1e-9)

        conv = np.zeros(len(df), dtype=float)
        holding = False
        peak = -np.inf
        held_days = 0
        confirm = 0
        for i in range(len(df)):
            if holding:
                held_days += 1
                peak = max(peak, c[i])
                stop_hit = not np.isnan(a[i]) and c[i] < peak - self.atr_mult * a[i]
                soft_exit = (b[i] == 0) or bel[i]
                if stop_hit or (soft_exit and held_days >= self.min_holding_days):
                    holding = False
                    peak = -np.inf
                    held_days = 0
                    confirm = 0
            else:
                # slower confirmation: score must hold above entry for
                # confirm_days consecutive sessions before we turn on.
                if not np.isnan(sc[i]) and sc[i] >= self.entry_threshold:
                    confirm += 1
                else:
                    confirm = 0
                if confirm >= self.confirm_days and b[i] == 1 and edge_ok[i]:
                    holding = True
                    peak = c[i]
                    held_days = 0
            if holding and not np.isnan(sc[i]):
                conv[i] = float(np.clip((sc[i] - self.exit_threshold) / denom, 0.0, 1.0))
            else:
                conv[i] = 0.0
        return pd.Series(conv, index=df.index)

    def generate_signals(self, panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
        panel = self.prepare_data(panel)
        path = (
            self._conviction_path
            if self.execution_mode == "conviction"
            else self._position_path
        )
        sig = {s: path(df) for s, df in panel.items()}
        self._execution_exit_inputs = {}
        for symbol, df in panel.items():
            lbs = self.conviction_lookbacks if self.execution_mode == 'conviction' else self.lookbacks
            kwargs = {'weights':tuple([1/len(lbs)]*len(lbs))} if self.execution_mode == 'conviction' else {}
            base = generate_trend_signals(compute_trend_score(df,lbs,**kwargs),self.entry_threshold,self.exit_threshold)
            self._execution_exit_inputs[symbol] = dict(soft=(base==0)|(consecutive_below_ema(df,50)>=3),
                                                       atr=atr(adjusted_ohlc(df),self.atr_window))
        self._signals = pd.DataFrame(sig).sort_index()
        return self._signals

    def target_weights(self, panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
        # The cost filter is applied at entry inside the position path, so a
        # held name keeps a stable weight instead of flickering to 0 and back.
        signals = self.generate_signals(panel)
        conviction_mode = self.execution_mode == "conviction"
        weights = {}
        for s, df in panel.items():
            sig = signals[s]
            rv = realized_vol(daily_returns(df), self.vol_window)
            if conviction_mode:
                weights[s] = size_by_conviction(
                    sig, rv, self.target_vol, self.max_weight
                )
            else:
                weights[s] = size_by_volatility(
                    sig, rv, self.target_vol, self.max_weight
                )
        wdf = pd.DataFrame(weights).sort_index()
        return wdf.clip(lower=0.0)  # long-only hard guard
