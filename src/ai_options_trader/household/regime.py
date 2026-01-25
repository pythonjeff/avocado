"""
Household Wealth Regime - Classification Logic

Classifies household financial conditions into actionable regimes based on
where government deficit dollars flow and what behavior they drive.

Regime Framework (based on MMT sectoral balances):
- Government deficits necessarily create private surpluses: S = (G-T) + I + NX
- The key question: WHERE does the surplus accumulate and WHAT behavior results?

Regimes:
1. WEALTH_ACCUMULATION: Surplus → net worth gains, healthy savings, low stress
2. DELEVERAGING: Surplus → debt paydown, elevated savings, low velocity
3. CREDIT_EXPANSION: Surplus → leverage-driven gains, fragile
4. INFLATIONARY_EROSION: Surplus → nominal gains but real purchasing power down
5. CORPORATE_CAPTURE: Surplus → corporate profits, not household prosperity
"""
from __future__ import annotations

from dataclasses import dataclass

from ai_options_trader.household.models import HouseholdInputs


@dataclass(frozen=True)
class HouseholdRegime:
    """
    Household regime classification result.
    
    Canonical fields for all regime types:
    - name: Machine-readable regime identifier
    - label: Human-readable short label
    - description: Detailed explanation
    - tags: Classification tags for filtering
    - market_implications: Trading implications
    """
    name: str
    label: str
    description: str
    tags: tuple[str, ...] = ()
    market_implications: str = ""


def classify_household_regime(inputs: HouseholdInputs) -> HouseholdRegime:
    """
    Classify household regime based on wealth, debt, and behavioral metrics.
    
    Classification logic uses composite scores:
    - wealth_score: Net worth growth + savings (positive = accumulating)
    - debt_stress_score: Debt burden + credit growth + delinquencies (positive = stress)
    - behavioral_score: Sentiment + income + spending (positive = confident)
    - prosperity_score: Overall household financial health
    
    Regime decision tree:
    1. If debt_stress high + behavioral low → DELEVERAGING
    2. If wealth high but debt_stress rising fast → CREDIT_EXPANSION
    3. If sentiment weak despite wealth gains → INFLATIONARY_EROSION
    4. If wealth high + behavioral high + debt low → WEALTH_ACCUMULATION
    5. If sectoral shows deficit but household metrics flat → CORPORATE_CAPTURE
    6. Default → NEUTRAL
    """
    # Extract scores (may be None)
    wealth = inputs.wealth_score
    debt_stress = inputs.debt_stress_score
    behavioral = inputs.behavioral_score
    prosperity = inputs.household_prosperity_score
    
    # Key individual metrics for nuanced classification
    z_debt_service = inputs.z_debt_service
    z_savings = inputs.z_savings_rate
    z_sentiment = inputs.z_consumer_sentiment
    z_velocity = inputs.z_m2_velocity
    z_net_worth = inputs.z_net_worth_yoy
    savings_rate = inputs.savings_rate
    
    # Sectoral context
    sectoral = inputs.sectoral
    govt_deficit = sectoral.govt_deficit_pct_gdp if sectoral else None
    
    # -------------------------------------------------------------------------
    # DELEVERAGING: High savings, weak velocity, debt paydown mode
    # -------------------------------------------------------------------------
    # Elevated savings + falling velocity + weak sentiment = hoarding mode
    if (
        (z_savings is not None and z_savings >= 1.0) and
        (z_velocity is not None and z_velocity <= -0.5) and
        (behavioral is not None and behavioral <= 0.0)
    ):
        return HouseholdRegime(
            name="deleveraging",
            label="Deleveraging",
            description=(
                "Households are prioritizing savings and debt paydown over spending. "
                "Elevated savings rate with falling money velocity indicates precautionary "
                "behavior. Deficit dollars are being hoarded rather than spent."
            ),
            tags=("household", "defensive", "risk_off"),
            market_implications=(
                "Favor: Long duration bonds (TLT), utilities (XLU), consumer staples (XLP). "
                "Avoid: Consumer discretionary (XLY), small caps (IWM). "
                "Risk: Deflationary pressure, weak demand."
            ),
        )
    
    # Also flag deleveraging if debt stress is high and behavior weak
    if (
        (debt_stress is not None and debt_stress >= 1.0) and
        (behavioral is not None and behavioral <= -0.5)
    ):
        return HouseholdRegime(
            name="deleveraging",
            label="Deleveraging (Stress-Driven)",
            description=(
                "Households are under debt stress and pulling back spending. "
                "High debt service burden forcing behavioral retrenchment."
            ),
            tags=("household", "defensive", "risk_off", "stress"),
            market_implications=(
                "Favor: Defensives, investment grade credit. "
                "Avoid: High yield, consumer discretionary, banks. "
                "Risk: Credit deterioration, recession risk."
            ),
        )
    
    # -------------------------------------------------------------------------
    # CREDIT_EXPANSION: Wealth rising but driven by leverage
    # -------------------------------------------------------------------------
    # Net worth up + debt growing fast + savings compressed
    if (
        (z_net_worth is not None and z_net_worth >= 0.5) and
        (inputs.z_consumer_credit_yoy is not None and inputs.z_consumer_credit_yoy >= 1.0) and
        (savings_rate is not None and savings_rate <= 5.0)
    ):
        return HouseholdRegime(
            name="credit_expansion",
            label="Credit Expansion",
            description=(
                "Household wealth gains are being supported by credit expansion rather than "
                "income growth. Low savings rate and rising consumer credit suggest fragile, "
                "leverage-dependent prosperity."
            ),
            tags=("household", "risk_on", "fragile"),
            market_implications=(
                "Favor: Momentum plays, financials (short-term). "
                "Avoid: Rate-sensitive if Fed tightening. "
                "Risk: Fed-dependent, fragile to rate hikes or credit tightening."
            ),
        )
    
    # -------------------------------------------------------------------------
    # INFLATIONARY_EROSION: Nominal gains but real purchasing power declining
    # -------------------------------------------------------------------------
    # Sentiment weak despite apparent wealth gains
    if (
        (z_net_worth is not None and z_net_worth >= 0.0) and
        (z_sentiment is not None and z_sentiment <= -1.0) and
        (inputs.net_worth_real_yoy_pct is not None and inputs.net_worth_real_yoy_pct <= 0.0)
    ):
        return HouseholdRegime(
            name="inflationary_erosion",
            label="Inflationary Erosion",
            description=(
                "Nominal household wealth may appear stable, but real purchasing power is "
                "declining. Consumer sentiment is weak despite 'good' headline numbers. "
                "Inflation is eroding the benefits of any government deficit injection."
            ),
            tags=("household", "stagflationary", "risk_off"),
            market_implications=(
                "Favor: Real assets, commodities (DBC, GLD), TIPS, energy (XLE). "
                "Avoid: Long duration bonds, growth stocks. "
                "Risk: Stagflationary conditions, political risk."
            ),
        )
    
    # -------------------------------------------------------------------------
    # WEALTH_ACCUMULATION: Healthy prosperity
    # -------------------------------------------------------------------------
    # Strong prosperity score + wealth building + manageable debt
    if (
        (prosperity is not None and prosperity >= 0.5) or
        (
            (wealth is not None and wealth >= 0.5) and
            (debt_stress is not None and debt_stress <= 0.5) and
            (behavioral is not None and behavioral >= 0.0)
        )
    ):
        return HouseholdRegime(
            name="wealth_accumulation",
            label="Wealth Accumulation",
            description=(
                "Households are successfully accumulating wealth with manageable debt levels. "
                "Government deficit dollars are translating into genuine private prosperity. "
                "Consumer behavior reflects confidence without excessive leverage."
            ),
            tags=("household", "risk_on", "healthy"),
            market_implications=(
                "Favor: Consumer discretionary (XLY), small caps (IWM), cyclicals. "
                "Avoid: Extreme defensives. "
                "Risk: Complacency, policy reversal."
            ),
        )
    
    # -------------------------------------------------------------------------
    # CORPORATE_CAPTURE: Deficits not reaching households
    # -------------------------------------------------------------------------
    # Large government deficit but weak household metrics
    if (
        (govt_deficit is not None and govt_deficit >= 4.0) and
        (prosperity is not None and prosperity <= 0.0)
    ):
        return HouseholdRegime(
            name="corporate_capture",
            label="Corporate Capture",
            description=(
                "Government deficits are running high but not translating into household "
                "prosperity. The private sector surplus may be accumulating in corporate "
                "coffers rather than household balance sheets (oligopoly capture)."
            ),
            tags=("household", "neutral", "concentration"),
            market_implications=(
                "Favor: Large cap quality, mega-cap tech, healthcare. "
                "Avoid: Small business exposure, consumer cyclicals. "
                "Risk: Political/regulatory intervention, populist policy."
            ),
        )
    
    # -------------------------------------------------------------------------
    # NEUTRAL: Mixed signals
    # -------------------------------------------------------------------------
    return HouseholdRegime(
        name="neutral",
        label="Neutral / Mixed",
        description=(
            "Household metrics show mixed signals without a clear directional bias. "
            "Monitor for regime transitions as data evolves."
        ),
        tags=("household", "neutral"),
        market_implications=(
            "Balanced positioning. Watch for emerging trends in savings rate, "
            "consumer sentiment, and debt dynamics."
        ),
    )


def classify_household_regime_from_state(
    inputs: HouseholdInputs,
) -> HouseholdRegime:
    """Alias for classify_household_regime for API consistency."""
    return classify_household_regime(inputs)
