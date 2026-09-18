"""Read-only legacy data inventory; absolute paths stay in external audit files."""
from __future__ import annotations
from collections import Counter
from datetime import datetime, timezone
import os
from pathlib import Path

import pandas as pd

from .storage.provenance import file_digest

def inventory(root: Path) -> dict:
    """Hash data/reports and other market-data files without touching their contents."""
    root=Path(root).resolve()
    files=[]
    for base, dirs, names in os.walk(root):
        dirs[:]=sorted(d for d in dirs if d not in
            {".git",".venv","venv","env","__pycache__",".pytest_cache","node_modules"})
        for name in sorted(names):
            path=Path(base)/name
            relative=path.relative_to(root).as_posix()
            if not (relative.startswith(("data/","reports/")) or
                    path.suffix.lower() in {".csv",".gz",".parquet",".sqlite",".db"}):
                continue
            before=path.stat()
            item=dict(original_path=str(path),relative_path=relative,
                file_type="".join(path.suffixes) or "extensionless",bytes=before.st_size,
                mtime_ns=before.st_mtime_ns,sha256=file_digest(path),row_count=None,
                symbols=[],observed_range=None,columns=[],classification="generated_artifact")
            if relative.startswith("data/"):
                if relative.startswith(("data/events/","data/portfolio/")):
                    item["classification"]="manual_input"
                elif relative.startswith(("data/options/processed/","data/options/raw/")):
                    item["classification"]="legacy_normalized"
                elif relative.startswith(("data/research/","data/options/features/")):
                    item["classification"]="generated_artifact"
                else:
                    item["classification"]="cache"
            if name.endswith((".csv",".csv.gz",".parquet")) and before.st_size:
                try:
                    df=(pd.read_parquet(path) if name.endswith(".parquet") else
                        pd.read_csv(path,float_precision="round_trip",low_memory=False))
                    item["row_count"]=len(df)
                    item["columns"]=list(df.columns)
                    for column in ("underlying","symbol","ticker"):
                        if column in df:
                            item["symbols"]=sorted(df[column].dropna().astype(str).unique().tolist())
                            break
                    if not item["symbols"] and relative.startswith("data/cache/"):
                        item["symbols"]=[path.stem]
                    dc=next((c for c in ("date","Date","observation_date","as_of_date") if c in df),None)
                    if dc:
                        dates=pd.to_datetime(df[dc],format="mixed",errors="coerce").dropna()
                        if len(dates):
                            item["observed_range"]={"start":str(dates.min().date()),
                                                     "end":str(dates.max().date())}
                            item["unique_dates"]=int(dates.dt.normalize().nunique())
                    if relative.startswith("data/") and "option_type" in df and "expiration" in df:
                        item["classification"]="legacy_normalized"
                except Exception as exc:
                    item["inspection_error"]=type(exc).__name__
            after=path.stat()
            if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):
                raise ValueError(f"source changed during inventory: {relative}")
            files.append(item)
    return dict(format_version=1,created_at=datetime.now(timezone.utc).isoformat(),
                files=files,file_count=len(files),bytes=sum(f["bytes"] for f in files),
                classifications=dict(Counter(f["classification"] for f in files)))
