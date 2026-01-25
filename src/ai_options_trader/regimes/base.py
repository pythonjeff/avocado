"""
Unified regime base classes for consistent interface across all regime types.

All regime classifiers should return a dataclass that inherits from or matches
the RegimeResult protocol for ML-friendly feature extraction.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol, runtime_checkable


@runtime_checkable
class RegimeProtocol(Protocol):
    """Protocol that all regime classes should implement."""
    
    @property
    def name(self) -> str:
        """Programmatic identifier (e.g., 'stagflation', 'vol_shock')."""
        ...
    
    @property
    def label(self) -> str:
        """Human-readable label (e.g., 'Stagflation', 'Volatility Shock')."""
        ...
    
    @property
    def description(self) -> str:
        """Brief description of the regime and its implications."""
        ...
    
    @property
    def score(self) -> float:
        """Numeric score (0-100) indicating regime intensity/confidence."""
        ...


@dataclass(frozen=True)
class RegimeResult:
    """
    Standardized regime classification result.
    
    All regime classifiers should return this or a compatible dataclass.
    This enables uniform ML feature extraction and Monte Carlo integration.
    
    Attributes:
        name: Programmatic identifier (lowercase, underscores)
        label: Human-readable label for display
        description: Brief description of regime implications
        score: 0-100 intensity/confidence score
        domain: Regime domain (e.g., 'macro', 'volatility', 'funding')
        tags: Optional list of characteristics (e.g., ['risk_off', 'vol_elevated'])
        metrics: Optional dict of key metrics used in classification
    """
    name: str
    label: str
    description: str
    score: float
    domain: str
    tags: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    
    def to_feature_dict(self) -> dict:
        """Convert to ML-friendly feature dictionary."""
        return {
            f"{self.domain}_regime": self.name,
            f"{self.domain}_score": self.score,
            f"{self.domain}_is_stressed": 1.0 if "stressed" in self.tags or "shock" in self.tags else 0.0,
            f"{self.domain}_is_risk_off": 1.0 if "risk_off" in self.tags else 0.0,
        }
    
    def to_display_dict(self) -> dict:
        """Convert to display-friendly dictionary."""
        return {
            "regime": self.label,
            "description": self.description,
            "score": self.score,
            "domain": self.domain,
        }


# =============================================================================
# Regime Domain Constants
# =============================================================================

REGIME_DOMAINS = [
    "macro",
    "volatility", 
    "rates",
    "funding",
    "fiscal",
    "commodities",
    "housing",
    "monetary",
    "usd",
    "crypto",
]

# Standard regime categories for cross-domain comparison
REGIME_RISK_CATEGORIES = {
    "risk_on": ["goldilocks", "normal_vol", "abundant_reserves", "benign_funding", "neutral"],
    "cautious": ["elevated", "moderate", "tightening", "heavy_funding", "inverted_curve"],
    "risk_off": ["stagflation", "vol_shock", "funding_stress", "fiscal_dominance", "rates_shock"],
}


def categorize_regime(regime_name: str) -> str:
    """Map any regime name to risk category (risk_on, cautious, risk_off)."""
    name_lower = regime_name.lower().replace(" ", "_").replace("-", "_")
    
    for category, regimes in REGIME_RISK_CATEGORIES.items():
        for r in regimes:
            if r in name_lower or name_lower in r:
                return category
    
    return "cautious"  # Default to cautious if unknown


# =============================================================================
# Regime Transition Probabilities (learned from history)
# =============================================================================

# Default transition probabilities (can be overridden by trained values)
# Format: {from_regime: {to_regime: probability}}
# These are conservative defaults - actual values should be learned from data

DEFAULT_TRANSITION_PROBS = {
    "risk_on": {
        "risk_on": 0.85,
        "cautious": 0.12,
        "risk_off": 0.03,
    },
    "cautious": {
        "risk_on": 0.25,
        "cautious": 0.55,
        "risk_off": 0.20,
    },
    "risk_off": {
        "risk_on": 0.10,
        "cautious": 0.30,
        "risk_off": 0.60,
    },
}


def get_transition_prob(from_category: str, to_category: str, horizon_months: int = 1) -> float:
    """
    Get probability of transitioning from one regime category to another.
    
    Args:
        from_category: Current regime category
        to_category: Target regime category
        horizon_months: Forecast horizon in months (scales probabilities)
    
    Returns:
        Transition probability (0-1)
    """
    base_prob = DEFAULT_TRANSITION_PROBS.get(from_category, {}).get(to_category, 0.33)
    
    # For longer horizons, mean-revert toward equal probabilities
    if horizon_months > 1:
        mean_prob = 0.33
        decay = 0.8 ** (horizon_months - 1)  # Exponential decay toward mean
        return base_prob * decay + mean_prob * (1 - decay)
    
    return base_prob
