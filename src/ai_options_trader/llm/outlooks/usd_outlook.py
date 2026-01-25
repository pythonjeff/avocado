from __future__ import annotations

import json
from typing import Any

from ai_options_trader.config import Settings


def llm_usd_outlook(
    *,
    settings: Settings,
    usd_state: Any,
    macro_state: Any | None = None,
    liquidity_state: Any | None = None,
    year: int = 2026,
    model: str | None = None,
    temperature: float = 0.2,
) -> str:
    """
    LLM-generated USD outlook, grounded in the provided USD regime snapshot (and optional context).

    Notes:
    - This is scenario-based and conditional; it cannot "know" the future.
    - The prompt forbids inventing facts not present in the JSON.
    """
    if not settings.openai_api_key:
        raise RuntimeError("Missing OPENAI_API_KEY in environment / .env")

    try:
        from openai import OpenAI  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError("openai package is not installed. Try: pip install -e .") from e

    client = OpenAI(api_key=settings.openai_api_key)
    chosen_model = model or settings.openai_model

    usd_dict = usd_state.model_dump() if hasattr(usd_state, "model_dump") else usd_state
    macro_dict = macro_state.model_dump() if (macro_state is not None and hasattr(macro_state, "model_dump")) else macro_state
    liq_dict = liquidity_state.model_dump() if (liquidity_state is not None and hasattr(liquidity_state, "model_dump")) else liquidity_state

    payload = {"usd": usd_dict, "context": {"macro": macro_dict, "liquidity": liq_dict}}
    payload_json = json.dumps(payload, indent=2, default=str)

    prompt = f"""
You are a macro + FX research assistant.
You are given JSON describing the latest USD regime readings (and optional macro/liquidity context).

Task:
Write a concise USD outlook focused on the path "into {year}".

Output format:
1) USD regime snapshot (3-6 bullets): cite the exact JSON fields used (e.g., usd.inputs.z_usd_level)
2) Base case into {year} (4-8 bullets): conditional statements only (if/then), no invented facts
3) Bull USD scenario (3-6 bullets): what would have to be true; what markets/sectors it pressures
4) Bear USD scenario (3-6 bullets): what would have to be true; what it would relieve
5) What to watch (5-8 bullets): specific releases/metrics to monitor (no dates if not provided)
6) Trade expression ideas (2-4 bullets): high-level ETF/sector/hedge ideas (NOT advice; defined-risk language)

Rules:
- Use ONLY the JSON below. Do not add facts not present in it.
- If context is null, do not reference it.
- Be explicit about what is "high/low" or "rising/falling" based on the values.
- If data is missing/None, say what is missing.

JSON:
{payload_json}
""".strip()

    resp = client.chat.completions.create(
        model=chosen_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=float(temperature),
    )
    return (resp.choices[0].message.content or "").strip()


