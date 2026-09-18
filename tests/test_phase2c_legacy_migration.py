"""Controlled legacy migration contracts; all fixtures are synthetic."""
from datetime import datetime, timezone, date
import json
from pathlib import Path

import pandas as pd
import pytest

STAMP = datetime(2026, 1, 5, 22, tzinfo=timezone.utc)

def frame():
    return pd.DataFrame([
        dict(date="2022-01-03",underlying="SPY",expiration="2022-01-21",
             strike=470.0,option_type="call",bid=2.0,ask=2.2,mid=2.1,
             volume=12,open_interest=0,implied_volatility=0.2,
             delta=0.5,gamma=0.1,theta=-0.02,vega=0.3,rho=0.01,
             underlying_price=471.0,contract_multiplier=100,
             exercise_style="american",last=2.15,dte=18),
        dict(date="2022-01-04",underlying="SPY",expiration="2022-01-21",
             strike=470.0,option_type="call",bid=0.0,ask=0.2,mid=0.1,
             volume=0,open_interest=0,implied_volatility=float("nan"),
             delta=float("nan"),gamma=0.1,theta=-0.02,vega=0.3,rho=float("nan"),
             underlying_price=469.0,contract_multiplier=100,
             exercise_style="american",last=float("nan"),dte=17),
    ])

def legacy(tmp_path):
    root=tmp_path/"original"
    path=root/"data/options/processed/SPY/2022/2022-01.csv.gz"
    path.parent.mkdir(parents=True)
    frame().to_csv(path,index=False,compression="gzip")
    return root,path

def test_inventory_is_complete_read_only_and_classifies_normalized(tmp_path):
    from quantbot.data.legacy_migration import inventory
    from quantbot.data.storage.provenance import file_digest
    root,p=legacy(tmp_path)
    before=(file_digest(p),p.stat().st_mtime_ns)
    inv=inventory(root)
    item=next(e for e in inv["files"] if e["relative_path"].endswith(".csv.gz"))
    assert item["original_path"]==str(p.resolve())
    assert item["classification"]=="legacy_normalized"
    assert item["row_count"]==2 and item["symbols"]==["SPY"]
    assert item["observed_range"]=={"start":"2022-01-03","end":"2022-01-04"}
    assert item["sha256"]==before[0] and item["bytes"]==p.stat().st_size
    assert (file_digest(p),p.stat().st_mtime_ns)==before

def test_legacy_normalization_preserves_fields_and_changes_only_documented_oi():
    from quantbot.data.legacy_migration import normalize_legacy
    t=normalize_legacy(frame(),imported_at=STAMP)
    rows=t.to_pylist()
    assert len(rows)==2
    assert rows[0]["observation_date"]==date(2022,1,3)
    assert rows[0]["expiration"]==date(2022,1,21)
    assert str(rows[0]["strike"])=="470.000000"
    assert rows[0]["right"]=="call" and rows[0]["underlying"]=="SPY"
    assert rows[0]["bid"]==2 and rows[0]["ask"]==2.2 and rows[0]["last"]==2.15
    assert all(r["open_interest"] is None for r in rows)
    assert rows[0]["multiplier"]==100
    assert "legacy_oi_unreliable" in rows[0]["quality_flags"]
    assert "legacy_contract_terms_unverified" in rows[0]["quality_flags"]
    assert rows[0]["event_timestamp"] is None
    assert "import_receipt_not_provider_retrieval" in rows[0]["quality_flags"]
    assert rows[1]["implied_volatility"] is None
    assert rows[0]["contract_id"]==rows[1]["contract_id"]

def test_quality_counts_duplicates_and_suspicious_quotes_without_deletion():
    from quantbot.data.legacy_migration import audit_frame
    df=pd.concat([frame(),frame().iloc[[0]]],ignore_index=True)
    df.loc[1,"bid"]=3
    q=audit_frame(df,expected_dates=["2022-01-03","2022-01-04","2022-01-05"])
    assert q["rows"]==3 and q["duplicate_excess_rows"]==1
    assert q["crossed_markets"]==1 and q["missing_iv"]==1
    assert q["unavailable_oi"]==3 and q["legacy_oi_zero"]==3
    assert q["missing_greeks"]["delta"]==1
    assert q["gaps"]==["2022-01-05"]
    assert q["ambiguous_or_missing_event_timestamps"]==3
    assert len(df)==3

def test_copy_and_roundtrip_manifest_checksums_and_repeated_migration(tmp_path):
    from quantbot.data.legacy_migration import inventory, migrate_partition
    from quantbot.data.storage import DataStore
    from quantbot.data.storage.provenance import file_digest
    root,p=legacy(tmp_path)
    before=(file_digest(p),p.stat().st_mtime_ns,p.read_bytes())
    inv=inventory(root)
    store=DataStore(tmp_path/"external")
    item=next(e for e in inv["files"] if e["relative_path"].endswith(".csv.gz"))
    result=migrate_partition(store,item,imported_at=STAMP,
                             expected_dates=["2022-01-03","2022-01-04"])
    m=store.root/result["dataset_manifest"]["path"]
    t=store.read_dataset(m)
    assert len(t)==result["reconciliation"]["source_rows"]==2
    assert result["reconciliation"]["all_recoverable_fields_equal"]
    assert result["reconciliation"]["identity_equal"]
    assert result["reconciliation"]["date_coverage_equal"]
    src=store.root/result["source_manifest"]["path"]
    sm=json.loads(src.read_text())
    assert file_digest(src.parent/"payload.bin")==before[0]==sm["payload_sha256"]
    assert sm["kind"]=="legacy_normalized"
    assert store.query(m,"SELECT count(*) AS n, count(open_interest) AS oi FROM observations").to_pylist()==[{"n":2,"oi":0}]
    assert (file_digest(p),p.stat().st_mtime_ns,p.read_bytes())==before
    again=migrate_partition(store,item,imported_at=STAMP,
                             expected_dates=["2022-01-03","2022-01-04"])
    assert result==again

def test_changed_source_refused_before_copy(tmp_path):
    from quantbot.data.legacy_migration import inventory, migrate_partition
    from quantbot.data.storage import DataStore
    root,p=legacy(tmp_path)
    item=inventory(root)["files"][0]
    p.write_bytes(b"changed")
    with pytest.raises(ValueError,match="changed"):
        migrate_partition(DataStore(tmp_path/"external"),item,imported_at=STAMP)
    assert not (tmp_path/"external").exists()

@pytest.mark.parametrize("field,value", [("strike",-1),("bid",float("inf"))])
def test_schema_incompatible_observations_are_flagged_then_fail_not_dropped(field,value):
    from quantbot.data.legacy_migration import normalize_legacy, audit_frame
    df=frame()
    df.loc[0,field]=value
    q=audit_frame(df)
    assert q["rows"]==2
    with pytest.raises(ValueError):
        normalize_legacy(df,imported_at=STAMP)

def test_duplicate_migration_fails_without_deduplicating(tmp_path):
    from quantbot.data.legacy_migration import normalize_legacy
    df=pd.concat([frame(),frame().iloc[[0]]],ignore_index=True)
    with pytest.raises(ValueError,match="duplicate"):
        normalize_legacy(df,imported_at=STAMP)

def test_incomplete_inventory_rejects_unexpected_scale(tmp_path):
    from quantbot.data.legacy_migration import select_partitions
    with pytest.raises(ValueError,match="scale"):
        select_partitions({"files":[dict(relative_path="data/options/processed/SPY/2022/2022-01.csv.gz",
            row_count=20_000_000,bytes=1000,classification="legacy_normalized",symbols=["SPY"])]})

def test_no_hidden_timestamp_or_oi_reconstruction():
    from quantbot.data.legacy_migration import normalize_legacy
    df=frame()
    df.loc[0,"open_interest"]=999
    t=normalize_legacy(df,imported_at=STAMP)
    assert t["open_interest"].null_count==2
    assert t["provider_created_at"].null_count==2

def test_existing_aware_timestamps_survive():
    from quantbot.data.legacy_migration import normalize_legacy
    df=frame()
    df["event_timestamp"]=["2022-01-03T21:00:00Z","2022-01-04T21:00:00Z"]
    t=normalize_legacy(df,imported_at=STAMP)
    assert t["event_timestamp"][0].as_py().hour==21

def test_ambiguous_timestamp_rejected_not_silently_assumed_utc():
    from quantbot.data.legacy_migration import normalize_legacy
    df=frame()
    df["event_timestamp"]=["2022-01-03 16:00:00","2022-01-04 16:00:00"]
    with pytest.raises(ValueError,match="timezone"):
        normalize_legacy(df,imported_at=STAMP)


def test_generated_option_reports_are_not_promoted_to_source_corpus(tmp_path):
    from quantbot.data.legacy_migration import inventory,select_partitions
    root,p=legacy(tmp_path)
    report=root/"reports/options/chain.csv"
    report.parent.mkdir(parents=True)
    frame().to_csv(report,index=False)
    inv=inventory(root)
    entry=next(e for e in inv["files"] if e["relative_path"]=="reports/options/chain.csv")
    assert entry["classification"]=="generated_artifact"
    assert len(select_partitions(inv))==1

def test_migration_parses_verified_copy_bytes_not_a_second_original_read(tmp_path,monkeypatch):
    from quantbot.data.legacy_migration import inventory,migrate_partition
    from quantbot.data.storage import DataStore
    import io
    root,p=legacy(tmp_path)
    entry=inventory(root)["files"][0]
    original_read=pd.read_csv
    def checked_read(source,*args,**kwargs):
        assert isinstance(source,io.BytesIO)
        return original_read(source,*args,**kwargs)
    monkeypatch.setattr(pd,"read_csv",checked_read)
    migrate_partition(DataStore(tmp_path/"external"),entry,imported_at=STAMP)

def test_monthly_variants_stay_separate_and_duplicates_are_not_hidden(tmp_path):
    from quantbot.data.legacy_migration import inventory,select_partitions
    root,p=legacy(tmp_path)
    daily=root/"data/options/raw/thetadata/SPY/2022/2022-01"
    daily.mkdir(parents=True)
    frame().iloc[[0]].to_csv(daily/"2022-01-03.csv.gz",index=False,compression="gzip")
    frame().iloc[[0]].to_csv(daily/"2022-01-03.greeks.csv.gz",index=False,compression="gzip")
    parts=select_partitions(inventory(root))
    assert {g["series"] for g in parts}=={"processed","daily_eod","daily_greeks"}
    assert sum(e["row_count"] for g in parts for e in g["files"])==4

def test_scoped_exchange_calendar():
    from quantbot.data.legacy_migration import expected_sessions
    assert sum(len(expected_sessions(2022,m)) for m in range(1,13))==251
    assert len(expected_sessions(2023,1))==20
    assert "2022-06-20" not in expected_sessions(2022,6)
    assert "2022-11-25" in expected_sessions(2022,11)
    with pytest.raises(ValueError,match="calendar"):
        expected_sessions(2024,1)


def test_corpus_manifest_reports_and_duckdb_queries_reconcile(tmp_path):
    from quantbot.data.legacy_corpus import save_inventory, migrate_corpus
    from quantbot.data.storage import DataStore
    from quantbot.data.storage.provenance import file_digest,load_sealed
    root,p=legacy(tmp_path)
    store=DataStore(tmp_path/"external")
    inv_path=save_inventory(root,store.root/"audits/inventory")
    corpus=migrate_corpus(store,inv_path)
    meta=load_sealed(corpus)
    assert meta["total_versioned_rows"]==2
    assert meta["source_file_count"]==1 and len(meta["partitions"])==1
    assert meta["normalization_version"]=="legacy-options-v1"
    assert meta["original_files_verified_unchanged"] is True
    assert meta["queries"]["processed_count"]==2
    assert meta["queries"]["distinct_identity_date_count"]==2
    assert meta["queries"]["full_chain_rows"]==1
    assert meta["queries"]["time_series_rows"]==2
    assert meta["queries"]["oi_nonnull"]==0
    assert meta["queries"]["missing_iv"]==1
    assert file_digest(store.root/meta["inventory"]["path"])==meta["inventory"]["sha256"]
    assert (corpus.parent/"quality.md").exists()
    assert migrate_corpus(store,inv_path)==corpus

def test_inventory_reports_keep_original_paths_only_in_external_private_file(tmp_path):
    from quantbot.data.legacy_corpus import save_inventory
    root,p=legacy(tmp_path)
    out=tmp_path/"external/audits"
    private=save_inventory(root,out)
    assert str(p.resolve()) in json.loads(private.read_text())["files"][0]["original_path"]
    public=json.loads(private.with_name("inventory.json").read_text())
    assert "original_path" not in public["files"][0]
    assert (out/"inventory.md").is_file()


def test_duplicate_occurrences_are_preserved_in_distinct_monthly_snapshots(tmp_path):
    from quantbot.data.legacy_migration import inventory,migrate_partition
    from quantbot.data.storage import DataStore
    from quantbot.data.storage.provenance import load_sealed
    root,p=legacy(tmp_path)
    df=pd.concat([frame(),frame().iloc[[0]]],ignore_index=True)
    df.loc[2,"bid"]=1.9
    df.to_csv(p,index=False,compression="gzip")
    item=inventory(root)["files"][0]
    store=DataStore(tmp_path/"external")
    result=migrate_partition(store,item,imported_at=STAMP)
    assert len(result["dataset_manifests"])==2
    back=[store.read_dataset(store.root/r["path"]) for r in result["dataset_manifests"]]
    assert sum(len(t) for t in back)==3
    bids=[v for t in back for v in t["bid"].to_pylist()]
    assert sorted(bids)==[0.0,1.9,2.0]
    q=load_sealed(store.root/result["quality_report"]["path"])
    assert q["duplicate_excess_rows"]==1 and q["exact_duplicate_excess_rows"]==0
    assert result["reconciliation"]["source_rows"]==result["reconciliation"]["output_rows"]==3
    assert result["reconciliation"]["all_recoverable_fields_equal"]
    assert all(load_sealed(store.root/r["path"])["normalization_parameters"]["duplicate_policy"]
               =="preserve occurrence in separate snapshot" for r in result["dataset_manifests"])


def test_corpus_separates_daily_variants_and_preserves_overlap(tmp_path):
    from quantbot.data.legacy_corpus import save_inventory,migrate_corpus
    from quantbot.data.storage import DataStore
    from quantbot.data.storage.provenance import load_sealed
    root,p=legacy(tmp_path)
    daily=root/"data/options/raw/thetadata/SPY/2022/2022-01"
    daily.mkdir(parents=True)
    for suffix in (".csv.gz",".greeks.csv.gz"):
        frame().iloc[[0]].to_csv(daily/("2022-01-03"+suffix),index=False,compression="gzip")
    store=DataStore(tmp_path/"x")
    inv=save_inventory(root,store.root/"audits/i")
    m=load_sealed(migrate_corpus(store,inv))
    assert m["total_versioned_rows"]==4 and m["unique_observation_keys"]==2
    assert m["queries"]["variant_overlap"]["daily_eod"]=={
        "records":1,"absent_from_processed":0,"different_bid_ask":0}
    assert m["quality_by_series"]["processed"]["rows"]==2
    assert m["quality_by_series"]["daily_eod"]["rows"]==1
    assert m["source_file_count"]==3
