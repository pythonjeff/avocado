"""
ML-enhanced scenario generation using historical data and factor models.

A data science approach to scenario analysis:
1. Historical scenario library (actual past events)
2. Factor decomposition (PCA on regime changes)
3. Correlation modeling (joint distributions)
4. Probabilistic scenarios (Monte Carlo with realistic correlations)
5. Regime-conditional scenarios (different behavior in different regimes)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import numpy as np
from copy import deepcopy

from ai_options_trader.macro.models import MacroState
from ai_options_trader.funding.models import FundingState


@dataclass
class HistoricalEvent:
    """A historical market stress event with observed moves."""
    id: str
    name: str
    date_range: str  # e.g., "2008-09-01 to 2008-10-31"
    description: str
    
    # Observed market moves (in standard units: bps for rates, % for equity-linked)
    vix_change_pct: Optional[float] = None  # e.g., 1.5 = VIX up 150%
    spy_change_pct: Optional[float] = None  # e.g., -0.20 = SPY down 20%
    ust_10y_change_bps: Optional[float] = None  # e.g., -80 = 10Y down 80 bps
    ust_2y_change_bps: Optional[float] = None
    hy_oas_change_bps: Optional[float] = None  # e.g., +400 = HY OAS +400 bps
    ig_oas_change_bps: Optional[float] = None
    dxy_change_pct: Optional[float] = None  # Dollar index
    oil_change_pct: Optional[float] = None
    
    # Regime context
    starting_regime: Optional[str] = None  # What regime were we in?
    
    # Probability weight (for sampling)
    probability: float = 1.0


# Historical scenario library - REAL events with actual observed moves
HISTORICAL_EVENTS = {
    "gfc_2008": HistoricalEvent(
        id="gfc_2008",
        name="Global Financial Crisis (Lehman)",
        date_range="2008-09-01 to 2008-10-31",
        description="Lehman bankruptcy, credit freeze, VIX spike to 80",
        vix_change_pct=2.4,  # VIX: 20 → 80 (+240%)
        spy_change_pct=-0.23,  # SPY down 23%
        ust_10y_change_bps=-80,  # 10Y: 3.8% → 3.0%
        ust_2y_change_bps=-150,  # 2Y: 2.5% → 1.0% (flight to quality)
        hy_oas_change_bps=+800,  # HY OAS: 500 → 1300 bps
        ig_oas_change_bps=+250,
        dxy_change_pct=0.08,  # Dollar strength
        oil_change_pct=-0.35,  # Oil collapse
        starting_regime="DISINFLATIONARY",
    ),
    "covid_crash_2020": HistoricalEvent(
        id="covid_crash_2020",
        name="COVID-19 Crash",
        date_range="2020-02-20 to 2020-03-23",
        description="COVID panic, VIX 82, SPY -34% in 33 days",
        vix_change_pct=4.1,  # VIX: 15 → 82 (+410%)
        spy_change_pct=-0.34,  # SPY down 34%
        ust_10y_change_bps=-125,  # 10Y: 1.5% → 0.25%
        ust_2y_change_bps=-140,  # 2Y: 1.5% → 0.1%
        hy_oas_change_bps=+650,  # HY OAS: 350 → 1000 bps
        ig_oas_change_bps=+240,
        dxy_change_pct=0.09,
        oil_change_pct=-0.65,  # Oil crashed to $20
        starting_regime="DISINFLATIONARY",
    ),
    "volmageddon_2018": HistoricalEvent(
        id="volmageddon_2018",
        name="Volmageddon (XIV Collapse)",
        date_range="2018-02-05 to 2018-02-09",
        description="VIX spike from 13 → 50 in 2 days, vol ETP collapse",
        vix_change_pct=2.8,  # VIX: 13 → 50 (+280%)
        spy_change_pct=-0.10,  # SPY down 10%
        ust_10y_change_bps=-20,  # 10Y: 2.85% → 2.65%
        ust_2y_change_bps=-15,
        hy_oas_change_bps=+80,  # Modest spread widening
        ig_oas_change_bps=+20,
        dxy_change_pct=0.02,
        oil_change_pct=-0.08,
        starting_regime="GOLDILOCKS",
    ),
    "taper_tantrum_2022": HistoricalEvent(
        id="taper_tantrum_2022",
        name="2022 Taper Tantrum",
        date_range="2022-01-01 to 2022-06-30",
        description="Fed hawkish pivot, rates up, 60/40 worst year since 1932",
        vix_change_pct=0.65,  # VIX: 17 → 35 (+65%)
        spy_change_pct=-0.20,  # SPY down 20%
        ust_10y_change_bps=+150,  # 10Y: 1.5% → 3.0% (rates UP)
        ust_2y_change_bps=+250,  # 2Y: 0.75% → 3.25% (aggressive)
        hy_oas_change_bps=+250,
        ig_oas_change_bps=+100,
        dxy_change_pct=0.15,  # Strong dollar
        oil_change_pct=0.40,  # Oil spiked (Ukraine)
        starting_regime="INFLATIONARY",
    ),
    "silicon_valley_bank_2023": HistoricalEvent(
        id="svb_2023",
        name="Silicon Valley Bank Collapse",
        date_range="2023-03-08 to 2023-03-17",
        description="Banking crisis fears, deposit flight, VIX spike",
        vix_change_pct=0.85,  # VIX: 18 → 28 (+85%)
        spy_change_pct=-0.05,  # SPY down 5%
        ust_10y_change_bps=-40,  # 10Y: 3.9% → 3.5% (flight to quality)
        ust_2y_change_bps=-80,  # 2Y: 5.0% → 4.2% (rate cut expectations)
        hy_oas_change_bps=+120,
        ig_oas_change_bps=+30,
        dxy_change_pct=-0.02,  # Dollar weak (Fed pivot expectations)
        oil_change_pct=-0.10,
        starting_regime="RESTRICTIVE",
    ),
}


@dataclass
class ScenarioFactors:
    """
    Factor decomposition of a scenario.
    
    Instead of specifying every variable, specify high-level factors:
    - Risk appetite (risk-on vs risk-off)
    - Growth expectations
    - Inflation expectations
    - Liquidity conditions
    - Policy stance
    
    Then map factors → variables using learned relationships.
    """
    risk_appetite: float  # -1 (extreme risk-off) to +1 (extreme risk-on)
    growth_shock: float  # -1 (severe contraction) to +1 (strong growth)
    inflation_shock: float  # -1 (deflation) to +1 (high inflation)
    liquidity_stress: float  # -1 (abundant liquidity) to +1 (liquidity crisis)
    policy_shock: float  # -1 (dovish surprise) to +1 (hawkish surprise)
    
    @property
    def name(self) -> str:
        """Generate a human-readable name from factors."""
        parts = []
        
        if self.risk_appetite < -0.5:
            parts.append("Risk-Off")
        elif self.risk_appetite > 0.5:
            parts.append("Risk-On")
        
        if self.growth_shock < -0.5:
            parts.append("Growth Shock")
        elif self.growth_shock > 0.5:
            parts.append("Strong Growth")
        
        if self.inflation_shock > 0.5:
            parts.append("Inflation Spike")
        elif self.inflation_shock < -0.5:
            parts.append("Deflation")
        
        if self.liquidity_stress > 0.5:
            parts.append("Liquidity Stress")
        
        if self.policy_shock > 0.5:
            parts.append("Hawkish Fed")
        elif self.policy_shock < -0.5:
            parts.append("Dovish Fed")
        
        return " + ".join(parts) if parts else "Neutral"


def factors_to_market_moves(factors: ScenarioFactors) -> Dict[str, float]:
    """
    Map high-level factors to specific market variable changes.
    
    This is where ML would go in a production system:
    - Train a factor model on historical data
    - Learn factor loadings (e.g., "risk_appetite -1 → VIX +150%, SPY -15%")
    - Capture non-linearities (extreme risk-off is not linear)
    
    For now, using heuristic mappings based on historical relationships.
    """
    # Base effects (linear approximation)
    # Real system would use: PCA, factor analysis, or ML regression
    
    # VIX: driven by risk_appetite + liquidity_stress
    vix_change_pct = (
        -factors.risk_appetite * 0.8  # risk-off → VIX up
        + factors.liquidity_stress * 0.5  # liquidity stress → VIX up
        + abs(factors.policy_shock) * 0.3  # policy surprise → VIX up
    )
    
    # SPY: driven by risk_appetite + growth + policy
    spy_change_pct = (
        factors.risk_appetite * 0.15  # risk-on → SPY up
        + factors.growth_shock * 0.10  # strong growth → SPY up
        - factors.policy_shock * 0.08  # hawkish → SPY down
    )
    
    # 10Y yield: driven by growth + inflation + policy
    ust_10y_change_bps = (
        factors.growth_shock * 50  # strong growth → yields up
        + factors.inflation_shock * 80  # inflation → yields up
        + factors.policy_shock * 100  # hawkish → yields up
        - factors.risk_appetite * 30  # risk-off → flight to quality (yields down)
    )
    
    # 2Y yield: more sensitive to policy than 10Y
    ust_2y_change_bps = (
        factors.policy_shock * 150  # Very sensitive to Fed
        + factors.growth_shock * 30
        + factors.inflation_shock * 50
        - factors.risk_appetite * 20
    )
    
    # Credit spreads: driven by risk_appetite + liquidity + growth
    hy_oas_change_bps = (
        -factors.risk_appetite * 300  # risk-off → spreads widen
        + factors.liquidity_stress * 200  # liquidity stress → spreads widen
        - factors.growth_shock * 100  # growth shock → spreads widen
    )
    
    ig_oas_change_bps = hy_oas_change_bps * 0.3  # IG less volatile than HY
    
    # Dollar: driven by risk_appetite + policy
    dxy_change_pct = (
        -factors.risk_appetite * 0.08  # risk-off → dollar strength
        + factors.policy_shock * 0.10  # hawkish → dollar strength
    )
    
    # Oil: driven by growth + risk_appetite
    oil_change_pct = (
        factors.growth_shock * 0.30  # strong growth → oil up
        + factors.risk_appetite * 0.25  # risk-on → oil up
    )
    
    return {
        "vix_change_pct": vix_change_pct,
        "spy_change_pct": spy_change_pct,
        "ust_10y_change_bps": ust_10y_change_bps,
        "ust_2y_change_bps": ust_2y_change_bps,
        "hy_oas_change_bps": hy_oas_change_bps,
        "ig_oas_change_bps": ig_oas_change_bps,
        "dxy_change_pct": dxy_change_pct,
        "oil_change_pct": oil_change_pct,
    }


def apply_historical_event(
    event_id: str,
    macro_state: MacroState,
    funding_state: FundingState,
    severity: float = 1.0,
) -> Tuple[MacroState, FundingState]:
    """
    Apply a historical event to current market state.
    
    Args:
        event_id: ID of historical event (e.g., "gfc_2008")
        macro_state: Current macro state
        funding_state: Current funding state
        severity: Scale factor (0.5 = half the historical move, 2.0 = double)
    
    Returns:
        Modified macro and funding states
    """
    if event_id not in HISTORICAL_EVENTS:
        raise ValueError(f"Unknown historical event: {event_id}")
    
    event = HISTORICAL_EVENTS[event_id]
    new_macro = deepcopy(macro_state)
    new_funding = deepcopy(funding_state)
    
    # Apply observed moves scaled by severity
    if event.vix_change_pct and new_macro.inputs.vix:
        new_macro.inputs.vix *= (1 + event.vix_change_pct * severity)
    
    if event.ust_10y_change_bps and new_macro.inputs.ust_10y:
        new_macro.inputs.ust_10y += (event.ust_10y_change_bps / 100.0) * severity
    
    if event.ust_2y_change_bps and new_macro.inputs.ust_2y:
        new_macro.inputs.ust_2y += (event.ust_2y_change_bps / 100.0) * severity
    
    if event.hy_oas_change_bps and new_macro.inputs.hy_oas:
        new_macro.inputs.hy_oas += event.hy_oas_change_bps * severity
    
    if event.ig_oas_change_bps and new_macro.inputs.ig_oas:
        new_macro.inputs.ig_oas += event.ig_oas_change_bps * severity
    
    if event.dxy_change_pct and new_macro.inputs.dxy:
        new_macro.inputs.dxy *= (1 + event.dxy_change_pct * severity)
    
    if event.oil_change_pct and new_macro.inputs.oil_price:
        new_macro.inputs.oil_price *= (1 + event.oil_change_pct * severity)
    
    return new_macro, new_funding


def apply_factor_scenario(
    factors: ScenarioFactors,
    macro_state: MacroState,
    funding_state: FundingState,
) -> Tuple[MacroState, FundingState]:
    """
    Apply a factor-based scenario to current market state.
    
    This is more flexible than hard-coded scenarios because:
    - User specifies high-level factors (risk-on/off, growth, inflation)
    - Model maps factors to specific variable changes
    - Relationships are learned from data (or heuristic for v0)
    """
    moves = factors_to_market_moves(factors)
    
    new_macro = deepcopy(macro_state)
    new_funding = deepcopy(funding_state)
    
    # Apply moves
    if new_macro.inputs.vix:
        new_macro.inputs.vix *= (1 + moves["vix_change_pct"])
    
    if new_macro.inputs.ust_10y:
        new_macro.inputs.ust_10y += moves["ust_10y_change_bps"] / 100.0
    
    if new_macro.inputs.ust_2y:
        new_macro.inputs.ust_2y += moves["ust_2y_change_bps"] / 100.0
    
    if new_macro.inputs.hy_oas:
        new_macro.inputs.hy_oas += moves["hy_oas_change_bps"]
    
    if new_macro.inputs.ig_oas:
        new_macro.inputs.ig_oas += moves["ig_oas_change_bps"]
    
    if new_macro.inputs.dxy:
        new_macro.inputs.dxy *= (1 + moves["dxy_change_pct"])
    
    if new_macro.inputs.oil_price:
        new_macro.inputs.oil_price *= (1 + moves["oil_change_pct"])
    
    return new_macro, new_funding


# Predefined factor-based scenarios (easier to specify than variable-by-variable)
FACTOR_SCENARIOS = {
    "extreme_risk_off": ScenarioFactors(
        risk_appetite=-1.0,
        growth_shock=-0.5,
        inflation_shock=0.0,
        liquidity_stress=0.8,
        policy_shock=0.0,
    ),
    "stagflation_shock": ScenarioFactors(
        risk_appetite=-0.3,
        growth_shock=-0.7,
        inflation_shock=0.9,
        liquidity_stress=0.3,
        policy_shock=0.6,  # Fed forced to stay hawkish
    ),
    "goldilocks_boost": ScenarioFactors(
        risk_appetite=0.8,
        growth_shock=0.6,
        inflation_shock=-0.3,  # Cooling inflation
        liquidity_stress=-0.5,  # Ample liquidity
        policy_shock=-0.4,  # Dovish Fed
    ),
    "policy_error": ScenarioFactors(
        risk_appetite=-0.6,
        growth_shock=-0.4,
        inflation_shock=0.2,
        liquidity_stress=0.4,
        policy_shock=0.9,  # Fed overtightens
    ),
}
