"""
Tests for the household wealth regime module.

Tests the regime classification logic and feature extraction.
"""
from __future__ import annotations

import pytest

from ai_options_trader.household.models import (
    HouseholdInputs,
    HouseholdState,
    SectoralBalances,
)
from ai_options_trader.household.regime import (
    HouseholdRegime,
    classify_household_regime,
)
from ai_options_trader.household.features import (
    household_feature_vector,
    HOUSEHOLD_REGIME_NAMES,
)


class TestHouseholdRegimeClassification:
    """Test household regime classification logic."""
    
    def test_wealth_accumulation_regime(self):
        """High prosperity score should yield wealth_accumulation regime."""
        inputs = HouseholdInputs(
            wealth_score=1.0,
            debt_stress_score=0.0,
            behavioral_score=0.5,
            household_prosperity_score=0.8,
            savings_rate=7.0,
            z_savings_rate=0.0,
        )
        regime = classify_household_regime(inputs)
        assert regime.name == "wealth_accumulation"
        assert "household" in regime.tags
        assert "risk_on" in regime.tags
    
    def test_deleveraging_regime_high_savings(self):
        """High savings + low velocity should yield deleveraging regime."""
        inputs = HouseholdInputs(
            z_savings_rate=1.5,
            z_m2_velocity=-1.0,
            behavioral_score=-0.5,
            wealth_score=0.0,
            debt_stress_score=0.5,
            household_prosperity_score=0.0,
            savings_rate=12.0,
        )
        regime = classify_household_regime(inputs)
        assert regime.name == "deleveraging"
        assert "defensive" in regime.tags
    
    def test_deleveraging_regime_debt_stress(self):
        """High debt stress + weak behavior should yield deleveraging."""
        inputs = HouseholdInputs(
            debt_stress_score=1.5,
            behavioral_score=-0.8,
            wealth_score=0.0,
            household_prosperity_score=-0.5,
            z_savings_rate=0.0,
            z_m2_velocity=0.0,
            savings_rate=5.0,
        )
        regime = classify_household_regime(inputs)
        assert regime.name == "deleveraging"
        assert "stress" in regime.tags
    
    def test_credit_expansion_regime(self):
        """Net worth up but credit-driven should yield credit_expansion."""
        inputs = HouseholdInputs(
            z_net_worth_yoy=1.0,
            z_consumer_credit_yoy=1.5,
            savings_rate=3.0,  # Low savings
            z_savings_rate=-1.0,
            debt_stress_score=0.5,
            behavioral_score=0.5,
            wealth_score=0.5,
            household_prosperity_score=0.3,
        )
        regime = classify_household_regime(inputs)
        assert regime.name == "credit_expansion"
        assert "fragile" in regime.tags
    
    def test_inflationary_erosion_regime(self):
        """Nominal gains but weak sentiment and real losses → inflationary_erosion."""
        inputs = HouseholdInputs(
            z_net_worth_yoy=0.5,
            net_worth_real_yoy_pct=-2.0,  # Real decline
            z_consumer_sentiment=-1.5,  # Weak sentiment
            wealth_score=0.0,
            debt_stress_score=0.0,
            behavioral_score=-0.5,
            household_prosperity_score=-0.2,
            savings_rate=5.0,
            z_savings_rate=0.0,
        )
        regime = classify_household_regime(inputs)
        assert regime.name == "inflationary_erosion"
        assert "stagflationary" in regime.tags
    
    def test_corporate_capture_regime(self):
        """High deficit but poor household prosperity → corporate_capture."""
        sectoral = SectoralBalances(
            govt_deficit_pct_gdp=6.0,  # Large deficit
            net_exports_pct_gdp=-3.0,
            private_balance_pct_gdp=3.0,
        )
        inputs = HouseholdInputs(
            sectoral=sectoral,
            household_prosperity_score=-0.5,  # Poor household outcomes
            wealth_score=-0.3,
            debt_stress_score=0.3,
            behavioral_score=-0.2,
            savings_rate=5.0,
            z_savings_rate=0.0,
        )
        regime = classify_household_regime(inputs)
        assert regime.name == "corporate_capture"
        assert "concentration" in regime.tags
    
    def test_neutral_regime(self):
        """Mixed signals should yield neutral regime."""
        inputs = HouseholdInputs(
            wealth_score=0.2,
            debt_stress_score=0.2,
            behavioral_score=0.1,
            household_prosperity_score=0.1,
            savings_rate=5.0,
            z_savings_rate=0.0,
        )
        regime = classify_household_regime(inputs)
        assert regime.name == "neutral"


class TestHouseholdFeatureVector:
    """Test ML feature extraction."""
    
    def test_feature_vector_structure(self):
        """Feature vector should contain expected feature groups."""
        sectoral = SectoralBalances(
            govt_deficit_pct_gdp=5.0,
            net_exports_pct_gdp=-2.5,
            private_balance_pct_gdp=2.5,
        )
        inputs = HouseholdInputs(
            sectoral=sectoral,
            savings_rate=6.0,
            z_savings_rate=0.5,
            debt_service_ratio=10.0,
            z_debt_service=0.0,
            consumer_sentiment=95.0,
            z_consumer_sentiment=0.0,
            wealth_score=0.5,
            debt_stress_score=0.0,
            behavioral_score=0.3,
            household_prosperity_score=0.4,
        )
        state = HouseholdState(
            asof="2024-01-15",
            start_date="2011-01-01",
            inputs=inputs,
        )
        regime = HouseholdRegime(
            name="wealth_accumulation",
            label="Wealth Accumulation",
            description="Test",
            tags=("household", "risk_on"),
        )
        
        vec = household_feature_vector(state, regime)
        
        # Check sectoral features
        assert "hh.sectoral.govt_deficit_pct_gdp" in vec.features
        assert vec.features["hh.sectoral.govt_deficit_pct_gdp"] == 5.0
        
        # Check behavioral features
        assert "hh.behavior.savings_rate" in vec.features
        assert vec.features["hh.behavior.savings_rate"] == 6.0
        
        # Check debt features
        assert "hh.debt.service_ratio" in vec.features
        
        # Check composite features
        assert "hh.composite.prosperity_score" in vec.features
        
        # Check one-hot encoding
        assert "hh.regime.wealth_accumulation" in vec.features
        assert vec.features["hh.regime.wealth_accumulation"] == 1.0
        assert vec.features.get("hh.regime.deleveraging", 0.0) == 0.0
    
    def test_all_regime_names_in_one_hot(self):
        """All canonical regime names should be available for one-hot."""
        assert "wealth_accumulation" in HOUSEHOLD_REGIME_NAMES
        assert "deleveraging" in HOUSEHOLD_REGIME_NAMES
        assert "credit_expansion" in HOUSEHOLD_REGIME_NAMES
        assert "inflationary_erosion" in HOUSEHOLD_REGIME_NAMES
        assert "corporate_capture" in HOUSEHOLD_REGIME_NAMES
        assert "neutral" in HOUSEHOLD_REGIME_NAMES


class TestSectoralBalances:
    """Test MMT sectoral balances model."""
    
    def test_sectoral_balances_identity(self):
        """Private balance should equal (G-T) + NX."""
        sb = SectoralBalances(
            govt_deficit_pct_gdp=5.0,
            net_exports_pct_gdp=-3.0,
            private_balance_pct_gdp=2.0,  # 5 + (-3) = 2
        )
        expected_balance = sb.govt_deficit_pct_gdp + sb.net_exports_pct_gdp
        assert abs(sb.private_balance_pct_gdp - expected_balance) < 0.01
    
    def test_sectoral_balances_with_none(self):
        """Sectoral balances should handle None values gracefully."""
        sb = SectoralBalances(
            govt_deficit_pct_gdp=5.0,
            net_exports_pct_gdp=None,
            private_balance_pct_gdp=None,
        )
        assert sb.govt_deficit_pct_gdp == 5.0
        assert sb.net_exports_pct_gdp is None
