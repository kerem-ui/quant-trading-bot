"""SEC EDGAR client (read-only, stdlib-only, polite, locally cached).

Official free source for US public-company filings and XBRL fundamentals.
No API key is required by SEC; SEC instead asks every client to send a
descriptive ``User-Agent`` with contact info and to stay under ~10 req/s.

Design (mirrors ``quantbot.macro.fred_loader``)
----------------------------------------------
- stdlib ``urllib`` only -- NO new package (no ``requests``, no ``sec-edgar``).
- ``User-Agent`` is read from ``QUANTBOT_SEC_USER_AGENT`` and is **never
  hardcoded with private data**. If unset, a neutral placeholder is used and
  a one-time note asks the operator to set it. The UA *value* is never logged
  or printed (it may contain a personal email).
- Cache-first. Everything fetched is written atomically under
  ``data/company/sec/`` and re-used on the next call.
- Polite throttle between live requests (default 5 req/s, well under SEC's
  limit). No aggressive scraping.
- **Never raises** on a network/HTTP/parse failure -- returns ``None`` and
  lets the caller degrade. No broker / live / IBKR. No options/ThetaData.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..config import project_root

log = logging.getLogger("quantbot.company.sec")

SEC_WWW = "https://www.sec.gov"
SEC_DATA = "https://data.sec.gov"
COMPANY_TICKERS_URL = f"{SEC_WWW}/files/company_tickers.json"

# A neutral default. SEC only needs *a* descriptive UA with contact info; set
# QUANTBOT_SEC_USER_AGENT to your own "Name email@domain" for real use.
DEFAULT_USER_AGENT = "quantbot-research (set QUANTBOT_SEC_USER_AGENT; contact: research@example.com)"

# Polite default: 5 requests/second (SEC tolerates up to ~10).
RATE_LIMIT_MIN_INTERVAL = 0.2
_last_request_ts = 0.0


# --------------------------------------------------------------------------- #
# Paths / config
# --------------------------------------------------------------------------- #
def company_cache_dir(root: str | Path | None = None) -> Path:
    base = Path(root) if root else project_root() / "data" / "company"
    return base / "sec"


def default_user_agent() -> str:
    """Return the configured SEC User-Agent (env var) or a neutral default.

    The value is intentionally NOT logged anywhere (it may carry a personal
    email). Callers should not print it either.
    """
    ua = os.environ.get("QUANTBOT_SEC_USER_AGENT", "").strip()
    return ua or DEFAULT_USER_AGENT


def has_custom_user_agent() -> bool:
    """True iff QUANTBOT_SEC_USER_AGENT is set (value not exposed)."""
    return bool(os.environ.get("QUANTBOT_SEC_USER_AGENT", "").strip())


def normalize_cik(cik: str | int) -> str:
    """Return a 10-digit zero-padded CIK string (e.g. ``0000320193``)."""
    s = str(cik).strip().upper()
    if s.startswith("CIK"):
        s = s[3:]
    s = s.lstrip("0") or "0"
    if not s.isdigit():
        raise ValueError(f"CIK must be numeric, got {cik!r}")
    return s.zfill(10)


def cik_int(cik: str | int) -> int:
    """CIK as a plain int (used for the /Archives/edgar/data/<int>/ path)."""
    return int(normalize_cik(cik))


# --------------------------------------------------------------------------- #
# Low-level IO (atomic write, JSON cache, polite HTTP GET)
# --------------------------------------------------------------------------- #
def _atomic_write_bytes(data: bytes, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=path.suffix or ".tmp", dir=str(path.parent))
    os.close(fd)
    try:
        Path(tmp).write_bytes(data)
        os.replace(tmp, path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def _read_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # corrupt cache -> treat as miss
        log.warning("corrupt JSON cache %s: %s", path.name, exc)
        return None


def _throttle(min_interval: float) -> None:
    global _last_request_ts
    now = time.monotonic()
    wait = min_interval - (now - _last_request_ts)
    if wait > 0:
        time.sleep(wait)
    _last_request_ts = time.monotonic()


def http_get(
    url: str, *,
    timeout_seconds: float = 20.0,
    min_interval: float = RATE_LIMIT_MIN_INTERVAL,
    user_agent: str | None = None,
) -> bytes | None:
    """Polite GET. Returns body bytes, or ``None`` on any failure (never raises).

    ``Accept-Encoding: identity`` keeps responses uncompressed so we don't need
    a gzip dependency. The ``User-Agent`` is sent but never logged.
    """
    ua = user_agent or default_user_agent()
    _throttle(min_interval)
    req = Request(url, headers={
        "User-Agent": ua,
        "Accept-Encoding": "identity",
        "Accept": "application/json, text/html, */*",
    })
    try:
        with urlopen(req, timeout=timeout_seconds) as resp:
            return resp.read()
    except (HTTPError, URLError, TimeoutError) as exc:
        # Never surface the UA (could contain a personal email).
        log.warning("SEC GET failed (%s): %s", url, type(exc).__name__)
        return None
    except Exception as exc:  # be defensive: this layer must not raise
        log.warning("SEC GET unexpected error (%s): %s", url, type(exc).__name__)
        return None


# --------------------------------------------------------------------------- #
# Ticker -> CIK
# --------------------------------------------------------------------------- #
def fetch_company_tickers(
    *, use_cache: bool = True, refresh: bool = False,
    root: str | Path | None = None, **http_kwargs,
) -> dict | None:
    """Fetch SEC's ticker->CIK directory (cached as company_tickers.json)."""
    path = company_cache_dir(root) / "company_tickers.json"
    if use_cache and not refresh:
        cached = _read_json(path)
        if cached is not None:
            return cached

    body = http_get(COMPANY_TICKERS_URL, **http_kwargs)
    if body is None:
        return _read_json(path)  # fall back to stale cache if any
    try:
        payload = json.loads(body)
    except Exception as exc:
        log.warning("company_tickers JSON parse failed: %s", exc)
        return _read_json(path)
    _atomic_write_bytes(json.dumps(payload).encode("utf-8"), path)
    return payload


def build_ticker_map(raw: dict | None) -> dict[str, dict]:
    """Normalise SEC's ``{idx: {cik_str, ticker, title}}`` into
    ``{TICKER: {"cik": "0000320193", "title": ...}}``. Empty on bad input."""
    out: dict[str, dict] = {}
    if not isinstance(raw, dict):
        return out
    for rec in raw.values():
        if not isinstance(rec, dict):
            continue
        tkr = str(rec.get("ticker", "")).upper().strip()
        cik_raw = rec.get("cik_str", rec.get("cik"))
        if not tkr or cik_raw is None:
            continue
        try:
            out[tkr] = {"cik": normalize_cik(cik_raw),
                        "title": str(rec.get("title", ""))}
        except ValueError:
            continue
    return out


def ticker_to_cik(
    ticker: str, *, use_cache: bool = True, refresh: bool = False,
    root: str | Path | None = None, tickers: dict | None = None,
    **http_kwargs,
) -> str | None:
    """Map a ticker to its 10-digit CIK, or ``None`` if unknown/unavailable."""
    raw = tickers if tickers is not None else fetch_company_tickers(
        use_cache=use_cache, refresh=refresh, root=root, **http_kwargs)
    tmap = build_ticker_map(raw)
    rec = tmap.get(str(ticker).upper().strip())
    return rec["cik"] if rec else None


# --------------------------------------------------------------------------- #
# Submissions metadata + company facts (cached by CIK)
# --------------------------------------------------------------------------- #
def _resolve_cik(ticker_or_cik: str | int, *, root, use_cache, refresh,
                 **http_kwargs) -> str | None:
    s = str(ticker_or_cik).strip()
    if s.upper().startswith("CIK") or s.isdigit():
        try:
            return normalize_cik(s)
        except ValueError:
            return None
    return ticker_to_cik(s, use_cache=use_cache, refresh=refresh,
                         root=root, **http_kwargs)


def fetch_submissions(
    ticker_or_cik: str | int, *, use_cache: bool = True, refresh: bool = False,
    root: str | Path | None = None, **http_kwargs,
) -> dict | None:
    """Fetch a company's submissions metadata JSON (recent filings list)."""
    cik = _resolve_cik(ticker_or_cik, root=root, use_cache=use_cache,
                       refresh=refresh, **http_kwargs)
    if cik is None:
        log.info("could not resolve CIK for %r", ticker_or_cik)
        return None
    path = company_cache_dir(root) / "submissions" / f"CIK{cik}.json"
    if use_cache and not refresh:
        cached = _read_json(path)
        if cached is not None:
            return cached
    body = http_get(f"{SEC_DATA}/submissions/CIK{cik}.json", **http_kwargs)
    if body is None:
        return _read_json(path)
    try:
        payload = json.loads(body)
    except Exception as exc:
        log.warning("submissions JSON parse failed for CIK%s: %s", cik, exc)
        return _read_json(path)
    _atomic_write_bytes(json.dumps(payload).encode("utf-8"), path)
    return payload


def fetch_company_facts(
    ticker_or_cik: str | int, *, use_cache: bool = True, refresh: bool = False,
    root: str | Path | None = None, **http_kwargs,
) -> dict | None:
    """Fetch a company's XBRL ``companyfacts`` JSON (all reported concepts)."""
    cik = _resolve_cik(ticker_or_cik, root=root, use_cache=use_cache,
                       refresh=refresh, **http_kwargs)
    if cik is None:
        return None
    path = company_cache_dir(root) / "companyfacts" / f"CIK{cik}.json"
    if use_cache and not refresh:
        cached = _read_json(path)
        if cached is not None:
            return cached
    body = http_get(f"{SEC_DATA}/api/xbrl/companyfacts/CIK{cik}.json", **http_kwargs)
    if body is None:
        return _read_json(path)
    try:
        payload = json.loads(body)
    except Exception as exc:
        log.warning("companyfacts JSON parse failed for CIK%s: %s", cik, exc)
        return _read_json(path)
    _atomic_write_bytes(json.dumps(payload).encode("utf-8"), path)
    return payload


# --------------------------------------------------------------------------- #
# Raw filing document (HTML/txt) -- cached
# --------------------------------------------------------------------------- #
def filing_document_url(cik: str | int, accession: str, primary_document: str) -> str:
    """Build the EDGAR archive URL for a filing's primary document."""
    acc_nodash = str(accession).replace("-", "")
    return f"{SEC_WWW}/Archives/edgar/data/{cik_int(cik)}/{acc_nodash}/{primary_document}"


def fetch_filing_document(
    cik: str | int, accession: str, primary_document: str, *,
    use_cache: bool = True, refresh: bool = False,
    root: str | Path | None = None, **http_kwargs,
) -> str | None:
    """Fetch (and cache) one filing's primary document, returned as text.

    Returns ``None`` if unavailable. Decodes as UTF-8 with error replacement
    (filings are sometimes latin-1 / contain odd bytes).
    """
    cik10 = normalize_cik(cik)
    acc_nodash = str(accession).replace("-", "")
    path = (company_cache_dir(root) / "filings" / f"CIK{cik10}"
            / acc_nodash / primary_document)
    if use_cache and not refresh and path.is_file():
        return path.read_text(encoding="utf-8", errors="replace")
    body = http_get(filing_document_url(cik, accession, primary_document), **http_kwargs)
    if body is None:
        if path.is_file():
            return path.read_text(encoding="utf-8", errors="replace")
        return None
    _atomic_write_bytes(body, path)
    return body.decode("utf-8", errors="replace")
