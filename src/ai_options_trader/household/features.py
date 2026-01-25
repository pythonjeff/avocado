"""
Household Wealth Regime - ML Feature Extraction

Converts household state into a flat feature vector for ML models.
Follows the canonical pattern used by other regime modules.
"""
from __future__ import annotations

from ai_options_trader.regimes.schema import RegimeVector, add_feature, add_one_hot
from ai_options_trader.household.models import HouseholdState
from ai_options_trader.household.regime import HouseholdRegime


# Canonical regime names for one-hot encoding
HOUSEHOLD_REGIME_NAMES = (
    "wealth_accumulation",
    "deleveraging", 
    "credit_expansion",
    "inflationary_erosion",
    "corporate_capture",
    "neutral",
)


def household_feature_vector(
    state: HouseholdState, 
    regime: HouseholdRegime,
) -> RegimeVector:
    """
    Convert household state to ML-friendly feature vector.
    
    Feature groups:
    - hh.sectoral.*: MMT sectoral balances context
    - hh.wealth.*: Wealth accumulation metrics
    - hh.debt.*: Debt burden metrics
    - hh.behavior.*: Behavioral indicators
    - hh.composite.*: Composite scores
    - hh.regime.*: One-hot regime encoding
    """
    f: dict[str, float] = {}
    inp = state.inputs
    
    # -------------------------------------------------------------------------
    # Sectoral Balances (MMT Context)
    # -------------------------------------------------------------------------
    if inp.sectoral:
        add_feature(f, "hh.sectoral.govt_deficit_pct_gdp", inp.sectoral.govt_deficit_pct_gdp)
        add_feature(f, "hh.sectoral.net_exports_pct_gdp", inp.sectoral.net_exports_pct_gdp)
        add_feature(f, "hh.sectoral.investment_pct_gdp", inp.sectoral.private_investment_pct_gdp)
        add_feature(f, "hh.sectoral.private_balance_pct_gdp", inp.sectoral.private_balance_pct_gdp)
    
    # -------------------------------------------------------------------------
    # Wealth Metrics
    # -------------------------------------------------------------------------
    add_feature(f, "hh.wealth.net_worth_tn", inp.net_worth_tn)
    add_feature(f, "hh.wealth.net_worth_yoy_pct", inp.net_worth_yoy_pct)
    add_feature(f, "hh.wealth.net_worth_real_yoy_pct", inp.net_worth_real_yoy_pct)
    add_feature(f, "hh.wealth.z_net_worth_yoy", inp.z_net_worth_yoy)
    add_feature(f, "hh.wealth.checkable_deposits_bn", inp.checkable_deposits_bn)
    add_feature(f, "hh.wealth.money_market_funds_bn", inp.money_market_funds_bn)
    
    # -------------------------------------------------------------------------
    # Debt Metrics
    # -------------------------------------------------------------------------
    add_feature(f, "hh.debt.service_ratio", inp.debt_service_ratio)
    add_feature(f, "hh.debt.service_yoy_chg", inp.debt_service_yoy_chg)
    add_feature(f, "hh.debt.z_service_ratio", inp.z_debt_service)
    add_feature(f, "hh.debt.consumer_credit_yoy_pct", inp.consumer_credit_yoy_pct)
    add_feature(f, "hh.debt.revolving_credit_yoy_pct", inp.revolving_credit_yoy_pct)
    add_feature(f, "hh.debt.z_consumer_credit_yoy", inp.z_consumer_credit_yoy)
    add_feature(f, "hh.debt.mortgage_delinquency_rate", inp.mortgage_delinquency_rate)
    add_feature(f, "hh.debt.z_mortgage_delinquency", inp.z_mortgage_delinquency)
    
    # -------------------------------------------------------------------------
    # Behavioral Metrics
    # -------------------------------------------------------------------------
    add_feature(f, "hh.behavior.savings_rate", inp.savings_rate)
    add_feature(f, "hh.behavior.savings_rate_3m_avg", inp.savings_rate_3m_avg)
    add_feature(f, "hh.behavior.z_savings_rate", inp.z_savings_rate)
    add_feature(f, "hh.behavior.consumer_sentiment", inp.consumer_sentiment)
    add_feature(f, "hh.behavior.consumer_sentiment_yoy_chg", inp.consumer_sentiment_yoy_chg)
    add_feature(f, "hh.behavior.z_consumer_sentiment", inp.z_consumer_sentiment)
    add_feature(f, "hh.behavior.m2_velocity", inp.m2_velocity)
    add_feature(f, "hh.behavior.m2_velocity_yoy_pct", inp.m2_velocity_yoy_pct)
    add_feature(f, "hh.behavior.z_m2_velocity", inp.z_m2_velocity)
    add_feature(f, "hh.behavior.real_dpi_yoy_pct", inp.real_dpi_yoy_pct)
    add_feature(f, "hh.behavior.z_real_dpi_yoy", inp.z_real_dpi_yoy)
    add_feature(f, "hh.behavior.retail_sales_yoy_pct", inp.retail_sales_yoy_pct)
    add_feature(f, "hh.behavior.z_retail_sales_yoy", inp.z_retail_sales_yoy)
    
    # -------------------------------------------------------------------------
    # Wealth Distribution (if available)
    # -------------------------------------------------------------------------
    add_feature(f, "hh.distribution.top_1pct_share", inp.top_1pct_wealth_share)
    add_feature(f, "hh.distribution.bottom_50pct_share", inp.bottom_50pct_wealth_share)
    add_feature(f, "hh.distribution.concentration_delta", inp.wealth_concentration_delta)
    
    # -------------------------------------------------------------------------
    # Composite Scores
    # -------------------------------------------------------------------------
    add_feature(f, "hh.composite.wealth_score", inp.wealth_score)
    add_feature(f, "hh.composite.debt_stress_score", inp.debt_stress_score)
    add_feature(f, "hh.composite.behavioral_score", inp.behavioral_score)
    add_feature(f, "hh.composite.prosperity_score", inp.household_prosperity_score)
    
    # -------------------------------------------------------------------------
    # Regime One-Hot Encoding
    # -------------------------------------------------------------------------
    add_one_hot(f, "hh.regime", regime.name, HOUSEHOLD_REGIME_NAMES)
    
    return RegimeVector(
        asof=state.asof,
        features=f,
        notes=(
            "Household wealth regime features. Includes MMT sectoral balances context, "
            "wealth/debt/behavioral metrics, and composite scores. "
            "Regime identity: S = (G-T) + I + NX."
        ),
    )
