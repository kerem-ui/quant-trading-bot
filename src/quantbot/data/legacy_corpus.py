"""Inventory-first corpus orchestration; generated artifacts remain external."""
from __future__ import annotations
from collections import Counter, defaultdict
from datetime import datetime
import io
import json
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

from .legacy_inventory import inventory
from .legacy_migration import (NORMALIZATION_VERSION, _ref, expected_sessions,
                               migrate_partition, select_partitions)
from .storage import DataStore
from .storage.provenance import code_revision, digest, file_digest, json_bytes, load_sealed, seal

def save_inventory(root: Path, output: Path) -> Path:
    """Persist complete read-only inventory before any legacy source is copied."""
    output=Path(output)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError("inventory destination must be new")
    inv=inventory(root)
    output.mkdir(parents=True,exist_ok=True)
    portable={**inv,"files":[{k:v for k,v in e.items() if k!="original_path"} for e in inv["files"]]}
    with (output/"inventory.private.json").open("xb") as handle:
        handle.write(json_bytes(inv))
    with (output/"inventory.json").open("xb") as handle:
        handle.write(json_bytes(seal(portable)))
    lines=["# Legacy corpus inventory","",f"Files: {inv['file_count']}; bytes: {inv['bytes']}.",
           "", "Absolute source locations are recorded only in inventory.private.json.",
           "", "| Relative source | Classification | Bytes | Rows | Coverage | SHA-256 |",
           "|---|---|---:|---:|---|---|"]
    for e in inv["files"]:
        lines.append(f"| {e['relative_path']} | {e['classification']} | {e['bytes']} | "
                     f"{e['row_count']} | {e['observed_range']} | {e['sha256']} |")
    with (output/"inventory.md").open("x",encoding="utf-8") as handle:
        handle.write("\n".join(lines)+"\n")
    return output/"inventory.private.json"

def _series_quality(store, results):
    summaries={}
    scalar=("rows","exact_duplicate_excess_rows","duplicate_excess_rows","duplicate_involved_rows","missing_bid","missing_ask",
            "crossed_markets","zero_bids","negative_quotes","missing_iv","unavailable_oi",
            "legacy_oi_zero","legacy_oi_nonzero","missing_underlying_price",
            "ambiguous_or_missing_event_timestamps","inconsistent_contract_identities")
    for series in sorted({p["series"] for p in results}):
        selected=[p for p in results if p["series"]==series]
        qualities=[load_sealed(store.root/p["quality_report"]["path"]) for p in selected]
        summary={k:sum(q[k] for q in qualities) for k in scalar}
        for key in ("missing_greeks","nonfinite_numeric_fields","missing_numeric_fields","dte_distribution","rights"):
            counts=Counter()
            for q in qualities: counts.update(q[key])
            summary[key]=dict(counts)
        dates=sorted({d for q in qualities for d in q["dates"]})
        summary.update(unique_trading_dates=len(dates),earliest_date=min(dates),latest_date=max(dates),
            expirations=sorted({d for q in qualities for d in q["expirations"]}),
            gaps={p["symbol"]+"-"+p["month"]:q["gaps"] for p,q in zip(selected,qualities)},
            strike_min=min(q["strike_min"] for q in qualities),
            strike_max=max(q["strike_max"] for q in qualities),
            coverage_by_symbol={sym:dict(
                rows=sum(q["rows"] for p,q in zip(selected,qualities) if p["symbol"]==sym),
                dates=sorted({d for p,q in zip(selected,qualities) if p["symbol"]==sym for d in q["dates"]}))
                for sym in sorted({p["symbol"] for p in selected})})
        summaries[series]=summary
    return summaries

def _queries(store: DataStore, results: list[dict]):
    """Run analytical checks against verified Parquet, preserving full results."""
    paths=defaultdict(list)
    for result in results:
        for manifest_ref in result["dataset_manifests"]:
            m=store.root/manifest_ref["path"]
            if file_digest(m)!=manifest_ref["sha256"]:
                raise ValueError("dataset manifest changed")
            meta=load_sealed(m)
            for ref in meta["files"]:
                p=store._inside(m.parent/ref["path"])
                if file_digest(p)!=ref["sha256"]:
                    raise ValueError("dataset checksum mismatch")
                paths[result["series"]].append(str(p))
    with duckdb.connect(":memory:") as con:
        for series, files in paths.items():
            con.read_parquet(sorted(files)).create_view(series)
        union=" UNION ALL ".join(f"SELECT * FROM {s}" for s in sorted(paths))
        con.sql(union).create_view("all_versions")
        summary=dict(
            processed_count=con.sql("SELECT count(*) FROM processed").fetchone()[0],
            total_versioned_records=con.sql("SELECT count(*) FROM all_versions").fetchone()[0],
            distinct_identity_date_count=con.sql("""SELECT count(*) FROM (
              SELECT DISTINCT underlying, observation_date, expiration, strike, "right" FROM all_versions)""").fetchone()[0],
            oi_nonnull=con.sql("SELECT count(open_interest) FROM all_versions").fetchone()[0],
            missing_iv=con.sql("SELECT count(*) FROM processed WHERE implied_volatility IS NULL").fetchone()[0])
        day=con.sql("SELECT min(observation_date) FROM processed WHERE underlying='SPY'").fetchone()[0]
        if day is None:
            raise ValueError("SPY demonstration requires a processed SPY partition")
        chain=con.sql(f"SELECT * FROM processed WHERE underlying='SPY' AND observation_date=DATE '{day}' ORDER BY expiration,strike,\"right\"").to_arrow_table()
        chosen=con.sql(f"""SELECT expiration,strike,\"right\" FROM processed
            WHERE underlying='SPY' AND observation_date=DATE '{day}' AND \"right\"='call'
            ORDER BY abs(strike-underlying_price),expiration LIMIT 1""").fetchone()
        exp,strike,right=chosen
        history=con.sql(f"""SELECT * FROM processed WHERE underlying='SPY'
            AND expiration=DATE '{exp}' AND strike={strike} AND \"right\"='{right}'
            ORDER BY observation_date""").to_arrow_table()
        atm=con.sql(f"""SELECT * FROM processed WHERE underlying='SPY'
            AND observation_date=DATE '{day}' AND abs(strike-underlying_price)<=underlying_price*0.01
            ORDER BY expiration,strike,\"right\"""").to_arrow_table()
        coverage=con.sql("""SELECT underlying,observation_date,expiration,count(*) AS rows
            FROM processed GROUP BY ALL ORDER BY underlying,observation_date,expiration""").to_arrow_table()
        missing=con.sql("""SELECT underlying,count(*) AS rows,
            count(*) FILTER(WHERE implied_volatility IS NULL) AS missing_iv
            FROM processed GROUP BY underlying ORDER BY underlying""").to_arrow_table()
        summary.update(full_chain_date=str(day),full_chain_rows=len(chain),time_series_rows=len(history),
            time_series_contract=dict(underlying="SPY",expiration=str(exp),strike=str(strike),right=right),
            near_atm_rows=len(atm),date_expiration_coverage_rows=len(coverage),
            missing_iv_by_symbol=missing.to_pylist())
        artifacts={}
        for name,table in (("full_spy_chain",chain),("contract_time_series",history),
                           ("near_atm",atm),("date_expiration_coverage",coverage),("missing_iv",missing)):
            sink=io.BytesIO()
            pq.write_table(table,sink,compression="zstd")
            artifacts[name+".parquet"]=sink.getvalue()
        # Measure overlap without silently merging versions or privileging a quote.
        overlap={}
        for s in ("daily_eod","daily_greeks"):
            if s not in paths: continue
            overlap[s]=con.sql(f"""SELECT count(*) AS records,
                count(*) FILTER(WHERE p.contract_id IS NULL) AS absent_from_processed,
                count(*) FILTER(WHERE p.contract_id IS NOT NULL AND
                    (r.bid IS DISTINCT FROM p.bid OR r.ask IS DISTINCT FROM p.ask)) AS different_bid_ask
                FROM {s} r LEFT JOIN processed p USING(underlying,observation_date,expiration,strike,\"right\")
            """).to_arrow_table().to_pylist()[0]
        summary["variant_overlap"]=overlap
        return summary,artifacts

def migrate_corpus(store: DataStore, inventory_path: Path) -> Path:
    """Migrate bounded real corpus by version/underlying/month, then verify originals."""
    inventory_path=Path(inventory_path)
    inv=json.loads(inventory_path.read_text(encoding="utf-8"))
    portable=inventory_path.with_name("inventory.json")
    portable_inv=load_sealed(portable)
    current_portable={**inv,"files":[{k:v for k,v in e.items() if k!="original_path"} for e in inv["files"]]}
    if digest(json_bytes(current_portable))!=portable_inv["manifest_sha256"]:
        raise ValueError("private and portable inventories disagree")
    partitions=select_partitions(inv)
    if not partitions: raise ValueError("no bounded source corpus")
    stamp=datetime.fromisoformat(inv["created_at"])
    results=[]
    for i,partition in enumerate(partitions,1):
        print(f"[{i}/{len(partitions)}] {partition['series']} {partition['symbol']} "
              f"{partition['year']}-{partition['month']:02d}: "
              f"{sum(e['row_count'] for e in partition['files'])} rows",flush=True)
        results.append(migrate_partition(store,partition,imported_at=stamp,
            expected_dates=expected_sessions(partition["year"],partition["month"])))
    query_summary,artifacts=_queries(store,results)
    quality=_series_quality(store,results)
    # This verifies the entire inventory, not only migrated options inputs.
    for e in inv["files"]:
        p=Path(e["original_path"])
        if not p.is_file() or file_digest(p)!=e["sha256"] or p.stat().st_mtime_ns!=e["mtime_ns"]:
            raise ValueError("inventoried original changed; corpus cannot be certified")
    expected=sum(e["row_count"] for g in partitions for e in g["files"])
    if query_summary["total_versioned_records"]!=expected or query_summary["oi_nonnull"]!=0:
        raise ValueError("corpus SQL count/OI reconciliation failed")
    limits=["legacy OI unavailable; original values only in forensic/source copies",
        "legacy observation dates retained; collapsed provider timestamps cannot be recovered",
        "receipt timestamps describe import, not original provider retrieval",
        "contract multiplier/style are unverified legacy assumptions",
        "overlapping EOD/Greek/processed versions are intentionally separate",
        "coverage is the supplied bounded corpus, not complete all-strike/all-expiry history"]
    meta=dict(manifest_version=1,kind="legacy_options_corpus",
        normalization_version=NORMALIZATION_VERSION,code=code_revision(),
        inventory=_ref(store,portable),private_inventory_sha256=file_digest(inventory_path),
        source_file_count=sum(len(g["files"]) for g in partitions),
        total_versioned_rows=expected,
        unique_observation_keys=query_summary["distinct_identity_date_count"],
        partitions=results,queries=query_summary,quality_by_series=quality,
        limitations=limits,original_files_verified_unchanged=True,
        original_verified_count=len(inv["files"]))
    corpus_id=digest(json_bytes(meta))
    meta["corpus_version"]=corpus_id
    artifacts["manifest.json"]=json_bytes(seal(meta))
    artifacts["quality.json"]=json_bytes(seal(dict(series=quality,queries=query_summary,limitations=limits)))
    lines=["# Legacy options corpus quality audit","",
        f"Source files: {meta['source_file_count']}; versioned rows: {expected:,}.",
        f"Distinct underlying/date/expiry/strike/right keys: {meta['unique_observation_keys']:,}.",
        "Overlapping versions are not independent observations.","",
        "| Series | Rows | Dates | Missing IV | Zero bid | Crossed | Missing OI |",
        "|---|---:|---:|---:|---:|---:|---:|"]
    for name,q in quality.items():
        lines.append(f"| {name} | {q['rows']} | {q['unique_trading_dates']} | {q['missing_iv']} | "
                     f"{q['zero_bids']} | {q['crossed_markets']} | {q['unavailable_oi']} |")
    lines+=["","## Limitations",""]+["- "+s for s in limits]
    lines+=["","## DuckDB validation","", "```json",json.dumps(query_summary,indent=2),"```",
        "", "Each partition references its full JSON/Markdown audit, exact source copies, "
        "forensic fields and Phase 2B dataset manifest. No source row was filtered.",
        "",f"All {len(inv['files'])} inventoried originals retained their SHA-256 and modification time."]
    artifacts["quality.md"]=("\n".join(lines)+"\n").encode()
    return store._publish(store.root/"corpora"/"legacy_options",corpus_id,artifacts)/"manifest.json"
