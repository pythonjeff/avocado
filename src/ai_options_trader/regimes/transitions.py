"""
Regime transition probability estimation.

Learns transition probabilities from historical data for Monte Carlo simulation.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from ai_options_trader.regimes.features import UnifiedRegimeState

import numpy as np
import pandas as pd

from ai_options_trader.config import load_settings
from ai_options_trader.regimes.base import REGIME_RISK_CATEGORIES, categorize_regime

logger = logging.getLogger(__name__)


@dataclass
class TransitionMatrix:
    """
    Regime transition probability matrix.
    
    Stores probabilities of transitioning from one regime state to another
    over a given time horizon.
    """
    domain: str
    horizon_days: int
    states: List[str]
    matrix: np.ndarray  # N x N matrix where matrix[i,j] = P(state_j | state_i)
    sample_count: int = 0
    last_updated: str = ""
    
    def get_prob(self, from_state: str, to_state: str) -> float:
        """Get transition probability from one state to another."""
        try:
            from_idx = self.states.index(from_state)
            to_idx = self.states.index(to_state)
            return float(self.matrix[from_idx, to_idx])
        except (ValueError, IndexError):
            # Unknown state - return uniform
            return 1.0 / len(self.states)
    
    def get_next_state_probs(self, current_state: str) -> Dict[str, float]:
        """Get probability distribution over next states."""
        try:
            from_idx = self.states.index(current_state)
            probs = self.matrix[from_idx, :]
            return {state: float(probs[i]) for i, state in enumerate(self.states)}
        except (ValueError, IndexError):
            # Unknown state - return uniform
            return {state: 1.0 / len(self.states) for state in self.states}
    
    def sample_next_state(self, current_state: str, rng: Optional[np.random.Generator] = None) -> str:
        """Sample next state based on transition probabilities."""
        if rng is None:
            rng = np.random.default_rng()
        
        probs = self.get_next_state_probs(current_state)
        states = list(probs.keys())
        probabilities = list(probs.values())
        
        return rng.choice(states, p=probabilities)
    
    def to_dict(self) -> dict:
        """Convert to serializable dictionary."""
        return {
            "domain": self.domain,
            "horizon_days": self.horizon_days,
            "states": self.states,
            "matrix": self.matrix.tolist(),
            "sample_count": self.sample_count,
            "last_updated": self.last_updated,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "TransitionMatrix":
        """Create from dictionary."""
        return cls(
            domain=data["domain"],
            horizon_days=data["horizon_days"],
            states=data["states"],
            matrix=np.array(data["matrix"]),
            sample_count=data.get("sample_count", 0),
            last_updated=data.get("last_updated", ""),
        )


# =============================================================================
# Default Transition Matrices (prior to learning)
# =============================================================================

def get_default_risk_transition_matrix(horizon_days: int = 21) -> TransitionMatrix:
    """
    Get default transition matrix for risk categories.
    
    Based on empirical estimates:
    - Risk regimes are sticky (60-85% persistence)
    - Risk-off is stickier than risk-on (crisis persistence)
    - Transitions usually go through 'cautious'
    """
    states = ["risk_on", "cautious", "risk_off"]
    
    # Monthly (21 trading days) transition probabilities
    if horizon_days <= 21:
        matrix = np.array([
            [0.80, 0.15, 0.05],  # risk_on -> ...
            [0.25, 0.55, 0.20],  # cautious -> ...
            [0.10, 0.25, 0.65],  # risk_off -> ...
        ])
    elif horizon_days <= 63:  # Quarterly
        matrix = np.array([
            [0.65, 0.25, 0.10],
            [0.30, 0.45, 0.25],
            [0.20, 0.35, 0.45],
        ])
    else:  # 6 months+
        matrix = np.array([
            [0.50, 0.35, 0.15],
            [0.35, 0.40, 0.25],
            [0.30, 0.40, 0.30],
        ])
    
    return TransitionMatrix(
        domain="risk_category",
        horizon_days=horizon_days,
        states=states,
        matrix=matrix,
        sample_count=0,
        last_updated="default",
    )


def get_default_vol_transition_matrix(horizon_days: int = 21) -> TransitionMatrix:
    """Default volatility regime transition matrix."""
    states = ["normal_vol", "elevated_vol", "vol_shock"]
    
    if horizon_days <= 21:
        matrix = np.array([
            [0.85, 0.12, 0.03],  # normal -> ...
            [0.30, 0.55, 0.15],  # elevated -> ...
            [0.15, 0.35, 0.50],  # shock -> ...
        ])
    else:
        # Longer horizons mean-revert more
        matrix = np.array([
            [0.70, 0.22, 0.08],
            [0.40, 0.45, 0.15],
            [0.30, 0.40, 0.30],
        ])
    
    return TransitionMatrix(
        domain="volatility",
        horizon_days=horizon_days,
        states=states,
        matrix=matrix,
        sample_count=0,
        last_updated="default",
    )


# =============================================================================
# Transition Learning from Historical Data
# =============================================================================

def learn_transitions_from_history(
    regime_history: pd.DataFrame,
    horizon_days: int = 21,
    smoothing: float = 1.0,  # Laplace smoothing
) -> TransitionMatrix:
    """
    Learn transition probabilities from historical regime data.
    
    Args:
        regime_history: DataFrame with columns ['date', 'regime']
        horizon_days: Forecast horizon for transitions
        smoothing: Laplace smoothing parameter (1.0 = add-one smoothing)
    
    Returns:
        TransitionMatrix learned from data
    """
    if len(regime_history) < horizon_days * 2:
        raise ValueError(f"Need at least {horizon_days * 2} observations, got {len(regime_history)}")
    
    # Get unique states
    states = sorted(regime_history['regime'].unique().tolist())
    n_states = len(states)
    
    # Initialize count matrix with smoothing
    counts = np.full((n_states, n_states), smoothing)
    
    # Count transitions
    df = regime_history.sort_values('date').reset_index(drop=True)
    
    for i in range(len(df) - horizon_days):
        from_regime = df.loc[i, 'regime']
        to_regime = df.loc[i + horizon_days, 'regime']
        
        from_idx = states.index(from_regime)
        to_idx = states.index(to_regime)
        counts[from_idx, to_idx] += 1
    
    # Normalize to probabilities
    row_sums = counts.sum(axis=1, keepdims=True)
    matrix = counts / row_sums
    
    return TransitionMatrix(
        domain="learned",
        horizon_days=horizon_days,
        states=states,
        matrix=matrix,
        sample_count=len(df) - horizon_days,
        last_updated=datetime.now().isoformat(),
    )


# =============================================================================
# Transition Matrix Storage
# =============================================================================

def get_cache_path() -> Path:
    """Get path to transition matrix cache."""
    return Path("data/cache/transitions")


def save_transition_matrix(matrix: TransitionMatrix, name: str) -> None:
    """Save transition matrix to cache."""
    cache_path = get_cache_path()
    cache_path.mkdir(parents=True, exist_ok=True)
    
    filepath = cache_path / f"{name}_{matrix.horizon_days}d.json"
    with open(filepath, 'w') as f:
        json.dump(matrix.to_dict(), f, indent=2)
    
    logger.info(f"Saved transition matrix to {filepath}")


def load_transition_matrix(name: str, horizon_days: int) -> Optional[TransitionMatrix]:
    """Load transition matrix from cache."""
    cache_path = get_cache_path()
    filepath = cache_path / f"{name}_{horizon_days}d.json"
    
    if not filepath.exists():
        return None
    
    try:
        with open(filepath, 'r') as f:
            data = json.load(f)
        return TransitionMatrix.from_dict(data)
    except Exception as e:
        logger.warning(f"Failed to load transition matrix: {e}")
        return None


def get_transition_matrix(
    domain: str,
    horizon_days: int = 21,
    use_learned: bool = True,
) -> TransitionMatrix:
    """
    Get transition matrix for a domain, using learned if available.
    
    Args:
        domain: Regime domain (e.g., 'risk_category', 'volatility')
        horizon_days: Forecast horizon in trading days
        use_learned: Whether to use learned matrix if available
    
    Returns:
        TransitionMatrix (learned or default)
    """
    if use_learned:
        loaded = load_transition_matrix(domain, horizon_days)
        if loaded is not None:
            return loaded
    
    # Fall back to defaults
    if domain == "risk_category":
        return get_default_risk_transition_matrix(horizon_days)
    elif domain == "volatility":
        return get_default_vol_transition_matrix(horizon_days)
    else:
        # Generic default - moderate persistence
        return get_default_risk_transition_matrix(horizon_days)


# =============================================================================
# Leading Indicator Adjustments (Option 3 - Edge Enhancement)
# =============================================================================

# Well-documented leading indicators and their effects on regime transitions
# Based on academic research and empirical observations

LEADING_INDICATORS = {
    "yield_curve_inverted": {
        "description": "2s10s curve inverted (< 0) - recession signal",
        "risk_off_multiplier": 1.8,  # 80% more likely to go risk-off
        "risk_on_multiplier": 0.6,   # 40% less likely to go risk-on
        "source": "Estrella & Mishkin (1996), Fed research",
    },
    "vix_elevated": {
        "description": "VIX > 25 - fear elevated",
        "risk_off_multiplier": 1.5,
        "risk_on_multiplier": 0.7,
        "source": "VIX as fear gauge - CBOE research",
    },
    "vix_term_inverted": {
        "description": "VIX > VIX3M - near-term stress",
        "risk_off_multiplier": 2.0,  # Strong signal
        "risk_on_multiplier": 0.5,
        "source": "Term structure inversion predicts volatility spikes",
    },
    "credit_spreads_widening": {
        "description": "HY OAS expanding rapidly (z-score > 1)",
        "risk_off_multiplier": 1.6,
        "risk_on_multiplier": 0.7,
        "source": "Credit leads equity - Gilchrist & Zakrajsek",
    },
    "funding_stress": {
        "description": "SOFR-EFFR spread elevated or repo stress",
        "risk_off_multiplier": 1.7,
        "risk_on_multiplier": 0.6,
        "source": "2019 repo crisis, March 2020 funding stress",
    },
    "vix_complacent": {
        "description": "VIX < 13 - complacency (contrarian signal)",
        "risk_off_multiplier": 1.3,  # Slightly elevated risk of correction
        "risk_on_multiplier": 0.9,
        "source": "Low vol regimes tend to end abruptly",
    },
    "rates_shock_up": {
        "description": "10Y yield spiking (z-score > 1.5)",
        "risk_off_multiplier": 1.4,
        "risk_on_multiplier": 0.8,
        "source": "Rate shocks precede equity weakness",
    },
}


@dataclass
class LeadingIndicatorSignals:
    """Current state of leading indicators for transition adjustment."""
    
    yield_curve_inverted: bool = False
    vix_elevated: bool = False
    vix_term_inverted: bool = False
    credit_spreads_widening: bool = False
    funding_stress: bool = False
    vix_complacent: bool = False
    rates_shock_up: bool = False
    
    # Raw values for transparency
    curve_2s10s: Optional[float] = None
    vix_level: Optional[float] = None
    vix_term_spread: Optional[float] = None  # VIX - VIX3M
    hy_oas_zscore: Optional[float] = None
    funding_spread_bps: Optional[float] = None
    rates_zscore: Optional[float] = None
    
    def active_signals(self) -> List[str]:
        """Return list of currently active warning signals."""
        active = []
        if self.yield_curve_inverted:
            active.append("yield_curve_inverted")
        if self.vix_elevated:
            active.append("vix_elevated")
        if self.vix_term_inverted:
            active.append("vix_term_inverted")
        if self.credit_spreads_widening:
            active.append("credit_spreads_widening")
        if self.funding_stress:
            active.append("funding_stress")
        if self.vix_complacent:
            active.append("vix_complacent")
        if self.rates_shock_up:
            active.append("rates_shock_up")
        return active
    
    def risk_adjustment_factor(self) -> Tuple[float, float]:
        """
        Calculate combined adjustment factors for risk-off and risk-on.
        
        Returns:
            (risk_off_multiplier, risk_on_multiplier)
        """
        risk_off_mult = 1.0
        risk_on_mult = 1.0
        
        for signal_name in self.active_signals():
            indicator = LEADING_INDICATORS.get(signal_name, {})
            risk_off_mult *= indicator.get("risk_off_multiplier", 1.0)
            risk_on_mult *= indicator.get("risk_on_multiplier", 1.0)
        
        # Cap multipliers to avoid extreme values
        risk_off_mult = min(risk_off_mult, 3.0)
        risk_on_mult = max(risk_on_mult, 0.3)
        
        return risk_off_mult, risk_on_mult


def extract_leading_indicators(unified_state) -> LeadingIndicatorSignals:
    """
    Extract leading indicator signals from UnifiedRegimeState.
    
    Args:
        unified_state: UnifiedRegimeState from build_unified_regime_state()
    
    Returns:
        LeadingIndicatorSignals with current signal states
    """
    signals = LeadingIndicatorSignals()
    
    # Rates regime - yield curve
    if unified_state.rates:
        if "inverted" in unified_state.rates.name.lower():
            signals.yield_curve_inverted = True
        if "shock_up" in unified_state.rates.name.lower():
            signals.rates_shock_up = True
        # Try to get raw curve value from metrics
        if hasattr(unified_state.rates, 'metrics'):
            signals.curve_2s10s = unified_state.rates.metrics.get('curve_2s10s')
            signals.rates_zscore = unified_state.rates.metrics.get('z_10y_chg')
    
    # Volatility regime - VIX signals
    if unified_state.volatility:
        vol_name = unified_state.volatility.name.lower()
        vol_score = unified_state.volatility.score
        
        if "shock" in vol_name or vol_score > 70:
            signals.vix_elevated = True
        elif "complacent" in vol_name or vol_score < 30:
            signals.vix_complacent = True
        
        # Check for term structure inversion in tags
        if hasattr(unified_state.volatility, 'tags'):
            if "term_inverted" in unified_state.volatility.tags:
                signals.vix_term_inverted = True
        
        # Raw VIX from metrics
        if hasattr(unified_state.volatility, 'metrics'):
            signals.vix_level = unified_state.volatility.metrics.get('vix')
            signals.vix_term_spread = unified_state.volatility.metrics.get('vix_term_spread')
    
    # Funding regime - stress signals
    if unified_state.funding:
        funding_name = unified_state.funding.name.lower()
        if "stress" in funding_name or unified_state.funding.score > 70:
            signals.funding_stress = True
        
        if hasattr(unified_state.funding, 'metrics'):
            signals.funding_spread_bps = unified_state.funding.metrics.get('sofr_effr_spread_bps')
    
    # Macro regime - credit spreads (often embedded in macro state)
    if unified_state.macro:
        if hasattr(unified_state.macro, 'metrics'):
            hy_z = unified_state.macro.metrics.get('z_hy_oas')
            if hy_z and hy_z > 1.0:
                signals.credit_spreads_widening = True
                signals.hy_oas_zscore = hy_z
    
    return signals


def adjust_transition_matrix(
    base_matrix: TransitionMatrix,
    signals: LeadingIndicatorSignals,
) -> TransitionMatrix:
    """
    Adjust transition probabilities based on leading indicator signals.
    
    This is where the edge comes from - we're using forward-looking
    signals to shift probabilities away from historical averages.
    
    Args:
        base_matrix: Historical frequency-based transition matrix
        signals: Current leading indicator states
    
    Returns:
        Adjusted TransitionMatrix with signal-informed probabilities
    """
    risk_off_mult, risk_on_mult = signals.risk_adjustment_factor()
    
    # If no signals active, return base matrix
    if risk_off_mult == 1.0 and risk_on_mult == 1.0:
        return base_matrix
    
    # Copy and adjust the matrix
    adjusted = base_matrix.matrix.copy()
    states = base_matrix.states
    
    # Find indices for risk categories
    try:
        risk_on_idx = states.index("risk_on")
        risk_off_idx = states.index("risk_off")
    except ValueError:
        # If states don't match expected, return base
        logger.warning("Cannot adjust matrix - unexpected state names")
        return base_matrix
    
    # Adjust each row (from-state)
    for i in range(len(states)):
        # Scale risk_off transition up
        adjusted[i, risk_off_idx] *= risk_off_mult
        
        # Scale risk_on transition down
        adjusted[i, risk_on_idx] *= risk_on_mult
        
        # Re-normalize row to sum to 1.0
        row_sum = adjusted[i, :].sum()
        if row_sum > 0:
            adjusted[i, :] /= row_sum
    
    return TransitionMatrix(
        domain=f"{base_matrix.domain}_adjusted",
        horizon_days=base_matrix.horizon_days,
        states=states,
        matrix=adjusted,
        sample_count=base_matrix.sample_count,
        last_updated=datetime.now().isoformat(),
    )


def get_adjusted_transition_matrix(
    domain: str,
    horizon_days: int,
    unified_state=None,  # UnifiedRegimeState
) -> Tuple[TransitionMatrix, LeadingIndicatorSignals]:
    """
    Get transition matrix adjusted for current leading indicators.
    
    This is the main entry point for edge-enhanced transitions.
    
    Args:
        domain: Regime domain
        horizon_days: Forecast horizon
        unified_state: Current regime state (if None, returns base matrix)
    
    Returns:
        (adjusted_matrix, signals) - The adjusted matrix and active signals
    """
    base = get_transition_matrix(domain, horizon_days, use_learned=True)
    
    if unified_state is None:
        return base, LeadingIndicatorSignals()
    
    signals = extract_leading_indicators(unified_state)
    adjusted = adjust_transition_matrix(base, signals)
    
    return adjusted, signals


# =============================================================================
# Monte Carlo Integration
# =============================================================================

def simulate_regime_path(
    initial_regime: str,
    domain: str,
    n_steps: int,
    step_days: int = 21,
    rng: Optional[np.random.Generator] = None,
) -> List[str]:
    """
    Simulate regime path for Monte Carlo.
    
    Args:
        initial_regime: Starting regime
        domain: Regime domain
        n_steps: Number of steps to simulate
        step_days: Days per step
        rng: Random number generator
    
    Returns:
        List of regime states over time
    """
    if rng is None:
        rng = np.random.default_rng()
    
    matrix = get_transition_matrix(domain, horizon_days=step_days)
    
    path = [initial_regime]
    current = initial_regime
    
    for _ in range(n_steps - 1):
        current = matrix.sample_next_state(current, rng)
        path.append(current)
    
    return path


def get_regime_scenario_weights(
    current_regime: str,
    target_regimes: List[str],
    domain: str,
    horizon_days: int = 126,  # 6 months
) -> Dict[str, float]:
    """
    Get probability weights for different regime scenarios.
    
    Useful for weighting Monte Carlo scenarios by regime likelihood.
    
    Args:
        current_regime: Current regime state
        target_regimes: List of possible target regimes
        domain: Regime domain
        horizon_days: Forecast horizon
    
    Returns:
        Dict mapping regime -> probability weight
    """
    matrix = get_transition_matrix(domain, horizon_days=horizon_days)
    probs = matrix.get_next_state_probs(current_regime)
    
    # Normalize to target regimes
    total = sum(probs.get(r, 0.0) for r in target_regimes)
    if total == 0:
        return {r: 1.0 / len(target_regimes) for r in target_regimes}
    
    return {r: probs.get(r, 0.0) / total for r in target_regimes}
