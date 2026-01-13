from __future__ import annotations

from dataclasses import dataclass

from ai_options_trader.housing.models import HousingInputs


@dataclass(frozen=True)
class HousingRegime:
    label: str
    description: str


def classify_housing_regime(inp: HousingInputs) -> HousingRegime:
    """
    Very simple regime classifier (MVP):
    - High housing_pressure_score => stress (mortgage spreads wide + housing/REIT/MBS underperforming)
    - Low score => easing
    """
    s = inp.housing_pressure_score
    if s is None:
        return HousingRegime(label="unknown", description="Insufficient data to classify housing regime.")

    if float(s) >= 1.0:
        return HousingRegime(
            label="housing_stress",
            description="Mortgage spreads wide and housing/REIT/MBS proxies are weak vs benchmarks (risk-off / credit-tight housing impulse).",
        )
    if float(s) <= -0.5:
        return HousingRegime(
            label="housing_easing",
            description="Mortgage spread pressure is contained and housing/REIT/MBS proxies are holding up (risk-on / easing impulse).",
        )
    return HousingRegime(
        label="housing_neutral",
        description="Mixed signals: mortgage spread and housing/REIT/MBS proxies are not strongly aligned.",
    )

