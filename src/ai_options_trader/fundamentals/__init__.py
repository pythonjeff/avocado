"""
Fundamentals Analysis Module

CFA-level financial analysis including:
- Revenue/margin sensitivity models
- DCF valuation
- Scenario analysis
- Earnings quality metrics
- CapEx analysis
"""

from .sensitivity import (
    SensitivityModel,
    build_sensitivity_model,
    run_scenario_analysis,
)
from .valuation import (
    DCFModel,
    calculate_implied_growth,
    reverse_dcf,
)

__all__ = [
    "SensitivityModel",
    "build_sensitivity_model",
    "run_scenario_analysis",
    "DCFModel",
    "calculate_implied_growth",
    "reverse_dcf",
]
