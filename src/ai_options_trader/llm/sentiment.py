from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from openai import OpenAI

@dataclass(frozen=True)
class SentimentResult:
    label: str  # 'positive'|'negative'|'neutral'
    confidence: float  # 0..1

def rule_based_sentiment(text: str) -> SentimentResult:
    t = text.lower()
    if "downgrade" in t or "miss" in t or "lawsuit" in t or "fraud" in t:
        return SentimentResult("negative", 0.65)
    if "upgrade" in t or "beat" in t or "record" in t or "strong" in t:
        return SentimentResult("positive", 0.65)
    return SentimentResult("neutral", 0.50)

def llm_sentiment(api_key: str, model: str, headline_blob: str) -> SentimentResult:
    client = OpenAI(api_key=api_key)
    prompt = (
        "You are a finance assistant. Classify the overall near-term sentiment for the stock "
        "based on the following news headlines/snippets. Return ONLY JSON: "
        '{"label":"positive|negative|neutral","confidence":0..1}.\n\n'
        f"{headline_blob}"
    )
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role":"user","content":prompt}],
        temperature=0.2,
    )
    content = resp.choices[0].message.content or ""
    # very small, safe parser
    import json
    obj = json.loads(content)
    return SentimentResult(label=obj["label"], confidence=float(obj["confidence"]))
