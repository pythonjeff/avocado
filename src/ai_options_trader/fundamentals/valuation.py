"""
Valuation Models

DCF, reverse DCF, and implied growth analysis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
import numpy as np

from ai_options_trader.config import Settings


@dataclass
class DCFModel:
    """DCF valuation model results."""
    
    ticker: str
    
    # Inputs
    fcf_base: float = 0  # Base year FCF
    growth_rate_phase1: float = 0  # High growth phase (years 1-5)
    growth_rate_phase2: float = 0  # Fade phase (years 6-10)
    terminal_growth: float = 0.025  # Terminal growth (perpetuity)
    discount_rate: float = 0.10  # WACC
    
    # Outputs
    pv_phase1: float = 0
    pv_phase2: float = 0
    pv_terminal: float = 0
    enterprise_value: float = 0
    equity_value: float = 0
    fair_value_per_share: float = 0
    
    # Sensitivity
    upside_vs_current: float = 0
    implied_return: float = 0
    
    # FCF projections
    fcf_projections: list[float] = field(default_factory=list)


@dataclass
class ImpliedGrowthResult:
    """Result of reverse DCF / implied growth calculation."""
    
    ticker: str
    current_price: float
    implied_growth_rate: float  # What growth is priced in
    terminal_growth: float
    discount_rate: float
    
    # Interpretation
    growth_assessment: str  # "reasonable", "aggressive", "conservative"
    comparison_vs_historical: float  # vs actual historical growth
    comparison_vs_consensus: Optional[float] = None


def build_dcf_model(
    settings: Settings,
    ticker: str,
    growth_phase1: float = 0.20,  # 20% growth years 1-5
    growth_phase2: float = 0.10,  # 10% growth years 6-10
    terminal_growth: float = 0.025,  # 2.5% perpetuity
    discount_rate: float = 0.10,  # 10% WACC
) -> DCFModel:
    """
    Build a two-stage DCF model.
    
    Args:
        settings: App settings
        ticker: Stock ticker
        growth_phase1: Growth rate for years 1-5
        growth_phase2: Growth rate for years 6-10
        terminal_growth: Terminal perpetuity growth
        discount_rate: WACC / discount rate
    
    Returns:
        DCFModel with valuation
    """
    import requests
    
    t = ticker.strip().upper()
    
    # Fetch FCF and other data
    fcf_base = 0
    shares = 1
    cash = 0
    debt = 0
    current_price = 0
    
    base_url = "https://financialmodelingprep.com/api/v3"
    
    # Get FCF from cash flow statement
    try:
        resp = requests.get(
            f"{base_url}/cash-flow-statement/{t}",
            params={"apikey": settings.fmp_api_key, "period": "annual", "limit": 1},
            timeout=15,
        )
        if resp.ok:
            data = resp.json()
            if data:
                fcf_base = data[0].get("freeCashFlow", 0) / 1e6
    except Exception:
        pass
    
    # Get shares, cash, debt
    try:
        resp = requests.get(
            f"{base_url}/balance-sheet-statement/{t}",
            params={"apikey": settings.fmp_api_key, "period": "annual", "limit": 1},
            timeout=15,
        )
        if resp.ok:
            data = resp.json()
            if data:
                bs = data[0]
                cash = bs.get("cashAndCashEquivalents", 0) / 1e6
                debt = bs.get("totalDebt", 0) / 1e6
    except Exception:
        pass
    
    try:
        resp = requests.get(
            f"{base_url}/enterprise-values/{t}",
            params={"apikey": settings.fmp_api_key, "limit": 1},
            timeout=15,
        )
        if resp.ok:
            data = resp.json()
            if data:
                shares = data[0].get("numberOfShares", 1e6) / 1e6
    except Exception:
        pass
    
    try:
        resp = requests.get(
            f"{base_url}/quote/{t}",
            params={"apikey": settings.fmp_api_key},
            timeout=10,
        )
        if resp.ok:
            data = resp.json()
            if data:
                current_price = data[0].get("price", 0)
    except Exception:
        pass
    
    # Project FCFs
    fcf_projections = []
    
    # Phase 1: Years 1-5
    fcf = fcf_base
    pv_phase1 = 0
    for year in range(1, 6):
        fcf = fcf * (1 + growth_phase1)
        pv = fcf / ((1 + discount_rate) ** year)
        pv_phase1 += pv
        fcf_projections.append(round(fcf, 0))
    
    # Phase 2: Years 6-10
    pv_phase2 = 0
    for year in range(6, 11):
        fcf = fcf * (1 + growth_phase2)
        pv = fcf / ((1 + discount_rate) ** year)
        pv_phase2 += pv
        fcf_projections.append(round(fcf, 0))
    
    # Terminal value
    terminal_fcf = fcf * (1 + terminal_growth)
    terminal_value = terminal_fcf / (discount_rate - terminal_growth)
    pv_terminal = terminal_value / ((1 + discount_rate) ** 10)
    
    # Enterprise value
    enterprise_value = pv_phase1 + pv_phase2 + pv_terminal
    
    # Equity value
    equity_value = enterprise_value + cash - debt
    
    # Per share
    fair_value = equity_value / shares if shares > 0 else 0
    
    # Upside
    upside = (fair_value / current_price - 1) * 100 if current_price > 0 else 0
    
    # Implied return (if bought at current price)
    implied_return = ((fair_value / current_price) ** (1/5) - 1) * 100 if current_price > 0 else 0
    
    return DCFModel(
        ticker=t,
        fcf_base=fcf_base,
        growth_rate_phase1=growth_phase1,
        growth_rate_phase2=growth_phase2,
        terminal_growth=terminal_growth,
        discount_rate=discount_rate,
        pv_phase1=round(pv_phase1, 0),
        pv_phase2=round(pv_phase2, 0),
        pv_terminal=round(pv_terminal, 0),
        enterprise_value=round(enterprise_value, 0),
        equity_value=round(equity_value, 0),
        fair_value_per_share=round(fair_value, 2),
        upside_vs_current=round(upside, 1),
        implied_return=round(implied_return, 1),
        fcf_projections=fcf_projections,
    )


def reverse_dcf(
    settings: Settings,
    ticker: str,
    terminal_growth: float = 0.025,
    discount_rate: float = 0.10,
) -> ImpliedGrowthResult:
    """
    Reverse DCF: What growth rate is implied by current price?
    
    Solves for the growth rate that makes DCF = current market cap.
    """
    import requests
    
    t = ticker.strip().upper()
    
    # Fetch data
    fcf_base = 0
    market_cap = 0
    current_price = 0
    historical_growth = 0
    consensus_growth = None
    cash = 0
    debt = 0
    
    base_url = "https://financialmodelingprep.com/api/v3"
    
    # Get FCF
    try:
        resp = requests.get(
            f"{base_url}/cash-flow-statement/{t}",
            params={"apikey": settings.fmp_api_key, "period": "annual", "limit": 3},
            timeout=15,
        )
        if resp.ok:
            data = resp.json()
            if data:
                fcf_base = data[0].get("freeCashFlow", 0) / 1e6
                # Historical growth
                if len(data) >= 3:
                    fcf_3y_ago = data[2].get("freeCashFlow", 0) / 1e6
                    if fcf_3y_ago > 0:
                        historical_growth = (fcf_base / fcf_3y_ago) ** (1/2) - 1
    except Exception:
        pass
    
    # Get market cap
    try:
        resp = requests.get(
            f"{base_url}/profile/{t}",
            params={"apikey": settings.fmp_api_key},
            timeout=15,
        )
        if resp.ok:
            data = resp.json()
            if data:
                market_cap = data[0].get("mktCap", 0) / 1e6
                current_price = data[0].get("price", 0)
    except Exception:
        pass
    
    # Get cash/debt
    try:
        resp = requests.get(
            f"{base_url}/balance-sheet-statement/{t}",
            params={"apikey": settings.fmp_api_key, "period": "annual", "limit": 1},
            timeout=15,
        )
        if resp.ok:
            data = resp.json()
            if data:
                bs = data[0]
                cash = bs.get("cashAndCashEquivalents", 0) / 1e6
                debt = bs.get("totalDebt", 0) / 1e6
    except Exception:
        pass
    
    # Get consensus growth
    try:
        resp = requests.get(
            f"{base_url}/analyst-estimates/{t}",
            params={"apikey": settings.fmp_api_key, "period": "annual", "limit": 2},
            timeout=15,
        )
        if resp.ok:
            data = resp.json()
            if data and len(data) >= 2:
                rev_y1 = data[0].get("estimatedRevenueAvg", 0)
                rev_y2 = data[1].get("estimatedRevenueAvg", 0)
                if rev_y1 > 0 and rev_y2 > 0:
                    consensus_growth = (rev_y1 / rev_y2 - 1)
    except Exception:
        pass
    
    # Implied enterprise value
    implied_ev = market_cap - cash + debt
    
    # Binary search for implied growth rate
    if fcf_base <= 0 or implied_ev <= 0:
        implied_growth = 0
    else:
        # Search between -20% and 50% growth
        low, high = -0.2, 0.5
        for _ in range(50):  # Binary search iterations
            mid = (low + high) / 2
            
            # Calculate DCF at this growth rate
            dcf_value = _calculate_dcf_value(fcf_base, mid, terminal_growth, discount_rate)
            
            if dcf_value < implied_ev:
                low = mid
            else:
                high = mid
        
        implied_growth = mid
    
    # Assessment
    if implied_growth > 0.30:
        assessment = "aggressive"
    elif implied_growth > 0.15:
        assessment = "reasonable"
    elif implied_growth > 0.05:
        assessment = "conservative"
    else:
        assessment = "very conservative / value"
    
    return ImpliedGrowthResult(
        ticker=t,
        current_price=current_price,
        implied_growth_rate=round(implied_growth, 3),
        terminal_growth=terminal_growth,
        discount_rate=discount_rate,
        growth_assessment=assessment,
        comparison_vs_historical=round(implied_growth - historical_growth, 3) if historical_growth else 0,
        comparison_vs_consensus=round(implied_growth - consensus_growth, 3) if consensus_growth else None,
    )


def _calculate_dcf_value(
    fcf_base: float,
    growth_rate: float,
    terminal_growth: float,
    discount_rate: float,
    years: int = 10,
) -> float:
    """Calculate DCF value for a given growth rate."""
    pv_sum = 0
    fcf = fcf_base
    
    for year in range(1, years + 1):
        fcf = fcf * (1 + growth_rate)
        pv = fcf / ((1 + discount_rate) ** year)
        pv_sum += pv
    
    # Terminal value
    terminal_fcf = fcf * (1 + terminal_growth)
    terminal_value = terminal_fcf / (discount_rate - terminal_growth)
    pv_terminal = terminal_value / ((1 + discount_rate) ** years)
    
    return pv_sum + pv_terminal


def calculate_implied_growth(
    current_price: float,
    eps: float,
    pe_target: float = 20,
    years: int = 5,
) -> float:
    """
    Simple implied growth calculation.
    
    What earnings growth is needed to justify current price
    at a target PE multiple in N years?
    """
    if eps <= 0 or current_price <= 0:
        return 0
    
    # Current PE
    current_pe = current_price / eps
    
    # Required EPS to justify price at target PE
    required_eps = current_price / pe_target
    
    # Implied CAGR
    implied_growth = (required_eps / eps) ** (1 / years) - 1
    
    return implied_growth
