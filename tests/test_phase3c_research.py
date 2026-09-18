"""Phase 3C reporting must fail closed, not certify legacy or mutable inputs."""
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
import json
import numpy as np
import pandas as pd
import pytest
from quantbot.research.certification import (freeze, verify_freeze, cost_scenario,
    reconcile_metrics, write_manifest, verify_manifest, load_sources, classify,
    executed_episodes, pair_attribution)
from quantbot.data.storage.provenance import file_digest, seal, json_bytes
from quantbot.costs.transaction_costs import EquityCostModel
from quantbot.backtest.order import Order, OrderStatus


def result():
    ix=pd.to_datetime(['2020-01-02','2020-01-03','2020-01-06'])
    eq=pd.Series([990.,1000.,1010.],index=ix)
    z=pd.DataFrame({'A':[0.,0.,0.]},index=ix)
    return SimpleNamespace(equity_curve=eq,initial_capital=1000.,
        returns=eq/pd.Series([1000.,990.,1000.],index=ix)-1,
        cash=eq.copy(),quantities=z.copy(),marks=z.copy(),weights=z.copy(),
        pnl_components=pd.DataFrame({'market_pnl':[-10.,10.,10.],
            'transaction_cost':[0.,0.,0.],'total_net_pnl':[-10.,10.,10.]},index=ix),
        turnover_series=pd.Series(0.,index=ix),orders=[],ledger=[],
        gross_pnl=pd.DataFrame({'A':[-10.,10.,10.]},index=ix),
        trading_costs=z.copy(),borrow_costs=z.copy(),dividends=z.copy(),risk_events=[])


def test_metrics_include_first_day_loss_and_correct_subperiod_anchor():
    r=result(); m=reconcile_metrics(r)
    assert m['total_return']==pytest.approx(.01)
    assert m['max_drawdown']==pytest.approx(-.01)
    assert m['starting_equity']==1000
    sub=reconcile_metrics(r,start='2020-01-03')
    assert sub['starting_equity']==990
    assert sub['total_return']==pytest.approx(1010/990-1)
    assert m['sortino']==pytest.approx(r.returns.mean()/np.sqrt(np.mean(np.minimum(r.returns,0)**2))*np.sqrt(252))


@pytest.mark.parametrize('what',['returns','cash','pnl_components'])
def test_inconsistent_result_is_never_certified(what):
    r=result()
    if what=='pnl_components': r.pnl_components.iloc[0,0]+=1
    else: getattr(r,what).iloc[0]+=.01
    with pytest.raises(ValueError,match='reconcil'): reconcile_metrics(r)


def test_freeze_is_exclusive_and_detects_changes(tmp_path):
    p=tmp_path/'spec.json'; cfg={'x':[1,2]}; freeze(p,cfg)
    assert verify_freeze(p)['specification']==cfg
    with pytest.raises(FileExistsError): freeze(p,cfg)
    v=json.loads(p.read_text()); v['specification']['x'][0]=2
    p.write_text(json.dumps(v))
    with pytest.raises(ValueError,match='checksum'): verify_freeze(p)


@pytest.mark.parametrize('multiplier',[0.,1.,2.])
def test_sensitivity_changes_only_declared_costs(multiplier):
    base={'execution':'next_open','borrow_bps':50.,'commission_bps':1.,
          'half_spread_bps':2.,'slippage_bps':2.,'impact_bps':0.,'min_commission':0.,
          'signal_cost_filter_bps':10.,'max_participation':None}
    before=deepcopy(base); scenario=cost_scenario(base,multiplier)
    assert base==before
    for k,v in base.items():
        assert scenario[k]==(v*multiplier if k in ['commission_bps','half_spread_bps','slippage_bps','impact_bps','min_commission'] else v)
    assert cost_scenario(base,1,borrow_bps=100)['borrow_bps']==100


def test_manifest_hashes_outputs_and_rejects_legacy_area(tmp_path):
    d=tmp_path/'runs'/'phase3c'/'test'; d.mkdir(parents=True)
    (d/'equity.csv').write_text('small deterministic fixture')
    metadata={'run_id':'test','git_commit':'abc','specification_sha256':'def','dataset_identity':'123'}
    path=write_manifest(d,metadata)
    assert verify_manifest(path)['run_id']=='test'
    (d/'equity.csv').write_text('changed')
    with pytest.raises(ValueError,match='output'): verify_manifest(path)
    with pytest.raises(ValueError,match='Phase 3C'): write_manifest(tmp_path/'reports'/'backtests',metadata)


def test_sources_are_hash_pinned_and_no_return_artifact_is_accepted(tmp_path):
    p=tmp_path/'SPY.csv'; p.write_text('date,open,high,low,close,adjusted_close,volume\n2020-01-02,10,11,9,10,10,100\n')
    records=[{'symbol':'SPY','filename':'SPY.csv','sha256':file_digest(p)}]
    before=p.read_bytes(); panel=load_sources(tmp_path,records)
    assert panel['SPY'].iloc[0]['close']==10
    assert p.read_bytes()==before
    p.write_text('date,equity\n2020-01-02,100')
    with pytest.raises(ValueError,match='checksum'): load_sources(tmp_path,records)
    records[0]['sha256']=file_digest(p)
    with pytest.raises(ValueError,match='OHLCV'): load_sources(tmp_path,records)


def test_status_uses_predeclared_evidence_not_sharpe_alone():
    evidence={'years':10,'completed_episodes':50,'base_return':.1,'double_cost_return':.05,
        'zero_cost_return':.2,'positive_subperiods':3,'max_drawdown':-.1,
        'largest_positive_contributor_share':.3,'reconciled':True}
    assert classify(evidence)['status']=='RESEARCH-VALIDATED'
    assert classify(evidence|{'completed_episodes':3})['status']=='RESEARCH-UNCERTAIN'
    assert classify(evidence|{'base_return':-.1,'double_cost_return':-.2,'positive_subperiods':0})['status']=='RESEARCH-REJECTED'
    with pytest.raises(ValueError): classify(evidence|{'reconciled':False})


def test_episodes_use_executed_fills_not_signal_targets():
    r=result(); ix=r.equity_curve.index
    def order(day,q,price,before,fee):
        return Order('A',day-pd.Timedelta(days=1),day,0,.5,status=OrderStatus.FILLED,
            executed_quantity=q,fill_price=price,quantity_before=before,cost=fee,notional=abs(q*price))
    r.orders=[order(ix[0],2,10,0,1),order(ix[2],-2,12,2,1)]
    r.quantities['A']=[2,2,0]; r.marks['A']=[10,11,0]
    r.borrow_costs['A']=[0,1,1]
    rejected=Order('A',ix[0],ix[1],0,1,status=OrderStatus.REJECTED)
    r.orders.append(rejected)
    episodes=executed_episodes(r)
    assert len(episodes)==1
    assert episodes[0]['net_pnl']==pytest.approx(0) # 4 gain - 2 fees - 2 borrow
    assert episodes[0]['closed'] is True
    assert episodes[0]['fills']==2


def test_pair_attribution_preserves_executed_hedge_and_reconciles():
    r=result(); ix=r.equity_curve.index
    panel={s:pd.DataFrame({'open':p,'close':p,'adjusted_close':p},index=ix)
        for s,p in {'A':[10.,12.,14.],'B':[4.,5.,6.]}.items()}
    r.quantities=pd.DataFrame({'A':[2.,2.,0.],'B':[-4.,-4.,0.]},index=ix)
    r.gross_pnl=pd.DataFrame({'A':[0.,4.,4.],'B':[0.,-4.,-4.]},index=ix)
    r.trading_costs=pd.DataFrame({'A':[1.,0.,1.],'B':[1.,0.,1.]},index=ix)
    r.borrow_costs=pd.DataFrame({'A':[0.,0.,0.],'B':[0.,.1,.1]},index=ix)
    r.ledger=[{'date':ix[0],'event':'pair_batch','accepted':True,'pairs':[{'a':'A','b':'B','beta':2.,'signal':1,'quantity_a':2.,'quantity_b':-4.}]},
        {'date':ix[2],'event':'pair_batch','accepted':True,'pairs':[]}]
    out=pair_attribution(r,panel)
    assert out.market_pnl.sum()==pytest.approx(0)
    assert out.trading_cost.sum()==pytest.approx(4)
    assert out.borrow_cost.sum()==pytest.approx(.2)
    assert out.net_pnl.sum()==pytest.approx(-4.2)
    r.quantities.at[ix[1],'A']=3
    with pytest.raises(ValueError,match='pair'): pair_attribution(r,panel)


def test_missing_held_mark_cannot_hide_in_pandas_sum():
    r=result(); r.quantities.iloc[0,0]=1.; r.marks.iloc[0,0]=np.nan
    with pytest.raises(ValueError,match='mark'): reconcile_metrics(r)


def test_run_guard_detects_config_and_legacy_mutation(tmp_path,monkeypatch):
    from quantbot.research.phase3c import guard
    import quantbot.research.phase3c as module
    monkeypatch.setattr(module,'code_files',lambda p:{'runner':'same'})
    f=tmp_path/'config.json'; f.write_text('{}')
    legacy=tmp_path/'old.csv'; legacy.write_text('historical')
    spec={'code_files':{'runner':'same'},'config_files':{'config.json':file_digest(f)},'legacy_outputs':{'old.csv':file_digest(legacy)}}
    guard(tmp_path,spec)
    legacy.write_text('changed')
    with pytest.raises(ValueError,match='legacy'): guard(tmp_path,spec)


@pytest.mark.parametrize('name',['S01','S02','S03'])
def test_runner_preserves_strategy_signals_across_cost_sensitivity(name,panel,sector_map,tmp_path):
    from quantbot.research.phase3c import run_engine,diagnostics,KEYS
    from quantbot.config import load_strategy_config,load_risk_config
    key=KEYS[name][0]; cfg=load_strategy_config()['strategies'][key]
    base={'initial_capital':1e6,'execution':'next_open','price_mode':'adjusted',
        'commission_bps':1.,'half_spread_bps':2.,'slippage_bps':2.,'impact_bps':0.,'min_commission':0.,
        'borrow_bps':50. if name=='S03' else 0.,'borrow_day_count':'sessions_252',
        'cash_interest_rate':0.,'financing_rate':None,'max_participation':None,'rebalance_band':cfg.get('rebalance_band',0.)}
    frozen={'configuration':cfg,'risk_configuration':load_risk_config()}
    before=deepcopy(frozen)
    first,sa=run_engine(name,frozen,panel,sector_map,base)
    second,sb=run_engine(name,frozen,panel,sector_map,cost_scenario(base,2.))
    pd.testing.assert_frame_equal(sa._signals,sb._signals)
    assert frozen==before
    reconcile_metrics(first); reconcile_metrics(second)
    out=diagnostics(name,first,sa,panel,tmp_path)
    assert out['completed_episodes']>=0


def test_pair_observation_does_not_change_targets(panel,sector_map):
    from quantbot.research.phase3c import AuditedPairs
    from quantbot.strategies.s03_pairs_mean_reversion import S03PairsMeanReversion
    cfg={'max_active_pairs':10}
    a=AuditedPairs(cfg,sector_map); b=S03PairsMeanReversion(cfg,sector_map)
    pd.testing.assert_frame_equal(a.target_weights(panel),b.target_weights(panel))


def test_complete_freeze_serializes_periods_and_preserves_source(tmp_path,monkeypatch):
    import quantbot.research.phase3c as module
    source=tmp_path/'original.csv'
    source.write_text('date,open,high,low,close,adjusted_close,volume\n2020-01-02,10,11,9,10,10,100\n')
    checksum=file_digest(source)
    inv=tmp_path/'inventory.json'; inv.write_text(json.dumps({'files':[{
        'relative_path':'data/cache/SPY.csv','original_path':str(source),'sha256':checksum,
        'bytes':source.stat().st_size,'row_count':1,'observed_range':{'start':'2020-01-02','end':'2020-01-02'}}]}))
    data={'universes':{u:['SPY'] for _,u in module.KEYS.values()},'sector_map':{'SPY':'broad'}}
    monkeypatch.setattr(module,'load_data_config',lambda:data)
    monkeypatch.setattr(module.subprocess,'run',lambda *a,**k:SimpleNamespace(stdout='abc'))
    for filename in ['configs/strategy_configs.json','configs/data_config.example.json','strategy_configs.json','uv.lock','pyproject.toml']:
        p=tmp_path/filename; p.parent.mkdir(exist_ok=True); p.write_text('{}')
    frozen=module.prepare(tmp_path,'unit',inv)
    spec=verify_freeze(frozen)['specification']
    assert spec['chronological_periods'][0]==['2010-2014','2010-01-01','2014-12-31']
    assert file_digest(source)==checksum
    assert file_digest(tmp_path/'runs/phase3c/unit/source_inputs/SPY.csv')==checksum


def test_report_renderer_cannot_certify_legacy_outputs(tmp_path):
    import runpy
    path=Path(__file__).parents[1]/'scripts'/'report_phase3c.py'
    module=runpy.run_path(str(path))
    legacy=tmp_path/'reports'/'backtests'; legacy.mkdir(parents=True)
    with pytest.raises(ValueError,match='Phase 3C'): module['render'](tmp_path,legacy)


def test_git_newline_conversion_preserves_research_code_identity(tmp_path):
    from quantbot.research.phase3c import code_files,guard
    src=tmp_path/'src';src.mkdir();code=src/'example.py'
    code.write_bytes(b'x = 1\r\ny = 2\n')
    before=code_files(tmp_path)
    code.write_bytes(b'x = 1\ny = 2\n')
    assert code_files(tmp_path)==before
    code.write_bytes(b'x = 2\ny = 2\n')
    assert code_files(tmp_path)!=before


def test_market_source_hash_remains_byte_exact_after_newline_conversion(tmp_path):
    p=tmp_path/'SPY.csv'
    p.write_bytes(b'date,open,high,low,close,adjusted_close,volume\r\n2020-01-02,10,11,9,10,10,100\r\n')
    records=[{'symbol':'SPY','filename':'SPY.csv','sha256':file_digest(p)}]
    assert load_sources(tmp_path,records)['SPY'].shape==(1,6)
    p.write_bytes(p.read_bytes().replace(b'\r\n',b'\n'))
    with pytest.raises(ValueError,match='checksum'):load_sources(tmp_path,records)
