from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Optional, Dict


class MacroInputs(BaseModel):
    # Inflation "reality"
    cpi_yoy: Optional[float] = None
    core_cpi_yoy: Optional[float] = None
    median_cpi_yoy: Optional[float] = None  # Sticky inflation proxy
    cpi_3m_annualized: Optional[float] = None
    cpi_6m_annualized: Optional[float] = None

    # Inflation "expectations"
    breakeven_5y: Optional[float] = None
    breakeven_10y: Optional[float] = None
    breakeven_5y5y: Optional[float] = None  # 5y5y forward inflation expectation

    # Labor market
    payrolls_yoy: Optional[float] = None  # PAYEMS YoY % change
    payrolls_3m_annualized: Optional[float] = None  # PAYEMS 3m annualized % change
    payrolls_mom: Optional[float] = None  # PAYEMS MoM % change
    unemployment_rate: Optional[float] = None  # UNRATE
    initial_claims_4w: Optional[float] = None  # ICSA 4-week average

    # Rates
    eff_fed_funds: Optional[float] = None
    ust_2y: Optional[float] = None
    ust_10y: Optional[float] = None

    # Derived
    curve_2s10s: Optional[float] = None
    real_yield_proxy_10y: Optional[float] = None  # DGS10 - T10YIE
    inflation_momentum_minus_be5y: Optional[float] = None  # CPI 6m ann - 5y breakeven

    # Credit spreads (systemic stress)
    hy_oas: Optional[float] = None  # High yield OAS (bps)
    ig_oas: Optional[float] = None  # Investment grade OAS (bps)
    hy_ig_spread: Optional[float] = None  # HY - IG spread (bps)
    
    # Volatility regime
    vix: Optional[float] = None  # CBOE VIX (1-month implied vol)
    vixm: Optional[float] = None  # CBOE VIX Mid-Term (3-month implied vol)
    vix_term_structure: Optional[float] = None  # VIX - VIXM (negative = contango, positive = backwardation)
    move: Optional[float] = None  # ICE MOVE index (bond volatility)
    
    # Dollar / FX stress
    dxy: Optional[float] = None  # Dollar index
    
    # Commodities
    gold_price: Optional[float] = None  # Gold spot price
    oil_price: Optional[float] = None  # WTI crude
    gold_oil_ratio: Optional[float] = None  # Gold/Oil ratio (risk-off indicator)
    
    # Housing
    mortgage_30y: Optional[float] = None  # 30-year mortgage rate
    mortgage_spread: Optional[float] = None  # Mortgage rate - 10Y treasury (bps)
    home_prices_yoy: Optional[float] = None  # Case-Shiller YoY % change

    # Composite
    disconnect_score: Optional[float] = None
    components: Dict[str, Optional[float]] = Field(default_factory=dict)


class MacroState(BaseModel):
    asof: str
    start_date: str
    inputs: MacroInputs
    notes: str = ""
