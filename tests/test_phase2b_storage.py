"""Phase 2B storage/provenance contracts; synthetic data only."""
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import subprocess

import pandas as pd
import pyarrow as pa
import pytest

RETRIEVED = datetime(2026, 1, 5, 22, tzinfo=timezone.utc)

def option_rows():
    return [
        dict(symbol="SPY", expiration="2026-01-16", strike=500, right="call",
             date="2026-01-05", timestamp="2026-01-05T16:00:00-05:00",
             created="2026-01-05T21:01:00Z", last_trade="2026-01-02T15:00:00-05:00",
             bid=2.0, ask=2.2, bid_size=4, ask_size=5, volume=7,
             delta=0.5, implied_vol=0.2, underlying_price=501.0, iv_error=0.001),
        dict(symbol="QQQ", expiration="2026-01-16", strike=500, right="call",
             date="2026-01-05", timestamp="2026-01-05T21:00:00Z",
             created="2026-01-05T21:02:00Z", bid=3.0, ask=3.2,
             open_interest=0, volume=8),
    ]

def analytical():
    from quantbot.data.options_providers.theta_analytical import normalize_payload
    return normalize_payload({"response": option_rows()}, retrieved_at=RETRIEVED,
                             source_timezone="America/New_York")

def source(store):
    return store.preserve_source(
        json.dumps({"response": option_rows()}).encode(), provider="thetadata",
        dataset="options_eod", kind="fixture_payload", retrieved_at=RETRIEVED,
        request={"endpoint": "/v3/option/history/eod", "symbols": ["SPY", "QQQ"],
                 "start_date": "2026-01-05", "end_date": "2026-01-06"},
    )

def dataset(store, **kwargs):
    return store.write_dataset(analytical(), schema_name="options-v1",
        provider="thetadata", dataset="options_eod", sources=[source(store)],
        requested_start=date(2026, 1, 5), requested_end=date(2026, 1, 6),
        normalization_version="theta-v3-1", **kwargs)

def test_legacy_date_discovery(tmp_path):
    from quantbot.data import options_cache as oc
    oc.write_raw(pd.DataFrame({"x": [1]}), "thetadata", "SPY", "2022-01-03", root=tmp_path)
    base = oc.raw_path("thetadata", "SPY", "2022-01-04", root=tmp_path)
    base.parent.mkdir(parents=True, exist_ok=True)
    base.with_name("2022-01-04.greeks.csv.gz").touch()
    base.with_name("junk.csv.gz").touch()
    assert oc.list_raw_dates("thetadata", "SPY", root=tmp_path) == [
        pd.Timestamp("2022-01-03"), pd.Timestamp("2022-01-04")]

@pytest.mark.parametrize("normalizer", ["normalize_thetadata_eod",
    "normalize_thetadata_v3_option_eod", "normalize_thetadata_v3_greeks_eod"])
def test_existing_theta_oi_missing_is_null(normalizer):
    from quantbot.data.options_providers import thetadata as td
    rows = [option_rows()[0]]
    kwargs = (dict(snapshot_date="2026-01-05", spot=501)
              if normalizer == "normalize_thetadata_eod" else dict(spot_by_date={}))
    assert pd.isna(getattr(td, normalizer)(rows, underlying="SPY", **kwargs)
                   .iloc[0]["open_interest"])

def test_identity_nulls_and_separate_timestamps():
    t = analytical()
    rows = t.to_pylist()
    assert t.schema.field("strike").type == pa.decimal128(20, 6)
    assert {r["underlying"] for r in rows} == {"SPY", "QQQ"}
    a = next(r for r in rows if r["underlying"] == "SPY")
    assert a["observation_date"] == date(2026, 1, 5)
    assert a["trade_timestamp"].date() == date(2026, 1, 2)
    assert a["event_timestamp"] != a["provider_created_at"] != a["retrieved_at"]
    assert a["open_interest"] is None
    assert a["multiplier"] is None  # provider did not supply it
    assert a["bid_size"] == 4 and a["ask_size"] == 5
    assert a["iv_error"] == 0.001
    assert a["contract_id"] != rows[0 if rows[0] != a else 1]["contract_id"]

@pytest.mark.parametrize("change", [
    {"symbol": ""}, {"right": "nonsense"}, {"strike": -1},
    {"strike": "500"}, {"volume": 1.5}, {"bid": float("inf")},
    {"expiration": "not-a-date"}, {"multiplier": 0},
])
def test_invalid_options_rejected(change):
    from quantbot.data.options_providers.theta_analytical import normalize_payload
    rows = [option_rows()[0] | change]
    with pytest.raises((ValueError, TypeError)):
        normalize_payload(rows, retrieved_at=RETRIEVED, source_timezone="America/New_York")

def test_ambiguous_timestamp_requires_timezone_and_date():
    from quantbot.data.options_providers.theta_analytical import normalize_payload
    r = option_rows()[0] | {"timestamp": "2026-01-05T16:00:00"}
    with pytest.raises(ValueError, match="timezone"):
        normalize_payload([r], retrieved_at=RETRIEVED)
    r.pop("date")
    r.pop("timestamp")
    with pytest.raises(ValueError, match="observation"):
        normalize_payload([r], retrieved_at=RETRIEVED, source_timezone="America/New_York")

def test_large_strike_never_heuristically_divided():
    from quantbot.data.options_providers.theta_analytical import normalize_payload
    t = normalize_payload([option_rows()[0] | {"strike": 15000}],
                          retrieved_at=RETRIEVED, source_timezone="America/New_York")
    assert t["strike"][0].as_py() == Decimal("15000")

def test_crossed_quote_is_flagged_not_repaired():
    from quantbot.data.options_providers.theta_analytical import normalize_payload
    t = normalize_payload([option_rows()[0] | {"bid": 3}], retrieved_at=RETRIEVED,
                          source_timezone="America/New_York")
    assert t["bid"][0].as_py() == 3
    assert "crossed_quote" in t["quality_flags"][0].as_py()

def test_unknown_fields_are_not_silently_dropped():
    from quantbot.data.storage.schemas import normalized_table
    rows = analytical().to_pylist()
    rows[0]["secret_new_column"] = 1
    with pytest.raises(ValueError, match="unknown"):
        normalized_table(rows, "options-v1")

def test_duplicate_observation_rejected():
    from quantbot.data.storage.schemas import normalized_table
    rows = analytical().to_pylist()
    with pytest.raises(ValueError, match="duplicate"):
        normalized_table(rows + rows, "options-v1")

def test_equity_basis_separate_and_validated():
    from quantbot.data.storage.schemas import normalized_table
    r = dict(symbol="SPY", observation_date=date(2026,1,5),
        retrieved_at=RETRIEVED, raw_open=100.0, raw_high=103.0, raw_low=99.0,
        raw_close=102.0, adjusted_close=51.0, adjustment_factor=0.5,
        adjustment_convention="adjusted_over_raw", volume=100,
        quality_flags=[])
    t = normalized_table([r], "equities-v1")
    assert t["raw_close"][0].as_py() == 102
    assert t["adjusted_close"][0].as_py() == 51
    assert t["adjusted_open"][0].as_py() is None
    with pytest.raises(ValueError, match="adjust"):
        normalized_table([r | {"adjustment_factor": 0.6}], "equities-v1")
    with pytest.raises(ValueError, match="unknown"):
        normalized_table([r | {"close": 51}], "equities-v1")

def test_roundtrip_manifests_duckdb_and_determinism(tmp_path):
    from quantbot.data.storage import DataStore
    store = DataStore(tmp_path)
    m = dataset(store)
    info = json.loads(m.read_text())
    assert info["row_count"] == 2 and info["file_count"] == 1
    assert info["symbols"] == ["QQQ", "SPY"]
    assert info["requested_range"] == {"start": "2026-01-05", "end": "2026-01-06"}
    assert info["observed_range"] == {"start": "2026-01-05", "end": "2026-01-05"}
    assert info["quality"]["missing_fields"]["open_interest"] == 1
    assert info["quality"]["missing_fields"]["multiplier"] == 2
    assert info["code"]["commit"] and info["code"]["lock_sha256"]
    assert store.read_dataset(m).equals(analytical())
    q = store.query(m, "SELECT underlying, open_interest FROM observations ORDER BY underlying")
    assert q.to_pylist() == [{"underlying":"QQQ", "open_interest":0},
                             {"underlying":"SPY", "open_interest":None}]
    assert dataset(store) == m
    other = DataStore(tmp_path / "second")
    n = dataset(other)
    other_info = json.loads(n.read_text())
    assert info["files"] == other_info["files"]
    assert info["dataset_version"] == other_info["dataset_version"]
    for f in info["files"]:
        assert hashlib.sha256((m.parent/f["path"]).read_bytes()).hexdigest() == f["sha256"]

def test_tampering_detected(tmp_path):
    from quantbot.data.storage import DataStore
    store = DataStore(tmp_path)
    m = dataset(store)
    info = json.loads(m.read_text())
    file = m.parent/info["files"][0]["path"]
    file.write_bytes(file.read_bytes()+b"corrupt")
    with pytest.raises(ValueError, match="checksum"):
        store.read_dataset(m)

def test_manifest_tampering_detected(tmp_path):
    from quantbot.data.storage import DataStore
    store = DataStore(tmp_path)
    m = dataset(store)
    info = json.loads(m.read_text())
    info["row_count"] = 99
    m.write_text(json.dumps(info))
    with pytest.raises(ValueError, match="manifest"):
        store.read_dataset(m)

def test_source_semantics_and_immutability(tmp_path):
    from quantbot.data.storage import DataStore
    store = DataStore(tmp_path)
    p = source(store)
    meta = json.loads(p.read_text())
    assert meta["kind"] == "fixture_payload"
    assert json.loads((p.parent/"payload.bin").read_bytes()) == {"response":option_rows()}
    legacy = store.preserve_source(b"already,normalized\n1,2\n",
        provider="legacy", dataset="options", kind="legacy_normalized",
        retrieved_at=RETRIEVED, request={})
    assert "imports" in legacy.parts and "raw" not in legacy.parts
    assert source(store) == p
    (p.parent/"payload.bin").write_bytes(b"changed")
    with pytest.raises(ValueError, match="checksum"):
        store.verify_source(p)

@pytest.mark.parametrize("request_params", [
    {"api_key":"do-not-store"}, {"nested":{"authorization":"do-not-store"}},
    {"endpoint":"https://example.test/?token=do-not-store"},
])
def test_credentials_rejected_before_writes(tmp_path, request_params):
    from quantbot.data.storage import DataStore
    with pytest.raises(ValueError):
        DataStore(tmp_path).preserve_source(b"{}", provider="fixture", dataset="x",
            kind="fixture_payload", retrieved_at=RETRIEVED, request=request_params)
    assert list(tmp_path.iterdir()) == []

def test_source_payload_credentials_rejected(tmp_path):
    from quantbot.data.storage import DataStore
    with pytest.raises(ValueError, match="credential"):
        DataStore(tmp_path).preserve_source(b'{"api_key":"do-not-store"}',
            provider="fixture", dataset="x", kind="fixture_payload",
            retrieved_at=RETRIEVED, request={})

def test_request_range_and_unverified_sources_rejected(tmp_path):
    from quantbot.data.storage import DataStore
    store = DataStore(tmp_path)
    with pytest.raises(ValueError, match="range"):
        store.write_dataset(analytical(), schema_name="options-v1",
            provider="thetadata", dataset="options_eod", sources=[source(store)],
            requested_start=date(2026,1,6), requested_end=date(2026,1,7),
            normalization_version="theta-v3-1")
    with pytest.raises(ValueError, match="source"):
        store.write_dataset(analytical(), schema_name="options-v1",
            provider="thetadata", dataset="options_eod", sources=[],
            requested_start=date(2026,1,5), requested_end=date(2026,1,6),
            normalization_version="theta-v3-1")

def test_run_manifest_references_and_no_overwrite(tmp_path):
    from quantbot.data.storage import DataStore
    store=DataStore(tmp_path)
    m=dataset(store)
    run=store.write_run("sample-1", strategy="storage-fixture", config={"threshold":0.2},
        datasets=[m], outputs=["reports/example.json"], timestamp=RETRIEVED,
        code_version="sample-v1")
    r=json.loads(run.read_text())
    assert r["datasets"][0]["manifest_sha256"] == hashlib.sha256(m.read_bytes()).hexdigest()
    assert r["config_sha256"] and r["code"]["commit"]
    with pytest.raises(FileExistsError):
        store.write_run("sample-1", strategy="storage-fixture", config={},
            datasets=[m], outputs=[], timestamp=RETRIEVED, code_version="sample-v1")

def test_external_root_configuration_and_guardrails(tmp_path, monkeypatch):
    from quantbot.data.storage import DataStore, data_root
    monkeypatch.setenv("QUANTBOT_DATA_ROOT", str(tmp_path/"external"))
    assert data_root() == tmp_path/"external"
    with pytest.raises(ValueError):
        DataStore(tmp_path/"OneDrive"/"data")
    with pytest.raises(ValueError):
        DataStore(Path(__file__).resolve().parents[1]/"data")
    with pytest.raises(ValueError):
        DataStore("relative-data")
    with pytest.raises(ValueError):
        DataStore(tmp_path).preserve_source(b"{}", provider="../escape",
            dataset="x", kind="fixture_payload", retrieved_at=RETRIEVED, request={})

def test_git_ignores_generated_storage_but_tracks_source():
    root=Path(__file__).resolve().parents[1]
    paths=["data/raw/sample.json","local_data/normalized/x.parquet",
           "sample.duckdb","sample.duckdb.wal","runs/sample/manifest.json",
           "src/quantbot/data/storage/schemas.py"]
    p=subprocess.run(["git","-c",f"safe.directory={root.as_posix()}",
        "check-ignore","--no-index","--stdin","-z"],input=("\0".join(paths)+"\0").encode(),
        cwd=root,capture_output=True)
    assert set(p.stdout.decode().rstrip("\0").split("\0")) == set(paths[:-1])


def test_theta_ingestion_keeps_source_and_normalization_policy(tmp_path):
    from quantbot.data.storage import DataStore
    from quantbot.data.options_providers.theta_analytical import ingest_payload
    store = DataStore(tmp_path)
    raw = json.dumps({"response": option_rows()}).encode()
    m = ingest_payload(store, raw, retrieved_at=RETRIEVED,
        request={"endpoint":"/v3/option/history/eod","symbols":["SPY","QQQ"]},
        requested_start=date(2026,1,5), requested_end=date(2026,1,6),
        source_timezone="America/New_York", kind="fixture_payload")
    meta = json.loads(m.read_text())
    assert meta["normalization_parameters"]["source_timezone"] == "America/New_York"
    assert meta["normalization_parameters"]["observation_date_policy"] == "explicit-or-event"
    assert store.read_dataset(m).equals(analytical())

def test_nested_contract_conflict_and_timezone_date_mismatch():
    from quantbot.data.options_providers.theta_analytical import normalize_payload
    with pytest.raises(ValueError, match="conflict"):
        normalize_payload({"response":[{"contract":{"symbol":"QQQ"},
            "data":[option_rows()[0]]}]}, retrieved_at=RETRIEVED)
    bad = option_rows()[0] | {"date":"2026-01-04"}
    with pytest.raises(ValueError, match="date"):
        normalize_payload([bad], retrieved_at=RETRIEVED, source_timezone="America/New_York")

def test_source_change_changes_version_and_provenance(tmp_path):
    from quantbot.data.storage import DataStore
    store=DataStore(tmp_path)
    m=dataset(store)
    s=source(store)
    (s.parent/"payload.bin").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="checksum"):
        store.read_dataset(m)

def test_query_rejects_mutation_and_external_read(tmp_path):
    from quantbot.data.storage import DataStore
    import duckdb
    store=DataStore(tmp_path)
    m=dataset(store)
    with pytest.raises(ValueError, match="SELECT"):
        store.query(m, "CREATE TABLE x(a INT)")
    with pytest.raises((duckdb.Error, ValueError)):
        store.query(m, "SELECT * FROM read_csv('not-allowed.csv')")

def test_theta_capture_is_opt_in_and_preserves_exact_response(tmp_path, monkeypatch):
    from quantbot.data.storage import DataStore
    from quantbot.data.options_providers import thetadata as td
    raw=json.dumps({"response":option_rows()}, indent=2).encode()
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return raw
    monkeypatch.setattr(td, "urlopen", lambda *args,**kwargs: Response())
    loader=td.ThetaDataLoader(dry_run=False, rate_limit_seconds=0,
                              source_store=DataStore(tmp_path))
    assert loader._get_json("option/history/eod", {"symbol":"SPY","format":"json"}) == json.loads(raw)
    assert len(loader.source_manifests) == 1
    path=loader.source_manifests[0]
    meta=json.loads(path.read_text())
    assert meta["kind"] == "provider_payload"
    assert meta["request"]["endpoint"] == "/v3/option/history/eod"
    assert (path.parent/"payload.bin").read_bytes() == raw
    assert meta["retrieved_at"]

def test_equities_parquet_and_duckdb(tmp_path):
    from quantbot.data.storage import DataStore
    from quantbot.data.storage.schemas import normalized_table
    store=DataStore(tmp_path)
    t=normalized_table([dict(symbol="SPY",observation_date=date(2026,1,5),
        retrieved_at=RETRIEVED,raw_close=100.0,adjusted_close=50.0,
        adjustment_factor=0.5,adjustment_convention="adjusted_over_raw")], "equities-v1")
    m=store.write_dataset(t, schema_name="equities-v1", provider="thetadata",
        dataset="equities_eod",sources=[source(store)],requested_start=date(2026,1,5),
        requested_end=date(2026,1,5),normalization_version="fixture-v1")
    assert store.read_dataset(m).equals(t)
    assert store.query(m, "SELECT raw_close, adjusted_close FROM observations").to_pylist() == [
        {"raw_close":100.0,"adjusted_close":50.0}]

def test_file_sharding_and_retrieval_timestamp_validation(tmp_path):
    from quantbot.data.storage import DataStore
    with pytest.raises(ValueError, match="tiny"):
        dataset(DataStore(tmp_path), max_rows_per_file=1)
    from quantbot.data.storage.schemas import normalized_table
    rows=analytical().to_pylist()
    rows[0]["retrieved_at"]=datetime(2026,1,5)
    with pytest.raises(ValueError, match="timezone"):
        normalized_table(rows, "options-v1")


def test_nonidentity_nulls_shuffle_and_nan_do_not_change_parquet(tmp_path):
    from quantbot.data.storage import DataStore
    from quantbot.data.storage.schemas import normalized_table
    store=DataStore(tmp_path)
    t=analytical()
    reversed_table=normalized_table(list(reversed(t.to_pylist())), "options-v1")
    assert reversed_table.equals(t)
    m=dataset(store)
    same=store.write_dataset(reversed_table, schema_name="options-v1",
        provider="thetadata",dataset="options_eod",sources=[source(store)],
        requested_start=date(2026,1,5),requested_end=date(2026,1,6),
        normalization_version="theta-v3-1")
    assert same == m

def test_source_retrieval_and_table_retrieval_must_match(tmp_path):
    from quantbot.data.storage import DataStore
    from quantbot.data.storage.schemas import normalized_table
    store=DataStore(tmp_path)
    rows=analytical().to_pylist()
    rows[0]["retrieved_at"]=datetime(2026,1,6,22,tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="retrieval"):
        store.write_dataset(normalized_table(rows,"options-v1"),
            schema_name="options-v1",provider="thetadata",dataset="options_eod",
            sources=[source(store)],requested_start=date(2026,1,5),
            requested_end=date(2026,1,6),normalization_version="theta-v3-1")

def test_source_capture_failure_leaves_no_published_dataset(tmp_path):
    from quantbot.data.storage import DataStore
    from quantbot.data.options_providers.theta_analytical import ingest_payload
    store=DataStore(tmp_path)
    raw=json.dumps({"response":[option_rows()[0] | {"right":"bad"}]}).encode()
    with pytest.raises(ValueError):
        ingest_payload(store, raw, retrieved_at=RETRIEVED, request={},
            requested_start=date(2026,1,5),requested_end=date(2026,1,6),
            source_timezone="America/New_York",kind="fixture_payload")
    assert len(list(tmp_path.rglob("source.json"))) == 1
    assert list(tmp_path.rglob("*.parquet")) == []

def test_normalized_equity_adjustment_convention_required():
    from quantbot.data.storage.schemas import normalized_table
    with pytest.raises(ValueError, match="adjustment"):
        normalized_table([dict(symbol="SPY",observation_date=date(2026,1,5),
            retrieved_at=RETRIEVED, raw_close=100, adjusted_close=50)], "equities-v1")
