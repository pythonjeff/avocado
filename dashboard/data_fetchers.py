"""
Market data fetching utilities for the LOX FUND Dashboard.
Handles VIX, HY OAS, yields, and benchmark returns.
"""
import pandas as pd
import requests
from datetime import datetime, timezone

# Fund inception date - used across all benchmark comparisons
FUND_INCEPTION_DATE = "2026-01-09"


def get_hy_oas(settings):
    """Get HY OAS (credit spreads) - key for HYG puts."""
    try:
        if not settings or not getattr(settings, 'FRED_API_KEY', None):
            return None
        
        from ai_options_trader.data.fred import FredClient
        fred = FredClient(api_key=settings.FRED_API_KEY)
        df = fred.fetch_series(series_id="BAMLH0A0HYM2", start_date="2018-01-01", refresh=False)
        
        if df is None or df.empty:
            return None
        
        df = df.sort_values("date")
        df = df[df["value"].notna()]
        if df.shape[0] < 2:
            return None
        
        series = pd.Series(df["value"].values, index=pd.to_datetime(df["date"]))
        last = float(series.iloc[-1])
        last_bps = last * 100.0  # Convert to bps
        asof = str(series.index[-1].date())
        
        # Target: >325bp for credit stress (HYG puts pay)
        in_range = last_bps >= 325
        context = "Credit stress → HYG puts pay" if in_range else "Spreads tight → waiting"
        
        return {
            "value": last_bps, 
            "asof": asof, 
            "label": "HY OAS", 
            "unit": "bps",
            "target": ">325bp",
            "in_range": in_range,
            "context": context,
            "description": "High-yield credit spread (ICE BofA Index)"
        }
    except Exception:
        return None


def get_vix(settings):
    """Get VIX level - key for volatility hedges."""
    try:
        if not settings or not getattr(settings, 'FMP_API_KEY', None):
            return None
        
        url = "https://financialmodelingprep.com/api/v3/quote/%5EVIX"
        resp = requests.get(url, params={"apikey": settings.FMP_API_KEY}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        
        if not (isinstance(data, list) and data and data[0].get("price")):
            return None
        
        vix_value = float(data[0].get("price", 0))
        ts = data[0].get("timestamp")
        asof = _format_timestamp(ts)
        
        # Target: >20 for volatility hedges to pay
        in_range = vix_value >= 20
        context = "Elevated vol → hedges pay" if in_range else "Low vol → hedges wait"
        
        return {
            "value": vix_value, 
            "asof": asof, 
            "label": "VIX", 
            "unit": "",
            "target": ">20",
            "in_range": in_range,
            "context": context,
            "description": "CBOE Volatility Index (S&P 500 implied vol)"
        }
    except Exception as e:
        print(f"VIX fetch error: {e}")
        return None


def get_10y_yield(settings):
    """Get 10Y Treasury yield - key for TLT calls."""
    try:
        if not settings or not getattr(settings, 'FMP_API_KEY', None):
            return None
        
        url = "https://financialmodelingprep.com/api/v3/quote/%5ETNX"
        resp = requests.get(url, params={"apikey": settings.FMP_API_KEY}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        
        if not (isinstance(data, list) and data and data[0].get("price")):
            return None
        
        price = float(data[0].get("price", 0))
        # ^TNX is 10x the yield (e.g., 422.7 -> 4.227%)
        yield_pct = price / 100.0 if price > 20 else price
        asof = _format_timestamp(data[0].get("timestamp"))
        
        # Determine context based on yield level
        in_range = yield_pct >= 4.5
        if yield_pct >= 4.5:
            context = "High yields → main portfolio (inflation persistent)"
        elif yield_pct < 4.0:
            context = "Yields falling → TLT hedge pays (inflation easing)"
        else:
            context = "Yields neutral → mixed signals"
        
        return {
            "value": yield_pct, 
            "asof": asof, 
            "label": "10Y Yield", 
            "unit": "%",
            "target": ">4.5% (main) | <4.0% (TLT hedge)",
            "in_range": in_range,
            "context": context,
            "description": "10-Year Treasury yield (^TNX)"
        }
    except Exception as e:
        print(f"10Y yield fetch error: {e}")
        return None


def get_sp500_return_since_inception(settings):
    """Get S&P 500 return since fund inception for benchmark comparison."""
    return _get_asset_return_since_inception(settings, "SPY", "S&P 500")


def get_btc_return_since_inception(settings):
    """Get BTC return since fund inception for benchmark comparison."""
    return _get_asset_return_since_inception(settings, "BTCUSD", "BTC")


def _get_asset_return_since_inception(settings, symbol: str, name: str):
    """Generic helper to get asset return since fund inception."""
    try:
        if not settings or not getattr(settings, 'FMP_API_KEY', None):
            return None
        
        url = f"https://financialmodelingprep.com/api/v3/historical-price-full/{symbol}"
        resp = requests.get(url, params={
            "apikey": settings.FMP_API_KEY,
            "from": FUND_INCEPTION_DATE,
        }, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        
        if not isinstance(data, dict) or 'historical' not in data:
            return None
        
        historical = data['historical']
        if not historical or len(historical) < 2:
            return None
        
        # historical is sorted newest first
        current_price = historical[0].get('close', 0)
        inception_price = historical[-1].get('close', 0)
        
        if inception_price <= 0:
            return None
        
        return ((current_price - inception_price) / inception_price) * 100
    
    except Exception as e:
        print(f"{name} return fetch error: {e}")
        return None


def _format_timestamp(ts) -> str:
    """Format a Unix timestamp to readable time string."""
    if not ts:
        return "Live"
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%H:%M UTC")
    except Exception:
        return "Live"
