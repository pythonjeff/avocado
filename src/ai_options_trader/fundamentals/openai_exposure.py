"""
OpenAI Exposure Tracker

Tracks companies with direct exposure to OpenAI's success/failure:
- Investors (MSFT)
- Infrastructure providers (NVDA, ORCL)
- Integration partners (AAPL)
- API-dependent companies

Bear thesis: OpenAI is revenue-negative, burning investor cash,
and if it fails or scales back, these companies take the hit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Literal
from datetime import datetime
import requests

from ai_options_trader.config import Settings


# OpenAI financial estimates (private company, estimates from press reports)
OPENAI_FINANCIALS = {
    "valuation": 80_000,  # $80B+ (Jan 2024 round)
    "annual_revenue_est": 3_400,  # $3.4B ARR (late 2024 reports)
    "revenue_growth_yoy": 2.0,  # ~200% growth
    "annual_burn_est": 5_000,  # $5B+ annual burn (training + ops)
    "total_funding": 17_000,  # $17B+ raised
    "cash_runway_months": 18,  # Estimated
    "employees": 3_000,  # Approximate
    "profitable": False,
    "path_to_profit": "Unclear - compute costs scale with usage",
}

# Companies with OpenAI exposure
OPENAI_EXPOSURE = {
    "MSFT": {
        "name": "Microsoft",
        "relationship": "primary_investor",
        "investment_amount": 13_000,  # $13B+
        "ownership_pct": 49,  # 49% of profit interest (capped)
        "revenue_exposure": "high",  # Azure OpenAI, Copilot
        "exposure_description": "Exclusive cloud provider, 49% profit share (capped), Azure OpenAI service, Copilot products",
        "upside_if_success": "Copilot revenue, Azure AI dominance, enterprise AI lock-in",
        "downside_if_failure": "~$13B write-off, Copilot product risk, Azure AI credibility",
        "strategic_importance": 10,  # 1-10 scale
    },
    "NVDA": {
        "name": "NVIDIA",
        "relationship": "infrastructure_provider",
        "investment_amount": 0,  # Not a direct investor
        "ownership_pct": 0,
        "revenue_exposure": "very_high",  # OpenAI is major GPU customer
        "exposure_description": "Primary GPU supplier for OpenAI training, H100/H200 purchaser",
        "upside_if_success": "Continued massive GPU orders, pricing power",
        "downside_if_failure": "Lost customer (~5-10% of data center revenue?), demand narrative hit",
        "strategic_importance": 8,
    },
    "ORCL": {
        "name": "Oracle",
        "relationship": "infrastructure_partner",
        "investment_amount": 0,
        "ownership_pct": 0,
        "revenue_exposure": "medium",  # OCI partnership
        "exposure_description": "Cloud infrastructure partnership for training, OCI AI services",
        "upside_if_success": "OCI growth, enterprise AI credibility",
        "downside_if_failure": "OCI narrative weakened, partnership revenue loss",
        "strategic_importance": 5,
    },
    "AAPL": {
        "name": "Apple",
        "relationship": "integration_partner",
        "investment_amount": 0,
        "ownership_pct": 0,
        "revenue_exposure": "low",  # Siri integration
        "exposure_description": "Apple Intelligence powered by OpenAI, Siri integration",
        "upside_if_success": "AI feature parity, device differentiation",
        "downside_if_failure": "Need alternative AI provider, product feature gap",
        "strategic_importance": 4,
    },
    "ARM": {
        "name": "Arm Holdings",
        "relationship": "ecosystem",
        "investment_amount": 0,
        "ownership_pct": 0,
        "revenue_exposure": "low",
        "exposure_description": "AI inference chips, edge AI, architecture licensing",
        "upside_if_success": "AI chip demand, inference at edge",
        "downside_if_failure": "Modest - diversified customer base",
        "strategic_importance": 3,
    },
    "CRWV": {
        "name": "CoreWeave",
        "relationship": "nvda_invested_customer",
        "investment_amount": 500,  # Estimated NVDA stake ~$500M at IPO
        "ownership_pct": 5,  # Estimated 5-10% stake
        "revenue_exposure": "very_high",  # 100% NVDA GPUs
        "exposure_description": "GPU cloud provider, 100% NVIDIA infrastructure, NVDA investor + customer",
        "upside_if_success": "AI cloud demand explodes, MSFT overflow grows",
        "downside_if_failure": "Stock collapse, NVDA loses major customer, circular revenue exposed",
        "strategic_importance": 9,  # Critical for NVDA demand story
    },
}


# CoreWeave specific analysis
COREWEAVE_DETAILS = {
    "ticker": "CRWV",
    "ipo_date": "2025-03-28",
    "ipo_price": 40.00,
    "nvda_investment_rounds": [
        {"date": "2023-08", "round": "Series B", "amount_raised": 2300, "nvda_participation": True},
        {"date": "2024-05", "round": "Debt Financing", "amount_raised": 7500, "nvda_participation": True},
        {"date": "2025-03", "round": "IPO", "amount_raised": 1500, "nvda_participation": False},
    ],
    "key_customers": {
        "Microsoft": {"pct_revenue": 60, "relationship": "Azure overflow"},
        "OpenAI": {"pct_revenue": 15, "relationship": "Training infrastructure"},
        "Meta": {"pct_revenue": 10, "relationship": "AI workloads"},
    },
    "financials": {
        "revenue_2024": 1920,  # $M
        "net_income_2024": -860,  # $M
        "capex_2024": 8700,  # $M (mostly NVDA GPUs)
        "gross_margin": 0.74,
    },
    "circular_dependency": """
    The NVDA-CRWV Circular Revenue Problem:
    
    1. NVDA invests $X in CoreWeave
    2. CoreWeave uses $X to buy NVDA GPUs
    3. NVDA books GPU sale as revenue
    4. NVDA's investment is effectively paying itself
    
    If CoreWeave fails:
    - NVDA loses investment (~$500M)
    - NVDA loses customer (~$5-10B/year in GPU sales)
    - NVDA demand narrative takes a hit
    """,
}

# Companies that could be DISRUPTED by OpenAI
OPENAI_DISRUPTION_RISK = {
    "GOOG": {
        "name": "Google",
        "risk_type": "competitive",
        "risk_level": "high",
        "description": "Search disruption from ChatGPT, AI assistant competition",
    },
    "CRM": {
        "name": "Salesforce",
        "risk_type": "competitive", 
        "risk_level": "medium",
        "description": "AI agents could disrupt CRM workflows",
    },
    "NOW": {
        "name": "ServiceNow",
        "risk_type": "competitive",
        "risk_level": "medium", 
        "description": "AI agents could automate IT workflows",
    },
    "ADBE": {
        "name": "Adobe",
        "risk_type": "competitive",
        "risk_level": "medium",
        "description": "Generative AI for creative tools",
    },
}


@dataclass
class OpenAIHealth:
    """Estimated health metrics for OpenAI."""
    
    as_of: str
    
    # Financial estimates
    valuation: float = 0  # $M
    annual_revenue: float = 0  # $M
    revenue_growth: float = 0  # %
    annual_burn: float = 0  # $M
    cash_runway_months: int = 0
    
    # Business metrics
    profitable: bool = False
    path_to_profit: str = ""
    
    # Risk factors
    key_risks: list[str] = field(default_factory=list)
    
    # Health score (0-100, lower = more risk)
    health_score: int = 50


@dataclass  
class CompanyOpenAIExposure:
    """A company's exposure to OpenAI."""
    
    ticker: str
    name: str
    relationship: str  # primary_investor, infrastructure_provider, etc.
    
    # Investment exposure
    investment_amount: float = 0  # $M
    ownership_pct: float = 0
    
    # Revenue exposure
    revenue_exposure: str = ""  # very_high, high, medium, low
    exposure_description: str = ""
    
    # Scenario analysis
    upside_if_success: str = ""
    downside_if_failure: str = ""
    
    # Financial data
    market_cap: float = 0  # $B
    revenue_ttm: float = 0  # $B
    operating_margin: float = 0
    
    # Exposure as % of company
    investment_pct_of_mcap: float = 0
    openai_revenue_pct_est: float = 0  # Estimated % of revenue from OpenAI
    
    # Risk score (0-100, higher = more exposed)
    exposure_risk_score: int = 0


@dataclass
class OpenAIExposureReport:
    """Complete OpenAI exposure analysis."""
    
    as_of: str
    
    # OpenAI health
    openai_health: OpenAIHealth = None
    
    # Exposed companies
    exposed_companies: list[CompanyOpenAIExposure] = field(default_factory=list)
    
    # Disruption targets
    disruption_risks: list[dict] = field(default_factory=list)
    
    # Aggregate metrics
    total_investment_exposure: float = 0  # $B
    avg_exposure_score: float = 0
    
    # Key insights
    insights: list[str] = field(default_factory=list)
    thesis_implications: list[str] = field(default_factory=list)


def build_openai_health_estimate() -> OpenAIHealth:
    """Build estimated health profile for OpenAI."""
    
    health = OpenAIHealth(as_of=datetime.now().strftime("%Y-%m-%d"))
    
    # Pull from our estimates
    health.valuation = OPENAI_FINANCIALS["valuation"]
    health.annual_revenue = OPENAI_FINANCIALS["annual_revenue_est"]
    health.revenue_growth = OPENAI_FINANCIALS["revenue_growth_yoy"]
    health.annual_burn = OPENAI_FINANCIALS["annual_burn_est"]
    health.cash_runway_months = OPENAI_FINANCIALS["cash_runway_months"]
    health.profitable = OPENAI_FINANCIALS["profitable"]
    health.path_to_profit = OPENAI_FINANCIALS["path_to_profit"]
    
    # Key risks
    health.key_risks = [
        "Compute costs scale with usage - unclear unit economics",
        "Competition from open-source (Llama, Mistral) and Google",
        "Talent retention issues (Altman drama, departures)",
        "Regulatory risk (AI safety, copyright lawsuits)",
        "Microsoft dependency - 49% profit cap limits upside",
        "Model capability plateau concerns",
    ]
    
    # Calculate health score
    score = 50  # Start neutral
    
    # Revenue growth is strong (+)
    if health.revenue_growth > 1.0:  # >100% growth
        score += 15
    
    # But burning cash heavily (-)
    if health.annual_burn > health.annual_revenue:
        score -= 20
    
    # Short runway (-)
    if health.cash_runway_months < 24:
        score -= 10
    
    # Not profitable (-)
    if not health.profitable:
        score -= 10
    
    # High valuation relative to revenue (-)
    if health.valuation > health.annual_revenue * 30:  # >30x revenue
        score -= 5
    
    health.health_score = max(0, min(100, score))
    
    return health


def fetch_company_exposure(settings: Settings, ticker: str) -> CompanyOpenAIExposure:
    """Fetch financial data and calculate OpenAI exposure for a company."""
    
    t = ticker.strip().upper()
    info = OPENAI_EXPOSURE.get(t, {})
    
    exposure = CompanyOpenAIExposure(
        ticker=t,
        name=info.get("name", t),
        relationship=info.get("relationship", "unknown"),
        investment_amount=info.get("investment_amount", 0),
        ownership_pct=info.get("ownership_pct", 0),
        revenue_exposure=info.get("revenue_exposure", "unknown"),
        exposure_description=info.get("exposure_description", ""),
        upside_if_success=info.get("upside_if_success", ""),
        downside_if_failure=info.get("downside_if_failure", ""),
    )
    
    base_url = "https://financialmodelingprep.com/api/v3"
    
    # Fetch market cap and financials
    try:
        resp = requests.get(
            f"{base_url}/profile/{t}",
            params={"apikey": settings.fmp_api_key},
            timeout=15,
        )
        if resp.ok:
            data = resp.json()
            if data:
                exposure.market_cap = data[0].get("mktCap", 0) / 1e9
    except Exception:
        pass
    
    try:
        resp = requests.get(
            f"{base_url}/income-statement/{t}",
            params={"apikey": settings.fmp_api_key, "period": "annual", "limit": 1},
            timeout=15,
        )
        if resp.ok:
            data = resp.json()
            if data:
                exposure.revenue_ttm = data[0].get("revenue", 0) / 1e9
                if data[0].get("revenue", 0) > 0:
                    exposure.operating_margin = data[0].get("operatingIncome", 0) / data[0].get("revenue", 1)
    except Exception:
        pass
    
    # Calculate exposure metrics
    if exposure.market_cap > 0 and exposure.investment_amount > 0:
        exposure.investment_pct_of_mcap = (exposure.investment_amount / 1000) / exposure.market_cap * 100
    
    # Estimate OpenAI revenue contribution
    exposure.openai_revenue_pct_est = _estimate_openai_revenue_pct(t, exposure.revenue_ttm)
    
    # Calculate exposure risk score
    exposure.exposure_risk_score = _calculate_exposure_risk(exposure)
    
    return exposure


def _estimate_openai_revenue_pct(ticker: str, revenue_ttm: float) -> float:
    """Estimate what % of a company's revenue comes from OpenAI relationship."""
    
    # These are rough estimates based on public information
    estimates = {
        "MSFT": 2.0,   # Azure OpenAI + Copilot maybe 2% of revenue
        "NVDA": 8.0,   # OpenAI ~8% of data center revenue (rough)
        "ORCL": 1.0,   # Small portion of OCI
        "AAPL": 0.0,   # No direct revenue from OpenAI
        "ARM": 0.5,    # Indirect licensing
    }
    
    return estimates.get(ticker, 0.0)


def _calculate_exposure_risk(exposure: CompanyOpenAIExposure) -> int:
    """Calculate exposure risk score (0-100, higher = more risk)."""
    
    score = 0
    
    # Investment exposure
    if exposure.investment_pct_of_mcap > 5:
        score += 30
    elif exposure.investment_pct_of_mcap > 2:
        score += 20
    elif exposure.investment_pct_of_mcap > 0:
        score += 10
    
    # Revenue exposure
    revenue_exp_map = {
        "very_high": 40,
        "high": 30,
        "medium": 20,
        "low": 10,
    }
    score += revenue_exp_map.get(exposure.revenue_exposure, 0)
    
    # Strategic importance
    strategic = OPENAI_EXPOSURE.get(exposure.ticker, {}).get("strategic_importance", 5)
    score += strategic * 2
    
    return min(100, score)


def build_openai_exposure_report(settings: Settings) -> OpenAIExposureReport:
    """Build comprehensive OpenAI exposure report."""
    
    report = OpenAIExposureReport(as_of=datetime.now().strftime("%Y-%m-%d"))
    
    # Build OpenAI health estimate
    report.openai_health = build_openai_health_estimate()
    
    # Fetch exposure for all tracked companies
    for ticker in OPENAI_EXPOSURE.keys():
        try:
            exp = fetch_company_exposure(settings, ticker)
            report.exposed_companies.append(exp)
        except Exception:
            pass
    
    # Sort by exposure risk
    report.exposed_companies.sort(key=lambda x: x.exposure_risk_score, reverse=True)
    
    # Add disruption targets
    for ticker, info in OPENAI_DISRUPTION_RISK.items():
        report.disruption_risks.append({
            "ticker": ticker,
            **info,
        })
    
    # Calculate aggregates
    report.total_investment_exposure = sum(
        e.investment_amount for e in report.exposed_companies
    ) / 1000  # Convert to $B
    
    if report.exposed_companies:
        report.avg_exposure_score = sum(
            e.exposure_risk_score for e in report.exposed_companies
        ) / len(report.exposed_companies)
    
    # Generate insights
    report.insights = _generate_openai_insights(report)
    report.thesis_implications = _generate_thesis_implications(report)
    
    return report


def _generate_openai_insights(report: OpenAIExposureReport) -> list[str]:
    """Generate key insights about OpenAI exposure."""
    
    insights = []
    
    # OpenAI health
    health = report.openai_health
    insights.append(f"OpenAI burning ${health.annual_burn/1000:.1f}B/year vs ${health.annual_revenue/1000:.1f}B revenue")
    insights.append(f"OpenAI health score: {health.health_score}/100 (50 = neutral)")
    
    # Most exposed
    if report.exposed_companies:
        most_exposed = report.exposed_companies[0]
        insights.append(f"Most exposed: {most_exposed.name} (risk score: {most_exposed.exposure_risk_score})")
    
    # Total investment at risk
    insights.append(f"Total direct investment exposure: ${report.total_investment_exposure:.1f}B")
    
    return insights


def _generate_thesis_implications(report: OpenAIExposureReport) -> list[str]:
    """Generate implications for the bear thesis."""
    
    implications = []
    
    health = report.openai_health
    
    # If OpenAI fails/scales back
    implications.append("If OpenAI fails or significantly scales back:")
    
    msft = next((e for e in report.exposed_companies if e.ticker == "MSFT"), None)
    if msft:
        implications.append(f"  • MSFT: ${msft.investment_amount/1000:.0f}B write-off risk, Copilot strategy at risk")
    
    nvda = next((e for e in report.exposed_companies if e.ticker == "NVDA"), None)
    if nvda:
        implications.append(f"  • NVDA: ~{nvda.openai_revenue_pct_est:.0f}% revenue loss, narrative hit on AI demand")
    
    # If OpenAI succeeds
    implications.append("")
    implications.append("If OpenAI succeeds and achieves profitability:")
    implications.append("  • MSFT profit share kicks in (capped at ~$92B)")
    implications.append("  • NVDA benefits from continued scaling")
    implications.append("  • Disruption risk increases for GOOG, CRM, NOW")
    
    return implications


def get_openai_thesis_summary() -> dict:
    """Get a summary of the OpenAI bear thesis."""
    
    return {
        "thesis": "OpenAI is revenue-negative, burning investor cash for scaling compute that may hit limits",
        "key_questions": [
            "Can OpenAI achieve positive unit economics at scale?",
            "Will LLM capabilities continue scaling with compute?",
            "Can OpenAI compete with open-source and Google?",
            "What happens when Microsoft's $13B is exhausted?",
        ],
        "bear_triggers": [
            "OpenAI announces layoffs or compute reduction",
            "Microsoft takes write-down on OpenAI investment",
            "Model capability plateau becomes evident",
            "Open-source models achieve GPT-4 parity",
            "Major enterprise customers churn from ChatGPT Enterprise",
        ],
        "monitoring": [
            "Microsoft Copilot revenue disclosures",
            "Azure AI services growth",
            "OpenAI employee departures",
            "Sam Altman public statements on profitability",
            "Competitor model releases (Gemini, Llama, Claude)",
        ],
    }
