"""
Shiller CAPE (cyclically-adjusted P/E) fetcher.

Data source: multpl.com, which mirrors Shiller's `ie_data.xls` and is the
most reliable free public surface for the headline CAPE.  His own xlsx file
is the authoritative source but requires an Excel reader as a dependency;
multpl.com is HTML-scrape-able with `requests` alone.

Cache: 24h disk cache (CAPE updates roughly monthly, so daily refresh is
plenty).  Set `refresh=True` to force re-fetch.

Override: `LOX_CAPE_OVERRIDE` env var lets the user hand-key a value when
the scrape fails or when they want to lock to a specific reading.  This is
the escape hatch — institutional tools should always have a manual override
for scraped data.

Caveat: HTML scraping is fragile by nature.  If multpl.com restructures the
page, the fetch returns None and the bubble panel falls back to "—" on the
CAPE column.  That degrades gracefully without breaking other metrics.
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


_MULTPL_URL = "https://www.multpl.com/shiller-pe"
_CACHE_PATH = Path("data/cache/bubble/cape.txt")
_CACHE_TTL_SECONDS = 24 * 60 * 60  # 24 hours


@dataclass
class CAPESnapshot:
    value: Optional[float]
    source: str             # "multpl" | "override" | "cache" | "none"
    asof: Optional[str] = None  # YYYY-MM-DD when known


def _read_cache() -> Optional[float]:
    if not _CACHE_PATH.exists():
        return None
    age = time.time() - _CACHE_PATH.stat().st_mtime
    if age > _CACHE_TTL_SECONDS:
        return None
    try:
        return float(_CACHE_PATH.read_text().strip())
    except (ValueError, OSError):
        return None


def _write_cache(value: float) -> None:
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_PATH.write_text(f"{value:.2f}\n")
    except OSError:
        pass  # cache failure is non-fatal


def _scrape_multpl() -> Optional[float]:
    """
    Fetch the current Shiller PE from multpl.com.  Returns None on any failure
    (network, parse, unexpected HTML) — the caller falls back to "—".
    """
    try:
        import requests
        resp = requests.get(_MULTPL_URL, timeout=10, headers={
            "User-Agent": "Mozilla/5.0 (lox-bubble-monitor)",
        })
        resp.raise_for_status()
    except Exception:
        return None

    html = resp.text
    # The headline value sits in the "current" div; the formatted value follows
    # a "Current Shiller PE Ratio:" label.  Match either textual or numeric
    # variations — multpl's exact markup has drifted over the years.
    patterns = [
        r"Current Shiller PE Ratio[^\d]*([\d]+\.[\d]+)",
        r'id=["\']current["\'][^>]*>[^<]*<[^>]*>\s*([\d]+\.[\d]+)',
        r"Shiller PE Ratio[^\d]{0,40}([\d]{2,3}\.[\d]+)",
    ]
    for pat in patterns:
        m = re.search(pat, html)
        if m:
            try:
                v = float(m.group(1))
                # Sanity bound — CAPE has historically lived in [5, 50]; if
                # the scrape returns something wildly outside that, treat as
                # parse failure rather than display nonsense.
                if 5.0 <= v <= 100.0:
                    return v
            except ValueError:
                continue
    return None


def fetch_current_cape(*, refresh: bool = False) -> CAPESnapshot:
    """
    Get the current Shiller CAPE.  Resolution order:

      1. `LOX_CAPE_OVERRIDE` env var (manual lock — wins always)
      2. Disk cache if fresh and not `refresh`
      3. multpl.com scrape; writes cache on success
      4. Stale cache (any age) — better stale than nothing
      5. None
    """
    override = os.environ.get("LOX_CAPE_OVERRIDE")
    if override:
        try:
            return CAPESnapshot(value=float(override), source="override")
        except ValueError:
            pass

    if not refresh:
        cached = _read_cache()
        if cached is not None:
            return CAPESnapshot(value=cached, source="cache")

    scraped = _scrape_multpl()
    if scraped is not None:
        _write_cache(scraped)
        return CAPESnapshot(value=scraped, source="multpl")

    # Final fallback: stale cache (any age) — display old value with note
    # rather than nothing.  The asof on the panel is from the live FRED data
    # anyway, so the user can sanity-check freshness there.
    if _CACHE_PATH.exists():
        try:
            stale = float(_CACHE_PATH.read_text().strip())
            return CAPESnapshot(value=stale, source="cache")
        except (ValueError, OSError):
            pass

    return CAPESnapshot(value=None, source="none")
