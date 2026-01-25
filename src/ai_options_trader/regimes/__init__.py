"""
Unified regime classification module.

Provides consistent interface for all regime types and ML feature extraction.

Usage:
    # Get unified regime state
    from ai_options_trader.regimes import build_unified_regime_state
    state = build_unified_regime_state()
    
    # Extract ML features
    features = state.to_feature_dict()
    
    # Get Monte Carlo parameters
    mc_params = state.to_monte_carlo_params()
    
    # Simulate regime path
    from ai_options_trader.regimes import simulate_regime_path
    path = simulate_regime_path("risk_on", "risk_category", n_steps=6)
"""
from ai_options_trader.regimes.base import (
    RegimeProtocol,
    RegimeResult,
    REGIME_DOMAINS,
    REGIME_RISK_CATEGORIES,
    categorize_regime,
    get_transition_prob,
    DEFAULT_TRANSITION_PROBS,
)

from ai_options_trader.regimes.features import (
    UnifiedRegimeState,
    build_unified_regime_state,
    extract_ml_features,
)

from ai_options_trader.regimes.transitions import (
    TransitionMatrix,
    get_transition_matrix,
    simulate_regime_path,
    get_regime_scenario_weights,
    get_default_risk_transition_matrix,
    get_default_vol_transition_matrix,
    # Leading indicator adjustments
    LeadingIndicatorSignals,
    LEADING_INDICATORS,
    extract_leading_indicators,
    adjust_transition_matrix,
    get_adjusted_transition_matrix,
)

__all__ = [
    # Base
    "RegimeProtocol",
    "RegimeResult", 
    "REGIME_DOMAINS",
    "REGIME_RISK_CATEGORIES",
    "categorize_regime",
    "get_transition_prob",
    "DEFAULT_TRANSITION_PROBS",
    # Features
    "UnifiedRegimeState",
    "build_unified_regime_state",
    "extract_ml_features",
    # Transitions
    "TransitionMatrix",
    "get_transition_matrix",
    "simulate_regime_path",
    "get_regime_scenario_weights",
    "get_default_risk_transition_matrix",
    "get_default_vol_transition_matrix",
    # Leading Indicators (Edge Enhancement)
    "LeadingIndicatorSignals",
    "LEADING_INDICATORS",
    "extract_leading_indicators",
    "adjust_transition_matrix",
    "get_adjusted_transition_matrix",
]
