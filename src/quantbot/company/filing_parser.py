"""Filing text extraction (HTML -> readable text + best-effort sections).

Pure transforms -- no network, no broker. Uses only the stdlib ``html.parser``
(no BeautifulSoup / lxml dependency). This is a deliberately SAFE first version:
it always returns *something* (full plain text + a snippet + whichever known
section headers it can locate) and never raises on messy filings. Robust,
filer-specific section parsing is a documented future improvement.
"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser

_SKIP_TAGS = {"script", "style", "head", "title"}
_BLOCK_TAGS = {"p", "div", "br", "tr", "table", "li", "h1", "h2", "h3",
               "h4", "h5", "h6", "section", "article"}


class _TextExtractor(HTMLParser):
    """Collect visible text, inserting newlines at block boundaries."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag in _BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_data(self, data):
        if self._skip_depth == 0 and data:
            self._chunks.append(data)

    def text(self) -> str:
        return "".join(self._chunks)


def _collapse_ws(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def html_to_text(content: str | None) -> str:
    """Convert HTML (or already-plain text) to collapsed readable text.

    Never raises; on a parser error falls back to a crude tag strip.
    """
    if not content:
        return ""
    looks_html = "<" in content and ">" in content
    if not looks_html:
        return _collapse_ws(html.unescape(content))
    try:
        p = _TextExtractor()
        p.feed(content)
        p.close()
        return _collapse_ws(p.text())
    except Exception:
        stripped = re.sub(r"<[^>]+>", " ", content)
        return _collapse_ws(html.unescape(stripped))


# --------------------------------------------------------------------------- #
# Best-effort section detection
# --------------------------------------------------------------------------- #
# friendly section -> regex that matches its heading ("Item 1A. Risk Factors")
_SECTION_PATTERNS: dict[str, dict[str, re.Pattern]] = {
    "10-K": {
        "business": re.compile(r"item\s*1\.?\s*business", re.I),
        "risk_factors": re.compile(r"item\s*1a\.?\s*risk\s+factors", re.I),
        "mdna": re.compile(r"item\s*7\.?\s*management.?s\s+discussion", re.I),
        "market_risk": re.compile(r"item\s*7a\.?\s*quantitative", re.I),
        "liquidity": re.compile(r"liquidity\s+and\s+capital\s+resources", re.I),
    },
    "10-Q": {
        "mdna": re.compile(r"item\s*2\.?\s*management.?s\s+discussion", re.I),
        "risk_factors": re.compile(r"item\s*1a\.?\s*risk\s+factors", re.I),
        "liquidity": re.compile(r"liquidity\s+and\s+capital\s+resources", re.I),
    },
    "8-K": {
        # 8-K material-event items, e.g. "Item 2.02 Results of Operations".
        "material_events": re.compile(r"item\s*\d\.\d{2}", re.I),
    },
}


def _form_key(form: str) -> str:
    f = (form or "").upper().strip().split("/")[0]  # 10-K/A -> 10-K
    return f if f in _SECTION_PATTERNS else "10-K"


def extract_sections(text: str | None, form: str, *,
                     max_chars: int = 4000) -> dict[str, str]:
    """Best-effort: return ``{section_name: snippet}`` for headings found.

    Each snippet runs from its heading to the next detected heading (or
    ``max_chars``, whichever is shorter). Sections not found are simply
    omitted -- callers must treat a missing key as "not extracted", not
    "not present in the filing".
    """
    if not text:
        return {}
    patterns = _SECTION_PATTERNS[_form_key(form)]

    hits: list[tuple[int, str]] = []
    for name, pat in patterns.items():
        m = pat.search(text)
        if m:
            hits.append((m.start(), name))
    if not hits:
        return {}
    hits.sort()
    starts = [h[0] for h in hits]

    out: dict[str, str] = {}
    for i, (pos, name) in enumerate(hits):
        nxt = starts[i + 1] if i + 1 < len(starts) else len(text)
        end = min(nxt, pos + max_chars)
        snippet = text[pos:end].strip()
        if snippet and name not in out:
            out[name] = snippet
    return out


def summarize_filing_text(text: str | None, form: str = "10-K", *,
                          snippet_chars: int = 600) -> dict:
    """Compact, robust metadata for a filing's text body."""
    text = text or ""
    sections = extract_sections(text, form)
    return {
        "n_chars": len(text),
        "n_words": len(text.split()),
        "detected_sections": sorted(sections.keys()),
        "n_detected_sections": len(sections),
        "snippet": text[:snippet_chars].strip(),
    }
