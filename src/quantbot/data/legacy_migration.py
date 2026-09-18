"""Controlled, read-only legacy options migration and explicit quality audit."""
from __future__ import annotations
from datetime import date, datetime
import calendar
from collections import Counter
from decimal import Decimal
import json
import io
from pathlib import Path
import re

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from .legacy_inventory import inventory
from .storage import DataStore
from .storage.provenance import digest, file_digest, json_bytes, seal, load_sealed
from .storage.schemas import normalized_table, SCHEMAS

NORMALIZATION_VERSION = "legacy-options-v1"
KEYS = ["date","underlying","expiration","strike","option_type"]
# Scoped exchange calendar; source and limitations are documented, not a general calendar engine.
CLOSED = {"2022-01-17","2022-02-21","2022-04-15","2022-05-30","2022-06-20",
          "2022-07-04","2022-09-05","2022-11-24","2022-12-26","2023-01-02","2023-01-16"}

def expected_sessions(year: int, month: int) -> list[str]:
    """Return the explicitly supported 2022 / January 2023 exchange sessions."""
    if year != 2022 and (year,month)!=(2023,1):
        raise ValueError("calendar scope is only 2022 and January 2023")
    days=pd.bdate_range(date(year,month,1),date(year,month,calendar.monthrange(year,month)[1]))
    return [str(d.date()) for d in days if str(d.date()) not in CLOSED]

def select_partitions(inv: dict) -> list[dict]:
    """Select only bounded SPY/QQQ processed and Theta-derived daily snapshots."""
    groups={}
    for item in inv["files"]:
        rel=item["relative_path"]
        processed=re.fullmatch(r"data/options/processed/(SPY|QQQ)/(\d{4})/(\d{4}-\d{2})\.csv\.gz",rel)
        daily=re.fullmatch(r"data/options/raw/thetadata/(SPY|QQQ)/(\d{4})/(\d{4}-\d{2})/(\d{4}-\d{2}-\d{2})(\.greeks)?\.csv\.gz",rel)
        match=processed or daily
        if not match:
            continue
        if item.get("row_count") is None or item.get("inspection_error"):
            raise ValueError("selected source has incomplete inventory")
        if item["classification"]!="legacy_normalized":
            raise ValueError("unexpected source semantics")
        symbol,year,month=match.group(1),int(match.group(2)),match.group(3)
        if item.get("symbols") != [symbol]:
            raise ValueError("source/path underlying mismatch")
        series="processed" if processed else "daily_greeks" if daily.group(5) else "daily_eod"
        key=(series,symbol,month)
        groups.setdefault(key,dict(series=series,symbol=symbol,year=year,
            month=int(month[-2:]),files=[]))["files"].append(item)
    result=[groups[k] for k in sorted(groups)]
    rows=sum(e["row_count"] for g in result for e in g["files"])
    size=sum(e["bytes"] for g in result for e in g["files"])
    if rows>6_000_000 or size>512_000_000 or len(result)>60:
        raise ValueError("unexpected corpus scale; review inventory before migration")
    return result

def _number(df, field):
    if field not in df:
        return pd.Series(np.nan,index=df.index)
    return pd.to_numeric(df[field],errors="coerce")

def audit_frame(df: pd.DataFrame, expected_dates: list[str] | None = None) -> dict:
    """Measure observations as stored; never filter, deduplicate or impute."""
    dates=pd.to_datetime(df["date"],errors="coerce")
    expirations=pd.to_datetime(df["expiration"],errors="coerce")
    observed=sorted(dates.dropna().dt.strftime("%Y-%m-%d").unique().tolist())
    dte=(expirations-dates).dt.days
    numeric=[c for c in df if pd.api.types.is_numeric_dtype(df[c])]
    infinities={c:int(np.isinf(pd.to_numeric(df[c],errors="coerce").astype(float)).sum()) for c in numeric}
    nans={c:int(df[c].isna().sum()) for c in numeric}
    strike=_number(df,"strike")
    event=df["event_timestamp"] if "event_timestamp" in df else pd.Series(None,index=df.index,dtype=object)
    ambiguous=0
    for value in event:
        if pd.isna(value):
            ambiguous+=1
        else:
            ts=pd.Timestamp(value)
            ambiguous+=int(ts.tzinfo is None)
    invalid_identity=(dates.isna() | expirations.isna() | strike.isna() | (strike<=0) |
        ~df["option_type"].isin(["call","put"]) | df["underlying"].isna())
    quotes=_number(df,"bid"),_number(df,"ask")
    coverage=[]
    for (underlying,dt,expiry,right),part in df.groupby(["underlying","date","expiration","option_type"],dropna=False):
        strikes=_number(part,"strike")
        coverage.append(dict(underlying=str(underlying),date=str(dt),expiration=str(expiry),
            right=str(right),rows=len(part),unique_strikes=int(strikes.nunique()),
            strike_min=float(strikes.min()),strike_max=float(strikes.max())))
    return dict(rows=len(df),unique_trading_dates=len(observed),dates=observed,
        earliest_date=observed[0] if observed else None,latest_date=observed[-1] if observed else None,
        symbols=sorted(df["underlying"].dropna().unique().tolist()),
        rights={str(k):int(v) for k,v in df["option_type"].value_counts(dropna=False).items()},
        expirations=sorted(expirations.dropna().dt.strftime("%Y-%m-%d").unique().tolist()),
        dte_distribution={str(int(k)):int(v) for k,v in dte.value_counts().sort_index().items()},
        dte_min=int(dte.min()) if dte.notna().any() else None,
        dte_max=int(dte.max()) if dte.notna().any() else None,
        strike_min=float(strike.min()) if strike.notna().any() else None,
        strike_max=float(strike.max()) if strike.notna().any() else None,
        unique_strikes=int(strike.nunique()),strike_coverage=coverage,
        duplicate_excess_rows=int(df.duplicated(KEYS).sum()),
        exact_duplicate_excess_rows=int(df.duplicated().sum()),
        duplicate_involved_rows=int(df.duplicated(KEYS,keep=False).sum()),
        missing_bid=int(quotes[0].isna().sum()),missing_ask=int(quotes[1].isna().sum()),
        crossed_markets=int((quotes[0]>quotes[1]).sum()),zero_bids=int((quotes[0]==0).sum()),
        negative_quotes=int(((quotes[0]<0)|(quotes[1]<0)).sum()),
        missing_iv=int(_number(df,"implied_volatility").isna().sum()),
        missing_greeks={c:int(_number(df,c).isna().sum()) for c in ("delta","gamma","theta","vega","rho")},
        unavailable_oi=len(df),legacy_oi_zero=int((_number(df,"open_interest")==0).sum()),
        legacy_oi_nonzero=int((_number(df,"open_interest").fillna(0)!=0).sum()),
        missing_underlying_price=int(_number(df,"underlying_price").isna().sum()),
        nonfinite_numeric_fields=infinities,missing_numeric_fields=nans,
        ambiguous_or_missing_event_timestamps=ambiguous,
        inconsistent_contract_identities=int(invalid_identity.sum()),
        inconsistent_dte=int((dte!=_number(df,"dte")).sum()) if "dte" in df else None,
        expected_dates=expected_dates,
        gaps=sorted(set(expected_dates or [])-set(observed)) if expected_dates is not None else None,
        unexpected_dates=sorted(set(observed)-set(expected_dates)) if expected_dates is not None else None)

RENAMED={"date":"observation_date","option_type":"right","contract_multiplier":"multiplier"}
TIME_FIELDS=("event_timestamp","provider_created_at","trade_timestamp","underlying_timestamp")
FORENSIC={"mid","dte","moneyness","log_moneyness","time_to_expiry_years","open_interest","retrieved_at"}

def normalize_legacy(df: pd.DataFrame, *, imported_at: datetime, duplicate_mask=None) -> pa.Table:
    """Preserve recoverable values; mark import time, unreliable OI and lost times."""
    allowed=set(SCHEMAS["options-v1"].names)|set(RENAMED)|FORENSIC
    unknown=set(df.columns)-allowed
    if unknown:
        raise ValueError(f"unmapped legacy columns need review: {sorted(unknown)}")
    output=[]
    for row_number, src in enumerate(df.to_dict("records")):
        flags=["legacy_oi_unreliable","legacy_contract_terms_unverified",
               "legacy_observation_date_unverified","import_receipt_not_provider_retrieval"]
        row={}
        for name,value in src.items():
            if name in FORENSIC:
                continue
            target=RENAMED.get(name,name)
            if pd.isna(value):
                row[target]=None
            elif target in ("observation_date","expiration"):
                ts=pd.Timestamp(value)
                if ts.tzinfo is not None or ts != ts.normalize():
                    raise ValueError("ambiguous legacy observation/expiration date")
                row[target]=ts.date()
            elif target in TIME_FIELDS:
                ts=pd.Timestamp(value)
                if ts.tzinfo is None:
                    raise ValueError("legacy timestamp has no timezone; review required")
                row[target]=ts
            elif target=="strike":
                row[target]=Decimal(str(value))
            elif target in ("volume","multiplier","bid_size","ask_size","trade_size","trade_count"):
                if not isinstance(value,(int,float)) or not np.isfinite(value) or int(value)!=value:
                    raise ValueError(f"invalid legacy integer {name}")
                row[target]=int(value)
            else:
                row[target]=value
        row["open_interest"]=None
        row["retrieved_at"]=imported_at
        if row.get("event_timestamp") is None:
            flags.append("legacy_event_timestamp_unavailable")
        if duplicate_mask is not None and duplicate_mask[row_number]:
            flags.append("legacy_duplicate_observation")
        row["quality_flags"]=flags
        output.append(row)
    return normalized_table(output,"options-v1")

def _ref(store: DataStore, path: Path) -> dict:
    return {"path":path.relative_to(store.root).as_posix(),"sha256":file_digest(path)}

def _markdown(quality: dict, title: str) -> str:
    lines=[f"# {title}","", "Counts describe stored observations; no suspicious rows were removed.","",
        "| Measure | Value |","|---|---:|"]
    for k in ("rows","unique_trading_dates","earliest_date","latest_date","duplicate_excess_rows",
              "missing_bid","missing_ask","crossed_markets","zero_bids","negative_quotes","missing_iv",
              "unavailable_oi","missing_underlying_price","ambiguous_or_missing_event_timestamps",
              "inconsistent_contract_identities"):
        lines.append(f"| {k} | {quality[k]} |")
    lines+=["","Missing Greeks: "+json.dumps(quality["missing_greeks"]),
        "","Missing sessions: "+json.dumps(quality["gaps"]),
        "","Full date/expiry/strike and DTE coverage is in the matching JSON report."]
    return "\n".join(lines)+"\n"

def migrate_partition(store: DataStore, item: dict, *, imported_at: datetime,
                      expected_dates: list[str] | None = None) -> dict:
    """Copy immutable sources, write one monthly snapshot, and reconcile every row."""
    items=item.get("files",[item])
    series=item.get("series","processed")
    # Verify every source before publishing any copies.
    payloads=[]
    for entry in items:
        path=Path(entry["original_path"])
        if file_digest(path)!=entry["sha256"] or path.stat().st_size!=entry["bytes"]:
            raise ValueError("legacy source changed since inventory")
        payload=path.read_bytes()
        if digest(payload)!=entry["sha256"]:
            raise ValueError("legacy source changed during read")
        payloads.append(payload)
    frames=[pd.read_csv(io.BytesIO(payload),compression="gzip",float_precision="round_trip")
            for payload in payloads]
    df=pd.concat(frames,ignore_index=True)
    if len(df)!=sum(e["row_count"] for e in items):
        raise ValueError("source row count differs from inventory")
    symbols=sorted(df["underlying"].unique().tolist())
    months=pd.to_datetime(df["date"]).dt.strftime("%Y-%m").unique().tolist()
    if len(symbols)!=1 or len(months)!=1:
        raise ValueError("partition must contain one underlying/month")
    symbol,month=symbols[0],months[0]
    quality=audit_frame(df,expected_dates)
    quality_bytes=json_bytes(seal(quality))
    # Save the audit before strict schema validation, including failures.
    audit_id=digest(json_bytes({"sources":[e["sha256"] for e in items],"quality":quality}))
    audit_dir=store._publish(store.root/"audits"/"phase2c"/series/symbol/month,audit_id,
        {"quality.json":quality_bytes,"quality.md":_markdown(quality,f"{series} {symbol} {month}").encode()})
    source_refs=[]
    for entry,payload in zip(items,payloads):
        src=store.preserve_source(payload,provider="thetadata",dataset="legacy_options",
            kind="legacy_normalized",retrieved_at=imported_at,request={})
        source_refs.append(src)
        if file_digest(src.parent/"payload.bin")!=entry["sha256"]:
            raise ValueError("copied source checksum mismatch")
    start=pd.Timestamp(month+"-01").date()
    end=date(start.year,start.month,calendar.monthrange(start.year,start.month)[1])
    params=dict(source_semantics="legacy_normalized",series=series,
        legacy_files=[{"relative_path":e["relative_path"],"sha256":e["sha256"]} for e in items],
        oi_policy="all legacy OI is untrusted and normalized to null",
        receipt_semantics="import receipt; original provider retrieval time is unknown",
        requested_range_semantics="migration partition bounds; original provider request unknown",
        contract_terms="legacy supplied multiplier/style retained but unverified",
        original_date_semantics="legacy date retained; prior timestamp collapse cannot be reversed")
    occurrences=df.groupby(KEYS,dropna=False,sort=False).cumcount()
    duplicates=df.duplicated(KEYS,keep=False)
    manifests,back_frames=[],[]
    for occurrence in sorted(occurrences.unique()):
        mask=occurrences==occurrence
        part=df.loc[mask].reset_index(drop=True)
        table=normalize_legacy(part,imported_at=imported_at,
                               duplicate_mask=duplicates[mask].tolist())
        policy=params | {"occurrence":int(occurrence),
                         "duplicate_policy":"preserve occurrence in separate snapshot"}
        manifest=store.write_dataset(table,schema_name="options-v1",provider="thetadata",
            dataset=f"{dict(processed='p',daily_eod='e',daily_greeks='g')[series]}.{symbol}.{month.replace('-','')}.{occurrence}",
            sources=source_refs,requested_start=start,requested_end=end,
            normalization_version=NORMALIZATION_VERSION,normalization_parameters=policy)
        back=store.read_dataset(manifest)
        if not back.equals(table):
            raise ValueError("Parquet roundtrip changed normalized fields")
        as_frame=back.to_pandas().rename(columns={v:k for k,v in RENAMED.items()})
        as_frame["_occurrence"]=int(occurrence)
        back_frames.append(as_frame)
        manifests.append(manifest)
    # Forensic sidecar preserves ALL original CSV columns and row ordering.
    forensic=df.rename(columns={c:"legacy_"+c for c in df.columns}).copy()
    forensic["source_occurrence"]=occurrences.to_numpy()
    forensic["source_file"]=[e["relative_path"] for e,f in zip(items,frames) for _ in range(len(f))]
    forensic["source_row"]=[i for f in frames for i in range(len(f))]
    extras=pa.Table.from_pandas(forensic,preserve_index=False)
    sink=pa.BufferOutputStream()
    pq.write_table(extras,sink,compression="zstd",row_group_size=128000)
    forensic_dir=store._publish(store.root/"imports"/"forensic"/series/symbol/month,audit_id,
        {"legacy_fields.parquet":sink.getvalue().to_pybytes()})
    if not pq.ParquetFile(forensic_dir/"legacy_fields.parquet").read().equals(extras):
        raise ValueError("forensic roundtrip failed")
    # Independent sorted comparison of each mapped field, not just re-running normalization.
    ordered=df.assign(_occurrence=occurrences).sort_values(KEYS+["_occurrence"]).reset_index(drop=True)
    actual=pd.concat(back_frames,ignore_index=True).sort_values(KEYS+["_occurrence"]).reset_index(drop=True)
    checked=[]
    for col in df.columns:
        if col in FORENSIC:
            continue
        expected=ordered[col]
        found=actual[col]
        if col in ("date","expiration"):
            equal=np.array_equal(pd.to_datetime(expected).values,pd.to_datetime(found).values)
        elif col in TIME_FIELDS:
            equal=np.array_equal(pd.to_datetime(expected,utc=True).values,pd.to_datetime(found,utc=True).values)
        elif pd.api.types.is_numeric_dtype(expected):
            equal=np.array_equal(expected.to_numpy(dtype=float),found.to_numpy(dtype=float),equal_nan=True)
        else:
            equal=expected.fillna("<NULL>").astype(str).equals(found.fillna("<NULL>").astype(str))
        if not equal:
            raise ValueError(f"source/output field mismatch: {col}")
        checked.append(col)
    # Verify originals again after every write and readback.
    for e in items:
        p=Path(e["original_path"])
        if file_digest(p)!=e["sha256"] or p.stat().st_mtime_ns!=e["mtime_ns"]:
            raise ValueError("original source changed during migration")
    result=dict(series=series,symbol=symbol,month=month,
        dataset_manifest=_ref(store,manifests[0]),
        dataset_manifests=[_ref(store,m) for m in manifests],source_manifest=_ref(store,source_refs[0]),
        source_manifests=[_ref(store,p) for p in source_refs],
        quality_report=_ref(store,audit_dir/"quality.json"),
        quality_markdown=_ref(store,audit_dir/"quality.md"),
        forensic_fields=_ref(store,forensic_dir/"legacy_fields.parquet"),
        reconciliation=dict(source_rows=len(df),output_rows=len(actual),
            identity_equal=True,date_coverage_equal=True,
            all_recoverable_fields_equal=True,compared_fields=checked,
            forensic_preserved_fields=list(df.columns),oi_null_rows=int(actual["open_interest"].isna().sum()),
            copied_source_bytes=sum(e["bytes"] for e in items),
            parquet_bytes=sum(f["bytes"] for m in manifests for f in load_sealed(m)["files"])))
    return result
