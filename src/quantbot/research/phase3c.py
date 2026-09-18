"""Frozen, offline Phase 3C orchestration. No optimization or data acquisition."""
from __future__ import annotations
import argparse
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import warnings
import numpy as np
import pandas as pd
from .certification import (CRITERIA, freeze, verify_freeze, cost_scenario, load_sources,
    reconcile_metrics, executed_episodes, pair_attribution, write_manifest, verify_manifest, classify)
from ..config import load_strategy_config, load_data_config, load_risk_config
from ..data.storage.provenance import file_digest, digest, json_bytes, seal
from ..backtest.engine import BacktestEngine
from ..backtest.walk_forward import make_walk_forward_windows
from ..costs.transaction_costs import EquityCostModel
from ..costs.slippage import SlippageModel
from ..risk.risk_manager import RiskManager
from ..strategies.s01_trend_following import S01TrendFollowing
from ..strategies.s02_factor_blend import S02FactorBlend
from ..strategies.s03_pairs_mean_reversion import S03PairsMeanReversion
from ..indicators.pairs import (rolling_correlation, rolling_hedge_ratio, engle_granger_pvalue,
    estimate_half_life, compute_spread)
from ..indicators.factors import build_price_only_factors, composite_score

KEYS={'S01':('S01_trend_following','s01_trend'),'S02':('S02_factor_blend','s02_factor'),
      'S03':('S03_pairs_mean_reversion','s03_pairs')}
PERIODS=[('2010-2014','2010-01-01','2014-12-31'),('2015-2019','2015-01-01','2019-12-31'),
         ('2020-2026','2020-01-01','2026-05-19')]
LIMITATIONS=[
    'All periods previously examined; no demonstrable untouched OOS or untuned validation period.',
    'Fixed surviving ETF universe; selection and multiple-testing history; no point-in-time universe reconstruction.',
    'Legacy normalized cache bytes verified; original provider response/retrieval metadata absent; origin not independently authenticated.',
    'Adjusted research accounting, not raw-share dividend/corporate-action or live broker reconciliation.',
    'Daily next-open modeled execution; no observed bid/ask/depth; default capacity disabled, no scale-up capacity certification.',
    'Interest disabled, financing prohibited, S03 fixed borrow 50bp on carried net shorts /252; no locate or historical borrow data.',
    'No combined funded multi-strategy ledger; combined certification deferred.',
    'Performance triage is descriptive, not alpha proof; chronological windows are diagnostic, not fresh OOS.',
    'Full periods include warm-up and idle cash; annualization 252 sessions; risk-free hurdle zero.',
    'Final positions remain marked open, without invented terminal liquidation costs.',
]
RULES={
'S01':dict(signal='0.35/0.35/0.30 blend of trailing-return z-scores (20/60/120, trailing normalization 252)',
    entry='binary score >=1; trailing 20-session absolute move >4 * base roundtrip 10bp cost hurdle',
    exit='score <0.25 or three closes below EMA50 after minimum hold; ATR14*3 trailing hard stop always active',
    cadence='weekly entries/resizing; actual-held exits and central risk daily, next session execution',
    minimum_hold='20 sessions from executed entry for soft exits; hard stops/risk override',
    sizing='long-only inverse realized volatility20, target10%, strategy15% cap, central risk then 2% no-trade band',
    version='binary-phase3b'),
'S02':dict(signal='eligible-only percentile ranks: 12m-ex-1m momentum/3m momentum/1m reversal/lowvol/liquidity',
    entry='top 20% score, >=3 eligible names; raw close >=5, trailing raw ADV21 min10 >=10M; active factor values finite',
    exit='monthly no-longer-selected target zero; central risk daily',cadence='monthly entries/resizes/exits; daily risk',
    minimum_hold='none beyond monthly allocation cadence; risk may exit earlier',
    sizing='equal positive weights min(4%,1/selected count); no leverage-up; central caps; no band',version='price-only-v1-phase3b'),
'S03':dict(signal='spread=A-beta*B; trailing OLS covariance/variance beta252; trailing spread z60',
    entry='long spread z<=-2, short spread z>=2; re-arm only after |z|<=0.5',
    exit='|z|<=0.5 or >=3.5, correlation<0.50, max signal holding20, or pair deselection; evaluated daily',
    cadence='monthly causal same-sector pair selection: corr252>=0.65,coint p<=0.10,half-life2..45; weekly entry/resize; daily exits/risk',
    minimum_hold='none; max holding20 signal-state sessions (not a promise of 20 filled sessions)',
    sizing='quantities k*(+1,-beta) long or k*(-1,+beta) short; positive beta; common proportional risk/execution scale; atomic book reject',
    gross='2*risk_per_pair initial component gross, netted book scaled to target gross0.60 before caps; nonzero net permitted within limits',
    version='hedge-ratio-matched-phase3b'),
}


def portable(value):
    """Convert diagnostic types; undefined diagnostic statistics become explicit null."""
    if isinstance(value,dict): return {str(k):portable(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)): return [portable(v) for v in value]
    if isinstance(value,(pd.Timestamp,np.datetime64)): return str(pd.Timestamp(value).isoformat())
    if isinstance(value,(np.integer,)): return int(value)
    if isinstance(value,(float,np.floating)): return float(value) if np.isfinite(value) else None
    if isinstance(value,(np.bool_,)): return bool(value)
    return value


def save_json(path,value):
    """Exclusively create portable deterministic JSON."""
    with path.open('xb') as handle: handle.write(json_bytes(portable(value)))


def text_digest(path):
    """Fingerprint Git text independent of checkout CRLF/LF; never use for data blobs."""
    return digest(Path(path).read_bytes().replace(b'\r\n',b'\n'))


def code_files(repo):
    """Fingerprint all runtime source, not just the Git parent revision."""
    files=sorted((repo/'src').rglob('*.py'))
    return {p.relative_to(repo).as_posix():text_digest(p) for p in files}


def prepare(repo: Path, freeze_id: str, inventory_path: Path) -> Path:
    """Freeze specifications and hash-copy only the declared immutable source universe."""
    from ..data.storage.provenance import component
    component(freeze_id)
    destination=repo/'research'/'phase3c'/freeze_id/'freeze.json'
    if destination.exists(): raise FileExistsError(destination)
    cfg=load_strategy_config(); dc=load_data_config(); risk=load_risk_config()
    symbols=sorted(set(s for _,u in KEYS.values() for s in dc['universes'][u]))
    inventory=json.loads(inventory_path.read_text(encoding='utf-8'))
    entries={x['relative_path'].replace('\\','/'):x for x in inventory['files']}
    records=[]; source_paths={}
    for symbol in symbols:
        item=entries[f'data/cache/{symbol}.csv']; source=Path(item['original_path'])
        if file_digest(source)!=item['sha256']: raise ValueError(f'legacy source changed: {symbol}')
        records.append(dict(symbol=symbol,filename=symbol+'.csv',legacy_relative_path=item['relative_path'],
            sha256=item['sha256'],bytes=item['bytes'],rows=item['row_count'],coverage=item['observed_range'],
            classification='legacy_normalized_cache',provider='unverified legacy origin; configured yfinance intent'))
        source_paths[symbol]=source
    area=repo/'runs'/'phase3c'/freeze_id/'source_inputs'; area.mkdir(parents=True,exist_ok=False)
    for record in records:
        source=source_paths[record['symbol']]; data=source.read_bytes()
        if digest(data)!=record['sha256']: raise ValueError('source changed during freeze')
        with (area/record['filename']).open('xb') as handle: handle.write(data)
        if file_digest(source)!=record['sha256']: raise ValueError('original source changed during copy')
    panel=load_sources(area,records)
    git=subprocess.run(['git','rev-parse','HEAD'],cwd=repo,capture_output=True,text=True,check=True).stdout.strip()
    base=dict(initial_capital=1e6,execution='next_open',price_mode='adjusted',commission_bps=1.,
        half_spread_bps=2.,slippage_bps=2.,impact_bps=0.,min_commission=0.,cash_interest_rate=0.,
        financing_rate=None,max_participation=None,borrow_day_count='sessions_252',signal_cost_filter_bps=10.)
    specs={}
    for name,(key,u) in KEYS.items():
        specs[name]=dict(name=key,version=RULES[name]['version'],configuration=cfg['strategies'][key],
            universe=dc['universes'][u],rules=RULES[name],risk_configuration=risk,
            effective_risk=vars(RiskManager(risk)),
            execution=base|dict(borrow_bps=50. if name=='S03' else 0.,
                rebalance_band=cfg['strategies'][key].get('rebalance_band',0.)),
            data_start=str(min(panel[s].index[0] for s in dc['universes'][u]).date()),
            data_end=str(min(panel[s].index[-1] for s in dc['universes'][u]).date()))
    legacy={p.relative_to(repo).as_posix():file_digest(p) for root in ['reports/backtests','reports/core']
            for p in sorted((repo/root).rglob('*')) if p.is_file()}
    spec=dict(freeze_id=freeze_id,engine_git_commit=git,code_files=code_files(repo),
        config_files={name:text_digest(repo/name) for name in ['configs/strategy_configs.json',
            'configs/data_config.example.json','strategy_configs.json','uv.lock','pyproject.toml']},
        canonical_configuration=cfg,data_configuration=dc,strategy_specifications=specs,
        sources=records,dataset_identity=digest(json_bytes(records)),legacy_outputs=legacy,
        legacy_text_hashes={name:text_digest(repo/name) for name in legacy},
        text_fingerprint_convention='SHA256 after CRLF-to-LF normalization for Git text only; market inputs and generated outputs remain byte-exact',
        legacy_classification='LEGACY / NON-CERTIFIED; retained byte-for-byte for historical comparison',
        criteria=CRITERIA,chronological_periods=PERIODS,walk_forward='existing four expanding-history boundaries; continuous funded path; no fitting or reset; previously observed diagnostics',
        scenarios=['trading_0x','base','trading_2x','S03_borrow_0bp','S03_borrow_100bp'],
        research_period='2010-01-04..2026-05-19 previously observed development/research; genuine untouched OOS cannot be established',
        warnings=LIMITATIONS)
    freeze(destination,portable(spec))
    print('FROZEN',destination.relative_to(repo),'sources',len(records),'bytes',sum(r['bytes'] for r in records),flush=True)
    return destination


def guard(repo,spec):
    """Refuse changed code, configuration, lockfile, or legacy artifacts."""
    if code_files(repo)!=spec['code_files']: raise ValueError('frozen runtime code changed')
    for name,checksum in spec['config_files'].items():
        if text_digest(repo/name)!=checksum: raise ValueError('frozen config changed: '+name)
    legacy=spec.get('legacy_text_hashes',spec['legacy_outputs'])
    checksum_fn=text_digest if 'legacy_text_hashes' in spec else file_digest
    for name,checksum in legacy.items():
        if checksum_fn(repo/name)!=checksum: raise ValueError('frozen legacy artifact changed: '+name)


class AuditedPairs(S03PairsMeanReversion):
    """Observe original selection results without changing their order or values."""
    def _select_pairs(self, prices_to_date):
        chosen=super()._select_pairs(prices_to_date)
        if not hasattr(self,'selection_audit'): self.selection_audit=[]
        for a,b in chosen:
            pa,pb=prices_to_date[a].dropna().align(prices_to_date[b].dropna(),join='inner')
            beta=rolling_hedge_ratio(pa,pb,self.hedge_window).iloc[-1]
            self.selection_audit.append(dict(date=prices_to_date.index[-1],pair=a+' / '+b,
                beta=beta,correlation=rolling_correlation(pa,pb,self.correlation_window).iloc[-1],
                coint_pvalue=engle_granger_pvalue(pa.iloc[-self.correlation_window:],pb.iloc[-self.correlation_window:]),
                half_life=estimate_half_life(compute_spread(pa.iloc[-self.hedge_window:],pb.iloc[-self.hedge_window:],beta))))
        return chosen


def run_engine(name, frozen, panel, sectors, costs):
    """Instantiate fresh unchanged strategies and risk state for each sensitivity."""
    classes={'S01':S01TrendFollowing,'S02':S02FactorBlend,'S03':AuditedPairs}
    strategy=classes[name](deepcopy(frozen['configuration']),sector_map=sectors)
    cm=EquityCostModel(commission_bps=costs['commission_bps'],half_spread_bps=costs['half_spread_bps'],
        slippage=SlippageModel(fixed_bps=costs['slippage_bps'],impact_coef_bps=costs['impact_bps']),
        min_commission=costs['min_commission'])
    eng=BacktestEngine(cost_model=cm,risk_manager=RiskManager(deepcopy(frozen['risk_configuration'])),
        execution=costs['execution'],initial_capital=costs['initial_capital'],
        borrow_cost_bps_annual=costs['borrow_bps'],rebalance_band=costs['rebalance_band'],
        price_mode=costs['price_mode'],cash_interest_rate=costs['cash_interest_rate'],
        financing_rate=costs['financing_rate'],borrow_day_count=costs['borrow_day_count'],
        max_participation=costs['max_participation'])
    return eng.run(strategy,panel,sector_map=sectors),strategy


def diagnostics(name,result,strategy,panel,directory):
    """Produce descriptive evidence from fills/held quantities, never target-weight P&L."""
    episodes=executed_episodes(result)
    expected=float((result.gross_pnl-result.trading_costs-result.borrow_costs+result.dividends).sum().sum())
    if not np.isclose(sum(e['net_pnl'] for e in episodes),expected,atol=1e-6,rtol=1e-10):
        raise ValueError('executed episode P&L does not reconcile')
    pd.DataFrame(episodes).to_csv(directory/'executed_episodes.csv',index=False)
    contributors=(result.gross_pnl-result.trading_costs-result.borrow_costs+result.dividends).sum()
    contributors.to_csv(directory/'instrument_net_pnl.csv',header=['net_pnl'])
    out=dict(completed_episodes=sum(e['closed'] for e in episodes),open_episodes=sum(not e['closed'] for e in episodes),
        instrument_net_pnl=contributors.to_dict(),turnover_attribution=result.turnover_attribution(),
        cost_attribution=result.cost_attribution(),exposure=result.exposure_diagnostics())
    if name=='S01':
        durations=[e['sessions'] for e in episodes if e['closed']]
        gains=sorted([e['net_pnl'] for e in episodes if e['net_pnl']>0],reverse=True)
        out.update(median_completed_holding_sessions=float(np.median(durations)) if durations else None,
            top_five_episodes_positive_gain_share=sum(gains[:5])/sum(gains) if gains else None,
            short_holds_net_pnl=sum(e['net_pnl'] for e in episodes if e['sessions']<20),
            long_holds_net_pnl=sum(e['net_pnl'] for e in episodes if e['sessions']>=20),
            daily_exit_or_risk_decisions=sum(d['reason']=='daily_exit_or_risk' for d in result.decisions),
            signal_persistence=float((strategy._signals==strategy._signals.shift()).iloc[1:].mean().mean()),
            minimum_hold_note='Hard ATR stops and daily risk override soft minimum holding; no retuning.')
    if name=='S02':
        scores=strategy._signals; correlations=[]
        for i in range(1,len(scores)):
            a=scores.iloc[i-1]; b=scores.iloc[i]; valid=a.notna()&b.notna()
            if valid.sum()>2 and a[valid].std()>0 and b[valid].std()>0:
                correlations.append(a[valid].rank().corr(b[valid].rank()))
        prices=pd.DataFrame({s:f.adjusted_close for s,f in panel.items()})
        volume=pd.DataFrame({s:f.volume for s,f in panel.items()})
        raw=pd.DataFrame({s:f.close for s,f in panel.items()})
        factors=build_price_only_factors(prices,volume); factors['liquidity']=(raw*volume).rolling(21,min_periods=10).mean()
        eligible=scores.notna(); oldscore=composite_score(factors,strategy.factor_weights).where(eligible)
        changed=0; total=0
        for decision in result.decisions:
            if decision['reason']!='scheduled_rebalance': continue
            date=decision['date']; old=oldscore.loc[date].dropna(); new=scores.loc[date].dropna()
            if len(new)<3: continue
            def selected(row): return set(row[row>=row.quantile(1-strategy.top_q)].index)
            total+=1; changed+=selected(old)!=selected(new)
        gross=result.weights.abs().sum(axis=1); shares=result.weights.abs().div(gross.replace(0,np.nan),axis=0)
        factor_exposure={k:float((v.where(eligible).rank(axis=1,pct=True)*shares).sum(axis=1).loc[gross>0].mean()) for k,v in factors.items()}
        out.update(mean_daily_rank_correlation=float(np.mean(correlations)),
            mean_active_holdings=float((result.quantities.abs()>1e-10).sum(axis=1).loc[gross>0].mean()),
            mean_holdings_hhi=float((shares**2).sum(axis=1).loc[gross>0].mean()),
            eligibility_selection_changed_months=changed,eligible_months_examined=total,
            executed_holdings_factor_rank_exposure=factor_exposure,
            factor_pnl='Nonlinear composite ranks have no unique additive factor P&L. Held-factor ranks are exposure diagnostics, not independent funded factor returns.')
    if name=='S03':
        pairs=pair_attribution(result,panel); pairs.to_csv(directory/'pair_daily_attribution.csv',index=False)
        pd.DataFrame(getattr(strategy,'selection_audit',[])).to_csv(directory/'pair_selection.csv',index=False)
        stats=[]; pair_episodes=[]
        for pair,df in pairs.groupby('pair'):
            active=df[df.gross_notional>1e-9]; stats.append(dict(pair=pair,net_pnl=float(df.net_pnl.sum()),
                market_pnl=float(df.market_pnl.sum()),trading_cost=float(df.trading_cost.sum()),borrow_cost=float(df.borrow_cost.sum()),
                active_sessions=len(active),beta_min=float(active.beta.min()),beta_max=float(active.beta.max()),
                beta_std=float(active.beta.std()),mean_gross_notional=float(active.gross_notional.mean()),
                mean_net_notional=float(active.net_notional.mean())))
            # Include a closure row in its ending episode; gaps between active blocks remain flat.
            episode=None; previous_signal=0
            for row in df.itertuples():
                sign=row.signal
                if previous_signal and sign and sign!=previous_signal:
                    # A reversal ends one episode and starts another; split this day's
                    # P&L attribution is ambiguous, so count/duration only (no fabricated episode P&L).
                    episode['closed']=True; episode['end']=str(row.date.date()); pair_episodes.append(episode); episode=None
                if sign and episode is None: episode=dict(pair=pair,start=str(row.date.date()),end=str(row.date.date()),closed=False)
                if episode is not None: episode['end']=str(row.date.date())
                if not sign and episode is not None: episode['closed']=True; pair_episodes.append(episode); episode=None
                previous_signal=sign
            if episode: pair_episodes.append(episode)
        for e in pair_episodes:
            e['sessions']=int(((result.equity_curve.index>=e['start'])&(result.equity_curve.index<=e['end'])).sum())
        pd.DataFrame(stats).to_csv(directory/'pair_summary.csv',index=False)
        pd.DataFrame(pair_episodes).to_csv(directory/'pair_episodes.csv',index=False)
        out.update(pair_summary=stats,completed_pair_episodes=sum(e['closed'] for e in pair_episodes),
            pair_episode_median_sessions=float(np.median([e['sessions'] for e in pair_episodes])) if pair_episodes else None,
            selected_pairs=sorted(set(x['pair'] for x in getattr(strategy,'selection_audit',[]))),
            selection_summary=pd.DataFrame(getattr(strategy,'selection_audit',[])).drop(columns=['date','pair'],errors='ignore').describe().to_dict() if getattr(strategy,'selection_audit',[]) else {},
            attribution_convention='Accepted virtual pair quantities sum to actual netted holdings; fees allocated by absolute component deltas; net-short borrow allocated to short contributors. Not separate capital ledgers.')
        contributors=pd.Series({s['pair']:s['net_pnl'] for s in stats},dtype=float)
    positives=contributors.clip(lower=0)
    out['largest_positive_contributor_share']=float(positives.max()/positives.sum()) if positives.sum()>0 else 1.
    return portable(out)


def execute(repo: Path, freeze_path: Path, run_id: str, source_directory: Path):
    """Run all predefined scenarios offline and save reconciled, versioned artifacts."""
    from ..data.storage.provenance import component
    component(run_id); sealed=verify_freeze(freeze_path); spec=sealed['specification']; guard(repo,spec)
    panel=load_sources(source_directory,spec['sources']); area=repo/'runs'/'phase3c'/run_id
    area.mkdir(parents=True,exist_ok=False)
    save_json(area/'frozen_specification.json',sealed)
    summary={}; caught=[]
    legacy_runtime_bytes={name:file_digest(repo/name) for name in spec['legacy_outputs']}
    input_identity={s:digest(pd.util.hash_pandas_object(f,index=True).values.tobytes()) for s,f in panel.items()}
    def verify_inputs():
        if any(file_digest(repo/name)!=sha for name,sha in legacy_runtime_bytes.items()):
            raise ValueError('legacy artifact bytes changed during run')
        if verify_freeze(freeze_path)['manifest_sha256'] != sealed['manifest_sha256']:
            raise ValueError('frozen specification changed during run')
        current={s:digest(pd.util.hash_pandas_object(f,index=True).values.tobytes()) for s,f in panel.items()}
        if current!=input_identity: raise ValueError('in-memory source data changed during run')
        guard(repo,spec)
    with warnings.catch_warnings(record=True) as warning_records:
        warnings.simplefilter('always')
        for name,frozen in spec['strategy_specifications'].items():
            subpanel={s:panel[s] for s in frozen['universe']}; sectors=spec['data_configuration']['sector_map']
            scenarios=[('trading_0x',0.,None),('base',1.,None),('trading_2x',2.,None)]
            if name=='S03': scenarios += [('borrow_0bp',1.,0.),('borrow_100bp',1.,100.)]
            summary[name]={}
            for label,multiplier,borrow in scenarios:
                print('RUN',name,label,flush=True); verify_inputs()
                folder=area/name/label; folder.mkdir(parents=True,exist_ok=False)
                costs=cost_scenario(frozen['execution'],multiplier,borrow_bps=borrow)
                result,strategy=run_engine(name,frozen,subpanel,sectors,costs)
                metrics=reconcile_metrics(result)
                periods={label:reconcile_metrics(result,start,end) for label,start,end in spec['chronological_periods']}
                windows=[dict(history_end=str(w.train_end.date()),classification='previously-observed chronological diagnostic',
                    metrics=reconcile_metrics(result,w.test_start,w.test_end)) for w in make_walk_forward_windows(result.equity_curve.index)]
                for key in ['equity_curve','returns','cash','weights','quantities','marks','gross_pnl','trading_costs','borrow_costs','pnl_components']:
                    getattr(result,key).to_csv(folder/(key+'.csv'))
                pd.DataFrame([asdict(o) for o in result.orders]).to_csv(folder/'orders.csv',index=False)
                save_json(folder/'decisions.json',result.decisions); save_json(folder/'ledger.json',result.ledger)
                diag=diagnostics(name,result,strategy,subpanel,folder)
                record=dict(metrics=metrics,chronological_periods=periods,walk_forward=windows,diagnostics=diag,costs=costs)
                save_json(folder/'results.json',record)
                manifest=write_manifest(folder,dict(run_id=run_id+'-'+name+'-'+label,git_commit=spec['engine_git_commit'],
                    runtime_source_identity=digest(json_bytes(spec['code_files'])),specification_sha256=sealed['manifest_sha256'],
                    dataset_identity=spec['dataset_identity'],costs=costs,metrics=metrics,warnings=spec['warnings']))
                verify_manifest(manifest); summary[name][label]=record
                print('RESULT',name,label,json.dumps({k:metrics[k] for k in ['ending_equity','total_return','sharpe','executed_trades']}),flush=True)
                verify_inputs()
        caught=[dict(category=w.category.__name__,message=str(w.message)) for w in warning_records]
    for name,scenarios in summary.items():
        base=scenarios['base']; m=base['metrics']; d=base['diagnostics']
        evidence=dict(years=m['years'],completed_episodes=d.get('completed_pair_episodes',d['completed_episodes']),
            base_return=m['total_return'],double_cost_return=scenarios['trading_2x']['metrics']['total_return'],
            zero_cost_return=scenarios['trading_0x']['metrics']['total_return'],
            positive_subperiods=sum(x['total_return']>0 for x in base['chronological_periods'].values()),
            max_drawdown=m['max_drawdown'],largest_positive_contributor_share=d['largest_positive_contributor_share'],reconciled=True)
        scenarios['classification']=classify(evidence)
    save_json(area/'summary.json',summary); save_json(area/'warnings.json',caught)
    verify_inputs(); load_sources(source_directory,spec['sources'])
    path=write_manifest(area,dict(run_id=run_id,git_commit=spec['engine_git_commit'],
        runtime_source_identity=digest(json_bytes(spec['code_files'])),specification_sha256=sealed['manifest_sha256'],
        dataset_identity=spec['dataset_identity'],warnings=spec['warnings'],runtime_warnings=caught,
        research_status={name:x['classification']['status'] for name,x in summary.items()}))
    verify_manifest(path); print('COMPLETE',path.relative_to(repo),flush=True)
    return summary


def main():
    """Explicit freeze and run commands; never guess an input directory."""
    ap=argparse.ArgumentParser(); ap.add_argument('--repo',type=Path,default=Path.cwd())
    commands=ap.add_subparsers(dest='command',required=True)
    f=commands.add_parser('freeze'); f.add_argument('--id',required=True); f.add_argument('--inventory',type=Path,required=True)
    r=commands.add_parser('run'); r.add_argument('--freeze',type=Path,required=True); r.add_argument('--id',required=True); r.add_argument('--sources',type=Path,required=True)
    args=ap.parse_args()
    if args.command=='freeze': prepare(args.repo,args.id,args.inventory)
    else: execute(args.repo,args.freeze,args.id,args.sources)

if __name__=='__main__': main()
