"""Approved S05 defined-risk short volatility; daily research only.

This is an OptionsStrategy, not an equity target-weight strategy. The dedicated
Phase 4B runner seals its inputs; generic equity activation remains disabled.
"""
import math
import numpy as np
import pandas as pd
from ..options.s05_spec import S05Parameters
from ..options.strategy_base import OptionsStrategy
from ..options.spreads import Candidate, _reject
from ..options.fill_model import fill_structure
from ..options.contract_selector import lookup_row
from ..options.risk import RiskDecision
from ..costs.transaction_costs import OptionsCostModel
from ..utils.market_calendar import USMarketCalendar


def _spot(frame):
    values=pd.to_numeric(frame.underlying_price,errors='coerce').to_numpy(dtype=float)
    if (not len(values) or not np.isfinite(values).all() or (values<=0).any()
            or not np.allclose(values,values[0],rtol=0,atol=1e-8)):
        raise ValueError('missing_invalid_or_conflicting_underlying_spot')
    return float(values[0])


def build_condor(chain, day, underlying, p: S05Parameters) -> Candidate:
    """Freeze four identities before quote checks; never optimize width/premium."""
    name='S05_defined_risk_short_vol_v1'
    sub=chain[(chain.underlying==underlying)&(chain.date==day)].copy()
    if sub.empty:return _reject(name,'missing_chain')
    keys=['underlying','date','expiration','option_type','strike']
    if sub.duplicated(keys).any():raise ValueError('duplicate contract/date identity')
    try:spot=_spot(sub)
    except ValueError as exc:return _reject(name,str(exc))
    dte=(pd.to_datetime(sub.expiration)-day).dt.days
    eligible=sub[dte.between(p.dte_min,p.dte_max)]
    if eligible.empty:return _reject(name,'no_expiration')
    expiry=eligible.expiration.min();sub=sub[sub.expiration==expiry]
    shorts=[]
    for right,sign in [('put',-1),('call',1)]:
        d=sub.delta*sign
        x=sub[(sub.option_type==right)&np.isfinite(d)&d.between(p.short_delta_min,p.short_delta_max)].copy()
        x=x[x.strike<spot] if right=='put' else x[x.strike>spot]
        if x.empty:return _reject(name,'missing_short_'+right)
        x['distance']=(x.delta-sign*p.short_delta).abs().round(12)
        shorts.append(x.sort_values(['distance','strike'],kind='stable').iloc[0])
    put,call=shorts
    put_widths={round(float(put.strike-k),8) for k in sub.loc[sub.option_type=='put','strike'] if 0<put.strike-k<=p.max_width}
    call_widths={round(float(k-call.strike),8) for k in sub.loc[sub.option_type=='call','strike'] if 0<k-call.strike<=p.max_width}
    common=put_widths&call_widths
    if not common:return _reject(name,'no_common_protective_wing')
    width=min(common)
    identities=[('put',float(put.strike-width),1),('put',float(put.strike),-1),
                ('call',float(call.strike),-1),('call',float(call.strike+width),1)]
    legs=[dict(underlying=underlying,expiration=expiry,option_type=r,strike=k,qty=q,multiplier=100) for r,k,q in identities]
    rows=[lookup_row(sub,underlying=underlying,expiration=expiry,option_type=l['option_type'],strike=l['strike']) for l in legs]
    if any(r is None for r in rows):return _reject(name,'missing_protective_wing')
    fill=fill_structure(legs,rows,spread_max_pct=p.spread_max_pct,
        cost_model=OptionsCostModel(per_contract_fee=p.per_contract_fee,multi_leg_penalty=p.multi_leg_penalty))
    if not fill.accepted:return _reject(name,fill.reject_reason)
    if not 0<fill.net_cash<width*100:return _reject(name,'invalid_condor_credit')
    return Candidate(name,underlying,expiry,legs,fill,fill.net_cash,fill.net_cash,
        -(width*100-fill.net_cash),width,meta=dict(short_put_delta=float(put.delta),
        short_call_delta=float(call.delta),put_delta_distance=abs(float(put.delta)+p.short_delta),
        call_delta_distance=abs(float(call.delta)-p.short_delta),selected_dte=int((expiry-day).days),
        spot=spot,selection='smallest common outward listed width; no alternate quote search'))


def exit_decision(position, day, spot, liquidation_debit, p: S05Parameters):
    """Gross debit thresholds only: commissions never move profit/stop levels."""
    triggers=[]
    if (position.expiration-day).days<=p.exit_dte:triggers.append('dte_exit')
    put=next(l.strike for l in position.legs if l.qty<0 and l.option_type=='put')
    call=next(l.strike for l in position.legs if l.qty<0 and l.option_type=='call')
    if spot<=put or spot>=call:triggers.append('strike_breach')
    if liquidation_debit is not None and math.isfinite(liquidation_debit):
        if liquidation_debit>=p.stop_debit_multiple*position.net_entry_cash-1e-10:triggers.append('stop_credit')
        if liquidation_debit<=p.profit_debit_fraction*position.net_entry_cash+1e-10:triggers.append('profit_credit')
    return bool(triggers),triggers[0] if triggers else '',triggers


class S05ImpliedVsRealizedVol(OptionsStrategy):
    """One-lot hedge-defined short-volatility strategy, separately funded by symbol."""
    name='S05_defined_risk_short_vol_v1'

    def __init__(self, underlying, signal_panel, parameters=None):
        if underlying not in ('SPY','QQQ'):raise ValueError('S05 approved universe is SPY/QQQ')
        self.underlying=underlying
        self.parameters=parameters or S05Parameters()
        self.panel=signal_panel.copy(deep=True)
        if self.panel.index.has_duplicates:raise ValueError('duplicate signal date')
        self.decisions=[];self.exit_observations=[]
        self._attempted=set()

    def on_decision_open(self,t,chain_today,portfolio):
        """Weekly attempt only; every available decision is recorded with features."""
        p=self.parameters;cal=USMarketCalendar();t=cal.label(t)
        monday=t-pd.Timedelta(days=t.weekday())
        first=cal.sessions(monday,t)[0] if cal.is_session(t) else None
        features=self.panel.loc[t].to_dict() if t in self.panel.index else dict(signal=False,status='missing_features')
        record=dict(date=t,**features);self.decisions.append(record)
        if t!=first:record['decision']='not_week_start';return None
        if t in self._attempted:record['decision']='already_attempted';return None
        self._attempted.add(t)
        if not features['signal']:record['decision']=features['status'];return None
        if portfolio.open_positions>=p.max_positions:record['decision']='already_holding';return None
        cand=build_condor(chain_today,t,self.underlying,p)
        if not cand.reject_reason:
            check=self.admit_execution(cand,cand.fill,t,chain_today,portfolio,p.initial_capital)
            if not check.accepted:cand.reject_reason=check.reason
        record['decision']=cand.reject_reason or 'candidate'
        cand.meta.update(signal_date=str(t.date()),iv30=features.get('iv30'),rv=features.get('rv'),
                         percentile=features.get('percentile'),vrp=features.get('vrp'))
        return cand

    def admit_execution(self,candidate,fill,t,chain_today,portfolio,initial_capital):
        """Additional S05 checks before booking: real fills, fees and pre-credit cash."""
        p=self.parameters;obligation=candidate.width*100
        fees=fill.cost+4*p.per_contract_fee+p.multi_leg_penalty
        credit=fill.net_cash
        if not (np.isfinite([credit,fees,portfolio.cash,portfolio.equity]).all() and 0<credit<obligation):
            return RiskDecision(False,'invalid_condor_credit_or_account')
        if credit>p.max_credit_dollars:return RiskDecision(False,'credit_cap')
        loss=obligation-credit+fees
        if loss>min(p.max_loss_dollars,p.per_trade_risk_fraction*min(initial_capital,portfolio.equity))+1e-10:
            return RiskDecision(False,'fee_inclusive_max_loss')
        if portfolio.portfolio_defined_loss+loss>p.aggregate_risk_fraction*initial_capital:
            return RiskDecision(False,'fee_inclusive_aggregate_loss')
        if portfolio.cash<obligation+fees:return RiskDecision(False,'insufficient_unlevered_reserve')
        if portfolio.open_positions>=p.max_positions:return RiskDecision(False,'max_concurrent_positions')
        if (candidate.expiration-t).days<=p.exit_dte:return RiskDecision(False,'entry_already_at_exit_dte')
        return RiskDecision(True)

    def on_decision_close(self,position,chain_today,t):
        """Observe gross executable liquidation; schedule only a future atomic close."""
        p=self.parameters;sub=chain_today[chain_today.underlying==self.underlying]
        spot=_spot(sub)
        rows=[lookup_row(sub,underlying=self.underlying,expiration=l.expiration,
            option_type=l.option_type,strike=l.strike) for l in position.legs]
        if any(r is None for r in rows):raise ValueError(f'missing close observation: {self.underlying} {t}')
        legs=[dict(underlying=l.underlying,expiration=l.expiration,option_type=l.option_type,
                   strike=l.strike,qty=-l.qty,multiplier=l.multiplier) for l in position.legs]
        fill=fill_structure(legs,rows,spread_max_pct=p.spread_max_pct)
        debit=-fill.net_cash if fill.accepted else None
        want,reason,triggers=exit_decision(position,t,spot,debit,p)
        self.exit_observations.append(dict(date=t,expiration=position.expiration,
            entry_credit=position.net_entry_cash,liquidation_debit=debit,
            executable=fill.accepted,quote_status=fill.reject_reason or 'valid',
            spot=spot,triggers=triggers,reason=reason))
        return want,reason