"""Phase 3C research integrity and execution-derived accounting diagnostics.

This module never changes signals, risk, fills, or source inputs. Annualization
uses 252 sessions; Sortino uses RMS negative returns over ALL observations.
"""
from __future__ import annotations
from copy import deepcopy
from pathlib import Path
import json
import math
import numpy as np
import pandas as pd
from ..backtest.order import OrderStatus
from ..data.storage.provenance import seal, load_sealed, json_bytes, file_digest
from ..utils.market_calendar import USMarketCalendar

TRADING_FIELDS=('commission_bps','half_spread_bps','slippage_bps','impact_bps','min_commission')
CRITERIA={'minimum_years':5,'minimum_completed_episodes':30,
    'minimum_positive_subperiods':2,'maximum_drawdown_magnitude':.20,
    'maximum_positive_contributor_share':.50,
    'rejection':'base and 2x costs nonpositive AND at most one positive chronological period',
    'qualification':'base and 2x positive; all sample, drawdown, breadth gates satisfied',
    'meaning':'descriptive continued-research triage; neither alpha proof nor live readiness'}


def freeze(path: Path, specification: dict) -> dict:
    """Create a sealed, exclusive specification BEFORE any performance run."""
    value=seal({'format_version':'phase3c-freeze-v1','specification':deepcopy(specification)})
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('xb') as handle: handle.write(json_bytes(value))
    return value


def verify_freeze(path: Path) -> dict:
    """Read only a checksum-valid specification."""
    return load_sealed(path)


def cost_scenario(base: dict, multiplier: float, *, borrow_bps=None) -> dict:
    """Change execution charges only; the strategy entry cost filter stays frozen."""
    if not math.isfinite(multiplier) or multiplier<0: raise ValueError('invalid cost multiplier')
    out=deepcopy(base)
    for key in TRADING_FIELDS: out[key]*=multiplier
    if borrow_bps is not None:
        if not math.isfinite(borrow_bps) or borrow_bps<0: raise ValueError('invalid borrow rate')
        out['borrow_bps']=borrow_bps
    return out


def load_sources(directory: Path, records: list[dict]) -> dict:
    """Load hash-pinned OHLCV source bytes; no downloads, fallback, or filling gaps."""
    panel={}
    for item in records:
        name=item['filename']
        if Path(name).name!=name: raise ValueError('source filename must be a basename')
        p=directory/name
        if file_digest(p)!=item['sha256']: raise ValueError(f'source checksum mismatch: {name}')
        frame=pd.read_csv(p)
        needed={'date','open','high','low','close','adjusted_close','volume'}
        if not needed<=set(frame): raise ValueError(f'OHLCV source required: {name}')
        frame['date']=pd.to_datetime(frame['date']); frame=frame.set_index('date')
        USMarketCalendar().validate_index(frame.index)
        values=frame[list(needed-{'date'})].to_numpy(dtype=float)
        if not np.isfinite(values).all(): raise ValueError(f'nonfinite OHLCV: {name}')
        if not (frame[['open','high','low','close','adjusted_close']]>0).all().all() or (frame.volume<0).any():
            raise ValueError(f'invalid OHLCV: {name}')
        panel[item['symbol']]=frame
    return panel


def _equal(a,b,message):
    if not np.allclose(a,b,rtol=1e-10,atol=1e-7,equal_nan=False):
        raise ValueError('reconciliation failed: '+message)


def reconcile_metrics(result, start=None, end=None) -> dict:
    """Reconcile the complete run before measuring any chronologically anchored slice."""
    eq=result.equity_curve; r=result.returns
    if not eq.index.equals(r.index) or not len(eq) or not (eq>0).all():
        raise ValueError('reconciliation requires positive aligned equity')
    prev=eq.shift(1); prev.iloc[0]=result.initial_capital
    _equal(result.initial_capital*(1+r).cumprod(),eq,'returns / equity')
    held=result.quantities.abs()>1e-12
    if ((~np.isfinite(result.marks) | (result.marks<=0)) & held).any().any():
        raise ValueError('reconciliation missing/invalid held mark')
    _equal(result.cash+(result.quantities*result.marks).sum(axis=1),eq,'cash / positions')
    components=result.pnl_components.drop(columns='total_net_pnl')
    _equal(components.sum(axis=1),result.pnl_components.total_net_pnl,'components')
    _equal(result.pnl_components.total_net_pnl,eq-prev,'daily P&L')
    for event in result.ledger:
        if all(k in event for k in ('cash','quantities','marks','equity')):
            _equal(event['cash']+sum(q*event['marks'][s] for s,q in event['quantities'].items()),
                   event['equity'],'event ledger')
    select=(eq.index>=pd.Timestamp(start or eq.index[0]))&(eq.index<=pd.Timestamp(end or eq.index[-1]))
    ix=eq.index[select]
    if len(ix)==0: raise ValueError('empty measurement interval')
    rs=r.loc[ix]; es=eq.loc[ix]; initial=float(prev.loc[ix[0]]); final=float(es.iloc[-1])
    anchored=pd.Series([initial,*es.to_list()]); years=len(ix)/252
    vol=float(rs.std(ddof=1)*np.sqrt(252)) if len(ix)>1 else 0.
    downside=float(np.sqrt(np.mean(np.minimum(rs,0)**2))*np.sqrt(252))
    orders=[o for o in result.orders if o.execution_date in ix]
    executed=[o for o in orders if o.status==OrderStatus.FILLED and abs(o.executed_quantity)>1e-12]
    w=result.weights.loc[ix]; gross=w.abs().sum(axis=1); net=w.sum(axis=1)
    active=w.abs().stack(); active=active[active>1e-12]
    pnl={k:float(v) for k,v in components.loc[ix].sum().items()}
    return dict(start=str(ix[0].date()),end=str(ix[-1].date()),sessions=len(ix),years=years,
        starting_equity=initial,ending_equity=final,total_return=final/initial-1,
        cagr=(final/initial)**(1/years)-1 if years>=1 else None,
        annualized_volatility=vol,sharpe=float(rs.mean()*252/vol) if vol>0 else None,
        sortino=float(rs.mean()*252/downside) if downside>0 else None,
        max_drawdown=float((anchored/anchored.cummax()-1).min()),
        turnover=float(result.turnover_series.loc[ix].sum()),
        annual_turnover=float(result.turnover_series.loc[ix].sum()/years),
        executed_trades=len(executed),rejected_orders=sum(o.status==OrderStatus.REJECTED for o in orders),
        capacity_limited_orders=sum(o.execution_outcome=='capacity_limited' for o in orders),
        mean_gross_exposure=float(gross.mean()),max_gross_exposure=float(gross.max()),
        mean_net_exposure=float(net.mean()),max_absolute_net_exposure=float(net.abs().max()),
        mean_nonzero_position_exposure=float(active.mean()) if len(active) else 0.,
        max_position_exposure=float(w.abs().max().max()),
        mean_holdings=float((w.abs()>1e-12).sum(axis=1).mean()),
        component_pnl=pnl,total_net_pnl=final-initial,
        return_compounding_error=float(abs(initial*(1+rs).prod()-final)),
        risk_event_count=sum(pd.Timestamp(e['date']) in ix for e in result.risk_events))


def write_manifest(directory: Path, metadata: dict) -> Path:
    """Seal every output byte in a NEW, separate Phase 3C run directory."""
    if not any(directory.parts[i:i+2]==('runs','phase3c') for i in range(len(directory.parts)-1)):
        raise ValueError('certified outputs require a separate runs/phase3c Phase 3C directory')
    path=directory/'manifest.json'
    outputs=[{'path':p.relative_to(directory).as_posix(),'sha256':file_digest(p),'bytes':p.stat().st_size}
             for p in sorted(directory.rglob('*')) if p.is_file() and p!=path]
    value=seal(metadata|{'format_version':'phase3c-run-v1','artifact_class':'corrected-research-run',
                         'outputs':outputs})
    with path.open('xb') as handle: handle.write(json_bytes(value))
    return path


def verify_manifest(path: Path) -> dict:
    """Check both manifest contents and every declared output checksum."""
    value=load_sealed(path)
    for item in value['outputs']:
        target=(path.parent/item['path']).resolve()
        if not target.is_relative_to(path.parent.resolve()) or not target.is_file() or file_digest(target)!=item['sha256']:
            raise ValueError('output checksum/path mismatch')
    return value


def classify(e: dict) -> dict:
    """Apply the pre-run descriptive evidence gates without parameter search."""
    if not e['reconciled']: raise ValueError('unreconciled run cannot be classified')
    failures=[]
    gates={'sample_years':e['years']>=CRITERIA['minimum_years'],
        'completed_episodes':e['completed_episodes']>=CRITERIA['minimum_completed_episodes'],
        'base_positive':e['base_return']>0,'double_cost_positive':e['double_cost_return']>0,
        'chronological_stability':e['positive_subperiods']>=CRITERIA['minimum_positive_subperiods'],
        'drawdown':-e['max_drawdown']<=CRITERIA['maximum_drawdown_magnitude'],
        'contribution_breadth':e['largest_positive_contributor_share']<=CRITERIA['maximum_positive_contributor_share']}
    failures=[k for k,v in gates.items() if not v]
    rejected=e['base_return']<=0 and e['double_cost_return']<=0 and e['positive_subperiods']<=1
    status='RESEARCH-REJECTED' if rejected else ('RESEARCH-UNCERTAIN' if failures else 'RESEARCH-VALIDATED')
    return dict(status=status,failed_gates=failures,evidence=e,criteria=CRITERIA)


def executed_episodes(result) -> list[dict]:
    """Cash-flow P&L of actual symbol holding episodes, including open terminal marks.

    Allocate a reversal's fee by executed notional. Borrow belongs to the carried
    position (including its exit day), before applying that day's executions.
    """
    live={}; out=[]; orders={d:[] for d in result.equity_curve.index}
    for order in result.orders:
        if order.status==OrderStatus.FILLED and abs(order.executed_quantity)>1e-12:
            orders[order.execution_date].append(order)
    def finish(symbol,date,closed,mark=0.):
        record=live.pop(symbol); record['net_pnl']+=record['quantity']*mark
        record.update(end=str(date.date()),closed=closed,
            sessions=int(result.equity_curve.index.get_loc(date)-record.pop('start_index')+1))
        out.append(record)
    for i,date in enumerate(result.equity_curve.index):
        for symbol,record in live.items():
            record['net_pnl']-=float(result.borrow_costs.at[date,symbol])
            record['net_pnl']+=float(result.dividends.at[date,symbol])
        for order in orders[date]:
            s=order.symbol; q=order.executed_quantity; price=order.fill_price; fee=order.cost
            old=live.get(s,{}).get('quantity',0.)
            if old and old*q<0 and abs(q)>abs(old)+1e-10:
                close_fee=fee*abs(old/q)
                live[s]['net_pnl']+=old*price-close_fee; live[s]['quantity']=0.; live[s]['fills']+=1
                finish(s,date,True); q+=old; fee-=close_fee
            if s not in live:
                live[s]=dict(symbol=s,start=str(date.date()),start_index=i,quantity=0.,net_pnl=0.,fills=0)
            record=live[s]; record['quantity']+=q; record['net_pnl']-=q*price+fee; record['fills']+=1
            if abs(record['quantity'])<1e-9: record['quantity']=0.; finish(s,date,True)
    date=result.equity_curve.index[-1]
    for s in list(live): finish(s,date,False,float(result.marks.at[date,s]))
    return out


def pair_attribution(result, panel: dict) -> pd.DataFrame:
    """Replay accepted component quantities; reconcile them to the netted real book.

    Pair trading costs allocate actual symbol fees by absolute virtual quantity
    change. Actual net-short borrow allocates to contributing short components.
    These are attribution conventions, not independently funded pair backtests.
    """
    batches={e['date']:e['pairs'] for e in result.ledger if e['event']=='pair_batch' and e['accepted']}
    held={}; rows=[]; previous=None
    def legs(spec): return {spec['a']:spec['quantity_a'],spec['b']:spec['quantity_b']}
    for date in result.equity_curve.index:
        old=held
        if date in batches: held={p['a']+' / '+p['b']:p for p in batches[date]}
        keys=sorted(set(old)|set(held)); day=[]
        deltas={key:{s:legs(held[key]).get(s,0.) if key in held else 0. for s in panel} for key in keys}
        for key in keys:
            for s,q in (legs(old[key]) if key in old else {}).items(): deltas[key][s]-=q
        for key in keys:
            prior=legs(old[key]) if key in old else {}; now=legs(held[key]) if key in held else {}
            market=cost=borrow=turn=0.
            for s in set(prior)|set(now):
                close=float(panel[s].at[date,'adjusted_close'])
                op=float(panel[s].at[date,'open']*close/panel[s].at[date,'close'])
                last=float(panel[s].at[previous,'adjusted_close']) if previous is not None else op
                if date in batches:
                    market+=prior.get(s,0.)*(op-last)+now.get(s,0.)*(close-op)
                else: market+=now.get(s,0.)*(close-last)
                den=sum(abs(deltas[k][s]) for k in keys)
                if den: cost+=float(result.trading_costs.at[date,s])*abs(deltas[key][s])/den
                den_short=sum(max(0.,-legs(p).get(s,0.)) for p in old.values())
                if den_short: borrow+=float(result.borrow_costs.at[date,s])*max(0.,-prior.get(s,0.))/den_short
                turn+=abs(deltas[key][s])*op
            spec=held.get(key,old.get(key)); notionals=[q*panel[s].at[date,'adjusted_close'] for s,q in now.items()]
            day.append(dict(date=date,pair=key,market_pnl=market,trading_cost=cost,borrow_cost=borrow,
                net_pnl=market-cost-borrow,gross_notional=sum(abs(v) for v in notionals),net_notional=sum(notionals),
                virtual_trade_notional=turn,beta=spec['beta'],signal=spec['signal'] if key in held else 0,
                quantity_a=now.get(spec['a'],0.),quantity_b=now.get(spec['b'],0.)))
        actual={s:sum(legs(p).get(s,0.) for p in held.values()) for s in panel}
        _equal([actual[s] for s in result.quantities.columns],result.quantities.loc[date],'pair quantities')
        for key,frame in [('market_pnl',result.gross_pnl),('trading_cost',result.trading_costs),('borrow_cost',result.borrow_costs)]:
            _equal(sum(x[key] for x in day),frame.loc[date].sum(),'pair '+key)
        rows.extend(day); previous=date
    return pd.DataFrame(rows,columns=['date','pair','market_pnl','trading_cost','borrow_cost','net_pnl',
        'gross_notional','net_notional','virtual_trade_notional','beta','signal','quantity_a','quantity_b'])
