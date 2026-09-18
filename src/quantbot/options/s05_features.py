"""Causal S05 features. No filling of absent IV, returns or provider Greeks."""
import math
import numpy as np
import pandas as pd
from .s05_spec import S05Parameters
from .surface import AnalyticalChain
from ..utils.market_calendar import USMarketCalendar


def ewma_rv(adjusted_close: pd.Series, p: S05Parameters) -> pd.Series:
    """Existing recursive second moment with explicit warm-up/reset semantics."""
    s=adjusted_close.astype(float).copy()
    if s.empty:return pd.Series(dtype=float,index=s.index,name='rv')
    if s.index.has_duplicates or not s.index.is_monotonic_increasing:
        raise ValueError('underlying dates must be unique and increasing')
    cal=USMarketCalendar()
    if any(not cal.is_session(t) for t in s.index):raise ValueError('non-session underlying price')
    s=s.reindex(cal.sessions(s.index[0],s.index[-1]))
    prev=None;var=None;count=0;out=[]
    for price in s:
        if not np.isfinite(price) or price<=0:
            prev=None;var=None;count=0;out.append(np.nan);continue
        if prev is None:
            prev=price;out.append(np.nan);continue
        ret=price/prev-1;prev=price;count+=1
        var=ret*ret if var is None else p.rv_lambda*var+(1-p.rv_lambda)*ret*ret
        out.append(math.sqrt(var*p.rv_annualization) if count>=p.rv_warmup else np.nan)
    return pd.Series(out,index=s.index,name='rv')


def iv_percentile(iv: pd.Series, p: S05Parameters) -> pd.Series:
    """Strict empirical percentile; nulls consume session slots, not denominator."""
    values=iv.where(np.isfinite(iv)&(iv>0))
    def rank(a):
        if not np.isfinite(a[-1]):return np.nan
        past=a[:-1];past=past[np.isfinite(past)]
        return float((past<a[-1]).mean()) if len(past) else np.nan
    return values.rolling(p.percentile_window,min_periods=p.percentile_min_valid).apply(rank,raw=True)


def signal_eligible(iv, rv, percentile, p: S05Parameters) -> bool:
    """Inclusive frozen thresholds; small tolerance only for floating subtraction."""
    if not np.isfinite([iv,rv,percentile]).all() or iv<=0 or rv<0:return False
    spread=iv-rv
    return bool(percentile>=p.percentile_threshold and
                (spread>=p.vrp_threshold or math.isclose(spread,p.vrp_threshold,rel_tol=0,abs_tol=1e-12)))


def build_signal_panel(normalized_chain: pd.DataFrame, adjusted_close: pd.Series,
                       p: S05Parameters) -> pd.DataFrame:
    """Phase 4A IV30 + trailing underlying EWMA, indexed on exchange sessions.

    Each chain transformation sees one underlying/date only. Future additions
    cannot change past values. Invalid identities fail rather than deduplicate.
    """
    if normalized_chain.empty:raise ValueError('empty S05 corpus')
    if normalized_chain.underlying.nunique()!=1:raise ValueError('one underlying per S05 run')
    cal=USMarketCalendar();records=[]
    for day,frame in normalized_chain.groupby('observation_date',sort=True):
        day=pd.Timestamp(day)
        if not cal.is_session(day):raise ValueError(f'non-session chain: {day}')
        frame=frame.copy()
        frame['expiration']=pd.to_datetime(frame['expiration'])
        dte=(frame.expiration-day).dt.days
        frame=frame[(dte>0)&(dte<=p.iv_max_dte)]
        iv=dict(iv=None,status='insufficient_tenor_coverage',bracket_dtes=[],interpolated=False)
        if not frame.empty:iv=AnalyticalChain(frame).tenor(p.iv_target_dte)
        records.append(dict(date=day,iv30=iv['iv'],iv_status=iv['status'],
                            bracket_dtes=iv['bracket_dtes'],interpolated=iv['interpolated']))
    out=pd.DataFrame(records).set_index('date')
    out=out.reindex(cal.sessions(out.index[0],out.index[-1]))
    out.index.name='date'
    out['iv30']=pd.to_numeric(out.iv30,errors='raise')
    out['rv']=ewma_rv(adjusted_close.loc[:out.index[-1]],p).reindex(out.index)
    out['percentile']=iv_percentile(out.iv30,p)
    out['iv_count']=out.iv30.notna().rolling(p.percentile_window,min_periods=1).sum().astype(int)
    out['vrp']=out.iv30-out.rv
    out['signal']=[signal_eligible(iv,rv,pct,p) for iv,rv,pct in zip(out.iv30,out.rv,out.percentile)]
    def status(r):
        if pd.isna(r.iv30):return 'missing_iv30'
        if pd.isna(r.rv):return 'insufficient_rv_warmup'
        if pd.isna(r.percentile):return 'insufficient_iv_history'
        return 'eligible' if r.signal else 'below_threshold'
    out['status']=out.apply(status,axis=1)
    return out