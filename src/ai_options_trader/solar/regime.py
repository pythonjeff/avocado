from __future__ import annotations

from dataclasses import dataclass

from ai_options_trader.solar.models import SolarInputs


@dataclass(frozen=True)
class SolarRegime:
    label: str
    description: str


def classify_solar_regime(inp: SolarInputs) -> SolarRegime:
    """
    MVP classifier:
    - High headwind score => silver up, solar underperforming (cost pressure headwind)
    - Low score => solar outperforming despite silver (tailwind)
    """
    s = inp.solar_headwind_score
    if s is None:
        return SolarRegime(label="unknown", description="Insufficient data to classify solar regime.")
    if float(s) >= 1.0:
        return SolarRegime(
            label="silver_headwind",
            description="Silver momentum is strong while solar basket underperforms SPY (input-cost headwind risk).",
        )
    if float(s) <= -0.5:
        return SolarRegime(
            label="silver_tailwind",
            description="Solar basket outperforms despite weak/muted silver momentum (resilience tailwind).",
        )
    return SolarRegime(
        label="solar_neutral",
        description="Mixed signals between silver momentum and solar relative performance.",
    )
