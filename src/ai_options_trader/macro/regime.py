from dataclasses import dataclass


@dataclass
class MacroRegime:
    name: str
    inflation_trend: str
    real_yield_trend: str
    description: str


def classify_macro_regime(
    inflation_momentum_minus_be: float,
    real_yield: float,
    infl_thresh: float = 0.0,
    real_thresh: float = 0.0,
) -> MacroRegime:
    """
    Classify macro regime based on inflation surprise and real yields.
    """
    infl_up = inflation_momentum_minus_be > infl_thresh
    real_up = real_yield > real_thresh

    if infl_up and real_up:
        return MacroRegime(
            name="stagflation",
            inflation_trend="up",
            real_yield_trend="up",
            description="Inflation shock + tightening financial conditions",
        )

    if infl_up and not real_up:
        return MacroRegime(
            name="reflation",
            inflation_trend="up",
            real_yield_trend="down",
            description="Growth + inflation without tightening",
        )

    if not infl_up and real_up:
        return MacroRegime(
            name="disinflation_shock",
            inflation_trend="down",
            real_yield_trend="up",
            description="Growth scare / multiple compression",
        )

    return MacroRegime(
        name="goldilocks",
        inflation_trend="down",
        real_yield_trend="down",
        description="Risk-on, supportive macro",
    )
