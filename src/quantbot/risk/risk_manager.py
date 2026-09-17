"""Central RiskManager.

Every strategy's target weights pass through ``RiskManager.process`` before the
backtest engine turns them into orders. The pipeline (in order):

  1. Kill switch  - portfolio drawdown beyond limit -> flatten everything.
  2. Strategy pause - strategy drawdown beyond limit -> flatten this strategy.
  3. Daily-loss de-risk - large prior-day loss -> scale exposure down.
  4. Volatility targeting - scale gross so ex-ante vol ~ target. This is
     TWO-SIDED: a low-vol book may be scaled *up* toward the target, but only
     when leverage-up is explicitly enabled (directional books opt in via
     ``allow_leverage_up``; market-neutral books get it automatically). Any
     scale-up is still hard-bounded by ``max_vol_scale`` and the gross cap.
  5. Per-symbol caps - clip any name to the max single-symbol weight.
  6. Sector / asset-class caps - scale offending sectors down.
  7. Gross / net exposure caps - shrink only, without creating positions.
  8. Restore requested neutrality by reducing the overweight side; validate
     ALL caps, strategy per-name limits, long-only and neutrality together.

Conservative by construction: scale-up is opt-in and bounded; the gross/net
caps in step 7 always have the final say, so realised leverage can never
exceed ``max_gross_exposure``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..utils.math import TRADING_DAYS_PER_YEAR
from .drawdown import current_drawdown


def reduce_net_exposure(weights: pd.Series, limit: float) -> pd.Series:
    """Reduce only the overweight side; never grow, reverse, or create a position."""
    w = weights.copy()
    net = float(w.sum())
    if abs(net) > limit:
        side = w > 0 if net > 0 else w < 0
        gross_side = float(w[side].abs().sum())
        w.loc[side] *= max(0.0, 1.0 - (abs(net) - limit) / gross_side)
    return w


@dataclass
class RiskState:
    """Outcome of one risk evaluation, recorded by the engine for reporting."""

    kill_switch: bool = False
    strategy_paused: bool = False
    derisk_factor: float = 1.0
    vol_scale: float = 1.0
    gross_exposure: float = 0.0
    net_exposure: float = 0.0
    notes: list[str] = field(default_factory=list)


class RiskManager:
    def __init__(self, risk_config: dict):
        from ..config import RISK_FIELDS
        unknown = set(risk_config) - RISK_FIELDS - {"_comment"}
        if unknown:
            raise ValueError(f"unknown risk configuration fields: {sorted(unknown)}")
        if not isinstance(risk_config.get("allow_leverage_up", False), bool):
            raise ValueError("allow_leverage_up must be boolean")
        c = risk_config
        self.target_vol = float(c.get("portfolio_vol_target_annual", 0.10))
        self.max_gross = float(c.get("max_gross_exposure", 1.50))
        self.max_net = float(c.get("max_net_exposure", 1.00))
        self.max_single = float(c.get("max_single_symbol_weight", 0.15))
        self.max_sector = float(c.get("max_asset_class_weight", 0.40))
        self.max_daily_loss = float(c.get("max_daily_loss_reduce_risk", 0.02))
        self.derisk_factor = float(c.get("risk_reduction_factor_on_daily_loss", 0.5))
        self.dd_kill = float(c.get("max_portfolio_drawdown_kill_switch", 0.20))
        self.dd_pause = float(c.get("max_strategy_drawdown_pause", 0.12))
        self.vol_spike_kill = float(c.get("vol_spike_kill_multiple", 2.5))
        # V2: two-sided vol targeting. Directional books only scale up if this
        # is opted-in; scale-up is always bounded by max_vol_scale AND the
        # gross cap (step 7), so leverage stays <= max_gross_exposure.
        self.allow_leverage_up = bool(c.get("allow_leverage_up", False))
        self.max_vol_scale = float(c.get("max_vol_scale", 4.0))
        for name in ("target_vol", "max_gross", "max_net", "max_single", "max_sector",
                     "max_daily_loss", "dd_kill", "dd_pause", "vol_spike_kill", "max_vol_scale"):
            value = getattr(self, name)
            if not np.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and nonnegative")
        if not np.isfinite(self.derisk_factor) or not 0 <= self.derisk_factor <= 1:
            raise ValueError("risk_reduction_factor_on_daily_loss must be in [0, 1]")

    # --- individual controls ------------------------------------------------
    def volatility_target_scale(
        self,
        weights: pd.Series,
        cov: pd.DataFrame | None,
        asset_vols: pd.Series | None,
        *,
        allow_leverage_up: bool | None = None,
        market_neutral: bool = False,
    ) -> float:
        """Two-sided scale factor so ex-ante annualized portfolio vol ~ target.

        Estimation of book vol:
          - covariance matrix when available (correct for hedged books);
          - else, for a *market-neutral* book, the additive proxy
            ``sum(|w_i|*vol_i)`` would massively overstate risk (it ignores the
            hedge), so we do NOT scale down on it - sizing of neutral books is
            governed by the strategy's target gross + the gross cap;
          - else (directional book) the conservative fully-correlated proxy
            ``sum(|w_i|*vol_i)``.

        Direction of scaling:
          - scale *down* always allowed (de-risk);
          - scale *up* allowed only if ``allow_leverage_up`` (directional opt-in)
            or ``market_neutral`` (auto), and always capped by ``max_vol_scale``.
          The gross cap (step 7) is the final hard bound regardless.
        """
        if allow_leverage_up is None:
            allow_leverage_up = self.allow_leverage_up
        w = weights.reindex(weights.index).fillna(0.0)
        if (w.abs().sum() == 0) or self.target_vol <= 0:
            return 1.0
        if cov is not None and not cov.empty:
            aligned = cov.reindex(index=w.index, columns=w.index).fillna(0.0)
            var = float(w.values @ aligned.values @ w.values)
            port_vol = np.sqrt(max(var, 0.0)) * np.sqrt(TRADING_DAYS_PER_YEAR)
        elif market_neutral:
            # Additive proxy is invalid for a hedged book; let target-gross
            # sizing + the gross cap govern. No vol-based rescale here.
            return 1.0
        elif asset_vols is not None:
            port_vol = float((w.abs() * asset_vols.reindex(w.index).fillna(0.0)).sum())
        else:
            return 1.0
        if port_vol <= 1e-9:
            return 1.0
        raw_scale = self.target_vol / port_vol
        upper = self.max_vol_scale if (allow_leverage_up or market_neutral) else 1.0
        return float(np.clip(raw_scale, 0.0, upper))

    def apply_position_caps(self, weights: pd.Series) -> pd.Series:
        return weights.clip(lower=-self.max_single, upper=self.max_single)

    def apply_sector_caps(
        self, weights: pd.Series, sector_map: dict[str, str] | None
    ) -> pd.Series:
        w = weights.copy()
        sectors = self._sectors(w, sector_map)
        for sec in sectors.unique():
            members = sectors.index[sectors == sec]
            gross = w[members].abs().sum()
            if gross > self.max_sector and gross > 0:
                w[members] = w[members] * (self.max_sector / gross)
        return w

    def apply_exposure_caps(self, weights: pd.Series) -> pd.Series:
        w = weights.copy()
        gross = w.abs().sum()
        if gross > self.max_gross and gross > 0:
            w = w * (self.max_gross / gross)
        return reduce_net_exposure(w, self.max_net)

    @staticmethod
    def _sectors(weights: pd.Series, sector_map: dict | None) -> pd.Series:
        # Unknown classifications are one conservative group, not independent
        # invented sectors that can collectively evade the configured cap.
        return pd.Series({s: (sector_map or {}).get(s) or "__unmapped__"
                          for s in weights.index}, dtype=object)

    def validate_final(self, weights: pd.Series, *, sector_map: dict | None = None,
                       strategy_max_weight: float | None = None,
                       long_only: bool = False, market_neutral: bool = False) -> None:
        """Fail explicitly if any hard constraint is violated after all transforms."""
        cap = min(self.max_single, strategy_max_weight) if strategy_max_weight is not None else self.max_single
        tol = 1e-10
        sectors = self._sectors(weights, sector_map)
        if (not weights.index.is_unique or not np.isfinite(weights.to_numpy()).all()
                or (weights.abs() > cap + tol).any()
                or weights.abs().sum() > self.max_gross + tol
                or abs(weights.sum()) > (0.0 if market_neutral else self.max_net) + tol
                or (long_only and (weights < -tol).any())
                or (weights.abs().groupby(sectors).sum() > self.max_sector + tol).any()):
            raise ValueError("final portfolio violates a hard risk constraint")

    # --- orchestration ------------------------------------------------------
    def process(
        self,
        target_weights: pd.Series,
        *,
        portfolio_equity: pd.Series | None = None,
        strategy_equity: pd.Series | None = None,
        prev_day_return: float | None = None,
        cov: pd.DataFrame | None = None,
        asset_vols: pd.Series | None = None,
        sector_map: dict[str, str] | None = None,
        vol_spike_ratio: float | None = None,
        allow_leverage_up: bool | None = None,
        market_neutral: bool = False,
        strategy_max_weight: float | None = None,
        long_only: bool = False,
    ) -> tuple[pd.Series, RiskState]:
        state = RiskState()
        w = target_weights.copy().astype(float).fillna(0.0)
        if not w.index.is_unique or not np.isfinite(w.to_numpy()).all():
            raise ValueError("target weights must be finite with unique instruments")
        if strategy_max_weight is not None and (
                not np.isfinite(strategy_max_weight) or strategy_max_weight < 0):
            raise ValueError("strategy_max_weight must be finite and nonnegative")
        if long_only:
            w = w.clip(lower=0.0)

        # 1. Portfolio kill switch.
        if portfolio_equity is not None and len(portfolio_equity) > 1:
            if current_drawdown(portfolio_equity) <= -self.dd_kill:
                state.kill_switch = True
                state.notes.append(
                    f"KILL: portfolio drawdown <= -{self.dd_kill:.0%}; flattened"
                )
                return pd.Series(0.0, index=w.index), state

        # Vol-spike kill switch.
        if vol_spike_ratio is not None and vol_spike_ratio > self.vol_spike_kill:
            state.kill_switch = True
            state.notes.append(
                f"KILL: vol spike {vol_spike_ratio:.2f}x > {self.vol_spike_kill}x median"
            )
            return pd.Series(0.0, index=w.index), state

        # 2. Strategy pause.
        if strategy_equity is not None and len(strategy_equity) > 1:
            if current_drawdown(strategy_equity) <= -self.dd_pause:
                state.strategy_paused = True
                state.notes.append(
                    f"PAUSE: strategy drawdown <= -{self.dd_pause:.0%}; flattened"
                )
                return pd.Series(0.0, index=w.index), state

        # 3. Daily-loss de-risk.
        if prev_day_return is not None and prev_day_return <= -self.max_daily_loss:
            state.derisk_factor = self.derisk_factor
            w = w * self.derisk_factor
            state.notes.append(
                f"de-risk x{self.derisk_factor}: prior-day loss {prev_day_return:.2%}"
            )

        # 4. Volatility targeting (two-sided; scale-up opt-in & bounded).
        state.vol_scale = self.volatility_target_scale(
            w, cov, asset_vols,
            allow_leverage_up=allow_leverage_up,
            market_neutral=market_neutral,
        )
        if state.derisk_factor < 1:
            state.vol_scale = min(state.vol_scale, 1.0)
        w = w * state.vol_scale

        # 5-7. Caps.
        w = self.apply_position_caps(w)
        if strategy_max_weight is not None:
            w = w.clip(-strategy_max_weight, strategy_max_weight)
        if any((sector_map or {}).get(s) is None for s in w.index[w != 0]):
            state.notes.append("unmapped instruments share one conservative asset-class cap")
        w = self.apply_sector_caps(w, sector_map)
        w = self.apply_exposure_caps(w)
        if market_neutral:
            w = reduce_net_exposure(w, 0.0)
        self.validate_final(w, sector_map=sector_map, strategy_max_weight=strategy_max_weight,
                            long_only=long_only, market_neutral=market_neutral)

        state.gross_exposure = float(w.abs().sum())
        state.net_exposure = float(w.sum())
        return w, state
