"""
LOX FUND Dashboard
Flask app for investor-facing P&L dashboard (updates every 5 minutes).
Palmer analysis is server-cached and refreshes every 30 minutes automatically.
"""

# ============ IMPORTS ============
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

# Import refactored modules
from dashboard.data_fetchers import (
    get_hy_oas, get_vix, get_10y_yield,
    get_sp500_return_since_inception, get_btc_return_since_inception,
)
from dashboard.regime_utils import get_regime_domains_data, get_regime_label
from dashboard.news_utils import (
    fetch_economic_calendar, fetch_earnings_calendar,
    fetch_earnings_history, fetch_macro_headlines, get_event_source_url,
)

# ============ FLASK APP SETUP ============
app = Flask(__name__)

# ============ PALMER CACHE ============
# Server-side cache for Palmer's analysis - users cannot trigger refreshes
PALMER_CACHE = {
    "analysis": None,
    "regime_snapshot": None,
    "timestamp": None,
    "last_refresh": None,
    "traffic_lights": None,
    "portfolio_analysis": None,  # Position categorization and scenario matrix
    "prev_traffic_lights": None,  # For change detection
    "regime_changed": False,
    "regime_change_details": None,
}
PALMER_CACHE_LOCK = threading.Lock()
PALMER_REFRESH_INTERVAL = 30 * 60  # 30 minutes in seconds
ADMIN_SECRET = os.environ.get("PALMER_ADMIN_SECRET", "lox-admin-2026")  # Set in env for production

# ============ MONTE CARLO CACHE ============
# Separate cache for MC simulation - refreshes hourly
MC_CACHE = {
    "forecast": None,
    "timestamp": None,
    "last_refresh": None,
}
MC_CACHE_LOCK = threading.Lock()
MC_REFRESH_INTERVAL = 60 * 60  # 1 hour in seconds

# ============ POSITIONS CACHE ============
# Short-lived cache for positions data - reduces API calls on rapid refreshes
POSITIONS_CACHE = {
    "data": None,
    "timestamp": None,
}
POSITIONS_CACHE_LOCK = threading.Lock()
POSITIONS_CACHE_TTL = 10  # 10 seconds - live updates

# ============ OTHER DATA CACHES ============
# Short-lived caches for other frequently requested data
INVESTORS_CACHE = {"data": None, "timestamp": None}
INVESTORS_CACHE_LOCK = threading.Lock()
INVESTORS_CACHE_TTL = 10  # 10 seconds - live updates

TRADES_CACHE = {"data": None, "timestamp": None}
TRADES_CACHE_LOCK = threading.Lock()
TRADES_CACHE_TTL = 60  # 1 minute

DOMAINS_CACHE = {"data": None, "timestamp": None}
DOMAINS_CACHE_LOCK = threading.Lock()
DOMAINS_CACHE_TTL = 120  # 2 minutes

NEWS_CACHE = {"data": None, "timestamp": None}
NEWS_CACHE_LOCK = threading.Lock()
NEWS_CACHE_TTL = 300  # 5 minutes


# ============ QUOTE FETCHING HELPERS ============

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


def _fetch_batch_option_quotes(data_client, symbols: list[str]) -> dict[str, dict]:
    """
    Batch fetch bid/ask quotes for multiple options in a single API call.
    Returns dict mapping symbol -> {'bid': float, 'ask': float}
    """
    if not symbols:
        return {}
    
    result = {}
    try:
        from alpaca.data.requests import OptionLatestQuoteRequest
        req = OptionLatestQuoteRequest(symbol_or_symbols=symbols)
        quotes = data_client.get_option_latest_quote(req)
        if quotes:
            for symbol, q in quotes.items():
                result[symbol] = {
                    "bid": float(getattr(q, 'bid_price', 0) or 0),
                    "ask": float(getattr(q, 'ask_price', 0) or 0),
                }
    except Exception as e:
        print(f"[Quote] Batch option quote fetch error: {e}")
    return result


def _fetch_batch_stock_quotes(data_client, symbols: list[str]) -> dict[str, dict]:
    """
    Batch fetch bid/ask quotes for multiple stocks/ETFs in a single API call.
    Returns dict mapping symbol -> {'bid': float, 'ask': float}
    
    Note: data_client is OptionHistoricalDataClient, so we create a StockHistoricalDataClient here.
    """
    if not symbols:
        return {}
    
    result = {}
    try:
        from alpaca.data.requests import StockLatestQuoteRequest
        from alpaca.data.historical import StockHistoricalDataClient
        
        # Create stock data client (uses same API keys from env)
        stock_client = StockHistoricalDataClient(
            api_key=os.environ.get("ALPACA_API_KEY"),
            secret_key=os.environ.get("ALPACA_SECRET_KEY"),
            url_override=os.environ.get("ALPACA_DATA_URL"),
        )
        
        req = StockLatestQuoteRequest(symbol_or_symbols=symbols)
        quotes = stock_client.get_stock_latest_quote(req)
        if quotes:
            for symbol, q in quotes.items():
                result[symbol] = {
                    "bid": float(getattr(q, 'bid_price', 0) or 0),
                    "ask": float(getattr(q, 'ask_price', 0) or 0),
                }
    except Exception as e:
        print(f"[Quote] Batch stock quote fetch error: {e}")
    return result


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


# ============ POSITION DATA HELPERS ============

def _get_nav_equity(account):
    """Get NAV equity from NAV sheet or fallback to account equity."""
    nav_equity = 0.0
    try:
        nav_rows = read_nav_sheet()
        if nav_rows:
            nav = nav_rows[-1]
            nav_equity = float(nav.equity) if hasattr(nav, 'equity') and nav.equity is not None else 0.0
    except Exception as nav_error:
        print(f"Warning: Could not read NAV sheet: {nav_error}")
    
    # Fallback: calculate from account if NAV sheet is empty
    if nav_equity == 0.0 and account:
        try:
            account_equity = float(getattr(account, 'equity', 0.0) or 0.0)
            if account_equity > 0:
                nav_equity = account_equity
        except Exception:
            pass
    
    return nav_equity


def _get_original_capital():
    """Get original capital from env var or investor flows."""
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
    return original_capital


def _get_regime_context(settings):
    """Get regime context for intelligent theory generation."""
    try:
        hy_oas = get_hy_oas(settings)
        vix = get_vix(settings)
        yield_10y = get_10y_yield(settings)
        
        # Determine regime
        vix_val = vix.get("value") if vix else None
        hy_val = hy_oas.get("value") if hy_oas else None
        regime_label = get_regime_label(vix_val, hy_val)
        
        return {
            "vix": f"{vix_val:.1f}" if vix_val else "N/A",
            "hy_oas_bps": f"{hy_val:.0f}" if hy_val else "N/A",
            "yield_10y": f"{yield_10y.get('value'):.2f}%" if yield_10y and yield_10y.get('value') else "N/A",
            "regime": regime_label,
        }
    except Exception as e:
        print(f"[Positions] Could not fetch regime context: {e}")
        return {"vix": "N/A", "hy_oas_bps": "N/A", "yield_10y": "N/A", "regime": "UNKNOWN"}


def _parse_option_symbol(symbol):
    """Parse option symbol and return option info dict or None."""
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
                    return {
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
                return {
                    "underlying": underlying,
                    "expiry": str(exp),
                    "strike": strike,
                    "opt_type": opt_type_char,
                }
    except Exception:
        pass
    return None


def _get_live_twr(live_equity: float) -> float | None:
    """
    Calculate LIVE Time-Weighted Return by chaining:
    - Historical TWR from nav_sheet.csv (up to last snapshot)
    - Live return since last snapshot (from Alpaca)
    
    Formula: Live TWR = (1 + twr_cum) × (1 + return_since_snapshot) - 1
    """
    try:
        nav_sheet_path = os.path.join(os.path.dirname(__file__), "..", "data", "nav_sheet.csv")
        if not os.path.exists(nav_sheet_path):
            return None
        
        import csv
        with open(nav_sheet_path, "r") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        if not rows:
            return None
        
        latest = rows[-1]
        twr_cum_str = latest.get("twr_cum", "")
        last_equity_str = latest.get("equity", "")
        
        if not twr_cum_str or not last_equity_str:
            return None
        
        twr_cum = float(twr_cum_str)  # e.g., -0.056 = -5.6%
        last_equity = float(last_equity_str)
        
        if last_equity <= 0 or live_equity <= 0:
            return None
        
        # Return since last snapshot
        return_since_snapshot = (live_equity - last_equity) / last_equity
        
        # Chain the returns: (1 + cumulative) × (1 + recent) - 1
        live_twr = (1 + twr_cum) * (1 + return_since_snapshot) - 1
        
        return live_twr * 100  # Convert to percentage
        
    except Exception as e:
        print(f"[TWR] Live TWR calculation error: {e}")
        return None


# ============ DATA FUNCTIONS ============

def get_positions_data(force_refresh: bool = False):
    """
    Fetch positions and calculate P&L using conservative bid/ask marking.
    
    Uses short-lived cache (30s) to reduce API calls on rapid refreshes.
    Uses batch quote fetching for performance.
    """
    # Check cache first (unless force refresh)
    if not force_refresh:
        with POSITIONS_CACHE_LOCK:
            if POSITIONS_CACHE["data"] and POSITIONS_CACHE["timestamp"]:
                cache_age = (datetime.now(timezone.utc) - POSITIONS_CACHE["timestamp"]).total_seconds()
                if cache_age < POSITIONS_CACHE_TTL:
                    print(f"[Positions] Serving from cache (age: {cache_age:.1f}s)")
                    return POSITIONS_CACHE["data"]
    
    try:
        settings = load_settings()
        trading, data_client = make_clients(settings)
        account = trading.get_account()
        positions = trading.get_all_positions()
        
        # Use helper functions for cleaner code
        nav_equity = _get_nav_equity(account)
        original_capital = _get_original_capital()
        total_pnl = nav_equity - original_capital
        regime_context = _get_regime_context(settings)
        
        # OPTIMIZATION: Pre-parse all positions and batch quote requests
        position_data = []
        option_symbols = []
        stock_symbols = []
        
        for p in positions:
            symbol = str(getattr(p, "symbol", "") or "")
            if not symbol:
                continue
            
            opt_info = _parse_option_symbol(symbol)
            position_data.append({
                "raw": p,
                "symbol": symbol,
                "opt_info": opt_info,
                "qty": float(getattr(p, "qty", 0.0) or 0.0),
                "avg_entry": float(getattr(p, "avg_entry_price", 0.0) or 0.0),
                "current_price": float(getattr(p, "current_price", 0.0) or 0.0),
            })
            
            if opt_info:
                option_symbols.append(symbol)
            else:
                stock_symbols.append(symbol)
        
        # OPTIMIZATION: Batch fetch all quotes in 2 API calls (instead of N)
        print(f"[Positions] Batch fetching quotes: {len(option_symbols)} options, {len(stock_symbols)} stocks")
        option_quotes = _fetch_batch_option_quotes(data_client, option_symbols)
        stock_quotes = _fetch_batch_stock_quotes(data_client, stock_symbols)
        all_quotes = {**option_quotes, **stock_quotes}
        
        positions_list = []
        total_liquidation_value = 0.0
        
        # Process positions with pre-fetched quotes
        for pd in position_data:
            try:
                symbol = pd["symbol"]
                qty = pd["qty"]
                avg_entry = pd["avg_entry"]
                current_price = pd["current_price"]
                opt_info = pd["opt_info"]
                
                # Use pre-fetched quote
                quote = all_quotes.get(symbol)
                liquidation_price = current_price  # Fallback
                multiplier = 100 if opt_info else 1
                
                # Conservative mark: longs at bid, shorts at ask
                if quote:
                    if qty > 0:  # Long position - mark at bid
                        liquidation_price = quote["bid"] if quote["bid"] > 0 else current_price
                    else:  # Short position - mark at ask
                        liquidation_price = quote["ask"] if quote["ask"] > 0 else current_price
                
                # Calculate liquidation value and P&L
                entry_cost = avg_entry * multiplier * abs(qty) if avg_entry > 0 else 0
                liquidation_value = liquidation_price * multiplier * abs(qty)
                pnl = liquidation_value - entry_cost if qty > 0 else entry_cost - liquidation_value
                
                total_liquidation_value += liquidation_value
                
                # Build position dict
                position_dict = {
                    "symbol": symbol,
                    "qty": qty,
                    "market_value": liquidation_value,
                    "pnl": pnl,
                    "pnl_pct": (pnl / entry_cost * 100) if entry_cost > 0 else 0.0,
                    "current_price": liquidation_price,
                    "opt_info": opt_info,
                    "bid_ask_mark": True,
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
        
        # ============================================
        # LIVE Fund Return: Time-Weighted Return (TWR)
        # ============================================
        # TWR is industry standard (GIPS compliant) - removes cash flow distortion.
        # We chain historical TWR with live return since last snapshot.
        simple_return_pct = (liquidation_pnl / original_capital * 100) if original_capital > 0 else 0.0
        live_twr_pct = _get_live_twr(liquidation_nav)
        
        # Use live TWR if available, fallback to simple return
        return_pct = live_twr_pct if live_twr_pct is not None else simple_return_pct
        
        
        # Get benchmark performance since inception for comparison
        sp500_return = get_sp500_return_since_inception(settings)
        btc_return = get_btc_return_since_inception(settings)
        alpha_sp500 = return_pct - sp500_return if sp500_return is not None else None
        alpha_btc = return_pct - btc_return if btc_return is not None else None
        
        result = {
            "positions": positions_list,
            "total_pnl": liquidation_pnl,  # Conservative P&L at bid/ask
            "total_value": total_liquidation_value,
            "nav_equity": liquidation_nav,  # Liquidation NAV
            "original_capital": original_capital,
            "return_pct": return_pct,  # LIVE from Alpaca
            "sp500_return": sp500_return,
            "btc_return": btc_return,
            "alpha_sp500": alpha_sp500,
            "alpha_btc": alpha_btc,
            "cash_available": cash_available,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "mark_type": "liquidation",  # Flag that this is bid/ask marked
            "cached": False,
        }
        
        # Save to cache
        with POSITIONS_CACHE_LOCK:
            POSITIONS_CACHE["data"] = {**result, "cached": True}
            POSITIONS_CACHE["timestamp"] = datetime.now(timezone.utc)
        
        return result
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


# ============ FLASK ROUTES ============

@app.route('/')
def index():
    """Main dashboard page."""
    return render_template('dashboard.html')


@app.route('/api/positions')
def api_positions():
    """API endpoint for positions data - LIVE updates."""
    data = get_positions_data()
    response = jsonify(data)
    # Short cache for live updates
    response.headers['Cache-Control'] = 'public, max-age=10'
    return response


@app.route('/api/closed-trades')
def api_closed_trades():
    """API endpoint for closed trades (realized P&L) with caching."""
    # Check cache
    with TRADES_CACHE_LOCK:
        if TRADES_CACHE["data"] and TRADES_CACHE["timestamp"]:
            cache_age = (datetime.now(timezone.utc) - TRADES_CACHE["timestamp"]).total_seconds()
            if cache_age < TRADES_CACHE_TTL:
                response = jsonify(TRADES_CACHE["data"])
                response.headers['Cache-Control'] = 'public, max-age=60'
                return response
    
    try:
        data = get_closed_trades_data()
        # Save to cache
        with TRADES_CACHE_LOCK:
            TRADES_CACHE["data"] = data
            TRADES_CACHE["timestamp"] = datetime.now(timezone.utc)
        response = jsonify(data)
        response.headers['Cache-Control'] = 'public, max-age=60'
        return response
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e), "trades": [], "total_pnl": 0, "win_rate": 0})


@app.route('/api/regime-domains')
def api_regime_domains():
    """API endpoint for regime domain indicators with caching."""
    # Check cache
    with DOMAINS_CACHE_LOCK:
        if DOMAINS_CACHE["data"] and DOMAINS_CACHE["timestamp"]:
            cache_age = (datetime.now(timezone.utc) - DOMAINS_CACHE["timestamp"]).total_seconds()
            if cache_age < DOMAINS_CACHE_TTL:
                response = jsonify(DOMAINS_CACHE["data"])
                response.headers['Cache-Control'] = 'public, max-age=120'
                return response
    
    try:
        settings = load_settings()
        data = get_regime_domains_data(settings)
        # Save to cache
        with DOMAINS_CACHE_LOCK:
            DOMAINS_CACHE["data"] = data
            DOMAINS_CACHE["timestamp"] = datetime.now(timezone.utc)
        response = jsonify(data)
        response.headers['Cache-Control'] = 'public, max-age=120'
        return response
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e), "domains": {}})


@app.route('/api/investors')
def api_investors():
    """API endpoint for investor ledger - LIVE updates."""
    # Check cache
    with INVESTORS_CACHE_LOCK:
        if INVESTORS_CACHE["data"] and INVESTORS_CACHE["timestamp"]:
            cache_age = (datetime.now(timezone.utc) - INVESTORS_CACHE["timestamp"]).total_seconds()
            if cache_age < INVESTORS_CACHE_TTL:
                response = jsonify(INVESTORS_CACHE["data"])
                response.headers['Cache-Control'] = 'public, max-age=10'
                return response
    
    try:
        data = get_investor_data()
        # Save to cache
        with INVESTORS_CACHE_LOCK:
            INVESTORS_CACHE["data"] = data
            INVESTORS_CACHE["timestamp"] = datetime.now(timezone.utc)
        response = jsonify(data)
        response.headers['Cache-Control'] = 'public, max-age=10'
        return response
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e), "investors": [], "nav_per_unit": 1.0, "total_units": 0})


def get_investor_data():
    """
    Fetch investor ledger with unitized returns using LIVE Alpaca NAV.
    
    This combines:
    - Static investor flows (contributions) from nav_investor_flows.csv
    - Historical NAV snapshots from nav_sheet.csv (for unit price history)
    - LIVE current equity from Alpaca (for real-time values)
    """
    try:
        # Paths to data files
        nav_sheet_path = os.path.join(os.path.dirname(__file__), "..", "data", "nav_sheet.csv")
        investor_flows_path = os.path.join(os.path.dirname(__file__), "..", "data", "nav_investor_flows.csv")
        
        if not os.path.exists(investor_flows_path):
            return {"error": "Investor flows file not found", "investors": [], "nav_per_unit": 1.0, "total_units": 0}
        
        # Read investor flows (contributions)
        import csv
        
        flows = []
        with open(investor_flows_path, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                flows.append({
                    "ts": row.get("ts", ""),
                    "code": row.get("code", ""),
                    "amount": float(row.get("amount", 0)),
                })
        
        # Read historical NAV snapshots (for unit price calculation at each flow)
        nav_rows = []
        if os.path.exists(nav_sheet_path):
            with open(nav_sheet_path, "r") as f:
                reader = csv.DictReader(f)
                nav_rows = list(reader)
        
        # ============================================
        # LIVE: Get current equity from positions API
        # This ensures investor values reflect real-time NAV
        # ============================================
        live_equity = None
        try:
            positions_data = get_positions_data()
            live_equity = positions_data.get("nav_equity")
            if not live_equity or live_equity <= 0:
                # Fallback to direct Alpaca call
                settings = load_settings()
                trading, _ = make_clients(settings)
                account = trading.get_account()
                if account:
                    live_equity = float(getattr(account, 'equity', 0) or 0)
        except Exception as e:
            print(f"[Investors] Live equity fetch error: {e}")
        
        # Final fallback to last CSV snapshot
        if not live_equity or live_equity <= 0:
            if nav_rows:
                live_equity = float(nav_rows[-1].get("equity", 0))
        
        # ============================================
        # Compute unitization from historical events
        # Units are assigned at the NAV/unit price when each flow occurred
        # ============================================
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
                # Issue units at current NAV/unit price
                if nav_per_unit <= 0:
                    nav_per_unit = 1.0
                du = float(obj["amount"]) / float(nav_per_unit)
                code = obj["code"]
                units_by[code] = float(units_by.get(code, 0.0)) + du
                total_units += du
            else:
                # NAV snapshot updates the unit price
                if total_units > 0:
                    equity = float(obj.get("equity", 0))
                    if equity > 0:
                        nav_per_unit = equity / total_units
        
        # ============================================
        # LIVE: Calculate current NAV/unit from live equity
        # ============================================
        if total_units > 0 and live_equity and live_equity > 0:
            nav_per_unit = live_equity / total_units
        
        # Calculate investor values based on LIVE NAV/unit
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
            "equity": round(live_equity, 2) if live_equity else 0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "live": True,  # Flag indicating this uses live data
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
                    "url": get_event_source_url(event_name),
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
        return "No positions", {}
    
    longs = []
    shorts = []
    
    for p in positions:
        symbol = p.get("symbol", "")
        qty = p.get("qty", 0)
        opt = p.get("opt_info")
        
        if opt:
            # Option position
            underlying = opt.get("underlying", symbol[:3])
            opt_type = opt.get("opt_type", opt.get("type", "")).upper()
            
            if qty > 0:  # Long options
                if opt_type in ["PUT", "P"]:
                    shorts.append(f"{underlying} (puts)")
                elif opt_type in ["CALL", "C"]:
                    longs.append(f"{underlying} (calls)")
            else:  # Short options
                if opt_type in ["PUT", "P"]:
                    longs.append(f"{underlying} (short puts)")
                elif opt_type in ["CALL", "C"]:
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


# ============ ANALYSIS FUNCTIONS ============

def _categorize_portfolio_positions(positions):
    """
    Categorize portfolio positions by their macro sensitivity for scenario analysis.
    
    Returns dict with structured position breakdown and scenario impacts.
    """
    if not positions:
        return {
            "summary": "No positions",
            "by_category": {},
            "scenario_matrix": {},
        }
    
    # Category buckets
    categories = {
        "long_equity_calls": [],      # Bullish equity (profit if market rallies)
        "long_equity_puts": [],       # Bearish equity (profit if market sells off)
        "long_vol": [],               # Long volatility (profit if VIX spikes)
        "long_rates_sensitive": [],   # Rates plays (TLT calls = profit if yields fall)
        "long_credit_puts": [],       # Credit stress plays (HYG puts = profit if spreads widen)
        "long_commodity": [],         # Commodity exposure (gold, oil, etc.)
        "short_equity_calls": [],     # Short calls (profit if market flat/down)
        "short_equity_puts": [],      # Short puts (profit if market flat/up)
        "etf_long": [],               # Long ETF shares
        "etf_short": [],              # Short ETF shares
    }
    
    # Known ETF classifications
    vol_etfs = ["VIXM", "VXX", "UVXY", "SVXY", "VIXY"]
    rates_etfs = ["TLT", "IEF", "SHY", "TBT", "TMF", "TMV"]
    credit_etfs = ["HYG", "JNK", "LQD", "BKLN", "HYGH"]
    commodity_etfs = ["GLDM", "GLD", "SLV", "USO", "UNG", "DBA", "DBB"]
    em_etfs = ["FXI", "EEM", "EWZ", "EWY", "EWT", "MCHI"]
    growth_etfs = ["QQQ", "ARKK", "TAN", "ICLN", "SOXX"]
    
    for p in positions:
        symbol = p.get("symbol", "")
        qty = p.get("qty", 0)
        opt = p.get("opt_info")
        pnl = p.get("pnl", 0)
        mv = p.get("market_value", 0)
        
        if not symbol or qty == 0:
            continue
        
        pos_entry = {
            "symbol": symbol,
            "qty": qty,
            "pnl": pnl,
            "market_value": mv,
        }
        
        if opt:
            underlying = opt.get("underlying", symbol[:3]).upper()
            opt_type = opt.get("opt_type", opt.get("type", "")).upper()
            strike = opt.get("strike", 0)
            expiry = opt.get("expiry", "")
            
            pos_entry["underlying"] = underlying
            pos_entry["opt_type"] = opt_type
            pos_entry["strike"] = strike
            pos_entry["expiry"] = expiry
            
            is_call = opt_type in ["CALL", "C"]
            is_put = opt_type in ["PUT", "P"]
            is_long = qty > 0
            
            # Categorize by underlying and option type
            if underlying in vol_etfs:
                if is_long and is_call:
                    categories["long_vol"].append(pos_entry)
                elif is_long and is_put:
                    categories["short_equity_puts"].append(pos_entry)  # Rare but possible
            elif underlying in rates_etfs:
                if is_long and is_call:
                    categories["long_rates_sensitive"].append(pos_entry)
                elif is_long and is_put:
                    categories["long_equity_puts"].append(pos_entry)  # Bearish bonds
            elif underlying in credit_etfs:
                if is_long and is_put:
                    categories["long_credit_puts"].append(pos_entry)
                elif is_long and is_call:
                    categories["long_equity_calls"].append(pos_entry)
            elif underlying in commodity_etfs:
                if is_long:
                    categories["long_commodity"].append(pos_entry)
            else:
                # General equity/sector ETF
                if is_long and is_call:
                    categories["long_equity_calls"].append(pos_entry)
                elif is_long and is_put:
                    categories["long_equity_puts"].append(pos_entry)
                elif not is_long and is_call:
                    categories["short_equity_calls"].append(pos_entry)
                elif not is_long and is_put:
                    categories["short_equity_puts"].append(pos_entry)
        else:
            # Stock/ETF shares
            ticker = symbol.upper()
            if qty > 0:
                if ticker in vol_etfs:
                    categories["long_vol"].append(pos_entry)
                elif ticker in commodity_etfs:
                    categories["long_commodity"].append(pos_entry)
                else:
                    categories["etf_long"].append(pos_entry)
            else:
                categories["etf_short"].append(pos_entry)
    
    # Build scenario impact matrix
    scenario_matrix = {
        "risk_off_spike": {  # VIX +10pts, HY spreads +100bp, equities -10%
            "winners": [],
            "losers": [],
        },
        "rates_surge": {  # 10Y +50bp, growth equities -5%
            "winners": [],
            "losers": [],
        },
        "goldilocks_rally": {  # VIX -5pts, equities +5%
            "winners": [],
            "losers": [],
        },
        "credit_stress": {  # HY spreads +150bp, HYG -5%
            "winners": [],
            "losers": [],
        },
    }
    
    # Map categories to scenario impacts
    for pos in categories["long_vol"]:
        scenario_matrix["risk_off_spike"]["winners"].append(pos["symbol"])
        scenario_matrix["goldilocks_rally"]["losers"].append(pos["symbol"])
    
    for pos in categories["long_equity_puts"]:
        scenario_matrix["risk_off_spike"]["winners"].append(pos["symbol"])
        scenario_matrix["goldilocks_rally"]["losers"].append(pos["symbol"])
    
    for pos in categories["long_equity_calls"]:
        scenario_matrix["goldilocks_rally"]["winners"].append(pos["symbol"])
        scenario_matrix["risk_off_spike"]["losers"].append(pos["symbol"])
        scenario_matrix["rates_surge"]["losers"].append(pos["symbol"])
    
    for pos in categories["long_rates_sensitive"]:
        scenario_matrix["rates_surge"]["losers"].append(pos["symbol"])
        # Rates falling = TLT calls win (flight to quality)
        scenario_matrix["risk_off_spike"]["winners"].append(pos["symbol"])
    
    for pos in categories["long_credit_puts"]:
        scenario_matrix["credit_stress"]["winners"].append(pos["symbol"])
        scenario_matrix["risk_off_spike"]["winners"].append(pos["symbol"])
        scenario_matrix["goldilocks_rally"]["losers"].append(pos["symbol"])
    
    for pos in categories["long_commodity"]:
        # Gold typically wins in risk-off
        if "GLD" in pos["symbol"] or "GLDM" in pos["symbol"]:
            scenario_matrix["risk_off_spike"]["winners"].append(pos["symbol"])
    
    # Build summary string
    active_categories = {k: v for k, v in categories.items() if v}
    summary_parts = []
    
    if categories["long_vol"]:
        tickers = [p["underlying"] if "underlying" in p else p["symbol"] for p in categories["long_vol"]]
        summary_parts.append(f"Long Vol: {', '.join(set(tickers))}")
    
    if categories["long_equity_puts"]:
        tickers = [p.get("underlying", p["symbol"]) for p in categories["long_equity_puts"]]
        summary_parts.append(f"Long Puts: {', '.join(set(tickers))}")
    
    if categories["long_equity_calls"]:
        tickers = [p.get("underlying", p["symbol"]) for p in categories["long_equity_calls"]]
        summary_parts.append(f"Long Calls: {', '.join(set(tickers))}")
    
    if categories["long_credit_puts"]:
        tickers = [p.get("underlying", p["symbol"]) for p in categories["long_credit_puts"]]
        summary_parts.append(f"Credit Puts: {', '.join(set(tickers))}")
    
    if categories["long_rates_sensitive"]:
        tickers = [p.get("underlying", p["symbol"]) for p in categories["long_rates_sensitive"]]
        summary_parts.append(f"Rates Plays: {', '.join(set(tickers))}")
    
    if categories["long_commodity"]:
        tickers = [p.get("underlying", p["symbol"]) for p in categories["long_commodity"]]
        summary_parts.append(f"Commodities: {', '.join(set(tickers))}")
    
    return {
        "summary": " | ".join(summary_parts) if summary_parts else "No directional exposure",
        "by_category": active_categories,
        "scenario_matrix": scenario_matrix,
    }


def _build_portfolio_from_alpaca(positions_data, cash_available):
    """
    Build a Portfolio object from Alpaca positions for Monte Carlo simulation.
    
    Returns a Portfolio with Position objects including calculated greeks.
    """
    from ai_options_trader.portfolio.positions import Portfolio, Position
    from datetime import datetime
    
    portfolio_positions = []
    
    for p in positions_data:
        symbol = p.get("symbol", "")
        qty = p.get("qty", 0)
        current_price = p.get("current_price", 0) or 0
        market_value = abs(p.get("market_value", 0) or 0)
        opt_info = p.get("opt_info")
        
        if not symbol or qty == 0:
            continue
        
        if opt_info:
            # Option position
            underlying = opt_info.get("underlying", symbol[:3])
            strike = opt_info.get("strike", 0)
            expiry_str = opt_info.get("expiry", "")
            opt_type = opt_info.get("opt_type", "P").upper()
            
            # Parse expiry
            try:
                expiry = datetime.strptime(expiry_str, "%Y-%m-%d") if expiry_str else None
            except:
                expiry = None
            
            # Estimate underlying price from strike proximity
            # (In production, fetch live underlying price)
            underlying_price = strike * 1.05 if opt_type in ["P", "PUT"] else strike * 0.95
            
            # Entry IV estimate based on position type
            entry_iv = 0.25  # Default
            if "VIX" in underlying.upper():
                entry_iv = 0.90
            elif "HYG" in underlying.upper():
                entry_iv = 0.18
            elif "TAN" in underlying.upper():
                entry_iv = 0.35
            
            pos = Position(
                ticker=symbol,
                quantity=qty,
                position_type="put" if opt_type in ["P", "PUT"] else "call",
                strike=strike,
                expiry=expiry,
                entry_price=current_price if current_price > 0 else (market_value / (abs(qty) * 100) if qty != 0 else 1),
                entry_underlying_price=underlying_price,
                entry_iv=entry_iv,
            )
            
            # Calculate greeks
            pos.calculate_greeks(underlying_price, entry_iv)
            portfolio_positions.append(pos)
        else:
            # Stock/ETF position
            pos = Position(
                ticker=symbol,
                quantity=qty,
                position_type="etf" if len(symbol) <= 5 else "stock",
                entry_price=current_price if current_price > 0 else (market_value / abs(qty) if qty != 0 else 1),
            )
            pos.calculate_greeks(pos.entry_price, 0.20)
            portfolio_positions.append(pos)
    
    return Portfolio(positions=portfolio_positions, cash=cash_available)


def _run_monte_carlo_simulation(portfolio, vix_val, hy_val, regime_label, n_scenarios=2000):
    """
    Run actual Monte Carlo simulation using the v01 engine.
    
    Returns rich metrics including attribution and tail risk analysis.
    """
    import numpy as np
    from ai_options_trader.llm.scenarios.monte_carlo_v01 import MonteCarloV01, ScenarioAssumptions
    
    # Map dashboard regime to MC regime
    regime_map = {
        "RISK-ON": "GOLDILOCKS",
        "CAUTIOUS": "ALL",  # Neutral
        "RISK-OFF": "RISK_OFF",
        "UNKNOWN": "ALL",
    }
    mc_regime = regime_map.get(regime_label, "ALL")
    
    # Adjust regime based on VIX level for more dynamic behavior
    if vix_val:
        if vix_val > 30:
            mc_regime = "RISK_OFF"
        elif vix_val > 25:
            mc_regime = "CREDIT_STRESS" if (hy_val and hy_val > 400) else "RATES_SHOCK"
        elif vix_val < 14:
            mc_regime = "VOL_CRUSH"
    
    # Get regime-conditional assumptions
    assumptions = ScenarioAssumptions.for_regime(mc_regime, horizon_months=6)
    
    # Run simulation
    mc = MonteCarloV01(portfolio, assumptions)
    results = mc.generate_scenarios(n_scenarios=n_scenarios)
    analysis = mc.analyze_results(results)
    
    # Extract top risk driver from CVaR attribution
    cvar_attr = analysis.get("cvar_attribution", {})
    top_risk_driver = None
    if cvar_attr:
        # Most negative contributor in tail scenarios
        sorted_attr = sorted(cvar_attr.items(), key=lambda x: x[1])
        if sorted_attr:
            top_risk_driver = sorted_attr[0][0]  # Ticker with most negative attribution
    
    # Format worst scenario for display
    worst_scenarios = analysis.get("top_3_losers", [])
    worst_scenario_desc = None
    if worst_scenarios:
        worst = worst_scenarios[0]
        moves = worst.get("equity_moves", {})
        if moves:
            # Find the biggest mover
            biggest_move = max(moves.items(), key=lambda x: abs(x[1]))
            worst_scenario_desc = f"{biggest_move[0]} {biggest_move[1]*100:+.0f}%"
            if worst.get("had_jump"):
                worst_scenario_desc += " (crash)"
    
    return {
        "mean_pnl_pct": round(analysis.get("mean_pnl_pct", 0), 4),
        "median_pnl_pct": round(analysis.get("median_pnl_pct", 0), 4),
        "var_95_pct": round(analysis.get("var_95_pct", 0), 4),
        "cvar_95_pct": round(analysis.get("cvar_95_pct", 0), 4),
        "prob_positive": round(analysis.get("prob_positive", 0.5), 3),
        "prob_loss_gt_10pct": round(analysis.get("prob_loss_gt_10pct", 0), 3),
        "prob_loss_gt_20pct": round(analysis.get("prob_loss_gt_20pct", 0), 3),
        "skewness": round(analysis.get("skewness", 0), 2),
        "max_loss_pct": round(analysis.get("max_loss_pct", 0), 4),
        "max_gain_pct": round(analysis.get("max_gain_pct", 0), 4),
        "top_risk_driver": top_risk_driver,
        "worst_scenario": worst_scenario_desc,
        "regime": regime_label,
        "mc_regime": mc_regime,
        "horizon_months": 6,
        "n_scenarios": n_scenarios,
    }


def _calculate_monte_carlo_forecast(vix_val, hy_val, regime_label, positions_data=None, cash_available=0):
    """
    Calculate Monte Carlo forecast - uses real simulation if positions available,
    falls back to simplified estimate otherwise.
    """
    # Try to run real Monte Carlo if we have positions
    if positions_data and len(positions_data) > 0:
        try:
            portfolio = _build_portfolio_from_alpaca(positions_data, cash_available)
            if portfolio.positions:
                return _run_monte_carlo_simulation(portfolio, vix_val, hy_val, regime_label)
        except Exception as e:
            print(f"[MC] Real simulation failed, using fallback: {e}")
    
    # Fallback to simplified estimate (for empty portfolios or errors)
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
        vol_mult = 1 + (vix_val - 20) / 30
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


def _refresh_mc_cache():
    """Refresh Monte Carlo simulation cache."""
    global MC_CACHE
    print(f"[MC] Refreshing simulation at {datetime.now(timezone.utc).isoformat()}")
    
    try:
        settings = load_settings()
        
        # Get current regime data
        vix = get_vix(settings)
        hy_oas = get_hy_oas(settings)
        vix_val = vix.get("value") if vix else None
        hy_val = hy_oas.get("value") if hy_oas else None
        regime_label = get_regime_label(vix_val, hy_val)
        
        # Get positions data
        positions_data = get_positions_data()
        positions_list = positions_data.get("positions", [])
        cash_available = positions_data.get("cash_available", 0)
        
        # Run Monte Carlo
        forecast = _calculate_monte_carlo_forecast(
            vix_val, hy_val, regime_label,
            positions_data=positions_list,
            cash_available=cash_available
        )
        
        with MC_CACHE_LOCK:
            MC_CACHE["forecast"] = forecast
            MC_CACHE["timestamp"] = datetime.now(timezone.utc).isoformat()
            MC_CACHE["last_refresh"] = datetime.now(timezone.utc)
        
        print(f"[MC] Cache refreshed: mean={forecast.get('mean_pnl_pct')}, VaR95={forecast.get('var_95_pct')}")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[MC] Cache refresh failed: {e}")


def _mc_background_refresh():
    """Background thread that refreshes MC simulation every hour."""
    while True:
        try:
            time.sleep(MC_REFRESH_INTERVAL)
            _refresh_mc_cache()
        except Exception as e:
            print(f"[MC] Background refresh error: {e}")
            time.sleep(60)  # Wait a minute before retrying


# ============ TRAFFIC LIGHT STATUS HELPERS ============

def _get_regime_status(vix_val, hy_val):
    """Determine overall market regime based on VIX and HY spreads."""
    if vix_val is None:
        return "UNKNOWN", "gray"
    if vix_val > 25 or (hy_val and hy_val > 400):
        return "RISK-OFF", "red"
    elif vix_val > 18 or (hy_val and hy_val > 350):
        return "CAUTIOUS", "yellow"
    else:
        return "RISK-ON", "green"


def _get_vol_status(vix_val):
    """Determine volatility status based on VIX level."""
    if vix_val is None:
        return "UNKNOWN", "gray"
    if vix_val > 25:
        return "ELEVATED", "red"
    elif vix_val > 18:
        return "MODERATE", "yellow"
    else:
        return "LOW", "green"


def _get_credit_status(hy_val):
    """Determine credit market status based on HY spreads."""
    if hy_val is None:
        return "UNKNOWN", "gray"
    if hy_val > 400:
        return "STRESSED", "red"
    elif hy_val > 325:
        return "WATCHING", "yellow"
    else:
        return "STABLE", "green"


def _get_rates_status(yield_val):
    """
    Determine rates status based on 10Y yield.
    
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


def _build_vix_context(vix_val):
    """Build quantitative VIX context string for analysis."""
    if not vix_val:
        return ""
    if vix_val < 14:
        return f"VIX at {vix_val:.1f} (5th-15th percentile) — implied vol compressed, hedges cheap but portfolio vol positions face theta decay"
    elif vix_val < 18:
        return f"VIX at {vix_val:.1f} (25th-45th percentile) — normal regime, balanced convexity vs carry trade-off"
    elif vix_val < 22:
        return f"VIX at {vix_val:.1f} (50th-70th percentile) — elevated regime, event risk priced, vol positions approaching profitability zone"
    elif vix_val < 28:
        return f"VIX at {vix_val:.1f} (75th-90th percentile) — stressed regime, term structure likely inverted, vol positions should be delta-hedging"
    else:
        return f"VIX at {vix_val:.1f} (>90th percentile) — crisis regime, vol positions at max vega, consider rolling strikes"


def _build_hy_context(hy_val):
    """Build quantitative HY spread context string for analysis."""
    if not hy_val:
        return ""
    if hy_val < 300:
        return f"HY OAS at {hy_val:.0f}bp (tight) — credit risk underpriced, HYG put holders waiting for catalyst"
    elif hy_val < 350:
        return f"HY OAS at {hy_val:.0f}bp (normal) — credit benign but tightening cycle mature, watching for spread decompression"
    elif hy_val < 450:
        return f"HY OAS at {hy_val:.0f}bp (widening) — early stress signals, HYG put deltas expanding, equity-credit correlation rising"
    else:
        return f"HY OAS at {hy_val:.0f}bp (stressed) — credit dislocation, HYG puts deep ITM, contagion risk to equity"


def _build_rates_context(yield_val):
    """Build quantitative rates context string for analysis."""
    if not yield_val:
        return ""
    if yield_val < 3.5:
        return f"10Y at {yield_val:.2f}% (dovish) — duration tailwind, TLT calls profitable, growth outperforming value"
    elif yield_val < 4.2:
        return f"10Y at {yield_val:.2f}% (neutral) — Fed at terminal, duration-sensitive plays range-bound"
    elif yield_val < 4.7:
        return f"10Y at {yield_val:.2f}% (restrictive) — term premium rebuilding, growth/tech equity multiples under pressure"
    else:
        return f"10Y at {yield_val:.2f}% (hawkish extreme) — fiscal supply pressure, equity multiple compression accelerating"


def _build_scenario_impacts(scenario_matrix):
    """Build scenario impact descriptions from the scenario matrix."""
    impacts = []
    
    # Risk-off scenario
    risk_off_winners = scenario_matrix.get("risk_off_spike", {}).get("winners", [])
    risk_off_losers = scenario_matrix.get("risk_off_spike", {}).get("losers", [])
    if risk_off_winners or risk_off_losers:
        impact = "RISK-OFF SPIKE (VIX +10, SPX -10%): "
        parts = []
        if risk_off_winners:
            parts.append(f"Winners: {', '.join(list(set(risk_off_winners))[:3])}")
        if risk_off_losers:
            parts.append(f"Losers: {', '.join(list(set(risk_off_losers))[:3])}")
        impacts.append(impact + " | ".join(parts))
    
    # Goldilocks rally
    rally_winners = scenario_matrix.get("goldilocks_rally", {}).get("winners", [])
    rally_losers = scenario_matrix.get("goldilocks_rally", {}).get("losers", [])
    if rally_winners or rally_losers:
        impact = "GOLDILOCKS RALLY (VIX -5, SPX +5%): "
        parts = []
        if rally_winners:
            parts.append(f"Winners: {', '.join(list(set(rally_winners))[:3])}")
        if rally_losers:
            parts.append(f"Losers: {', '.join(list(set(rally_losers))[:3])}")
        impacts.append(impact + " | ".join(parts))
    
    # Credit stress
    credit_winners = scenario_matrix.get("credit_stress", {}).get("winners", [])
    if credit_winners:
        impacts.append(f"CREDIT STRESS (HY +150bp): Winners: {', '.join(list(set(credit_winners))[:3])}")
    
    return impacts


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
    hy_oas = get_hy_oas(settings)
    vix = get_vix(settings)
    yield_10y = get_10y_yield(settings)
    
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
    
    # Build regime snapshot for structured output
    regime_snapshot = {
        "hy_oas_bps": hy_oas.get("value") if hy_oas else None,
        "vix": vix.get("value") if vix else None,
        "yield_10y": yield_10y.get("value") if yield_10y else None,
        "portfolio_nav": positions_data.get("nav_equity"),
        "portfolio_pnl": positions_data.get("total_pnl"),
    }
    
    # Determine traffic light statuses using module-level helpers
    vix_val = regime_snapshot.get("vix")
    hy_val = regime_snapshot.get("hy_oas_bps")
    yield_val = regime_snapshot.get("yield_10y")
    
    regime_label, regime_color = _get_regime_status(vix_val, hy_val)
    vol_label, vol_color = _get_vol_status(vix_val)
    credit_label, credit_color = _get_credit_status(hy_val)
    rates_label, rates_color = _get_rates_status(yield_val)
    
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
    
    # Generate LLM insight with professional macro brief style
    try:
        from openai import OpenAI
        client = OpenAI(api_key=settings.openai_api_key)
        
        # Get detailed portfolio categorization for scenario analysis
        portfolio_positions = positions_data.get("positions", []) if positions_data else []
        portfolio_analysis = _categorize_portfolio_positions(portfolio_positions)
        scenario_matrix = portfolio_analysis.get("scenario_matrix", {})
        
        # Build quantitative regime context using module-level helpers
        vix_context = _build_vix_context(vix_val)
        hy_context = _build_hy_context(hy_val)
        rate_context = _build_rates_context(yield_val)
        
        # Build scenario impact descriptions
        scenario_impacts = _build_scenario_impacts(scenario_matrix)
        
        # Format events with significance
        events_context = ""
        if fed_fiscal_events:
            event_details = []
            for e in fed_fiscal_events[:4]:
                evt_name = e.get("event", "")
                actual = e.get("actual")
                estimate = e.get("estimate")
                
                if actual is not None and estimate is not None:
                    try:
                        diff = float(actual) - float(estimate)
                        direction = "beat" if diff > 0 else "miss"
                        event_details.append(f"{evt_name}: {actual} vs {estimate} ({direction})")
                    except:
                        event_details.append(f"{evt_name}: {actual}")
                elif actual is not None:
                    event_details.append(f"{evt_name}: {actual}")
                else:
                    event_details.append(f"{evt_name} (pending)")
            events_context = " | ".join(event_details)
        
        # Format headlines
        news_context = ""
        if headlines:
            news_items = [h.get("headline", "")[:80] for h in headlines[:3] if h]
            news_context = " | ".join(news_items)
        
        # Construct professional macro brief prompt
        prompt = f"""You are a senior macro trader writing a morning brief for the investment committee. 
Write a professional market overview that connects macro conditions to our specific portfolio positions.

═══════════════════════════════════════════════════════════════
MARKET REGIME: {regime_label}
═══════════════════════════════════════════════════════════════

QUANTITATIVE LEVELS:
• {vix_context or "VIX data unavailable"}
• {hy_context or "Credit spread data unavailable"}
• {rate_context or "Rates data unavailable"}

PORTFOLIO POSITIONING:
{portfolio_analysis.get("summary", "No positions")}

SCENARIO P&L ATTRIBUTION:
{chr(10).join(scenario_impacts) if scenario_impacts else "No scenario analysis available"}

TODAY'S CALENDAR:
{events_context if events_context else "No significant releases"}

RELEVANT HEADLINES:
{news_context if news_context else "None"}

═══════════════════════════════════════════════════════════════
INSTRUCTIONS: Write a 3-4 sentence macro brief in PROFESSIONAL TONE:

1. REGIME ASSESSMENT: State the current macro regime with quantitative anchors (VIX level, spread levels). Be direct.

2. PORTFOLIO IMPACT: Explain how current conditions affect our specific positions:
   - For LONG PUTS: Describe what needs to happen for them to pay (underlying decline, vol spike)
   - For LONG CALLS: Describe the tailwind/headwind they face
   - For VOL POSITIONS: Comment on whether vol is cheap/expensive relative to realized

3. KEY RISK: Name ONE specific catalyst or threshold that would shift the portfolio P&L materially.

STYLE REQUIREMENTS:
- Write like a macro PM, not a news anchor
- Use precise language: "10Y above 4.50% → multiple compression → long puts accelerate"
- No hedging words ("could", "might", "possibly")
- No sentiment language ("confident", "optimistic")
- Reference specific positions by underlying (e.g., "HYG puts", "VIXM calls")
- Maximum 4 sentences"""

        response = client.chat.completions.create(
            model=settings.openai_model or "gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=350,
        )
        
        insight = response.choices[0].message.content.strip()
    except Exception as e:
        print(f"[Palmer] LLM error: {e}")
        insight = "Market analysis temporarily unavailable."
    
    # Use cached Monte Carlo forecast (updated hourly in separate thread)
    with MC_CACHE_LOCK:
        mc_forecast = MC_CACHE.get("forecast")
    
    # Fallback if MC cache not ready yet
    if mc_forecast is None:
        mc_forecast = _calculate_monte_carlo_forecast(
            vix_val, hy_val, regime_label,
            positions_data=positions_data.get("positions", []),
            cash_available=positions_data.get("cash_available", 0)
        )
    
    # Get portfolio analysis for return value (may have been generated during LLM call)
    try:
        portfolio_analysis_output = _categorize_portfolio_positions(positions_data.get("positions", []))
    except Exception:
        portfolio_analysis_output = {"summary": "Analysis unavailable", "scenario_matrix": {}}
    
    return {
        "analysis": insight,
        "regime_snapshot": regime_snapshot,
        "traffic_lights": {
            "regime": {"label": regime_label, "color": regime_color},
            "volatility": {"label": vol_label, "color": vol_color, "value": f"VIX {vix_val:.1f}" if vix_val else "N/A"},
            "credit": {"label": credit_label, "color": credit_color, "value": f"{hy_val:.0f}bp" if hy_val else "N/A"},
            "rates": {"label": rates_label, "color": rates_color, "value": f"{yield_val:.2f}%" if yield_val else "N/A"},
        },
        "portfolio_analysis": {
            "summary": portfolio_analysis_output.get("summary", ""),
            "scenario_matrix": portfolio_analysis_output.get("scenario_matrix", {}),
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
            PALMER_CACHE["portfolio_analysis"] = result.get("portfolio_analysis")
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
        
        # Return cached data including monte_carlo and portfolio_analysis
        return jsonify({
            "analysis": PALMER_CACHE.get("analysis"),
            "regime_snapshot": PALMER_CACHE.get("regime_snapshot"),
            "traffic_lights": PALMER_CACHE.get("traffic_lights"),
            "portfolio_analysis": PALMER_CACHE.get("portfolio_analysis"),
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


@app.route('/api/monte-carlo')
def api_monte_carlo():
    """Monte Carlo simulation results. Refreshes automatically every hour."""
    with MC_CACHE_LOCK:
        forecast = MC_CACHE.get("forecast")
        timestamp = MC_CACHE.get("timestamp")
    
    if forecast is None:
        return jsonify({"error": "Monte Carlo simulation not ready yet. Please wait.", "timestamp": None})
    
    return jsonify({
        "forecast": forecast,
        "timestamp": timestamp,
    })


@app.route('/api/monte-carlo/force-refresh')
def api_monte_carlo_force():
    """Admin-only: Force refresh Monte Carlo simulation. Requires secret."""
    secret = request.args.get("secret", "")
    if secret != ADMIN_SECRET:
        return jsonify({"error": "Unauthorized. Admin secret required."}), 403
    
    _refresh_mc_cache()
    return jsonify({"message": "Monte Carlo refreshed", "timestamp": datetime.now(timezone.utc).isoformat()})


# ============ NEWS & CALENDAR API ============

@app.route('/api/market-news')
def api_market_news():
    """API endpoint for portfolio ticker news and economic calendar."""
    try:
        return jsonify(get_market_news_data())
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e), "news": [], "calendar": []})


def get_market_news_data():
    """Fetch news for portfolio tickers and upcoming economic events."""
    import requests
    
    news_items = []
    calendar_items = []
    
    try:
        settings = load_settings()
    except Exception:
        return {"news": news_items, "calendar": calendar_items, "error": "Settings not available"}
    
    # Get portfolio tickers
    portfolio_tickers = set()
    try:
        positions_data = get_positions_data()
        for pos in positions_data.get("positions", []):
            sym = pos.get("symbol", "")
            # Extract underlying from options (OCC format)
            if len(sym) > 10:
                underlying = sym[:6].rstrip("0123456789 ")
                portfolio_tickers.add(underlying)
            else:
                portfolio_tickers.add(sym)
    except Exception as e:
        print(f"[News] Error getting portfolio tickers: {e}")
        portfolio_tickers = {"SPY", "QQQ"}  # Fallback to broad market
    
    # Fetch news from FMP
    if settings.FMP_API_KEY and portfolio_tickers:
        try:
            tickers_str = ",".join(list(portfolio_tickers)[:5])  # Limit to 5 tickers
            url = "https://financialmodelingprep.com/api/v3/stock_news"
            resp = requests.get(url, params={
                "tickers": tickers_str,
                "limit": 8,
                "apikey": settings.FMP_API_KEY
            }, timeout=10)
            data = resp.json()
            
            if isinstance(data, list):
                for item in data[:8]:
                    news_items.append({
                        "title": item.get("title", "")[:100],
                        "symbol": item.get("symbol", ""),
                        "source": item.get("site", ""),
                        "url": item.get("url", ""),
                        "time": item.get("publishedDate", "")[:16],  # Trim to date/time
                    })
        except Exception as e:
            print(f"[News] FMP news error: {e}")
    
    # Fetch economic calendar from FMP
    if settings.FMP_API_KEY:
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            next_week = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
            url = "https://financialmodelingprep.com/api/v3/economic_calendar"
            resp = requests.get(url, params={
                "from": today,
                "to": next_week,
                "apikey": settings.FMP_API_KEY
            }, timeout=10)
            data = resp.json()
            
            # Filter for high-impact US events
            high_impact_keywords = ["CPI", "PPI", "NFP", "FOMC", "Fed", "GDP", "Unemployment", "Retail Sales", "PCE", "Jobs"]
            if isinstance(data, list):
                for item in data:
                    event_name = item.get("event", "")
                    country = item.get("country", "")
                    impact = item.get("impact", "")
                    
                    # Only show US high-impact events
                    if country == "US" and (impact == "High" or any(kw in event_name for kw in high_impact_keywords)):
                        calendar_items.append({
                            "event": event_name[:50],
                            "date": item.get("date", "")[:10],
                            "time": item.get("date", "")[11:16] if len(item.get("date", "")) > 11 else "",
                            "previous": item.get("previous", ""),
                            "estimate": item.get("estimate", ""),
                            "impact": impact,
                        })
                
                # Limit to 5 events
                calendar_items = calendar_items[:5]
        except Exception as e:
            print(f"[News] FMP calendar error: {e}")
    
    return {
        "news": news_items,
        "calendar": calendar_items,
        "tickers": list(portfolio_tickers),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ============ BACKGROUND THREADS ============

_background_threads_started = False

def start_background_threads():
    """Initialize Palmer and Monte Carlo caches and start background refresh threads."""
    global _background_threads_started
    if _background_threads_started:
        return
    _background_threads_started = True
    
    print(f"[Palmer] Starting background refresh thread (interval: {PALMER_REFRESH_INTERVAL}s)")
    print(f"[MC] Starting background refresh thread (interval: {MC_REFRESH_INTERVAL}s = 1 hour)")
    
    # Do initial refreshes in background
    def initial_refresh():
        _refresh_mc_cache()  # MC first (Palmer uses cached MC)
        _refresh_palmer_cache()
    
    init_thread = threading.Thread(target=initial_refresh, daemon=True)
    init_thread.start()
    
    # Start Palmer background refresh thread (every 30 min)
    palmer_thread = threading.Thread(target=_palmer_background_refresh, daemon=True)
    palmer_thread.start()
    
    # Start Monte Carlo background refresh thread (every 1 hour)
    mc_thread = threading.Thread(target=_mc_background_refresh, daemon=True)
    mc_thread.start()


# Alias for backward compatibility
start_palmer_background = start_background_threads


# ============ APP STARTUP ============

# Auto-start background threads when module loads (works with gunicorn)
# Only start once per worker process
start_background_threads()


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True, threaded=True)
