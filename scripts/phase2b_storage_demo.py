"""Offline Phase 2B sample: exact JSON -> Arrow -> Parquet -> manifests -> SQL.

No historical download and no old local data are used. All output is external.
"""
from __future__ import annotations
import argparse
from datetime import date, datetime, timezone
import json
from pathlib import Path

import _common  # noqa: F401
from quantbot.data.options_providers.theta_analytical import ingest_payload
from quantbot.data.storage import DataStore
from quantbot.data.storage.provenance import json_bytes
from quantbot.data.storage.schemas import normalized_table

def main():
    """Create a tiny synthetic dataset and a research-run provenance record."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=None)
    parser.add_argument("--run-id", default="phase2b-sample")
    args = parser.parse_args()
    store = DataStore(args.data_root)
    retrieved = datetime(2026,1,5,22,tzinfo=timezone.utc)
    rows = [
        dict(symbol="SPY",expiration="2026-01-16",strike=500,right="call",
            date="2026-01-05",timestamp="2026-01-05T16:00:00-05:00",
            created="2026-01-05T21:01:00Z",last_trade="2026-01-02T15:00:00-05:00",
            bid=2.0,ask=2.2,bid_size=4,ask_size=5,volume=7,delta=0.5,
            implied_vol=0.2,underlying_price=501.0,iv_error=0.001),
        dict(symbol="QQQ",expiration="2026-01-16",strike=500,right="call",
            date="2026-01-05",timestamp="2026-01-05T21:00:00Z",
            created="2026-01-05T21:02:00Z",bid=3.0,ask=3.2,open_interest=0,volume=8),
    ]
    options = ingest_payload(store, json_bytes({"response":rows}),
        retrieved_at=retrieved, kind="fixture_payload",
        request={"endpoint":"/v3/option/history/eod","symbols":["SPY","QQQ"],
                 "start_date":"2026-01-05","end_date":"2026-01-06"},
        requested_start=date(2026,1,5), requested_end=date(2026,1,6),
        source_timezone="America/New_York")
    equity_source = store.preserve_source(
        json_bytes({"symbol":"SPY","date":"2026-01-05","close":102,
                    "adjusted_close":51,"adjustment_factor":0.5}),
        provider="fixture",dataset="equities_daily",kind="fixture_payload",
        retrieved_at=retrieved,request={})
    equity_table=normalized_table([dict(symbol="SPY",observation_date=date(2026,1,5),
        retrieved_at=retrieved,raw_open=100,raw_high=103,raw_low=99,raw_close=102,
        adjusted_close=51,adjustment_factor=0.5,
        adjustment_convention="adjusted_over_raw",volume=100)],"equities-v1")
    equities=store.write_dataset(equity_table,schema_name="equities-v1",
        provider="fixture",dataset="equities_daily",sources=[equity_source],
        requested_start=date(2026,1,5),requested_end=date(2026,1,5),
        normalization_version="fixture-v1")
    result=store.query(options,
        "SELECT underlying, bid, ask, open_interest, multiplier FROM observations ORDER BY underlying"
    ).to_pylist()
    output=f"runs/{args.run_id}/sample.json"
    run=store.write_run(args.run_id,strategy="storage-demo",config={"synthetic":True},
        datasets=[options,equities],outputs=[output],timestamp=datetime.now(timezone.utc),
        code_version="phase2b-demo-v1")
    summary=dict(options_rows=len(store.read_dataset(options)),equity_rows=len(equity_table),
        options_sql=result,equity_sql=store.query(equities,
        "SELECT raw_close, adjusted_close, adjustment_factor FROM observations").to_pylist(),
        dataset_manifests=[p.relative_to(store.root).as_posix() for p in (options,equities)])
    with (store.root/output).open("xb") as handle:
        handle.write(json_bytes(summary))
    print(json.dumps(summary,indent=2))
    print(f"Run manifest: {run}")

if __name__ == "__main__":
    main()
