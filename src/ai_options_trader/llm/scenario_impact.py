"""
Estimate portfolio impact under different scenarios.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ai_options_trader.macro.models import MacroState
from ai_options_trader.funding.models import FundingState


@dataclass
class PortfolioImpact:
    """Estimated portfolio impact under a scenario."""
    scenario_id: str
    scenario_name: str
    
    # High-level impact
    expected_pnl_pct: float  # Expected P&L as % of NAV
    tail_hedge_pnl_pct: Optional[float] = None  # P&L from tail hedges specifically
    equity_pnl_pct: Optional[float] = None  # P&L from equity exposure
    
    # Confidence
    confidence: str = "medium"  # low, medium, high
    
    # Narrative
    summary: str = ""
    key_drivers: list[str] = None
    risks: list[str] = None
    
    def __post_init__(self):
        if self.key_drivers is None:
            self.key_drivers = []
        if self.risks is None:
            self.risks = []


def estimate_portfolio_impact(
    baseline_macro: MacroState,
    baseline_funding: FundingState,
    scenario_macro: MacroState,
    scenario_funding: FundingState,
    portfolio_net_delta: float,  # Net equity exposure as % of NAV
    portfolio_vega: float,  # Vega exposure (approx)
    portfolio_theta: float,  # Theta exposure (daily)
    has_tail_hedges: bool = True,
    horizon_months: int = 3,  # Time horizon in months
) -> PortfolioImpact:
    """
    Estimate portfolio impact based on regime changes.
    
    This is a simplified heuristic model. For a full implementation, you'd want:
    - Full greeks for each position
    - Vol surface changes
    - Correlation effects
    - Execution costs
    
    Args:
        baseline_macro: Current macro state
        baseline_funding: Current funding state
        scenario_macro: Scenario macro state
        scenario_funding: Scenario funding state
        portfolio_net_delta: Net equity exposure as % of NAV (e.g., -0.2 for 20% net short)
        portfolio_vega: Vega exposure (rough estimate)
        portfolio_theta: Theta (time decay) per day
        has_tail_hedges: Whether portfolio has convex tail hedges
    
    Returns:
        PortfolioImpact with estimated P&L and narrative
    """
    key_drivers = []
    risks = []
    
    # --- Calculate market moves ---
    
    # VIX move
    vix_change_pct = 0.0
    if baseline_macro.inputs.vix and scenario_macro.inputs.vix:
        vix_change_pct = (scenario_macro.inputs.vix - baseline_macro.inputs.vix) / baseline_macro.inputs.vix
    
    # Rates move
    ten_year_change_bps = 0.0
    if baseline_macro.inputs.ust_10y and scenario_macro.inputs.ust_10y:
        ten_year_change_bps = (scenario_macro.inputs.ust_10y - baseline_macro.inputs.ust_10y) * 100
    
    # Credit spreads
    hy_spread_change_bps = 0.0
    if baseline_macro.inputs.hy_oas and scenario_macro.inputs.hy_oas:
        hy_spread_change_bps = scenario_macro.inputs.hy_oas - baseline_macro.inputs.hy_oas
    
    # Liquidity stress (funding spreads)
    funding_stress_change_bps = 0.0
    if baseline_funding.inputs.spread_corridor_bps and scenario_funding.inputs.spread_corridor_bps:
        funding_stress_change_bps = scenario_funding.inputs.spread_corridor_bps - baseline_funding.inputs.spread_corridor_bps
    
    # --- Estimate P&L components ---
    
    # 1. Equity exposure P&L (simplified: assume SPX moves inversely to VIX in stress)
    equity_pnl_pct = 0.0
    if vix_change_pct != 0:
        # Rough heuristic: VIX up 50% → SPX down ~10%
        # This is very crude; real implementation would use actual equity beta
        spx_move_pct = -vix_change_pct * 0.2  # Simplified relationship
        equity_pnl_pct = portfolio_net_delta * spx_move_pct
        
        if abs(equity_pnl_pct) > 0.01:
            key_drivers.append(f"Equity exposure: {equity_pnl_pct*100:.1f}% (net delta {portfolio_net_delta*100:.0f}%)")
    
    # 2. Vega P&L (vol exposure)
    vega_pnl_pct = 0.0
    if vix_change_pct != 0 and portfolio_vega != 0:
        # Positive vega benefits from vol increase
        # Rough: 1 unit of vega → 1% NAV per 10 vol points
        vix_absolute_change = vix_change_pct * baseline_macro.inputs.vix if baseline_macro.inputs.vix else 0
        vega_pnl_pct = portfolio_vega * vix_absolute_change * 0.01  # Very rough
        
        if abs(vega_pnl_pct) > 0.01:
            key_drivers.append(f"Vega exposure: {vega_pnl_pct*100:.1f}% (VIX {vix_change_pct*100:+.0f}%)")
    
    # 3. Tail hedge P&L (convexity)
    tail_hedge_pnl_pct = 0.0
    if has_tail_hedges and vix_change_pct > 0.3:  # Significant vol spike
        # Tail hedges show convexity in stress
        # Rough heuristic: if VIX doubles, tail hedges make 20-50% of NAV
        tail_hedge_pnl_pct = vix_change_pct * 0.5  # Very rough
        key_drivers.append(f"Tail hedges: +{tail_hedge_pnl_pct*100:.1f}% (convexity)")
    elif has_tail_hedges:
        # Tail hedges always bleed from theta (even if VIX stays flat or rises modestly)
        # Calculate theta decay over the horizon
        days_in_period = horizon_months * 30  # Approximate
        theta_bleed_pct = portfolio_theta * days_in_period  # portfolio_theta is daily
        
        # If VIX falls, bleed is worse; if VIX rises, bleed is partially offset
        theta_adj_factor = 1.0 + (vix_change_pct * 0.5)  # Partial offset if VIX rises
        tail_hedge_pnl_pct = theta_bleed_pct * theta_adj_factor
        
        if tail_hedge_pnl_pct < 0:
            key_drivers.append(f"Tail hedges: {tail_hedge_pnl_pct*100:.1f}% (theta decay over {horizon_months}M)")
        else:
            key_drivers.append(f"Tail hedges: +{tail_hedge_pnl_pct*100:.1f}% (vol gain offsets theta)")
    
    # 4. Credit exposure (if any)
    credit_pnl_pct = 0.0
    if hy_spread_change_bps > 100:  # Material spread widening
        # Assume portfolio has some credit exposure (negative for long credit)
        credit_pnl_pct = -0.05  # Simplified: -5% for severe credit stress
        key_drivers.append(f"Credit impact: {credit_pnl_pct*100:.1f}% (HY OAS +{hy_spread_change_bps:.0f} bps)")
    
    # 5. Liquidity stress (slippage, execution costs)
    liquidity_cost_pct = 0.0
    if funding_stress_change_bps > 10:
        liquidity_cost_pct = -0.02  # -2% for severe funding stress (harder to execute)
        risks.append(f"Funding stress: SOFR-IORB +{funding_stress_change_bps:.0f} bps (execution risk)")
    
    # --- Total P&L ---
    expected_pnl_pct = equity_pnl_pct + vega_pnl_pct + tail_hedge_pnl_pct + credit_pnl_pct + liquidity_cost_pct
    
    # --- Confidence ---
    confidence = "medium"
    if abs(vix_change_pct) > 1.0 or abs(ten_year_change_bps) > 150:
        confidence = "low"  # Extreme moves are harder to model
        risks.append("Extreme move: model uncertainty high")
    elif abs(vix_change_pct) < 0.2 and abs(ten_year_change_bps) < 50:
        confidence = "high"  # Small moves are easier to estimate
    
    # --- Summary ---
    summary_parts = []
    if expected_pnl_pct > 0.05:
        summary_parts.append(f"Portfolio gains +{expected_pnl_pct*100:.1f}%")
    elif expected_pnl_pct < -0.05:
        summary_parts.append(f"Portfolio loses {expected_pnl_pct*100:.1f}%")
    else:
        summary_parts.append(f"Portfolio flat ({expected_pnl_pct*100:+.1f}%)")
    
    if vix_change_pct > 0.5 and has_tail_hedges:
        summary_parts.append("Tail hedges perform well")
    elif vix_change_pct < -0.2 and has_tail_hedges:
        summary_parts.append("Tail hedges bleed")
    
    if hy_spread_change_bps > 200:
        summary_parts.append("Credit stress")
    
    summary = ". ".join(summary_parts) + "."
    
    return PortfolioImpact(
        scenario_id="",
        scenario_name="",
        expected_pnl_pct=expected_pnl_pct,
        tail_hedge_pnl_pct=tail_hedge_pnl_pct if has_tail_hedges else None,
        equity_pnl_pct=equity_pnl_pct,
        confidence=confidence,
        summary=summary,
        key_drivers=key_drivers,
        risks=risks,
    )
