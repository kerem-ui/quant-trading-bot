"""S02 - Cross-Sectional Factor Blend (price-only v1).

LONG-ONLY (per project constraint), monthly rebalance, ETF universe.

v1 is price-only because point-in-time fundamentals are not available - this is
a documented limitation. Factors: 12m-ex-1m momentum, 3m momentum, 1m
reversal, low volatility, liquidity. Each is converted to a cross-sectional
percentile rank per date (so it cannot leak the future), blended by the config
weights, then the top quantile is held equal-weight subject to a per-name cap.

A liquidity/price filter removes names below ``min_price`` or
``min_avg_dollar_volume`` before ranking.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..indicators.factors import build_price_only_factors, composite_score
from .base import Strategy


class S02FactorBlend(Strategy):
    name = "S02_factor_blend"
    long_only = True

    def __init__(self, config: dict | None = None, sector_map: dict | None = None):
        super().__init__(config, sector_map)
        c = config or {}
        self.rebalance_frequency = c.get("rebalance_frequency", "monthly")
        self.min_price = float(c.get("min_price", 5.0))
        self.min_adv = float(c.get("min_avg_dollar_volume", 10_000_000))
        self.top_q = float(c.get("top_quantile_long", 0.20))
        self.max_weight = float(c.get("max_weight_per_name_long_only", 0.04))
        self.factor_weights = c.get(
            "factor_weights_price_only",
            {
                "momentum_12m_ex_1m": 0.45,
                "momentum_3m": 0.20,
                "one_month_reversal": 0.20,
                "low_volatility": 0.10,
                "liquidity": 0.05,
            },
        )

    def generate_signals(self, panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
        panel = self.prepare_data(panel)
        prices = self._wide(panel, "adjusted_close")
        volume = self._wide(panel, "volume")
        factors = build_price_only_factors(prices, volume)

        # Causal liquidity / price eligibility mask.
        raw_close = self._wide(panel, 'close')
        adv = (raw_close * volume).rolling(21, min_periods=10).mean()
        eligible = (raw_close >= self.min_price) & (adv >= self.min_adv)
        # Liquidity is raw dollars traded, not adjusted units times raw shares.
        if 'liquidity' in factors:
            factors['liquidity'] = adv
        active_factors = {name:weight for name,weight in self.factor_weights.items() if weight != 0}
        for name in active_factors:
            eligible &= np.isfinite(factors[name])
        score = composite_score({name:frame.where(eligible) for name,frame in factors.items()},
                                active_factors)
        self._signals = score
        return score

    def target_weights(self, panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
        score = self.generate_signals(panel)
        weights = pd.DataFrame(0.0, index=score.index, columns=score.columns)
        for date, row in score.iterrows():
            valid = row.dropna()
            if len(valid) < 3:
                continue
            cutoff = valid.quantile(1.0 - self.top_q)
            longs = valid[valid >= cutoff].index
            if len(longs) == 0:
                continue
            w = min(self.max_weight, 1.0 / len(longs))
            weights.loc[date, longs] = w
        return weights.clip(lower=0.0)  # long-only hard guard
