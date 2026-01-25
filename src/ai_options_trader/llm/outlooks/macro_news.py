from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import requests
from openai import OpenAI

from ai_options_trader.config import Settings
from ai_options_trader.llm.outlooks.ticker_news import parse_iso8601


@dataclass(frozen=True)
class MacroNewsItem:
    published_at: str  # ISO8601
    title: str
    url: str | None
    source: str | None
    snippet: str | None
    topic: str  # monetary|fiscal|trade_tariffs|inflation|growth_labor|markets|other


@dataclass(frozen=True)
class MacroNewsBrief:
    tldr: list[str]
    monetary_policy: str
    fiscal_policy: str
    tariffs_trade: str
    inflation: str
    implications: list[str]
    risks: list[str]
    confidence: float
    evidence_indices: list[int]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def filter_since(items: Iterable[MacroNewsItem], since: datetime) -> list[MacroNewsItem]:
    out: list[MacroNewsItem] = []
    for it in items:
        try:
            dt = parse_iso8601(it.published_at)
        except Exception:
            continue
        if dt >= since:
            out.append(it)
    out.sort(key=lambda x: parse_iso8601(x.published_at), reverse=True)
    return out


def _topic_from_text(title: str, snippet: str | None) -> str:
    t = (title or "").lower()
    s = (snippet or "").lower()
    blob = f"{t} {s}"

    def has(*words: str) -> bool:
        return any(w in blob for w in words)

    # Monetary policy
    if has("fomc", "federal reserve", "fed", "powell", "interest rate", "rate hike", "rate cut", "qt", "qe"):
        return "monetary"

    # Fiscal policy / budgets / deficits
    if has("treasury", "bond auction", "deficit", "debt ceiling", "budget", "spending bill", "stimulus", "tax"):
        return "fiscal"

    # Trade / tariffs
    if has("tariff", "trade war", "import", "export", "sanction", "duties", "wto", "customs"):
        return "trade_tariffs"

    # Inflation / prices
    if has("cpi", "ppi", "inflation", "disinflation", "prices", "core inflation", "energy prices", "oil"):
        return "inflation"

    # Growth / labor / activity
    if has("gdp", "recession", "soft landing", "unemployment", "jobs report", "nonfarm payroll", "wages"):
        return "growth_labor"

    # Markets / rates as markets topic
    if has("yield", "curve", "10-year", "2-year", "spreads", "credit", "equities", "stocks", "s&p"):
        return "markets"

    return "other"


def load_sample_macro_news_json(path: str) -> list[MacroNewsItem]:
    p = Path(path)
    if not p.exists():
        return []
    raw = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("sample macro news file must be a JSON array")
    items: list[MacroNewsItem] = []
    for obj in raw:
        if not isinstance(obj, dict):
            continue
        title = str(obj.get("title", "") or "").strip()
        snippet = (str(obj.get("snippet")) if obj.get("snippet") is not None else None)
        topic = str(obj.get("topic", "") or "").strip() or _topic_from_text(title, snippet)
        published_at = str(obj.get("published_at", "") or "").strip()
        if not title or not published_at:
            continue
        items.append(
            MacroNewsItem(
                published_at=published_at,
                title=title,
                url=(str(obj["url"]) if obj.get("url") else None),
                source=(str(obj["source"]) if obj.get("source") else None),
                snippet=snippet,
                topic=topic,
            )
        )
    return items


def fetch_fmp_general_news(
    *,
    settings: Settings,
    max_pages: int = 3,
) -> list[MacroNewsItem]:
    """
    Pull general market news and then we filter + topic-tag locally.

    Endpoint (FMP): `/api/v4/general_news?page=0&apikey=...`
    """
    if not settings.fmp_api_key:
        raise RuntimeError("Missing FMP_API_KEY in environment / .env")

    base_url = "https://financialmodelingprep.com/api/v4/general_news"
    out: list[MacroNewsItem] = []

    for page in range(max(0, int(max_pages))):
        resp = requests.get(base_url, params={"page": page, "apikey": settings.fmp_api_key}, timeout=30)
        resp.raise_for_status()
        rows = resp.json()
        # Response is typically a list of items with: title, snippet, url, publishedDate
        if not isinstance(rows, list) or not rows:
            break
        for row in rows:
            if not isinstance(row, dict):
                continue
            title = str(row.get("title", "") or "").strip()
            if not title:
                continue
            published = str(row.get("publishedDate", "") or "").strip()
            if not published:
                continue
            snippet = str(row.get("snippet", "") or "").strip() or None
            url = str(row.get("url", "") or "").strip() or None
            source = str(row.get("site", "") or "").strip() or None
            topic = _topic_from_text(title, snippet)
            published_at = parse_iso8601(published).isoformat().replace("+00:00", "Z")
            out.append(
                MacroNewsItem(
                    published_at=published_at,
                    title=title,
                    url=url,
                    source=source,
                    snippet=snippet,
                    topic=topic,
                )
            )
    return out


def format_macro_news_indexed(items: list[MacroNewsItem], max_items: int = 30) -> str:
    if not items:
        return "(no news items)"
    take = items[: max(1, int(max_items))]
    lines: list[str] = []
    for i, it in enumerate(take):
        src = f" ({it.source})" if it.source else ""
        url = f" [{it.url}]" if it.url else ""
        snip = f" — {it.snippet.strip()}" if it.snippet else ""
        lines.append(f"[{i}] {it.published_at}{src} [{it.topic}]: {it.title}{snip}{url}")
    return "\n".join(lines)


def format_macro_news_indexed_compact(items: list[MacroNewsItem], max_items: int = 30) -> str:
    """
    Compact form for audits: titles only (plus topic/date/source), no snippets/urls.
    """
    if not items:
        return "(no news items)"
    take = items[: max(1, int(max_items))]
    lines: list[str] = []
    for i, it in enumerate(take):
        src = f" ({it.source})" if it.source else ""
        lines.append(f"[{i}] {it.published_at}{src} [{it.topic}]: {it.title}")
    return "\n".join(lines)


def _extract_json_object(text: str) -> str:
    """
    Best-effort extraction of a JSON object from an LLM response.
    Handles fenced blocks and extra prose.
    """
    t = (text or "").strip()
    if not t:
        raise ValueError("Empty LLM response")
    # Remove common fenced wrappers
    t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.IGNORECASE).strip()
    t = re.sub(r"\s*```$", "", t).strip()
    # Grab first {...} block
    start = t.find("{")
    end = t.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"LLM did not return a JSON object. Got: {t[:200]!r}")
    return t[start : end + 1]


def llm_macro_outlook(
    *,
    settings: Settings,
    items: list[MacroNewsItem],
    lookback_label: str,
    model: str | None = None,
    temperature: float = 0.2,
    max_items: int = 30,
) -> str:
    """
    Clean, human-readable macro outlook (no JSON parsing), focused on 3/6/12 month horizons.
    """
    if not settings.openai_api_key:
        raise RuntimeError("Missing OPENAI_API_KEY in environment / .env")

    client = OpenAI(api_key=settings.openai_api_key)
    chosen_model = model or settings.openai_model
    blob = format_macro_news_indexed_compact(items, max_items=max_items)

    prompt = f"""
You are a macro research assistant focused on inflation + tariffs/cost-push + rates.
Using ONLY the news items below, write a concise macro outlook for the next 3/6/12 months.

Rules:
- Do NOT add facts beyond the items.
- If items are empty, say so and stop.
- Keep it clean and readable (no JSON).

Output format:
1) TL;DR (3-6 bullets)
2) 3 months: (3-6 bullets)
3) 6 months: (3-6 bullets)
4) 12 months: (3-6 bullets)
5) (Do NOT include "What to watch next" in this response; it will be generated separately.)

Lookback: {lookback_label}

News items (compact, indexed):
{blob}
""".strip()

    resp = client.chat.completions.create(
        model=chosen_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=float(temperature),
    )
    return (resp.choices[0].message.content or "").strip()

def llm_macro_news_brief_explain(
    *,
    settings: Settings,
    items: list[MacroNewsItem],
    lookback_label: str,
    model: str | None = None,
    temperature: float = 0.2,
    max_items: int = 30,
) -> MacroNewsBrief:
    if not settings.openai_api_key:
        raise RuntimeError("Missing OPENAI_API_KEY in environment / .env")

    client = OpenAI(api_key=settings.openai_api_key)
    chosen_model = model or settings.openai_model
    blob = format_macro_news_indexed_compact(items, max_items=max_items)

    prompt = f"""
You are a macro research assistant focused on inflation + tariffs/cost-push + rates regimes.
Using ONLY the news items below, produce a structured brief.

Return ONLY JSON with schema:
{{
  "tldr": ["..."],                    // 2-6 bullets
  "monetary_policy": "short paragraph",
  "fiscal_policy": "short paragraph",
  "tariffs_trade": "short paragraph",
  "inflation": "short paragraph",
  "implications": ["..."],            // 3-8 bullets (what it implies for inflation/rates/equities)
  "risks": ["..."],                   // 2-6 bullets (what could invalidate / surprises)
  "confidence": 0.0,                  // 0..1
  "evidence_indices": [0, 3, 8]       // which items you relied on
}}

Rules:
- No hallucinations; only what is supported by the items.
- If items are empty, set confidence=1.0 and explain that there were no items in TLDR.
- Confidence should reflect density + consistency + specificity.

Lookback: {lookback_label}

News items:
{blob}
""".strip()

    resp = client.chat.completions.create(
        model=chosen_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=float(temperature),
    )
    raw = (resp.choices[0].message.content or "").strip()
    obj = json.loads(_extract_json_object(raw))
    return MacroNewsBrief(
        tldr=[str(x) for x in (obj.get("tldr") or [])][:6],
        monetary_policy=str(obj.get("monetary_policy", "") or "").strip(),
        fiscal_policy=str(obj.get("fiscal_policy", "") or "").strip(),
        tariffs_trade=str(obj.get("tariffs_trade", "") or "").strip(),
        inflation=str(obj.get("inflation", "") or "").strip(),
        implications=[str(x) for x in (obj.get("implications") or [])][:8],
        risks=[str(x) for x in (obj.get("risks") or [])][:6],
        confidence=float(obj.get("confidence", 0.0) or 0.0),
        evidence_indices=[int(x) for x in (obj.get("evidence_indices") or [])],
    )


