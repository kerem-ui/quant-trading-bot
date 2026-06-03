"""V7.8.1 — MarketPulse data-population helper (manual + cache-only).

Append one validated row to one of the three MarketPulse CSVs under
``data/research/marketpulse/``. **Manual entries only, plus a cache-only
read of an existing local FRED CSV** at ``data/macro/fred/<SERIES>.csv``.

The script does NOT:
  * connect to a broker / send an order
  * fetch from the network — including the FRED HTTP API
  * scrape news / web pages
  * mutate sector scoring or any V6 artefact
  * touch ThetaData or any live options feed
  * affect ``LIVE_TRADING_ENABLED`` (stays ``False``)

It DOES:
  * validate every row via the V7.8 dataclasses + a few extra non-empty
    checks the operator workflow needs
  * APPEND one row in append-mode (with explicit idempotent / append /
    strict modes mirroring V6.6.1 / V6.7 / V6.8 / V6.6.2)
  * read a single pre-existing local FRED cache file for the optional
    ``from-fred`` subcommand (cache-only; fails clearly when missing)

Manual entry examples:

    # Regime row (one panel snapshot)
    python scripts/populate_marketpulse.py add-regime \\
        --panel RATES --indicator "10Y Treasury yield" \\
        --value "4.45" --status NEUTRAL \\
        --interpretation "mid-range" --source FRED \\
        --source-file "dgs10.csv" --last-updated 2026-06-03

    # Sector ETF snapshot
    python scripts/populate_marketpulse.py add-etf \\
        --ticker SPY --sector BROAD --theme "benchmark" \\
        --price 500.00 --return-1d "+0.5%" --return-1w "+1.0%" \\
        --return-1m "+3.0%" --trend-status UPTREND \\
        --risk-note "above 50/200dma" --source MANUAL \\
        --last-updated 2026-06-03

    # Economic event row
    python scripts/populate_marketpulse.py add-event \\
        --date 2026-06-11 --time 08:30 --country US \\
        --event "CPI YoY" --expected "2.7%" --prior "2.8%" \\
        --impact HIGH --notes "core focus" --source MANUAL \\
        --last-updated 2026-06-03

    # FRED cache helper (cache-only — no network)
    python scripts/populate_marketpulse.py from-fred \\
        --series DGS10 --panel RATES \\
        --indicator "10Y Treasury yield" --status NEUTRAL \\
        --interpretation "latest cache observation"

``quantbot.LIVE_TRADING_ENABLED`` stays ``False``.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

import quantbot
from quantbot.research.marketpulse import (
    ALLOWED_EVENT_IMPACT,
    ALLOWED_REGIME_PANELS,
    ALLOWED_REGIME_STATUS,
    ALLOWED_TREND_STATUS,
    DEFAULT_EVENT_CALENDAR_FILE,
    DEFAULT_REGIME_DASHBOARD_FILE,
    DEFAULT_SECTOR_ETF_SCOREBOARD_FILE,
    EventCalendarRow,
    MarketPulseSchemaError,
    RegimeRow,
    SectorETFRow,
    append_event_calendar_rows,
    append_regime_rows,
    append_sector_etf_rows,
    ensure_event_calendar_header,
    ensure_regime_dashboard_header,
    ensure_sector_etf_scoreboard_header,
)

DEFAULT_FRED_CACHE_DIR: Path = ROOT / "data" / "macro" / "fred"


class PopulateMarketPulseValidationError(ValueError):
    """Raised when an operator-supplied row fails CLI-level checks beyond
    the V7.8 dataclass schema (e.g. empty value / source)."""


def _require_non_empty(value: str, name: str) -> None:
    if not value or not value.strip():
        raise PopulateMarketPulseValidationError(
            f"{name} must be non-empty"
        )


# --------------------------------------------------------------------------- #
# Python entry points (testable without argparse)
# --------------------------------------------------------------------------- #
def add_regime_row(
    *,
    panel: str,
    indicator: str,
    value: str,
    status: str,
    interpretation: str = "",
    source: str = "",
    source_file: str = "",
    last_updated: str = "",
    mode: str = "idempotent",
    path: Path | str | None = None,
) -> dict:
    """Validate + append a single regime-dashboard row."""
    assert quantbot.LIVE_TRADING_ENABLED is False, \
        "V7.8.1 populate helper is RESEARCH only."
    _require_non_empty(panel, "panel")
    _require_non_empty(indicator, "indicator")
    _require_non_empty(value, "value")
    _require_non_empty(status, "status")
    if panel not in ALLOWED_REGIME_PANELS:
        raise PopulateMarketPulseValidationError(
            f"panel must be in {sorted(ALLOWED_REGIME_PANELS)}, "
            f"got {panel!r}"
        )
    if status not in ALLOWED_REGIME_STATUS:
        raise PopulateMarketPulseValidationError(
            f"status must be in {sorted(ALLOWED_REGIME_STATUS)}, "
            f"got {status!r}"
        )

    p = Path(path) if path else DEFAULT_REGIME_DASHBOARD_FILE
    row = RegimeRow(
        panel=panel, indicator=indicator, value=value, status=status,
        interpretation=interpretation, source=source,
        source_file=source_file, last_updated=last_updated,
    )
    ensure_regime_dashboard_header(p)
    result = append_regime_rows([row], p, mode=mode)
    return {"path": str(p), "row_kind": "regime", **result}


def add_etf_row(
    *,
    ticker: str,
    sector: str,
    theme: str = "",
    price: str = "",
    return_1d: str = "",
    return_1w: str = "",
    return_1m: str = "",
    trend_status: str = "N_A",
    risk_note: str = "",
    source: str = "",
    last_updated: str = "",
    mode: str = "idempotent",
    path: Path | str | None = None,
) -> dict:
    """Validate + append a single sector-ETF scoreboard row."""
    assert quantbot.LIVE_TRADING_ENABLED is False, \
        "V7.8.1 populate helper is RESEARCH only."
    _require_non_empty(ticker, "ticker")
    _require_non_empty(sector, "sector")
    if trend_status not in ALLOWED_TREND_STATUS:
        raise PopulateMarketPulseValidationError(
            f"trend_status must be in {sorted(ALLOWED_TREND_STATUS)}, "
            f"got {trend_status!r}"
        )

    p = Path(path) if path else DEFAULT_SECTOR_ETF_SCOREBOARD_FILE
    row = SectorETFRow(
        ticker=ticker, sector=sector, theme=theme, price=price,
        return_1d=return_1d, return_1w=return_1w, return_1m=return_1m,
        trend_status=trend_status, risk_note=risk_note,
        source=source, last_updated=last_updated,
    )
    ensure_sector_etf_scoreboard_header(p)
    result = append_sector_etf_rows([row], p, mode=mode)
    return {"path": str(p), "row_kind": "etf", **result}


def add_event_row(
    *,
    date: str,
    event: str,
    time: str = "",
    country: str = "",
    expected: str = "",
    actual: str = "",
    prior: str = "",
    impact: str = "N_A",
    notes: str = "",
    source: str = "",
    last_updated: str = "",
    mode: str = "idempotent",
    path: Path | str | None = None,
) -> dict:
    """Validate + append a single economic-event row."""
    assert quantbot.LIVE_TRADING_ENABLED is False, \
        "V7.8.1 populate helper is RESEARCH only."
    _require_non_empty(date, "date")
    _require_non_empty(event, "event")
    if impact not in ALLOWED_EVENT_IMPACT:
        raise PopulateMarketPulseValidationError(
            f"impact must be in {sorted(ALLOWED_EVENT_IMPACT)}, "
            f"got {impact!r}"
        )

    p = Path(path) if path else DEFAULT_EVENT_CALENDAR_FILE
    row = EventCalendarRow(
        date=date, event=event, time=time, country=country,
        expected=expected, actual=actual, prior=prior, impact=impact,
        notes=notes, source=source, last_updated=last_updated,
    )
    ensure_event_calendar_header(p)
    result = append_event_calendar_rows([row], p, mode=mode)
    return {"path": str(p), "row_kind": "event", **result}


def _read_latest_fred_cache(cache_path: Path) -> tuple[str, str]:
    """Return ``(date, value)`` from the LAST row of a FRED cache CSV.

    Cache-only — no network. The cache file is the simple
    ``data/macro/fred/<SERIES>.csv`` shape ``date,value``. Missing file or
    empty cache raises :class:`PopulateMarketPulseValidationError` with a
    clear message; nothing silently fetches.
    """
    if not cache_path.is_file():
        raise PopulateMarketPulseValidationError(
            f"FRED cache file not found at {cache_path}. The populate "
            "helper does NOT fetch from FRED — point --cache at an "
            "existing cache CSV or run an existing cache builder first."
        )
    last: tuple[str, str] | None = None
    with cache_path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None or "date" not in reader.fieldnames \
                or "value" not in reader.fieldnames:
            raise PopulateMarketPulseValidationError(
                f"FRED cache {cache_path} must have columns 'date,value'; "
                f"found {reader.fieldnames!r}."
            )
        for r in reader:
            d = (r.get("date") or "").strip()
            v = (r.get("value") or "").strip()
            if d and v:
                last = (d, v)
    if last is None:
        raise PopulateMarketPulseValidationError(
            f"FRED cache {cache_path} has no usable data rows."
        )
    return last


def from_fred(
    *,
    series: str,
    panel: str,
    indicator: str,
    status: str = "N_A",
    interpretation: str = "",
    source_file: str = "",
    cache_dir: Path | str | None = None,
    cache_path: Path | str | None = None,
    last_updated: str | None = None,
    mode: str = "idempotent",
    path: Path | str | None = None,
) -> dict:
    """Read a local FRED cache and append a regime row.

    Strictly cache-only. ``cache_path`` overrides the default
    ``data/macro/fred/<series>.csv`` lookup. ``last_updated`` defaults to
    the date of the last row in the cache; ``source_file`` defaults to the
    cache file name.
    """
    assert quantbot.LIVE_TRADING_ENABLED is False, \
        "V7.8.1 populate helper is RESEARCH only."
    _require_non_empty(series, "series")

    if cache_path is not None:
        cpath = Path(cache_path)
    else:
        cdir = Path(cache_dir) if cache_dir else DEFAULT_FRED_CACHE_DIR
        cpath = cdir / f"{series}.csv"

    cache_date, cache_value = _read_latest_fred_cache(cpath)
    return add_regime_row(
        panel=panel,
        indicator=indicator,
        value=cache_value,
        status=status,
        interpretation=interpretation,
        source="FRED_CACHE",
        source_file=source_file or cpath.name,
        last_updated=last_updated or cache_date,
        mode=mode,
        path=path,
    )


# --------------------------------------------------------------------------- #
# argparse CLI
# --------------------------------------------------------------------------- #
def _add_common_mode(sub: argparse.ArgumentParser) -> None:
    sub.add_argument(
        "--mode",
        choices=("idempotent", "append", "strict"),
        default="idempotent",
        help="Write mode (default: idempotent).",
    )


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=("V7.8.1 — MarketPulse data-population helper. "
                     "Manual entries + cache-only FRED reads. No network. "
                     "No trading. No broker."),
    )
    sub = ap.add_subparsers(dest="subcommand", required=True)

    # --- add-regime ---------------------------------------------------- #
    p_regime = sub.add_parser(
        "add-regime",
        help="Append one row to data/research/marketpulse/regime_dashboard.csv",
    )
    p_regime.add_argument("--panel", required=True,
                            choices=sorted(ALLOWED_REGIME_PANELS))
    p_regime.add_argument("--indicator", required=True)
    p_regime.add_argument("--value", required=True)
    p_regime.add_argument("--status", required=True,
                            choices=sorted(ALLOWED_REGIME_STATUS))
    p_regime.add_argument("--interpretation", default="")
    p_regime.add_argument("--source", default="")
    p_regime.add_argument("--source-file", default="")
    p_regime.add_argument("--last-updated", default="")
    p_regime.add_argument("--path", default=None,
                            help="Override regime_dashboard.csv path.")
    _add_common_mode(p_regime)

    # --- add-etf ------------------------------------------------------- #
    p_etf = sub.add_parser(
        "add-etf",
        help=("Append one row to data/research/marketpulse/"
              "sector_etf_scoreboard.csv"),
    )
    p_etf.add_argument("--ticker", required=True)
    p_etf.add_argument("--sector", required=True)
    p_etf.add_argument("--theme", default="")
    p_etf.add_argument("--price", default="")
    p_etf.add_argument("--return-1d", default="")
    p_etf.add_argument("--return-1w", default="")
    p_etf.add_argument("--return-1m", default="")
    p_etf.add_argument("--trend-status", default="N_A",
                        choices=sorted(ALLOWED_TREND_STATUS))
    p_etf.add_argument("--risk-note", default="")
    p_etf.add_argument("--source", default="")
    p_etf.add_argument("--last-updated", default="")
    p_etf.add_argument("--path", default=None,
                        help="Override sector_etf_scoreboard.csv path.")
    _add_common_mode(p_etf)

    # --- add-event ----------------------------------------------------- #
    p_event = sub.add_parser(
        "add-event",
        help="Append one row to data/research/marketpulse/event_calendar.csv",
    )
    p_event.add_argument("--date", required=True)
    p_event.add_argument("--event", required=True)
    p_event.add_argument("--time", default="")
    p_event.add_argument("--country", default="")
    p_event.add_argument("--expected", default="")
    p_event.add_argument("--actual", default="")
    p_event.add_argument("--prior", default="")
    p_event.add_argument("--impact", default="N_A",
                          choices=sorted(ALLOWED_EVENT_IMPACT))
    p_event.add_argument("--notes", default="")
    p_event.add_argument("--source", default="")
    p_event.add_argument("--last-updated", default="")
    p_event.add_argument("--path", default=None,
                          help="Override event_calendar.csv path.")
    _add_common_mode(p_event)

    # --- from-fred (cache-only) --------------------------------------- #
    p_fred = sub.add_parser(
        "from-fred",
        help=("Append a regime row from an existing local FRED cache "
              "CSV (cache-only — never fetches from the network)."),
    )
    p_fred.add_argument("--series", required=True,
                         help="FRED series id (e.g. DGS10, DGS2, FEDFUNDS).")
    p_fred.add_argument("--panel", required=True,
                         choices=sorted(ALLOWED_REGIME_PANELS))
    p_fred.add_argument("--indicator", required=True)
    p_fred.add_argument("--status", default="N_A",
                         choices=sorted(ALLOWED_REGIME_STATUS))
    p_fred.add_argument("--interpretation", default="")
    p_fred.add_argument("--source-file", default="")
    p_fred.add_argument("--cache-dir", default=None,
                         help="Override data/macro/fred/ directory.")
    p_fred.add_argument("--cache", default=None,
                         help="Override the full path to the cache CSV.")
    p_fred.add_argument("--last-updated", default=None,
                         help=("Override the row's last_updated. "
                               "Default: date of the last cache row."))
    p_fred.add_argument("--path", default=None,
                         help="Override regime_dashboard.csv path.")
    _add_common_mode(p_fred)

    return ap


def cli(argv: list[str] | None = None) -> int:
    ap = _build_parser()
    args = ap.parse_args(argv)

    try:
        if args.subcommand == "add-regime":
            summary = add_regime_row(
                panel=args.panel,
                indicator=args.indicator,
                value=args.value,
                status=args.status,
                interpretation=args.interpretation,
                source=args.source,
                source_file=args.source_file,
                last_updated=args.last_updated,
                mode=args.mode,
                path=args.path,
            )
        elif args.subcommand == "add-etf":
            summary = add_etf_row(
                ticker=args.ticker,
                sector=args.sector,
                theme=args.theme,
                price=args.price,
                return_1d=args.return_1d,
                return_1w=args.return_1w,
                return_1m=args.return_1m,
                trend_status=args.trend_status,
                risk_note=args.risk_note,
                source=args.source,
                last_updated=args.last_updated,
                mode=args.mode,
                path=args.path,
            )
        elif args.subcommand == "add-event":
            summary = add_event_row(
                date=args.date,
                event=args.event,
                time=args.time,
                country=args.country,
                expected=args.expected,
                actual=args.actual,
                prior=args.prior,
                impact=args.impact,
                notes=args.notes,
                source=args.source,
                last_updated=args.last_updated,
                mode=args.mode,
                path=args.path,
            )
        elif args.subcommand == "from-fred":
            summary = from_fred(
                series=args.series,
                panel=args.panel,
                indicator=args.indicator,
                status=args.status,
                interpretation=args.interpretation,
                source_file=args.source_file,
                cache_dir=args.cache_dir,
                cache_path=args.cache,
                last_updated=args.last_updated,
                mode=args.mode,
                path=args.path,
            )
        else:
            ap.error(f"unknown subcommand {args.subcommand!r}")
            return 2
    except (PopulateMarketPulseValidationError,
            MarketPulseSchemaError) as exc:
        print(f"populate-marketpulse rejected: {exc}", file=sys.stderr)
        return 2

    print(
        f"Appended {summary['n_appended']} {summary['row_kind']} row(s) "
        f"(skipped {summary['n_skipped']}) "
        f"to {Path(summary['path']).name} [mode={args.mode}]."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
