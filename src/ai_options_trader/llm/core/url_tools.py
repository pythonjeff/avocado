from __future__ import annotations

import re
from html import unescape

import requests


def html_to_text(html: str) -> str:
    """
    Very lightweight HTML -> text converter (no extra deps).
    Good enough for news articles; not perfect.
    """
    s = html or ""
    # Drop scripts/styles
    s = re.sub(r"(?is)<script.*?>.*?</script>", " ", s)
    s = re.sub(r"(?is)<style.*?>.*?</style>", " ", s)
    # Replace breaks/paragraphs with newlines
    s = re.sub(r"(?i)</(p|div|br|li|h1|h2|h3|h4|tr)>", "\n", s)
    # Strip all tags
    s = re.sub(r"(?is)<.*?>", " ", s)
    s = unescape(s)
    # Collapse whitespace
    s = re.sub(r"[ \t\r\f\v]+", " ", s)
    s = re.sub(r"\n{2,}", "\n", s)
    return s.strip()


def fetch_url_text(url: str, *, timeout_s: int = 20, max_chars: int = 20_000) -> str:
    """
    Fetch a URL and return best-effort extracted plain text.
    """
    u = (url or "").strip()
    if not u:
        raise ValueError("Empty url")
    resp = requests.get(
        u,
        timeout=int(timeout_s),
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; ai-options-trader/1.0; +https://example.com)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    resp.raise_for_status()
    txt = html_to_text(resp.text or "")
    if max_chars and len(txt) > int(max_chars):
        txt = txt[: int(max_chars)]
    return txt

