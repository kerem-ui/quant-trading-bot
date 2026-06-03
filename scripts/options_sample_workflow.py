"""V4 options sample workflow.

End-to-end: load -> validate -> normalize -> cache (raw + processed) -> update
metadata. Designed to run safely against the synthetic loader by default.

Real ThetaData fetches are GATED. Running ``--provider thetadata`` without
``--approve-real-fetch`` only prints the fetch plan; it does **not** call the
network. No broker, no live data, no API key is ever printed.

Usage examples
--------------
Synthetic dry-run (always safe, offline):
    python scripts/options_sample_workflow.py --provider synthetic \
        --underlyings SPY QQQ --start 2022-01-03 --end 2022-01-07

Print the ThetaData fetch plan without fetching:
    python scripts/options_sample_workflow.py --provider thetadata \
        --underlyings SPY --start 2022-01-03 --end 2022-01-07

Approve a real ThetaData fetch (requires THETADATA_API_KEY in env):
    python scripts/options_sample_workflow.py --provider thetadata \
        --underlyings SPY --start 2022-01-03 --end 2022-01-07 \
        --approve-real-fetch
"""

from __future__ import annotations

import argparse
import os
import sys

import pandas as pd
from _common import detect_data_source  # noqa: F401 - kept for parity

from quantbot.data import options_cache as oc
from quantbot.data.options_chain_loader import REQUIRED_COLS, get_loader
import quantbot.data.options_providers  # noqa: F401 - registers loaders
from quantbot.data.options_validators import (
    OptionsQualityThresholds,
    rejection_reasons,
    validate_canonical_chain,
)


def _mask(v: str | None, keep: int = 4) -> str:
    if not v:
        return "<unset>"
    return v[:2] + "***" + v[-keep:] if len(v) > keep + 2 else "***"


def _bdays(start: str, end: str) -> pd.DatetimeIndex:
    return pd.bdate_range(pd.Timestamp(start), pd.Timestamp(end))


def _print_fetch_plan(provider: str, underlyings: list[str],
                      start: str, end: str) -> None:
    days = _bdays(start, end)
    # Tiny SPY-only sample bound: ~6 front-month expirations x ~100 strikes
    # x 2 (C/P) x N days. We cap expirations in the adapter to keep it small.
    est_rows = 1200 * len(underlyings) * len(days)         # ~1.2k per chain/day
    est_kb = est_rows * 220 / 1024                          # ~220 bytes/row csv.gz
    key_env = os.environ.get("THETADATA_API_KEY")
    base_url = os.environ.get("THETADATA_BASE_URL", "http://127.0.0.1:25503")
    is_local = ("127.0.0.1" in base_url) or ("localhost" in base_url)
    root = oc.options_root()
    print("=" * 72)
    print("THETADATA v3 REAL-FETCH PLAN  (NOT EXECUTED unless --approve-real-fetch)")
    print("=" * 72)
    print(f"  provider           : {provider}")
    print(f"  underlyings        : {underlyings}")
    print(f"  start / end        : {start}  /  {end}")
    print(f"  business days      : {len(days)}")
    print(f"  estimated rows     : ~{est_rows:,}")
    print(f"  estimated size     : ~{est_kb:,.0f} KB on disk (csv.gz)")
    print(f"  THETADATA_BASE_URL : {base_url}  (API v3)")
    if is_local:
        print( "  auth               : LOCAL Theta Terminal (creds.txt next to "
              "the jar; this script never reads it)")
    else:
        print(f"  THETADATA_API_KEY  : {_mask(key_env)}")
    print(f"  raw cache root     : {root / 'raw' / provider.lower()}")
    print(f"  processed root     : {root / 'processed'}")
    print(f"  metadata file      : {root / 'metadata.json'}")
    print("  guards             : research/backtest only; no broker; "
          "no live; LIVE_TRADING_ENABLED=False")
    print("=" * 70)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=["synthetic", "thetadata"],
                    default="synthetic")
    ap.add_argument("--underlyings", nargs="+", default=["SPY"])
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--approve-real-fetch", action="store_true",
                    help="Required to issue an actual ThetaData network call.")
    ap.add_argument("--dte-min", type=int, default=None,
                    help="Optional minimum DTE filter for the option chain.")
    ap.add_argument("--dte-max", type=int, default=None,
                    help="Optional maximum DTE filter (also bounds the "
                         "ThetaData server-side max_dte parameter).")
    args = ap.parse_args()

    days = _bdays(args.start, args.end)
    if len(days) == 0:
        print("No business days in range; nothing to do."); return 1
    if len(days) > 21:
        print(f"Refusing to run with >21 business days ({len(days)}). "
              "V4 sample workflow is for SMALL ranges only.")
        return 2

    # ThetaData real fetch is gated.
    if args.provider == "thetadata":
        _print_fetch_plan(args.provider, args.underlyings, args.start, args.end)
        base_url = os.environ.get("THETADATA_BASE_URL", "http://127.0.0.1:25503")
        is_local = ("127.0.0.1" in base_url) or ("localhost" in base_url)
        if not args.approve_real_fetch:
            print("\nDry-run: synthetic data will be substituted because "
                  "--approve-real-fetch was not set.")
            if is_local:
                print("To actually fetch, ensure Theta Terminal v3 is running "
                      "(creds.txt next to its jar) and re-run with "
                      "--approve-real-fetch.")
            else:
                print("To actually fetch from a remote URL, set "
                      "THETADATA_API_KEY and re-run with --approve-real-fetch.")
        else:
            if (not is_local) and not os.environ.get("THETADATA_API_KEY"):
                print("\nERROR: --approve-real-fetch passed with a remote "
                      "THETADATA_BASE_URL but THETADATA_API_KEY is not set. "
                      "Aborting.")
                return 3
            print(f"\nProceeding with REAL ThetaData v3 fetch via {base_url} ...")

    dry_run = (args.provider == "thetadata") and (not args.approve_real_fetch)
    loader_kwargs = {"dry_run": dry_run} if args.provider == "thetadata" else {}
    loader = get_loader(args.provider, **loader_kwargs)
    print(f"\nLoader: {loader}")

    threshold = OptionsQualityThresholds()
    total_rows = 0
    written_dates: list[pd.Timestamp] = []
    rejection_summary: dict[str, int] = {}

    for u in args.underlyings:
        df = loader.load(u, args.start, args.end,
                          dte_min=args.dte_min, dte_max=args.dte_max)
        for d, day_df in df.groupby("date"):
            rep = validate_canonical_chain(day_df, threshold)
            if not rep.ok:
                print(f"  WARN {u} {pd.Timestamp(d).date()}: {rep.errors}")
                continue
            # Record per-row rejection counts (warnings only - we still write).
            rr = rejection_reasons(day_df, threshold)
            for col in rr.columns:
                if col == "any_reject":
                    continue
                rejection_summary[col] = rejection_summary.get(col, 0) + int(rr[col].sum())
            # Write raw (no overwrite). If a file already exists, skip and warn.
            try:
                p = oc.write_raw(day_df, args.provider, u, d)
                total_rows += len(day_df)
                written_dates.append(pd.Timestamp(d))
                print(f"  OK   {u} {pd.Timestamp(d).date()} -> "
                      f"{p.relative_to(oc.options_root().parent)}  "
                      f"({len(day_df)} rows)")
            except FileExistsError:
                print(f"  SKIP {u} {pd.Timestamp(d).date()}: raw cache exists "
                      "(pass --force-overwrite-raw to override, NOT supported here)")
        # Aggregate processed (monthly).
        for (yr, mo), g in df.groupby([df["date"].dt.year, df["date"].dt.month]):
            oc.write_processed(g, u, int(yr), int(mo))

    if written_dates:
        oc.update_metadata(args.provider, args.underlyings[0],
                            written_dates, total_rows,
                            note=f"sample_workflow {args.start}..{args.end}")
        print(f"\nMetadata updated -> {oc.metadata_path()}")
    print(f"\nTotal rows written: {total_rows}")
    if rejection_summary:
        print("Rejection counts (per rule, across written rows):")
        for k, v in sorted(rejection_summary.items(), key=lambda kv: -kv[1])[:10]:
            if v:
                print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
