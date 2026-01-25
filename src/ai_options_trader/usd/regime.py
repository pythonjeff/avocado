"""
USD regime classification.

Classifies the dollar environment based on strength/weakness signals.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ai_options_trader.usd.models import UsdInputs, UsdState


@dataclass(frozen=True)
class UsdRegime:
    """
    USD regime classification result.
    
    Attributes:
        name: Programmatic identifier
        label: Human-readable label
        description: Brief description
        score: 0-100 intensity score (50 = neutral, >50 = strong, <50 = weak)
        tags: List of characteristics
    """
    name: str
    label: str
    description: str
    score: float = 50.0
    tags: list[str] = field(default_factory=list)


# =============================================================================
# Regime Definitions
# =============================================================================

USD_REGIMES = {
    "usd_surge": UsdRegime(
        name="usd_surge",
        label="Dollar Surge",
        description="Rapid dollar strengthening; EM stress, commodity headwinds, US equity relative outperformance",
        score=85,
        tags=["risk_off", "em_stress", "commodity_headwind"],
    ),
    "usd_strong": UsdRegime(
        name="usd_strong",
        label="Strong Dollar",
        description="Elevated dollar; gradual pressure on multinationals, EM assets, and commodities",
        score=70,
        tags=["cautious", "em_pressure"],
    ),
    "usd_neutral": UsdRegime(
        name="usd_neutral",
        label="Neutral Dollar",
        description="Dollar trading near fair value; limited directional pressure",
        score=50,
        tags=["neutral"],
    ),
    "usd_weak": UsdRegime(
        name="usd_weak",
        label="Weak Dollar",
        description="Dollar softening; tailwind for EM, commodities, and US multinationals",
        score=30,
        tags=["risk_on", "em_tailwind", "commodity_tailwind"],
    ),
    "usd_plunge": UsdRegime(
        name="usd_plunge",
        label="Dollar Plunge",
        description="Rapid dollar weakening; potential confidence crisis, inflation import risk",
        score=15,
        tags=["risk_off", "inflation_risk", "confidence_crisis"],
    ),
}

USD_REGIME_CHOICES = tuple(USD_REGIMES.keys())


# =============================================================================
# Classification Logic
# =============================================================================

def classify_usd_regime(
    inputs: UsdInputs,
    *,
    surge_threshold: float = 2.0,
    strong_threshold: float = 1.0,
    weak_threshold: float = -1.0,
    plunge_threshold: float = -2.0,
) -> UsdRegime:
    """
    Classify USD regime based on strength score and z-scores.
    
    Args:
        inputs: UsdInputs with strength score and z-scores
        surge_threshold: z-score threshold for surge (default 2.0)
        strong_threshold: z-score threshold for strong (default 1.0)
        weak_threshold: z-score threshold for weak (default -1.0)
        plunge_threshold: z-score threshold for plunge (default -2.0)
    
    Returns:
        UsdRegime classification
    """
    # Use strength score if available, otherwise fall back to z-scores
    score = inputs.usd_strength_score
    
    if score is None:
        # Fallback: use z_usd_level
        z_level = inputs.z_usd_level or 0.0
        score = z_level
    
    # Classify based on score thresholds
    if score >= surge_threshold:
        return USD_REGIMES["usd_surge"]
    elif score >= strong_threshold:
        return USD_REGIMES["usd_strong"]
    elif score <= plunge_threshold:
        return USD_REGIMES["usd_plunge"]
    elif score <= weak_threshold:
        return USD_REGIMES["usd_weak"]
    else:
        return USD_REGIMES["usd_neutral"]


def classify_usd_regime_from_state(state: UsdState) -> UsdRegime:
    """Classify USD regime from UsdState object."""
    return classify_usd_regime(state.inputs)


# =============================================================================
# Feature Extraction
# =============================================================================

def usd_regime_to_features(regime: UsdRegime) -> dict:
    """Convert USD regime to ML-friendly features."""
    return {
        "usd_regime": regime.name,
        "usd_score": regime.score,
        "usd_is_strong": 1.0 if regime.score > 60 else 0.0,
        "usd_is_weak": 1.0 if regime.score < 40 else 0.0,
        "usd_is_extreme": 1.0 if regime.score > 80 or regime.score < 20 else 0.0,
        "usd_em_pressure": 1.0 if "em_stress" in regime.tags or "em_pressure" in regime.tags else 0.0,
        "usd_commodity_headwind": 1.0 if "commodity_headwind" in regime.tags else 0.0,
    }
