"""V7.5.2 — Local SEC company-facts fundamentals reader (cache-only).

Reads existing local SEC EDGAR ``companyfacts`` JSON files under
``data/company/sec/companyfacts/CIK<10-digit>.json`` and the
``data/company/sec/company_tickers.json`` ticker → CIK directory. **Never
fetches** any live SEC endpoint or any other network resource.

Pre-declared US-GAAP / DEI tag candidates (mirrors the philosophy of
``src/quantbot/company/company_facts.py``): for each friendly fundamentals
field, an ordered list of candidate concept tags is tried — first match
wins. The selection prefers the candidate whose most recent observation
is the freshest so that filers who switched tag over time (e.g. NVDA
moved from ``RevenueFromContractWithCustomerExcludingAssessedTax`` to
``Revenues`` after FY2022) surface the current data, not the stale one.

Valuation is computed **only** when a local price cache and the
SEC-supplied shares-outstanding value are both available. Otherwise the
valuation fields stay ``"n/a"`` and the snapshot carries an explicit
``valuation_note`` explaining why.

No network. No broker. No order. No live equity-price feed.
``quantbot.LIVE_TRADING_ENABLED`` stays ``False``.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

# Repo root (.../quant_trading_bot). Module sits four levels deep.
_THIS_FILE = Path(__file__).resolve()
ROOT = _THIS_FILE.parents[4]

DEFAULT_SEC_CACHE_DIR: Path = ROOT / "data" / "company" / "sec"
DEFAULT_COMPANYFACTS_DIR: Path = DEFAULT_SEC_CACHE_DIR / "companyfacts"
DEFAULT_TICKER_MAP_FILE: Path = (
    DEFAULT_SEC_CACHE_DIR / "company_tickers.json"
)


# --------------------------------------------------------------------------- #
# Pre-declared US-GAAP candidate tags
# --------------------------------------------------------------------------- #
# Friendly field -> ordered list of candidates. First match with any
# observation wins, with tie-break preferring the freshest candidate
# (mirrors the V6.2.1 ``_first_matching_tag`` selection policy).
GAAP_CANDIDATES: dict[str, list[str]] = {
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss"],
    "operating_cash_flow": [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment"],
    "inventory": ["InventoryNet"],
    "cash": [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ],
    "debt": [
        "LongTermDebt",
        "LongTermDebtNoncurrent",
        "DebtLongtermAndShorttermCombinedAmount",
    ],
    "shares_outstanding_gaap": [
        "CommonStockSharesOutstanding",
        "CommonStockSharesIssued",
    ],
}

# DEI concepts live under ``facts.dei`` not ``facts.us-gaap``.
DEI_CANDIDATES: dict[str, list[str]] = {
    "shares_outstanding_dei": [
        "EntityCommonStockSharesOutstanding",
    ],
}


FUNDAMENTALS_FIELDS: tuple[str, ...] = (
    "ticker", "cik", "cache_path",
    "latest_fiscal_period", "latest_report_date",
    "revenue", "revenue_yoy_pct",
    "gross_profit", "gross_margin_pct",
    "operating_income", "operating_margin_pct",
    "net_income",
    "operating_cash_flow", "capex", "free_cash_flow",
    "inventory", "inventory_yoy_pct",
    "debt", "cash", "shares_outstanding",
    "market_cap", "price_to_sales", "price_to_earnings",
    "price_to_free_cash_flow", "enterprise_value", "ev_to_sales",
    "data_gap_note", "valuation_note",
)


@dataclass(frozen=True)
class FundamentalsSnapshot:
    """Compact fundamentals + valuation summary for one ticker.

    Every numeric field is a string — formatted money for absolutes
    (``"$ 60.92B"``), percent strings for ratios (``"+65.50%"``), or the
    literal ``"n/a"`` when the cache lacks the relevant tag. The renderer
    never re-parses these.
    """

    ticker: str
    cik: str = ""
    cache_path: str = ""
    latest_fiscal_period: str = ""
    latest_report_date: str = ""
    revenue: str = "n/a"
    revenue_yoy_pct: str = "n/a"
    gross_profit: str = "n/a"
    gross_margin_pct: str = "n/a"
    operating_income: str = "n/a"
    operating_margin_pct: str = "n/a"
    net_income: str = "n/a"
    operating_cash_flow: str = "n/a"
    capex: str = "n/a"
    free_cash_flow: str = "n/a"
    inventory: str = "n/a"
    inventory_yoy_pct: str = "n/a"
    debt: str = "n/a"
    cash: str = "n/a"
    shares_outstanding: str = "n/a"
    # Valuation (only populated when local price cache + shares both available).
    market_cap: str = "n/a"
    price_to_sales: str = "n/a"
    price_to_earnings: str = "n/a"
    price_to_free_cash_flow: str = "n/a"
    enterprise_value: str = "n/a"
    ev_to_sales: str = "n/a"
    data_gap_note: str = ""
    valuation_note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- #
# Ticker → CIK + companyfacts loaders
# --------------------------------------------------------------------------- #
def load_ticker_to_cik_map(
    path: Path | str = DEFAULT_TICKER_MAP_FILE,
) -> dict[str, str]:
    """Return ``{TICKER: "CIK<10-digit>"}`` from the SEC ticker directory.

    Missing / unparseable file → ``{}``. The reader normalises the raw
    SEC JSON (``{idx: {cik_str, ticker, title}}``) into an upper-cased
    ticker key and a zero-padded CIK string.
    """
    p = Path(path)
    if not p.is_file():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[str, str] = {}
    if not isinstance(raw, dict):
        return out
    for rec in raw.values():
        if not isinstance(rec, dict):
            continue
        ticker = str(rec.get("ticker", "")).upper().strip()
        cik_raw = rec.get("cik_str", rec.get("cik"))
        if not ticker or cik_raw is None:
            continue
        try:
            out[ticker] = f"CIK{int(cik_raw):010d}"
        except (TypeError, ValueError):
            continue
    return out


def load_companyfacts_json(
    cik: str,
    *,
    companyfacts_dir: Path | str = DEFAULT_COMPANYFACTS_DIR,
) -> dict | None:
    """Load the parsed companyfacts JSON for ``cik``. ``None`` on miss.

    Strictly cache-only. Network is never touched.
    """
    if not cik:
        return None
    p = Path(companyfacts_dir) / f"{cik}.json"
    if not p.is_file() or p.stat().st_size == 0:
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def companyfacts_path_for_ticker(
    ticker: str,
    *,
    ticker_map_path: Path | str = DEFAULT_TICKER_MAP_FILE,
    companyfacts_dir: Path | str = DEFAULT_COMPANYFACTS_DIR,
) -> tuple[str, Path | None]:
    """Resolve ``ticker`` to ``(cik, cache_path_or_None)``.

    Returns the empty string + None when the ticker cannot be mapped (e.g.
    foreign filers like TSM / ASML that have no US SEC filings).
    """
    tmap = load_ticker_to_cik_map(ticker_map_path)
    cik = tmap.get(str(ticker).upper().strip(), "")
    if not cik:
        return "", None
    p = Path(companyfacts_dir) / f"{cik}.json"
    return cik, (p if p.is_file() else None)


# --------------------------------------------------------------------------- #
# Pure tag extraction helpers
# --------------------------------------------------------------------------- #
def _facts_subtree(facts_json: dict | None, taxonomy: str) -> dict:
    if not isinstance(facts_json, dict):
        return {}
    facts = facts_json.get("facts")
    if not isinstance(facts, dict):
        return {}
    sub = facts.get(taxonomy)
    return sub if isinstance(sub, dict) else {}


def _latest_end_for_tag(node: dict | None) -> str:
    """Return the latest ``end`` ISO date across every observation in
    ``node["units"]``. Empty string when the tag has no observations."""
    if not isinstance(node, dict):
        return ""
    units = node.get("units")
    if not isinstance(units, dict):
        return ""
    latest = ""
    for obs_list in units.values():
        if not isinstance(obs_list, list):
            continue
        for obs in obs_list:
            if isinstance(obs, dict):
                end = str(obs.get("end") or "")
                if end > latest:
                    latest = end
    return latest


def _pick_freshest_tag(taxonomy_node: dict,
                       candidates: list[str]) -> str | None:
    """First candidate whose freshest observation is freshest overall.

    Ties broken by candidate-list order (earlier candidate wins). Returns
    ``None`` if no candidate has any observations.
    """
    present: list[tuple[str, str, int]] = []
    for idx, tag in enumerate(candidates):
        node = taxonomy_node.get(tag)
        latest = _latest_end_for_tag(node)
        if latest:
            present.append((latest, tag, idx))
    if not present:
        return None
    # Sort by (latest_end desc, candidate_idx asc).
    present.sort(key=lambda t: (-_iso_to_sortable(t[0]), t[2]))
    return present[0][1]


def _iso_to_sortable(s: str) -> int:
    """Crude ISO date → sortable integer (YYYYMMDD). Empty → 0."""
    s = (s or "").replace("-", "")
    if len(s) >= 8 and s[:8].isdigit():
        return int(s[:8])
    return 0


def _latest_annual_observation(
    node: dict | None, *, prefer_unit: str = "USD",
) -> dict | None:
    """Return the FY observation with the latest ``end`` date.

    Filters to ``fp == "FY"`` so we never mix quarterly and annual
    observations into one number. Prefers ``prefer_unit`` to avoid
    accidentally surfacing a non-USD restatement; falls back to any unit
    if the preferred one has no FY observations.
    """
    if not isinstance(node, dict):
        return None
    units = node.get("units")
    if not isinstance(units, dict):
        return None
    unit_order = [prefer_unit] + [u for u in units if u != prefer_unit]
    for unit in unit_order:
        obs_list = units.get(unit)
        if not isinstance(obs_list, list):
            continue
        annual: list[dict] = []
        for obs in obs_list:
            if not isinstance(obs, dict):
                continue
            if obs.get("fp") == "FY":
                annual.append({
                    "val": obs.get("val"),
                    "fy": obs.get("fy"),
                    "fp": obs.get("fp"),
                    "end": str(obs.get("end") or ""),
                    "unit": unit,
                })
        if annual:
            annual.sort(key=lambda c: c["end"], reverse=True)
            return annual[0]
    return None


def _prior_annual_observation(
    node: dict | None, latest: dict | None,
    *, prefer_unit: str = "USD",
) -> dict | None:
    """The FY observation immediately *before* ``latest`` (by end date).

    Uses the same unit as ``latest`` so YoY values are unit-consistent.
    """
    if not isinstance(node, dict) or not isinstance(latest, dict):
        return None
    units = node.get("units")
    if not isinstance(units, dict):
        return None
    latest_end = latest.get("end") or ""
    target_unit = latest.get("unit") or prefer_unit
    obs_list = units.get(target_unit)
    if not isinstance(obs_list, list):
        return None
    prior: list[dict] = []
    for obs in obs_list:
        if not isinstance(obs, dict):
            continue
        if obs.get("fp") != "FY":
            continue
        end = str(obs.get("end") or "")
        if end < latest_end:
            prior.append({
                "val": obs.get("val"),
                "fy": obs.get("fy"),
                "fp": obs.get("fp"),
                "end": end,
                "unit": target_unit,
            })
    if not prior:
        return None
    prior.sort(key=lambda c: c["end"], reverse=True)
    return prior[0]


def _extract_friendly_observation(
    taxonomy_node: dict, friendly: str,
    *, candidates: list[str], prefer_unit: str = "USD",
) -> tuple[dict | None, dict | None, str]:
    """Return ``(latest_obs, prior_obs, matched_tag)`` for one friendly field.

    Either obs may be None (no data / no prior year). matched_tag is
    empty when no candidate had any observations at all.
    """
    tag = _pick_freshest_tag(taxonomy_node, candidates)
    if tag is None:
        return None, None, ""
    node = taxonomy_node.get(tag)
    latest = _latest_annual_observation(node, prefer_unit=prefer_unit)
    if latest is None:
        return None, None, tag
    prior = _prior_annual_observation(node, latest, prefer_unit=prefer_unit)
    return latest, prior, tag


# --------------------------------------------------------------------------- #
# Formatting helpers
# --------------------------------------------------------------------------- #
def _fmt_money(value: float | int | None) -> str:
    """Format an absolute money value with B / M / K suffix."""
    if value is None:
        return "n/a"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "n/a"
    sign = "-" if v < 0 else ""
    a = abs(v)
    if a >= 1_000_000_000_000:
        return f"{sign}${a / 1_000_000_000_000:.2f}T"
    if a >= 1_000_000_000:
        return f"{sign}${a / 1_000_000_000:.2f}B"
    if a >= 1_000_000:
        return f"{sign}${a / 1_000_000:.2f}M"
    if a >= 1_000:
        return f"{sign}${a / 1_000:.2f}K"
    return f"{sign}${a:.2f}"


def _fmt_count(value: float | int | None) -> str:
    """Format a share count (no $)."""
    if value is None:
        return "n/a"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "n/a"
    a = abs(v)
    if a >= 1_000_000_000:
        return f"{v / 1_000_000_000:.2f}B"
    if a >= 1_000_000:
        return f"{v / 1_000_000:.2f}M"
    return f"{v:,.0f}"


def _fmt_pct(value: float | None, *, signed: bool = True) -> str:
    if value is None:
        return "n/a"
    fmt = "{:+.2f}%" if signed else "{:.2f}%"
    return fmt.format(value)


def _fmt_ratio(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}x"


def _safe_div(num: float | None, den: float | None) -> float | None:
    if num is None or den is None or den == 0:
        return None
    return num / den


def _yoy_pct(latest_val: float | None,
             prior_val: float | None) -> float | None:
    if latest_val is None or prior_val is None or prior_val == 0:
        return None
    return ((latest_val - prior_val) / abs(prior_val)) * 100.0


def _obs_val(obs: dict | None) -> float | None:
    if not isinstance(obs, dict):
        return None
    v = obs.get("val")
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _format_fiscal_period(obs: dict | None) -> str:
    if not isinstance(obs, dict):
        return ""
    fy = obs.get("fy")
    fp = obs.get("fp") or ""
    if not fy:
        return str(fp)
    if fp == "FY":
        return f"FY{fy}"
    return f"{fp} FY{fy}".strip()


# --------------------------------------------------------------------------- #
# Composition entry point
# --------------------------------------------------------------------------- #
def compute_fundamentals_snapshot(
    facts_json: dict | None,
    *,
    ticker: str = "",
    cik: str = "",
    cache_path: str = "",
    latest_close: float | None = None,
) -> FundamentalsSnapshot:
    """Compose a :class:`FundamentalsSnapshot` from a parsed companyfacts
    payload.

    PURE. No I/O. Missing tags surface as ``"n/a"``. Valuation is
    populated only when ``latest_close`` is provided and the snapshot's
    shares-outstanding can be resolved.
    """
    if not isinstance(facts_json, dict):
        return FundamentalsSnapshot(
            ticker=ticker, cik=cik, cache_path=cache_path,
            data_gap_note=(
                "Fundamentals cache not available. "
                "No live SEC fetch performed."
            ),
            valuation_note="Valuation data unavailable from local cache.",
        )

    gaap = _facts_subtree(facts_json, "us-gaap")
    dei = _facts_subtree(facts_json, "dei")

    if not gaap and not dei:
        return FundamentalsSnapshot(
            ticker=ticker, cik=cik, cache_path=cache_path,
            data_gap_note=(
                "Companyfacts JSON has no us-gaap / dei subtrees. "
                "No live SEC fetch performed."
            ),
            valuation_note="Valuation data unavailable from local cache.",
        )

    gaps: list[str] = []
    extracted: dict[str, tuple[dict | None, dict | None]] = {}
    for friendly, cands in GAAP_CANDIDATES.items():
        latest, prior, matched = _extract_friendly_observation(
            gaap, friendly, candidates=cands,
        )
        extracted[friendly] = (latest, prior)
        if matched == "":
            gaps.append(f"{friendly}: no matching GAAP tag")

    # DEI shares-outstanding fallback (used only if GAAP failed).
    dei_shares_latest, _, dei_matched = _extract_friendly_observation(
        dei, "shares_outstanding_dei",
        candidates=DEI_CANDIDATES["shares_outstanding_dei"],
        prefer_unit="shares",
    )

    # Numeric pulls.
    rev_latest, rev_prior = extracted["revenue"]
    rev_val = _obs_val(rev_latest)
    rev_prev_val = _obs_val(rev_prior)
    rev_yoy = _yoy_pct(rev_val, rev_prev_val)

    gp_latest, _ = extracted["gross_profit"]
    gp_val = _obs_val(gp_latest)

    oi_latest, _ = extracted["operating_income"]
    oi_val = _obs_val(oi_latest)

    ni_latest, _ = extracted["net_income"]
    ni_val = _obs_val(ni_latest)

    ocf_latest, _ = extracted["operating_cash_flow"]
    ocf_val = _obs_val(ocf_latest)

    capex_latest, _ = extracted["capex"]
    capex_val = _obs_val(capex_latest)
    fcf_val = (None if ocf_val is None or capex_val is None
               else ocf_val - capex_val)

    inv_latest, inv_prior = extracted["inventory"]
    inv_val = _obs_val(inv_latest)
    inv_prev_val = _obs_val(inv_prior)
    inv_yoy = _yoy_pct(inv_val, inv_prev_val)

    cash_latest, _ = extracted["cash"]
    cash_val = _obs_val(cash_latest)

    debt_latest, _ = extracted["debt"]
    debt_val = _obs_val(debt_latest)

    shares_gaap_latest, _ = extracted["shares_outstanding_gaap"]
    shares_val = _obs_val(shares_gaap_latest)
    if shares_val is None and dei_shares_latest is not None:
        shares_val = _obs_val(dei_shares_latest)

    # Margins (latest FY only, same period).
    gross_margin = _safe_div(gp_val, rev_val)
    if gross_margin is not None:
        gross_margin *= 100.0
    op_margin = _safe_div(oi_val, rev_val)
    if op_margin is not None:
        op_margin *= 100.0

    # Latest fiscal-period label (from revenue if available, else NI).
    headline_obs = rev_latest or ni_latest or oi_latest
    fiscal_period = _format_fiscal_period(headline_obs)
    report_date = (
        headline_obs["end"] if isinstance(headline_obs, dict)
        else ""
    )

    # ---- Valuation ------------------------------------------------------- #
    valuation_note = ""
    market_cap_val: float | None = None
    ps: float | None = None
    pe: float | None = None
    pfcf: float | None = None
    ev_val: float | None = None
    ev_sales: float | None = None
    if latest_close is None:
        valuation_note = (
            "No local price cache for this ticker — valuation skipped."
        )
    elif shares_val is None or shares_val <= 0:
        valuation_note = (
            "No shares-outstanding tag in local SEC cache — "
            "valuation skipped."
        )
    else:
        market_cap_val = float(latest_close) * float(shares_val)
        ps = _safe_div(market_cap_val, rev_val)
        # P/E only when NI > 0 (negative-earnings P/E is not informative).
        if ni_val is not None and ni_val > 0:
            pe = market_cap_val / ni_val
        if fcf_val is not None and fcf_val > 0:
            pfcf = market_cap_val / fcf_val
        if (debt_val is not None) and (cash_val is not None):
            ev_val = market_cap_val + debt_val - cash_val
            ev_sales = _safe_div(ev_val, rev_val)

    return FundamentalsSnapshot(
        ticker=ticker,
        cik=cik,
        cache_path=cache_path,
        latest_fiscal_period=fiscal_period,
        latest_report_date=report_date,
        revenue=_fmt_money(rev_val),
        revenue_yoy_pct=_fmt_pct(rev_yoy),
        gross_profit=_fmt_money(gp_val),
        gross_margin_pct=_fmt_pct(gross_margin, signed=False),
        operating_income=_fmt_money(oi_val),
        operating_margin_pct=_fmt_pct(op_margin, signed=False),
        net_income=_fmt_money(ni_val),
        operating_cash_flow=_fmt_money(ocf_val),
        capex=_fmt_money(capex_val),
        free_cash_flow=_fmt_money(fcf_val),
        inventory=_fmt_money(inv_val),
        inventory_yoy_pct=_fmt_pct(inv_yoy),
        debt=_fmt_money(debt_val),
        cash=_fmt_money(cash_val),
        shares_outstanding=_fmt_count(shares_val),
        market_cap=_fmt_money(market_cap_val),
        price_to_sales=_fmt_ratio(ps),
        price_to_earnings=_fmt_ratio(pe),
        price_to_free_cash_flow=_fmt_ratio(pfcf),
        enterprise_value=_fmt_money(ev_val),
        ev_to_sales=_fmt_ratio(ev_sales),
        data_gap_note=" ; ".join(gaps),
        valuation_note=valuation_note,
    )


__all__ = [
    # paths
    "DEFAULT_SEC_CACHE_DIR", "DEFAULT_COMPANYFACTS_DIR",
    "DEFAULT_TICKER_MAP_FILE",
    # candidates
    "GAAP_CANDIDATES", "DEI_CANDIDATES",
    "FUNDAMENTALS_FIELDS",
    # schema
    "FundamentalsSnapshot",
    # loaders
    "load_ticker_to_cik_map", "load_companyfacts_json",
    "companyfacts_path_for_ticker",
    # composition
    "compute_fundamentals_snapshot",
]
