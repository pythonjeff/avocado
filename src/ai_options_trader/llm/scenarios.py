"""
Scenario definitions and engine for stress testing portfolio under different market conditions.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Callable
from copy import deepcopy

from ai_options_trader.macro.models import MacroState, MacroInputs
from ai_options_trader.funding.models import FundingState, FundingInputs


@dataclass
class Scenario:
    """A scenario represents a potential future market state."""
    id: str
    name: str
    description: str
    modifier: Callable[[MacroState, FundingState], tuple[MacroState, FundingState]]
    
    # Metadata for display
    category: str  # "rates", "inflation", "liquidity", "volatility", "credit", "growth"
    severity: str  # "mild", "moderate", "severe"


def _modify_rates_rise(macro: MacroState, funding: FundingState, bps: int = 100) -> tuple[MacroState, FundingState]:
    """Rates rise scenario: increase 2Y and 10Y yields."""
    new_macro = deepcopy(macro)
    new_funding = deepcopy(funding)
    
    if new_macro.inputs.ust_10y is not None:
        new_macro.inputs.ust_10y += bps / 100.0
    if new_macro.inputs.ust_2y is not None:
        new_macro.inputs.ust_2y += bps / 100.0
    if new_macro.inputs.curve_2s10s is not None:
        # Assume parallel shift for now
        pass
    if new_macro.inputs.real_yield_proxy_10y is not None:
        new_macro.inputs.real_yield_proxy_10y += bps / 100.0
    
    return new_macro, new_funding


def _modify_rates_collapse(macro: MacroState, funding: FundingState) -> tuple[MacroState, FundingState]:
    """Ten year collapse scenario: sharp drop in long-end rates."""
    new_macro = deepcopy(macro)
    new_funding = deepcopy(funding)
    
    if new_macro.inputs.ust_10y is not None:
        new_macro.inputs.ust_10y -= 1.0  # -100 bps
    if new_macro.inputs.curve_2s10s is not None:
        # Curve steepens (10Y falls more than 2Y)
        new_macro.inputs.curve_2s10s -= 0.5  # -50 bps steepening
    if new_macro.inputs.real_yield_proxy_10y is not None:
        new_macro.inputs.real_yield_proxy_10y -= 1.0
    
    # Often accompanies flight to quality
    if new_macro.inputs.vix is not None:
        new_macro.inputs.vix *= 1.3  # VIX up 30%
    
    return new_macro, new_funding


def _modify_vix_spike(macro: MacroState, funding: FundingState) -> tuple[MacroState, FundingState]:
    """VIX spike scenario: vol explosion."""
    new_macro = deepcopy(macro)
    new_funding = deepcopy(funding)
    
    if new_macro.inputs.vix is not None:
        new_macro.inputs.vix *= 2.0  # VIX doubles
    if new_macro.inputs.vixm is not None:
        new_macro.inputs.vixm *= 1.5  # VIXM up 50% (term structure steepens)
    
    # Credit spreads widen
    if new_macro.inputs.hy_oas is not None:
        new_macro.inputs.hy_oas += 150  # +150 bps
    if new_macro.inputs.ig_oas is not None:
        new_macro.inputs.ig_oas += 50  # +50 bps
    
    # Flight to quality
    if new_macro.inputs.ust_10y is not None:
        new_macro.inputs.ust_10y -= 0.5  # -50 bps
    
    return new_macro, new_funding


def _modify_liquidity_drain(macro: MacroState, funding: FundingState) -> tuple[MacroState, FundingState]:
    """Liquidity drain: RRP depleted, reserves falling, TGA rising."""
    new_macro = deepcopy(macro)
    new_funding = deepcopy(funding)
    
    # RRP near zero
    if new_funding.inputs.on_rrp_usd_bn is not None:
        new_funding.inputs.on_rrp_usd_bn = 50.0  # $50B (depleted)
    
    # Reserves falling
    if new_funding.inputs.bank_reserves_usd_bn is not None:
        new_funding.inputs.bank_reserves_usd_bn -= 500.0  # -$500B
    
    # TGA rising (Treasury draining liquidity)
    if new_funding.inputs.tga_usd_bn is not None:
        new_funding.inputs.tga_usd_bn += 200.0  # +$200B
    
    # Funding spreads widen
    if new_funding.inputs.spread_corridor_bps is not None:
        new_funding.inputs.spread_corridor_bps += 15  # +15 bps
    
    return new_macro, new_funding


def _modify_inflation_spike(macro: MacroState, funding: FundingState) -> tuple[MacroState, FundingState]:
    """Inflation spike: CPI accelerates, breakevens rise."""
    new_macro = deepcopy(macro)
    new_funding = deepcopy(funding)
    
    if new_macro.inputs.cpi_yoy is not None:
        new_macro.inputs.cpi_yoy += 1.5  # +150 bps
    if new_macro.inputs.cpi_3m_annualized is not None:
        new_macro.inputs.cpi_3m_annualized += 2.0  # +200 bps (accelerating)
    if new_macro.inputs.core_cpi_yoy is not None:
        new_macro.inputs.core_cpi_yoy += 1.0  # +100 bps
    if new_macro.inputs.breakeven_5y is not None:
        new_macro.inputs.breakeven_5y += 0.5  # +50 bps
    
    # Real yields stay elevated or fall if Fed is behind
    if new_macro.inputs.ust_10y is not None:
        new_macro.inputs.ust_10y += 0.5  # +50 bps (Fed forced to hike)
    
    return new_macro, new_funding


def _modify_growth_shock(macro: MacroState, funding: FundingState) -> tuple[MacroState, FundingState]:
    """Growth shock: payrolls collapse, unemployment rises."""
    new_macro = deepcopy(macro)
    new_funding = deepcopy(funding)
    
    if new_macro.inputs.payrolls_3m_annualized is not None:
        new_macro.inputs.payrolls_3m_annualized = -2.0  # -2% annualized (recession)
    if new_macro.inputs.unemployment_rate is not None:
        new_macro.inputs.unemployment_rate += 1.5  # +150 bps
    if new_macro.inputs.initial_claims_4w is not None:
        new_macro.inputs.initial_claims_4w *= 1.5  # +50% increase
    
    # Rates fall (growth scare)
    if new_macro.inputs.ust_10y is not None:
        new_macro.inputs.ust_10y -= 0.75  # -75 bps
    if new_macro.inputs.ust_2y is not None:
        new_macro.inputs.ust_2y -= 1.0  # -100 bps (Fed cuts priced)
    
    # Vol rises
    if new_macro.inputs.vix is not None:
        new_macro.inputs.vix *= 1.5
    
    return new_macro, new_funding


def _modify_credit_stress(macro: MacroState, funding: FundingState) -> tuple[MacroState, FundingState]:
    """Credit stress: spreads blow out."""
    new_macro = deepcopy(macro)
    new_funding = deepcopy(funding)
    
    if new_macro.inputs.hy_oas is not None:
        new_macro.inputs.hy_oas += 300  # +300 bps (severe stress)
    if new_macro.inputs.ig_oas is not None:
        new_macro.inputs.ig_oas += 100  # +100 bps
    
    # Vol spikes
    if new_macro.inputs.vix is not None:
        new_macro.inputs.vix *= 1.8
    
    # Flight to quality
    if new_macro.inputs.ust_10y is not None:
        new_macro.inputs.ust_10y -= 0.5
    
    return new_macro, new_funding


def _modify_stagflation(macro: MacroState, funding: FundingState) -> tuple[MacroState, FundingState]:
    """Stagflation: inflation high + growth weak."""
    # Combine inflation spike + growth shock (but milder)
    new_macro, new_funding = _modify_inflation_spike(macro, funding)
    
    if new_macro.inputs.payrolls_3m_annualized is not None:
        new_macro.inputs.payrolls_3m_annualized = -0.5  # Mild contraction
    if new_macro.inputs.unemployment_rate is not None:
        new_macro.inputs.unemployment_rate += 0.8
    
    # Fed is stuck (can't cut due to inflation)
    if new_macro.inputs.ust_10y is not None:
        new_macro.inputs.ust_10y += 0.3  # Rates stay elevated
    
    return new_macro, new_funding


def _modify_goldilocks(macro: MacroState, funding: FundingState) -> tuple[MacroState, FundingState]:
    """Goldilocks: inflation cooling + growth solid."""
    new_macro = deepcopy(macro)
    new_funding = deepcopy(funding)
    
    if new_macro.inputs.cpi_yoy is not None:
        new_macro.inputs.cpi_yoy = 2.2  # Near target
    if new_macro.inputs.cpi_3m_annualized is not None:
        new_macro.inputs.cpi_3m_annualized = 2.0  # Stable
    if new_macro.inputs.payrolls_3m_annualized is not None:
        new_macro.inputs.payrolls_3m_annualized = 1.5  # Solid growth
    
    # Rates stable/falling (Fed can ease)
    if new_macro.inputs.ust_10y is not None:
        new_macro.inputs.ust_10y -= 0.3
    
    # Vol low
    if new_macro.inputs.vix is not None:
        new_macro.inputs.vix = 14.0
    
    # Spreads tight
    if new_macro.inputs.hy_oas is not None:
        new_macro.inputs.hy_oas = 300  # Tight
    
    return new_macro, new_funding


# Define all available scenarios
SCENARIOS: Dict[str, Scenario] = {
    "rates_rise_mild": Scenario(
        id="rates_rise_mild",
        name="Rates Rise (Mild)",
        description="10Y yield +50 bps, 2Y +50 bps",
        modifier=lambda m, f: _modify_rates_rise(m, f, bps=50),
        category="rates",
        severity="mild",
    ),
    "rates_rise_moderate": Scenario(
        id="rates_rise_moderate",
        name="Rates Rise (Moderate)",
        description="10Y yield +100 bps, 2Y +100 bps",
        modifier=lambda m, f: _modify_rates_rise(m, f, bps=100),
        category="rates",
        severity="moderate",
    ),
    "rates_rise_severe": Scenario(
        id="rates_rise_severe",
        name="Rates Rise (Severe)",
        description="10Y yield +200 bps, 2Y +200 bps",
        modifier=lambda m, f: _modify_rates_rise(m, f, bps=200),
        category="rates",
        severity="severe",
    ),
    "ten_year_collapse": Scenario(
        id="ten_year_collapse",
        name="Ten Year Collapse",
        description="10Y yield -100 bps, curve steepens, VIX +30%",
        modifier=_modify_rates_collapse,
        category="rates",
        severity="moderate",
    ),
    "vix_spike": Scenario(
        id="vix_spike",
        name="VIX Spike",
        description="VIX doubles, credit spreads widen, 10Y -50 bps",
        modifier=_modify_vix_spike,
        category="volatility",
        severity="severe",
    ),
    "liquidity_drain": Scenario(
        id="liquidity_drain",
        name="Liquidity Drain",
        description="RRP depleted, reserves -$500B, TGA +$200B, funding spreads +15 bps",
        modifier=_modify_liquidity_drain,
        category="liquidity",
        severity="moderate",
    ),
    "inflation_spike": Scenario(
        id="inflation_spike",
        name="Inflation Spike",
        description="CPI +150 bps YoY, 3m momentum +200 bps, breakevens +50 bps",
        modifier=_modify_inflation_spike,
        category="inflation",
        severity="moderate",
    ),
    "growth_shock": Scenario(
        id="growth_shock",
        name="Growth Shock",
        description="Payrolls -2% ann, unemployment +150 bps, 10Y -75 bps, VIX +50%",
        modifier=_modify_growth_shock,
        category="growth",
        severity="severe",
    ),
    "credit_stress": Scenario(
        id="credit_stress",
        name="Credit Stress",
        description="HY OAS +300 bps, IG OAS +100 bps, VIX +80%",
        modifier=_modify_credit_stress,
        category="credit",
        severity="severe",
    ),
    "stagflation": Scenario(
        id="stagflation",
        name="Stagflation",
        description="CPI +150 bps, payrolls -0.5% ann, rates stay elevated",
        modifier=_modify_stagflation,
        category="inflation",
        severity="severe",
    ),
    "goldilocks": Scenario(
        id="goldilocks",
        name="Goldilocks",
        description="CPI 2.2%, payrolls +1.5% ann, 10Y -30 bps, VIX 14",
        modifier=_modify_goldilocks,
        category="growth",
        severity="mild",
    ),
}


def list_scenarios(category: Optional[str] = None) -> list[Scenario]:
    """List all available scenarios, optionally filtered by category."""
    scenarios = list(SCENARIOS.values())
    if category:
        scenarios = [s for s in scenarios if s.category == category]
    return scenarios


def apply_scenario(
    scenario_id: str,
    macro_state: MacroState,
    funding_state: FundingState,
) -> tuple[MacroState, FundingState]:
    """Apply a scenario to the current market state."""
    if scenario_id not in SCENARIOS:
        raise ValueError(f"Unknown scenario: {scenario_id}")
    
    scenario = SCENARIOS[scenario_id]
    return scenario.modifier(macro_state, funding_state)
