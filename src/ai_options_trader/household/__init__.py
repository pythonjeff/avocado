"""
Household Wealth Regime Module

Tracks where government deficit dollars flow and what household behavior they drive,
based on the MMT sectoral balances identity: S = (G-T) + I + NX

Regimes:
- WEALTH_ACCUMULATION: Healthy prosperity, deficit → net worth gains
- DELEVERAGING: Precautionary mode, deficit → savings/debt paydown
- CREDIT_EXPANSION: Leverage-driven gains, fragile
- INFLATIONARY_EROSION: Nominal gains but real purchasing power declining
- CORPORATE_CAPTURE: Deficit not reaching households (oligopoly capture)
"""
from __future__ import annotations

from ai_options_trader.household.models import (
    HouseholdInputs,
    HouseholdState,
    SectoralBalances,
)
from ai_options_trader.household.regime import (
    HouseholdRegime,
    classify_household_regime,
    classify_household_regime_from_state,
)
from ai_options_trader.household.signals import (
    build_household_state,
    build_household_dataset,
    build_sectoral_balances,
    HOUSEHOLD_FRED_SERIES,
)
from ai_options_trader.household.features import (
    household_feature_vector,
    HOUSEHOLD_REGIME_NAMES,
)

__all__ = [
    # Models
    "HouseholdInputs",
    "HouseholdState",
    "SectoralBalances",
    # Regime
    "HouseholdRegime",
    "classify_household_regime",
    "classify_household_regime_from_state",
    # Signals
    "build_household_state",
    "build_household_dataset",
    "build_sectoral_balances",
    "HOUSEHOLD_FRED_SERIES",
    # Features
    "household_feature_vector",
    "HOUSEHOLD_REGIME_NAMES",
]
