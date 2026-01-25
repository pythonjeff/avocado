from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from openai import OpenAI

from ai_options_trader.config import Settings


def llm_macro_full_outlook(
    *,
    settings: Settings,
    macro_state: Any,
    macro_regime: Any,
    macro_news_items: list[dict[str, Any]],
    watchlist_lines: list[str],
    lookback_label: str,
    model: str | None = None,
    temperature: float = 0.2,
) -> str:
    """
    Combine quantitative regime + qualitative macro news + an economic watchlist into a single report.

    Returns: markdown-ish text to print to terminal.
    """
    if not settings.openai_api_key:
        raise RuntimeError("Missing OPENAI_API_KEY in environment / .env")

    chosen_model = model or settings.openai_model
    client = OpenAI(api_key=settings.openai_api_key)

    macro_state_dict = macro_state.model_dump() if hasattr(macro_state, "model_dump") else macro_state
    macro_regime_dict = asdict(macro_regime) if hasattr(macro_regime, "__dataclass_fields__") else macro_regime

    payload = {
        "macro": {"state": macro_state_dict, "regime": macro_regime_dict},
        "macro_news": macro_news_items,
        "watchlist": watchlist_lines,
        "lookback": lookback_label,
    }
    payload_json = json.dumps(payload, indent=2, default=str)

    prompt = (
        "You are a macro research assistant.\n"
        "You are given JSON with:\n"
        "- a quantitative macro state + regime classification\n"
        "- a set of recent macro news items (qualitative)\n"
        "- an economic watchlist with next-release dates and current/long-run deltas\n\n"
        "Write ONE cohesive macro outlook, and explicitly tie the watchlist to the regime.\n\n"
        "Output format:\n"
        "1) Regime snapshot (1 paragraph): name + what it means\n"
        "2) Key quantitative drivers (5 bullets max): cite the specific fields you used\n"
        "3) Qualitative overlay (5 bullets max): cite news item indices like [0], [2]\n"
        "4) Outlook:\n"
        "   - 3 months (4-6 bullets)\n"
        "   - 6 months (4-6 bullets)\n"
        "   - 12 months (4-6 bullets)\n"
        "5) What to watch next (the provided watchlist, but add 1 short 'why it matters in this regime' clause to each)\n"
        "6) Biggest risks / invalidation (5 bullets max)\n\n"
        "Rules:\n"
        "- Use ONLY the JSON. Do not add facts.\n"
        "- Be concrete: rising/falling, high/low, and directionality.\n"
        "- No investing advice.\n\n"
        f"JSON:\n{payload_json}\n"
    )

    resp = client.chat.completions.create(
        model=chosen_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=float(temperature),
    )
    return (resp.choices[0].message.content or "").strip()


