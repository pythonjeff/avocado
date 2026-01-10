from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any
import csv
from pathlib import Path

from ai_options_trader.config import Settings


DEFAULT_TRACKER_KEYS: tuple[str, ...] = (
    "macro_disconnect_score",
    "usd_strength_score",
    "rates_z_ust_10y",
    "rates_z_curve_2s10s",
    "vol_pressure_score",
    "commod_pressure_score",
    "fiscal_pressure_score",
    "funding_tightness_score",
)


def extract_underlyings(symbols: list[str]) -> set[str]:
    """
    Normalize symbols to underlyings.

    - For options OCC-ish symbols like `VIXY260220C00028000`, returns `VIXY`.
    - For equities/ETFs, returns the symbol.
    """
    out: set[str] = set()
    for s in symbols:
        sym = (s or "").strip().upper()
        if not sym:
            continue
        m = re.match(r"^([A-Z]+)", sym)
        out.add(str(m.group(1)) if m else sym)
    return out


def build_trackers(
    *,
    settings: Settings,
    start_date: str = "2012-01-01",
    refresh_fred: bool = False,
    tracker_keys: tuple[str, ...] = DEFAULT_TRACKER_KEYS,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Return:
    - feat_row: full feature row (dict) for the latest available date
    - risk_watch: {trackers_asof, trackers, events: []}
    """
    from ai_options_trader.regimes.feature_matrix import build_regime_feature_matrix

    X = build_regime_feature_matrix(settings=settings, start_date=str(start_date), refresh_fred=bool(refresh_fred))
    if X.empty:
        return {}, {"trackers_asof": None, "trackers": {}, "events": []}
    row = X.iloc[-1].to_dict()
    asof = str(X.index[-1].date())
    return row, {"trackers_asof": asof, "trackers": {k: row.get(k) for k in tracker_keys if k in row}, "events": []}


def fetch_calendar_events(
    *,
    settings: Settings,
    days_ahead: int = 10,
    max_items: int = 18,
    us_only: bool = True,
) -> list[dict[str, Any]]:
    """
    Best-effort: upcoming economic calendar events via FMP (cached in data layer).
    Returns normalized dicts or [] if FMP is not configured/unavailable.
    """
    if not settings.fmp_api_key:
        return []
    from ai_options_trader.data.econ_release import fetch_fmp_economic_calendar, normalize_fmp_economic_calendar

    now = datetime.now(timezone.utc)
    from_date = now.date().isoformat()
    to_date = (now.date() + timedelta(days=int(days_ahead))).isoformat()
    rows = fetch_fmp_economic_calendar(api_key=settings.fmp_api_key, from_date=from_date, to_date=to_date)
    ev = normalize_fmp_economic_calendar(rows)
    upcoming0 = [e for e in ev if e.datetime_utc > now]

    # Default filter: keep only US/USD-relevant events (to avoid surfacing random global CPI prints).
    if bool(us_only):
        upcoming = []
        for e in upcoming0:
            ctry = str(e.country or "").strip().lower()
            cat = str(e.category or "").strip().lower()
            is_us = (ctry in {"us", "usa", "united states"}) or ("united states" in ctry) or ("usd" in cat)
            # If provider omitted country, keep it (best-effort).
            if (not ctry) or is_us:
                upcoming.append(e)
    else:
        upcoming = upcoming0

    upcoming = upcoming[: max(0, int(max_items))]
    return [
        {
            "datetime_utc": e.datetime_utc.isoformat().replace("+00:00", "Z"),
            "country": e.country,
            "event": e.event,
            "category": e.category,
            "importance": e.importance,
            "forecast": e.forecast,
            "previous": e.previous,
        }
        for e in upcoming
    ]


def fetch_news_payload(
    *,
    settings: Settings,
    tickers: list[str],
    lookback_days: int = 7,
    max_items: int = 18,
) -> dict[str, Any]:
    """
    Best-effort: ticker news via FMP + a cheap aggregate sentiment (rule-based).
    Returns a dict with `items_by_ticker` for downstream ticker-specific LLM prompts.
    """
    if not settings.fmp_api_key:
        return {}
    from ai_options_trader.llm.ticker_news import fetch_fmp_stock_news
    from ai_options_trader.llm.sentiment import rule_based_sentiment

    now = datetime.now(timezone.utc)
    from_date = (now - timedelta(days=int(lookback_days))).date().isoformat()
    to_date = now.date().isoformat()

    syms = sorted({t.strip().upper() for t in tickers if t and t.strip()})
    if not syms:
        return {}

    items = fetch_fmp_stock_news(settings=settings, tickers=syms, from_date=from_date, to_date=to_date, max_pages=3)
    items = sorted(items, key=lambda x: x.published_at, reverse=True)[: max(0, int(max_items))]

    items_by_ticker: dict[str, list[dict[str, Any]]] = {}
    for it in items:
        tk = str(getattr(it, "ticker", "") or "").strip().upper()
        if not tk:
            continue
        items_by_ticker.setdefault(tk, []).append(
            {
                "ticker": tk,
                "title": getattr(it, "title", None),
                "url": getattr(it, "url", None),
                "published_at": getattr(it, "published_at", None),
                "source": getattr(it, "source", None),
                "snippet": getattr(it, "snippet", None),
            }
        )

    blob = "\n".join([f"{i.ticker}: {i.title} — {i.snippet or ''}" for i in items])[:8000]
    sent = rule_based_sentiment(blob)
    return {
        "lookback_days": int(lookback_days),
        "tickers": syms,
        "sentiment": {"label": sent.label, "confidence": float(sent.confidence)},
        "items_by_ticker": items_by_ticker,
        "items": [
            {"ticker": i.ticker, "title": i.title, "url": i.url, "published_at": i.published_at, "source": i.source}
            for i in items
        ],
    }


def fetch_general_news_items(
    *,
    settings: Settings,
    max_pages: int = 2,
    max_items: int = 30,
) -> list[dict[str, Any]]:
    """
    Best-effort: broad market news (FMP general news) with URLs.
    Useful as a fallback when a specific ETF has sparse ticker-tagged news.
    """
    if not settings.fmp_api_key:
        return []
    from ai_options_trader.llm.macro_news import fetch_fmp_general_news

    items = fetch_fmp_general_news(settings=settings, max_pages=int(max_pages))
    items = sorted(items, key=lambda x: x.published_at, reverse=True)[: max(0, int(max_items))]
    out: list[dict[str, Any]] = []
    for it in items:
        out.append(
            {
                "title": it.title,
                "url": it.url,
                "published_at": it.published_at,
                "source": it.source,
                "topic": it.topic,
                "snippet": it.snippet,
            }
        )
    return out


def filter_news_items_by_keywords(items: list[dict[str, Any]], keywords: list[str], *, max_items: int = 6) -> list[dict[str, Any]]:
    """
    Simple keyword filter over (title + snippet). Returns newest-first subset.
    """
    if not items:
        return []
    kw = [k.strip().lower() for k in (keywords or []) if k and k.strip()]
    if not kw:
        return items[: max(0, int(max_items))]
    out: list[dict[str, Any]] = []
    for it in items:
        text = f"{it.get('title') or ''} {it.get('snippet') or ''}".lower()
        if any(k in text for k in kw):
            out.append(it)
        if len(out) >= max(0, int(max_items)):
            break
    return out


def merge_news_payload(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """
    Merge two news payloads (best-effort). Keeps newer items first.
    """
    if not a:
        return b or {}
    if not b:
        return a
    out = dict(a)
    out["tickers"] = sorted(set((a.get("tickers") or []) + (b.get("tickers") or [])))
    # Merge items_by_ticker
    abt = dict(a.get("items_by_ticker") or {})
    bbt = dict(b.get("items_by_ticker") or {})
    for k, v in bbt.items():
        abt.setdefault(k, [])
        abt[k].extend(v or [])
    out["items_by_ticker"] = abt
    # Merge flat items list
    items = list(a.get("items") or []) + list(b.get("items") or [])
    # Best-effort sort by published_at (string ISO); if missing, keep order.
    items.sort(key=lambda x: str(x.get("published_at") or ""), reverse=True)
    out["items"] = items
    return out


def fetch_treasury_auction_events(
    *,
    settings: Settings | None = None,
    days_ahead: int = 21,
    max_items: int = 18,
    refresh: bool = False,
) -> list[dict[str, Any]]:
    """
    Best-effort: upcoming Treasury auction calendar from FiscalData cache.

    We prefer the local cache at `data/cache/fiscaldata/auctions_query.csv` (created by fiscal module pulls).
    If `refresh=True` and we have network/runtime support, we will attempt a refresh via FiscalDataClient.

    Returns normalized dicts compatible with `risk_watch["events"]`:
      {datetime_utc, country, event, category, importance, forecast, previous, source}
    """
    cache_path = Path("data/cache/fiscaldata/auctions_query.csv")

    # Optional refresh (runtime-only; tests/sandbox may not have network).
    if refresh:
        try:
            from ai_options_trader.data.fiscaldata import FiscalDataClient, FiscalDataEndpoint

            fd = FiscalDataClient()
            fd.fetch(
                endpoint=FiscalDataEndpoint(path="/v1/accounting/od/auctions_query"),
                params={"sort": "-auction_date,-issue_date,maturity_date"},
                cache_key="auctions_query",
                refresh=True,
            )
        except Exception:
            pass

    if not cache_path.exists():
        return []

    now = datetime.now(timezone.utc)
    end = now + timedelta(days=int(days_ahead))

    out: list[dict[str, Any]] = []
    with open(cache_path, newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            d = (row.get("auction_date") or "").strip()
            if not d:
                continue
            try:
                # Dates in cache are YYYY-MM-DD.
                dt = datetime.fromisoformat(d).replace(tzinfo=timezone.utc)
            except Exception:
                continue
            if dt < now:
                continue
            if dt > end:
                continue
            sec_type = (row.get("security_type") or "").strip()
            sec_term = (row.get("security_term") or "").strip()
            label = "Treasury auction"
            if sec_type and sec_term:
                label = f"Treasury auction: {sec_type} {sec_term}"
            elif sec_type:
                label = f"Treasury auction: {sec_type}"
            out.append(
                {
                    "datetime_utc": dt.isoformat().replace("+00:00", "Z"),
                    "country": "US",
                    "event": label,
                    "category": "Treasury auction",
                    "importance": "medium",
                    "forecast": None,
                    "previous": None,
                    "source": "fiscaldata_cache",
                }
            )
            if len(out) >= max(0, int(max_items)):
                break

    out.sort(key=lambda x: str(x.get("datetime_utc") or ""))
    return out[: max(0, int(max_items))]

