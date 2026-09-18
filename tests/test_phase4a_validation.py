"""Report correctness and deterministic sampling; no provider/network required."""
import json
from pathlib import Path
import duckdb
import pandas as pd
import pytest
from quantbot.data.storage.provenance import file_digest, json_bytes, seal
from quantbot.options.validation import comparison_stats, stratified_sample, verify_reference, compare_sample
from test_phase4a_analytics import observation


def test_comparison_stats_does_not_substitute_missing_or_zero_denominator():
    s=comparison_stats([(1,2),(None,2),(0,3)])
    assert s['count']==2
    assert s['mean_absolute_difference']==2
    assert s['relative_count']==1
    assert s['mean_relative_difference']==1


def test_sample_is_deterministic_under_row_permutation():
    rows=[]
    for i in range(10):
        rows.append(observation()|{'contract_id':str(i),'strike':100+i/100})
    with duckdb.connect() as con:
        con.register('processed',pd.DataFrame(rows))
        first=stratified_sample(con)
        con.unregister('processed')
        con.register('processed',pd.DataFrame(list(reversed(rows))))
        second=stratified_sample(con)
    assert first['contract_id'].tolist()==second['contract_id'].tolist()
    assert len(first)==3


def test_source_checksum_and_path_escape_are_rejected(tmp_path):
    p=tmp_path/'source.json';p.write_bytes(json_bytes(seal({'value':1})))
    ref=dict(path=p.name,sha256=file_digest(p))
    assert verify_reference(tmp_path,ref)==p
    p.write_text('changed')
    with pytest.raises(ValueError,match='checksum'):
        verify_reference(tmp_path,ref)
    with pytest.raises(ValueError,match='escape'):
        verify_reference(tmp_path,dict(path='../elsewhere',sha256='no'))


def test_report_local_and_vendor_values_are_distinct_and_inputs_explicit():
    row=observation()|{'contract_id':'fixture','exercise_style':'american',
                       'multiplier':100,'event_timestamp':None,'underlying_timestamp':None}
    summary,details=compare_sample(pd.DataFrame([row]),.03,.01)
    assert summary['observations']==1
    assert summary['statuses']=={'ok':1}
    assert summary['strict_contemporaneous_validation_count']==0
    assert summary['unverifiable_historical_input_count']==1
    assert summary['iv_comparison']['count']==1
    assert summary['iv_comparison']['mean_absolute_difference']==pytest.approx(.01,abs=1e-7)
    assert summary['greeks_at_reconstructed_iv']['delta']['count']==0
    assert details[0]['provider_iv']==.21
    assert details[0]['local_iv']==pytest.approx(.2,abs=1e-7)
    assert details[0]['inputs']['risk_free_rate']==.03
