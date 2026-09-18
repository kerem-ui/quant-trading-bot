"""Phase 4B frozen research/reporting guards (no market fixtures)."""
import json
from pathlib import Path
import pandas as pd
import pytest
from quantbot.research.phase4b import load_specification, reconcile_result, guard_unchanged
from quantbot.data.storage.provenance import file_digest

ROOT=Path(__file__).resolve().parents[1]
SPEC=ROOT/'research/phase4b/s05-v1/specification.json'


def test_frozen_approved_parameters_and_metadata():
    spec,p=load_specification(SPEC,ROOT)
    assert p.profit_debit_fraction==.5 and p.stop_debit_multiple==2
    assert p.percentile_min_valid==126 and p.contracts_per_leg==1
    assert spec['rules']['universe']==['SPY','QQQ']
    assert len(spec['underlying_sources'])==2
    assert spec['corpus']['version'] and spec['git_commit']


def test_specification_tampering_fails(tmp_path):
    value=json.loads(SPEC.read_text());value['parameters']['vrp_threshold']=0
    path=tmp_path/'spec.json';path.write_text(json.dumps(value))
    with pytest.raises(ValueError,match='checksum'):load_specification(path,ROOT)


def test_runtime_input_mutation_is_detected(tmp_path):
    p=tmp_path/'f';p.write_text('original');pins={p:file_digest(p)}
    guard_unchanged(pins);p.write_text('changed')
    with pytest.raises(ValueError,match='changed'):guard_unchanged(pins)


def test_metrics_reject_inconsistent_returns():
    from types import SimpleNamespace
    r=SimpleNamespace(initial_capital=100,equity_curve=pd.Series([100.,110.]),
        daily_returns=pd.Series([0.,0.]),event_ledger=[],trades=[],total_cost=0,orders=[])
    with pytest.raises(ValueError,match='returns'):reconcile_result(r)

def test_output_cannot_be_legacy_or_overwritten(tmp_path):
    from quantbot.research.phase4b import run_research
    with pytest.raises(ValueError,match='ignored'):
        run_research(ROOT,tmp_path,SPEC,tmp_path,ROOT/'reports/legacy')
    output=tmp_path/'runs/phase4b/already-exists';output.mkdir(parents=True)
    with pytest.raises(FileExistsError):
        run_research(tmp_path,tmp_path,SPEC,tmp_path,output)


def test_lf_checkout_configuration_remains_equivalent(tmp_path):
    import shutil
    (tmp_path/'configs').mkdir()
    cfg=(ROOT/'configs/strategy_configs.json').read_bytes().replace(b'\r\n',b'\n')
    (tmp_path/'configs/strategy_configs.json').write_bytes(cfg)
    shutil.copyfile(ROOT/'uv.lock',tmp_path/'uv.lock')
    load_specification(SPEC,tmp_path)
    value=json.loads(cfg);value['strategies']['S05_implied_vs_realized_vol']['vrp_threshold_vol_points']=0
    (tmp_path/'configs/strategy_configs.json').write_text(json.dumps(value))
    with pytest.raises(ValueError,match='canonical configuration changed'):
        load_specification(SPEC,tmp_path)


def test_strategy_inputs_are_immutable_copies():
    from dataclasses import FrozenInstanceError
    from quantbot.strategies.s05_implied_vs_realized_vol import S05ImpliedVsRealizedVol,S05Parameters
    p=S05Parameters()
    with pytest.raises(FrozenInstanceError):p.vrp_threshold=0
    panel=pd.DataFrame({'signal':[False]},index=pd.to_datetime(['2022-07-05']))
    s=S05ImpliedVsRealizedVol('SPY',panel,p);panel.loc[:,'signal']=True
    assert not s.panel.signal.iloc[0]

def test_reconciliation_does_not_tolerate_ten_cent_ledger_gap():
    from types import SimpleNamespace
    r=SimpleNamespace(initial_capital=100000.,equity_curve=pd.Series([100000.,99999.9]),
        daily_returns=pd.Series([0.,-.000001]),event_ledger=[],trades=[],total_cost=0,orders=[])
    with pytest.raises(ValueError,match='closed ledger'):
        reconcile_result(r)