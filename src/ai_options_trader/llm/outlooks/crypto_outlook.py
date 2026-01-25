from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from ai_options_trader.config import Settings
from ai_options_trader.macro.regime import MacroRegime


def llm_crypto_outlook(
    *,
    settings: Settings,
    symbol: str,
    quant_snapshot: dict[str, Any],
    macro_state: Any | None = None,
    macro_regime: MacroRegime | None = None,
    liquidity_state: Any | None = None,
    usd_state: Any | None = None,
    year: int = 2026,
    model: str | None = None,
    temperature: float = 0.2,
) -> str:
    """
    LLM-generated crypto outlook for a given symbol (e.g. BTC/USD), grounded in:
    - the crypto quantitative snapshot (trend/returns/vol)
    - the current macro regime state + label (optional)
    - the current liquidity regime state (optional)
    - the current USD regime state (optional)

    The prompt forbids inventing facts not present in the JSON.
    """
    if not settings.openai_api_key:
        raise RuntimeError("Missing OPENAI_API_KEY in environment / .env")

    try:
        from openai import OpenAI  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError("openai package is not installed. Try: pip install -e .") from e

    client = OpenAI(api_key=settings.openai_api_key)
    chosen_model = model or settings.openai_model

    macro_dict = macro_state.model_dump() if (macro_state is not None and hasattr(macro_state, "model_dump")) else macro_state
    liq_dict = (
        liquidity_state.model_dump() if (liquidity_state is not None and hasattr(liquidity_state, "model_dump")) else liquidity_state
    )
    usd_dict = usd_state.model_dump() if (usd_state is not None and hasattr(usd_state, "model_dump")) else usd_state

    payload: dict[str, Any] = {
        "symbol": symbol,
        "crypto_quant": quant_snapshot,
        "macro": {"state": macro_dict, "regime": (asdict(macro_regime) if macro_regime else None)},
        "liquidity": liq_dict,
        "usd": usd_dict,
        "target_year": year,
    }
    payload_json = json.dumps(payload, indent=2, default=str)

    prompt = f"""
You are a macro + crypto research assistant.
You are given JSON describing:
- a crypto quantitative snapshot (trend/returns/vol)
- the current macro regime readings and regime label (if provided)
- the current liquidity regime snapshot (if provided)
- the current USD regime snapshot (if provided)

Task:
Write a concise outlook focused on the path "into {year}" for the crypto symbol.

Output format:
1) Snapshot (3-6 bullets): cite the exact JSON fields used (e.g., crypto_quant.returns.asset_6m)
2) Base case into {year} (6-10 bullets): conditional statements only (if/then); no invented facts
3) Bull scenario (4-7 bullets): what must be true in macro/liquidity/USD terms; how that affects crypto risk appetite
4) Bear scenario (4-7 bullets): what must be true; downside catalysts
5) What to watch (6-10 bullets): tie to the provided regime fields (macro/liquidity/USD); do NOT invent release dates
6) Trade expression ideas (2-5 bullets): high-level, defined-risk options language (NOT advice)

Rules:
- Use ONLY the JSON below. Do not add facts not present in it.
- If a context object is null, do not reference it.
- Be explicit about what is high/low or rising/falling based on values.
- If key data is missing/None, say what's missing and how it limits confidence.

JSON:
{payload_json}
""".strip()

    resp = client.chat.completions.create(
        model=chosen_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=float(temperature),
    )
    return (resp.choices[0].message.content or "").strip()


