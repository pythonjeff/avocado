from __future__ import annotations

import json
from typing import Any

from ai_options_trader.config import Settings


def llm_moonshot_theory(
    *,
    settings: Settings,
    asof: str,
    ticker: str,
    direction: str,
    horizon_days: int,
    regime_features: dict[str, Any],
    analog_stats: dict[str, Any],
    dossier: dict[str, Any] | None = None,
    model: str | None = None,
    temperature: float = 0.2,
) -> str:
    """
    Produce a short "why this could hit" theory for a moonshot candidate.

    Strictly grounded in the provided JSON (no news / no fundamentals / no extra claims).
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
        "ticker": ticker,
        "direction": direction,
        "horizon_days": int(horizon_days),
        "regime_features": regime_features,
        "analog_stats": analog_stats,
        "dossier": dossier or {},
    }
    payload_json = json.dumps(payload, indent=2, default=str)

    prompt = f"""
You are an options trader writing a concise "moonshot thesis" for a single trade.

You are given JSON containing:
- current regime features (macro/funding/usd/rates/vol/commod/fiscal)
- analog-conditioned forward return stats for the ticker (quantiles, best/worst, an example extreme date)
- a ticker dossier (company profile, earnings calendar + earnings history rows, and recent news headlines) when available

Task:
Write a short, grounded theory for why this trade could plausibly hit over the next {int(horizon_days)} days.

Output format (markdown-ish text):
1) Thesis (2-4 bullets)
2) Why the analogs matter (2-3 bullets)
3) Catalysts to watch (2-6 bullets) — ONLY from dossier fields (earnings date/time + news titles)
4) What must be true for the option to pay (1-3 bullets)
5) Risks / why it could bleed (2-4 bullets)

Rules:
- Use ONLY the JSON provided. Do NOT add external facts, dates, or claims.
- If the dossier has no usable catalyst info, say so explicitly (e.g., "No verified company catalysts found in dossier").
- Be explicit about uncertainty and path risk (OTM options can go to zero).
- Keep it concise: ~160-260 words total.

JSON:
{payload_json}
""".strip()

    resp = client.chat.completions.create(
        model=chosen_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=float(temperature),
    )
    return str(resp.choices[0].message.content or "").strip()

