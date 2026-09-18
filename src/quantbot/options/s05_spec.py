"""Immutable parameters for the explicitly approved S05 research specification."""
from dataclasses import dataclass, fields
import math


@dataclass(frozen=True)
class S05Parameters:
    """Annualized volatility is decimal; money is USD; DTE is calendar days."""
    rv_lambda: float = .94
    rv_annualization: int = 252
    rv_warmup: int = 20
    iv_target_dte: int = 30
    iv_max_dte: int = 45
    percentile_window: int = 252
    percentile_min_valid: int = 126
    percentile_threshold: float = .70
    vrp_threshold: float = .05
    dte_min: int = 30
    dte_max: int = 45
    short_delta: float = .20
    short_delta_min: float = .15
    short_delta_max: float = .25
    max_width: float = 10.
    contracts_per_leg: int = 1
    max_positions: int = 1
    spread_max_pct: float = .20
    profit_debit_fraction: float = .50
    stop_debit_multiple: float = 2.
    exit_dte: int = 21
    per_trade_risk_fraction: float = .01
    aggregate_risk_fraction: float = .05
    max_loss_dollars: float = 1000.
    max_credit_dollars: float = 500.
    initial_capital: float = 100000.
    per_contract_fee: float = .65
    multi_leg_penalty: float = 1.

    def __post_init__(self):
        for f in fields(self):
            v=getattr(self,f.name)
            if not isinstance(v,(int,float)) or not math.isfinite(v) or v<0:
                raise ValueError(f'invalid S05 parameter: {f.name}')
        if not (0<self.rv_lambda<1 and 2<=self.percentile_min_valid<=self.percentile_window
                and self.contracts_per_leg==self.max_positions==1
                and 0<self.short_delta_min<=self.short_delta<=self.short_delta_max<.5
                and self.dte_max>=self.dte_min>self.exit_dte):
            raise ValueError('inconsistent S05 specification')