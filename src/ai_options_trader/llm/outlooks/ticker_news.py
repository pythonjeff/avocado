from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from openai import OpenAI
import requests

from ai_options_trader.config import Settings


@dataclass(frozen=True)
class NewsItem:
    ticker: str
    title: str
    url: str | None
    published_at: str  # ISO8601
    source: str | None = None
    snippet: str | None = None


@dataclass(frozen=True)
class NewsBrief:
    summary: str
    key_items: list[str]
    tone: str  # bullish|bearish|neutral
    confidence: float  # 0..1
    reasons: list[str]
    uncertainties: list[str]
    evidence_indices: list[int]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_iso8601(s: str) -> datetime:
    """
    Parse timestamps into UTC.

    Supports:
    - ISO8601 (accepts 'Z' suffix)
    - FMP style: 'YYYY-MM-DD HH:MM:SS' (assumed UTC)
    """
    s = (s or "").strip()
    if not s:
        raise ValueError("Empty datetime string")
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        # Common non-ISO format from some feeds: 'YYYY-MM-DD HH:MM:SS'
        # Assume UTC if timezone is not provided.
        dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    if dt.tzinfo is None:
        # Assume UTC if missing tz.
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def filter_items_since(items: Iterable[NewsItem], since: datetime) -> list[NewsItem]:
    out: list[NewsItem] = []
    for it in items:
        try:
            dt = parse_iso8601(it.published_at)
        except Exception:
            continue
        if dt >= since:
            out.append(it)
    # Most recent first
    out.sort(key=lambda x: parse_iso8601(x.published_at), reverse=True)
    return out


def infer_underlying_from_symbol(symbol: str) -> str:
    """
    Best-effort underlying extraction.

    Handles:
    - Equity: 'AAPL' -> 'AAPL'
    - OCC options: 'AAPL251219C00150000' -> 'AAPL'
    """
    sym = (symbol or "").strip().upper()
    m = re.match(r"^([A-Z]+)\d{6}[CP]\d{8}$", sym)
    if m:
        return m.group(1)
    # Fallback: treat as equity ticker
    return sym


def load_sample_news_json(path: str) -> list[NewsItem]:
    p = Path(path)
    if not p.exists():
        return []
    raw = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("sample news file must be a JSON array")
    items: list[NewsItem] = []
    for obj in raw:
        if not isinstance(obj, dict):
            continue
        try:
            items.append(
                NewsItem(
                    ticker=str(obj.get("ticker", "")).upper(),
                    title=str(obj.get("title", "")),
                    url=(str(obj["url"]) if obj.get("url") else None),
                    published_at=str(obj.get("published_at", "")),
                    source=(str(obj["source"]) if obj.get("source") else None),
                    snippet=(str(obj["snippet"]) if obj.get("snippet") else None),
                )
            )
        except Exception:
            continue
    return items


def fetch_fmp_stock_news(
    *,
    settings: Settings,
    tickers: list[str],
    from_date: str,
    to_date: str,
    start_page: int = 0,
    max_pages: int = 3,
) -> list[NewsItem]:
    """
    Fetch FMP `stock_news` for a list of tickers and return NewsItems.

    Example:
    `/api/v3/stock_news?tickers=AAPL,FB&page=0&from=2024-01-01&to=2024-03-01&apikey=...`
    """
    if not settings.fmp_api_key:
        raise RuntimeError("Missing FMP_API_KEY in environment / .env")

    base_url = "https://financialmodelingprep.com/api/v3/stock_news"
    out: list[NewsItem] = []

    syms = [t.strip().upper() for t in tickers if t and t.strip()]
    if not syms:
        return []

    for page in range(int(start_page), int(start_page) + max(0, int(max_pages))):
        params = {
            "tickers": ",".join(syms),
            "page": int(page),
            "from": str(from_date),
            "to": str(to_date),
            "apikey": settings.fmp_api_key,
        }
        resp = requests.get(base_url, params=params, timeout=30)
        resp.raise_for_status()
        rows = resp.json()
        # Response shape: list[ {symbol, publishedDate, title, site, text, url, ...}, ... ]
        if not isinstance(rows, list) or not rows:
            break

        for row in rows:
            if not isinstance(row, dict):
                continue

            sym = str(row.get("symbol", "") or "").strip().upper()
            if not sym:
                continue
            if sym not in syms:
                continue

            title = str(row.get("title", "") or "").strip()
            dt_raw = str(row.get("publishedDate", "") or "").strip()
            if not dt_raw:
                continue

            site = str(row.get("site", "") or "").strip() or None
            url = str(row.get("url", "") or "").strip() or None
            text = str(row.get("text", "") or "").strip() or None

            # Keep published_at in ISO format for our downstream parser.
            published_at = parse_iso8601(dt_raw).isoformat().replace("+00:00", "Z")

            out.append(
                NewsItem(
                    ticker=sym,
                    title=title,
                    url=url,
                    published_at=published_at,
                    source=site,
                    snippet=text,
                )
            )

    return out


def format_news_for_llm(items: list[NewsItem], max_items: int = 12) -> str:
    """
    Compact, LLM-friendly format. Keep it deterministic.
    """
    if not items:
        return "(no news items)"
    lines: list[str] = []
    for it in items[: max(1, int(max_items))]:
        src = f" ({it.source})" if it.source else ""
        url = f" [{it.url}]" if it.url else ""
        snip = f" — {it.snippet.strip()}" if it.snippet else ""
        lines.append(f"- {it.published_at}{src}: {it.title}{snip}{url}")
    return "\n".join(lines)


def format_news_for_llm_indexed(items: list[NewsItem], max_items: int = 12) -> str:
    """
    Like `format_news_for_llm` but with stable indices so the LLM can cite evidence.
    """
    if not items:
        return "(no news items)"
    lines: list[str] = []
    take = items[: max(1, int(max_items))]
    for i, it in enumerate(take):
        src = f" ({it.source})" if it.source else ""
        url = f" [{it.url}]" if it.url else ""
        snip = f" — {it.snippet.strip()}" if it.snippet else ""
        lines.append(f"[{i}] {it.published_at}{src}: {it.title}{snip}{url}")
    return "\n".join(lines)


def llm_recent_news_brief(
    *,
    settings: Settings,
    ticker: str,
    items: list[NewsItem],
    model: str | None = None,
    temperature: float = 0.2,
    lookback_label: str = "the lookback window",
    explain: bool = False,
) -> str:
    """
    Produce a short summary of recent news for a ticker.
    """
    if not settings.openai_api_key:
        raise RuntimeError("Missing OPENAI_API_KEY in environment / .env")

    client = OpenAI(api_key=settings.openai_api_key)
    news_blob = format_news_for_llm_indexed(items)
    model_name = model or settings.openai_model

    if explain:
        prompt = f"""
You are a finance assistant. Using ONLY the news items below, summarize the most relevant developments for {ticker}.

Rules:
- Use ONLY the provided items. Do NOT add facts.
- If items are empty, set tone=neutral, confidence=1.0, and explain that there were no items.
- Evaluate likely near-term impact (days to weeks) based on the text we have.
- Confidence should reflect: (a) number of relevant items, (b) consistency, (c) specificity, (d) credibility of sources implied by the feed.
- Return ONLY JSON (no markdown, no extra text) with this schema:
  {{
    "summary": "2-4 sentences",
    "key_items": ["...", "..."],   // max 5
    "tone": "bullish|bearish|neutral",
    "confidence": 0.0,
    "reasons": ["...", "..."],     // 2-6 bullets explaining tone/confidence
    "uncertainties": ["...", "..."], // 0-5 bullets
    "evidence_indices": [0, 2]     // indices you relied on (from the list below)
  }}

Lookback: {lookback_label}

News items (indexed):
{news_blob}
""".strip()
    else:
        prompt = f"""
You are a finance assistant. Summarize the most relevant developments for {ticker} from the news items below.

Rules:
- Use ONLY the provided news items. If there are none, say so.
- Focus on what's new in {lookback_label}, and how it could impact price in the near term (days to weeks).
- Be concise and factual. No hype. No investment advice.
- Output format:
  1) 2-4 sentence summary
  2) Bullet list of key items (max 5)
  3) "Tone:" one of bullish/bearish/neutral and "Confidence:" 0-1

News items:
{news_blob}
""".strip()

    resp = client.chat.completions.create(
        model=model_name,
        messages=[{"role": "user", "content": prompt}],
        temperature=float(temperature),
    )
    return (resp.choices[0].message.content or "").strip()


def llm_recent_news_brief_explain(
    *,
    settings: Settings,
    ticker: str,
    items: list[NewsItem],
    model: str | None = None,
    temperature: float = 0.2,
    lookback_label: str = "the lookback window",
) -> NewsBrief:
    """
    Same as `llm_recent_news_brief(..., explain=True)` but parsed into a typed object.
    """
    raw = llm_recent_news_brief(
        settings=settings,
        ticker=ticker,
        items=items,
        model=model,
        temperature=temperature,
        lookback_label=lookback_label,
        explain=True,
    )
    obj = json.loads(raw)
    return NewsBrief(
        summary=str(obj.get("summary", "") or "").strip(),
        key_items=[str(x) for x in (obj.get("key_items") or [])][:5],
        tone=str(obj.get("tone", "") or "").strip(),
        confidence=float(obj.get("confidence", 0.0) or 0.0),
        reasons=[str(x) for x in (obj.get("reasons") or [])][:6],
        uncertainties=[str(x) for x in (obj.get("uncertainties") or [])][:5],
        evidence_indices=[int(x) for x in (obj.get("evidence_indices") or [])],
    )


