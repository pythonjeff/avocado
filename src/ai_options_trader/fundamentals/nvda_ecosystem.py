"""
NVIDIA Ecosystem Basket

Comprehensive list of all public companies with direct NVDA relationships:
- Companies NVDA supplies GPUs to (customers)
- Companies NVDA has invested in directly
- Companies in NVDA supply chain (suppliers)
- Strategic partners
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Literal
from datetime import datetime
import requests

from ai_options_trader.config import Settings


# Complete NVDA ecosystem with relationship types
NVDA_ECOSYSTEM = {
    # =========================================
    # NVDA DIRECT INVESTMENTS (Equity Stakes)
    # =========================================
    "CRWV": {
        "name": "CoreWeave",
        "relationship": "investment",
        "category": "gpu_cloud",
        "nvda_stake_est_pct": 7,  # Estimated 5-10%
        "description": "GPU cloud provider, NVDA invested in Series B and debt rounds",
        "revenue_from_nvda": False,
        "revenue_to_nvda": True,  # Buys NVDA GPUs
        "nvda_revenue_impact": "high",
    },
    "ARM": {
        "name": "Arm Holdings",
        "relationship": "investment",
        "category": "chip_ip",
        "nvda_stake_est_pct": 0,  # Attempted acquisition failed, but partnership
        "description": "Chip architecture IP, NVDA uses ARM for Grace CPU",
        "revenue_from_nvda": True,  # Licensing fees
        "revenue_to_nvda": False,
        "nvda_revenue_impact": "low",
    },
    "SNOW": {
        "name": "Snowflake",
        "relationship": "investment",
        "category": "data_ai",
        "nvda_stake_est_pct": 1,  # Small stake from IPO
        "description": "Data cloud, NVDA invested at IPO, AI/ML partnership",
        "revenue_from_nvda": False,
        "revenue_to_nvda": False,
        "nvda_revenue_impact": "low",
    },
    "PATH": {
        "name": "UiPath",
        "relationship": "investment",
        "category": "automation",
        "nvda_stake_est_pct": 1,
        "description": "RPA/automation, NVDA invested for AI automation",
        "revenue_from_nvda": False,
        "revenue_to_nvda": False,
        "nvda_revenue_impact": "low",
    },
    "RBLX": {
        "name": "Roblox",
        "relationship": "investment",
        "category": "metaverse",
        "nvda_stake_est_pct": 0.5,
        "description": "Metaverse gaming, NVDA invested for Omniverse",
        "revenue_from_nvda": False,
        "revenue_to_nvda": False,
        "nvda_revenue_impact": "low",
    },
    
    # =========================================
    # MAJOR GPU CUSTOMERS (Hyperscalers)
    # =========================================
    "MSFT": {
        "name": "Microsoft",
        "relationship": "customer",
        "category": "hyperscaler",
        "nvda_stake_est_pct": 0,
        "description": "Azure AI, OpenAI partner, largest enterprise AI provider",
        "revenue_from_nvda": False,
        "revenue_to_nvda": True,
        "nvda_revenue_impact": "very_high",
        "nvda_revenue_pct_est": 15,  # Est 15% of NVDA data center rev
    },
    "GOOGL": {
        "name": "Google/Alphabet",
        "relationship": "customer",
        "category": "hyperscaler",
        "nvda_stake_est_pct": 0,
        "description": "GCP AI, Gemini, also develops competing TPUs",
        "revenue_from_nvda": False,
        "revenue_to_nvda": True,
        "nvda_revenue_impact": "high",
        "nvda_revenue_pct_est": 10,
    },
    "AMZN": {
        "name": "Amazon",
        "relationship": "customer",
        "category": "hyperscaler",
        "nvda_stake_est_pct": 0,
        "description": "AWS AI, Bedrock, also develops Trainium/Inferentia",
        "revenue_from_nvda": False,
        "revenue_to_nvda": True,
        "nvda_revenue_impact": "high",
        "nvda_revenue_pct_est": 10,
    },
    "META": {
        "name": "Meta",
        "relationship": "customer",
        "category": "hyperscaler",
        "nvda_stake_est_pct": 0,
        "description": "Llama training, Reality Labs, massive GPU buyer",
        "revenue_from_nvda": False,
        "revenue_to_nvda": True,
        "nvda_revenue_impact": "very_high",
        "nvda_revenue_pct_est": 12,
    },
    "ORCL": {
        "name": "Oracle",
        "relationship": "customer",
        "category": "hyperscaler",
        "nvda_stake_est_pct": 0,
        "description": "OCI AI, aggressive cloud AI expansion",
        "revenue_from_nvda": False,
        "revenue_to_nvda": True,
        "nvda_revenue_impact": "high",
        "nvda_revenue_pct_est": 5,
    },
    
    # =========================================
    # AI COMPANY CUSTOMERS
    # =========================================
    "TSLA": {
        "name": "Tesla",
        "relationship": "customer",
        "category": "ai_company",
        "nvda_stake_est_pct": 0,
        "description": "FSD training, also developing Dojo chips",
        "revenue_from_nvda": False,
        "revenue_to_nvda": True,
        "nvda_revenue_impact": "medium",
        "nvda_revenue_pct_est": 3,
    },
    "PLTR": {
        "name": "Palantir",
        "relationship": "customer",
        "category": "ai_company",
        "nvda_stake_est_pct": 0,
        "description": "AI platform, uses NVDA for AIP/Foundry",
        "revenue_from_nvda": False,
        "revenue_to_nvda": True,
        "nvda_revenue_impact": "low",
    },
    
    # =========================================
    # GPU CLOUD PROVIDERS (Buy NVDA GPUs)
    # =========================================
    "LLAP": {
        "name": "Terran Orbital",  # Note: Lambda Labs is private
        "relationship": "ecosystem",
        "category": "gpu_cloud",
        "nvda_stake_est_pct": 0,
        "description": "Satellite - placeholder for GPU cloud sector",
        "revenue_from_nvda": False,
        "revenue_to_nvda": False,
        "nvda_revenue_impact": "none",
    },
    
    # =========================================
    # NVDA SUPPLY CHAIN (Suppliers TO NVDA)
    # =========================================
    "TSM": {
        "name": "Taiwan Semiconductor",
        "relationship": "supplier",
        "category": "foundry",
        "nvda_stake_est_pct": 0,
        "description": "Manufactures all NVDA chips, critical supplier",
        "revenue_from_nvda": True,
        "revenue_to_nvda": False,
        "nvda_revenue_impact": "none",
        "pct_revenue_from_nvda_est": 10,  # NVDA is ~10% of TSMC revenue
    },
    "ASML": {
        "name": "ASML",
        "relationship": "supplier",
        "category": "equipment",
        "nvda_stake_est_pct": 0,
        "description": "EUV lithography machines, enables TSMC to make NVDA chips",
        "revenue_from_nvda": False,  # Indirect via TSMC
        "revenue_to_nvda": False,
        "nvda_revenue_impact": "none",
    },
    "KLAC": {
        "name": "KLA Corporation",
        "relationship": "supplier",
        "category": "equipment",
        "nvda_stake_est_pct": 0,
        "description": "Chip inspection/metrology, semiconductor equipment",
        "revenue_from_nvda": False,
        "revenue_to_nvda": False,
        "nvda_revenue_impact": "none",
    },
    "LRCX": {
        "name": "Lam Research",
        "relationship": "supplier",
        "category": "equipment",
        "nvda_stake_est_pct": 0,
        "description": "Wafer fabrication equipment",
        "revenue_from_nvda": False,
        "revenue_to_nvda": False,
        "nvda_revenue_impact": "none",
    },
    "AMAT": {
        "name": "Applied Materials",
        "relationship": "supplier",
        "category": "equipment",
        "nvda_stake_est_pct": 0,
        "description": "Semiconductor equipment, materials engineering",
        "revenue_from_nvda": False,
        "revenue_to_nvda": False,
        "nvda_revenue_impact": "none",
    },
    "MU": {
        "name": "Micron",
        "relationship": "supplier",
        "category": "memory",
        "nvda_stake_est_pct": 0,
        "description": "HBM memory for GPUs, critical component",
        "revenue_from_nvda": True,
        "revenue_to_nvda": False,
        "nvda_revenue_impact": "none",
        "pct_revenue_from_nvda_est": 8,
    },
    "SKHHY": {
        "name": "SK Hynix",
        "relationship": "supplier",
        "category": "memory",
        "nvda_stake_est_pct": 0,
        "description": "HBM memory supplier, largest HBM producer",
        "revenue_from_nvda": True,
        "revenue_to_nvda": False,
        "nvda_revenue_impact": "none",
        "pct_revenue_from_nvda_est": 15,
    },
    "AVGO": {
        "name": "Broadcom",
        "relationship": "partner",
        "category": "networking",
        "nvda_stake_est_pct": 0,
        "description": "Networking chips, also competitor in custom AI chips",
        "revenue_from_nvda": False,
        "revenue_to_nvda": False,
        "nvda_revenue_impact": "none",
    },
    "MRVL": {
        "name": "Marvell",
        "relationship": "partner",
        "category": "networking",
        "nvda_stake_est_pct": 0,
        "description": "Data center networking, storage controllers",
        "revenue_from_nvda": False,
        "revenue_to_nvda": False,
        "nvda_revenue_impact": "none",
    },
    
    # =========================================
    # COMPETITORS (Track for comparison)
    # =========================================
    "AMD": {
        "name": "AMD",
        "relationship": "competitor",
        "category": "gpu",
        "nvda_stake_est_pct": 0,
        "description": "MI300 GPUs, main GPU competitor",
        "revenue_from_nvda": False,
        "revenue_to_nvda": False,
        "nvda_revenue_impact": "none",
    },
    "INTC": {
        "name": "Intel",
        "relationship": "competitor",
        "category": "gpu",
        "nvda_stake_est_pct": 0,
        "description": "Gaudi accelerators, x86 CPUs, foundry aspirations",
        "revenue_from_nvda": False,
        "revenue_to_nvda": False,
        "nvda_revenue_impact": "none",
    },
    
    # =========================================
    # DATA CENTER / AI INFRASTRUCTURE
    # =========================================
    "SMCI": {
        "name": "Super Micro Computer",
        "relationship": "partner",
        "category": "servers",
        "nvda_stake_est_pct": 0,
        "description": "AI server manufacturer, major NVDA GPU integrator",
        "revenue_from_nvda": False,  # Buys from NVDA and integrates
        "revenue_to_nvda": True,  # Indirectly - drives GPU sales
        "nvda_revenue_impact": "medium",
    },
    "DELL": {
        "name": "Dell Technologies",
        "relationship": "partner",
        "category": "servers",
        "nvda_stake_est_pct": 0,
        "description": "Enterprise AI servers, PowerEdge with NVDA GPUs",
        "revenue_from_nvda": False,
        "revenue_to_nvda": True,
        "nvda_revenue_impact": "medium",
    },
    "HPE": {
        "name": "Hewlett Packard Enterprise",
        "relationship": "partner",
        "category": "servers",
        "nvda_stake_est_pct": 0,
        "description": "AI servers, Cray supercomputers with NVDA",
        "revenue_from_nvda": False,
        "revenue_to_nvda": True,
        "nvda_revenue_impact": "medium",
    },
    "VRT": {
        "name": "Vertiv",
        "relationship": "ecosystem",
        "category": "infrastructure",
        "nvda_stake_est_pct": 0,
        "description": "Data center power/cooling, benefits from GPU density",
        "revenue_from_nvda": False,
        "revenue_to_nvda": False,
        "nvda_revenue_impact": "none",
    },
    "ETN": {
        "name": "Eaton",
        "relationship": "ecosystem",
        "category": "infrastructure",
        "nvda_stake_est_pct": 0,
        "description": "Power management, data center electrical",
        "revenue_from_nvda": False,
        "revenue_to_nvda": False,
        "nvda_revenue_impact": "none",
    },
}

# Companies highly dependent on NVDA/AI - would struggle if AI demand fades
# These have NO significant fallback business
NVDA_DEPENDENT_TICKERS = {
    "CRWV": {
        "name": "CoreWeave",
        "dependency": "critical",
        "ai_revenue_pct": 100,  # 100% AI/GPU cloud
        "fallback_business": None,
        "why_dependent": "Entire business is renting NVDA GPUs. No AI demand = no business.",
        "survival_without_nvda": "Would collapse",
    },
    "SMCI": {
        "name": "Super Micro Computer",
        "dependency": "critical",
        "ai_revenue_pct": 70,  # ~70% AI servers
        "fallback_business": "Legacy servers (shrinking)",
        "why_dependent": "Valuation based on AI server growth. Without AI, it's a low-margin server company.",
        "survival_without_nvda": "Stock would crash 70%+, business survives at much lower scale",
    },
    "VRT": {
        "name": "Vertiv",
        "dependency": "high",
        "ai_revenue_pct": 50,  # ~50% AI data center
        "fallback_business": "Traditional data center power/cooling",
        "why_dependent": "AI data centers need 3-5x more cooling. Growth story = AI.",
        "survival_without_nvda": "Would survive but growth story dies",
    },
    "MRVL": {
        "name": "Marvell",
        "dependency": "high",
        "ai_revenue_pct": 40,
        "fallback_business": "Storage, networking (slow growth)",
        "why_dependent": "AI networking (custom silicon, interconnects) is the growth driver.",
        "survival_without_nvda": "Would survive but valuation collapses",
    },
    "ARM": {
        "name": "Arm Holdings",
        "dependency": "high",
        "ai_revenue_pct": 30,
        "fallback_business": "Mobile chip licensing (mature)",
        "why_dependent": "Valuation premium based on AI/data center expansion. Mobile is saturated.",
        "survival_without_nvda": "Survives but trades at much lower multiple",
    },
    "PATH": {
        "name": "UiPath",
        "dependency": "high",
        "ai_revenue_pct": 35,
        "fallback_business": "Legacy RPA (declining)",
        "why_dependent": "AI automation is the entire bull thesis. Legacy RPA is commoditized.",
        "survival_without_nvda": "Survives but growth story gone",
    },
    "SNOW": {
        "name": "Snowflake",
        "dependency": "medium",
        "ai_revenue_pct": 25,
        "fallback_business": "Data warehousing (competitive)",
        "why_dependent": "AI/ML workloads driving new growth. Without AI, it's another cloud database.",
        "survival_without_nvda": "Survives but premium multiple gone",
    },
    "PLTR": {
        "name": "Palantir",
        "dependency": "medium",
        "ai_revenue_pct": 40,
        "fallback_business": "Government contracts (stable)",
        "why_dependent": "AIP (AI Platform) is the commercial growth story.",
        "survival_without_nvda": "Government business survives, commercial growth dies",
    },
}

# Basket definitions for different strategies
NVDA_BASKETS = {
    "all": {
        "name": "Complete NVDA Ecosystem",
        "description": "All companies with NVDA relationships",
        "tickers": list(NVDA_ECOSYSTEM.keys()),
    },
    "investments": {
        "name": "NVDA Direct Investments",
        "description": "Companies NVDA has equity stakes in",
        "tickers": [t for t, v in NVDA_ECOSYSTEM.items() if v["relationship"] == "investment"],
    },
    "customers": {
        "name": "NVDA GPU Customers",
        "description": "Companies that buy NVDA GPUs",
        "tickers": [t for t, v in NVDA_ECOSYSTEM.items() if v.get("revenue_to_nvda", False)],
    },
    "suppliers": {
        "name": "NVDA Supply Chain",
        "description": "Companies that supply to NVDA",
        "tickers": [t for t, v in NVDA_ECOSYSTEM.items() if v["relationship"] == "supplier"],
    },
    "hyperscalers": {
        "name": "Hyperscaler Customers",
        "description": "Big tech GPU buyers",
        "tickers": [t for t, v in NVDA_ECOSYSTEM.items() if v["category"] == "hyperscaler"],
    },
    "bear_thesis": {
        "name": "Bear Thesis Basket",
        "description": "Key tickers for the AI demand bear thesis",
        "tickers": ["CRWV", "MSFT", "META", "ORCL", "TSM", "SMCI"],
    },
    "dependent": {
        "name": "NVDA-Dependent Pure Plays",
        "description": "Companies that NEED NVDA/AI to survive - no fallback business",
        "tickers": list(NVDA_DEPENDENT_TICKERS.keys()),
    },
    "critical": {
        "name": "Critically NVDA-Dependent",
        "description": "Would collapse without NVDA/AI demand",
        "tickers": [t for t, v in NVDA_DEPENDENT_TICKERS.items() if v["dependency"] == "critical"],
    },
}


@dataclass
class EcosystemTicker:
    """A ticker in the NVDA ecosystem."""
    
    ticker: str
    name: str
    relationship: str
    category: str
    
    # NVDA relationship details
    nvda_stake_pct: float = 0
    revenue_to_nvda: bool = False
    revenue_from_nvda: bool = False
    nvda_revenue_impact: str = "none"
    
    # Current market data
    price: float = 0
    market_cap: float = 0  # $B
    
    # Performance
    return_1d: float = 0
    return_1w: float = 0
    return_1m: float = 0
    return_ytd: float = 0
    
    # Correlation with NVDA
    nvda_correlation_30d: float = 0


@dataclass
class EcosystemReport:
    """NVDA ecosystem analysis report."""
    
    as_of: str
    basket_name: str
    
    # Tickers
    tickers: list[EcosystemTicker] = field(default_factory=list)
    
    # NVDA reference
    nvda_price: float = 0
    nvda_return_1d: float = 0
    nvda_return_1m: float = 0
    
    # Basket stats
    avg_return_1d: float = 0
    avg_return_1m: float = 0
    avg_nvda_correlation: float = 0
    
    # Category breakdown
    by_category: dict = field(default_factory=dict)
    by_relationship: dict = field(default_factory=dict)


def get_basket_tickers(basket: str = "all") -> list[str]:
    """Get list of tickers for a specific basket."""
    if basket in NVDA_BASKETS:
        return NVDA_BASKETS[basket]["tickers"]
    return NVDA_BASKETS["all"]["tickers"]


def get_ticker_info(ticker: str) -> dict:
    """Get NVDA ecosystem info for a ticker."""
    return NVDA_ECOSYSTEM.get(ticker.upper(), {})


def build_ecosystem_report(
    settings: Settings,
    basket: str = "all",
) -> EcosystemReport:
    """Build performance report for NVDA ecosystem basket."""
    
    basket_info = NVDA_BASKETS.get(basket, NVDA_BASKETS["all"])
    tickers = basket_info["tickers"]
    
    report = EcosystemReport(
        as_of=datetime.now().strftime("%Y-%m-%d"),
        basket_name=basket_info["name"],
    )
    
    base_url = "https://financialmodelingprep.com/api/v3"
    
    # Fetch NVDA first
    try:
        resp = requests.get(
            f"{base_url}/quote/NVDA",
            params={"apikey": settings.fmp_api_key},
            timeout=15,
        )
        if resp.ok and resp.json():
            nvda = resp.json()[0]
            report.nvda_price = nvda.get("price", 0)
            report.nvda_return_1d = nvda.get("changesPercentage", 0)
    except Exception:
        pass
    
    # Fetch each ticker
    for ticker in tickers:
        info = NVDA_ECOSYSTEM.get(ticker, {})
        
        et = EcosystemTicker(
            ticker=ticker,
            name=info.get("name", ticker),
            relationship=info.get("relationship", "unknown"),
            category=info.get("category", "unknown"),
            nvda_stake_pct=info.get("nvda_stake_est_pct", 0),
            revenue_to_nvda=info.get("revenue_to_nvda", False),
            revenue_from_nvda=info.get("revenue_from_nvda", False),
            nvda_revenue_impact=info.get("nvda_revenue_impact", "none"),
        )
        
        # Fetch quote
        try:
            resp = requests.get(
                f"{base_url}/quote/{ticker}",
                params={"apikey": settings.fmp_api_key},
                timeout=10,
            )
            if resp.ok and resp.json():
                q = resp.json()[0]
                et.price = q.get("price", 0)
                et.market_cap = q.get("marketCap", 0) / 1e9
                et.return_1d = q.get("changesPercentage", 0)
        except Exception:
            pass
        
        report.tickers.append(et)
    
    # Calculate averages
    if report.tickers:
        report.avg_return_1d = sum(t.return_1d for t in report.tickers) / len(report.tickers)
    
    # Group by category
    for t in report.tickers:
        if t.category not in report.by_category:
            report.by_category[t.category] = []
        report.by_category[t.category].append(t.ticker)
        
        if t.relationship not in report.by_relationship:
            report.by_relationship[t.relationship] = []
        report.by_relationship[t.relationship].append(t.ticker)
    
    return report


def get_ecosystem_summary() -> dict:
    """Get summary of NVDA ecosystem."""
    
    summary = {
        "total_tickers": len(NVDA_ECOSYSTEM),
        "by_relationship": {},
        "by_category": {},
        "baskets": list(NVDA_BASKETS.keys()),
    }
    
    for ticker, info in NVDA_ECOSYSTEM.items():
        rel = info["relationship"]
        cat = info["category"]
        
        if rel not in summary["by_relationship"]:
            summary["by_relationship"][rel] = []
        summary["by_relationship"][rel].append(ticker)
        
        if cat not in summary["by_category"]:
            summary["by_category"][cat] = []
        summary["by_category"][cat].append(ticker)
    
    return summary
