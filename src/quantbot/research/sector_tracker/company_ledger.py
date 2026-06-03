"""V6.7 — Company-level signal ledger (append-only, decision-support only).

Promotes the V6.5.x dashboard's in-memory "Company Lens" view into a stored,
dated, append-only company signal ledger. One row per company per run.

The ledger is **derived strictly from the existing sector-tracker catalysts**
(``data/research/sector_tracker/*_thesis_tracker.csv``). It does NOT:

  * invent any company-level score
  * add new numeric scoring
  * fetch from the network
  * import a broker, IBKR API, or order module
  * mutate V6.1 schema / scoring / driver / report-writer / dashboard logic
  * feed the sector score (V6.8 may aggregate later — V6.7 does not)

``quantbot.LIVE_TRADING_ENABLED`` stays ``False``.

The categorical ``read`` enum (``BULL`` / ``NEUTRAL`` / ``NEAR_THRESHOLD`` /
``BROKEN`` / ``MIXED`` / ``TRACKED`` / ``N/A``) and its derivation mirror the
dashboard's ``derive_company_read`` exactly. A parity test in
``tests/test_company_ledger.py`` asserts the two stay in lock-step.

V6.7 ships:
  * :class:`CompanyLedgerRow` dataclass + :data:`LEDGER_FIELDS` CSV order
  * :data:`COMPANY_LEDGER_UNIVERSE` — semiconductor / AI / energy companies
    matching the dashboard's pre-declared mapping
  * pure :func:`derive_read_for_company` + :func:`short_phrases_for_company`
  * pure :func:`build_company_ledger_rows`
  * I/O helpers: :func:`load_company_ledger`,
    :func:`ensure_company_ledger_header`, :func:`append_company_ledger_rows`
    (idempotent / append / strict modes)
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Mapping

from .schema import Catalyst

# --------------------------------------------------------------------------- #
# Enumerations
# --------------------------------------------------------------------------- #
ALLOWED_READ: frozenset[str] = frozenset({
    "BULL", "NEUTRAL", "NEAR_THRESHOLD", "BROKEN",
    "MIXED", "TRACKED", "N/A",
})

LEDGER_FIELDS: tuple[str, ...] = (
    "run_id", "timestamp", "date", "ticker", "company_or_label",
    "sector", "theme", "read", "why_short", "main_risk_short",
    "linked_catalysts", "n_linked_present", "n_linked_total",
    "source_files", "source_dates", "is_manual_or_tracked_context",
    "reason", "notes",
)


# --------------------------------------------------------------------------- #
# Pre-declared universe — mirrors apps/sector_thesis_dashboard.COMPANY_CATALYSTS.
# Parity test ensures the two never drift.
# --------------------------------------------------------------------------- #
COMPANY_LEDGER_UNIVERSE: dict[str, list[dict]] = {
    "SEMICONDUCTOR": [
        {"ticker": "NVDA", "company_or_label": "NVDA",
         "theme": "AI accelerator",
         "catalysts": ["SEMI-NVDA-REV-T1", "SEMI-NVDA-GM-T1",
                       "SEMI-NVDA-DC-REV-T1", "SEMI-INVENTORY-CYCLE-T2"]},
        {"ticker": "AMD", "company_or_label": "AMD",
         "theme": "AI accelerator",
         "catalysts": ["SEMI-AMD-REV-T2", "SEMI-INVENTORY-CYCLE-T2"]},
        {"ticker": "AVGO", "company_or_label": "AVGO",
         "theme": "AI custom silicon / networking",
         "catalysts": ["SEMI-AVGO-REV-T2", "SEMI-INVENTORY-CYCLE-T2"]},
        {"ticker": "MU", "company_or_label": "MU",
         "theme": "memory / HBM",
         "catalysts": ["SEMI-MU-HBM-REV-T1", "SEMI-MU-MEMCYCLE-NI-T1",
                       "SEMI-INVENTORY-CYCLE-T2"]},
        {"ticker": "AMAT", "company_or_label": "AMAT",
         "theme": "wafer-fab equipment",
         "catalysts": ["SEMI-EQUIPMENT-DEMAND-T2"]},
        {"ticker": "LRCX", "company_or_label": "LRCX",
         "theme": "wafer-fab equipment",
         "catalysts": ["SEMI-EQUIPMENT-DEMAND-T2"]},
        {"ticker": "KLAC", "company_or_label": "KLAC",
         "theme": "wafer-fab equipment",
         "catalysts": ["SEMI-EQUIPMENT-DEMAND-T2"]},
        {"ticker": "TSM", "company_or_label": "TSM",
         "theme": "foundry",
         "catalysts": ["SEMI-TSM-N3-DEMAND-T1"]},
        {"ticker": "ASML", "company_or_label": "ASML",
         "theme": "lithography / EUV",
         "catalysts": ["SEMI-ASML-BOOKINGS-T1"]},
    ],
    "AI": [
        {"ticker": "MSFT", "company_or_label": "MSFT",
         "theme": "hyperscaler",
         "catalysts": ["AI-MSFT-REV-T1", "AI-MSFT-OPMARGIN-T2",
                       "AI-HYPERSCALER-CAPEX-T1"]},
        {"ticker": "GOOGL", "company_or_label": "GOOGL",
         "theme": "hyperscaler",
         "catalysts": ["AI-GOOGL-REV-T1", "AI-GOOGL-OPMARGIN-T2",
                       "AI-HYPERSCALER-CAPEX-T1"]},
        {"ticker": "AMZN", "company_or_label": "AMZN",
         "theme": "hyperscaler",
         "catalysts": ["AI-AMZN-REV-T1", "AI-HYPERSCALER-CAPEX-T1"]},
        {"ticker": "META", "company_or_label": "META",
         "theme": "hyperscaler",
         "catalysts": ["AI-META-REV-T1", "AI-HYPERSCALER-CAPEX-T1"]},
        {"ticker": "ORCL", "company_or_label": "ORCL",
         "theme": "cloud infrastructure",
         "catalysts": ["AI-ORCL-REV-T1"]},
        {"ticker": "PLTR", "company_or_label": "PLTR",
         "theme": "enterprise AI",
         "catalysts": ["AI-PLTR-REV-T2"]},
        {"ticker": "OpenAI", "company_or_label": "OpenAI",
         "theme": "frontier AI lab (private)",
         "catalysts": ["AI-OPENAI-ARR-T1"]},
        {"ticker": "Anthropic", "company_or_label": "Anthropic",
         "theme": "frontier AI lab (private)",
         "catalysts": ["AI-ANTHROPIC-ARR-T1"]},
    ],
    "ENERGY": [
        {"ticker": "GEV", "company_or_label": "GEV",
         "theme": "AI power / turbines",
         "catalysts": ["ENER-GEV-REV-T1"]},
        {"ticker": "ETN", "company_or_label": "ETN",
         "theme": "AI power / electrical",
         "catalysts": ["ENER-ETN-REV-T1"]},
        {"ticker": "VRT", "company_or_label": "VRT",
         "theme": "AI power / data-center",
         "catalysts": ["ENER-VRT-REV-T1"]},
        {"ticker": "PWR", "company_or_label": "PWR",
         "theme": "AI power / grid construction",
         "catalysts": ["ENER-PWR-REV-T1"]},
        {"ticker": "CEG", "company_or_label": "CEG",
         "theme": "AI power / nuclear",
         "catalysts": ["ENER-CEG-REV-T1"]},
        {"ticker": "NEE", "company_or_label": "NEE",
         "theme": "utility / renewables",
         "catalysts": ["ENER-NEE-REV-T2"]},
        {"ticker": "SO", "company_or_label": "SO",
         "theme": "utility",
         "catalysts": ["ENER-SO-REV-T2"]},
        {"ticker": "XOM", "company_or_label": "XOM",
         "theme": "integrated oil & gas",
         "catalysts": ["ENER-XOM-REV-T1", "ENER-OILGAS-OCF-T2"]},
        {"ticker": "CVX", "company_or_label": "CVX",
         "theme": "integrated oil & gas",
         "catalysts": ["ENER-CVX-REV-T1", "ENER-OILGAS-OCF-T2"]},
        {"ticker": "COP", "company_or_label": "COP",
         "theme": "US shale / upstream",
         "catalysts": ["ENER-COP-REV-T2", "ENER-OILGAS-OCF-T2"]},
    ],
}


class CompanyLedgerSchemaError(ValueError):
    """Raised when a CompanyLedgerRow fails validation."""


# --------------------------------------------------------------------------- #
# Dataclass
# --------------------------------------------------------------------------- #
@dataclass
class CompanyLedgerRow:
    """One row of the V6.7 company signal ledger.

    Fields are deliberately string-typed for stable CSV serialisation. The
    only enumerated field is ``read``; everything else is free-text composed
    from already-loaded catalyst data.
    """

    run_id: str
    timestamp: str
    date: str
    ticker: str
    company_or_label: str
    sector: str
    theme: str
    read: str
    why_short: str
    main_risk_short: str
    linked_catalysts: str        # ";"-joined list of catalyst_ids
    n_linked_present: int
    n_linked_total: int
    source_files: str            # ";"-joined source_type:source_detail pairs
    source_dates: str            # ";"-joined catalyst.last_updated values
    is_manual_or_tracked_context: str  # "true" / "false"
    reason: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.run_id:
            raise CompanyLedgerSchemaError("run_id is required (non-empty)")
        if not self.timestamp:
            raise CompanyLedgerSchemaError("timestamp is required (non-empty)")
        if not self.ticker:
            raise CompanyLedgerSchemaError("ticker is required (non-empty)")
        if not self.sector:
            raise CompanyLedgerSchemaError("sector is required (non-empty)")
        if self.read not in ALLOWED_READ:
            raise CompanyLedgerSchemaError(
                f"read must be in {sorted(ALLOWED_READ)}, got {self.read!r}"
            )
        if self.is_manual_or_tracked_context not in {"true", "false"}:
            raise CompanyLedgerSchemaError(
                "is_manual_or_tracked_context must be 'true' or 'false', "
                f"got {self.is_manual_or_tracked_context!r}"
            )
        if not isinstance(self.n_linked_present, int):
            raise CompanyLedgerSchemaError(
                f"n_linked_present must be int, got {type(self.n_linked_present).__name__}"
            )
        if not isinstance(self.n_linked_total, int):
            raise CompanyLedgerSchemaError(
                f"n_linked_total must be int, got {type(self.n_linked_total).__name__}"
            )
        if self.n_linked_present < 0 or self.n_linked_total < 0:
            raise CompanyLedgerSchemaError(
                "n_linked_present and n_linked_total must be non-negative"
            )

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- #
# Pure derivation — mirrors dashboard's logic; parity-tested.
# --------------------------------------------------------------------------- #
_COMPACT_LABEL_LOOKUP: dict[str, str] = {
    "NVDA-REV": "Revenue",
    "NVDA-GM": "Gross margin",
    "NVDA-DC-REV": "DC revenue",
    "AMD-REV": "Revenue",
    "AVGO-REV": "Revenue",
    "MU-HBM-REV": "HBM revenue",
    "MU-MEMCYCLE-NI": "Memory NI",
    "INVENTORY-CYCLE": "Inventory cycle",
    "EQUIPMENT-DEMAND": "Equipment demand",
    "TSM-N3-DEMAND": "Advanced-node demand",
    "ASML-BOOKINGS": "EUV bookings",
    "MSFT-REV": "Revenue",
    "GOOGL-REV": "Revenue",
    "AMZN-REV": "Revenue",
    "META-REV": "Revenue",
    "ORCL-REV": "Revenue",
    "PLTR-REV": "Revenue",
    "MSFT-OPMARGIN": "Op margin",
    "GOOGL-OPMARGIN": "Op margin",
    "HYPERSCALER-CAPEX": "Hyperscaler capex",
    "RD-GROWTH": "R&D growth",
    "OPENAI-ARR": "OpenAI ARR",
    "ANTHROPIC-ARR": "Anthropic ARR",
    "REGULATION-RISK": "Regulation risk",
    "MODEL-PRICING": "Model pricing",
    "ENTERPRISE-ROI": "Enterprise AI ROI",
    "CUSTOM-SILICON": "Custom-silicon risk",
    "GEV-REV": "Revenue",
    "ETN-REV": "Revenue",
    "VRT-REV": "Revenue",
    "PWR-REV": "Revenue",
    "CEG-REV": "Revenue",
    "NEE-REV": "Revenue",
    "SO-REV": "Revenue",
    "XOM-REV": "Revenue",
    "CVX-REV": "Revenue",
    "COP-REV": "Revenue",
    "OILGAS-OCF": "Oil & gas OCF",
    "DATACENTER-POWER-DEMAND": "Data-center power",
    "NUCLEAR-SMR": "Nuclear/SMR",
    "REGULATORY-RATECASE": "Rate-case risk",
    "COMMODITY-OIL": "Crude oil",
    "LNG-CONTRACTS": "LNG contracts",
    "MACRO-RATES": "Long-end rates",
    "MACRO-VOL": "VIX",
    "MACRO-CURVE": "2s10s curve",
    "CHINA-EXPORT-RISK": "China export risk",
    "OPTIONS-RISK": "Options-market risk",
}


def _compact_label(c: Catalyst) -> str:
    """Short human-readable label for a catalyst (mirrors dashboard)."""
    parts = c.catalyst_id.split("-")
    if parts and parts[0] in {"SEMI", "AI", "ENER"}:
        parts = parts[1:]
    if parts and parts[-1].startswith("T") and parts[-1][1:].isdigit():
        parts = parts[:-1]
    key = "-".join(parts)
    if key in _COMPACT_LABEL_LOOKUP:
        return _COMPACT_LABEL_LOOKUP[key]
    return " ".join(p.title().replace("_", " ") for p in parts[-2:]) \
        if parts else c.catalyst_id


def _short_reason(found: list[Catalyst],
                  status_counts: dict[str, int]) -> str:
    parts: list[str] = []
    for c in found[:2]:
        cv = (c.current_value or "n/a").strip()
        if len(cv) > 32:
            cv = cv[:29] + "..."
        bits = c.catalyst_id.split("-", 2)
        label = bits[-1] if len(bits) > 1 else c.catalyst_id
        parts.append(f"{label} {cv}")
    summary = " · ".join(f"{n} {s}" for s, n in sorted(status_counts.items()))
    return "; ".join(parts) + f" ({summary})" if parts else summary


def _mixed_reason(found: list[Catalyst],
                  status_counts: dict[str, int]) -> str:
    bulls = [c for c in found if c.status == "BULL"]
    brokens = [c for c in found if c.status == "BROKEN"]
    nears = [c for c in found if c.status == "NEAR_THRESHOLD"]
    parts: list[str] = []
    if bulls:
        b = bulls[0]
        parts.append(
            f"{_compact_label(b)} {(b.current_value or '').strip()} BULL"
        )
    if brokens:
        x = brokens[0]
        parts.append(
            f"but {_compact_label(x)} "
            f"{(x.current_value or '').strip()} BROKEN"
        )
    elif nears:
        n = nears[0]
        parts.append(
            f"but {_compact_label(n)} "
            f"{(n.current_value or '').strip()} NEAR_THRESHOLD"
        )
    summary = " · ".join(
        f"{n_count} {s}" for s, n_count in sorted(status_counts.items())
    )
    return ("; ".join(parts) + f" ({summary})") if parts else summary


def derive_read_for_company(
    catalysts_by_id: Mapping[str, Catalyst],
    linked_ids: list[str],
) -> tuple[str, str, int]:
    """Return ``(read, reason, n_present)`` for one company.

    Mirrors the dashboard's ``derive_company_read`` exactly — the V6.5.2 rule
    set: BULL coexisting with BROKEN / NEAR_THRESHOLD → ``MIXED`` so bullish
    evidence is never hidden behind a single shared-risk break.
    """
    found = [catalysts_by_id[i] for i in linked_ids if i in catalysts_by_id]
    if not found:
        return "N/A", "no linked catalysts loaded — check driver output", 0
    n_present = len(found)
    if all(c.source_type == "MANUAL" and c.status == "NEUTRAL" for c in found):
        return ("TRACKED", "tracked context / no direct signal yet "
                "(manual placeholders only)", n_present)
    statuses = [c.status for c in found]
    status_counts = {s: statuses.count(s) for s in set(statuses)}
    has_bull = "BULL" in statuses
    has_broken = "BROKEN" in statuses
    has_near = "NEAR_THRESHOLD" in statuses
    has_neutral = "NEUTRAL" in statuses

    if has_bull and has_broken:
        return "MIXED", _mixed_reason(found, status_counts), n_present
    if has_broken:
        focus = [c for c in found if c.status == "BROKEN"]
        return "BROKEN", _short_reason(focus, status_counts), n_present
    if has_bull and has_near:
        return "MIXED", _mixed_reason(found, status_counts), n_present
    if has_near:
        focus = [c for c in found if c.status == "NEAR_THRESHOLD"]
        return "NEAR_THRESHOLD", _short_reason(focus, status_counts), n_present
    if has_bull and not has_neutral:
        focus = [c for c in found if c.status == "BULL"]
        return "BULL", _short_reason(focus, status_counts), n_present
    if not has_bull and has_neutral and not has_broken and not has_near:
        return "NEUTRAL", _short_reason(found, status_counts), n_present
    return "MIXED", _mixed_reason(found, status_counts), n_present


def short_phrases_for_company(found: list[Catalyst]) -> tuple[str, str]:
    """Return ``(why_short, main_risk_short)`` mirroring the dashboard."""
    if not found:
        return "no linked catalysts loaded", "—"
    if all(c.source_type == "MANUAL" and c.status == "NEUTRAL" for c in found):
        return "tracked context only", "—"

    bulls = [c for c in found if c.status == "BULL"]
    brokens = [c for c in found if c.status == "BROKEN"]
    nears = [c for c in found if c.status == "NEAR_THRESHOLD"]
    neutrals = [c for c in found if c.status == "NEUTRAL"]

    if bulls:
        b = bulls[0]
        why_short = f"{_compact_label(b)} {(b.current_value or '').strip()}"
    elif neutrals and any(c.source_type != "MANUAL" for c in neutrals):
        c = next(c for c in neutrals if c.source_type != "MANUAL")
        why_short = (f"{_compact_label(c)} "
                     f"{(c.current_value or '').strip()} (in-band)")
    else:
        why_short = "—"

    if brokens:
        x = brokens[0]
        main_risk_short = (f"{_compact_label(x)} "
                           f"{(x.current_value or '').strip()} BROKEN")
    elif nears:
        n = nears[0]
        main_risk_short = (f"{_compact_label(n)} "
                           f"{(n.current_value or '').strip()} NEAR")
    else:
        main_risk_short = "—"
    return why_short, main_risk_short


# --------------------------------------------------------------------------- #
# Row construction
# --------------------------------------------------------------------------- #
def _is_manual_or_tracked(found: list[Catalyst], read: str) -> bool:
    """Whether the row represents manual-only / placeholder context."""
    if read in {"TRACKED", "N/A"}:
        return True
    if not found:
        return True
    return all(c.source_type == "MANUAL" for c in found)


def build_company_ledger_rows(
    catalysts_by_sector: Mapping[str, list[Catalyst]],
    *,
    run_id: str,
    timestamp: str,
    as_of_date: str,
    universe: Mapping[str, list[dict]] | None = None,
    notes: str = "",
) -> list[CompanyLedgerRow]:
    """Build one :class:`CompanyLedgerRow` per company in ``universe``.

    Parameters
    ----------
    catalysts_by_sector
        Mapping ``{sector: [Catalyst, ...]}``. Sectors that map to ``None``
        or an empty list are tolerated — companies in those sectors will be
        emitted with ``read == "N/A"``.
    run_id, timestamp, as_of_date
        Caller-supplied so the build is reproducible and deterministic given
        the same inputs (no time-of-day side effects in this function).
    universe
        Optional override of :data:`COMPANY_LEDGER_UNIVERSE`.
    notes
        Optional per-build note copied onto every emitted row.
    """
    uni = universe if universe is not None else COMPANY_LEDGER_UNIVERSE
    rows: list[CompanyLedgerRow] = []

    for sector, companies in uni.items():
        cats = list(catalysts_by_sector.get(sector) or [])
        by_id = {c.catalyst_id: c for c in cats}

        for comp in companies:
            linked_ids: list[str] = list(comp["catalysts"])
            found = [by_id[i] for i in linked_ids if i in by_id]
            read, reason, n_present = derive_read_for_company(by_id, linked_ids)
            why_short, main_risk_short = short_phrases_for_company(found)

            src_files = ";".join(
                f"{c.source_type}:{c.source_detail}" for c in found
            )
            src_dates = ";".join(c.last_updated for c in found)
            tracked = "true" if _is_manual_or_tracked(found, read) else "false"

            rows.append(CompanyLedgerRow(
                run_id=run_id,
                timestamp=timestamp,
                date=as_of_date,
                ticker=comp["ticker"],
                company_or_label=comp.get("company_or_label", comp["ticker"]),
                sector=sector,
                theme=comp["theme"],
                read=read,
                why_short=why_short,
                main_risk_short=main_risk_short,
                linked_catalysts=";".join(linked_ids),
                n_linked_present=n_present,
                n_linked_total=len(linked_ids),
                source_files=src_files,
                source_dates=src_dates,
                is_manual_or_tracked_context=tracked,
                reason=reason,
                notes=notes,
            ))
    return rows


# --------------------------------------------------------------------------- #
# I/O — append-only with explicit idempotent mode
# --------------------------------------------------------------------------- #
def load_company_ledger(path: str | Path) -> list[CompanyLedgerRow]:
    """Read the company ledger. ``[]`` if the file is missing."""
    p = Path(path)
    if not p.is_file():
        return []
    out: list[CompanyLedgerRow] = []
    with p.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for r in reader:
            kwargs: dict = {k: r.get(k, "") for k in LEDGER_FIELDS}
            for int_field in ("n_linked_present", "n_linked_total"):
                raw = kwargs.get(int_field, "")
                try:
                    kwargs[int_field] = int(raw) if str(raw) != "" else 0
                except (TypeError, ValueError) as exc:
                    raise CompanyLedgerSchemaError(
                        f"{int_field} must be int, got {raw!r}"
                    ) from exc
            out.append(CompanyLedgerRow(**kwargs))
    return out


def ensure_company_ledger_header(path: str | Path) -> Path:
    """Write the header row if the file is missing or empty.

    Existing rows are NEVER touched. Returns the resolved Path.
    """
    p = Path(path)
    if p.is_file() and p.stat().st_size > 0:
        return p
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(LEDGER_FIELDS))
        writer.writeheader()
    return p


def _existing_keys(path: Path) -> set[tuple[str, str, str]]:
    """Set of ``(run_id, sector, ticker)`` tuples already in the ledger."""
    if not path.is_file() or path.stat().st_size == 0:
        return set()
    keys: set[tuple[str, str, str]] = set()
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for r in reader:
            keys.add((r.get("run_id", ""), r.get("sector", ""),
                      r.get("ticker", "")))
    return keys


def append_company_ledger_rows(
    rows: Iterable[CompanyLedgerRow],
    path: str | Path,
    *,
    mode: str = "idempotent",
) -> dict:
    """Append rows to the ledger at ``path``. Append-only — never truncates.

    Modes
    -----
    ``"idempotent"`` (default)
        Skip any input row whose ``(run_id, sector, ticker)`` already exists
        in the file. Safe to re-run with the same ``run_id`` — silently
        appends only genuinely new rows.

    ``"append"``
        Append every input row unconditionally. Use only when intentionally
        emitting multiple snapshots per run (and document why).

    ``"strict"``
        Raise :class:`CompanyLedgerSchemaError` if any input row collides with
        an existing ``(run_id, sector, ticker)``. Use in CI / tests where a
        duplicate write must fail loudly.

    Returns ``{"n_input": N, "n_appended": M, "n_skipped": S}``.
    """
    if mode not in {"idempotent", "append", "strict"}:
        raise ValueError(
            f"mode must be 'idempotent' / 'append' / 'strict', got {mode!r}"
        )

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    existing = _existing_keys(p)
    needs_header = not p.is_file() or p.stat().st_size == 0

    rows_list = list(rows)
    n_input = len(rows_list)
    to_write: list[CompanyLedgerRow] = []
    n_skipped = 0

    for r in rows_list:
        key = (r.run_id, r.sector, r.ticker)
        if key in existing:
            if mode == "strict":
                raise CompanyLedgerSchemaError(
                    f"duplicate ledger key already in file: {key!r}"
                )
            if mode == "idempotent":
                n_skipped += 1
                continue
            # mode == "append" — fall through and write anyway
        to_write.append(r)
        existing.add(key)  # prevents duplicate writes within the same batch

    with p.open("a", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(LEDGER_FIELDS))
        if needs_header:
            writer.writeheader()
        for r in to_write:
            writer.writerow(r.to_dict())

    return {
        "n_input": n_input,
        "n_appended": len(to_write),
        "n_skipped": n_skipped,
    }


__all__ = [
    # enums + constants
    "ALLOWED_READ", "LEDGER_FIELDS", "COMPANY_LEDGER_UNIVERSE",
    # schema
    "CompanyLedgerRow", "CompanyLedgerSchemaError",
    # derivation
    "derive_read_for_company", "short_phrases_for_company",
    # row construction
    "build_company_ledger_rows",
    # I/O
    "load_company_ledger", "ensure_company_ledger_header",
    "append_company_ledger_rows",
]
