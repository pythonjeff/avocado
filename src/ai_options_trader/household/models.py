"""
Household Wealth Regime - Data Models

Tracks where government deficit dollars flow and what household behavior they drive.

Based on the MMT Sectoral Balances Identity:
    S = (G - T) + I + NX

Where:
    S   = Private Sector Savings (household + corporate surplus)
    G-T = Government Deficit (spending minus taxes)
    I   = Net Investment
    NX  = Net Exports (trade balance)

The key insight: Government deficits *necessarily* create private surpluses.
The question is WHERE that surplus accumulates and what BEHAVIOR it drives.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SectoralBalances:
    """
    MMT Sectoral Balances: S = (G-T) + I + NX
    
    All values as % of GDP (annualized) for comparability.
    Positive private_balance = private sector surplus (accumulation).
    """
    # Components (% GDP)
    govt_deficit_pct_gdp: float | None = None      # (G-T): positive = deficit
    net_exports_pct_gdp: float | None = None       # NX: negative = trade deficit
    private_investment_pct_gdp: float | None = None  # I: gross private domestic investment
    
    # Derived
    private_balance_pct_gdp: float | None = None   # S = (G-T) + NX (simplified)
    
    # Data freshness
    asof: str | None = None
    notes: str = ""


@dataclass(frozen=True)
class HouseholdInputs:
    """
    Household balance sheet and behavioral metrics.
    
    Three pillars:
    1. WEALTH: Net worth, liquid assets
    2. DEBT: Service burden, credit dynamics
    3. BEHAVIOR: Savings rate, sentiment, velocity
    """
    # -------------------------------------------------------------------------
    # Sectoral Balances Context (MMT framework)
    # -------------------------------------------------------------------------
    sectoral: SectoralBalances | None = None
    
    # -------------------------------------------------------------------------
    # 1. WEALTH METRICS
    # -------------------------------------------------------------------------
    # Household net worth (FRED: TNWBSHNO, quarterly, trillions)
    net_worth_tn: float | None = None
    net_worth_yoy_pct: float | None = None
    net_worth_real_yoy_pct: float | None = None  # Adjusted for CPI
    z_net_worth_yoy: float | None = None
    
    # Liquid assets / cash holdings
    checkable_deposits_bn: float | None = None   # BOGZ1FL153020005Q
    money_market_funds_bn: float | None = None   # WRMFSL
    
    # -------------------------------------------------------------------------
    # 2. DEBT METRICS  
    # -------------------------------------------------------------------------
    # Debt service ratio (FRED: TDSP, quarterly, %)
    debt_service_ratio: float | None = None
    debt_service_yoy_chg: float | None = None
    z_debt_service: float | None = None
    
    # Consumer credit dynamics (FRED: TOTALSL, monthly, billions)
    consumer_credit_yoy_pct: float | None = None
    revolving_credit_yoy_pct: float | None = None  # Credit cards (REVOLSL)
    z_consumer_credit_yoy: float | None = None
    
    # Delinquency (FRED: DRSFRMACBS, quarterly, %)
    mortgage_delinquency_rate: float | None = None
    z_mortgage_delinquency: float | None = None
    
    # -------------------------------------------------------------------------
    # 3. BEHAVIORAL METRICS
    # -------------------------------------------------------------------------
    # Personal savings rate (FRED: PSAVERT, monthly, %)
    savings_rate: float | None = None
    savings_rate_3m_avg: float | None = None
    z_savings_rate: float | None = None
    
    # Consumer sentiment (FRED: UMCSENT, monthly, index)
    consumer_sentiment: float | None = None
    consumer_sentiment_yoy_chg: float | None = None
    z_consumer_sentiment: float | None = None
    
    # Money velocity (FRED: M2V, quarterly)
    m2_velocity: float | None = None
    m2_velocity_yoy_pct: float | None = None
    z_m2_velocity: float | None = None
    
    # Real disposable income (FRED: DSPIC96, monthly)
    real_dpi_yoy_pct: float | None = None
    z_real_dpi_yoy: float | None = None
    
    # Retail sales (FRED: RSXFS, monthly)
    retail_sales_yoy_pct: float | None = None
    z_retail_sales_yoy: float | None = None
    
    # -------------------------------------------------------------------------
    # 4. WEALTH DISTRIBUTION (optional - Fed DFA data)
    # -------------------------------------------------------------------------
    top_1pct_wealth_share: float | None = None
    bottom_50pct_wealth_share: float | None = None
    wealth_concentration_delta: float | None = None  # Δ(top1%) - Δ(bottom50%)
    
    # -------------------------------------------------------------------------
    # COMPOSITE SCORES
    # -------------------------------------------------------------------------
    # Wealth accumulation score (higher = more wealth building)
    wealth_score: float | None = None
    # Debt stress score (higher = more debt burden)  
    debt_stress_score: float | None = None
    # Behavioral confidence score (higher = more spending/risk-on)
    behavioral_score: float | None = None
    # Overall household prosperity score
    household_prosperity_score: float | None = None
    
    # Debug / transparency
    components: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HouseholdState:
    """
    Complete household regime snapshot.
    """
    asof: str
    start_date: str
    inputs: HouseholdInputs
    notes: str = ""
