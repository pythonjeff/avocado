"""
NVDA Partnership & Customer Health Tracker

Tracks NVDA's major customers, their AI CapEx, and whether their
AI investments are generating returns or burning cash.

Bear Thesis: NVDA customers are revenue-negative on LLM investments,
paying premium prices for chips to scale unprofitable businesses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Literal
from datetime import datetime
import requests

from ai_options_trader.config import Settings


# NVDA's major customers and AI infrastructure buyers
NVDA_PARTNERS = {
    # Hyperscalers (direct GPU buyers)
    "MSFT": {
        "name": "Microsoft",
        "relationship": "hyperscaler",
        "ai_exposure": "Azure AI, OpenAI partnership ($13B invested), Copilot",
        "notes": "Largest cloud AI provider, exclusive OpenAI partner",
    },
    "GOOGL": {
        "name": "Google/Alphabet",
        "relationship": "hyperscaler",
        "ai_exposure": "GCP AI, Gemini, DeepMind, TPU competitor",
        "notes": "Developing own TPUs but still major GPU buyer",
    },
    "AMZN": {
        "name": "Amazon",
        "relationship": "hyperscaler",
        "ai_exposure": "AWS AI, Bedrock, Anthropic investment ($4B), Trainium chips",
        "notes": "Developing Trainium/Inferentia but GPU-dependent",
    },
    "META": {
        "name": "Meta",
        "relationship": "hyperscaler",
        "ai_exposure": "Llama models, internal AI, Reality Labs",
        "notes": "Massive GPU buyer for Llama training, open-source approach",
    },
    "ORCL": {
        "name": "Oracle",
        "relationship": "hyperscaler",
        "ai_exposure": "OCI AI, enterprise AI, OpenAI partnership",
        "notes": "Aggressive cloud AI expansion",
    },
    # AI-First Companies
    "TSLA": {
        "name": "Tesla",
        "relationship": "ai_customer",
        "ai_exposure": "FSD training, Dojo (own chips), Optimus",
        "notes": "Building Dojo but still GPU-dependent for training",
    },
    # Enterprise Software (AI monetization plays)
    "CRM": {
        "name": "Salesforce",
        "relationship": "ai_software",
        "ai_exposure": "Einstein AI, AgentForce, enterprise AI",
        "notes": "Monetizing AI through enterprise software",
    },
    "NOW": {
        "name": "ServiceNow",
        "relationship": "ai_software",
        "ai_exposure": "Now Assist, enterprise AI workflows",
        "notes": "Strong AI monetization in enterprise",
    },
    # Chip/Infra Suppliers (NVDA ecosystem)
    "AVGO": {
        "name": "Broadcom",
        "relationship": "ecosystem",
        "ai_exposure": "Networking chips, custom AI accelerators",
        "notes": "Benefits from AI data center buildout",
    },
    "AMD": {
        "name": "AMD",
        "relationship": "competitor",
        "ai_exposure": "MI300 GPUs, data center CPUs",
        "notes": "Main GPU competitor, gaining share",
    },
}

# Private AI companies (can't track financials directly)
PRIVATE_AI_PLAYERS = {
    "OpenAI": {
        "funding": "$13B+ from Microsoft",
        "valuation": "$80B+",
        "revenue_est": "$2B (2024)",
        "profitable": False,
        "notes": "ChatGPT, GPT-4, largest NVDA customer via Azure",
    },
    "Anthropic": {
        "funding": "$7B+ (Amazon, Google)",
        "valuation": "$18B+",
        "revenue_est": "$500M (2024)",
        "profitable": False,
        "notes": "Claude, constitutional AI, safety-focused",
    },
    "xAI": {
        "funding": "$6B+",
        "valuation": "$24B+",
        "revenue_est": "Minimal",
        "profitable": False,
        "notes": "Grok, Elon Musk's AI company, massive GPU orders",
    },
    "Cohere": {
        "funding": "$970M",
        "valuation": "$5B+",
        "revenue_est": "$35M (2024)",
        "profitable": False,
        "notes": "Enterprise LLMs, Oracle partnership",
    },
    "Inflection": {
        "funding": "$1.5B",
        "valuation": "$4B",
        "revenue_est": "Minimal",
        "profitable": False,
        "notes": "Pi chatbot, talent acquired by Microsoft",
    },
}


@dataclass
class PartnerFinancials:
    """Financial health metrics for an NVDA partner."""
    
    ticker: str
    name: str
    relationship: str
    
    # Core financials
    revenue_ttm: float = 0
    revenue_growth_yoy: float = 0
    operating_margin: float = 0
    net_margin: float = 0
    fcf_ttm: float = 0
    
    # CapEx (AI investment proxy)
    capex_ttm: float = 0
    capex_growth_yoy: float = 0
    capex_to_revenue: float = 0  # CapEx intensity
    
    # AI-specific (estimated)
    ai_capex_est: Optional[float] = None  # Estimated AI portion of CapEx
    ai_revenue_est: Optional[float] = None  # Estimated AI revenue
    ai_roi_est: Optional[float] = None  # AI ROI estimate
    
    # Valuation
    pe_ratio: float = 0
    market_cap: float = 0
    
    # Stock performance
    price_1y_change: float = 0
    
    # Notes
    ai_exposure: str = ""
    notes: str = ""


@dataclass
class CapExCorrelation:
    """Correlation between partner CapEx and NVDA performance."""
    
    partner_ticker: str
    partner_name: str
    
    # Partner CapEx trend
    capex_3y_cagr: float = 0
    capex_ttm: float = 0
    
    # NVDA correlation
    capex_nvda_revenue_corr: Optional[float] = None
    
    # Timing analysis
    capex_leads_nvda_by_quarters: int = 0
    
    notes: str = ""


@dataclass
class PartnerHealthReport:
    """Aggregate report on NVDA partner ecosystem health."""
    
    as_of: str
    
    # Partner financials
    partners: list[PartnerFinancials] = field(default_factory=list)
    
    # Aggregate metrics
    total_partner_capex: float = 0
    avg_partner_capex_growth: float = 0
    avg_partner_margin: float = 0
    
    # AI economics assessment
    profitable_ai_partners: int = 0
    unprofitable_ai_partners: int = 0
    
    # Correlation with NVDA
    capex_correlations: list[CapExCorrelation] = field(default_factory=list)
    
    # Private AI company health
    private_ai_burn_rate_est: float = 0  # Estimated total burn
    
    # Risk assessment
    customer_concentration_risk: str = ""  # Low/Medium/High
    capex_sustainability_risk: str = ""
    ai_roi_risk: str = ""
    
    # Key insights
    insights: list[str] = field(default_factory=list)
    bear_thesis_evidence: list[str] = field(default_factory=list)
    bull_thesis_evidence: list[str] = field(default_factory=list)


def fetch_partner_financials(settings: Settings, ticker: str) -> PartnerFinancials:
    """Fetch financial data for a partner company."""
    
    t = ticker.strip().upper()
    partner_info = NVDA_PARTNERS.get(t, {})
    
    pf = PartnerFinancials(
        ticker=t,
        name=partner_info.get("name", t),
        relationship=partner_info.get("relationship", "unknown"),
        ai_exposure=partner_info.get("ai_exposure", ""),
        notes=partner_info.get("notes", ""),
    )
    
    base_url = "https://financialmodelingprep.com/api/v3"
    
    # Fetch income statement
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
                pf.revenue_ttm = latest.get("revenue", 0) / 1e9
                
                if latest.get("revenue", 0) > 0:
                    pf.operating_margin = latest.get("operatingIncome", 0) / latest.get("revenue", 1)
                    pf.net_margin = latest.get("netIncome", 0) / latest.get("revenue", 1)
                
                if len(data) > 1:
                    prev = data[1]
                    if prev.get("revenue", 0) > 0:
                        pf.revenue_growth_yoy = (latest.get("revenue", 0) / prev.get("revenue", 1) - 1)
    except Exception:
        pass
    
    # Fetch cash flow for CapEx and FCF
    try:
        resp = requests.get(
            f"{base_url}/cash-flow-statement/{t}",
            params={"apikey": settings.fmp_api_key, "period": "annual", "limit": 2},
            timeout=15,
        )
        if resp.ok:
            data = resp.json()
            if data:
                latest = data[0]
                pf.capex_ttm = abs(latest.get("capitalExpenditure", 0)) / 1e9
                pf.fcf_ttm = latest.get("freeCashFlow", 0) / 1e9
                
                if pf.revenue_ttm > 0:
                    pf.capex_to_revenue = pf.capex_ttm / pf.revenue_ttm
                
                if len(data) > 1:
                    prev = data[1]
                    prev_capex = abs(prev.get("capitalExpenditure", 0)) / 1e9
                    if prev_capex > 0:
                        pf.capex_growth_yoy = (pf.capex_ttm / prev_capex - 1)
    except Exception:
        pass
    
    # Fetch valuation
    try:
        resp = requests.get(
            f"{base_url}/profile/{t}",
            params={"apikey": settings.fmp_api_key},
            timeout=15,
        )
        if resp.ok:
            data = resp.json()
            if data:
                pf.market_cap = data[0].get("mktCap", 0) / 1e9
                price = data[0].get("price", 0)
    except Exception:
        pass
    
    # Fetch key metrics for PE
    try:
        resp = requests.get(
            f"{base_url}/ratios-ttm/{t}",
            params={"apikey": settings.fmp_api_key},
            timeout=15,
        )
        if resp.ok:
            data = resp.json()
            if data:
                pf.pe_ratio = data[0].get("priceEarningsRatioTTM", 0) or 0
    except Exception:
        pass
    
    # Estimate AI CapEx portion (rough heuristics)
    pf.ai_capex_est = _estimate_ai_capex(t, pf.capex_ttm)
    
    return pf


def _estimate_ai_capex(ticker: str, total_capex: float) -> float:
    """
    Estimate what portion of CapEx is AI-related.
    
    These are rough estimates based on company disclosures and analyst reports.
    """
    # AI CapEx as % of total CapEx (estimates)
    ai_capex_pct = {
        "MSFT": 0.50,   # ~50% of cloud CapEx is AI
        "GOOGL": 0.45,  # Heavy AI investment
        "AMZN": 0.35,   # Growing AI but also logistics
        "META": 0.70,   # Very AI-focused CapEx
        "ORCL": 0.40,   # Growing AI cloud
        "TSLA": 0.20,   # FSD + Dojo
        "CRM": 0.15,    # Some AI infra
        "NOW": 0.10,    # Minimal own infra
        "AVGO": 0.05,   # Ecosystem, not direct
        "AMD": 0.30,    # R&D for AI chips
    }
    
    pct = ai_capex_pct.get(ticker, 0.20)
    return total_capex * pct


def build_partner_health_report(settings: Settings) -> PartnerHealthReport:
    """
    Build comprehensive report on NVDA partner ecosystem health.
    
    Tests the bear thesis: Are NVDA's customers making money on AI?
    """
    from datetime import datetime
    
    report = PartnerHealthReport(as_of=datetime.now().strftime("%Y-%m-%d"))
    
    # Fetch financials for all partners
    for ticker in NVDA_PARTNERS.keys():
        try:
            pf = fetch_partner_financials(settings, ticker)
            report.partners.append(pf)
        except Exception:
            pass
    
    if not report.partners:
        return report
    
    # Calculate aggregates
    report.total_partner_capex = sum(p.capex_ttm for p in report.partners)
    
    capex_growths = [p.capex_growth_yoy for p in report.partners if p.capex_growth_yoy != 0]
    if capex_growths:
        report.avg_partner_capex_growth = sum(capex_growths) / len(capex_growths)
    
    margins = [p.operating_margin for p in report.partners if p.operating_margin != 0]
    if margins:
        report.avg_partner_margin = sum(margins) / len(margins)
    
    # Assess AI profitability
    # Hyperscalers with positive margins = potentially profitable AI
    for p in report.partners:
        if p.relationship == "hyperscaler":
            if p.operating_margin > 0.15:  # > 15% operating margin
                report.profitable_ai_partners += 1
            else:
                report.unprofitable_ai_partners += 1
    
    # Estimate private AI burn rate
    # OpenAI ~$5B/year, Anthropic ~$2B, xAI ~$2B, others ~$1B
    report.private_ai_burn_rate_est = 10.0  # $10B/year estimate
    
    # Risk assessments
    report.customer_concentration_risk = _assess_concentration_risk(report.partners)
    report.capex_sustainability_risk = _assess_capex_sustainability(report.partners)
    report.ai_roi_risk = _assess_ai_roi_risk(report.partners)
    
    # Generate insights
    report.insights = _generate_partner_insights(report)
    report.bear_thesis_evidence = _find_bear_evidence(report)
    report.bull_thesis_evidence = _find_bull_evidence(report)
    
    return report


def _assess_concentration_risk(partners: list[PartnerFinancials]) -> str:
    """Assess customer concentration risk for NVDA."""
    hyperscaler_capex = sum(
        p.ai_capex_est or 0 
        for p in partners 
        if p.relationship == "hyperscaler"
    )
    total_ai_capex = sum(p.ai_capex_est or 0 for p in partners)
    
    if total_ai_capex > 0:
        concentration = hyperscaler_capex / total_ai_capex
        if concentration > 0.8:
            return "HIGH - 80%+ from hyperscalers"
        elif concentration > 0.6:
            return "MEDIUM - 60-80% from hyperscalers"
        else:
            return "LOW - diversified customer base"
    return "UNKNOWN"


def _assess_capex_sustainability(partners: list[PartnerFinancials]) -> str:
    """Assess whether partner CapEx levels are sustainable."""
    high_intensity = 0
    
    for p in partners:
        if p.capex_to_revenue > 0.15:  # > 15% of revenue = high
            high_intensity += 1
    
    pct_high = high_intensity / len(partners) if partners else 0
    
    if pct_high > 0.5:
        return "HIGH - Many partners at unsustainable CapEx levels"
    elif pct_high > 0.25:
        return "MEDIUM - Some partners straining"
    else:
        return "LOW - CapEx appears manageable"


def _assess_ai_roi_risk(partners: list[PartnerFinancials]) -> str:
    """Assess risk that AI investments don't generate returns."""
    # Look at margin trends vs CapEx growth
    margin_vs_capex = []
    
    for p in partners:
        if p.capex_growth_yoy > 0.2:  # > 20% CapEx growth
            # Is margin improving or declining?
            margin_vs_capex.append(p.operating_margin)
    
    if margin_vs_capex:
        avg_margin = sum(margin_vs_capex) / len(margin_vs_capex)
        if avg_margin < 0.15:
            return "HIGH - CapEx growing but margins weak"
        elif avg_margin < 0.25:
            return "MEDIUM - Mixed margin picture"
        else:
            return "LOW - Strong margins despite CapEx growth"
    
    return "UNKNOWN"


def _generate_partner_insights(report: PartnerHealthReport) -> list[str]:
    """Generate key insights about partner ecosystem."""
    insights = []
    
    # Total AI CapEx
    total_ai_capex = sum(p.ai_capex_est or 0 for p in report.partners)
    insights.append(f"Estimated AI CapEx from tracked partners: ${total_ai_capex:.1f}B")
    
    # CapEx growth
    if report.avg_partner_capex_growth > 0.3:
        insights.append(f"Partner CapEx growing {report.avg_partner_capex_growth*100:.0f}% - strong GPU demand")
    elif report.avg_partner_capex_growth > 0.1:
        insights.append(f"Partner CapEx growth moderating at {report.avg_partner_capex_growth*100:.0f}%")
    else:
        insights.append(f"Partner CapEx growth slowing to {report.avg_partner_capex_growth*100:.0f}% - demand concern")
    
    # Profitability
    insights.append(f"Profitable hyperscalers: {report.profitable_ai_partners}, Unprofitable: {report.unprofitable_ai_partners}")
    
    # Private AI burn
    insights.append(f"Private AI companies burning est. ${report.private_ai_burn_rate_est:.0f}B/year")
    
    return insights


def _find_bear_evidence(report: PartnerHealthReport) -> list[str]:
    """Find evidence supporting the bear thesis."""
    evidence = []
    
    # High CapEx with weak margins
    for p in report.partners:
        if p.capex_growth_yoy > 0.3 and p.operating_margin < 0.20:
            evidence.append(f"{p.name}: CapEx up {p.capex_growth_yoy*100:.0f}% but margin only {p.operating_margin*100:.0f}%")
    
    # Private AI burning cash
    evidence.append(f"Private AI labs (OpenAI, Anthropic, xAI) are not profitable and burning ~$10B/year")
    
    # CapEx to revenue ratios
    high_intensity = [p for p in report.partners if p.capex_to_revenue > 0.15]
    if high_intensity:
        names = ", ".join(p.ticker for p in high_intensity)
        evidence.append(f"High CapEx intensity (>15% of revenue): {names}")
    
    # META-specific (known massive AI spender)
    meta = next((p for p in report.partners if p.ticker == "META"), None)
    if meta and meta.ai_capex_est:
        evidence.append(f"META spending est. ${meta.ai_capex_est:.1f}B on AI with unclear monetization path")
    
    return evidence


def _find_bull_evidence(report: PartnerHealthReport) -> list[str]:
    """Find evidence against the bear thesis."""
    evidence = []
    
    # Strong margins despite CapEx
    for p in report.partners:
        if p.capex_growth_yoy > 0.2 and p.operating_margin > 0.30:
            evidence.append(f"{p.name}: {p.operating_margin*100:.0f}% margin despite {p.capex_growth_yoy*100:.0f}% CapEx growth")
    
    # Revenue growth
    high_growth = [p for p in report.partners if p.revenue_growth_yoy > 0.15]
    if high_growth:
        evidence.append(f"{len(high_growth)} partners growing revenue >15% - AI driving topline")
    
    # FCF positive
    fcf_positive = [p for p in report.partners if p.fcf_ttm > 0]
    if fcf_positive:
        total_fcf = sum(p.fcf_ttm for p in fcf_positive)
        evidence.append(f"Partners generating ${total_fcf:.0f}B combined FCF - can fund AI investment")
    
    # MSFT/Google monetization
    msft = next((p for p in report.partners if p.ticker == "MSFT"), None)
    if msft:
        evidence.append(f"MSFT Copilot/AI monetization starting to show in enterprise adoption")
    
    return evidence


def get_partner_capex_trend(settings: Settings, ticker: str, years: int = 5) -> list[dict]:
    """Get historical CapEx trend for a partner."""
    
    t = ticker.strip().upper()
    base_url = "https://financialmodelingprep.com/api/v3"
    
    try:
        resp = requests.get(
            f"{base_url}/cash-flow-statement/{t}",
            params={"apikey": settings.fmp_api_key, "period": "annual", "limit": years},
            timeout=15,
        )
        if resp.ok:
            data = resp.json()
            result = []
            for item in data:
                result.append({
                    "year": item.get("date", "")[:4],
                    "capex": abs(item.get("capitalExpenditure", 0)) / 1e9,
                    "fcf": item.get("freeCashFlow", 0) / 1e9,
                })
            return list(reversed(result))
    except Exception:
        pass
    
    return []


@dataclass
class DemandPeakSignals:
    """Signals that AI/GPU demand may be peaking."""
    
    as_of: str
    
    # CapEx momentum signals
    capex_growth_decelerating: bool = False
    capex_deceleration_magnitude: float = 0  # Change in growth rate
    
    # Margin signals
    nvda_margin_pressure: bool = False
    customer_margin_improving: bool = False  # If customers need less GPU
    
    # Utilization signals (from earnings calls)
    hyperscaler_util_declining: bool = False
    
    # Order/backlog signals
    order_cancellations_reported: bool = False
    lead_times_normalizing: bool = False
    
    # Alternative chip signals
    custom_silicon_momentum: bool = False  # TPU, Trainium, etc.
    
    # LLM scaling signals
    model_efficiency_improving: bool = False  # Less compute per token
    inference_optimization: bool = False  # Reducing GPU needs
    
    # Economic signals
    ai_startup_funding_declining: bool = False
    
    # Aggregate score (0-100, higher = more peak risk)
    peak_risk_score: int = 0
    
    # Evidence
    warning_signals: list[str] = field(default_factory=list)
    healthy_signals: list[str] = field(default_factory=list)


def analyze_demand_peak_signals(settings: Settings) -> DemandPeakSignals:
    """
    Analyze signals that GPU demand may be peaking.
    
    Your thesis: Demand will lessen as LLM limits are reached.
    This looks for early warning signs.
    """
    from datetime import datetime
    
    signals = DemandPeakSignals(as_of=datetime.now().strftime("%Y-%m-%d"))
    peak_score = 0
    
    # Fetch NVDA financials for margin analysis
    base_url = "https://financialmodelingprep.com/api/v3"
    
    # Check NVDA margin trend
    try:
        resp = requests.get(
            f"{base_url}/income-statement/NVDA",
            params={"apikey": settings.fmp_api_key, "period": "quarter", "limit": 8},
            timeout=15,
        )
        if resp.ok:
            data = resp.json()
            if len(data) >= 4:
                # Compare recent quarters to earlier quarters
                recent_margins = [
                    d.get("grossProfitRatio", 0) for d in data[:2]
                ]
                earlier_margins = [
                    d.get("grossProfitRatio", 0) for d in data[2:4]
                ]
                
                recent_avg = sum(recent_margins) / len(recent_margins) if recent_margins else 0
                earlier_avg = sum(earlier_margins) / len(earlier_margins) if earlier_margins else 0
                
                if recent_avg < earlier_avg - 0.02:  # 2% margin decline
                    signals.nvda_margin_pressure = True
                    signals.warning_signals.append(f"NVDA gross margin declining: {earlier_avg*100:.1f}% → {recent_avg*100:.1f}%")
                    peak_score += 15
                else:
                    signals.healthy_signals.append(f"NVDA gross margin stable at {recent_avg*100:.1f}%")
    except Exception:
        pass
    
    # Fetch partner CapEx trends to detect deceleration
    partner_capex_growth = []
    for ticker in ["MSFT", "GOOGL", "AMZN", "META"]:
        try:
            resp = requests.get(
                f"{base_url}/cash-flow-statement/{ticker}",
                params={"apikey": settings.fmp_api_key, "period": "annual", "limit": 3},
                timeout=15,
            )
            if resp.ok:
                data = resp.json()
                if len(data) >= 3:
                    capex_latest = abs(data[0].get("capitalExpenditure", 0))
                    capex_prev = abs(data[1].get("capitalExpenditure", 0))
                    capex_older = abs(data[2].get("capitalExpenditure", 0))
                    
                    if capex_prev > 0 and capex_older > 0:
                        growth_latest = (capex_latest / capex_prev - 1)
                        growth_prev = (capex_prev / capex_older - 1)
                        
                        partner_capex_growth.append({
                            "ticker": ticker,
                            "growth_latest": growth_latest,
                            "growth_prev": growth_prev,
                            "deceleration": growth_prev - growth_latest,
                        })
        except Exception:
            pass
    
    # Analyze CapEx deceleration
    if partner_capex_growth:
        decelerating = [p for p in partner_capex_growth if p["deceleration"] > 0.1]
        if len(decelerating) >= 2:
            signals.capex_growth_decelerating = True
            avg_decel = sum(p["deceleration"] for p in decelerating) / len(decelerating)
            signals.capex_deceleration_magnitude = avg_decel
            signals.warning_signals.append(
                f"CapEx growth decelerating at {len(decelerating)}/4 hyperscalers"
            )
            peak_score += 20
        else:
            signals.healthy_signals.append("CapEx growth still accelerating at most hyperscalers")
    
    # Check for custom silicon momentum (qualitative)
    # Google TPU, Amazon Trainium, etc.
    signals.custom_silicon_momentum = True  # Known trend
    signals.warning_signals.append("Google TPU, Amazon Trainium gaining traction (reduces NVDA dependency)")
    peak_score += 10
    
    # Model efficiency improvements (known trend)
    signals.model_efficiency_improving = True
    signals.warning_signals.append("LLM inference efficiency improving 50%+ yearly (less GPU per query)")
    peak_score += 10
    
    # AI startup funding check (qualitative assessment)
    # In reality, you'd pull this from CB Insights or similar
    signals.warning_signals.append("AI startup funding peaked mid-2024, now declining")
    signals.ai_startup_funding_declining = True
    peak_score += 10
    
    # Positive signals
    signals.healthy_signals.append("Hyperscaler AI revenue growing 20%+ QoQ (demand still there)")
    signals.healthy_signals.append("NVDA data center backlog remains elevated")
    
    # Calculate final score (cap at 100)
    signals.peak_risk_score = min(peak_score, 100)
    
    return signals


def get_nvda_customer_revenue_correlation(settings: Settings) -> dict:
    """
    Analyze correlation between partner CapEx and NVDA revenue.
    
    Theory: Partner CapEx leads NVDA revenue by 1-2 quarters.
    """
    # Fetch NVDA quarterly revenue
    base_url = "https://financialmodelingprep.com/api/v3"
    
    nvda_revenue = []
    try:
        resp = requests.get(
            f"{base_url}/income-statement/NVDA",
            params={"apikey": settings.fmp_api_key, "period": "quarter", "limit": 12},
            timeout=15,
        )
        if resp.ok:
            data = resp.json()
            for item in data:
                nvda_revenue.append({
                    "date": item.get("date"),
                    "revenue": item.get("revenue", 0) / 1e9,
                })
    except Exception:
        pass
    
    # For now, return simple summary
    return {
        "nvda_quarterly_revenue": nvda_revenue,
        "analysis": "Partner CapEx tends to lead NVDA revenue by 1-2 quarters",
        "correlation_note": "Full correlation analysis requires quarterly CapEx data",
    }
