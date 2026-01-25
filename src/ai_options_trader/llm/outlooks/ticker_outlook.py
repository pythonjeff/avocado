from __future__ import annotations

import json
from typing import Any

from ai_options_trader.config import Settings


def llm_ticker_outlook(
    *,
    settings: Settings,
    ticker_snapshot: Any,
    regimes: dict[str, Any],
    year: int = 2026,
    model: str | None = None,
    temperature: float = 0.2,
) -> str:
    """
    LLM-generated 3/6/12 month ticker outlook grounded in:
    - a quantitative ticker snapshot
    - current regime states (macro/liquidity/usd/tariff/etc.)
    """
    if not settings.openai_api_key:
        raise RuntimeError("Missing OPENAI_API_KEY in environment / .env")

    try:
        from openai import OpenAI  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError("openai package is not installed. Try: pip install -e .") from e

    client = OpenAI(api_key=settings.openai_api_key)
    chosen_model = model or settings.openai_model

    snap = ticker_snapshot.model_dump() if hasattr(ticker_snapshot, "model_dump") else ticker_snapshot
    payload = {"ticker_snapshot": snap, "regimes": regimes}
    payload_json = json.dumps(payload, indent=2, default=str)

    prompt = f"""
You are a systematic macro + equities research assistant.
You are given JSON containing:
- a quantitative ticker snapshot (returns, vol, drawdown, relative strength vs benchmark)
- current regime states (macro/liquidity/usd/tariff)

Task:
Write a concise outlook for the ticker over 3/6/12 month horizons, and tie your reasoning to the regimes.
Keep it scenario-based and conditional. Focus on the path "into {year}".

Output format:
1) Snapshot (3-6 bullets): cite exact JSON fields used
2) Regime interpretation (4-8 bullets): what the macro/liquidity/usd/tariff regimes imply for this ticker
3) Outlook:
   - 3 months (4-8 bullets)
   - 6 months (4-8 bullets)
   - 12 months (4-8 bullets)
4) Key risks / invalidation (5-8 bullets)
5) Trade expressions (NOT advice):
   - Shares/ETF expression ideas (2-4 bullets)
   - Options structure ideas (2-4 bullets, defined-risk language, high-level)

Rules:
- Use ONLY the JSON. Do not invent facts (no earnings dates, no product news, no macro facts not in JSON).
- If values are missing/None, say what is missing.
- Be explicit about high/low and rising/falling using the provided numbers.

JSON:
{payload_json}
""".strip()

    resp = client.chat.completions.create(
        model=chosen_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=float(temperature),
    )
    return (resp.choices[0].message.content or "").strip()


