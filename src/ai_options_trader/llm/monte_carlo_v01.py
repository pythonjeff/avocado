"""
v0.1: Upgraded Monte Carlo with position-level P&L and S/IV dynamics.

Key improvements:
1. Position-level representation (not just aggregate greeks)
2. Separate S and IV simulation (correlated)
3. Taylor approximation per instrument
4. Scenario attribution (top winners/losers)
5. Regime-conditional assumptions
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Dict, List, Tuple

from ai_options_trader.portfolio.positions import Portfolio


@dataclass
class ScenarioAssumptions:
    """Regime-conditional scenario assumptions."""
    
    regime: str
    horizon_months: int
    
    # Equity dynamics
    equity_drift: float  # Annualized
    equity_vol: float  # Annualized
    
    # Vol dynamics  
    iv_mean_reversion_speed: float
    iv_vol_of_vol: float
    iv_mean_level: float
    
    # Correlations
    corr_return_iv: float  # Negative skew in risk-off
    
    # Jump risk (rare but decisive for hedges)
    jump_probability: float
    jump_size_mean: float  # % down
    jump_iv_spike: float  # pts up
    
    @classmethod
    def for_regime(cls, regime: str, horizon_months: int) -> ScenarioAssumptions:
        """
        Get regime-conditional assumptions.
        
        Available regimes:
        - STAGFLATION / INFLATIONARY: High inflation + weak growth
        - GOLDILOCKS / DISINFLATIONARY: Low inflation + strong growth
        - RISK_OFF / CRASH: Flight to safety, sharp drawdown
        - RATES_SHOCK / TERM_PREMIUM: Aggressive Fed hiking, bond sell-off
        - CREDIT_STRESS / CREDIT_EVENT: Spread widening, credit concerns
        - SLOW_BLEED / GRINDING_DOWN: Persistent drift lower, no vol spike
        - VOL_CRUSH / COMPLACENT: Low realized vol, put premium collapse
        - ALL: Balanced/neutral conditions
        """
        
        if regime.upper() in ["STAGFLATION", "INFLATIONARY"]:
            return cls(
                regime=regime,
                horizon_months=horizon_months,
                equity_drift=-0.02,  # Slight negative drift
                equity_vol=0.22,  # Higher vol (22%)
                iv_mean_reversion_speed=0.5,
                iv_vol_of_vol=0.80,  # High vol-of-vol
                iv_mean_level=0.25,
                corr_return_iv=-0.65,  # Strong negative skew
                jump_probability=0.10,  # 10% chance of jump
                jump_size_mean=-0.15,  # -15% crash
                jump_iv_spike=10.0,  # +10pts IV
            )
        
        elif regime.upper() in ["GOLDILOCKS", "DISINFLATIONARY"]:
            return cls(
                regime=regime,
                horizon_months=horizon_months,
                equity_drift=0.08,  # Positive drift
                equity_vol=0.15,  # Lower vol (15%)
                iv_mean_reversion_speed=1.0,
                iv_vol_of_vol=0.50,
                iv_mean_level=0.18,
                corr_return_iv=-0.50,  # Moderate negative skew
                jump_probability=0.03,  # 3% chance
                jump_size_mean=-0.10,
                jump_iv_spike=5.0,
            )
        
        elif regime.upper() in ["RISK_OFF", "CRASH", "RISK-OFF"]:
            return cls(
                regime=regime,
                horizon_months=horizon_months,
                equity_drift=-0.25,  # Sharp drawdown (-25% annual)
                equity_vol=0.35,  # Extreme vol (35%)
                iv_mean_reversion_speed=0.2,  # Slow mean reversion (vol stays high)
                iv_vol_of_vol=1.2,  # Very high vol-of-vol
                iv_mean_level=0.40,  # High IV target
                corr_return_iv=-0.80,  # Very strong negative skew
                jump_probability=0.25,  # 25% chance - frequent gaps
                jump_size_mean=-0.20,  # -20% crash
                jump_iv_spike=15.0,  # +15pts IV spike
            )
        
        elif regime.upper() in ["RATES_SHOCK", "TERM_PREMIUM", "RATES-SHOCK", "TERM-PREMIUM"]:
            return cls(
                regime=regime,
                horizon_months=horizon_months,
                equity_drift=-0.10,  # Moderate downside
                equity_vol=0.24,  # Elevated vol
                iv_mean_reversion_speed=0.6,
                iv_vol_of_vol=0.70,
                iv_mean_level=0.22,
                corr_return_iv=-0.55,  # Moderate skew (rates≠equity crash)
                jump_probability=0.08,  # Some jumps
                jump_size_mean=-0.12,
                jump_iv_spike=8.0,
            )
        
        elif regime.upper() in ["CREDIT_STRESS", "CREDIT_EVENT", "CREDIT-STRESS", "CREDIT-EVENT"]:
            return cls(
                regime=regime,
                horizon_months=horizon_months,
                equity_drift=-0.15,  # Credit-driven selloff
                equity_vol=0.28,  # High vol
                iv_mean_reversion_speed=0.4,
                iv_vol_of_vol=0.90,
                iv_mean_level=0.30,
                corr_return_iv=-0.75,  # Strong skew (credit stress → flight to quality)
                jump_probability=0.15,  # Frequent jumps
                jump_size_mean=-0.18,  # Sharp drops
                jump_iv_spike=12.0,
            )
        
        elif regime.upper() in ["SLOW_BLEED", "GRINDING_DOWN", "SLOW-BLEED", "GRINDING-DOWN"]:
            return cls(
                regime=regime,
                horizon_months=horizon_months,
                equity_drift=-0.08,  # Persistent drift lower
                equity_vol=0.16,  # Low realized vol (no crash, just bleed)
                iv_mean_reversion_speed=0.9,
                iv_vol_of_vol=0.45,
                iv_mean_level=0.19,
                corr_return_iv=-0.40,  # Weak skew (no panic)
                jump_probability=0.02,  # Rare jumps (grinding, not crashing)
                jump_size_mean=-0.08,
                jump_iv_spike=4.0,
            )
        
        elif regime.upper() in ["VOL_CRUSH", "COMPLACENT", "VOL-CRUSH"]:
            return cls(
                regime=regime,
                horizon_months=horizon_months,
                equity_drift=0.10,  # Positive drift (melt-up)
                equity_vol=0.12,  # Very low realized vol
                iv_mean_reversion_speed=1.5,  # Fast mean reversion (IV collapses)
                iv_vol_of_vol=0.35,
                iv_mean_level=0.14,  # Low IV target
                corr_return_iv=-0.35,  # Weak skew (complacency)
                jump_probability=0.01,  # Almost no jumps
                jump_size_mean=-0.06,
                jump_iv_spike=3.0,
            )
        
        else:  # ALL / default
            return cls(
                regime=regime,
                horizon_months=horizon_months,
                equity_drift=0.05,
                equity_vol=0.18,
                iv_mean_reversion_speed=0.75,
                iv_vol_of_vol=0.65,
                iv_mean_level=0.20,
                corr_return_iv=-0.60,
                jump_probability=0.05,
                jump_size_mean=-0.12,
                jump_iv_spike=7.5,
            )


@dataclass
class ScenarioResult:
    """Single scenario result with attribution."""
    
    scenario_id: int
    
    # Market moves
    equity_return_pct: Dict[str, float]  # ticker -> %
    iv_change_pts: Dict[str, float]  # ticker -> pts
    had_jump: bool
    
    # P&L
    total_pnl_usd: float
    total_pnl_pct: float  # % of NAV
    position_pnls: Dict[str, float]  # ticker -> $
    
    # Attribution
    top_contributor: str
    top_detractor: str


class MonteCarloV01:
    """
    v0.1 Monte Carlo with position-level representation.
    
    Improvements over v0.0:
    - Position-level P&L (Taylor approximation)
    - Separate S and IV dynamics
    - Regime-conditional assumptions
    - Jump risk modeling
    - Scenario attribution
    """
    
    def __init__(self, portfolio: Portfolio, assumptions: ScenarioAssumptions):
        self.portfolio = portfolio
        self.assumptions = assumptions
    
    def generate_scenarios(self, n_scenarios: int = 10000) -> List[ScenarioResult]:
        """
        Generate N scenarios with correlated S and IV dynamics.
        
        Returns list of ScenarioResult objects.
        """
        results = []
        
        # Time scaling
        t = self.assumptions.horizon_months / 12.0
        days = int(self.assumptions.horizon_months * 30)
        
        # Get unique underlyings from portfolio
        underlyings = set()
        for pos in self.portfolio.positions:
            ticker = pos.ticker.split('/')[0] if '/' in pos.ticker else pos.ticker
            underlyings.add(ticker)
        
        for i in range(n_scenarios):
            # Generate correlated (return, IV change) for each underlying
            equity_returns = {}
            iv_changes = {}
            had_jump = False
            
            for underlying in underlyings:
                # Check for jump event
                if np.random.random() < self.assumptions.jump_probability:
                    # Jump scenario
                    ret = self.assumptions.jump_size_mean + np.random.normal(0, 0.05)
                    iv_chg = self.assumptions.jump_iv_spike + np.random.normal(0, 2.0)
                    
                    # CRITICAL FIX: Bound jump IV spike too
                    current_iv = 0.20
                    min_iv_pts = 5.0 - (current_iv * 100)
                    max_iv_pts = 150.0 - (current_iv * 100)
                    iv_chg = np.clip(iv_chg, min_iv_pts, max_iv_pts)
                    
                    had_jump = True
                else:
                    # Normal scenario: correlated (return, IV)
                    # Generate correlated normals
                    rho = self.assumptions.corr_return_iv
                    z1 = np.random.normal(0, 1)
                    z2 = rho * z1 + np.sqrt(1 - rho**2) * np.random.normal(0, 1)
                    
                    # Scale by volatilities
                    ret = (
                        self.assumptions.equity_drift * t +
                        self.assumptions.equity_vol * np.sqrt(t) * z1
                    )
                    
                    # IV change (mean-reverting + vol-of-vol)
                    current_iv = 0.20  # Simplified: use entry IV or track current
                    iv_mr = self.assumptions.iv_mean_reversion_speed * (
                        self.assumptions.iv_mean_level - current_iv
                    ) * t
                    iv_vol = self.assumptions.iv_vol_of_vol * np.sqrt(t) * z2
                    iv_chg = (iv_mr + iv_vol) * 100  # Convert to pts
                    
                    # CRITICAL FIX: Bound IV changes to prevent negative IV
                    # Min IV = 5%, Max IV = 150%
                    min_iv_pts = 5.0 - (current_iv * 100)  # Can't go below 5%
                    max_iv_pts = 150.0 - (current_iv * 100)  # Cap at 150%
                    iv_chg = np.clip(iv_chg, min_iv_pts, max_iv_pts)
                
                # #region agent log
                import json
                if i < 3:  # Log first 3 scenarios
                    with open('/Users/jeffreylarson/sites/ai-options-trader-starter/.cursor/debug.log', 'a') as f:
                        f.write(json.dumps({"location":"monte_carlo_v01.py:181","message":"IV change generated","data":{"scenario_id":i,"underlying":underlying,"ret":ret,"iv_chg":iv_chg,"had_jump":had_jump},"timestamp":__import__('time').time()*1000,"sessionId":"debug-session","hypothesisId":"D"}) + '\n')
                # #endregion
                
                equity_returns[underlying] = ret
                iv_changes[underlying] = iv_chg
            
            # Calculate P&L using portfolio's estimate_pnl method
            total_pnl, position_pnls = self.portfolio.estimate_pnl(
                underlying_changes=equity_returns,
                iv_changes=iv_changes,
                days_elapsed=days,
            )
            
            # #region agent log
            import json
            if i < 3:  # Log first 3 scenarios
                with open('/Users/jeffreylarson/sites/ai-options-trader-starter/.cursor/debug.log', 'a') as f:
                    f.write(json.dumps({"location":"monte_carlo_v01.py:195","message":"P&L calculated","data":{"scenario_id":i,"total_pnl":total_pnl,"total_pnl_pct":(total_pnl/self.portfolio.nav)*100,"position_pnls":position_pnls},"timestamp":__import__('time').time()*1000,"sessionId":"debug-session","hypothesisId":"E"}) + '\n')
            # #endregion
            
            # Find top contributor and detractor
            sorted_pnls = sorted(position_pnls.items(), key=lambda x: x[1], reverse=True)
            top_contrib = sorted_pnls[0][0] if sorted_pnls else "None"
            top_detract = sorted_pnls[-1][0] if sorted_pnls else "None"
            
            results.append(ScenarioResult(
                scenario_id=i,
                equity_return_pct=equity_returns,
                iv_change_pts=iv_changes,
                had_jump=had_jump,
                total_pnl_usd=total_pnl,
                total_pnl_pct=total_pnl / self.portfolio.nav if self.portfolio.nav > 0 else 0,
                position_pnls=position_pnls,
                top_contributor=top_contrib,
                top_detractor=top_detract,
            ))
        
        return results
    
    def analyze_results(self, results: List[ScenarioResult]) -> Dict:
        """Analyze scenario results and compute risk metrics."""
        
        pnls_pct = np.array([r.total_pnl_pct for r in results])
        pnls_usd = np.array([r.total_pnl_usd for r in results])
        
        # Basic stats
        analysis = {
            "n_scenarios": len(results),
            "mean_pnl_pct": float(np.mean(pnls_pct)),
            "median_pnl_pct": float(np.median(pnls_pct)),
            "std_pnl_pct": float(np.std(pnls_pct)),
            "skewness": float(self._skewness(pnls_pct)),
            "var_95_pct": float(np.percentile(pnls_pct, 5)),
            "var_99_pct": float(np.percentile(pnls_pct, 1)),
            "cvar_95_pct": float(np.mean(pnls_pct[pnls_pct <= np.percentile(pnls_pct, 5)])),
            "max_gain_pct": float(np.max(pnls_pct)),
            "max_loss_pct": float(np.min(pnls_pct)),
            "prob_positive": float(np.sum(pnls_pct > 0) / len(pnls_pct)),
            "prob_loss_gt_10pct": float(np.sum(pnls_pct < -0.10) / len(pnls_pct)),
            "prob_loss_gt_20pct": float(np.sum(pnls_pct < -0.20) / len(pnls_pct)),
        }
        
        # Top 3 winners and losers
        sorted_results = sorted(results, key=lambda r: r.total_pnl_pct)
        analysis["top_3_losers"] = [
            {
                "pnl_pct": r.total_pnl_pct,
                "equity_moves": r.equity_return_pct,
                "iv_moves": r.iv_change_pts,
                "had_jump": r.had_jump,
                "top_detractor": r.top_detractor,
            }
            for r in sorted_results[:3]
        ]
        analysis["top_3_winners"] = [
            {
                "pnl_pct": r.total_pnl_pct,
                "equity_moves": r.equity_return_pct,
                "iv_moves": r.iv_change_pts,
                "had_jump": r.had_jump,
                "top_contributor": r.top_contributor,
            }
            for r in sorted_results[-3:][::-1]
        ]
        
        # CVaR attribution (worst 5% scenarios)
        worst_5pct_idx = pnls_pct <= np.percentile(pnls_pct, 5)
        worst_results = [r for i, r in enumerate(results) if worst_5pct_idx[i]]
        
        # Aggregate position contributions in worst scenarios
        position_contrib = {}
        for r in worst_results:
            for ticker, pnl in r.position_pnls.items():
                position_contrib[ticker] = position_contrib.get(ticker, 0) + pnl
        
        total_worst_pnl = sum(position_contrib.values())
        analysis["cvar_attribution"] = {
            ticker: (pnl / total_worst_pnl * 100 if total_worst_pnl != 0 else 0)
            for ticker, pnl in sorted(position_contrib.items(), key=lambda x: x[1])
        }
        
        return analysis
    
    @staticmethod
    def _skewness(data: np.ndarray) -> float:
        """Calculate skewness."""
        mean = np.mean(data)
        std = np.std(data)
        if std == 0:
            return 0.0
        return np.mean(((data - mean) / std) ** 3)


# =============================================================================
# Unified Regime Integration
# =============================================================================

def assumptions_from_unified_regime(
    unified_state,  # UnifiedRegimeState
    horizon_months: int = 6,
    base_regime: str = "ALL",
) -> ScenarioAssumptions:
    """
    Create ScenarioAssumptions from UnifiedRegimeState.
    
    This integrates all regime signals into a single set of Monte Carlo
    assumptions, providing more nuanced scenario generation.
    
    Args:
        unified_state: UnifiedRegimeState from regimes.build_unified_regime_state()
        horizon_months: Simulation horizon
        base_regime: Fallback regime if unified state is incomplete
    
    Returns:
        ScenarioAssumptions with regime-adjusted parameters
    """
    # Start with base regime assumptions
    base = ScenarioAssumptions.for_regime(base_regime, horizon_months)
    
    # Get Monte Carlo adjustments from unified state
    mc_params = unified_state.to_monte_carlo_params()
    
    # Apply adjustments to base assumptions
    return ScenarioAssumptions(
        regime=f"unified_{unified_state.overall_category}",
        horizon_months=horizon_months,
        
        # Equity dynamics with adjustments
        equity_drift=base.equity_drift + mc_params["equity_drift_adj"],
        equity_vol=base.equity_vol * mc_params["equity_vol_adj"],
        
        # IV dynamics with adjustments
        iv_mean_reversion_speed=base.iv_mean_reversion_speed,
        iv_vol_of_vol=base.iv_vol_of_vol * mc_params["iv_vol_adj"],
        iv_mean_level=base.iv_mean_level + mc_params["iv_drift_adj"],
        
        # Correlation (keep base, could enhance later)
        corr_return_iv=base.corr_return_iv,
        
        # Jump risk with adjustments
        jump_probability=base.jump_probability * mc_params["jump_prob_adj"],
        jump_size_mean=base.jump_size_mean * mc_params["jump_size_adj"],
        jump_iv_spike=base.jump_iv_spike * mc_params["jump_size_adj"],
    )


def run_regime_weighted_monte_carlo(
    portfolio: "Portfolio",
    unified_state,  # UnifiedRegimeState
    horizon_months: int = 6,
    n_scenarios: int = 10000,
) -> Dict:
    """
    Run Monte Carlo with regime-weighted scenario probabilities.
    
    This generates scenarios under different regime assumptions and weights
    them by transition probabilities, providing a more realistic distribution.
    
    Args:
        portfolio: Portfolio to simulate
        unified_state: Current regime state
        horizon_months: Simulation horizon
        n_scenarios: Total scenarios to generate
    
    Returns:
        Dict with weighted analysis results
    """
    from ai_options_trader.regimes import get_regime_scenario_weights
    
    # Get transition probabilities for regime categories
    current_category = unified_state.overall_category
    weights = get_regime_scenario_weights(
        current_regime=current_category,
        target_regimes=["risk_on", "cautious", "risk_off"],
        domain="risk_category",
        horizon_days=horizon_months * 21,
    )
    
    # Map categories to regimes for simulation
    regime_mapping = {
        "risk_on": "GOLDILOCKS",
        "cautious": "ALL",
        "risk_off": "RISK_OFF",
    }
    
    all_results = []
    regime_results = {}
    
    for category, weight in weights.items():
        if weight < 0.01:  # Skip negligible weights
            continue
        
        # Number of scenarios for this regime (proportional to weight)
        n_regime = max(100, int(n_scenarios * weight))
        
        # Create assumptions for this regime
        regime = regime_mapping.get(category, "ALL")
        assumptions = ScenarioAssumptions.for_regime(regime, horizon_months)
        
        # Apply unified state adjustments
        mc_params = unified_state.to_monte_carlo_params()
        assumptions = ScenarioAssumptions(
            regime=f"weighted_{category}",
            horizon_months=horizon_months,
            equity_drift=assumptions.equity_drift + mc_params["equity_drift_adj"],
            equity_vol=assumptions.equity_vol * mc_params["equity_vol_adj"],
            iv_mean_reversion_speed=assumptions.iv_mean_reversion_speed,
            iv_vol_of_vol=assumptions.iv_vol_of_vol * mc_params["iv_vol_adj"],
            iv_mean_level=assumptions.iv_mean_level + mc_params["iv_drift_adj"],
            corr_return_iv=assumptions.corr_return_iv,
            jump_probability=assumptions.jump_probability * mc_params["jump_prob_adj"],
            jump_size_mean=assumptions.jump_size_mean,
            jump_iv_spike=assumptions.jump_iv_spike,
        )
        
        # Run simulation
        mc = MonteCarloV01(portfolio, assumptions)
        results = mc.generate_scenarios(n_regime)
        
        # Tag results with regime
        for r in results:
            r.regime_category = category  # type: ignore
            r.regime_weight = weight  # type: ignore
        
        all_results.extend(results)
        regime_results[category] = {
            "weight": weight,
            "n_scenarios": n_regime,
            "analysis": mc.analyze_results(results),
        }
    
    # Combined analysis
    if not all_results:
        return {"error": "No scenarios generated"}
    
    pnls_pct = np.array([r.total_pnl_pct for r in all_results])
    
    combined = {
        "weighted": True,
        "total_scenarios": len(all_results),
        "regime_weights": weights,
        "mean_return_pct": float(np.mean(pnls_pct)),
        "median_return_pct": float(np.median(pnls_pct)),
        "std_return_pct": float(np.std(pnls_pct)),
        "var_95_pct": float(np.percentile(pnls_pct, 5)),
        "cvar_95_pct": float(np.mean(pnls_pct[pnls_pct <= np.percentile(pnls_pct, 5)])),
        "win_rate": float(np.mean(pnls_pct > 0)),
        "regime_breakdown": regime_results,
    }
    
    return combined
