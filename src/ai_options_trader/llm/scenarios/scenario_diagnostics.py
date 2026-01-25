"""
Diagnostic tools for understanding scenario P&L estimates.
"""
from __future__ import annotations

from dataclasses import dataclass
from ai_options_trader.macro.models import MacroState
from ai_options_trader.funding.models import FundingState


@dataclass
class PnLBreakdown:
    """Detailed breakdown of P&L estimate with explanations."""
    
    # Market moves detected
    vix_change_pct: float | None = None
    vix_change_abs: float | None = None
    spx_implied_move_pct: float | None = None
    ust_10y_change_bps: float | None = None
    ust_2y_change_bps: float | None = None
    curve_change_bps: float | None = None
    cpi_change_pp: float | None = None
    hy_oas_change_bps: float | None = None
    
    # P&L components
    equity_pnl_pct: float = 0.0
    vega_pnl_pct: float = 0.0
    theta_pnl_pct: float = 0.0
    tail_hedge_pnl_pct: float = 0.0
    credit_pnl_pct: float = 0.0
    liquidity_cost_pct: float = 0.0
    
    # Explanations
    missing_inputs: list[str] = None
    warnings: list[str] = None
    assumptions: list[str] = None
    
    def __post_init__(self):
        if self.missing_inputs is None:
            self.missing_inputs = []
        if self.warnings is None:
            self.warnings = []
        if self.assumptions is None:
            self.assumptions = []
    
    @property
    def total_pnl_pct(self) -> float:
        return (
            self.equity_pnl_pct +
            self.vega_pnl_pct +
            self.theta_pnl_pct +
            self.tail_hedge_pnl_pct +
            self.credit_pnl_pct +
            self.liquidity_cost_pct
        )


def diagnose_scenario_estimate(
    baseline_macro: MacroState,
    baseline_funding: FundingState,
    scenario_macro: MacroState,
    scenario_funding: FundingState,
    portfolio_net_delta: float,
    portfolio_vega: float,
    portfolio_theta: float,
    has_tail_hedges: bool,
    horizon_months: int,
) -> PnLBreakdown:
    """
    Detailed diagnostic of P&L estimate with explanations.
    
    This shows you:
    - What market moves were detected
    - How each greek contributed
    - What's missing or assumed
    - Why the estimate might be wrong
    """
    breakdown = PnLBreakdown()
    
    # --- Detect market moves ---
    
    # VIX
    if baseline_macro.inputs.vix and scenario_macro.inputs.vix:
        baseline_vix = baseline_macro.inputs.vix
        scenario_vix = scenario_macro.inputs.vix
        breakdown.vix_change_abs = scenario_vix - baseline_vix
        breakdown.vix_change_pct = (scenario_vix - baseline_vix) / baseline_vix
        
        # Imply SPX move from VIX (rough heuristic)
        breakdown.spx_implied_move_pct = -breakdown.vix_change_pct * 0.2
    else:
        breakdown.missing_inputs.append("VIX not specified in scenario - cannot estimate equity/vol impact")
        breakdown.warnings.append("Without VIX target, model assumes no vol change (unrealistic!)")
    
    # Rates
    if baseline_macro.inputs.ust_10y and scenario_macro.inputs.ust_10y:
        breakdown.ust_10y_change_bps = (scenario_macro.inputs.ust_10y - baseline_macro.inputs.ust_10y) * 100
    else:
        breakdown.missing_inputs.append("10Y yield not specified")
    
    if baseline_macro.inputs.ust_2y and scenario_macro.inputs.ust_2y:
        breakdown.ust_2y_change_bps = (scenario_macro.inputs.ust_2y - baseline_macro.inputs.ust_2y) * 100
    else:
        breakdown.missing_inputs.append("2Y yield not specified")
    
    # Curve
    if baseline_macro.inputs.curve_2s10s and scenario_macro.inputs.curve_2s10s:
        breakdown.curve_change_bps = (scenario_macro.inputs.curve_2s10s - baseline_macro.inputs.curve_2s10s) * 100
    
    # CPI
    if baseline_macro.inputs.cpi_yoy and scenario_macro.inputs.cpi_yoy:
        breakdown.cpi_change_pp = scenario_macro.inputs.cpi_yoy - baseline_macro.inputs.cpi_yoy
    else:
        breakdown.missing_inputs.append("CPI not specified")
    
    # Credit spreads
    if baseline_macro.inputs.hy_oas and scenario_macro.inputs.hy_oas:
        breakdown.hy_oas_change_bps = scenario_macro.inputs.hy_oas - baseline_macro.inputs.hy_oas
    
    # --- Calculate P&L components ---
    
    # 1. Equity exposure
    if breakdown.spx_implied_move_pct is not None:
        breakdown.equity_pnl_pct = portfolio_net_delta * breakdown.spx_implied_move_pct
        breakdown.assumptions.append(
            f"Equity: Assumed SPX moves {breakdown.spx_implied_move_pct*100:.1f}% "
            f"based on VIX change (rough heuristic)"
        )
    else:
        breakdown.warnings.append("Equity P&L = 0 (no VIX change to infer from)")
    
    # 2. Vega
    if breakdown.vix_change_abs is not None and portfolio_vega != 0:
        breakdown.vega_pnl_pct = portfolio_vega * breakdown.vix_change_abs * 0.01
        breakdown.assumptions.append(
            f"Vega: 1 unit vega = 1% NAV per 10 VIX points (simplified)"
        )
    else:
        breakdown.warnings.append("Vega P&L = 0 (no VIX change)")
    
    # 3. Theta
    days_in_period = horizon_months * 30
    breakdown.theta_pnl_pct = portfolio_theta * days_in_period
    breakdown.assumptions.append(
        f"Theta: {portfolio_theta*100:.2f} bps/day × {days_in_period} days = {breakdown.theta_pnl_pct*100:.1f}%"
    )
    
    # 4. Tail hedges
    if has_tail_hedges:
        if breakdown.vix_change_pct and breakdown.vix_change_pct > 0.3:
            # Convexity kicks in
            breakdown.tail_hedge_pnl_pct = breakdown.vix_change_pct * 0.5
            breakdown.assumptions.append(
                f"Tail hedges: VIX up {breakdown.vix_change_pct*100:.0f}% → "
                f"convexity gains ~{breakdown.tail_hedge_pnl_pct*100:.0f}% (heuristic)"
            )
        else:
            # Just theta (already captured above)
            breakdown.assumptions.append(
                "Tail hedges: Only theta decay (VIX not up enough for convexity)"
            )
    
    # 5. Credit
    if breakdown.hy_oas_change_bps and breakdown.hy_oas_change_bps > 100:
        breakdown.credit_pnl_pct = -0.05  # Simplified
        breakdown.assumptions.append(
            f"Credit: HY OAS +{breakdown.hy_oas_change_bps:.0f} bps → assume -5% (simplified)"
        )
    
    # --- Key warnings ---
    
    if not breakdown.vix_change_pct:
        breakdown.warnings.append(
            "⚠️  VIX NOT SPECIFIED: Model cannot estimate equity or vol impact!"
        )
        breakdown.warnings.append(
            "   → Specify --vix to get realistic estimate"
        )
    
    if breakdown.ust_10y_change_bps and abs(breakdown.ust_10y_change_bps) > 20:
        if not breakdown.vix_change_pct:
            breakdown.warnings.append(
                f"⚠️  10Y moving {breakdown.ust_10y_change_bps:+.0f} bps but VIX not specified"
            )
            breakdown.warnings.append(
                "   → Big rate moves usually cause vol spikes!"
            )
    
    if breakdown.cpi_change_pp and abs(breakdown.cpi_change_pp) > 0.3:
        if not breakdown.vix_change_pct:
            breakdown.warnings.append(
                f"⚠️  CPI moving {breakdown.cpi_change_pp:+.1f}pp but VIX not specified"
            )
            breakdown.warnings.append(
                "   → Inflation surprises usually increase volatility!"
            )
    
    if breakdown.total_pnl_pct < 0 and abs(breakdown.theta_pnl_pct / breakdown.total_pnl_pct) > 0.9:
        breakdown.warnings.append(
            "⚠️  P&L is >90% driven by theta decay"
        )
        breakdown.warnings.append(
            "   → This suggests missing market impacts"
        )
        breakdown.warnings.append(
            "   → Specify more inputs (--vix, --hy-oas, etc.)"
        )
    
    return breakdown
