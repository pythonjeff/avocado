from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from ai_options_trader.config import Settings


def llm_fiscal_outlook(
    *,
    settings: Settings,
    fiscal_snapshot: dict[str, Any],
    fiscal_regime: Any,
    model: str | None = None,
    temperature: float = 0.2,
) -> str:
    """
    LLM summary of the fiscal snapshot, grounded strictly in the snapshot JSON.

    Output is intended for terminal display: concise, scenario-based, and focused on
    "so what for trading" (equities/rates/liquidity).
    """
    if not settings.openai_api_key:
        raise RuntimeError("Missing OPENAI_API_KEY in environment / .env")

    try:
        from openai import OpenAI  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError("openai package is not installed. Try: pip install -e .") from e

    client = OpenAI(api_key=settings.openai_api_key)
    chosen_model = model or settings.openai_model

    reg = asdict(fiscal_regime) if hasattr(fiscal_regime, "__dataclass_fields__") else fiscal_regime
    payload = {"fiscal_snapshot": fiscal_snapshot, "fiscal_regime": reg}
    payload_json = json.dumps(payload, indent=2, default=str)

    prompt = f"""
You are a macro + equity + rates research assistant.
You are given JSON describing a US fiscal snapshot and a rule-based regime label.

Task:
Write a concise markdown report focused on the implications for trading (NOT financial advice).
Be scenario-based and conditional, and tie every claim to fields present in the JSON.

Output format:
1) TL;DR (2-4 bullets)
2) What the fiscal picture implies (equities, rates/term premium, liquidity)
3) Market-absorption read (use auctions + dealer take + issuance mix if present)
4) Risk checklist (what would flip the regime / change your view)
5) 2-3 high-level options trade expression ideas (defined-risk; no tickers required)

Rules:
- Do NOT hallucinate data that is not present in the JSON.
- If a field is null/n/a, explicitly say it’s missing and how that affects confidence.
- Use the context markers (e.g., "stress watch") if present.

JSON:
{payload_json}
""".strip()

    resp = client.chat.completions.create(
        model=chosen_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=float(temperature),
    )
    return (resp.choices[0].message.content or "").strip()


