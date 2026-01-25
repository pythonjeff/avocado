"""
Regime domain utilities for the LOX FUND Dashboard.
Handles classification of market regimes across multiple domains.
"""
import requests
from datetime import datetime, timezone


def get_regime_domains_data(settings):
    """Fetch regime status for each domain using available modules."""
    domains = {}
    
    if not settings:
        return {"domains": domains, "error": "Settings not available"}
    
    # Funding regime
    domains["funding"] = _get_funding_regime(settings)
    
    # USD regime (DXY)
    domains["usd"] = _get_usd_regime(settings)
    
    # Commodities regime (Gold price)
    domains["commod"] = _get_commodities_regime(settings)
    
    # Volatility regime
    domains["volatility"] = _get_volatility_regime(settings)
    
    # Housing regime (30Y mortgage rate)
    domains["housing"] = _get_housing_regime(settings)
    
    # Crypto regime (BTC price)
    domains["crypto"] = _get_crypto_regime(settings)
    
    return {
        "domains": domains,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _get_funding_regime(settings):
    """Get funding/liquidity regime status."""
    try:
        from ai_options_trader.funding.signals import build_funding_state
        from ai_options_trader.funding.regime import classify_funding_regime
        
        state = build_funding_state(settings=settings, start_date="2020-01-01", refresh=False)
        regime = classify_funding_regime(state.inputs)
        label = regime.label or regime.name
        
        color = "green" if any(x in label.lower() for x in ["normal", "easy", "benign"]) else \
                "red" if any(x in label.lower() for x in ["stress", "tight", "crisis"]) else "yellow"
        
        return {"label": label.upper(), "color": color}
    except Exception as e:
        print(f"[Regimes] Funding error: {e}")
        return {"label": "N/A", "color": "gray"}


def _get_usd_regime(settings):
    """
    Get USD regime based on DXY (Dollar Index).
    Post-2020 context: DXY ranged 89 (Jan 2021) to 114 (Sep 2022)
    """
    try:
        if not getattr(settings, 'FMP_API_KEY', None):
            return {"label": "N/A", "color": "gray"}
        
        url = "https://financialmodelingprep.com/api/v3/quote/DX-Y.NYB"
        resp = requests.get(url, params={"apikey": settings.FMP_API_KEY}, timeout=10)
        data = resp.json()
        
        if not (isinstance(data, list) and data):
            return {"label": "N/A", "color": "gray"}
        
        dxy = data[0].get("price", 0)
        
        # Post-2020 DXY thresholds
        if dxy >= 108:
            color = "red"  # Extreme = headwind for EM/commodities
        elif dxy >= 103:
            color = "yellow"
        elif dxy >= 95:
            color = "yellow"
        else:
            color = "yellow"  # Weak USD is neither universally good nor bad
        
        return {"label": f"DXY {dxy:.1f}", "color": color}
    except Exception as e:
        print(f"[Regimes] USD error: {e}")
        return {"label": "N/A", "color": "gray"}


def _get_commodities_regime(settings):
    """
    Get commodities regime based on gold price.
    Post-2020: Gold ranged $1,680 (Mar 2020) to ATH $2,700+ (Oct 2024)
    """
    try:
        from ai_options_trader.commodities.signals import build_commodities_state
        
        state = build_commodities_state(settings=settings, start_date="2020-01-01", refresh=False)
        gold_price = state.inputs.gold
        
        if gold_price is not None:
            # Post-2020 gold thresholds
            if gold_price >= 2400:
                color = "red"  # Historic highs, inflation/fear bid
            elif gold_price >= 2000:
                color = "yellow"  # Elevated but not extreme
            else:
                color = "green"  # Relatively low, deflationary
            
            return {"label": f"GOLD ${gold_price:,.0f}", "color": color}
        
        # Fallback to regime classifier
        from ai_options_trader.commodities.regime import classify_commodities_regime
        regime = classify_commodities_regime(state.inputs)
        label = regime.label or regime.name
        color = "red" if any(x in label.lower() for x in ["spike", "inflation"]) else \
                "green" if "disinflation" in label.lower() else "yellow"
        
        return {"label": label.upper(), "color": color}
    except Exception as e:
        print(f"[Regimes] Commodities error: {e}")
        return {"label": "N/A", "color": "gray"}


def _get_volatility_regime(settings):
    """Get volatility regime status."""
    try:
        from ai_options_trader.volatility.signals import build_volatility_state
        from ai_options_trader.volatility.regime import classify_volatility_regime
        
        state = build_volatility_state(settings=settings, start_date="2020-01-01", refresh=False)
        regime = classify_volatility_regime(state.inputs)
        label = regime.label or regime.name
        
        color = "green" if any(x in label.lower() for x in ["low", "calm", "complacent"]) else \
                "red" if any(x in label.lower() for x in ["high", "stress", "spike", "crisis"]) else "yellow"
        
        return {"label": label.upper(), "color": color}
    except Exception as e:
        print(f"[Regimes] Volatility error: {e}")
        return {"label": "N/A", "color": "gray"}


def _get_housing_regime(settings):
    """
    Get housing regime based on 30Y mortgage rate.
    Post-2020 thresholds: <5% green, 5-6.5% yellow, >6.5% red
    """
    try:
        from ai_options_trader.housing.signals import build_housing_state
        
        state = build_housing_state(settings=settings, start_date="2020-01-01", refresh=False)
        mortgage_rate = state.inputs.mortgage_30y
        
        if mortgage_rate is not None:
            if mortgage_rate < 5.0:
                color, status = "green", "LOW"
            elif mortgage_rate < 6.5:
                color, status = "yellow", "MODERATE"
            else:
                color, status = "red", "ELEVATED"
            
            return {"label": f"{status} ({mortgage_rate:.2f}%)", "color": color}
        
        # Fallback to mortgage spread
        spread = state.inputs.mortgage_spread
        if spread is not None:
            if spread > 2.5:
                return {"label": f"STRESSED ({spread:.1f}% sprd)", "color": "red"}
            elif spread < 1.8:
                return {"label": f"HEALTHY ({spread:.1f}% sprd)", "color": "green"}
            else:
                return {"label": f"NORMAL ({spread:.1f}% sprd)", "color": "yellow"}
        
        return {"label": "N/A", "color": "gray"}
    except Exception as e:
        print(f"[Regimes] Housing error: {e}")
        return {"label": "N/A", "color": "gray"}


def _get_crypto_regime(settings):
    """
    Get crypto regime based on BTC price.
    Post-2024 thresholds (ATH ~$108K): >$100K green, $70-100K yellow, <$70K red
    """
    try:
        if not getattr(settings, 'FMP_API_KEY', None):
            return {"label": "N/A", "color": "gray"}
        
        url = "https://financialmodelingprep.com/api/v3/quote/BTCUSD"
        resp = requests.get(url, params={"apikey": settings.FMP_API_KEY}, timeout=10)
        data = resp.json()
        
        if not (isinstance(data, list) and data):
            return {"label": "N/A", "color": "gray"}
        
        btc_price = data[0].get("price", 0)
        change_pct = data[0].get("changesPercentage", 0)
        
        # Daily momentum override for big moves
        if change_pct > 5:
            color = "green"
        elif change_pct < -5:
            color = "red"
        elif btc_price >= 100000:
            color = "green"  # ATH zone
        elif btc_price >= 70000:
            color = "yellow"  # Consolidation
        elif btc_price >= 50000:
            color = "red"  # Pullback
        else:
            color = "red"  # Bear market
        
        return {"label": f"BTC ${btc_price/1000:.0f}K", "color": color}
    except Exception as e:
        print(f"[Regimes] Crypto error: {e}")
        return {"label": "N/A", "color": "gray"}


def get_regime_label(vix_val, hy_val):
    """Determine overall market regime from VIX and HY spreads."""
    if vix_val is None:
        return "UNKNOWN"
    if vix_val > 25 or (hy_val and hy_val > 400):
        return "RISK-OFF"
    elif vix_val > 18 or (hy_val and hy_val > 350):
        return "CAUTIOUS"
    else:
        return "RISK-ON"
