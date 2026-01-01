from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.pipeline import Pipeline


@dataclass(frozen=True)
class FeatureContribution:
    feature: str
    value: float
    contribution: float


def explain_linear_pipeline(
    *,
    pipe: Pipeline,
    x: pd.Series,
    top_n: int = 12,
) -> dict[str, object]:
    """
    Explain a linear model inside a pipeline (StandardScaler + {LogisticRegression|Ridge}).

    Returns:
    - intercept (in model space)
    - logit_or_pred (raw linear output)
    - top positive/negative contributions (coef_i * x_scaled_i)

    Notes:
    - For LogisticRegression, the linear output is the logit.
    - For Ridge, it's the predicted value.
    """
    scaler = pipe.named_steps.get("scaler")
    model = pipe.named_steps.get("clf") or pipe.named_steps.get("reg")
    if scaler is None or model is None:
        return {"status": "unsupported_pipeline"}

    feature_names = list(x.index)
    X = pd.DataFrame([x.values], columns=feature_names)
    Xs = scaler.transform(X)

    coef = getattr(model, "coef_", None)
    intercept = getattr(model, "intercept_", None)
    if coef is None:
        return {"status": "no_coef"}
    c = np.array(coef).reshape(-1)
    if len(c) != Xs.shape[1]:
        return {"status": "shape_mismatch"}

    contrib = (c * Xs.reshape(-1)).astype(float)
    items: list[FeatureContribution] = []
    for i, name in enumerate(feature_names):
        items.append(
            FeatureContribution(
                feature=name,
                value=float(x.iloc[i]) if pd.notna(x.iloc[i]) else float("nan"),
                contribution=float(contrib[i]),
            )
        )

    items_sorted = sorted(items, key=lambda it: it.contribution)
    top_neg = items_sorted[:top_n]
    top_pos = list(reversed(items_sorted[-top_n:]))

    # Linear output
    lin = float(np.sum(contrib) + (float(np.array(intercept).reshape(-1)[0]) if intercept is not None else 0.0))

    def to_dict(lst: list[FeatureContribution]) -> list[dict[str, float | str]]:
        return [{"feature": it.feature, "value": it.value, "contribution": it.contribution} for it in lst]

    return {
        "status": "ok",
        "intercept": float(np.array(intercept).reshape(-1)[0]) if intercept is not None else 0.0,
        "linear_output": lin,
        "top_positive": to_dict(top_pos),
        "top_negative": to_dict(top_neg),
    }


