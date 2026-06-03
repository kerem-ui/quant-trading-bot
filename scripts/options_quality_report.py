"""V4 options data quality report.

Walks the local options cache (``data/options/raw/<provider>/<underlying>/...``)
and prints + writes a quality summary covering:
  - row counts, date and expiration coverage, gaps,
  - DTE distribution,
  - bid/ask spread statistics,
  - missing IV / Greeks,
  - volume / open-interest summary,
  - per-rule rejection counts.

Output: console + ``reports/options/options_quality_report.md``. No network,
no broker, no live data; this script only reads from the local cache.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import _common  # noqa: F401 - sets up src/ on sys.path
import numpy as np
import pandas as pd

from quantbot.config import project_root
from quantbot.data import options_cache as oc
from quantbot.data.options_validators import (
    OptionsQualityThresholds,
    rejection_reasons,
)

pd.set_option("display.width", 180)


def _scan_cache(provider: str | None) -> dict[tuple[str, str, str], list[Path]]:
    """Return ``{(provider, underlying, kind): [path...]}`` for everything cached.

    ``kind`` is ``"eod"`` for price-only ``YYYY-MM-DD.csv.gz`` files and
    ``"greeks"`` for V4.1-enriched ``YYYY-MM-DD.greeks.csv.gz`` files. The
    two are kept SEPARATE in the report so the same logical day isn't
    double-counted across file variants.
    """
    root = oc.options_root() / "raw"
    if not root.is_dir():
        return {}
    out: dict[tuple[str, str, str], list[Path]] = {}
    for p in sorted(root.rglob("*.csv.gz")):
        try:
            prov = p.relative_to(root).parts[0]
            und = p.relative_to(root).parts[1]
        except Exception:
            continue
        if provider and prov.lower() != provider.lower():
            continue
        kind = "greeks" if p.name.endswith(".greeks.csv.gz") else "eod"
        out.setdefault((prov, und.upper(), kind), []).append(p)
    return out


def _load_panel(paths: list[Path]) -> pd.DataFrame:
    frames = []
    for p in paths:
        df = pd.read_csv(p, compression="gzip")
        for c in ("date", "expiration"):
            if c in df.columns:
                df[c] = pd.to_datetime(df[c])
        frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _date_gaps(dates: pd.Series) -> int:
    d = pd.DatetimeIndex(sorted(dates.unique()))
    if len(d) < 2:
        return 0
    full = pd.bdate_range(d.min(), d.max())
    return int(len(set(full) - set(d)))


def _section(title: str, lines: list[str], buf: list[str]) -> None:
    buf.append(f"\n## {title}")
    buf.extend(lines)


def _format_section(name: str, df: pd.DataFrame) -> list[str]:
    """Per-underlying section."""
    total = len(df)
    out: list[str] = [f"_rows: **{total:,}**_"]
    if total == 0:
        out.append("  (empty)"); return out
    out.append(f"- date range: {df['date'].min().date()} -> {df['date'].max().date()}")
    out.append(f"- unique dates: {df['date'].nunique()} "
               f"(business-day gaps: {_date_gaps(df['date'])})")
    out.append(f"- unique expirations: {df['expiration'].nunique()}; "
               f"range {df['expiration'].min().date()} -> "
               f"{df['expiration'].max().date()}")
    dq = df["dte"].astype(float).quantile([.10, .25, .50, .75, .90])
    out.append(f"- DTE percentiles (p10/p25/p50/p75/p90): "
               f"{int(dq.iloc[0])}/{int(dq.iloc[1])}/{int(dq.iloc[2])}/"
               f"{int(dq.iloc[3])}/{int(dq.iloc[4])}")
    # spread stats
    mid = df["mid"].where(df["mid"] > 0)
    sp = ((df["ask"] - df["bid"]) / mid).abs()
    spq = sp.quantile([.50, .75, .90, .99])
    out.append(f"- spread/mid p50/p75/p90/p99: "
               f"{spq.iloc[0]:.2%}/{spq.iloc[1]:.2%}/"
               f"{spq.iloc[2]:.2%}/{spq.iloc[3]:.2%}")
    # IV / Greeks coverage
    iv_miss = int(df["implied_volatility"].isna().sum())
    g_miss = {g: int(df[g].isna().sum()) for g in ("delta", "gamma", "theta", "vega")}
    out.append(f"- missing IV rows: {iv_miss} ({iv_miss/total:.1%})")
    out.append("- missing Greeks: " + ", ".join(
        f"{k}={v} ({v/total:.1%})" for k, v in g_miss.items()))
    # vol / OI
    zv = int((df["volume"].fillna(0) == 0).sum())
    zoi = int((df["open_interest"].fillna(0) == 0).sum())
    out.append(f"- zero-volume rows: {zv} ({zv/total:.1%}); "
               f"zero open-interest rows: {zoi} ({zoi/total:.1%})")
    out.append(f"- avg open_interest: {df['open_interest'].fillna(0).astype(float).mean():,.0f}; "
               f"avg volume: {df['volume'].fillna(0).astype(float).mean():,.0f}")
    # rejections
    rr = rejection_reasons(df, OptionsQualityThresholds())
    counts = {c: int(rr[c].sum()) for c in rr.columns if c != "any_reject"}
    out.append(f"- any_reject rows: {int(rr['any_reject'].sum())}")
    nonzero = {k: v for k, v in counts.items() if v > 0}
    if nonzero:
        out.append("- rejections by reason:")
        for k, v in sorted(nonzero.items(), key=lambda kv: -kv[1]):
            out.append(f"  - {k}: {v} ({v/total:.1%})")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default=None,
                    help="filter to one provider (synthetic/thetadata)")
    args = ap.parse_args()

    groups = _scan_cache(args.provider)
    if not groups:
        print("No cached options data found under data/options/raw/. "
              "Run scripts/options_sample_workflow.py first.")
        return 1

    out_dir = project_root() / "reports" / "options"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "options_quality_report.md"

    buf: list[str] = ["# Options Data Quality Report (V4)", "",
                       "_Read-only over the local cache; no network, no broker._",
                       ""]
    grand_rows = 0
    for (prov, und, kind), paths in sorted(groups.items()):
        df = _load_panel(paths)
        grand_rows += len(df)
        label = f"{prov} / {und} [{kind}]  ({len(paths)} files)"
        _section(label, _format_section(f"{prov}/{und}/{kind}", df), buf)

    buf.insert(2, f"**total rows across cache:** {grand_rows:,}  ")
    out_path.write_text("\n".join(buf), encoding="utf-8")
    print("\n".join(buf))
    print(f"\nMarkdown written to: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
