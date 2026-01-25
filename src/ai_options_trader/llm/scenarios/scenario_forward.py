"""
Regime-conditional scenario generation for forward-looking risk analysis.

This module generates PLAUSIBLE scenarios for the next 3-6 months based on:
1. Current regime (different risks in different regimes)
2. Current market levels (constrains how far things can move)
3. Known catalysts on the horizon
4. Conditional probabilities (some transitions are more likely than others)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple
from copy import deepcopy

from ai_options_trader.macro.models import MacroState
from ai_options_trader.funding.models import FundingState
from ai_options_trader.llm.scenarios.scenario_ml import ScenarioFactors, apply_factor_scenario


@dataclass
class ForwardScenario:
    """A plausible scenario for the next 3-6 months."""
    id: str
    name: str
    description: str
    factors: ScenarioFactors
    
    # Forward-looking metadata
    probability: float  # 0-1, subjective probability
    horizon_months: int  # 3, 6, 12
    catalysts: List[str]  # What could trigger this?
    early_warning_signs: List[str]  # What to watch for
    
    # Regime context
    plausible_in_regimes: List[str]  # Which regimes allow this scenario


def generate_plausible_scenarios(
    current_regime: str,
    macro_state: MacroState,
    funding_state: FundingState,
    horizon_months: int = 3,
) -> List[ForwardScenario]:
    """
    Generate plausible scenarios for the next 3-6 months based on current regime.
    
    Different regimes have different plausible risks:
    - DISINFLATIONARY: Risk of rates spike, growth shock
    - INFLATIONARY: Risk of stagflation, policy error
    - GOLDILOCKS: Risk of surprise inflation, external shock
    - RESTRICTIVE: Risk of overtightening, credit event
    
    Args:
        current_regime: Current macro regime classification
        macro_state: Current macro state (for levels)
        funding_state: Current funding state (for liquidity)
        horizon_months: 3, 6, or 12 months
    
    Returns:
        List of plausible ForwardScenarios with probabilities
    """
    scenarios = []
    
    # Get current levels for context
    current_vix = macro_state.inputs.vix or 15
    current_10y = macro_state.inputs.ust_10y or 4.0
    current_hy_oas = macro_state.inputs.hy_oas or 350
    current_cpi = macro_state.inputs.cpi_yoy or 2.5
    on_rrp = funding_state.inputs.on_rrp_usd_bn or 200
    
    # Base scenario (continuation of current regime)
    scenarios.append(_base_case_scenario(current_regime, macro_state))
    
    # Regime-conditional plausible scenarios
    # Extract regime name and convert to uppercase for matching
    regime_name = current_regime.name.upper() if hasattr(current_regime, 'name') else str(current_regime).upper()
    
    if "DISINFLATIONARY" in regime_name or "LOW" in regime_name:
        scenarios.extend(_disinflationary_scenarios(current_vix, current_10y, current_hy_oas))
    
    elif "INFLATIONARY" in regime_name or "STAGFLATION" in regime_name:
        scenarios.extend(_inflationary_scenarios(current_cpi, current_10y))
    
    elif "GOLDILOCKS" in regime_name:
        scenarios.extend(_goldilocks_scenarios(current_vix))
    
    elif "RESTRICTIVE" in regime_name:
        scenarios.extend(_restrictive_scenarios(current_10y, current_hy_oas, on_rrp))
    
    # Universal tail risks (low probability, always possible)
    scenarios.extend(_universal_tail_risks(current_regime))
    
    # Filter by horizon
    scenarios = [s for s in scenarios if s.horizon_months <= horizon_months]
    
    # Normalize probabilities
    total_prob = sum(s.probability for s in scenarios)
    for s in scenarios:
        s.probability = s.probability / total_prob
    
    return scenarios


def _base_case_scenario(current_regime: str, macro_state: MacroState) -> ForwardScenario:
    """Base case: current regime continues with mild variations."""
    # Extract regime name if it's a MacroRegime object
    regime_name = current_regime.name if hasattr(current_regime, 'name') else str(current_regime)
    
    return ForwardScenario(
        id="base_case",
        name="Base Case (Regime Continues)",
        description=f"Current {regime_name} regime persists with modest volatility and theta decay",
        factors=ScenarioFactors(
            risk_appetite=0.0,  # Neutral
            growth_shock=0.0,  # No major change
            inflation_shock=0.0,  # No major change
            liquidity_stress=0.05,  # Mild background noise
            policy_shock=0.0,  # No surprise
        ),
        probability=0.35,  # 35% chance nothing major changes
        horizon_months=3,
        catalysts=["No major catalysts", "Gradual mean reversion", "Normal theta decay"],
        early_warning_signs=["Watch for breakout from recent ranges"],
        plausible_in_regimes=["ALL"],
    )


def _disinflationary_scenarios(vix: float, ust_10y: float, hy_oas: float) -> List[ForwardScenario]:
    """Plausible scenarios if we're in DISINFLATIONARY regime."""
    scenarios = []
    
    # Scenario 1: Soft landing / goldilocks transition (bullish)
    scenarios.append(ForwardScenario(
        id="soft_landing",
        name="Soft Landing",
        description="Inflation cools to 2%, growth stays positive, Fed cuts 50-75 bps",
        factors=ScenarioFactors(
            risk_appetite=0.5,  # Risk-on (stocks up)
            growth_shock=0.3,  # Modest positive growth
            inflation_shock=-0.3,  # Inflation cooling
            liquidity_stress=-0.2,  # Liquidity improves
            policy_shock=-0.4,  # Fed dovish (cuts)
        ),
        probability=0.25,  # 25% chance
        horizon_months=6,
        catalysts=[
            "CPI prints 2.0-2.5% YoY for 3+ months",
            "Payrolls stay positive (50k-150k/month)",
            "Fed signals rate cuts",
            "No recession",
        ],
        early_warning_signs=[
            "Median CPI slowing",
            "Initial claims staying < 250k",
            "Fed speakers sounding dovish",
            "10Y yield falling below 3.5%",
        ],
        plausible_in_regimes=["DISINFLATIONARY", "LOW REAL YIELDS"],
    ))
    
    # Scenario 2: Growth shock / hard landing (bearish)
    scenarios.append(ForwardScenario(
        id="hard_landing",
        name="Hard Landing",
        description="Payrolls turn negative, unemployment spikes, Fed cuts aggressively",
        factors=ScenarioFactors(
            risk_appetite=-0.7,  # Risk-off
            growth_shock=-0.8,  # Severe contraction
            inflation_shock=-0.2,  # Inflation falls (demand collapse)
            liquidity_stress=0.4,  # Some stress (credit spreads widen)
            policy_shock=-0.6,  # Fed forced to cut
        ),
        probability=0.15,  # 15% chance
        horizon_months=6,
        catalysts=[
            "Payrolls turn negative for 2+ months",
            "Unemployment jumps 0.5%+ in a quarter",
            "ISM PMI < 45",
            "Yield curve inverts deeper",
        ],
        early_warning_signs=[
            "Initial claims rising to 300k+",
            "Continuing claims spiking",
            "Consumer confidence falling",
            "HY spreads widening 50+ bps",
        ],
        plausible_in_regimes=["DISINFLATIONARY", "RESTRICTIVE"],
    ))
    
    # Scenario 3: Rates spike / inflation surprise (if 10Y is low)
    if ust_10y < 4.0:
        scenarios.append(ForwardScenario(
            id="inflation_surprise",
            name="Inflation Surprise",
            description="CPI re-accelerates, Fed stays hawkish, rates spike 75-100 bps",
            factors=ScenarioFactors(
                risk_appetite=-0.4,  # Risk-off (growth-sensitive stocks hurt)
                growth_shock=-0.2,  # Growth slows (higher rates)
                inflation_shock=0.7,  # Inflation re-accelerates
                liquidity_stress=0.3,  # Some stress
                policy_shock=0.6,  # Fed hawkish (hikes or stays higher for longer)
            ),
            probability=0.12,  # 12% chance
            horizon_months=6,
            catalysts=[
                "CPI 3m momentum > 3.5% annualized",
                "Core services inflation sticky",
                "Wage growth re-accelerates",
                "Oil spike (geopolitics)",
            ],
            early_warning_signs=[
                "Supercore CPI rising",
                "Wage growth > 4%",
                "Breakevens rising 20+ bps",
                "Fed speakers sounding concerned",
            ],
            plausible_in_regimes=["DISINFLATIONARY"],
        ))
    
    # Scenario 4: Credit event (if spreads are tight)
    if hy_oas < 400:
        scenarios.append(ForwardScenario(
            id="credit_event",
            name="Credit Event",
            description="Corporate defaults rise, spreads blow out, VIX spikes",
            factors=ScenarioFactors(
                risk_appetite=-0.8,  # Extreme risk-off
                growth_shock=-0.5,  # Growth slows
                inflation_shock=0.0,  # Inflation neutral
                liquidity_stress=0.7,  # High stress
                policy_shock=-0.3,  # Fed eases (but late)
            ),
            probability=0.08,  # 8% chance
            horizon_months=6,
            catalysts=[
                "Major corporate bankruptcy (e.g., another SVB)",
                "Leveraged loan / CLO stress",
                "CRE defaults spike",
                "High-yield default rate > 5%",
            ],
            early_warning_signs=[
                "HY spreads widening 100+ bps",
                "Distressed ratio rising",
                "Bank lending standards tightening sharply",
                "Loan delinquencies rising",
            ],
            plausible_in_regimes=["DISINFLATIONARY", "RESTRICTIVE"],
        ))
    
    return scenarios


def _inflationary_scenarios(cpi: float, ust_10y: float) -> List[ForwardScenario]:
    """Plausible scenarios if we're in INFLATIONARY regime."""
    scenarios = []
    
    # Scenario 1: Stagflation
    scenarios.append(ForwardScenario(
        id="stagflation",
        name="Stagflation",
        description="High inflation + weak growth, Fed stuck, rates stay elevated",
        factors=ScenarioFactors(
            risk_appetite=-0.5,  # Risk-off
            growth_shock=-0.6,  # Weak growth
            inflation_shock=0.8,  # High inflation
            liquidity_stress=0.4,  # Some stress
            policy_shock=0.5,  # Fed stays hawkish (can't cut)
        ),
        probability=0.30,  # 30% chance if already inflationary
        horizon_months=3,  # Near-term risk
        catalysts=[
            "CPI stays > 3.5% while payrolls turn negative",
            "Supply shocks (oil, food)",
            "Wage-price spiral",
            "Fed credibility at risk",
        ],
        early_warning_signs=[
            "Core services inflation sticky",
            "Initial claims rising while CPI elevated",
            "Real wages falling",
            "Consumer confidence collapsing",
        ],
        plausible_in_regimes=["INFLATIONARY", "STAGFLATION"],
    ))
    
    # Scenario 2: Policy error (Fed overtightens)
    scenarios.append(ForwardScenario(
        id="policy_error",
        name="Policy Error (Overtightening)",
        description="Fed hikes too much, breaks something, forced to reverse",
        factors=ScenarioFactors(
            risk_appetite=-0.7,  # Risk-off
            growth_shock=-0.6,  # Growth collapses
            inflation_shock=0.3,  # Inflation still elevated
            liquidity_stress=0.6,  # High stress
            policy_shock=0.8,  # Initially very hawkish, then reverses
        ),
        probability=0.20,  # 20% chance
        horizon_months=3,  # Near-term risk
        catalysts=[
            "Fed hikes into weakness",
            "Credit event / banking stress",
            "Unemployment spikes",
            "Fed forced to cut aggressively (too late)",
        ],
        early_warning_signs=[
            "Fed speakers very hawkish despite weak data",
            "2Y-10Y curve inverts deeper",
            "Credit spreads widening",
            "Dollar spiking (funding stress)",
        ],
        plausible_in_regimes=["INFLATIONARY", "RESTRICTIVE"],
    ))
    
    # Scenario 3: Inflation victory (transitions to disinflationary)
    scenarios.append(ForwardScenario(
        id="inflation_victory",
        name="Inflation Victory",
        description="Inflation falls rapidly to 2%, Fed cuts, soft landing achieved",
        factors=ScenarioFactors(
            risk_appetite=0.6,  # Risk-on
            growth_shock=0.4,  # Growth stays positive
            inflation_shock=-0.5,  # Inflation falls sharply
            liquidity_stress=-0.3,  # Liquidity improves
            policy_shock=-0.5,  # Fed dovish (cuts)
        ),
        probability=0.15,  # 15% chance (optimistic)
        horizon_months=3,  # Near-term possibility
        catalysts=[
            "Supply chains fully normalize",
            "Energy prices fall",
            "Wage growth moderates to 3-3.5%",
            "Rent inflation cools sharply",
        ],
        early_warning_signs=[
            "CPI 3m < 2% annualized",
            "Median CPI falling",
            "Fed speakers sounding confident",
            "Breakevens falling 30+ bps",
        ],
        plausible_in_regimes=["INFLATIONARY"],
    ))
    
    return scenarios


def _goldilocks_scenarios(vix: float) -> List[ForwardScenario]:
    """Plausible scenarios if we're in GOLDILOCKS regime."""
    scenarios = []
    
    # Scenario 1: Goldilocks continues (most likely)
    scenarios.append(ForwardScenario(
        id="goldilocks_continues",
        name="Goldilocks Continues",
        description="Low vol, solid growth, contained inflation - market grinds higher",
        factors=ScenarioFactors(
            risk_appetite=0.4,  # Mild risk-on
            growth_shock=0.3,  # Solid growth
            inflation_shock=0.0,  # Inflation near target
            liquidity_stress=-0.2,  # Ample liquidity
            policy_shock=-0.2,  # Fed neutral/dovish
        ),
        probability=0.35,  # 35% chance
        horizon_months=6,
        catalysts=["No major catalysts", "Benign macro backdrop"],
        early_warning_signs=["VIX staying < 15", "Spreads tight", "Positive earnings"],
        plausible_in_regimes=["GOLDILOCKS"],
    ))
    
    # Scenario 2: Melt-up / euphoria (if VIX is very low)
    if vix < 14:
        scenarios.append(ForwardScenario(
            id="melt_up",
            name="Melt-Up / Euphoria",
            description="FOMO rally, VIX collapses to <12, spreads at cycle tights",
            factors=ScenarioFactors(
                risk_appetite=0.9,  # Extreme risk-on
                growth_shock=0.5,  # Strong growth
                inflation_shock=0.2,  # Inflation ticking up (ignored)
                liquidity_stress=-0.4,  # Very loose
                policy_shock=-0.3,  # Fed dovish / behind the curve
            ),
            probability=0.12,  # 12% chance
            horizon_months=3,
            catalysts=["AI hype", "FOMO", "Retail inflows", "Short covering"],
            early_warning_signs=["VIX < 12", "Put/call ratio at lows", "Sentiment extreme"],
            plausible_in_regimes=["GOLDILOCKS"],
        ))
    
    # Scenario 3: Surprise shock (external event)
    scenarios.append(ForwardScenario(
        id="external_shock",
        name="External Shock",
        description="Geopolitical event, natural disaster, or surprise that breaks goldilocks",
        factors=ScenarioFactors(
            risk_appetite=-0.7,  # Risk-off
            growth_shock=-0.4,  # Growth hit
            inflation_shock=0.3,  # Inflation spike (supply shock)
            liquidity_stress=0.5,  # Liquidity stress
            policy_shock=0.0,  # Fed on hold (confused)
        ),
        probability=0.15,  # 15% chance
        horizon_months=6,
        catalysts=[
            "Geopolitical crisis (Taiwan, Middle East)",
            "Oil spike to $100+",
            "Cyber attack / infrastructure",
            "Major natural disaster",
        ],
        early_warning_signs=["Geopolitical tensions rising", "VIX skew steepening"],
        plausible_in_regimes=["GOLDILOCKS", "ALL"],
    ))
    
    return scenarios


def _restrictive_scenarios(ust_10y: float, hy_oas: float, on_rrp: float) -> List[ForwardScenario]:
    """Plausible scenarios if we're in RESTRICTIVE regime (high real yields)."""
    scenarios = []
    
    # Scenario 1: Something breaks (most likely in restrictive regime)
    scenarios.append(ForwardScenario(
        id="something_breaks",
        name="Something Breaks",
        description="High rates break something (credit, housing, banking), Fed forced to ease",
        factors=ScenarioFactors(
            risk_appetite=-0.8,  # Extreme risk-off
            growth_shock=-0.6,  # Growth collapses
            inflation_shock=-0.2,  # Inflation falls (demand destruction)
            liquidity_stress=0.8,  # Liquidity crisis
            policy_shock=-0.5,  # Fed forced to cut
        ),
        probability=0.30,  # 30% chance in restrictive regime
        horizon_months=6,
        catalysts=[
            "Credit event (corporate bankruptcy, bank failure)",
            "Housing market collapse",
            "Liquidity crisis (RRP depleted, funding stress)",
            "Debt ceiling / fiscal crisis",
        ],
        early_warning_signs=[
            "HY spreads widening 150+ bps",
            "Regional bank stress",
            "SOFR-IORB spiking",
            "Mortgage spreads blowing out",
        ],
        plausible_in_regimes=["RESTRICTIVE"],
    ))
    
    # Scenario 2: Higher for longer (if inflation is sticky)
    scenarios.append(ForwardScenario(
        id="higher_for_longer",
        name="Higher for Longer",
        description="Fed keeps rates elevated 12+ months, slow grind lower in risk assets",
        factors=ScenarioFactors(
            risk_appetite=-0.3,  # Mild risk-off
            growth_shock=-0.3,  # Slow growth
            inflation_shock=0.3,  # Inflation sticky
            liquidity_stress=0.3,  # Ongoing stress
            policy_shock=0.5,  # Fed stays hawkish
        ),
        probability=0.25,  # 25% chance
        horizon_months=12,  # Longer horizon
        catalysts=[
            "Core services inflation stays > 4%",
            "Labor market stays tight",
            "Fed maintains hawkish stance",
            "No major crisis forces cuts",
        ],
        early_warning_signs=[
            "Fed dots staying high",
            "Core PCE not falling",
            "Wage growth > 4%",
            "Breakevens stable/rising",
        ],
        plausible_in_regimes=["RESTRICTIVE", "INFLATIONARY"],
    ))
    
    # Scenario 3: Successful disinflation (Fed pivots)
    scenarios.append(ForwardScenario(
        id="fed_pivot",
        name="Fed Pivot",
        description="Inflation falls, Fed cuts 100+ bps, risk assets rally",
        factors=ScenarioFactors(
            risk_appetite=0.6,  # Risk-on
            growth_shock=0.2,  # Growth stabilizes
            inflation_shock=-0.5,  # Inflation falls
            liquidity_stress=-0.3,  # Liquidity improves
            policy_shock=-0.7,  # Fed cuts aggressively
        ),
        probability=0.20,  # 20% chance
        horizon_months=6,
        catalysts=[
            "CPI falls to 2-2.5%",
            "Labor market cools (not collapses)",
            "Fed signals multiple cuts",
            "No financial stability issues",
        ],
        early_warning_signs=[
            "CPI 3m < 2% annualized",
            "Initial claims rising to 240-260k (cooling, not crisis)",
            "Fed speakers sounding dovish",
            "2Y yield falling 50+ bps",
        ],
        plausible_in_regimes=["RESTRICTIVE", "DISINFLATIONARY"],
    ))
    
    return scenarios


def _universal_tail_risks(current_regime: str) -> List[ForwardScenario]:
    """Universal tail risks that are always possible (but low probability)."""
    scenarios = []
    
    # Black swan
    scenarios.append(ForwardScenario(
        id="black_swan",
        name="Black Swan",
        description="Unpredictable extreme event (GFC, COVID-scale)",
        factors=ScenarioFactors(
            risk_appetite=-1.0,  # Extreme risk-off
            growth_shock=-0.9,  # Severe contraction
            inflation_shock=0.0,  # Uncertain
            liquidity_stress=0.9,  # Extreme stress
            policy_shock=-0.8,  # Emergency Fed response
        ),
        probability=0.03,  # 3% chance (tail risk)
        horizon_months=12,
        catalysts=["Unknown unknowns", "Unpredictable external shock"],
        early_warning_signs=["None - by definition unpredictable"],
        plausible_in_regimes=["ALL"],
    ))
    
    return scenarios
