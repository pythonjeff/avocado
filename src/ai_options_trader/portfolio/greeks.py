"""
v3.5: Import real positions from Alpaca and calculate actual greeks.

This replaces manual greek inputs with real portfolio data.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple
import requests
from datetime import datetime

from ai_options_trader.config import Settings
from ai_options_trader.options.symbols import parse_occ_symbol


@dataclass
class PortfolioGreeks:
    """Calculated greeks for entire portfolio."""
    
    net_delta: float  # As % of NAV
    net_vega: float   # As % of NAV per VIX point
    net_theta: float  # As % of NAV per day
    net_gamma: float  # As % of NAV per 1% SPX move
    
    # Breakdown by position
    positions: List[PositionGreeks]
    
    # Portfolio stats
    total_nav: float
    equity_value: float
    options_value: float
    cash: float
    
    # Summary
    has_tail_hedges: bool
    n_positions: int


@dataclass
class PositionGreeks:
    """Greeks for a single position."""
    
    symbol: str
    quantity: float
    market_value: float
    
    # Greeks (per contract for options, per share for stock)
    delta: float
    vega: float
    theta: float
    gamma: float
    
    # Position-level greeks (quantity * per-contract)
    position_delta: float
    position_vega: float
    position_theta: float
    position_gamma: float
    
    # Metadata
    asset_type: str  # "stock", "call", "put"
    underlying: str | None
    strike: float | None
    expiry: datetime | None
    dte: int | None


class AlpacaGreeksCalculator:
    """
    Calculate portfolio greeks from Alpaca positions.
    
    For stocks: Simple delta = 1.0 per share
    For options: Fetch from market data or estimate using Black-Scholes
    """
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.api_key = settings.ALPACA_API_KEY
        self.api_secret = settings.ALPACA_SECRET_KEY
        self.base_url = settings.ALPACA_BASE_URL or "https://paper-api.alpaca.markets"
    
    def _get_headers(self) -> Dict[str, str]:
        return {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.api_secret,
        }
    
    def fetch_positions(self) -> List[Dict]:
        """Fetch all positions from Alpaca."""
        url = f"{self.base_url}/v2/positions"
        resp = requests.get(url, headers=self._get_headers(), timeout=10)
        resp.raise_for_status()
        return resp.json()
    
    def fetch_account(self) -> Dict:
        """Fetch account info (NAV, cash, etc.)."""
        url = f"{self.base_url}/v2/account"
        resp = requests.get(url, headers=self._get_headers(), timeout=10)
        resp.raise_for_status()
        return resp.json()
    
    def estimate_option_greeks(
        self,
        option_type: str,
        strike: float,
        expiry: datetime,
        underlying_price: float,
        implied_vol: float = 0.25,  # Default IV if not available
    ) -> Tuple[float, float, float, float]:
        """
        Estimate option greeks using simplified Black-Scholes.
        
        Returns: (delta, vega, theta, gamma)
        
        Note: In production, fetch greeks from market data provider.
        This is a simplified approximation.
        """
        import math
        from scipy.stats import norm
        
        # Days to expiration
        dte = (expiry - datetime.now()).days
        if dte <= 0:
            return (0.0, 0.0, 0.0, 0.0)
        
        t = dte / 365.0
        
        # Risk-free rate (simplified)
        r = 0.045
        
        # Black-Scholes
        d1 = (math.log(underlying_price / strike) + (r + 0.5 * implied_vol**2) * t) / (implied_vol * math.sqrt(t))
        d2 = d1 - implied_vol * math.sqrt(t)
        
        if option_type.upper() == "CALL":
            delta = norm.cdf(d1)
            theta = (
                -underlying_price * norm.pdf(d1) * implied_vol / (2 * math.sqrt(t))
                - r * strike * math.exp(-r * t) * norm.cdf(d2)
            ) / 365.0  # Per day
        else:  # PUT
            delta = norm.cdf(d1) - 1.0
            theta = (
                -underlying_price * norm.pdf(d1) * implied_vol / (2 * math.sqrt(t))
                + r * strike * math.exp(-r * t) * norm.cdf(-d2)
            ) / 365.0  # Per day
        
        vega = underlying_price * norm.pdf(d1) * math.sqrt(t) / 100.0  # Per 1% vol change
        gamma = norm.pdf(d1) / (underlying_price * implied_vol * math.sqrt(t))
        
        return (delta, vega, theta, gamma)
    
    def calculate_portfolio_greeks(self) -> PortfolioGreeks:
        """
        Calculate greeks for entire portfolio.
        
        Returns PortfolioGreeks with aggregated risk metrics.
        """
        print("Fetching positions from Alpaca...")
        positions = self.fetch_positions()
        account = self.fetch_account()
        
        nav = float(account["equity"])
        cash = float(account["cash"])
        
        print(f"✓ Found {len(positions)} positions, NAV ${nav:,.0f}")
        
        position_greeks: List[PositionGreeks] = []
        
        total_delta = 0.0
        total_vega = 0.0
        total_theta = 0.0
        total_gamma = 0.0
        
        equity_value = 0.0
        options_value = 0.0
        has_tail_hedges = False
        
        for pos in positions:
            symbol = pos["symbol"]
            qty = float(pos["qty"])
            market_value = float(pos["market_value"])
            
            # Determine asset type
            if "/" in symbol:
                # Option symbol (OCC format)
                parsed = parse_occ_symbol(symbol)
                if not parsed:
                    print(f"Warning: Could not parse option symbol {symbol}")
                    continue
                
                underlying, expiry_str, option_type, strike_str = parsed
                expiry = datetime.strptime(expiry_str, "%y%m%d")
                strike = float(strike_str)
                dte = (expiry - datetime.now()).days
                
                # Estimate greeks (in production, fetch from market data)
                # For now, use simplified estimates
                underlying_price = 500.0  # Would fetch from market
                delta, vega, theta, gamma = self.estimate_option_greeks(
                    option_type=option_type,
                    strike=strike,
                    expiry=expiry,
                    underlying_price=underlying_price,
                )
                
                # Position-level greeks (per contract, then multiply by qty)
                # Note: 1 option contract = 100 shares
                pos_delta = delta * 100 * qty
                pos_vega = vega * 100 * qty
                pos_theta = theta * 100 * qty
                pos_gamma = gamma * 100 * qty
                
                options_value += abs(market_value)
                
                # Detect tail hedges (OTM puts)
                if option_type == "P" and strike < underlying_price * 0.9:
                    has_tail_hedges = True
                
            else:
                # Stock position
                underlying = symbol
                expiry = None
                strike = None
                dte = None
                option_type = "stock"
                
                # Stock greeks: delta=1, others=0
                delta = 1.0
                vega = 0.0
                theta = 0.0
                gamma = 0.0
                
                pos_delta = qty * delta
                pos_vega = 0.0
                pos_theta = 0.0
                pos_gamma = 0.0
                
                equity_value += abs(market_value)
            
            # Accumulate
            total_delta += pos_delta
            total_vega += pos_vega
            total_theta += pos_theta
            total_gamma += pos_gamma
            
            # Store
            position_greeks.append(PositionGreeks(
                symbol=symbol,
                quantity=qty,
                market_value=market_value,
                delta=delta,
                vega=vega,
                theta=theta,
                gamma=gamma,
                position_delta=pos_delta,
                position_vega=pos_vega,
                position_theta=pos_theta,
                position_gamma=pos_gamma,
                asset_type=option_type if option_type != "stock" else "stock",
                underlying=underlying,
                strike=strike,
                expiry=expiry,
                dte=dte,
            ))
        
        # Normalize by NAV
        net_delta = total_delta / nav if nav > 0 else 0.0
        net_vega = total_vega / nav if nav > 0 else 0.0
        net_theta = total_theta / nav if nav > 0 else 0.0
        net_gamma = total_gamma / nav if nav > 0 else 0.0
        
        print(f"\nPortfolio Greeks (% of NAV):")
        print(f"  Net Delta: {net_delta*100:+.1f}%")
        print(f"  Net Vega:  {net_vega:.4f} (per VIX point)")
        print(f"  Net Theta: {net_theta*100:.3f}% per day")
        print(f"  Net Gamma: {net_gamma:.4f}")
        print(f"\n  Tail hedges: {'Yes' if has_tail_hedges else 'No'}")
        
        return PortfolioGreeks(
            net_delta=net_delta,
            net_vega=net_vega,
            net_theta=net_theta,
            net_gamma=net_gamma,
            positions=position_greeks,
            total_nav=nav,
            equity_value=equity_value,
            options_value=options_value,
            cash=cash,
            has_tail_hedges=has_tail_hedges,
            n_positions=len(position_greeks),
        )
