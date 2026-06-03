"""Build and filter a filing index from SEC submissions metadata.

Pure transforms -- no network, no I/O, no broker. Input is the parsed JSON
returned by :func:`quantbot.company.sec_edgar.fetch_submissions`; output is a
tidy ``pandas`` DataFrame, one row per filing.

Only the ``filings.recent`` block is parsed here (the most recent ~1000
filings SEC inlines into the submissions JSON). Older filings live in separate
``filings.files`` shards; parsing those is a documented future extension, not
needed for the recent-history research this stage targets.
"""

from __future__ import annotations

import pandas as pd

from .sec_edgar import filing_document_url, normalize_cik

INDEX_COLUMNS = [
    "cik", "entity_name", "form", "filing_date", "report_date",
    "accession_number", "primary_document", "primary_doc_description",
    "items", "size", "is_xbrl", "document_url",
]

# Forms this stage supports as first-class.
SUPPORTED_FORMS = ("10-K", "10-Q", "8-K")


def _empty_index() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype="object") for c in INDEX_COLUMNS})


def build_filing_index(submissions: dict | None) -> pd.DataFrame:
    """Return a tidy filing index from a submissions JSON payload.

    Missing / malformed input yields a typed empty frame (never raises).
    """
    if not isinstance(submissions, dict):
        return _empty_index()

    cik_raw = submissions.get("cik")
    try:
        cik = normalize_cik(cik_raw) if cik_raw is not None else ""
    except ValueError:
        cik = ""
    entity_name = str(submissions.get("name", ""))

    recent = (submissions.get("filings") or {}).get("recent") or {}
    forms = recent.get("form") or []
    n = len(forms)
    if n == 0:
        return _empty_index()

    def col(key: str) -> list:
        vals = recent.get(key) or []
        return list(vals) + [None] * (n - len(vals))  # pad short columns

    accession = col("accessionNumber")
    primary_doc = col("primaryDocument")
    filing_date = col("filingDate")
    report_date = col("reportDate")
    primary_desc = col("primaryDocDescription")
    items = col("items")
    size = col("size")
    is_xbrl = col("isXBRL")

    rows = []
    for i in range(n):
        acc = accession[i] or ""
        doc = primary_doc[i] or ""
        url = ""
        if cik and acc and doc:
            url = filing_document_url(cik, acc, doc)
        rows.append({
            "cik": cik,
            "entity_name": entity_name,
            "form": str(forms[i] or ""),
            "filing_date": filing_date[i] or "",
            "report_date": report_date[i] or "",
            "accession_number": acc,
            "primary_document": doc,
            "primary_doc_description": primary_desc[i] or "",
            "items": items[i] or "",
            "size": size[i],
            "is_xbrl": bool(is_xbrl[i]) if is_xbrl[i] is not None else False,
            "document_url": url,
        })

    df = pd.DataFrame(rows, columns=INDEX_COLUMNS)
    df["filing_date"] = pd.to_datetime(df["filing_date"], errors="coerce")
    df["report_date"] = pd.to_datetime(df["report_date"], errors="coerce")
    return df.sort_values("filing_date", ascending=False).reset_index(drop=True)


def filter_filings(
    index: pd.DataFrame, *,
    forms: list[str] | tuple[str, ...] | None = None,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
    include_amendments: bool = True,
) -> pd.DataFrame:
    """Filter a filing index by form type and ``filing_date`` range.

    ``forms`` matching is case-insensitive. When ``include_amendments`` is
    True a request for ``10-K`` also keeps ``10-K/A`` (and similar). An empty
    or missing index returns a typed empty frame.
    """
    if index is None or index.empty:
        return _empty_index()
    out = index.copy()

    if forms:
        wanted = {f.upper().strip() for f in forms}
        form_u = out["form"].astype(str).str.upper().str.strip()
        if include_amendments:
            base = form_u.str.split("/").str[0]  # "10-K/A" -> "10-K"
            mask = form_u.isin(wanted) | base.isin(wanted)
        else:
            mask = form_u.isin(wanted)
        out = out[mask]

    if start is not None:
        out = out[out["filing_date"] >= pd.Timestamp(start)]
    if end is not None:
        out = out[out["filing_date"] <= pd.Timestamp(end)]

    return out.reset_index(drop=True)


def filings_near(
    index: pd.DataFrame, target_date: str | pd.Timestamp, *,
    window_days: int = 45, forms: list[str] | tuple[str, ...] | None = None,
) -> pd.DataFrame:
    """Filings whose ``filing_date`` falls within +/- ``window_days`` of a date.

    Used to line filings up against a notable price-move window. Read-only and
    descriptive -- this is NOT a signal.
    """
    if index is None or index.empty:
        return _empty_index()
    t = pd.Timestamp(target_date)
    sub = filter_filings(index, forms=forms,
                         start=t - pd.Timedelta(days=window_days),
                         end=t + pd.Timedelta(days=window_days))
    if sub.empty:
        return sub
    sub = sub.assign(days_from_target=(sub["filing_date"] - t).dt.days)
    return sub.sort_values("days_from_target", key=lambda s: s.abs()).reset_index(drop=True)
