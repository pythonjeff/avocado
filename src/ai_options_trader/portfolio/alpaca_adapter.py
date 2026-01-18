"""
Convert Alpaca positions to Portfolio object for Monte Carlo analysis.

Uses existing infrastructure from data/alpaca.py (make_clients).
"""
from typing import List, Dict
from datetime import datetime

from ai_options_trader.config import Settings
from ai_options_trader.data.alpaca import make_clients
from ai_options_trader.portfolio.positions import Position, Portfolio
from ai_options_trader.altdata.fmp import fetch_realtime_quotes


def alpaca_to_portfolio(settings: Settings) -> Portfolio:
    """
    Fetch positions from Alpaca and convert to Portfolio object.
    
    Uses existing make_clients() infrastructure.
    """
    print("Fetching positions from Alpaca...")
    
    trading, _ = make_clients(settings)
    
    # Get account
    try:
        acct = trading.get_account()
        cash = float(getattr(acct, "cash", 0.0) or 0.0)
    except Exception as e:
        print(f"❌ Error fetching account: {e}")
        return Portfolio(positions=[], cash=0.0)
    
    # Get positions
    try:
        alpaca_positions = trading.get_all_positions()
    except Exception as e:
        print(f"❌ Error fetching positions: {e}")
        return Portfolio(positions=[], cash=cash)
    
    print(f"✓ Found {len(alpaca_positions)} positions, cash: ${cash:,.0f}")
    
    # Extract unique underlying tickers for options
    underlying_tickers = set()
    for p in alpaca_positions:
        symbol = str(getattr(p, "symbol", ""))
        is_option = '/' in symbol or (
            len(symbol) > 10 and 
            any(symbol[i].isdigit() for i in range(len(symbol))) and
            any(c in symbol for c in ['C', 'P'])
        )
        if is_option:
            parsed = _parse_option_symbol(symbol)
            if parsed:
                underlying_tickers.add(parsed['underlying'])
    
    # Fetch real underlying prices from FMP
    print(f"Fetching real-time prices for {len(underlying_tickers)} underlyings...")
    underlying_prices: Dict[str, float] = {}
    if underlying_tickers:
        try:
            underlying_prices = fetch_realtime_quotes(
                settings=settings,
                tickers=list(underlying_tickers),
            )
            print(f"✓ Fetched prices for: {', '.join(f'{t}=${p:.2f}' for t, p in underlying_prices.items())}")
        except Exception as e:
            print(f"⚠️  Could not fetch underlying prices: {e}")
            print("   Falling back to strike prices as proxies")
    
    # Convert to Position objects
    positions: List[Position] = []
    
    for p in alpaca_positions:
        symbol = str(getattr(p, "symbol", ""))
        qty = float(getattr(p, "qty", 0.0) or 0.0)
        current_price = float(getattr(p, "current_price", 0.0) or 0.0)
        avg_entry = float(getattr(p, "avg_entry_price", 0.0) or 0.0)
        
        # #region agent log
        import json
        with open('/Users/jeffreylarson/sites/ai-options-trader-starter/.cursor/debug.log', 'a') as f:
            f.write(json.dumps({"location":"alpaca_adapter.py:49","message":"Alpaca position raw","data":{"symbol":symbol,"qty":qty,"current_price":current_price,"avg_entry":avg_entry},"timestamp":__import__('time').time()*1000,"sessionId":"debug-session","hypothesisId":"C"}) + '\n')
        # #endregion
        
        # Determine if it's an option (has / or looks like OCC format)
        is_option = '/' in symbol or (
            len(symbol) > 10 and 
            any(symbol[i].isdigit() for i in range(len(symbol))) and
            any(c in symbol for c in ['C', 'P'])
        )
        
        if is_option:
            # Parse option details
            parsed = _parse_option_symbol(symbol)
            if not parsed:
                print(f"⚠️  Could not parse option: {symbol}, treating as stock")
                # Treat as stock
                position = Position(
                    ticker=symbol,
                    quantity=qty,
                    position_type="stock",
                    entry_price=avg_entry,
                )
            else:
                # Option position
                # ✅ CRITICAL FIX: Use REAL underlying price from FMP
                underlying_symbol = parsed['underlying']
                
                # Try to get real price, fall back to strike if unavailable
                if underlying_symbol in underlying_prices:
                    underlying_price = underlying_prices[underlying_symbol]
                else:
                    # Fallback to strike as proxy
                    underlying_price = parsed['strike']
                    print(f"⚠️  No price data for {underlying_symbol}, using strike ${underlying_price:.2f} as proxy")
                
                position = Position(
                    ticker=symbol,
                    quantity=qty,
                    position_type=parsed['type'],
                    strike=parsed['strike'],
                    expiry=parsed['expiry'],
                    entry_price=avg_entry,
                    entry_underlying_price=underlying_price,
                    entry_iv=0.25,  # Default IV
                )
                
                # Calculate greeks
                position.calculate_greeks(
                    underlying_price=underlying_price,
                    iv=0.25,
                )
                
                # #region agent log
                import json
                with open('/Users/jeffreylarson/sites/ai-options-trader-starter/.cursor/debug.log', 'a') as f:
                    f.write(json.dumps({"location":"alpaca_adapter.py:97","message":"Option greeks calculated","data":{"symbol":symbol,"delta":position.delta,"gamma":position.gamma,"vega":position.vega,"theta":position.theta,"dte":position.dte,"underlying_price":underlying_price,"iv":0.25},"timestamp":__import__('time').time()*1000,"sessionId":"debug-session","hypothesisId":"A"}) + '\n')
                # #endregion
        else:
            # Stock/ETF position
            position = Position(
                ticker=symbol,
                quantity=qty,
                position_type="stock",
                entry_price=avg_entry,
            )
            
            # Calculate greeks (delta=1 for stocks)
            position.calculate_greeks(
                underlying_price=current_price,
                iv=0.0,
            )
        
        positions.append(position)
        
        # Show what we added
        if position.is_option:
            print(f"  {symbol}: {qty:+.1f} contracts @ ${current_price:.2f} "
                  f"(Δ{position.delta:+.2f}, V${position.position_vega_usd:.0f}, Θ${position.position_theta_usd:.0f}/day)")
        else:
            # Show fractional shares properly
            if abs(qty) < 1:
                print(f"  {symbol}: {qty:+.4f} shares @ ${current_price:.2f}")
            else:
                print(f"  {symbol}: {qty:+.0f} shares @ ${current_price:.2f}")
    
    portfolio = Portfolio(positions=positions, cash=cash)
    
    print(f"\n✓ Portfolio loaded:")
    print(f"  NAV: ${portfolio.nav:,.0f}")
    print(f"  Positions: {len(positions)}")
    print(f"  Net Delta: {portfolio.net_delta_pct*100:+.1f}%")
    print(f"  Net Vega: ${portfolio.net_vega:,.0f}")
    print(f"  Net Theta: ${portfolio.net_theta_per_day:,.0f} /day")
    
    return portfolio


def _parse_option_symbol(symbol: str) -> dict | None:
    """
    Parse OCC option symbol format.
    
    Example: "SPY/250321P00400000" or "SPY250321P00400000"
    - SPY = underlying
    - 250321 = Mar 21, 2025 (YYMMDD)
    - P = put (C = call)
    - 00400000 = $400.00 strike (8 digits, last 3 are cents)
    """
    # Split on / if present
    if '/' in symbol:
        parts = symbol.split('/')
        underlying = parts[0]
        option_part = parts[1] if len(parts) > 1 else symbol
    else:
        # Find where the date starts (first 6-digit sequence)
        idx = 0
        while idx < len(symbol) and not symbol[idx].isdigit():
            idx += 1
        
        underlying = symbol[:idx]
        option_part = symbol[idx:]
    
    # Need at least 15 characters for YYMMDDCPPPPPPPP format
    if len(option_part) < 15:
        return None
    
    try:
        # Parse date (YYMMDD)
        date_str = option_part[:6]
        year = 2000 + int(date_str[:2])
        month = int(date_str[2:4])
        day = int(date_str[4:6])
        expiry = datetime(year, month, day)
        
        # Parse type (C/P)
        option_type = option_part[6]
        if option_type.upper() not in ['C', 'P']:
            return None
        
        # Parse strike (8 digits with last 3 as cents)
        strike_str = option_part[7:15]
        strike = float(strike_str) / 1000.0
        
        return {
            'underlying': underlying,
            'expiry': expiry,
            'type': 'call' if option_type.upper() == 'C' else 'put',
            'strike': strike,
        }
    except Exception:
        return None
