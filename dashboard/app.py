"""
LOX FUND Dashboard
Flask app for investor-facing P&L dashboard (updates every 5 minutes).
Palmer analysis is server-cached and refreshes every 30 minutes automatically.
"""
from flask import Flask, render_template, jsonify, request
from datetime import datetime, timezone, timedelta
import sys
import os
import threading
import time
import json

# Add parent directory to path to import lox modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Load .env file explicitly (required for gunicorn)
from dotenv import load_dotenv
env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
load_dotenv(env_path)
print(f"[Dashboard] Loaded .env from: {env_path}")

from ai_options_trader.config import load_settings
from ai_options_trader.data.alpaca import make_clients
from ai_options_trader.data.market import fetch_equity_daily_closes
from ai_options_trader.nav.store import read_nav_sheet
from ai_options_trader.nav.investors import read_investor_flows
from ai_options_trader.utils.occ import parse_occ_option_symbol
import re
import pandas as pd

app = Flask(__name__)

# ============ PALMER CACHE ============
# Server-side cache for Palmer's analysis - users cannot trigger refreshes
PALMER_CACHE = {
    "analysis": None,
    "regime_snapshot": None,
    "timestamp": None,
    "last_refresh": None,
    "traffic_lights": None,
    "prev_traffic_lights": None,  # For change detection
    "regime_changed": False,
    "regime_change_details": None,
}
PALMER_CACHE_LOCK = threading.Lock()
PALMER_REFRESH_INTERVAL = 30 * 60  # 30 minutes in seconds
ADMIN_SECRET = os.environ.get("PALMER_ADMIN_SECRET", "lox-admin-2026")  # Set in env for production


def get_hy_oas():
    """Get HY OAS (credit spreads) - key for HYG puts."""
    try:
        settings = load_settings()
        if not settings or not hasattr(settings, 'FRED_API_KEY') or not settings.FRED_API_KEY:
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
        target = ">325bp"
        in_range = last_bps >= 325
        context = "Credit stress → HYG puts pay" if in_range else "Spreads tight → waiting"
        return {
            "value": last_bps, 
            "asof": asof, 
            "label": "HY OAS", 
            "unit": "bps",
            "target": target,
            "in_range": in_range,
            "context": context,
            "description": "High-yield credit spread (ICE BofA Index)"
        }
    except Exception:
        return None


def get_vix():
    """Get VIX level - key for volatility hedges."""
    try:
        settings = load_settings()
        if not settings or not hasattr(settings, 'FMP_API_KEY') or not settings.FMP_API_KEY:
            return None
        
        import requests
        # Try ^VIX first (CBOE VIX index)
        url = "https://financialmodelingprep.com/api/v3/quote/%5EVIX"
        resp = requests.get(url, params={"apikey": settings.FMP_API_KEY}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list) and data and data[0].get("price"):
            vix_value = float(data[0].get("price", 0))
            ts = data[0].get("timestamp")
            asof = "Live"
            if ts:
                try:
                    from datetime import datetime, timezone
                    asof = datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%H:%M UTC")
                except:
                    pass
            # Target: >20 for volatility hedges to pay
            target = ">20"
            in_range = vix_value >= 20
            context = "Elevated vol → hedges pay" if in_range else "Low vol → hedges wait"
            return {
                "value": vix_value, 
                "asof": asof, 
                "label": "VIX", 
                "unit": "",
                "target": target,
                "in_range": in_range,
                "context": context,
                "description": "CBOE Volatility Index (S&P 500 implied vol)"
            }
        return None
    except Exception as e:
        print(f"VIX fetch error: {e}")
        return None


def get_sp500_return_since_inception():
    """Get S&P 500 return since fund inception (Jan 9, 2026) for comparison."""
    try:
        settings = load_settings()
        if not settings or not hasattr(settings, 'FMP_API_KEY') or not settings.FMP_API_KEY:
            return None
        
        import requests
        
        # Fund inception date
        inception_date = "2026-01-09"
        
        # Get SPY historical prices
        url = f"https://financialmodelingprep.com/api/v3/historical-price-full/SPY"
        resp = requests.get(url, params={
            "apikey": settings.FMP_API_KEY,
            "from": inception_date,
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
        
        sp500_return = ((current_price - inception_price) / inception_price) * 100
        return sp500_return
    
    except Exception as e:
        print(f"S&P 500 return fetch error: {e}")
        return None


def get_btc_return_since_inception():
    """Get BTC/USD return since fund inception (Jan 9, 2026) for comparison."""
    try:
        settings = load_settings()
        if not settings or not hasattr(settings, 'FMP_API_KEY') or not settings.FMP_API_KEY:
            return None
        
        import requests
        
        # Fund inception date
        inception_date = "2026-01-09"
        
        # Get BTC historical prices (using BTCUSD)
        url = f"https://financialmodelingprep.com/api/v3/historical-price-full/BTCUSD"
        resp = requests.get(url, params={
            "apikey": settings.FMP_API_KEY,
            "from": inception_date,
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
        
        btc_return = ((current_price - inception_price) / inception_price) * 100
        return btc_return
    
    except Exception as e:
        print(f"BTC return fetch error: {e}")
        return None


def get_10y_yield():
    """Get 10Y Treasury yield - key for TLT calls. Uses live FMP data."""
    try:
        settings = load_settings()
        if not settings or not hasattr(settings, 'FMP_API_KEY') or not settings.FMP_API_KEY:
            return None
        
        import requests
        # Use ^TNX for live 10Y yield (CBOE 10Y Treasury Yield Index)
        url = "https://financialmodelingprep.com/api/v3/quote/%5ETNX"
        resp = requests.get(url, params={"apikey": settings.FMP_API_KEY}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list) and data and data[0].get("price"):
            price = float(data[0].get("price", 0))
            # ^TNX is 10x the yield (e.g., 422.7 -> 4.227%)
            yield_pct = price / 100.0 if price > 20 else price
            ts = data[0].get("timestamp")
            asof = "Live"
            if ts:
                try:
                    from datetime import datetime, timezone
                    asof = datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%H:%M UTC")
                except:
                    pass
            # Portfolio: Main thesis = persistent inflation, high rates (NVDA puts, HYG puts, VIX)
            # Hedge: TLT calls pay if inflation comes down, rates fall
            # Target: >4.5% for main portfolio thesis
            target = ">4.5% (main) | <4.0% (TLT hedge)"
            in_range = yield_pct >= 4.5  # Main portfolio thesis playing out
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
                "target": target,
                "in_range": in_range,
                "context": context,
                "description": "10-Year Treasury yield (^TNX)"
            }
        return None
    except Exception as e:
        print(f"10Y yield fetch error: {e}")
        return None


def _fetch_option_quote(data_client, symbol: str) -> dict:
    """Fetch bid/ask quote for an option. Returns {'bid': float, 'ask': float} or None."""
    try:
        from alpaca.data.requests import OptionLatestQuoteRequest
        req = OptionLatestQuoteRequest(symbol_or_symbols=[symbol])
        quotes = data_client.get_option_latest_quote(req)
        if quotes and symbol in quotes:
            q = quotes[symbol]
            return {
                "bid": float(getattr(q, 'bid_price', 0) or 0),
                "ask": float(getattr(q, 'ask_price', 0) or 0),
            }
    except Exception as e:
        print(f"[Quote] Option quote fetch error for {symbol}: {e}")
    return None


def _fetch_stock_quote(data_client, symbol: str) -> dict:
    """Fetch bid/ask quote for a stock/ETF. Returns {'bid': float, 'ask': float} or None."""
    try:
        from alpaca.data.requests import StockLatestQuoteRequest
        req = StockLatestQuoteRequest(symbol_or_symbols=[symbol])
        quotes = data_client.get_stock_latest_quote(req)
        if quotes and symbol in quotes:
            q = quotes[symbol]
            return {
                "bid": float(getattr(q, 'bid_price', 0) or 0),
                "ask": float(getattr(q, 'ask_price', 0) or 0),
            }
    except Exception as e:
        print(f"[Quote] Stock quote fetch error for {symbol}: {e}")
    return None


def _generate_position_theory(position, regime_context, settings):
    """
    Generate intelligent macro-aware theory for a position using LLM.
    
    Returns a brief (max 50 chars) explanation of what market conditions
    would make this position profitable, considering current regime.
    """
    try:
        if not settings or not hasattr(settings, 'openai_api_key') or not settings.openai_api_key:
            return _simple_position_theory(position)
        
        from openai import OpenAI
        client = OpenAI(api_key=settings.openai_api_key)
        
        symbol = position.get("symbol", "")
        qty = position.get("qty", 0)
        opt_info = position.get("opt_info")
        
        # Build position description and determine required direction
        if opt_info:
            underlying = opt_info.get("underlying", symbol.split('/')[0] if '/' in symbol else symbol[:3])
            # Handle both "opt_type" and "type" keys
            opt_type = opt_info.get("opt_type", opt_info.get("type", "")).upper()
            strike = opt_info.get("strike", "")
            expiry = opt_info.get("expiry", "")
            is_long = qty > 0
            is_call = opt_type in ['C', 'CALL']
            
            # Determine what needs to happen for profit
            if is_long and is_call:
                direction = f"{underlying} MUST RISE"
                vol_need = "IV expansion helps"
            elif is_long and not is_call:
                direction = f"{underlying} MUST FALL"
                vol_need = "IV expansion helps"
            elif not is_long and is_call:
                direction = f"{underlying} MUST STAY DOWN or FALL"
                vol_need = "IV crush helps"
            else:  # short put
                direction = f"{underlying} MUST STAY UP or RISE"
                vol_need = "IV crush helps"
            
            pos_desc = f"{'Long' if is_long else 'Short'} {opt_type} on {underlying}"
        else:
            underlying = symbol
            is_long = qty > 0
            direction = f"{underlying} MUST {'RISE' if is_long else 'FALL'}"
            vol_need = "N/A"
            pos_desc = f"{'Long' if is_long else 'Short'} {underlying}"
        
        # Get current macro context
        vix = regime_context.get("vix", "N/A")
        hy_spread = regime_context.get("hy_oas_bps", "N/A")
        yield_10y = regime_context.get("yield_10y", "N/A")
        regime = regime_context.get("regime", "UNKNOWN")
        
        prompt = f"""Position: {pos_desc}
REQUIREMENT: {direction} ({vol_need})
Current regime: {regime}
Macro: VIX {vix}, HY spreads {hy_spread}bp, 10Y {yield_10y}%

In 1 sentence (max 50 chars), what macro conditions would cause {direction.lower()}?
Be specific about regime, volatility, rates, credit, or sector catalysts.

Examples:
- Long PUT on FXI: "China stress → FXI breaks, vol expands"
- Long CALL on SOFI: "Growth rally → rates fall, tech outperforms"
- Long PUT on TAN: "Solar selloff → rates rise, sector rotation"

Theory:"""
        
        response = client.chat.completions.create(
            model=settings.openai_model or "gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=80,
        )
        
        theory = response.choices[0].message.content.strip()
        # Truncate to 50 chars for table display
        if len(theory) > 50:
            theory = theory[:47] + "..."
        
        return theory
        
    except Exception as e:
        print(f"[Theory] LLM error for {symbol}: {e}")
        return _simple_position_theory(position)


def _simple_position_theory(position):
    """Fallback simple theory if LLM fails."""
    symbol = position.get("symbol", "")
    qty = position.get("qty", 0)
    opt_info = position.get("opt_info")
    
    if opt_info:
        underlying = opt_info.get("underlying", symbol.split('/')[0] if '/' in symbol else symbol[:3])
        # Handle both "opt_type" and "type" keys
        opt_type = opt_info.get("opt_type", opt_info.get("type", "")).upper()
        is_long = qty > 0
        is_call = opt_type in ['C', 'CALL']
        
        if is_long and is_call:
            return f"↑ {underlying} rises, IV expands"
        elif is_long and not is_call:
            return f"↓ {underlying} falls, IV expands"
        elif not is_long and is_call:
            return f"↓ {underlying} stays down, IV crushes"
        else:
            return f"↑ {underlying} stays up, IV crushes"
    else:
        is_long = qty > 0
        return f"{'↑' if is_long else '↓'} Price {'appreciation' if is_long else 'decline'}"


def get_positions_data():
    """Fetch positions and calculate P&L using conservative bid/ask marking."""
    try:
        settings = load_settings()
        trading, data_client = make_clients(settings)
        account = trading.get_account()
        positions = trading.get_all_positions()
        
        # Get NAV from sheet first, fallback to account equity
        nav_equity = 0.0
        try:
            nav_rows = read_nav_sheet()
            if nav_rows:
                nav = nav_rows[-1]
                nav_equity = float(nav.equity) if hasattr(nav, 'equity') and nav.equity is not None else 0.0
        except Exception as nav_error:
            print(f"Warning: Could not read NAV sheet: {nav_error}")
        
        # #region agent log
        try:
            debug_payload = {
                "sessionId": "debug-session",
                "runId": "pre-fix",
                "hypothesisId": "H1",
                "location": "dashboard/app.py:get_positions_data:nav_read",
                "message": "NAV sheet and account snapshot",
                "data": {
                    "nav_equity": nav_equity,
                    "has_nav_rows": bool(nav_rows) if "nav_rows" in locals() else False,
                },
                "timestamp": int(time.time() * 1000),
            }
            with open("/Users/jeffreylarson/sites/ai-options-trader-starter/.cursor/debug.log", "a") as _f:
                _f.write(json.dumps(debug_payload) + "\n")
        except Exception:
            pass
        # #endregion
        
        # Fallback: calculate from account if NAV sheet is empty
        if nav_equity == 0.0 and account:
            try:
                account_equity = float(getattr(account, 'equity', 0.0) or 0.0)
                if account_equity > 0:
                    nav_equity = account_equity
            except Exception:
                pass
        
        # Get original capital from env var (tracks total deposits) or investor flows
        # FUND_TOTAL_CAPITAL should be updated when deposits/withdrawals occur
        original_capital = float(os.environ.get("FUND_TOTAL_CAPITAL", "0")) or 950.0
        if original_capital == 950.0:
            # Try reading from investor flows if env var not set
            try:
                flows = read_investor_flows()
                capital_sum = sum(float(f.amount) for f in flows if float(f.amount) > 0)
                if capital_sum > 0:
                    original_capital = capital_sum
            except Exception as flow_error:
                print(f"Warning: Could not read investor flows: {flow_error}")
        
        # Total P&L = NAV - original capital
        total_pnl = nav_equity - original_capital
        
        # Get regime context for intelligent theory generation
        try:
            hy_oas = get_hy_oas()
            vix = get_vix()
            yield_10y = get_10y_yield()
            
            # Determine regime
            vix_val = vix.get("value") if vix else None
            hy_val = hy_oas.get("value") if hy_oas else None
            
            def get_regime_label(vix_val, hy_val):
                if vix_val is None:
                    return "UNKNOWN"
                if vix_val > 25 or (hy_val and hy_val > 400):
                    return "RISK-OFF"
                elif vix_val > 18 or (hy_val and hy_val > 350):
                    return "CAUTIOUS"
                else:
                    return "RISK-ON"
            
            regime_label = get_regime_label(vix_val, hy_val)
            
            regime_context = {
                "vix": f"{vix_val:.1f}" if vix_val else "N/A",
                "hy_oas_bps": f"{hy_val:.0f}" if hy_val else "N/A",
                "yield_10y": f"{yield_10y.get('value'):.2f}%" if yield_10y and yield_10y.get('value') else "N/A",
                "regime": regime_label,
            }
        except Exception as e:
            print(f"[Positions] Could not fetch regime context: {e}")
            regime_context = {"vix": "N/A", "hy_oas_bps": "N/A", "yield_10y": "N/A", "regime": "UNKNOWN"}
        
        positions_list = []
        total_liquidation_value = 0.0
        
        # Process positions with conservative bid/ask marking
        for p in positions:
            try:
                symbol = str(getattr(p, "symbol", "") or "")
                if not symbol:
                    continue
                    
                qty = float(getattr(p, "qty", 0.0) or 0.0)
                mv = float(getattr(p, "market_value", 0.0) or 0.0)  # Alpaca's mid-market mark
                avg_entry = float(getattr(p, "avg_entry_price", 0.0) or 0.0)
                current_price = float(getattr(p, "current_price", 0.0) or 0.0)
                
                # Parse option symbol if needed
                opt_info = None
                try:
                    sym_upper = symbol.upper()
                    # Handle both OCC format and Alpaca format (with /)
                    if '/' in sym_upper:
                        parts = sym_upper.split('/')
                        if len(parts) >= 2:
                            underlying = parts[0]
                            option_part = parts[1]
                            m = re.match(r"^(\d{6})([CP])(\d{8})$", option_part)
                            if m:
                                exp_str, opt_type_char, strike_str = m.groups()
                                # Parse date
                                year = int(exp_str[:2]) + 2000
                                month = int(exp_str[2:4])
                                day = int(exp_str[4:6])
                                from datetime import date
                                exp = date(year, month, day)
                                opt_type = 'C' if opt_type_char == 'C' else 'P'
                                strike = float(strike_str) / 1000.0
                                opt_info = {
                                    "underlying": underlying,
                                    "expiry": str(exp),
                                    "strike": strike,
                                    "opt_type": opt_type,
                                }
                    else:
                        # Standard OCC format
                        m = re.match(r"^([A-Z]+)(\d{6}[CP]\d{8})$", sym_upper)
                        if m:
                            underlying = m.group(1)
                            exp, opt_type, strike = parse_occ_option_symbol(sym_upper, underlying)
                            # Convert 'call'/'put' to 'C'/'P'
                            opt_type_char = 'C' if opt_type.lower() == 'call' else 'P'
                            opt_info = {
                                "underlying": underlying,
                                "expiry": str(exp),
                                "strike": strike,
                                "opt_type": opt_type_char,
                            }
                except Exception as parse_err:
                    # Skip option parsing errors, continue with symbol only
                    pass
                
                # Fetch real bid/ask quote for conservative marking
                quote = None
                liquidation_price = current_price  # Fallback to Alpaca's price
                
                if opt_info:
                    # Option position - fetch option quote
                    quote = _fetch_option_quote(data_client, symbol)
                    multiplier = 100
                else:
                    # Stock/ETF position - fetch stock quote  
                    quote = _fetch_stock_quote(data_client, symbol)
                    multiplier = 1
                
                # Conservative mark: longs at bid, shorts at ask
                if quote:
                    if qty > 0:  # Long position - mark at bid (what we'd get selling)
                        liquidation_price = quote["bid"] if quote["bid"] > 0 else current_price
                    else:  # Short position - mark at ask (what we'd pay to cover)
                        liquidation_price = quote["ask"] if quote["ask"] > 0 else current_price
                
                # Calculate liquidation value and P&L
                if opt_info:
                    entry_cost = avg_entry * multiplier * abs(qty) if avg_entry > 0 else 0
                    liquidation_value = liquidation_price * multiplier * abs(qty)
                    pnl = liquidation_value - entry_cost if qty > 0 else entry_cost - liquidation_value
                else:
                    entry_cost = avg_entry * abs(qty) if avg_entry > 0 else 0
                    liquidation_value = liquidation_price * abs(qty) if qty > 0 else liquidation_price * abs(qty)
                    pnl = liquidation_value - entry_cost if qty > 0 else entry_cost - liquidation_value
                
                total_liquidation_value += liquidation_value
                
                # Generate intelligent theory for this position
                position_dict = {
                    "symbol": symbol,
                    "qty": qty,
                    "market_value": liquidation_value,  # Now using liquidation value
                    "pnl": pnl,
                    "pnl_pct": (pnl / entry_cost * 100) if entry_cost > 0 else 0.0,
                    "current_price": liquidation_price,  # Show liquidation price
                    "opt_info": opt_info,
                    "bid_ask_mark": True,  # Flag that this is conservatively marked
                }
                
                # Generate macro-aware theory
                theory = _generate_position_theory(position_dict, regime_context, settings)
                position_dict["theory"] = theory
                
                positions_list.append(position_dict)
            except Exception as pos_err:
                print(f"Warning: Error processing position: {pos_err}")
                continue
        
        # Sort by P&L (most profitable to least profitable)
        positions_list.sort(key=lambda x: x["pnl"], reverse=True)
        
        # Get cash available from account
        cash_available = 0.0
        try:
            if account:
                cash_available = float(getattr(account, 'cash', 0.0) or 0.0)
        except Exception:
            pass
        
        # Calculate Liquidation NAV = Cash + Liquidation Value of Positions
        liquidation_nav = cash_available + total_liquidation_value
        
        # Total P&L based on liquidation value (conservative)
        liquidation_pnl = liquidation_nav - original_capital
        
        # Live performance since inception based on current liquidation NAV.
        # This keeps the LOX Fund row on the dashboard updating on every refresh,
        # instead of only when the NAV sheet CSV is updated.
        simple_return_pct = (liquidation_pnl / original_capital * 100) if original_capital > 0 else 0.0
        
        # Optionally also load TWR (Time-Weighted Return) from nav_sheet for reference.
        # This is exposed separately so it can be used for reports without
        # interfering with the live dashboard behaviour.
        twr_pct = None
        try:
            nav_sheet_path = os.path.join(os.path.dirname(__file__), "..", "data", "nav_sheet.csv")
            if os.path.exists(nav_sheet_path):
                import csv
                with open(nav_sheet_path, "r") as f:
                    reader = csv.DictReader(f)
                    rows = list(reader)
                    if rows:
                        # Latest TWR cumulative is stored as a decimal (e.g. 0.128 = 12.8%)
                        latest = rows[-1]
                        twr_cum = latest.get("twr_cum", "")
                        if twr_cum:
                            twr_pct = float(twr_cum) * 100  # Convert to percentage
        except Exception as twr_err:
            print(f"[Positions] Could not read TWR: {twr_err}")
        
        # #region agent log
        try:
            debug_payload = {
                "sessionId": "debug-session",
                "runId": "pre-fix",
                "hypothesisId": "H1",
                "location": "dashboard/app.py:get_positions_data:twr_block",
                "message": "TWR and liquidation metrics",
                "data": {
                    "twr_pct": twr_pct,
                    "liquidation_nav": liquidation_nav,
                    "liquidation_pnl": liquidation_pnl,
                    "original_capital": original_capital,
                },
                "timestamp": int(time.time() * 1000),
            }
            with open("/Users/jeffreylarson/sites/ai-options-trader-starter/.cursor/debug.log", "a") as _f:
                _f.write(json.dumps(debug_payload) + "\n")
        except Exception:
            pass
        # #endregion
        
        # For the dashboard we always surface the live simple return so the LOX Fund
        # performance row reflects current liquidation NAV.
        return_pct = simple_return_pct
        
        # #region agent log
        try:
            debug_payload = {
                "sessionId": "debug-session",
                "runId": "pre-fix",
                "hypothesisId": "H1",
                "location": "dashboard/app.py:get_positions_data:return_calc",
                "message": "Final return calculation",
                "data": {
                    "simple_return_pct": simple_return_pct,
                    "twr_pct": twr_pct,
                    "return_pct": return_pct,
                },
                "timestamp": int(time.time() * 1000),
            }
            with open("/Users/jeffreylarson/sites/ai-options-trader-starter/.cursor/debug.log", "a") as _f:
                _f.write(json.dumps(debug_payload) + "\n")
        except Exception:
            pass
        # #endregion
        
        # Get benchmark performance since inception for comparison
        sp500_return = get_sp500_return_since_inception()
        btc_return = get_btc_return_since_inception()
        alpha_sp500 = return_pct - sp500_return if sp500_return is not None else None
        alpha_btc = return_pct - btc_return if btc_return is not None else None
        
        return {
            "positions": positions_list,
            "total_pnl": liquidation_pnl,  # Conservative P&L at bid/ask
            "total_value": total_liquidation_value,
            "nav_equity": liquidation_nav,  # Liquidation NAV
            "original_capital": original_capital,
            "return_pct": return_pct,
            "twr_return_pct": twr_pct,
            "sp500_return": sp500_return,
            "btc_return": btc_return,
            "alpha_sp500": alpha_sp500,
            "alpha_btc": alpha_btc,
            "cash_available": cash_available,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "mark_type": "liquidation",  # Flag that this is bid/ask marked
        }
    except Exception as e:
        import traceback
        error_msg = str(e)
        print(f"Error in get_positions_data: {error_msg}")
        traceback.print_exc()
        
        # Try to at least get account info for NAV fallback
        nav_equity = 0.0
        original_capital = 950.0
        try:
            settings = load_settings()
            trading, _ = make_clients(settings)
            account = trading.get_account()
            if account:
                nav_equity = float(getattr(account, 'equity', 0.0) or 0.0)
        except Exception:
            pass
        
        try:
            flows = read_investor_flows()
            capital_sum = sum(float(f.amount) for f in flows if float(f.amount) > 0)
            if capital_sum > 0:
                original_capital = capital_sum
        except Exception:
            pass
        
        return {
            "error": error_msg,
            "positions": [],
            "total_pnl": nav_equity - original_capital,
            "total_value": 0.0,
            "nav_equity": nav_equity,
            "original_capital": original_capital,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


@app.route('/')
def index():
    """Main dashboard page."""
    return render_template('dashboard.html')


@app.route('/api/positions')
def api_positions():
    """API endpoint for positions data."""
    data = get_positions_data()
    return jsonify(data)


@app.route('/api/closed-trades')
def api_closed_trades():
    """API endpoint for closed trades (realized P&L)."""
    try:
        return jsonify(get_closed_trades_data())
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e), "trades": [], "total_pnl": 0, "win_rate": 0})


@app.route('/api/investors')
def api_investors():
    """API endpoint for investor ledger (unitized NAV)."""
    try:
        return jsonify(get_investor_data())
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e), "investors": [], "nav_per_unit": 1.0, "total_units": 0})


def get_investor_data():
    """Fetch investor ledger with unitized returns."""
    try:
        # Try to read from local investor flows file
        nav_sheet_path = os.path.join(os.path.dirname(__file__), "..", "data", "nav_sheet.csv")
        investor_flows_path = os.path.join(os.path.dirname(__file__), "..", "data", "nav_investor_flows.csv")
        
        if not os.path.exists(investor_flows_path):
            return {"error": "Investor flows file not found", "investors": [], "nav_per_unit": 1.0, "total_units": 0}
        
        # Read investor flows
        import csv
        from datetime import datetime as dt
        
        flows = []
        with open(investor_flows_path, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                flows.append({
                    "ts": row.get("ts", ""),
                    "code": row.get("code", ""),
                    "amount": float(row.get("amount", 0)),
                })
        
        # Read nav sheet for equity
        nav_rows = []
        if os.path.exists(nav_sheet_path):
            with open(nav_sheet_path, "r") as f:
                reader = csv.DictReader(f)
                nav_rows = list(reader)
        
        # Get current equity from Alpaca if nav sheet not available
        current_equity = 0.0
        if nav_rows:
            current_equity = float(nav_rows[-1].get("equity", 0))
        else:
            try:
                settings = load_settings()
                trading, _ = make_clients(settings)
                account = trading.get_account()
                if account:
                    current_equity = float(getattr(account, 'equity', 0) or 0)
            except:
                pass
        
        # Compute unitization (simplified version)
        # Merge flows and nav snapshots chronologically
        events = []
        for f in flows:
            events.append((f["ts"], "flow", f))
        for r in nav_rows:
            events.append((r.get("ts", ""), "nav", r))
        events.sort(key=lambda x: x[0])
        
        nav_per_unit = 1.0
        units_by = {}
        total_units = 0.0
        
        for ts, kind, obj in events:
            if kind == "flow":
                if nav_per_unit <= 0:
                    nav_per_unit = 1.0
                du = float(obj["amount"]) / float(nav_per_unit)
                code = obj["code"]
                units_by[code] = float(units_by.get(code, 0.0)) + du
                total_units += du
            else:
                # NAV snapshot
                if total_units > 0:
                    equity = float(obj.get("equity", 0))
                    if equity > 0:
                        nav_per_unit = equity / total_units
        
        # Calculate investor values
        basis_by = {}
        for f in flows:
            code = f["code"]
            basis_by[code] = float(basis_by.get(code, 0.0)) + float(f["amount"])
        
        investors = []
        for code in sorted(units_by.keys()):
            units = float(units_by.get(code, 0.0))
            value = units * float(nav_per_unit)
            basis = float(basis_by.get(code, 0.0))
            pnl = value - basis
            ret = (pnl / basis * 100) if basis != 0 else 0
            ownership = (units / total_units * 100) if total_units > 0 else 0
            investors.append({
                "code": code,
                "ownership": round(ownership, 1),
                "basis": round(basis, 2),
                "value": round(value, 2),
                "pnl": round(pnl, 2),
                "return_pct": round(ret, 1),
            })
        
        return {
            "investors": investors,
            "nav_per_unit": round(nav_per_unit, 6),
            "total_units": round(total_units, 2),
            "equity": round(current_equity, 2),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"error": str(e), "investors": [], "nav_per_unit": 1.0, "total_units": 0}


def get_closed_trades_data():
    """Fetch closed trades and calculate realized P&L using FIFO matching."""
    from collections import defaultdict
    
    try:
        settings = load_settings()
        trading, _ = make_clients(settings)
    except Exception as e:
        return {"error": str(e), "trades": [], "total_pnl": 0, "win_rate": 0}
    
    try:
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus
        
        req = GetOrdersRequest(status=QueryOrderStatus.ALL, limit=500)
        orders = trading.get_orders(req) or []
    except Exception as e:
        return {"error": str(e), "trades": [], "total_pnl": 0, "win_rate": 0}
    
    # Group filled orders by symbol
    trades_by_symbol = defaultdict(lambda: {'buys': [], 'sells': []})
    
    for o in orders:
        status = str(getattr(o, 'status', '?')).split('.')[-1].lower()
        if 'filled' not in status:
            continue
        
        sym = getattr(o, 'symbol', '?')
        side = str(getattr(o, 'side', '?')).split('.')[-1].lower()
        filled_qty = float(getattr(o, 'filled_qty', 0) or 0)
        filled_price = getattr(o, 'filled_avg_price', 0)
        filled_at = getattr(o, 'filled_at', None)
        
        try:
            price = float(filled_price) if filled_price else 0
        except (ValueError, TypeError):
            price = 0
        
        if filled_qty <= 0 or price <= 0:
            continue
        
        # Determine if option (multiplier = 100)
        is_option = len(sym) > 10 and any(c.isdigit() for c in sym[-8:]) and '/' not in sym
        mult = 100 if is_option else 1
        
        trade = {
            'qty': filled_qty,
            'price': price,
            'date': filled_at,  # Keep full datetime for sorting
            'date_str': str(filled_at)[:10] if filled_at else '?',
            'value': filled_qty * price * mult,
            'mult': mult
        }
        
        if side == 'buy':
            trades_by_symbol[sym]['buys'].append(trade)
        else:
            trades_by_symbol[sym]['sells'].append(trade)
    
    # Calculate closed trades using FIFO matching
    closed_trades = []
    
    for sym, data in trades_by_symbol.items():
        # Sort by date (oldest first) for FIFO
        buys = sorted(data['buys'], key=lambda x: x['date'] or '0')
        sells = sorted(data['sells'], key=lambda x: x['date'] or '0')
        
        display_sym = _parse_option_symbol_display(sym)
        
        # FIFO matching: match each sell with the oldest available buy that came BEFORE it
        total_cost = 0.0
        total_proceeds = 0.0
        closed_qty = 0.0
        
        buy_queue = []  # Queue of (remaining_qty, price_per_unit, mult, date)
        for b in buys:
            buy_queue.append([b['qty'], b['price'], b['mult'], b['date']])
        
        for sell in sells:
            sell_qty_remaining = sell['qty']
            sell_date = sell['date']
            
            while sell_qty_remaining > 0 and buy_queue:
                # Find first buy that came BEFORE this sell
                buy_idx = None
                for i, (bq, bp, bm, bd) in enumerate(buy_queue):
                    if bq > 0 and (bd is None or sell_date is None or bd <= sell_date):
                        buy_idx = i
                        break
                
                if buy_idx is None:
                    # No matching buy found (sell came before any remaining buys)
                    break
                
                buy_remaining, buy_price, buy_mult, buy_date = buy_queue[buy_idx]
                match_qty = min(sell_qty_remaining, buy_remaining)
                
                # Calculate P&L for this match
                cost = match_qty * buy_price * buy_mult
                proceeds = match_qty * sell['price'] * sell['mult']
                
                total_cost += cost
                total_proceeds += proceeds
                closed_qty += match_qty
                
                # Update remaining quantities
                buy_queue[buy_idx][0] -= match_qty
                sell_qty_remaining -= match_qty
                
                # Remove exhausted buys
                if buy_queue[buy_idx][0] <= 0:
                    buy_queue.pop(buy_idx)
        
        # Only include if we matched something
        if closed_qty > 0:
            realized_pnl = total_proceeds - total_cost
            pnl_pct = (realized_pnl / total_cost * 100) if total_cost > 0 else 0
            # Check if any buys remain unmatched
            remaining_buy_qty = sum(b[0] for b in buy_queue)
            fully_closed = remaining_buy_qty < 0.001  # Floating point tolerance
            
            closed_trades.append({
                'symbol': display_sym,
                'cost': total_cost,
                'proceeds': total_proceeds,
                'pnl': realized_pnl,
                'pnl_pct': pnl_pct,
                'fully_closed': fully_closed
            })
    
    # Sort by P&L (best first)
    closed_trades.sort(key=lambda x: x['pnl'], reverse=True)
    
    # Calculate totals
    total_realized = sum(t['pnl'] for t in closed_trades)
    total_wins = sum(1 for t in closed_trades if t['pnl'] >= 0)
    total_losses = sum(1 for t in closed_trades if t['pnl'] < 0)
    win_rate = total_wins / (total_wins + total_losses) * 100 if (total_wins + total_losses) > 0 else 0
    
    return {
        "trades": closed_trades,
        "total_pnl": total_realized,
        "wins": total_wins,
        "losses": total_losses,
        "win_rate": win_rate,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _parse_option_symbol_display(sym: str) -> str:
    """Parse option symbol for display."""
    if '/' in sym:  # Crypto
        return sym
    if len(sym) <= 6:  # Stock/ETF
        return sym
    
    try:
        i = 0
        while i < len(sym) and not sym[i].isdigit():
            i += 1
        
        if i == 0 or i >= len(sym):
            return sym
        
        ticker = sym[:i]
        rest = sym[i:]
        
        if len(rest) >= 15:
            exp = f"{rest[2:4]}/{rest[4:6]}"
            opt_type = "C" if rest[6] == 'C' else "P"
            strike = int(rest[7:]) / 1000
            return f"{ticker} ${strike:.0f}{opt_type} {exp}"
    except (ValueError, IndexError):
        pass
    
    return sym


def fetch_economic_calendar(days_back=3, days_ahead=7):
    """Fetch recent and upcoming economic events from FMP."""
    try:
        settings = load_settings()
        if not settings or not hasattr(settings, 'FMP_API_KEY') or not settings.FMP_API_KEY:
            return [], []
        
        import requests
        url = "https://financialmodelingprep.com/api/v3/economic_calendar"
        resp = requests.get(url, params={"apikey": settings.FMP_API_KEY}, timeout=15)
        resp.raise_for_status()
        events = resp.json()
        
        if not isinstance(events, list):
            return [], []
        
        now = datetime.now(timezone.utc)
        past_cutoff = now - timedelta(days=days_back)
        future_cutoff = now + timedelta(days=days_ahead)
        
        recent_releases = []
        upcoming_events = []
        
        for event in events:
            if not isinstance(event, dict):
                continue
            
            # Parse date
            event_date_str = event.get("date", "").replace(" ", "T")
            try:
                event_date = datetime.fromisoformat(event_date_str).replace(tzinfo=timezone.utc)
            except:
                try:
                    event_date = datetime.strptime(event_date_str.split("T")[0], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                except:
                    continue
            
            # Only US events
            country = event.get("country", "").upper()
            if country and country != "US":
                continue
            
            event_name = event.get("event", "")
            actual = event.get("actual")
            estimate = event.get("estimate")
            previous = event.get("previous")
            
            # Recent releases (with actual values)
            if past_cutoff <= event_date <= now and actual is not None:
                surprise = None
                if estimate is not None and actual is not None:
                    try:
                        surprise = float(actual) - float(estimate)
                    except:
                        pass
                
                recent_releases.append({
                    "date": event_date.strftime("%Y-%m-%d"),
                    "event": event_name,
                    "actual": actual,
                    "estimate": estimate,
                    "previous": previous,
                    "surprise": surprise,
                })
            
            # Upcoming events
            elif now < event_date <= future_cutoff:
                upcoming_events.append({
                    "date": event_date.strftime("%Y-%m-%d %H:%M"),
                    "event": event_name,
                    "estimate": estimate,
                    "previous": previous,
                })
        
        # Sort and limit
        recent_releases.sort(key=lambda x: x["date"], reverse=True)
        upcoming_events.sort(key=lambda x: x["date"])
        
        return recent_releases[:10], upcoming_events[:8]
    
    except Exception as e:
        print(f"Economic calendar fetch error: {e}")
        return [], []


def fetch_earnings_history(symbol, api_key, num_quarters=4):
    """Fetch historical earnings surprises for a ticker from FMP."""
    try:
        import requests
        url = f"https://financialmodelingprep.com/api/v3/earnings-surprises/{symbol}"
        resp = requests.get(url, params={"apikey": api_key}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        
        if not isinstance(data, list) or not data:
            return None
        
        # Get last N quarters
        recent = data[:num_quarters]
        
        beats = 0
        misses = 0
        meets = 0
        
        for q in recent:
            actual = q.get("actualEarningResult")
            estimate = q.get("estimatedEarning")
            if actual is not None and estimate is not None:
                try:
                    diff = float(actual) - float(estimate)
                    if diff > 0.01:
                        beats += 1
                    elif diff < -0.01:
                        misses += 1
                    else:
                        meets += 1
                except:
                    pass
        
        total = beats + misses + meets
        if total == 0:
            return None
        
        return {
            "beats": beats,
            "misses": misses,
            "meets": meets,
            "total": total,
            "beat_rate": round(beats / total * 100),
            "miss_rate": round(misses / total * 100),
        }
    except Exception as e:
        print(f"Earnings history fetch error for {symbol}: {e}")
        return None


def fetch_earnings_calendar(tickers, days_ahead=14):
    """Fetch upcoming earnings for specified tickers from FMP with historical beat/miss data."""
    try:
        settings = load_settings()
        if not settings or not hasattr(settings, 'FMP_API_KEY') or not settings.FMP_API_KEY:
            return []
        
        import requests
        
        # ETF holdings mapping - key components that matter for our thesis
        etf_holdings = {
            "TAN": ["ENPH", "SEDG", "FSLR", "RUN", "CSIQ", "JKS"],  # Solar stocks
            "HYG": [],  # Bond ETF - no individual earnings
            "TLT": [],  # Treasury ETF - no individual earnings
            "VIXM": [],  # VIX futures ETF - no individual earnings
            "GLDM": [],  # Gold ETF - no individual earnings
        }
        
        # Expand tickers to include ETF holdings
        all_tickers = set()
        for ticker in tickers:
            # Clean ticker (remove option suffixes)
            base_ticker = ticker.split()[0] if ' ' in ticker else ticker
            # Remove any numbers (strike prices)
            base_ticker = ''.join([c for c in base_ticker if not c.isdigit()]).strip()
            
            if base_ticker in etf_holdings:
                all_tickers.update(etf_holdings[base_ticker])
            else:
                all_tickers.add(base_ticker)
        
        if not all_tickers:
            return []
        
        # Get earnings calendar from FMP
        now = datetime.now(timezone.utc)
        from_date = now.strftime("%Y-%m-%d")
        to_date = (now + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
        
        url = "https://financialmodelingprep.com/api/v3/earning_calendar"
        resp = requests.get(url, params={
            "apikey": settings.FMP_API_KEY,
            "from": from_date,
            "to": to_date,
        }, timeout=15)
        resp.raise_for_status()
        earnings = resp.json()
        
        if not isinstance(earnings, list):
            return []
        
        # Filter for our tickers and enrich with historical data
        relevant_earnings = []
        for e in earnings:
            symbol = e.get("symbol", "").upper()
            if symbol in [t.upper() for t in all_tickers]:
                # Get historical beat/miss data
                history = fetch_earnings_history(symbol, settings.FMP_API_KEY, num_quarters=4)
                
                relevant_earnings.append({
                    "date": e.get("date", ""),
                    "symbol": symbol,
                    "time": e.get("time", ""),  # "bmo" (before market open) or "amc" (after market close)
                    "eps_estimate": e.get("epsEstimated"),
                    "revenue_estimate": e.get("revenueEstimated"),
                    "history": history,  # Beat/miss history
                })
        
        # Sort by date
        relevant_earnings.sort(key=lambda x: x["date"])
        
        return relevant_earnings
    
    except Exception as e:
        print(f"Earnings calendar fetch error: {e}")
        return []


def fetch_macro_headlines(settings, portfolio_tickers=None, limit=3):
    """Fetch headlines ONLY for portfolio tickers - top 3 most relevant."""
    import requests
    from zoneinfo import ZoneInfo
    headlines = []
    
    try:
        if not portfolio_tickers:
            return headlines
        
        # Filter to clean underlying tickers only
        clean_tickers = list(set([
            t.upper() for t in portfolio_tickers 
            if t and len(t) <= 5 and t.isalpha() and t.upper() not in ['C', 'P']
        ]))
        
        if not clean_tickers:
            return headlines
        
        # Fetch from FMP stock news - portfolio tickers ONLY
        tickers_str = ",".join(clean_tickers[:8])
        url = f"https://financialmodelingprep.com/api/v3/stock_news?tickers={tickers_str}&limit={limit * 3}&apikey={settings.fmp_api_key}"
        
        resp = requests.get(url, timeout=10)
        data = resp.json()
        
        if isinstance(data, list):
            now = datetime.now(timezone.utc)
            for item in data:
                title = item.get("title", "") or ""
                site = item.get("site", "") or ""
                published = item.get("publishedDate", "") or ""
                ticker = item.get("symbol", "") or ""
                news_url = item.get("url", "") or ""
                
                if not title:
                    continue
                
                # Parse date and show relative time
                time_str = ""
                if published:
                    try:
                        dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
                        diff = now - dt
                        hours = diff.total_seconds() / 3600
                        if hours < 1:
                            time_str = f"{int(diff.total_seconds() / 60)}m ago"
                        elif hours < 24:
                            time_str = f"{int(hours)}h ago"
                        else:
                            time_str = dt.strftime("%b %d")
                    except:
                        pass
                
                headlines.append({
                    "headline": title[:100],
                    "source": site[:15] if site else "News",
                    "time": time_str,
                    "ticker": ticker,
                    "url": news_url,
                })
        
        # Dedupe by headline
        seen = set()
        unique_headlines = []
        for h in headlines:
            key = h["headline"][:50].lower()
            if key not in seen:
                seen.add(key)
                unique_headlines.append(h)
        
        headlines = unique_headlines[:limit]
        
    except Exception as e:
        print(f"[Palmer] Headlines error: {e}")
    
    return headlines


def _get_event_source_url(event_name: str) -> str:
    """Map economic event names to authoritative source URLs."""
    event_lower = event_name.lower()
    
    # Federal Reserve / FOMC
    if any(kw in event_lower for kw in ['fomc', 'fed ', 'federal reserve', 'powell', 'rate decision']):
        return "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
    
    # Treasury / Auctions
    if any(kw in event_lower for kw in ['treasury', 'auction', 't-bill', 't-bond', 't-note']):
        return "https://www.treasurydirect.gov/auctions/upcoming/"
    
    # Employment / Jobs (BLS)
    if any(kw in event_lower for kw in ['payroll', 'employment', 'unemployment', 'jobless', 'nonfarm', 'jobs']):
        return "https://www.bls.gov/news.release/empsit.toc.htm"
    
    # Inflation - CPI (BLS)
    if 'cpi' in event_lower or 'consumer price' in event_lower:
        return "https://www.bls.gov/cpi/"
    
    # Inflation - PCE (BEA)
    if 'pce' in event_lower or 'personal consumption' in event_lower:
        return "https://www.bea.gov/data/personal-consumption-expenditures-price-index"
    
    # GDP (BEA)
    if 'gdp' in event_lower or 'gross domestic' in event_lower:
        return "https://www.bea.gov/data/gdp/gross-domestic-product"
    
    # Retail Sales (Census)
    if 'retail' in event_lower:
        return "https://www.census.gov/retail/index.html"
    
    # Housing (Census)
    if any(kw in event_lower for kw in ['housing', 'home sales', 'building permits', 'housing starts']):
        return "https://www.census.gov/construction/nrc/index.html"
    
    # ISM / PMI
    if any(kw in event_lower for kw in ['ism', 'pmi', 'manufacturing index', 'services index']):
        return "https://www.ismworld.org/supply-management-news-and-reports/reports/ism-report-on-business/"
    
    # Durable Goods (Census)
    if 'durable' in event_lower:
        return "https://www.census.gov/manufacturing/m3/index.html"
    
    # Consumer Confidence (Conference Board)
    if 'consumer confidence' in event_lower or 'consumer sentiment' in event_lower:
        return "https://www.conference-board.org/topics/consumer-confidence"
    
    # Default: Trading Economics calendar
    return "https://tradingeconomics.com/united-states/calendar"


def fetch_trading_economics_calendar(api_key, today_str):
    """Try Trading Economics API first - better timezone handling."""
    import requests
    events = []
    
    try:
        # Trading Economics API endpoint
        url = f"https://api.tradingeconomics.com/calendar/country/united%20states/{today_str}/{today_str}"
        headers = {"Authorization": f"Client {api_key}"}
        resp = requests.get(url, headers=headers, timeout=10)
        
        if resp.status_code == 200:
            data = resp.json() or []
            for item in data:
                event_name = item.get("Event", "") or item.get("event", "")
                event_date_str = item.get("Date", "") or item.get("date", "")
                
                # Parse time - Trading Economics provides timezone-aware times
                event_time = ""
                if event_date_str:
                    try:
                        from zoneinfo import ZoneInfo
                        # Trading Economics format: "2024-01-22T07:30:00-05:00" (already ET)
                        if "T" in event_date_str:
                            dt = datetime.fromisoformat(event_date_str)
                            # Convert to Eastern if needed
                            if dt.tzinfo:
                                dt_et = dt.astimezone(ZoneInfo("America/New_York"))
                            else:
                                dt_et = dt
                            event_time = dt_et.strftime("%I:%M %p ET").lstrip("0")
                    except:
                        pass
                
                actual = item.get("Actual") or item.get("actual")
                estimate = item.get("Forecast") or item.get("forecast") or item.get("TEForecast")
                previous = item.get("Previous") or item.get("previous")
                
                events.append({
                    "event": event_name,
                    "time": event_time,
                    "actual": actual,
                    "estimate": estimate,
                    "previous": previous,
                    "source": "tradingeconomics"
                })
        
        return events
    except Exception as e:
        print(f"[Palmer] Trading Economics error: {e}")
        return []


def fetch_fed_fiscal_calendar(settings):
    """Fetch TODAY's economic releases - tries Trading Economics first, falls back to FMP."""
    events = []
    seen_events = set()
    
    from datetime import datetime
    import requests
    
    # Only fetch TODAY's events
    today = datetime.now().strftime("%Y-%m-%d")
    today_display = datetime.now().strftime("%A, %B %d, %Y")
    
    # Try Trading Economics first (better timezone data)
    te_key = getattr(settings, 'trading_economics_api_key', None) or getattr(settings, 'TRADING_ECONOMICS_API_KEY', None)
    if te_key:
        print("[Palmer] Trying Trading Economics for calendar...")
        te_events = fetch_trading_economics_calendar(te_key, today)
        if te_events:
            print(f"[Palmer] Got {len(te_events)} events from Trading Economics")
            for item in te_events:
                event_name = item.get("event", "")
                dedup_key = f"{event_name[:30].lower().strip()}"
                if dedup_key in seen_events:
                    continue
                seen_events.add(dedup_key)
                
                # Calculate surprise
                actual = item.get("actual")
                estimate = item.get("estimate")
                surprise_direction = None
                if actual is not None and estimate is not None:
                    try:
                        a = float(str(actual).replace("%", "").replace(",", "").strip())
                        e = float(str(estimate).replace("%", "").replace(",", "").strip())
                        if a > e:
                            surprise_direction = "beat"
                        elif a < e:
                            surprise_direction = "miss"
                    except:
                        pass
                
                events.append({
                    "time": item.get("time", ""),
                    "event": event_name,
                    "actual": actual,
                    "previous": item.get("previous"),
                    "estimate": estimate,
                    "surprise_direction": surprise_direction,
                    "url": "https://tradingeconomics.com/united-states/calendar",
                    "source": "tradingeconomics"
                })
            
            if events:
                return events, today_display
    
    # Fallback to FMP
    print("[Palmer] Using FMP for calendar...")
    fmp_key = settings.fmp_api_key
    if not fmp_key:
        return events, None
    
    try:
        url = f"https://financialmodelingprep.com/api/v3/economic_calendar?from={today}&to={today}&apikey={fmp_key}"
        resp = requests.get(url, timeout=10)
        
        if resp.status_code == 200:
            data = resp.json() or []
            
            for item in data:
                country = item.get("country", "").upper()
                
                # Only US events
                if country and country != "US":
                    continue
                
                event_name = item.get("event", "")
                event_name_lower = event_name.lower()
                event_date_str = item.get("date", "")
                
                # Parse time - FMP may be UTC, convert to ET
                event_time = ""
                if len(event_date_str) > 10:
                    try:
                        from zoneinfo import ZoneInfo
                        dt = datetime.fromisoformat(event_date_str.replace(" ", "T"))
                        # Assume FMP is UTC, convert to Eastern
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
                        dt_et = dt.astimezone(ZoneInfo("America/New_York"))
                        event_time = dt_et.strftime("%I:%M %p ET").lstrip("0")
                    except:
                        pass
                
                # Dedupe
                dedup_key = f"{event_name[:30].lower().strip()}"
                if dedup_key in seen_events:
                    continue
                seen_events.add(dedup_key)
                
                # Get values
                actual = item.get("actual")
                estimate = item.get("estimate")
                previous = item.get("previous")
                
                # Calculate surprise
                surprise_direction = None
                if actual is not None and estimate is not None:
                    try:
                        actual_val = float(actual)
                        estimate_val = float(estimate)
                        diff = actual_val - estimate_val
                        # Jobless claims: lower = better
                        if "jobless" in event_name_lower or "unemployment" in event_name_lower:
                            surprise_direction = "beat" if diff < 0 else "miss" if diff > 0 else "inline"
                        else:
                            surprise_direction = "beat" if diff > 0 else "miss" if diff < 0 else "inline"
                    except:
                        pass
                
                events.append({
                    "time": event_time,
                    "event": event_name,
                    "actual": actual,
                    "previous": previous,
                    "estimate": estimate,
                    "surprise_direction": surprise_direction,
                    "url": _get_event_source_url(event_name),
                })
        
        # Sort by time
        events.sort(key=lambda x: x.get("time", "99:99"))
        return events, today_display
        
    except Exception as e:
        print(f"[Palmer] Calendar error: {e}")
        return [], None


def _describe_portfolio(positions):
    """Build a concise description of portfolio positioning from actual positions."""
    if not positions:
        return "No positions"
    
    longs = []
    shorts = []
    
    for p in positions:
        symbol = p.get("symbol", "")
        qty = p.get("qty", 0)
        opt = p.get("opt_info")
        
        if opt:
            # Option position
            underlying = opt.get("underlying", symbol[:3])
            opt_type = opt.get("type", "").upper()
            
            if qty > 0:  # Long options
                if opt_type == "PUT":
                    shorts.append(f"{underlying} (puts)")
                elif opt_type == "CALL":
                    longs.append(f"{underlying} (calls)")
            else:  # Short options
                if opt_type == "PUT":
                    longs.append(f"{underlying} (short puts)")
                elif opt_type == "CALL":
                    shorts.append(f"{underlying} (short calls)")
        else:
            # Stock/ETF position
            ticker = symbol
            if qty > 0:
                longs.append(ticker)
            elif qty < 0:
                shorts.append(ticker)
    
    desc_parts = []
    if longs:
        desc_parts.append(f"Long: {', '.join(longs[:4])}")
    if shorts:
        desc_parts.append(f"Short: {', '.join(shorts[:4])}")
    
    return "; ".join(desc_parts) if desc_parts else "No clear directional exposure"


def _calculate_monte_carlo_forecast(vix_val, hy_val, regime_label):
    """
    Calculate simplified Monte Carlo forecast based on current regime.
    
    This is a regime-conditional estimate, not a full MC simulation.
    The actual MC simulation runs separately via the CLI.
    """
    import numpy as np
    
    # Base assumptions by regime (6-month horizon)
    regime_params = {
        "RISK-ON": {"mean": 0.08, "vol": 0.12, "var95": -0.10, "prob_positive": 0.68},
        "CAUTIOUS": {"mean": 0.03, "vol": 0.18, "var95": -0.18, "prob_positive": 0.55},
        "RISK-OFF": {"mean": -0.02, "vol": 0.25, "var95": -0.30, "prob_positive": 0.42},
        "UNKNOWN": {"mean": 0.04, "vol": 0.15, "var95": -0.15, "prob_positive": 0.55},
    }
    
    params = regime_params.get(regime_label, regime_params["UNKNOWN"])
    
    # Adjust for current VIX (higher VIX = more tail risk)
    if vix_val and vix_val > 20:
        vol_mult = 1 + (vix_val - 20) / 30  # Scale up volatility
        params["var95"] *= vol_mult
        params["vol"] *= min(vol_mult, 1.5)
    
    # Adjust for HY spreads (wider = more credit stress)
    if hy_val and hy_val > 350:
        params["mean"] -= 0.02
        params["prob_positive"] -= 0.05
    
    return {
        "mean_pnl_pct": round(params["mean"], 3),
        "var_95_pct": round(params["var95"], 3),
        "prob_positive": round(params["prob_positive"], 2),
        "regime": regime_label,
        "horizon_months": 6,
    }


def _generate_palmer_analysis():
    """Internal function to generate Palmer's analysis (called by cache refresh)."""
    try:
        settings = load_settings()
    except Exception as e:
        print(f"[Palmer] Settings load error: {e}")
        return {"error": f"Settings error: {e}", "analysis": None}
    
    if not settings or not hasattr(settings, 'openai_api_key') or not settings.openai_api_key:
        return {"error": "OpenAI API key not configured", "analysis": None}
    
    # Get current macro data
    hy_oas = get_hy_oas()
    vix = get_vix()
    yield_10y = get_10y_yield()
    
    # Get today's economic calendar
    fed_fiscal_events, calendar_date = fetch_fed_fiscal_calendar(settings)
    
    # Get positions for context (need tickers for headline fallback)
    positions_data = get_positions_data()
    
    # Extract portfolio tickers for headline fallback
    portfolio_tickers = []
    for p in positions_data.get("positions", []):
        opt = p.get("opt_info")
        if opt:
            portfolio_tickers.append(opt.get("underlying"))
        else:
            portfolio_tickers.append(p.get("symbol"))
    
    # Get macro headlines (with portfolio fallback)
    headlines = fetch_macro_headlines(settings, portfolio_tickers=portfolio_tickers, limit=3)
    
    # Build dynamic portfolio description from actual positions
    portfolio_desc = _describe_portfolio(positions_data.get("positions", []))
    
    # Build regime snapshot for structured output
    regime_snapshot = {
        "hy_oas_bps": hy_oas.get("value") if hy_oas else None,
        "vix": vix.get("value") if vix else None,
        "yield_10y": yield_10y.get("value") if yield_10y else None,
        "portfolio_nav": positions_data.get("nav_equity"),
        "portfolio_pnl": positions_data.get("total_pnl"),
    }
    
    # Determine traffic light statuses
    def get_regime_status(vix_val, hy_val):
        if vix_val is None:
            return "UNKNOWN", "gray"
        if vix_val > 25 or (hy_val and hy_val > 400):
            return "RISK-OFF", "red"
        elif vix_val > 18 or (hy_val and hy_val > 350):
            return "CAUTIOUS", "yellow"
        else:
            return "RISK-ON", "green"
    
    def get_vol_status(vix_val):
        if vix_val is None:
            return "UNKNOWN", "gray"
        if vix_val > 25:
            return "ELEVATED", "red"
        elif vix_val > 18:
            return "MODERATE", "yellow"
        else:
            return "LOW", "green"
    
    def get_credit_status(hy_val):
        if hy_val is None:
            return "UNKNOWN", "gray"
        if hy_val > 400:
            return "STRESSED", "red"
        elif hy_val > 325:
            return "WATCHING", "yellow"
        else:
            return "STABLE", "green"
    
    def get_rates_status(yield_val):
        """
        10Y context (post-2008 avg ~2%, pre-2008 ~4.5%):
        - < 3.5%: LOW (dovish, unusual in current regime)
        - 3.5-4.0%: MODERATE (transition zone)
        - 4.0-4.5%: ELEVATED (restrictive, current zone)
        - > 4.5%: HIGH (very restrictive, approaching 2023 peaks)
        """
        if yield_val is None:
            return "UNKNOWN", "gray"
        if yield_val > 4.5:
            return "HIGH", "red"
        elif yield_val > 4.0:
            return "ELEVATED", "yellow"
        elif yield_val > 3.5:
            return "MODERATE", "green"
        else:
            return "LOW", "green"
    
    vix_val = regime_snapshot.get("vix")
    hy_val = regime_snapshot.get("hy_oas_bps")
    yield_val = regime_snapshot.get("yield_10y")
    
    regime_label, regime_color = get_regime_status(vix_val, hy_val)
    vol_label, vol_color = get_vol_status(vix_val)
    credit_label, credit_color = get_credit_status(hy_val)
    rates_label, rates_color = get_rates_status(yield_val)
    
    # Format today's releases for display
    events_display = {
        "date": calendar_date or datetime.now().strftime("%A, %B %d, %Y"),
        "releases": []
    }
    for e in fed_fiscal_events[:15]:
        events_display["releases"].append({
            "time": e.get("time", ""),
            "event": e["event"],
            "actual": e.get("actual"),
            "previous": e.get("previous"),
            "estimate": e.get("estimate"),
            "surprise_direction": e.get("surprise_direction"),
            "url": e.get("url", ""),
        })
    
    # Format headlines for display
    headlines_display = []
    for h in headlines[:4]:
        headlines_display.append({
            "headline": h["headline"],
            "source": h["source"],
            "time": h["time"],
            "ticker": h.get("ticker", ""),
            "url": h.get("url", ""),
        })
    
    # Generate LLM insight with technical depth
    try:
        from openai import OpenAI
        client = OpenAI(api_key=settings.openai_api_key)
        
        # Build rich context for technical analysis
        # VIX context: percentile positioning and term structure implications
        vix_context = ""
        if vix_val:
            if vix_val < 14:
                vix_context = f"VIX {vix_val:.1f} (5th-15th percentile, complacency zone—put premium compressed, hedges cheap)"
            elif vix_val < 18:
                vix_context = f"VIX {vix_val:.1f} (25th-45th percentile, normal regime—balanced risk/reward on vol)"
            elif vix_val < 22:
                vix_context = f"VIX {vix_val:.1f} (50th-70th percentile, elevated—event risk priced, hedges more expensive)"
            elif vix_val < 28:
                vix_context = f"VIX {vix_val:.1f} (75th-90th percentile, stressed—volatility term structure likely inverted)"
            else:
                vix_context = f"VIX {vix_val:.1f} (>90th percentile, crisis mode—vol selling opportunities emerging but timing risk high)"
        
        # HY OAS context: credit cycle positioning
        hy_context = ""
        if hy_val:
            if hy_val < 300:
                hy_context = f"HY OAS {hy_val:.0f}bp (tight spreads, late-cycle credit optimism—risk/reward unfavorable for HY longs)"
            elif hy_val < 350:
                hy_context = f"HY OAS {hy_val:.0f}bp (normal range, credit benign—watch for spread compression exhaustion)"
            elif hy_val < 450:
                hy_context = f"HY OAS {hy_val:.0f}bp (widening, early stress signals—correlation to equity rising)"
            else:
                hy_context = f"HY OAS {hy_val:.0f}bp (stressed, dislocation zone—credit leading equities lower, contagion risk)"
        
        # 10Y context: real rate and duration regime
        rate_context = ""
        if yield_val:
            if yield_val < 3.5:
                rate_context = f"10Y {yield_val:.2f}% (dovish regime, duration tailwind—growth concerns dominating)"
            elif yield_val < 4.2:
                rate_context = f"10Y {yield_val:.2f}% (neutral range, Fed at terminal—duration neutral)"
            elif yield_val < 4.7:
                rate_context = f"10Y {yield_val:.2f}% (restrictive, term premium rebuilding—duration drag on growth assets)"
            else:
                rate_context = f"10Y {yield_val:.2f}% (hawkish extreme, fiscal supply pressure—equity multiple compression zone)"
        
        # Portfolio transmission mechanism (defensive coding)
        portfolio_positions = positions_data.get("positions", []) if positions_data else []
        portfolio_greeks = {
            "delta_pct": positions_data.get("return_pct", 0) if positions_data else 0,
            "long_vol": any("VIXM" in str(p.get("symbol", "") or "") or "VIX" in str(p.get("symbol", "") or "") for p in portfolio_positions),
            "short_credit": any("HYG" in str(p.get("symbol", "") or "") and (p.get("qty") or 0) < 0 for p in portfolio_positions) or any("HYG" in str((p.get("opt_info") or {}).get("underlying", "")) for p in portfolio_positions if (p.get("opt_info") or {}).get("opt_type") == "P"),
            "em_exposure": any(ticker in str(p.get("symbol", "") or "") for p in portfolio_positions for ticker in ["FXI", "EEM", "EWZ", "EWY"]),
        }
        
        # Format events with economic significance
        events_context = ""
        if fed_fiscal_events:
            event_details = []
            for e in fed_fiscal_events[:5]:
                evt_name = e.get("event", "")
                actual = e.get("actual")
                estimate = e.get("estimate")
                
                # Determine economic significance
                if "PCE" in evt_name or "CPI" in evt_name:
                    sig = "inflation gauge—Fed reaction function driver"
                elif "Payroll" in evt_name or "Employment" in evt_name or "Jobless" in evt_name:
                    sig = "labor market—recession probability input"
                elif "GDP" in evt_name:
                    sig = "growth confirmation—earnings revision catalyst"
                elif "ISM" in evt_name or "PMI" in evt_name:
                    sig = "leading indicator—manufacturing cycle signal"
                elif "Retail" in evt_name:
                    sig = "consumer health—consumption resilience"
                elif "FOMC" in evt_name or "Fed" in evt_name:
                    sig = "policy signal—rate path recalibration"
                else:
                    sig = "macro data point"
                
                if actual is not None and estimate is not None:
                    try:
                        diff = float(actual) - float(estimate)
                        direction = "beat" if diff > 0 else "miss"
                        event_details.append(f"{evt_name}: {actual} vs {estimate} est ({direction}, {sig})")
                    except:
                        event_details.append(f"{evt_name}: {actual} ({sig})")
                elif actual is not None:
                    event_details.append(f"{evt_name}: {actual} ({sig})")
                else:
                    event_details.append(f"{evt_name} pending ({sig})")
            events_context = "; ".join(event_details[:3])
        
        # Format headlines with market relevance
        news_context = ""
        if headlines:
            news_items = []
            for h in headlines[:3]:
                headline = h.get("headline", "") if h else ""
                ticker = h.get("ticker", "") if h else ""
                # Add relevance tag
                if ticker and any(ticker in str(p.get("symbol", "") or "") or ticker in str((p.get("opt_info") or {}).get("underlying", "")) for p in portfolio_positions):
                    news_items.append(f"{headline} [POSITION-RELEVANT: {ticker}]")
                else:
                    news_items.append(headline)
            news_context = " | ".join(news_items)
        
        # Construct technically rigorous prompt
        prompt = f"""You are a macro strategist at a systematic hedge fund. Provide a TECHNICAL assessment (not sentiment).

QUANTITATIVE CONTEXT:
- {vix_context}
- {hy_context}
- {rate_context}
- Regime: {regime_label} (VIX/HY-based classification)

ECONOMIC CALENDAR:
{events_context if events_context else "No releases today"}

MARKET HEADLINES:
{news_context if news_context else "No relevant headlines"}

PORTFOLIO EXPOSURE:
{portfolio_desc}
Long vol: {'Yes' if portfolio_greeks['long_vol'] else 'No'} | EM exposure: {'Yes' if portfolio_greeks['em_exposure'] else 'No'}

TASK: Write 2-3 sentences maximum. Be precise and technical:
1. State regime with QUANTITATIVE anchor (VIX percentile, HY spread level)
2. Name the PRIMARY transmission: [data/event] → [mechanism] → [portfolio impact]
3. Cite ONE specific threshold or magnitude (e.g., "10Y above 4.50% compresses multiples ~5%")

Rules:
- No sentiment language ("confidence", "optimism")
- No hedging ("could", "might")
- Use: "→" for causality chains
- Be direct about portfolio positioning"""

        response = client.chat.completions.create(
            model=settings.openai_model or "gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.15,
            max_tokens=200,
        )
        
        insight = response.choices[0].message.content.strip()
    except Exception as e:
        print(f"[Palmer] LLM error: {e}")
        insight = "Analysis temporarily unavailable."
    
    # Generate simple Monte Carlo forecast based on current regime
    mc_forecast = _calculate_monte_carlo_forecast(vix_val, hy_val, regime_label)
    
    return {
        "analysis": insight,
        "regime_snapshot": regime_snapshot,
        "traffic_lights": {
            "regime": {"label": regime_label, "color": regime_color},
            "volatility": {"label": vol_label, "color": vol_color, "value": f"VIX {vix_val:.1f}" if vix_val else "N/A"},
            "credit": {"label": credit_label, "color": credit_color, "value": f"{hy_val:.0f}bp" if hy_val else "N/A"},
            "rates": {"label": rates_label, "color": rates_color, "value": f"{yield_val:.2f}%" if yield_val else "N/A"},
        },
        "events": events_display,
        "headlines": headlines_display,
        "monte_carlo": mc_forecast,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _detect_regime_change(old_lights, new_lights):
    """Detect if any traffic light changed color."""
    if not old_lights or not new_lights:
        return False, None
    
    changes = []
    for key in ["regime", "volatility", "credit", "rates"]:
        old_color = old_lights.get(key, {}).get("color") if old_lights.get(key) else None
        new_color = new_lights.get(key, {}).get("color") if new_lights.get(key) else None
        old_label = old_lights.get(key, {}).get("label") if old_lights.get(key) else None
        new_label = new_lights.get(key, {}).get("label") if new_lights.get(key) else None
        
        if old_color and new_color and old_color != new_color:
            # Determine direction of change
            severity_order = {"green": 0, "yellow": 1, "red": 2}
            old_sev = severity_order.get(old_color, 0)
            new_sev = severity_order.get(new_color, 0)
            direction = "worsening" if new_sev > old_sev else "improving"
            changes.append({
                "indicator": key.upper(),
                "from": old_label,
                "to": new_label,
                "direction": direction,
            })
    
    if changes:
        return True, changes
    return False, None


def _refresh_palmer_cache():
    """Refresh Palmer's cached analysis."""
    global PALMER_CACHE
    print(f"[Palmer] Refreshing analysis at {datetime.now(timezone.utc).isoformat()}")
    try:
        result = _generate_palmer_analysis()
        with PALMER_CACHE_LOCK:
            # Detect regime changes before updating
            old_lights = PALMER_CACHE.get("traffic_lights")
            new_lights = result.get("traffic_lights")
            changed, change_details = _detect_regime_change(old_lights, new_lights)
            
            # Store previous state
            PALMER_CACHE["prev_traffic_lights"] = old_lights
            
            # Update cache
            PALMER_CACHE["analysis"] = result.get("analysis")
            PALMER_CACHE["regime_snapshot"] = result.get("regime_snapshot")
            PALMER_CACHE["traffic_lights"] = new_lights
            PALMER_CACHE["events"] = result.get("events")
            PALMER_CACHE["headlines"] = result.get("headlines")
            PALMER_CACHE["monte_carlo"] = result.get("monte_carlo")
            PALMER_CACHE["timestamp"] = result.get("timestamp")
            PALMER_CACHE["last_refresh"] = datetime.now(timezone.utc)
            PALMER_CACHE["error"] = result.get("error")
            
            # Track regime change
            PALMER_CACHE["regime_changed"] = changed
            PALMER_CACHE["regime_change_details"] = change_details
            
            if changed:
                print(f"[Palmer] ⚡ REGIME CHANGE DETECTED: {change_details}")
        
        print(f"[Palmer] Cache refreshed successfully")
    except Exception as e:
        import traceback
        traceback.print_exc()
        with PALMER_CACHE_LOCK:
            PALMER_CACHE["error"] = str(e)
        print(f"[Palmer] Cache refresh failed: {e}")


def _palmer_background_refresh():
    """Background thread that refreshes Palmer's analysis every PALMER_REFRESH_INTERVAL seconds."""
    while True:
        try:
            time.sleep(PALMER_REFRESH_INTERVAL)
            _refresh_palmer_cache()
        except Exception as e:
            print(f"[Palmer] Background refresh error: {e}")
            time.sleep(60)  # Wait a minute before retrying on error


@app.route('/api/regime-analysis')
def api_regime_analysis():
    """Palmer: Returns cached LLM analysis. Refreshes automatically every 30 min."""
    with PALMER_CACHE_LOCK:
        if PALMER_CACHE["analysis"] is None:
            # First request - trigger initial refresh
            pass
        
        # Return cached data including monte_carlo
        return jsonify({
            "analysis": PALMER_CACHE.get("analysis"),
            "regime_snapshot": PALMER_CACHE.get("regime_snapshot"),
            "traffic_lights": PALMER_CACHE.get("traffic_lights"),
            "events": PALMER_CACHE.get("events"),
            "headlines": PALMER_CACHE.get("headlines"),
            "monte_carlo": PALMER_CACHE.get("monte_carlo"),
            "timestamp": PALMER_CACHE.get("timestamp"),
            "regime_changed": PALMER_CACHE.get("regime_changed", False),
            "regime_change_details": PALMER_CACHE.get("regime_change_details"),
            "error": PALMER_CACHE.get("error"),
        })


@app.route('/api/regime-analysis/force-refresh')
def api_regime_analysis_force():
    """Admin-only: Force refresh Palmer's analysis. Requires secret."""
    secret = request.args.get("secret", "")
    if secret != ADMIN_SECRET:
        return jsonify({"error": "Unauthorized. Admin secret required."}), 403
    
    _refresh_palmer_cache()
    return jsonify({"message": "Palmer analysis refreshed", "timestamp": datetime.now(timezone.utc).isoformat()})


# Start background refresh thread on app startup
_palmer_thread_started = False

def start_palmer_background():
    """Initialize Palmer's cache and start background refresh."""
    global _palmer_thread_started
    if _palmer_thread_started:
        return
    _palmer_thread_started = True
    
    print(f"[Palmer] Starting background refresh thread (interval: {PALMER_REFRESH_INTERVAL}s)")
    
    # Do initial refresh immediately in background
    def initial_refresh():
        _refresh_palmer_cache()
    
    init_thread = threading.Thread(target=initial_refresh, daemon=True)
    init_thread.start()
    
    # Start background refresh thread
    thread = threading.Thread(target=_palmer_background_refresh, daemon=True)
    thread.start()


# Auto-start Palmer when module loads (works with gunicorn)
# Only start once per worker process
start_palmer_background()


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True, threaded=True)
