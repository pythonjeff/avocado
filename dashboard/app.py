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


def get_positions_data():
    """Fetch positions and calculate P&L."""
    try:
        settings = load_settings()
        trading, _ = make_clients(settings)
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
        
        # Fallback: calculate from account if NAV sheet is empty
        if nav_equity == 0.0 and account:
            try:
                account_equity = float(getattr(account, 'equity', 0.0) or 0.0)
                if account_equity > 0:
                    nav_equity = account_equity
            except Exception:
                pass
        
        # Get original capital from investor flows
        original_capital = 950.0  # Default
        try:
            flows = read_investor_flows()
            capital_sum = sum(float(f.amount) for f in flows if float(f.amount) > 0)
            if capital_sum > 0:
                original_capital = capital_sum
        except Exception as flow_error:
            print(f"Warning: Could not read investor flows: {flow_error}")
        
        # Total P&L = NAV - original capital
        total_pnl = nav_equity - original_capital
        
        positions_list = []
        total_value = 0.0
        
        # Process positions with error handling
        for p in positions:
            try:
                symbol = str(getattr(p, "symbol", "") or "")
                if not symbol:
                    continue
                    
                qty = float(getattr(p, "qty", 0.0) or 0.0)
                mv = float(getattr(p, "market_value", 0.0) or 0.0)
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
                
                # Calculate position-level P&L
                if opt_info:
                    # For options, P&L is based on price change * 100 * qty
                    entry_cost = avg_entry * 100 * abs(qty) if avg_entry > 0 else 0
                    current_value = abs(mv)
                    pnl = current_value - entry_cost if qty > 0 else entry_cost - current_value
                else:
                    # For stocks/ETFs
                    entry_cost = avg_entry * abs(qty) if avg_entry > 0 else 0
                    pnl = mv - entry_cost
                
                total_value += abs(mv)
                
                positions_list.append({
                    "symbol": symbol,
                    "qty": qty,
                    "market_value": mv,
                    "pnl": pnl,
                    "pnl_pct": (pnl / entry_cost * 100) if entry_cost > 0 else 0.0,
                    "current_price": current_price,
                    "opt_info": opt_info,
                })
            except Exception as pos_err:
                print(f"Warning: Error processing position: {pos_err}")
                continue
        
        # Sort by P&L (most profitable to least profitable)
        positions_list.sort(key=lambda x: x["pnl"], reverse=True)
        
        # Calculate return percentage
        return_pct = (total_pnl / original_capital * 100) if original_capital > 0 else 0.0
        
        # Get benchmark performance since inception for comparison
        sp500_return = get_sp500_return_since_inception()
        btc_return = get_btc_return_since_inception()
        alpha_sp500 = return_pct - sp500_return if sp500_return is not None else None
        alpha_btc = return_pct - btc_return if btc_return is not None else None
        
        # Get cash available from account
        cash_available = 0.0
        try:
            if account:
                cash_available = float(getattr(account, 'cash', 0.0) or 0.0)
        except Exception:
            pass
        
        return {
            "positions": positions_list,
            "total_pnl": total_pnl,
            "total_value": total_value,
            "nav_equity": nav_equity,
            "original_capital": original_capital,
            "return_pct": return_pct,
            "sp500_return": sp500_return,
            "btc_return": btc_return,
            "alpha_sp500": alpha_sp500,
            "alpha_btc": alpha_btc,
            "cash_available": cash_available,
            "timestamp": datetime.now(timezone.utc).isoformat(),
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


def fetch_macro_headlines(settings, portfolio_tickers=None, limit=5):
    """Fetch top macro/financial headlines using FMP stock news API.
    
    Uses portfolio tickers if provided, otherwise defaults to macro ETFs.
    """
    import requests
    headlines = []
    
    try:
        # Build ticker list: portfolio tickers first, then macro fallback
        tickers_to_fetch = []
        
        if portfolio_tickers:
            # Filter to underlying tickers (not option symbols)
            clean_tickers = [t for t in portfolio_tickers if t and len(t) <= 5 and t.isalpha()]
            tickers_to_fetch.extend(clean_tickers[:5])
        
        # Add macro tickers if we don't have enough
        macro_tickers = ["SPY", "QQQ", "TLT", "GLD"]
        for mt in macro_tickers:
            if mt not in tickers_to_fetch and len(tickers_to_fetch) < 6:
                tickers_to_fetch.append(mt)
        
        # Fetch from FMP stock news
        tickers_str = ",".join(tickers_to_fetch)
        url = f"https://financialmodelingprep.com/api/v3/stock_news?tickers={tickers_str}&limit={limit * 2}&apikey={settings.fmp_api_key}"
        
        resp = requests.get(url, timeout=10)
        data = resp.json()
        
        if isinstance(data, list):
            for item in data:
                title = item.get("title", "") or ""
                site = item.get("site", "") or ""
                published = item.get("publishedDate", "") or ""
                ticker = item.get("symbol", "") or ""
                url = item.get("url", "") or ""
                
                if title:
                    # Parse date for display
                    time_str = ""
                    if published:
                        try:
                            from datetime import datetime
                            dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
                            time_str = dt.strftime("%b %d")
                        except:
                            pass
                    
                    headlines.append({
                        "headline": title[:120],
                        "source": site[:20] if site else "News",
                        "time": time_str,
                        "ticker": ticker,
                        "url": url,
                    })
        
        # Dedupe by headline
        seen = set()
        unique_headlines = []
        for h in headlines:
            if h["headline"] not in seen:
                seen.add(h["headline"])
                unique_headlines.append(h)
        
        headlines = unique_headlines[:limit]
        
    except Exception as e:
        print(f"[Palmer] FMP news fetch error: {e}")
    
    return headlines


def fetch_fed_fiscal_calendar(settings, days_ahead=14):
    """Fetch Fed and fiscal-focused economic events."""
    events = []
    
    # Fed/fiscal keywords to prioritize
    fed_fiscal_keywords = [
        'fed', 'fomc', 'powell', 'rate', 'treasury', 'auction', 'debt', 'deficit',
        'fiscal', 'budget', 'gdp', 'cpi', 'pce', 'inflation', 'employment', 'payroll',
        'jobless', 'retail', 'housing', 'durable', 'ism', 'pmi'
    ]
    
    try:
        fmp_key = settings.fmp_api_key
        if not fmp_key:
            return events
        
        from datetime import datetime, timedelta
        import requests
        
        start = datetime.now().strftime("%Y-%m-%d")
        end = (datetime.now() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
        
        url = f"https://financialmodelingprep.com/api/v3/economic_calendar?from={start}&to={end}&apikey={fmp_key}"
        resp = requests.get(url, timeout=10)
        
        if resp.status_code == 200:
            data = resp.json() or []
            
            for item in data:
                event_name = (item.get("event") or "").lower()
                
                # Only include Fed/fiscal focused events
                is_fed_fiscal = any(kw in event_name for kw in fed_fiscal_keywords)
                
                if is_fed_fiscal:
                    events.append({
                        "date": item.get("date", "")[:10],
                        "event": item.get("event", ""),
                        "estimate": item.get("estimate"),
                        "previous": item.get("previous"),
                        "impact": item.get("impact", ""),
                    })
    except Exception as e:
        print(f"[Palmer] Fed/fiscal calendar error: {e}")
    
    # Sort by date and limit
    events.sort(key=lambda x: x["date"])
    return events[:8]


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
    
    # Get Fed/fiscal focused calendar
    fed_fiscal_events = fetch_fed_fiscal_calendar(settings, days_ahead=14)
    
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
    headlines = fetch_macro_headlines(settings, portfolio_tickers=portfolio_tickers, limit=5)
    
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
    
    # Format events for display
    events_display = []
    for e in fed_fiscal_events[:4]:
        est_str = f"est: {e['estimate']}" if e.get('estimate') else ""
        events_display.append({
            "date": e["date"],
            "event": e["event"][:50],
            "estimate": est_str,
        })
    
    # Format headlines for display
    headlines_display = []
    for h in headlines[:4]:
        headlines_display.append({
            "headline": h["headline"],
            "source": h["source"],
            "time": h["time"],
        })
    
    # Generate LLM insight (just one focused paragraph)
    try:
        from openai import OpenAI
        client = OpenAI(api_key=settings.openai_api_key)
        
        # Simplified prompt for one insight
        prompt = f"""You are Palmer, a macro strategist. Give ONE actionable insight (3-4 sentences max).

CURRENT CONDITIONS:
- VIX: {f'{vix_val:.1f}' if vix_val else 'N/A'}
- HY Spreads: {f'{hy_val:.0f}bp' if hy_val else 'N/A'}
- 10Y Yield: {f'{yield_val:.2f}%' if yield_val else 'N/A'}
- Portfolio: Long vol (VIXM), short credit (HYG puts), short NVDA, short solar (TAN puts), long bonds (TLT calls)

UPCOMING FED/FISCAL EVENTS:
{chr(10).join(f"- {e['date']}: {e['event']}" for e in fed_fiscal_events[:5]) if fed_fiscal_events else "None in next 2 weeks"}

RECENT HEADLINES:
{chr(10).join(f"- {h['headline']}" for h in headlines[:3]) if headlines else "No recent macro headlines"}

Write ONE insight paragraph that:
1. States the current regime in 1 sentence
2. Identifies the key risk or opportunity from the calendar/headlines
3. Gives a specific implication for the portfolio

Be direct and specific. No fluff. Under 75 words total."""

        response = client.chat.completions.create(
            model=settings.openai_model or "gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=200,
        )
        
        insight = response.choices[0].message.content.strip()
    except Exception as e:
        print(f"[Palmer] LLM error: {e}")
        insight = "Analysis temporarily unavailable."
    
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
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    response = client.chat.completions.create(
        model=settings.openai_model or "gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=1000,
    )
    
    analysis = response.choices[0].message.content.strip()
    
    return {
        "analysis": analysis,
        "regime_snapshot": regime_snapshot,
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
        
        # Return cached data
        return jsonify({
            "analysis": PALMER_CACHE.get("analysis"),
            "regime_snapshot": PALMER_CACHE.get("regime_snapshot"),
            "traffic_lights": PALMER_CACHE.get("traffic_lights"),
            "events": PALMER_CACHE.get("events"),
            "headlines": PALMER_CACHE.get("headlines"),
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
