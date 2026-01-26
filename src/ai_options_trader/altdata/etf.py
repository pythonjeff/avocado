"""ETF-specific data fetching and analysis.

This module provides functions to detect ETFs, fetch holdings, performance,
fund flow signals, and institutional holders.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import requests

if TYPE_CHECKING:
    from ai_options_trader.config import Settings
    from ai_options_trader.altdata.fmp import CompanyProfile


@dataclass
class ETFData:
    """Consolidated ETF data container."""
    
    is_etf: bool = False
    etf_info: dict | None = None  # From /etf-info endpoint
    holdings: list[dict] = field(default_factory=list)  # Top holdings
    performance: dict = field(default_factory=dict)  # 1W, 1M, 3M, YTD, 1Y returns
    flow_signal: dict | None = None  # Volume trend proxy for fund flows
    institutional_holders: list[dict] = field(default_factory=list)  # Top institutional holders


def detect_etf(profile: "CompanyProfile | None") -> bool:
    """
    Detect if a ticker is an ETF based on profile data.
    
    Checks:
    - profile.is_etf attribute if available
    - Industry/sector containing 'etf'
    - Company name containing ETF indicators (iShares, Vanguard, SPDR, etc.)
    """
    if not profile:
        return False
    
    # Check is_etf attribute
    if hasattr(profile, 'is_etf') and profile.is_etf:
        return True
    
    # Check industry/sector
    if profile.industry and 'etf' in profile.industry.lower():
        return True
    if profile.sector and 'etf' in profile.sector.lower():
        return True
    
    # Check company name for common ETF indicators
    if profile.company_name:
        name_lower = profile.company_name.lower()
        etf_keywords = [
            'etf', ' fund', 'trust', 'ishares', 'vanguard', 'spdr',
            'proshares', 'invesco', 'wisdomtree', 'schwab', 'direxion'
        ]
        if any(kw in name_lower for kw in etf_keywords):
            return True
    
    return False


def fetch_etf_holdings(
    settings: "Settings",
    ticker: str,
    top_n: int = 10,
) -> tuple[bool, list[dict]]:
    """
    Fetch ETF holdings from FMP.
    
    Returns:
        Tuple of (is_etf, holdings_list)
        If holdings are returned, the ticker is definitely an ETF.
    """
    try:
        url = f"https://financialmodelingprep.com/api/v3/etf-holder/{ticker}"
        resp = requests.get(
            url,
            params={"apikey": settings.fmp_api_key},
            timeout=10,
        )
        if resp.ok:
            holdings = resp.json()
            if holdings and isinstance(holdings, list) and len(holdings) > 0:
                return True, holdings[:top_n]
    except Exception:
        pass
    
    return False, []


def fetch_etf_info(settings: "Settings", ticker: str) -> dict | None:
    """Fetch ETF-specific info (expense ratio, holdings count, etc.) from FMP."""
    try:
        url = "https://financialmodelingprep.com/api/v3/etf-info"
        resp = requests.get(
            url,
            params={"apikey": settings.fmp_api_key, "symbol": ticker},
            timeout=10,
        )
        if resp.ok:
            data = resp.json()
            if data and isinstance(data, list) and len(data) > 0:
                return data[0]
    except Exception:
        pass
    
    return None


def fetch_etf_performance(
    settings: "Settings",
    ticker: str,
) -> tuple[dict, dict | None]:
    """
    Calculate ETF performance returns and fund flow signals.
    
    Returns:
        Tuple of (performance_dict, flow_signal_dict)
        
        performance_dict: {
            "1W": float,  # 1-week return %
            "1M": float,  # 1-month return %
            "3M": float,  # 3-month return %
            "YTD": float, # Year-to-date return %
            "1Y": float,  # 1-year return %
        }
        
        flow_signal_dict: {
            "volume_trend": float,  # % change in avg volume (20d vs prior 20d)
            "recent_avg_vol": float,
            "prior_avg_vol": float,
        }
    """
    performance = {}
    flow_signal = None
    
    try:
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
        
        url = f"https://financialmodelingprep.com/api/v3/historical-price-full/{ticker}"
        resp = requests.get(
            url,
            params={
                "apikey": settings.fmp_api_key,
                "from": start_date,
                "to": end_date,
            },
            timeout=15,
        )
        
        if not resp.ok:
            return performance, flow_signal
        
        hist_data = resp.json()
        prices = hist_data.get("historical", [])
        
        if not prices:
            return performance, flow_signal
        
        # Prices are newest first
        current_price = prices[0].get("close", 0)
        if not current_price:
            return performance, flow_signal
        
        def find_price_at_days_ago(days: int) -> float | None:
            target_date = datetime.now() - timedelta(days=days)
            for p in prices:
                p_date = datetime.strptime(p["date"], "%Y-%m-%d")
                if p_date <= target_date:
                    return p.get("close")
            return None
        
        # Calculate returns
        price_1w = find_price_at_days_ago(7)
        price_1m = find_price_at_days_ago(30)
        price_3m = find_price_at_days_ago(90)
        price_1y = find_price_at_days_ago(365)
        
        # YTD - find price at start of year
        price_ytd = None
        year_start = datetime(datetime.now().year, 1, 1)
        for p in prices:
            p_date = datetime.strptime(p["date"], "%Y-%m-%d")
            if p_date <= year_start:
                price_ytd = p.get("close")
                break
        
        if price_1w:
            performance["1W"] = ((current_price - price_1w) / price_1w) * 100
        if price_1m:
            performance["1M"] = ((current_price - price_1m) / price_1m) * 100
        if price_3m:
            performance["3M"] = ((current_price - price_3m) / price_3m) * 100
        if price_ytd:
            performance["YTD"] = ((current_price - price_ytd) / price_ytd) * 100
        if price_1y:
            performance["1Y"] = ((current_price - price_1y) / price_1y) * 100
        
        # Calculate fund flow signal from volume trend
        recent_volumes = [p.get("volume", 0) for p in prices[:20]]
        older_volumes = [p.get("volume", 0) for p in prices[20:40]]
        
        if recent_volumes and older_volumes:
            avg_recent = sum(recent_volumes) / len(recent_volumes)
            avg_older = sum(older_volumes) / len(older_volumes)
            if avg_older > 0:
                volume_change_pct = ((avg_recent - avg_older) / avg_older) * 100
                flow_signal = {
                    "volume_trend": volume_change_pct,
                    "recent_avg_vol": avg_recent,
                    "prior_avg_vol": avg_older,
                }
    
    except Exception:
        pass
    
    return performance, flow_signal


def fetch_institutional_holders(
    settings: "Settings",
    ticker: str,
    top_n: int = 10,
) -> list[dict]:
    """
    Fetch top institutional holders for a ticker.
    
    Returns list of holders sorted by shares (descending), filtered to those
    with positive share counts.
    
    Each holder dict contains:
    - holder: str (institution name)
    - shares: int
    - change: int (change in shares)
    - dateReported: str
    """
    try:
        url = f"https://financialmodelingprep.com/api/v3/institutional-holder/{ticker}"
        resp = requests.get(
            url,
            params={"apikey": settings.fmp_api_key},
            timeout=10,
        )
        if resp.ok:
            data = resp.json()
            if data and isinstance(data, list):
                # Sort by shares and filter to those with holdings
                holders = sorted(
                    [h for h in data if h.get('shares', 0) > 0],
                    key=lambda x: x.get('shares', 0),
                    reverse=True,
                )
                return holders[:top_n]
    except Exception:
        pass
    
    return []


def fetch_etf_data(
    settings: "Settings",
    ticker: str,
    profile: "CompanyProfile | None" = None,
) -> ETFData:
    """
    Fetch all ETF-related data for a ticker.
    
    This is the main entry point that aggregates:
    - ETF detection
    - Holdings
    - ETF info (expense ratio, etc.)
    - Performance & fund flows
    - Institutional holders
    
    Args:
        settings: Application settings with API keys
        ticker: Ticker symbol (will be uppercased)
        profile: Optional CompanyProfile (avoids re-fetching if already available)
    
    Returns:
        ETFData dataclass with all available data
    """
    ticker = ticker.upper()
    result = ETFData()
    
    # Step 1: Detect ETF from profile
    result.is_etf = detect_etf(profile)
    
    # Step 2: Try to fetch holdings (definitive ETF detection)
    holdings_is_etf, holdings = fetch_etf_holdings(settings, ticker)
    if holdings_is_etf:
        result.is_etf = True
        result.holdings = holdings
    
    # If not an ETF, return early
    if not result.is_etf:
        return result
    
    # Step 3: Fetch ETF-specific info
    result.etf_info = fetch_etf_info(settings, ticker)
    
    # Step 4: Fetch performance and flow signals
    result.performance, result.flow_signal = fetch_etf_performance(settings, ticker)
    
    # Step 5: Fetch institutional holders
    result.institutional_holders = fetch_institutional_holders(settings, ticker)
    
    return result


def get_flow_signal_label(flow_signal: dict | None) -> tuple[str, str]:
    """
    Get human-readable flow signal label and color.
    
    Returns:
        Tuple of (label, color) where:
        - label: "INFLOWS", "OUTFLOWS", or "NEUTRAL"
        - color: "green", "red", or "yellow"
    """
    if not flow_signal:
        return "UNKNOWN", "dim"
    
    vol_trend = flow_signal.get("volume_trend", 0)
    
    if vol_trend > 10:
        return "INFLOWS", "green"
    elif vol_trend < -10:
        return "OUTFLOWS", "red"
    else:
        return "NEUTRAL", "yellow"


def format_holding_name(holding: dict, max_length: int = 40) -> str:
    """
    Get the display name for an ETF holding.
    
    Uses 'asset' field, falling back to 'name' if asset is empty.
    Truncates long names.
    """
    name = holding.get('asset') or holding.get('name') or 'Unknown'
    if len(name) > max_length:
        return name[:max_length - 3] + "..."
    return name
