"""V4.1 enrichment: pull IV + Greeks via /v3/option/history/greeks/eod and
re-generate the canonical processed file for the existing tiny SPY sample.

This script is purely additive:
  - Per-date RAW EOD files (data/options/raw/thetadata/SPY/.../YYYY-MM-DD.csv.gz)
    are NEVER overwritten.
  - The enriched per-date raw files are written alongside with a
    ``.greeks.csv.gz`` suffix.
  - The monthly processed (canonical) file is REGENERATED from the enriched
    superset (this is fine - processed is by design a re-aggregation).
  - metadata.json gets a new fetch event labelled ``greeks_enrichment``.

Guards: research/backtest only; no broker; no live; no strategy code; the
ThetaData Pro-only ``greeks/all`` endpoint is NOT used.

Usage:
    python scripts/options_enrich_greeks.py --start 2022-01-03 --end 2022-01-07
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import _common  # noqa: F401 - puts src/ on sys.path
import pandas as pd

from quantbot.data import options_cache as oc
from quantbot.data.options_chain_loader import REQUIRED_COLS
import quantbot.data.options_providers  # noqa: F401 - registers loaders
from quantbot.data.options_providers.thetadata import (
    ThetaDataLoader,
    _spot_from_local_cache,
    normalize_thetadata_v3_greeks_eod,
)
from quantbot.data.options_validators import (
    OptionsQualityThresholds,
    rejection_reasons,
    validate_canonical_chain,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--underlying", default="SPY",
                    help="Only one underlying per V4.1 scope. Default: SPY.")
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--dte-max", type=int, default=10,
                    help="Bound the option/history/greeks/eod call (server-"
                         "side max_dte). Default 10 = tiny near-term sample.")
    ap.add_argument("--dte-min", type=int, default=None)
    args = ap.parse_args()

    start_ts, end_ts = pd.Timestamp(args.start), pd.Timestamp(args.end)
    days = pd.bdate_range(start_ts, end_ts)
    if len(days) == 0:
        print("No business days in range."); return 1
    if len(days) > 25:
        print(f"Enrichment refuses to run with >25 business days "
              f"({len(days)}). Use a smaller range or split the run.")
        return 2

    # Raise timeout: a single greeks/eod call covering many strikes over a
    # multi-week range can take ~30-60s, more than the loader's 30s default.
    # Monthly OPEX expirations during volatile periods (e.g. May/Jun 2022)
    # can exceed 90s, so we use 240s here (the June 2022 run failed on the
    # 90s timeout at the 2022-06-17 OPEX expiration).
    loader = ThetaDataLoader(dry_run=False, timeout_seconds=240.0)
    if not loader.is_local_terminal:
        print("Refusing to run V4.1 enrichment against a remote URL. "
              "This script is for the local Theta Terminal only.")
        return 3
    print(f"Loader: {loader}")
    print(f"Endpoint: /v3/option/history/greeks/eod  symbol={args.underlying} "
          f"start_date={args.start} end_date={args.end} max_dte={args.dte_max}")

    # --- enumerate near-term expirations ------------------------------- #
    # NOTE: /v3/option/history/greeks/eod does NOT accept ``expiration=*``
    # (HTTP 400) - it requires a specific expiration per request. So we list
    # expirations once and call greeks/eod per expiration in [dte_min,
    # dte_max] for any date in the range. This stays tiny: a handful of
    # near-term expirations + at most one call per expiration.
    all_exps = loader._option_list_expirations(args.underlying)
    lo = (args.dte_min if args.dte_min is not None else 0)
    hi = args.dte_max
    keep_exps: list[pd.Timestamp] = []
    for exp in all_exps:
        dtes = [(exp - d).days for d in days]
        if any(lo <= dt <= hi for dt in dtes):
            keep_exps.append(exp)
    if not keep_exps:
        print(f"No expirations in DTE band [{lo}, {hi}]."); return 4
    print(f"expirations in band: {len(keep_exps)} -> "
          f"{[str(e.date()) for e in keep_exps]}")

    # --- one greeks/eod call per expiration ---------------------------- #
    # NOTE: edge-of-band expirations can return HTTP 472 ("no data") when
    # every date in the range puts the expiration out of `max_dte`. We log
    # and skip these instead of aborting the whole enrichment - otherwise
    # one missing tail expiration discards 30+ successfully-fetched ones.
    frames: list[pd.DataFrame] = []
    skipped_exps: list[tuple[str, str]] = []
    for i, exp in enumerate(keep_exps, 1):
        print(f"  [{i}/{len(keep_exps)}] greeks/eod exp={exp.date()} ...",
              end="", flush=True)
        try:
            sub = loader._option_history_greeks_eod(
                args.underlying, start_ts, end_ts,
                expiration=exp.strftime("%Y-%m-%d"), max_dte=args.dte_max,
            )
        except RuntimeError as exc:
            msg = str(exc)
            # Only swallow per-expiration provider errors; never mask
            # connectivity / auth issues (those will still abort).
            if ("HTTP 472" in msg) or ("HTTP 4" in msg and "no_data" in msg.lower()):
                print(f" SKIP ({msg.splitlines()[0][:80]})")
                skipped_exps.append((str(exp.date()), msg.splitlines()[0]))
                continue
            raise
        if not sub.empty:
            frames.append(sub)
        print(f" {len(sub)} rows")
    if skipped_exps:
        print(f"\nSkipped {len(skipped_exps)} expirations with provider 'no data' "
              "(typically edge-of-band exps where every range-day is out of "
              "max_dte):")
        for d, reason in skipped_exps:
            print(f"  - {d}")
    if not frames:
        print("greeks/eod returned no rows for any expiration."); return 5
    raw = pd.concat(frames, ignore_index=True)
    print(f"raw rows from provider: {len(raw)}")

    # Fallback spot (rows with no underlying_price) from the local ETF cache.
    spot_by_date = _spot_from_local_cache(args.underlying, start_ts, end_ts)
    df = normalize_thetadata_v3_greeks_eod(
        raw, underlying=args.underlying, spot_by_date=spot_by_date,
    )
    if args.dte_min is not None:
        df = df[df["dte"] >= args.dte_min]

    threshold = OptionsQualityThresholds()
    rejection_summary: dict[str, int] = {}
    written_dates: list[pd.Timestamp] = []
    total_rows = 0

    # --- per-date enriched RAW files (`.greeks.csv.gz` suffix) ---------- #
    for d, day_df in df.groupby("date"):
        rep = validate_canonical_chain(day_df, threshold)
        if not rep.ok:
            print(f"  WARN {pd.Timestamp(d).date()}: {rep.errors}"); continue
        rr = rejection_reasons(day_df, threshold)
        for col in rr.columns:
            if col == "any_reject":
                continue
            rejection_summary[col] = rejection_summary.get(col, 0) + int(rr[col].sum())

        # Build the path manually so we DON'T touch the existing
        # YYYY-MM-DD.csv.gz raw file (write_raw refuses overwrite anyway).
        d_ts = pd.Timestamp(d).normalize()
        out_path = (oc.options_root() / "raw" / "thetadata"
                    / args.underlying.upper() / f"{d_ts.year:04d}"
                    / f"{d_ts.year:04d}-{d_ts.month:02d}"
                    / f"{d_ts.strftime('%Y-%m-%d')}.greeks.csv.gz")
        if out_path.exists():
            print(f"  SKIP {d_ts.date()}: enriched raw exists at {out_path}")
            continue
        out_path.parent.mkdir(parents=True, exist_ok=True)
        # Reuse the cache's atomic-write helper.
        oc._atomic_write_csv(day_df, out_path)
        rel = out_path.relative_to(oc.options_root().parent)
        print(f"  OK   {d_ts.date()} -> {rel}  ({len(day_df)} rows)")
        written_dates.append(d_ts)
        total_rows += len(day_df)

    if not written_dates:
        print("\nNo new enriched raw files written (existing files present?)")
        return 0

    # --- regenerate processed (overwriteable; canonical superset) ------- #
    for (yr, mo), g in df.groupby([df["date"].dt.year, df["date"].dt.month]):
        oc.write_processed(g, args.underlying, int(yr), int(mo))

    # --- metadata fetch event ------------------------------------------- #
    oc.update_metadata(
        "thetadata", args.underlying, written_dates, total_rows,
        note=f"greeks_enrichment {args.start}..{args.end} (greeks/eod)",
    )
    print(f"\nMetadata updated -> {oc.metadata_path()}")

    # --- coverage check on canonical IV/Greeks -------------------------- #
    iv_present = int(df["implied_volatility"].notna().sum())
    iv_positive = int((df["implied_volatility"].fillna(0) > 0).sum())
    greeks_present = int(df[["delta", "gamma", "theta", "vega", "rho"]
                              ].notna().all(axis=1).sum())
    print(f"\nIV coverage : non-NaN={iv_present}/{len(df)} "
          f"({iv_present/len(df):.1%}); positive={iv_positive}/{len(df)} "
          f"({iv_positive/len(df):.1%})")
    print(f"Greeks coverage: all-5 non-NaN={greeks_present}/{len(df)} "
          f"({greeks_present/len(df):.1%})")

    if rejection_summary:
        print("\nRejection counts (per rule, across written rows):")
        for k, v in sorted(rejection_summary.items(), key=lambda kv: -kv[1])[:10]:
            if v:
                print(f"  {k}: {v}")

    print(f"\nTotal enriched rows written: {total_rows}")
    print("Next: python scripts/options_quality_report.py --provider thetadata")
    return 0


if __name__ == "__main__":
    sys.exit(main())
