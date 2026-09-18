"""Observed single-date chains and labelled short-tenor analytics, no surface fit."""
from __future__ import annotations
from datetime import date
import math
import numpy as np
import pandas as pd
from .features import delta_selection


def fixed_tenor(points: list[tuple[float,float]], target_dte: float) -> dict:
    """Interpolate ATM total variance only inside observed positive tenor coverage.

    This descriptive ATM approximation is not an arbitrage-free calibrated
    surface. Do not interpolate if total variance falls across the bracket.
    """
    if not math.isfinite(target_dte) or target_dte <= 0:
        raise ValueError('target DTE must be positive')
    points=sorted((float(t),float(v)) for t,v in points
                  if pd.notna(t) and pd.notna(v) and math.isfinite(t) and
                  math.isfinite(v) and t>0 and v>0)
    if len({t for t,_ in points})!=len(points):
        raise ValueError('duplicate tenor observations')
    out=dict(target_dte=target_dte,iv=None,status='insufficient_tenor_coverage',
             bracket_dtes=[],interpolated=False,extrapolated=False)
    for t,v in points:
        if t==target_dte:
            return out | dict(iv=v,status='observed',bracket_dtes=[t])
    for (t1,v1),(t2,v2) in zip(points,points[1:]):
        if t1<target_dte<t2:
            out['bracket_dtes']=[t1,t2]
            if v2*v2*t2 < v1*v1*t1-1e-12:
                return out | {'status':'decreasing_total_variance'}
            weight=(target_dte-t1)/(t2-t1)
            var=(1-weight)*v1*v1*t1+weight*v2*v2*t2
            return out | dict(iv=math.sqrt(var/target_dte),
                status='interpolated_total_variance',interpolated=True)
    return out


class AnalyticalChain:
    """One underlying/date, original observations kept separate from selections.

    Composite identity is preserved; duplicates rejected before any averaging.
    Bad quotes/IV are flagged without deleting observations. Spot-ATM means the
    closest observed strike (tie lower strike); wings mean nearest signed delta.
    """
    def __init__(self, frame: pd.DataFrame):
        df=frame.copy(deep=True).reset_index(drop=True)
        required={'underlying','observation_date','expiration','strike','right',
                  'implied_volatility','delta','underlying_price','bid','ask'}
        if required-set(df):
            raise ValueError(f'missing chain fields: {sorted(required-set(df))}')
        if df.empty or df['underlying'].nunique()!=1 or df['observation_date'].nunique()!=1:
            raise ValueError('one nonempty underlying and valuation date required')
        df['observation_date']=pd.to_datetime(df['observation_date'])
        df['expiration']=pd.to_datetime(df['expiration'])
        keys=['underlying','observation_date','expiration','strike','right']
        if df.duplicated(keys).any():
            raise ValueError('duplicate contract/date identity')
        if (df[keys].isna().any().any() or not df['right'].isin(['call','put']).all()
                or not (pd.to_numeric(df['strike'])>0).all()):
            raise ValueError('invalid contract identity')
        if 'contract_id' in df and df['contract_id'].dropna().duplicated().any():
            raise ValueError('contract identity reused across distinct observations')
        df['strike']=df['strike'].astype(float)
        df['dte']=(df['expiration']-df['observation_date']).dt.days
        if (df['dte']<0).any():
            raise ValueError('observation after expiration')
        df['moneyness']=df['strike']/df['underlying_price'].where(df['underlying_price']>0)
        df=df.rename(columns={'implied_volatility':'provider_iv',
            **{g:'provider_'+g for g in ('delta','gamma','theta','vega','rho') if g in df}})
        self._observations=df.sort_values(keys,kind='stable').reset_index(drop=True)
        iv=df['provider_iv']
        missing=iv.isna()
        invalid=~missing & (~np.isfinite(iv) | (iv<=0))
        quote_ok=np.isfinite(df['bid']) & np.isfinite(df['ask']) & (df['bid']>=0) & (df['ask']>=df['bid'])
        violations=0
        for (_,right), group in df[quote_ok].groupby(['expiration','right']):
            group=group.sort_values('strike')
            mid=(group['bid']+group['ask'])/2
            diff=mid.diff().dropna()
            violations+=int((diff>1e-10).sum() if right=='call' else (diff< -1e-10).sum())
        delta=df['provider_delta']
        invalid_delta=delta.notna() & (~np.isfinite(delta) |
            ~((df['right'].eq('call') & delta.between(0,1)) |
              (df['right'].eq('put') & delta.between(-1,0))))
        missing_greeks={g:int(df['provider_'+g].isna().sum()) if 'provider_'+g in df else len(df)
                        for g in ('delta','gamma','theta','vega','rho')}
        self.quality=dict(missing_greeks=missing_greeks,invalid_delta=int(invalid_delta.sum()),rows=len(df),missing_iv=int(missing.sum()),invalid_iv=int(invalid.sum()),
            invalid_quotes=int((~quote_ok).sum()),strike_monotonicity_violations=violations,
            strike_monotonicity_note='midpoint diagnostic; asynchronous quotes are not proof of arbitrage',
            insufficient_strike_slices=int((df.groupby(['expiration','right'])['strike'].nunique()<3).sum()),
            insufficient_tenors=bool(df['expiration'].nunique()<2),
            missing_delta=int(df['provider_delta'].isna().sum()),
            unavailable_oi=int(df['open_interest'].isna().sum()) if 'open_interest' in df else len(df))

    @property
    def observations(self):
        """Return a copy so interpolation cannot overwrite supplied observations."""
        return self._observations.copy(deep=True)

    def skew(self, expiration: date) -> dict:
        """Observed spot-ATM call/put mean; signed 25-delta wings within 0.10."""
        sub=self._observations[self._observations['expiration']==pd.Timestamp(expiration)].copy()
        if sub.empty:
            raise ValueError('expiration unavailable')
        valid=np.isfinite(sub['provider_iv']) & (sub['provider_iv']>0)
        selections={}; atm=[]
        for right in ('call','put'):
            candidates=sub[(sub['right']==right) & valid].copy()
            candidates=candidates[np.isfinite(candidates['underlying_price']) & (candidates['underlying_price']>0)]
            if candidates.empty:
                selections['atm_'+right]=None
            else:
                candidates['spot_distance']=(candidates['strike']-candidates['underlying_price']).abs()
                r=candidates.sort_values(['spot_distance','strike'],kind='stable').iloc[0]
                atm.append(float(r['provider_iv']))
                selections['atm_'+right]=dict(strike=float(r['strike']),iv=float(r['provider_iv']),
                    delta=None if pd.isna(r['provider_delta']) else float(r['provider_delta']),
                    spot_distance=float(r['spot_distance']))
        c=sub.rename(columns={'right':'option_type','provider_iv':'implied_volatility','provider_delta':'delta'})
        call=delta_selection(c,'call',.25,.1);put=delta_selection(c,'put',-.25,.1)
        a=float(np.mean(atm)) if atm else None
        cv,pv=call['iv'],put['iv']
        diff=float(pv-cv) if np.isfinite(pv) and np.isfinite(cv) else None
        return dict(expiration=str(pd.Timestamp(expiration).date()),dte=int(sub['dte'].iloc[0]),
            atm_iv=a,atm_convention='nearest_observed_spot_strike_call_put_mean',
            atm_sides=len(atm),call_wing=call,put_wing=put,**selections,
            put_skew=float(pv-a) if a is not None and np.isfinite(pv) else None,
            call_skew=float(cv-a) if a is not None and np.isfinite(cv) else None,
            put_call_skew=diff,risk_reversal_call_minus_put=None if diff is None else -diff)

    def tenor(self, target_dte: float) -> dict:
        """ATM total-variance tenor summary; no extrapolation beyond the chain."""
        points=[]
        for expiration in sorted(self._observations['expiration'].unique()):
            s=self.skew(expiration)
            # Both call and put coverage required to compare this ATM convention.
            if s['atm_iv'] is not None and s['atm_sides']==2:
                points.append((s['dte'],s['atm_iv']))
        return fixed_tenor(points,target_dte)
