from dataclasses import dataclass


@dataclass
class MacroRegime:
    name: str
    inflation_trend: str
    real_yield_trend: str
    description: str
    # Optional display-friendly label (keep `name` stable for programmatic use).
    label: str | None = None
    
    def __post_init__(self):
        # Auto-generate label from name if not provided
        if self.label is None:
            self.label = self.name.replace("_", " ").title()


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


def classify_macro_regime_from_state(
    *,
    cpi_yoy: float | None = None,
    payrolls_3m_annualized: float | None = None,
    inflation_momentum_minus_be5y: float | None,
    real_yield_proxy_10y: float | None,
    z_inflation_momentum_minus_be5y: float | None = None,
    z_real_yield_proxy_10y: float | None = None,
    use_zscores: bool = True,
    cpi_target: float = 3.0,
    infl_thresh: float = 0.0,
    real_thresh: float = 0.0,
) -> MacroRegime:
    """
    Classify macro regime using either:
    - raw inputs (percentage-point units), or
    - standardized z-scores relative to history (preferred)

    Why this exists:
    - Raw `real_yield_proxy_10y = DGS10 - T10YIE` is often > 0 in modern data.
    - Raw `inflation_momentum_minus_be5y = CPI_6m_ann - T5YIE` can also skew > 0.
    Using z-scores makes the regime *relative to the recent regime distribution*,
    which produces more variation over time.
    """
    # ---------------------------------------------------------------------
    # Primary rule requested by user:
    # - "inflation" if CPI YoY is above the Fed target (default 3%)
    # - ONLY "stagflation" if we're in inflation AND job growth is negative
    # ---------------------------------------------------------------------
    if cpi_yoy is not None and float(cpi_yoy) > float(cpi_target):
        job_growth_negative = payrolls_3m_annualized is not None and float(payrolls_3m_annualized) < 0.0
        if job_growth_negative:
            return MacroRegime(
                name="stagflation",
                inflation_trend="up",
                real_yield_trend="up",
                description=f"CPI YoY > {cpi_target:.1f}% and job growth < 0 (PAYEMS 3m annualized)",
            )
        return MacroRegime(
            name="inflation",
            inflation_trend="up",
            real_yield_trend="mixed",
            description=f"CPI YoY > {cpi_target:.1f}% (inflation stage)",
        )

    # Otherwise fall back to the older 2x2 framework (prefer z-scores)
    if use_zscores and z_inflation_momentum_minus_be5y is not None and z_real_yield_proxy_10y is not None:
        base = classify_macro_regime(
            inflation_momentum_minus_be=float(z_inflation_momentum_minus_be5y),
            real_yield=float(z_real_yield_proxy_10y),
            infl_thresh=float(infl_thresh),
            real_thresh=float(real_thresh),
        )
        # Guardrail: we only want to emit "stagflation" in the CPI+jobs condition above.
        if base.name == "stagflation":
            return MacroRegime(
                name="tightening",
                inflation_trend="up",
                real_yield_trend="up",
                description="Inflation momentum up and real yields up (z-score quadrant), but CPI not above target",
            )
        return base

    # Fallback to raw values (kept for backward compatibility / early history before z-scores exist)
    base = classify_macro_regime(
        inflation_momentum_minus_be=float(inflation_momentum_minus_be5y or 0.0),
        real_yield=float(real_yield_proxy_10y or 0.0),
        infl_thresh=float(infl_thresh),
        real_thresh=float(real_thresh),
    )
    if base.name == "stagflation":
        return MacroRegime(
            name="tightening",
            inflation_trend="up",
            real_yield_trend="up",
            description="Inflation momentum up and real yields up (raw quadrant), but CPI not above target",
        )
    return base
