"""Explicit, dated BSM analytics; provider fields are never overwritten.

Date-only ACT/365 is deliberately not an intraday maturity/settlement clock.
American contracts are labelled European approximations, including inverted IV.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass
from datetime import date, datetime
import math
import pandas as pd
from .greeks import bs_greeks
from .pricing import bs_price, solve_iv

GREEKS = ('delta', 'gamma', 'theta', 'vega', 'rho')


def nullable(value):
    """Represent absent/nonfinite analytics as null, never a meaningful zero."""
    return float(value) if value is not None and pd.notna(value) and math.isfinite(value) else None


@dataclass(frozen=True)
class AnalyticsInputs:
    """Annual continuously compounded fractions with explicit provenance.

    Missing r/q disables local calculations. Supply zero explicitly if that is
    the intended model assumption; no historical rate or yield is inferred.
    """
    valuation_date: date
    risk_free_rate: float | None
    dividend_yield: float | None
    rate_source: str
    dividend_source: str
    valuation_timestamp: datetime | None = None

    def __post_init__(self):
        if not isinstance(self.valuation_date, date) or isinstance(self.valuation_date, datetime):
            raise ValueError('valuation_date must be an explicit date')
        for value, source in ((self.risk_free_rate,self.rate_source),
                              (self.dividend_yield,self.dividend_source)):
            if value is not None and (not math.isfinite(value) or not source.strip()):
                raise ValueError('finite rate/yield and its source are required')
        t = self.valuation_timestamp
        if t is not None and (t.tzinfo is None or t.utcoffset() is None or t.date()!=self.valuation_date):
            raise ValueError('valuation timestamp must be timezone-aware and match its date')


@dataclass(frozen=True)
class ContractMetadata:
    """Contract terms must be supplied, not inferred from a ticker or multiplier."""
    underlying: str
    expiration: date
    strike: float
    right: str
    exercise_style: str | None
    settlement_type: str | None
    multiplier: int | None
    terms_source: str

    def __post_init__(self):
        if not self.underlying or not math.isfinite(self.strike) or self.strike <= 0:
            raise ValueError('invalid contract identity')
        if not isinstance(self.expiration,date) or isinstance(self.expiration,datetime):
            raise ValueError('expiration must be a date')
        if self.right not in ('call','put') or self.exercise_style not in ('american','european',None):
            raise ValueError('invalid right or exercise style')
        if self.settlement_type not in ('physical','cash',None):
            raise ValueError('invalid settlement type')
        if self.multiplier is not None and (not isinstance(self.multiplier,int) or self.multiplier<=0):
            raise ValueError('multiplier must be positive integer or unknown')
        if not self.terms_source.strip():
            raise ValueError('contract terms source required')


def analyze_observation(row: dict, inputs: AnalyticsInputs, contract: ContractMetadata,
                        *, quantity: float = 1.) -> dict:
    """Separate vendor values, quote-mid IV and model Greeks, with full assumptions.

    Midpoint is a descriptive valuation input, never an executable fill. Greek
    comparison at provider IV separates volatility inversion from model inputs.
    Original invalid provider numbers remain in the source, flagged here.
    """
    day = pd.Timestamp(row['observation_date']).date()
    if day != inputs.valuation_date:
        raise ValueError('observation/valuation date mismatch')
    if (row['underlying']!=contract.underlying or
            pd.Timestamp(row['expiration']).date()!=contract.expiration or
            float(row['strike'])!=contract.strike or row['right']!=contract.right):
        raise ValueError('contract identity mismatch')
    for term in ('exercise_style','settlement_type','multiplier'):
        value=row.get(term)
        if value is not None and pd.notna(value) and value!=getattr(contract,term):
            raise ValueError('contract terms mismatch: '+term)
    if not math.isfinite(quantity):
        raise ValueError('quantity must be finite')
    c=asdict(contract);c['expiration']=contract.expiration.isoformat()
    assumptions=asdict(inputs)
    assumptions['valuation_date']=day.isoformat()
    assumptions['valuation_timestamp']=(inputs.valuation_timestamp.isoformat()
                                         if inputs.valuation_timestamp else None)
    model_status={'american':'european_approximation_for_american',
                  'european':'european_bsm',None:'european_assumption_unknown_exercise'}[contract.exercise_style]
    blank=dict.fromkeys(GREEKS)
    result=dict(contract=c,inputs=assumptions,quantity=quantity,model_status=model_status,
        analytics_source='local_bsm_model_derived',time_basis='date_only_ACT_365',
        dividend_model='continuous_yield_no_discrete_dividends',
        settlement_model='none_analytics_only',
        provider_iv=nullable(row.get('implied_volatility')),
        provider_greeks={g:nullable(row.get(g)) for g in GREEKS},
        provider_units_status='unverified_source_convention',
        open_interest=nullable(row.get('open_interest')),
        local_iv=None,local_price=None,local_greeks=blank.copy(),
        position_greeks=blank.copy(),local_position_value=None,
        local_greeks_at_provider_iv=blank.copy(),price_at_provider_iv=None,
        repricing_residual=None,status='pending',
        invalid_provider_fields=[k for k in ('implied_volatility',*GREEKS)
            if row.get(k) is not None and pd.notna(row.get(k)) and nullable(row.get(k)) is None])
    r,q=inputs.risk_free_rate,inputs.dividend_yield
    if r is None or q is None:
        return result | {'status':'missing_rate_or_dividend_input'}
    T=(contract.expiration-day).days/365
    if T <= 0:
        return result | {'status':'expired_or_date_only_expiration_unidentifiable'}
    spot=nullable(row.get('underlying_price'))
    if spot is None or spot <= 0:
        return result | {'status':'missing_or_invalid_spot'}
    args=(spot,contract.strike,T,r)
    iv=result['provider_iv']
    if iv is not None and iv>0:
        result['price_at_provider_iv']=bs_price(*args,iv,contract.right,q)
        result['local_greeks_at_provider_iv']={k:nullable(v) for k,v in
            bs_greeks(*args,iv,contract.right,q).items()}
    bid,ask=nullable(row.get('bid')),nullable(row.get('ask'))
    if bid is None or ask is None or bid<0 or ask<bid:
        return result | {'status':'invalid_quote'}
    mid=(bid+ask)/2
    solved=solve_iv(mid,*args,contract.right,q)
    result['iv_solver']={'lower':solved.lower,'upper':solved.upper,'status':solved.status,
                         'iterations':solved.iterations,'price_tolerance':1e-8}
    if solved.status!='ok':
        return result | {'status':solved.status}
    iv=solved.volatility
    g={k:nullable(v) for k,v in bs_greeks(*args,iv,contract.right,q).items()}
    price=bs_price(*args,iv,contract.right,q)
    scale=None if contract.multiplier is None else contract.multiplier*quantity
    result.update(local_iv=iv,local_price=price,local_greeks=g,
        position_greeks={k:None if scale is None or v is None else scale*v for k,v in g.items()},
        local_position_value=None if scale is None else scale*price,
        repricing_residual=price-mid,status='ok')
    return result
