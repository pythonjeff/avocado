"""
Custom scenario builder - specify your exact macro view.
"""
from __future__ import annotations

from ai_options_trader.llm.scenario_ml import ScenarioFactors, apply_factor_scenario
from ai_options_trader.macro.models import MacroState
from ai_options_trader.funding.models import FundingState
from copy import deepcopy


def build_custom_scenario(
    name: str,
    description: str,
    baseline_macro: MacroState,
    baseline_funding: FundingState,
    # Specific variable changes (optional - use None to leave unchanged)
    ust_10y_target: float | None = None,  # e.g., 4.5
    ust_2y_target: float | None = None,  # e.g., 4.0
    cpi_yoy_target: float | None = None,  # e.g., 3.5
    unemployment_target: float | None = None,  # e.g., 4.6 (flat)
    vix_target: float | None = None,  # e.g., 18
    hy_oas_target: float | None = None,  # e.g., 400
    dxy_target: float | None = None,  # Dollar index
) -> tuple[MacroState, FundingState]:
    """
    Build a custom scenario by specifying exact target levels.
    
    This is easier than factor-based when you know exactly what you want:
    "I want to see 10Y at 4.5%, CPI at 3.5%, unemployment flat"
    
    Args:
        name: Scenario name
        description: What you're modeling
        baseline_macro: Current macro state
        baseline_funding: Current funding state
        ust_10y_target: Target 10Y yield (e.g., 4.5 for 4.5%)
        ust_2y_target: Target 2Y yield
        cpi_yoy_target: Target CPI YoY (e.g., 3.5 for 3.5%)
        unemployment_target: Target unemployment rate (e.g., 4.6 for 4.6%)
        vix_target: Target VIX level
        hy_oas_target: Target HY OAS (bps)
        dxy_target: Target dollar index
    
    Returns:
        Modified macro and funding states
    """
    new_macro = deepcopy(baseline_macro)
    new_funding = deepcopy(baseline_funding)
    
    # Apply exact changes
    if ust_10y_target is not None:
        new_macro.inputs.ust_10y = ust_10y_target
    
    if ust_2y_target is not None:
        new_macro.inputs.ust_2y = ust_2y_target
    
    # Recalculate curve if both rates are set
    if new_macro.inputs.ust_10y and new_macro.inputs.ust_2y:
        new_macro.inputs.curve_2s10s = new_macro.inputs.ust_10y - new_macro.inputs.ust_2y
    
    if cpi_yoy_target is not None:
        new_macro.inputs.cpi_yoy = cpi_yoy_target
        # Assume 3m momentum follows YoY (simplified)
        new_macro.inputs.cpi_3m_annualized = cpi_yoy_target
    
    # Recalculate real yield if we have both
    if new_macro.inputs.ust_10y and new_macro.inputs.breakeven_10y:
        new_macro.inputs.real_yield_proxy_10y = new_macro.inputs.ust_10y - new_macro.inputs.breakeven_10y
    
    if unemployment_target is not None:
        new_macro.inputs.unemployment_rate = unemployment_target
    
    if vix_target is not None:
        new_macro.inputs.vix = vix_target
    
    if hy_oas_target is not None:
        new_macro.inputs.hy_oas = hy_oas_target
    
    if dxy_target is not None:
        new_macro.inputs.dxy = dxy_target
    
    return new_macro, new_funding
