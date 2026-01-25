from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from ai_options_trader.config import Settings


def llm_regime_summary(
    *,
    settings: Settings,
    macro_state: Any,
    macro_regime: Any,
    tariff_regimes: list[dict[str, Any]],
    model: str | None = None,
    temperature: float = 0.2,
) -> str:
    """
    Ask an LLM to summarize the current macro + tariff/cost-push regimes.

    `tariff_regimes` is expected to be a list of dicts like:
      {"basket": str, "description": str, "benchmark": str, "state": TariffRegimeState}

    Returns: markdown-ish text to print to terminal.
    """
    if not settings.openai_api_key:
        raise RuntimeError("Missing OPENAI_API_KEY in environment / .env")

    chosen_model = model or settings.openai_model
    try:
        from openai import OpenAI  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError("openai package is not installed. Try: pip install -e .") from e

    client = OpenAI(api_key=settings.openai_api_key)

    # Pydantic models: model_dump(); dataclasses: asdict()
    macro_state_dict = macro_state.model_dump() if hasattr(macro_state, "model_dump") else macro_state
    macro_regime_dict = asdict(macro_regime) if hasattr(macro_regime, "__dataclass_fields__") else macro_regime

    tariff_payload = []
    for item in tariff_regimes:
        st = item.get("state")
        st_dict = st.model_dump() if hasattr(st, "model_dump") else st
        tariff_payload.append(
            {
                "basket": item.get("basket"),
                "description": item.get("description"),
                "benchmark": item.get("benchmark"),
                "state": st_dict,
            }
        )

    payload = {
        "macro": {"state": macro_state_dict, "regime": macro_regime_dict},
        "tariff": tariff_payload,
    }
    payload_json = json.dumps(payload, indent=2, default=str)

    prompt = (
        "You are a macro + equity cross-asset research assistant.\n"
        "You are given JSON describing the latest regime readings.\n\n"
        "Write a concise markdown report with:\n"
        "1) TL;DR (2-4 bullets)\n"
        "2) What these regimes imply (macro + equity impact)\n"
        "3) Key risks / what could invalidate\n"
        "4) Follow-up checklist (what to check next, what data to pull)\n"
        "5) Optional: 2-3 trade-structure ideas centered around options calls or puts(NOT financial advice; keep high-level)\n\n"
        "Be specific about what is 'high/low' or 'rising/falling' based on the provided values.\n"
        "Do not hallucinate data not present in the JSON.\n\n"
        f"JSON:\n{payload_json}\n"
    )

    resp = client.chat.completions.create(
        model=chosen_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
    )
    return resp.choices[0].message.content or ""


