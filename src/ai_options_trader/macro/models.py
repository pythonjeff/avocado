from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Optional, Dict


class MacroInputs(BaseModel):
    # Inflation "reality"
    cpi_yoy: Optional[float] = None
    core_cpi_yoy: Optional[float] = None
    cpi_3m_annualized: Optional[float] = None
    cpi_6m_annualized: Optional[float] = None

    # Inflation "expectations"
    breakeven_5y: Optional[float] = None
    breakeven_10y: Optional[float] = None

    # Rates
    eff_fed_funds: Optional[float] = None
    ust_2y: Optional[float] = None
    ust_10y: Optional[float] = None

    # Derived
    curve_2s10s: Optional[float] = None
    real_yield_proxy_10y: Optional[float] = None  # DGS10 - T10YIE
    inflation_momentum_minus_be5y: Optional[float] = None  # CPI 6m ann - 5y breakeven

    # Composite
    disconnect_score: Optional[float] = None
    components: Dict[str, Optional[float]] = Field(default_factory=dict)


class MacroState(BaseModel):
    asof: str
    start_date: str
    inputs: MacroInputs
    notes: str = ""
