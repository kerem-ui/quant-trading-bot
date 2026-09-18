"""Immutable source and dataset snapshots; bounded batch Parquet storage."""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime
import json
import os
from pathlib import Path
import shutil
import tempfile

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from .provenance import (code_revision, component, digest, file_digest, json_bytes,
                         load_sealed, safe_metadata, safe_request, seal, timestamp)
from .schemas import SCHEMAS, normalized_table

def data_root(configured: str | Path | None = None) -> Path:
    """Explicit root > QUANTBOT_DATA_ROOT > home/QuantData/quant_trading_bot."""
    candidate = Path(configured or os.environ.get("QUANTBOT_DATA_ROOT")
                     or Path.home() / "QuantData" / "quant_trading_bot").expanduser()
    if not candidate.is_absolute():
        raise ValueError("data root must be absolute")
    root = candidate.resolve()
    if any(p.lower().startswith("onedrive") for p in root.parts):
        raise ValueError("data root must be outside OneDrive")
    if any((p / ".git").exists() for p in (root, *root.parents)):
        raise ValueError("data root must be outside Git working trees")
    return root

class DataStore:
    """Small immutable snapshots; no implicit downloads or legacy migration."""

    def __init__(self, root: str | Path | None = None):
        self.root = data_root(root)

    def _inside(self, path: Path) -> Path:
        path = Path(path).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("path escapes data root")
        return path

    def _publish(self, parent: Path, name: str, files: dict[str, bytes]) -> Path:
        """Publish a complete directory; never overwrite an existing artifact."""
        parent = self._inside(parent)
        destination = parent / name
        if destination.exists():
            for filename, contents in files.items():
                p = destination / filename
                if not p.is_file() or p.read_bytes() != contents:
                    raise ValueError("immutable snapshot checksum mismatch")
            return destination
        parent.mkdir(parents=True, exist_ok=True)
        temp = Path(tempfile.mkdtemp(prefix=".pending-", dir=parent))
        try:
            for filename, contents in files.items():
                (temp / filename).write_bytes(contents)
            os.rename(temp, destination)
        finally:
            if temp.exists():
                # Only this call's newly created staging directory is removed.
                shutil.rmtree(temp)
        return destination

    def preserve_source(self, payload: bytes, *, provider: str, dataset: str,
                        kind: str, retrieved_at: datetime, request: dict) -> Path:
        """Preserve exact payload bytes and a credential-free retrieval record.

        fixture_payload is explicitly synthetic. legacy_normalized is imported
        below imports/normalized, never represented as a true raw response.
        """
        provider, dataset = component(provider), component(dataset)
        if kind not in {"provider_payload", "fixture_payload", "legacy_normalized"}:
            raise ValueError("unknown source semantics")
        request = safe_request(request)
        if not isinstance(payload, bytes):
            raise TypeError("source payload must be exact bytes")
        # Refuse recognized secrets in text/JSON responses; bytes are not redacted.
        try:
            text = payload.decode("utf-8")
            safe_metadata(text)
            try:
                safe_metadata(json.loads(text))
            except json.JSONDecodeError:
                pass
        except UnicodeDecodeError:
            if kind != "legacy_normalized":
                raise ValueError("provider payload must be inspectable UTF-8 JSON/text")
        meta = dict(manifest_version=1, kind=kind, provider=provider, dataset=dataset,
            retrieved_at=timestamp(retrieved_at), request=request,
            payload_sha256=digest(payload), payload_bytes=len(payload),
            payload_path="payload.bin")
        ident = digest(json_bytes(meta))
        area = {"provider_payload": Path("raw"), "fixture_payload": Path("raw"),
                "legacy_normalized": Path("imports/normalized")}[kind]
        parent = self.root / area / provider / dataset / retrieved_at.date().isoformat()
        path = self._publish(parent, ident, {
            "payload.bin": payload, "source.json": json_bytes(seal(meta))})
        return path / "source.json"

    def verify_source(self, manifest: Path) -> dict:
        """Verify source-manifest integrity and exact payload checksum."""
        manifest = self._inside(manifest)
        meta = load_sealed(manifest)
        path = self._inside(manifest.parent / meta["payload_path"])
        if file_digest(path) != meta["payload_sha256"] or path.stat().st_size != meta["payload_bytes"]:
            raise ValueError("source payload checksum mismatch")
        return meta

    def _reference(self, manifest: Path) -> dict:
        path = self._inside(manifest)
        return {"path": path.relative_to(self.root).as_posix(),
                "manifest_sha256": file_digest(path)}

    def write_dataset(self, table: pa.Table, *, schema_name: str, provider: str,
                      dataset: str, sources: list[Path], requested_start: date,
                      requested_end: date, normalization_version: str,
                      max_rows_per_file: int = 1_000_000,
                      normalization_parameters: dict | None = None) -> Path:
        """Validate and publish a sorted immutable batch plus its dataset manifest.

        One file for small samples; larger batches are sharded only at 1M rows
        by default. No per-contract/per-day tiny-file partitioning.
        """
        provider, dataset = component(provider), component(dataset)
        component(normalization_version)
        normalization_parameters = safe_metadata(normalization_parameters or {})
        if max_rows_per_file < 100_000:
            raise ValueError("minimum shard target is 100000 rows to avoid tiny files")
        table = normalized_table(table, schema_name)
        if table.num_rows == 0:
            raise ValueError("empty datasets require a separate no-data retrieval record")
        if not sources:
            raise ValueError("dataset requires verified source references")
        source_meta = [self.verify_source(p) for p in sources]
        if any(s["provider"] != provider for s in source_meta):
            raise ValueError("source provider mismatch")
        source_times = {datetime.fromisoformat(s["retrieved_at"]) for s in source_meta}
        if any(t not in source_times for t in table["retrieved_at"].to_pylist()):
            raise ValueError("table retrieval timestamp lacks a matching source receipt")
        dates = table["observation_date"].to_pylist()
        lo, hi = min(dates), max(dates)
        if (type(requested_start) is not date or type(requested_end) is not date
                or not requested_start <= lo <= hi <= requested_end):
            raise ValueError("observed dates outside requested range")
        symbol = "underlying" if schema_name == "options-v1" else "symbol"
        symbols = sorted(set(table[symbol].to_pylist()))
        files, descriptions = {}, []
        for offset in range(0, len(table), max_rows_per_file):
            name = f"part-{len(files):05d}.parquet"
            part = table.slice(offset, max_rows_per_file)
            sink = pa.BufferOutputStream()
            pq.write_table(part, sink, version="2.6", compression="zstd",
                compression_level=3, row_group_size=128_000,
                use_compliant_nested_type=False, write_statistics=True)
            contents = sink.getvalue().to_pybytes()
            files[name] = contents
            descriptions.append(dict(path=name, rows=len(part), bytes=len(contents),
                                     sha256=digest(contents)))
        flags = Counter(flag for row in table["quality_flags"].to_pylist() for flag in row)
        coverage = {}
        for sym in symbols:
            ds = [d for d, s in zip(dates, table[symbol].to_pylist()) if s == sym]
            coverage[sym] = dict(start=min(ds).isoformat(), end=max(ds).isoformat(),
                                 rows=len(ds), observed_dates=len(set(ds)))
        meta = dict(manifest_version=1, kind="normalized_observations",
            provider=provider, dataset=dataset, schema_version=schema_name,
            normalization_version=normalization_version,
            normalization_parameters=normalization_parameters,
            symbols=symbols, requested_range=dict(start=requested_start.isoformat(),
                end=requested_end.isoformat()), observed_range=dict(start=lo.isoformat(), end=hi.isoformat()),
            coverage_by_symbol=coverage,
            retrieval_timestamps=sorted({s["retrieved_at"] for s in source_meta}),
            sources=sorted([self._reference(p) for p in sources], key=lambda r:r["path"]),
            row_count=len(table), file_count=len(files), files=descriptions,
            quality={"missing_fields": {name:table[name].null_count for name in table.column_names},
                     "flag_counts":dict(sorted(flags.items()))},
            code=code_revision(), schema_sha256=digest(SCHEMAS[schema_name].serialize().to_pybytes()),
            writer=dict(pyarrow=pa.__version__, parquet_version="2.6", compression="zstd",
                        row_group_rows=128_000, max_rows_per_file=max_rows_per_file))
        version = digest(json_bytes(meta))
        meta["dataset_version"] = version
        files["manifest.json"] = json_bytes(seal(meta))
        asset = "options" if schema_name == "options-v1" else "equities"
        parent = self.root / "normalized" / asset / provider / schema_name / dataset
        return self._publish(parent, version, files) / "manifest.json"

    def read_dataset(self, manifest: Path) -> pa.Table:
        """Verify the complete provenance chain and return a deterministic table."""
        manifest = self._inside(manifest)
        meta = load_sealed(manifest)
        if meta["kind"] != "normalized_observations":
            raise ValueError("manifest is not a normalized observation dataset")
        for ref in meta["sources"]:
            path = self._inside(self.root / ref["path"])
            if file_digest(path) != ref["manifest_sha256"]:
                raise ValueError("source manifest checksum mismatch")
            self.verify_source(path)
        parts = []
        for item in meta["files"]:
            path = self._inside(manifest.parent / item["path"])
            if file_digest(path) != item["sha256"]:
                raise ValueError("Parquet checksum mismatch")
            table = pq.ParquetFile(path).read()
            if len(table) != item["rows"] or path.stat().st_size != item["bytes"]:
                raise ValueError("manifest file count/size mismatch")
            parts.append(table)
        if not parts or len(parts) != meta["file_count"]:
            raise ValueError("manifest file count mismatch")
        table = normalized_table(pa.concat_tables(parts), meta["schema_version"])
        if len(table) != meta["row_count"]:
            raise ValueError("manifest row count mismatch")
        return table

    def query(self, manifest: Path, sql: str) -> pa.Table:
        """Query verified Parquet observations through an isolated in-memory DuckDB.

        The observations relation is Arrow-backed after checked Parquet readback.
        Only one SELECT statement is accepted; filesystem/network SQL is disabled.
        """
        table = self.read_dataset(manifest)
        with duckdb.connect(":memory:") as connection:
            connection.register("observations", table)
            connection.execute("SET enable_external_access = false")
            statements = connection.extract_statements(sql)
            if len(statements) != 1 or statements[0].type != duckdb.StatementType.SELECT:
                raise ValueError("query must be one SELECT")
            return connection.sql(sql).to_arrow_table()

    def write_run(self, run_id: str, *, strategy: str, config: dict,
                  datasets: list[Path], outputs: list[str], timestamp: datetime,
                  code_version: str) -> Path:
        """Publish an immutable research-run record with dataset/config checksums."""
        from .provenance import timestamp as utc_timestamp
        component(run_id)
        safe_metadata(config)
        safe_metadata(outputs)
        for output in outputs:
            if Path(output).is_absolute() or ".." in Path(output).parts:
                raise ValueError("run outputs must be relative to the data root")
        for path in datasets:
            self.read_dataset(path)
        meta = seal(dict(manifest_version=1, kind="research_run", run_id=run_id,
            timestamp=utc_timestamp(timestamp), strategy=strategy, config=config,
            config_sha256=digest(json_bytes(config)), code=code_revision(),
            code_version=code_version, datasets=[
                self._reference(p) | {"dataset_version": load_sealed(p)["dataset_version"]}
                for p in datasets],
            outputs=outputs))
        destination = self.root / "runs" / run_id
        if destination.exists():
            raise FileExistsError("run ID already exists")
        return self._publish(destination.parent, run_id,
            {"manifest.json":json_bytes(meta)}) / "manifest.json"
