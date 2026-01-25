from __future__ import annotations

import json
from typing import Any

from ai_options_trader.config import Settings


def llm_position_outlook_one(
    *,
    settings: Settings,
    asof: str,
    position: dict[str, Any],
    metrics: dict[str, Any],
    trackers: dict[str, Any],
    events: list[dict[str, Any]],
    headlines: list[dict[str, Any]],
    model: str | None = None,
    temperature: float = 0.2,
) -> str:
    """
    LLM: single-position outlook, designed for an interactive "deck" review.

    Grounded strictly in the provided JSON and forced to be trade-metric-specific.
    """
    if not settings.openai_api_key:
        raise RuntimeError("Missing OPENAI_API_KEY in environment / .env")

    try:
        from openai import OpenAI  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError("openai package is not installed. Try: pip install -e .") from e

    client = OpenAI(api_key=settings.openai_api_key)
    chosen_model = model or settings.openai_model

    payload = {
        "asof": asof,
        "position": position,
        "metrics": metrics,
        "trackers": trackers,
        "events": events,
        "headlines": headlines,
    }
    payload_json = json.dumps(payload, indent=2, default=str)

    prompt = f"""
You are a "smarter macro trader" reviewing ONE open position.

You are given JSON with:
- position + computed trade metrics (entry/current, P&L$, P&L%, notional; for options: expiry/DTE/strike/breakeven)
- a small, relevant set of tracker values
- a small, relevant set of upcoming events
- ticker-specific headlines with URLs (may include curated "expert links")

Task:
Write a position outlook that is SPECIFIC to this trade and useful for next actions.

Output format (EXACT headings; do not add extra sections):
SYMBOL: <symbol>
METRICS (echo numbers): 3-8 bullets that repeat key numeric fields from JSON (no new calculations)
NEWS SENTIMENT (LLM): bullish|bearish|neutral + confidence 0..1
ACTION: hold|reduce|hedge|exit|needs_review
WHY (grounded): 2-5 bullets referencing ONLY the provided trackers/events/headlines and the metrics
WATCH NEXT (only concrete): 3-6 bullets, each bullet must be one of:
- a specific upcoming event from `events` (include datetime_utc + event name)
- a specific tracker from `trackers` (include name + value)
- a specific headline URL from `headlines`

Rules:
- Use ONLY the JSON provided. Do NOT invent macro facts, earnings, or prices.
- If there are zero headlines/links, say "no headlines provided" and set sentiment=neutral, confidence=0.5.
- If the symbol is an option (OCC-style), explicitly mention DTE and breakeven from metrics and the decay/catalyst requirement.
- If you cannot justify an action from the inputs, set ACTION=needs_review.

JSON:
{payload_json}
""".strip()

    resp = client.chat.completions.create(
        model=chosen_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=float(temperature),
    )
    return str(resp.choices[0].message.content or "").strip()

