"""
Revenue/Margin Sensitivity Model

Build sensitivity tables showing how EPS and valuation change
based on revenue growth and margin assumptions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Literal
import numpy as np

from ai_options_trader.config import Settings


@dataclass
class FinancialInputs:
    """Base financial inputs for the model."""
    ticker: str
    company_name: str = ""
    
    # Current financials (TTM or latest FY)
    revenue_ttm: float = 0  # in millions
    gross_profit_ttm: float = 0
    operating_income_ttm: float = 0
    net_income_ttm: float = 0
    
    # Margins
    gross_margin: float = 0
    operating_margin: float = 0
    net_margin: float = 0
    
    # Per share
    shares_outstanding: float = 0  # in millions
    eps_ttm: float = 0
    
    # Balance sheet
    cash: float = 0
    debt: float = 0
    
    # Valuation
    market_cap: float = 0
    current_price: float = 0
    pe_ratio: float = 0
    
    # Growth
    revenue_growth_yoy: float = 0
    eps_growth_yoy: float = 0
    
    # Estimates (consensus)
    revenue_est_next_fy: Optional[float] = None
    eps_est_next_fy: Optional[float] = None
    revenue_growth_est: Optional[float] = None


@dataclass
class SensitivityModel:
    """Revenue/Margin sensitivity model results."""
    
    ticker: str
    base_inputs: FinancialInputs
    
    # Scenario axes
    revenue_growth_scenarios: list[float] = field(default_factory=list)  # e.g., [10%, 20%, 30%]
    margin_scenarios: list[float] = field(default_factory=list)  # e.g., [20%, 25%, 30%]
    
    # Result matrices (rows = revenue growth, cols = margins)
    eps_matrix: list[list[float]] = field(default_factory=list)
    implied_pe_matrix: list[list[float]] = field(default_factory=list)
    upside_matrix: list[list[float]] = field(default_factory=list)  # vs current price
    
    # Fair value estimates
    base_case_eps: float = 0
    base_case_fair_value: float = 0
    bull_case_fair_value: float = 0
    bear_case_fair_value: float = 0
    
    # Key insights
    insights: list[str] = field(default_factory=list)


def fetch_financial_data(settings: Settings, ticker: str) -> FinancialInputs:
    """Fetch financial data for a ticker from FMP."""
    import requests
    
    t = ticker.strip().upper()
    inputs = FinancialInputs(ticker=t)
    
    if not settings.fmp_api_key:
        raise ValueError("FMP API key required for financial data")
    
    base_url = "https://financialmodelingprep.com/api/v3"
    
    # Fetch profile
    try:
        resp = requests.get(
            f"{base_url}/profile/{t}",
            params={"apikey": settings.fmp_api_key},
            timeout=15,
        )
        if resp.ok:
            data = resp.json()
            if data:
                p = data[0]
                inputs.company_name = p.get("companyName", t)
                inputs.market_cap = p.get("mktCap", 0) / 1e6  # Convert to millions
                inputs.current_price = p.get("price", 0)
    except Exception:
        pass
    
    # Fetch income statement (TTM)
    try:
        resp = requests.get(
            f"{base_url}/income-statement/{t}",
            params={"apikey": settings.fmp_api_key, "period": "annual", "limit": 2},
            timeout=15,
        )
        if resp.ok:
            data = resp.json()
            if data:
                latest = data[0]
                inputs.revenue_ttm = latest.get("revenue", 0) / 1e6
                inputs.gross_profit_ttm = latest.get("grossProfit", 0) / 1e6
                inputs.operating_income_ttm = latest.get("operatingIncome", 0) / 1e6
                inputs.net_income_ttm = latest.get("netIncome", 0) / 1e6
                inputs.eps_ttm = latest.get("eps", 0)
                
                # Calculate margins
                if inputs.revenue_ttm > 0:
                    inputs.gross_margin = inputs.gross_profit_ttm / inputs.revenue_ttm
                    inputs.operating_margin = inputs.operating_income_ttm / inputs.revenue_ttm
                    inputs.net_margin = inputs.net_income_ttm / inputs.revenue_ttm
                
                # YoY growth
                if len(data) > 1:
                    prev = data[1]
                    prev_rev = prev.get("revenue", 0) / 1e6
                    prev_eps = prev.get("eps", 0)
                    if prev_rev > 0:
                        inputs.revenue_growth_yoy = (inputs.revenue_ttm / prev_rev - 1)
                    if prev_eps > 0:
                        inputs.eps_growth_yoy = (inputs.eps_ttm / prev_eps - 1)
    except Exception:
        pass
    
    # Fetch shares outstanding
    try:
        resp = requests.get(
            f"{base_url}/enterprise-values/{t}",
            params={"apikey": settings.fmp_api_key, "limit": 1},
            timeout=15,
        )
        if resp.ok:
            data = resp.json()
            if data:
                inputs.shares_outstanding = data[0].get("numberOfShares", 0) / 1e6
    except Exception:
        pass
    
    # Fetch balance sheet for cash/debt
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
                inputs.cash = bs.get("cashAndCashEquivalents", 0) / 1e6
                inputs.debt = bs.get("totalDebt", 0) / 1e6
    except Exception:
        pass
    
    # Fetch analyst estimates
    try:
        resp = requests.get(
            f"{base_url}/analyst-estimates/{t}",
            params={"apikey": settings.fmp_api_key, "period": "annual", "limit": 2},
            timeout=15,
        )
        if resp.ok:
            data = resp.json()
            if data:
                est = data[0]
                inputs.revenue_est_next_fy = est.get("estimatedRevenueAvg", 0) / 1e6
                inputs.eps_est_next_fy = est.get("estimatedEpsAvg", 0)
                if inputs.revenue_ttm > 0 and inputs.revenue_est_next_fy:
                    inputs.revenue_growth_est = (inputs.revenue_est_next_fy / inputs.revenue_ttm - 1)
    except Exception:
        pass
    
    # Calculate PE ratio
    if inputs.current_price > 0 and inputs.eps_ttm > 0:
        inputs.pe_ratio = inputs.current_price / inputs.eps_ttm
    
    return inputs


def build_sensitivity_model(
    settings: Settings,
    ticker: str,
    revenue_growth_range: tuple[float, float, float] = (-0.1, 0.5, 0.1),  # (min, max, step)
    margin_range: tuple[float, float, float] = (0.15, 0.40, 0.05),  # (min, max, step)
    target_pe: float = 25,  # PE multiple for valuation
    inputs: Optional[FinancialInputs] = None,
) -> SensitivityModel:
    """
    Build a revenue/margin sensitivity model.
    
    Args:
        settings: App settings
        ticker: Stock ticker
        revenue_growth_range: (min, max, step) for revenue growth scenarios
        margin_range: (min, max, step) for margin scenarios
        target_pe: PE multiple to apply for fair value
        inputs: Optional pre-fetched financial inputs
    
    Returns:
        SensitivityModel with sensitivity matrices
    """
    # Fetch data if not provided
    if inputs is None:
        inputs = fetch_financial_data(settings, ticker)
    
    # Generate scenario axes
    rev_min, rev_max, rev_step = revenue_growth_range
    margin_min, margin_max, margin_step = margin_range
    
    revenue_scenarios = list(np.arange(rev_min, rev_max + rev_step/2, rev_step))
    margin_scenarios = list(np.arange(margin_min, margin_max + margin_step/2, margin_step))
    
    # Build sensitivity matrices
    eps_matrix = []
    pe_matrix = []
    upside_matrix = []
    
    base_revenue = inputs.revenue_ttm
    shares = inputs.shares_outstanding if inputs.shares_outstanding > 0 else 1
    current_price = inputs.current_price if inputs.current_price > 0 else 1
    
    for rev_growth in revenue_scenarios:
        eps_row = []
        pe_row = []
        upside_row = []
        
        projected_revenue = base_revenue * (1 + rev_growth)
        
        for net_margin in margin_scenarios:
            # Calculate projected net income and EPS
            projected_net_income = projected_revenue * net_margin
            projected_eps = projected_net_income / shares
            
            # Fair value at target PE
            fair_value = projected_eps * target_pe
            
            # Implied PE at current price
            implied_pe = current_price / projected_eps if projected_eps > 0 else 999
            
            # Upside/downside vs current price
            upside = (fair_value / current_price - 1) * 100 if current_price > 0 else 0
            
            eps_row.append(round(projected_eps, 2))
            pe_row.append(round(implied_pe, 1))
            upside_row.append(round(upside, 1))
        
        eps_matrix.append(eps_row)
        pe_matrix.append(pe_row)
        upside_matrix.append(upside_row)
    
    # Identify base/bull/bear cases
    # Base case: consensus growth, current margin
    base_growth_idx = len(revenue_scenarios) // 2
    base_margin_idx = len(margin_scenarios) // 2
    
    # Find closest to consensus if available
    if inputs.revenue_growth_est is not None:
        for i, g in enumerate(revenue_scenarios):
            if abs(g - inputs.revenue_growth_est) < abs(revenue_scenarios[base_growth_idx] - inputs.revenue_growth_est):
                base_growth_idx = i
    
    # Find closest to current margin
    for i, m in enumerate(margin_scenarios):
        if abs(m - inputs.net_margin) < abs(margin_scenarios[base_margin_idx] - inputs.net_margin):
            base_margin_idx = i
    
    base_case_eps = eps_matrix[base_growth_idx][base_margin_idx]
    base_case_fv = base_case_eps * target_pe
    
    # Bull case: high growth, high margin
    bull_case_fv = eps_matrix[-1][-1] * target_pe
    
    # Bear case: low growth, low margin
    bear_case_fv = eps_matrix[0][0] * target_pe
    
    # Generate insights
    insights = _generate_insights(inputs, eps_matrix, revenue_scenarios, margin_scenarios, target_pe)
    
    return SensitivityModel(
        ticker=ticker,
        base_inputs=inputs,
        revenue_growth_scenarios=revenue_scenarios,
        margin_scenarios=margin_scenarios,
        eps_matrix=eps_matrix,
        implied_pe_matrix=pe_matrix,
        upside_matrix=upside_matrix,
        base_case_eps=base_case_eps,
        base_case_fair_value=base_case_fv,
        bull_case_fair_value=bull_case_fv,
        bear_case_fair_value=bear_case_fv,
        insights=insights,
    )


def _generate_insights(
    inputs: FinancialInputs,
    eps_matrix: list[list[float]],
    revenue_scenarios: list[float],
    margin_scenarios: list[float],
    target_pe: float,
) -> list[str]:
    """Generate key insights from the sensitivity analysis."""
    insights = []
    
    current_price = inputs.current_price
    
    # What's implied by current price?
    if inputs.pe_ratio > 0:
        insights.append(f"Current P/E of {inputs.pe_ratio:.1f}x implies market expects strong growth continuation")
    
    # Margin sensitivity
    if inputs.net_margin > 0:
        mid_growth_idx = len(revenue_scenarios) // 2
        base_margin_eps = None
        high_margin_eps = None
        
        for i, m in enumerate(margin_scenarios):
            if abs(m - inputs.net_margin) < 0.02:
                base_margin_eps = eps_matrix[mid_growth_idx][i]
            if m >= inputs.net_margin + 0.05:
                high_margin_eps = eps_matrix[mid_growth_idx][i]
                break
        
        if base_margin_eps and high_margin_eps:
            margin_impact = (high_margin_eps / base_margin_eps - 1) * 100
            insights.append(f"5% margin expansion = {margin_impact:.0f}% EPS upside (high operating leverage)")
    
    # Revenue sensitivity
    mid_margin_idx = len(margin_scenarios) // 2
    if len(revenue_scenarios) >= 3:
        low_rev_eps = eps_matrix[0][mid_margin_idx]
        high_rev_eps = eps_matrix[-1][mid_margin_idx]
        rev_range = revenue_scenarios[-1] - revenue_scenarios[0]
        eps_range = (high_rev_eps / low_rev_eps - 1) * 100 if low_rev_eps > 0 else 0
        insights.append(f"Revenue growth range ({revenue_scenarios[0]*100:.0f}% to {revenue_scenarios[-1]*100:.0f}%) = {eps_range:.0f}% EPS range")
    
    # Breakeven analysis
    for i, rev_g in enumerate(revenue_scenarios):
        for j, margin in enumerate(margin_scenarios):
            eps = eps_matrix[i][j]
            fv = eps * target_pe
            if 0.95 <= fv / current_price <= 1.05:
                insights.append(f"Current price justified at {rev_g*100:.0f}% rev growth, {margin*100:.0f}% net margin")
                break
    
    return insights


def run_scenario_analysis(
    settings: Settings,
    ticker: str,
    scenarios: list[dict],
) -> list[dict]:
    """
    Run specific named scenarios.
    
    Args:
        scenarios: List of scenario dicts with:
            - name: Scenario name
            - revenue_growth: Revenue growth rate
            - net_margin: Net margin
            - pe_multiple: PE multiple to apply
    
    Returns:
        List of scenario results
    """
    inputs = fetch_financial_data(settings, ticker)
    
    results = []
    base_revenue = inputs.revenue_ttm
    shares = inputs.shares_outstanding if inputs.shares_outstanding > 0 else 1
    current_price = inputs.current_price
    
    for scenario in scenarios:
        rev_growth = scenario.get("revenue_growth", 0)
        net_margin = scenario.get("net_margin", inputs.net_margin)
        pe_mult = scenario.get("pe_multiple", 25)
        
        projected_rev = base_revenue * (1 + rev_growth)
        projected_ni = projected_rev * net_margin
        projected_eps = projected_ni / shares
        fair_value = projected_eps * pe_mult
        upside = (fair_value / current_price - 1) * 100 if current_price > 0 else 0
        
        results.append({
            "name": scenario.get("name", "Unnamed"),
            "revenue": round(projected_rev, 0),
            "net_income": round(projected_ni, 0),
            "eps": round(projected_eps, 2),
            "fair_value": round(fair_value, 2),
            "upside_pct": round(upside, 1),
        })
    
    return results
