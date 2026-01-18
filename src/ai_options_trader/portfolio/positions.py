"""
v0.1: Position-level portfolio representation for Monte Carlo.

Replaces abstract "net delta -20%" with actual positions:
- Each option: underlying, strike, expiry, type, quantity
- Each ETF/stock: ticker, quantity
- Greeks calculated per position
- P&L using Taylor approximation per instrument
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional
import numpy as np
from scipy.stats import norm
import math


@dataclass
class Position:
    """A single portfolio position (stock, ETF, or option)."""
    
    # Core attributes
    ticker: str
    quantity: float
    position_type: str  # "stock", "etf", "call", "put"
    
    # Option-specific (None for stocks/ETFs)
    strike: Optional[float] = None
    expiry: Optional[datetime] = None
    
    # Market data at entry
    entry_price: float = 0.0
    entry_underlying_price: float = 0.0  # For options
    entry_iv: float = 0.25  # Implied vol at entry
    
    # Greeks (calculated or provided)
    delta: float = 1.0  # Default for stocks
    gamma: float = 0.0
    vega: float = 0.0
    theta: float = 0.0
    
    @property
    def notional(self) -> float:
        """Position notional in $."""
        if self.position_type in ["call", "put"]:
            return abs(self.quantity * 100 * self.entry_price)  # Options are per 100 shares
        else:
            return abs(self.quantity * self.entry_price)
    
    @property
    def dte(self) -> int:
        """Days to expiration (0 for stocks/ETFs)."""
        if self.expiry is None:
            return 0
        return max(0, (self.expiry - datetime.now()).days)
    
    @property
    def is_option(self) -> bool:
        return self.position_type in ["call", "put"]
    
    @property
    def position_delta_usd(self) -> float:
        """Position delta in $ (for +$1 move in underlying)."""
        multiplier = 100 if self.is_option else 1
        underlying_px = self.entry_underlying_price if self.is_option else self.entry_price
        return self.quantity * multiplier * self.delta * underlying_px
    
    @property
    def position_vega_usd(self) -> float:
        """Position vega in $ (for +1pt IV move)."""
        if not self.is_option:
            return 0.0
        return self.quantity * 100 * self.vega
    
    @property
    def position_theta_usd(self) -> float:
        """Position theta in $ per day."""
        if not self.is_option:
            return 0.0
        return self.quantity * 100 * self.theta
    
    @property
    def position_gamma_usd(self) -> float:
        """Position gamma ($ P&L for +1% move squared)."""
        if not self.is_option:
            return 0.0
        return self.quantity * 100 * self.gamma
    
    def calculate_greeks(
        self,
        underlying_price: float,
        iv: float,
        rate: float = 0.045,
    ) -> None:
        """
        Calculate option greeks using Black-Scholes.
        
        For stocks/ETFs, greeks are simple (delta=1, others=0).
        """
        if not self.is_option:
            # Stock/ETF greeks
            self.delta = 1.0 if self.quantity > 0 else -1.0
            self.gamma = 0.0
            self.vega = 0.0
            self.theta = 0.0
            return
        
        # Option greeks (Black-Scholes)
        if self.dte == 0 or self.strike is None:
            self.delta = 0.0
            self.gamma = 0.0
            self.vega = 0.0
            self.theta = 0.0
            return
        
        t = self.dte / 365.0
        
        try:
            d1 = (math.log(underlying_price / self.strike) + (rate + 0.5 * iv**2) * t) / (iv * math.sqrt(t))
            d2 = d1 - iv * math.sqrt(t)
            
            if self.position_type == "call":
                self.delta = norm.cdf(d1)
                self.theta = (
                    -underlying_price * norm.pdf(d1) * iv / (2 * math.sqrt(t))
                    - rate * self.strike * math.exp(-rate * t) * norm.cdf(d2)
                ) / 365.0
            else:  # put
                self.delta = norm.cdf(d1) - 1.0
                self.theta = (
                    -underlying_price * norm.pdf(d1) * iv / (2 * math.sqrt(t))
                    + rate * self.strike * math.exp(-rate * t) * norm.cdf(-d2)
                ) / 365.0
            
            self.gamma = norm.pdf(d1) / (underlying_price * iv * math.sqrt(t))
            self.vega = underlying_price * norm.pdf(d1) * math.sqrt(t) / 100.0  # Per 1% vol
            
        except (ValueError, ZeroDivisionError):
            self.delta = 0.0
            self.gamma = 0.0
            self.vega = 0.0
            self.theta = 0.0
    
    def estimate_pnl(
        self,
        underlying_change_pct: float,
        iv_change_pts: float,
        days_elapsed: int,
    ) -> float:
        """
        Estimate P&L using Taylor approximation:
        ΔP ≈ Δ·ΔS + ½Γ(ΔS)² + Vega·Δσ + Θ·Δt
        
        Args:
            underlying_change_pct: % change in underlying (e.g., -0.10 for -10%)
            iv_change_pts: Change in IV in percentage points (e.g., 5 for +5%)
            days_elapsed: Days passed
        
        Returns:
            P&L in $ for this position (bounded by option max loss)
        """
        if not self.is_option:
            # Stock/ETF: simple delta P&L
            position_delta_usd = self.quantity * self.entry_price
            pnl = position_delta_usd * underlying_change_pct
            return pnl
        
        # Option P&L (Taylor approximation)
        multiplier = 100  # Options are per 100 shares
        
        # Delta P&L
        underlying_usd = self.entry_underlying_price
        delta_s = underlying_usd * underlying_change_pct
        delta_pnl = self.quantity * multiplier * self.delta * delta_s
        
        # Gamma P&L (½Γ(ΔS)²)
        gamma_pnl = 0.5 * self.quantity * multiplier * self.gamma * (delta_s ** 2)
        
        # Vega P&L (per 1pt vol change)
        vega_pnl = self.quantity * multiplier * self.vega * iv_change_pts
        
        # Theta P&L (time decay)
        # Stop decaying after expiry
        effective_days = min(days_elapsed, self.dte)
        theta_pnl = self.quantity * multiplier * self.theta * effective_days
        
        total_pnl = delta_pnl + gamma_pnl + vega_pnl + theta_pnl
        
        # ✅ CRITICAL: Bound option P&L by max loss (premium paid)
        # Long options: max loss = premium paid
        # Short options: technically unbounded, but we'll cap at 10x premium for sanity
        max_loss = -abs(self.notional)  # Can't lose more than premium paid (long)
        max_gain = abs(self.notional) * 10  # Cap gains at 10x premium for sanity
        
        if self.quantity > 0:  # Long option
            total_pnl = max(total_pnl, max_loss)
        
        # Cap extreme gains (>10x) to prevent numerical issues
        total_pnl = min(total_pnl, max_gain)
        
        return total_pnl


@dataclass
class Portfolio:
    """Collection of positions with portfolio-level metrics."""
    
    positions: List[Position]
    cash: float = 0.0
    
    @property
    def nav(self) -> float:
        """Total portfolio NAV."""
        positions_value = sum(p.notional for p in self.positions)
        return positions_value + self.cash
    
    @property
    def net_delta_pct(self) -> float:
        """
        Net delta as $ P&L per +1% move in each underlying.
        
        This represents the expected portfolio P&L if all underlyings move +1%.
        Expressed as % of NAV for normalization.
        """
        # Sum position deltas (already in $ terms)
        total_delta_usd = sum(p.position_delta_usd for p in self.positions)
        
        # Convert to "per 1% move" by dividing by 100
        delta_per_1pct_move = total_delta_usd / 100.0
        
        # Express as % of NAV
        return (delta_per_1pct_move / self.nav * 100) if self.nav > 0 else 0.0
    
    @property
    def net_delta_usd_per_1pct(self) -> float:
        """Net delta: $ P&L for a +1% move in all underlyings."""
        total_delta_usd = sum(p.position_delta_usd for p in self.positions)
        return total_delta_usd / 100.0
    
    @property
    def net_vega(self) -> float:
        """Net vega ($ change per 1% IV move)."""
        return sum(p.position_vega_usd for p in self.positions)
    
    @property
    def net_theta_per_day(self) -> float:
        """Net theta ($ decay per day)."""
        return sum(p.position_theta_usd for p in self.positions)
    
    @property
    def net_gamma(self) -> float:
        """Net gamma."""
        return sum(p.position_gamma_usd for p in self.positions)
    
    def estimate_pnl(
        self,
        underlying_changes: dict[str, float],  # ticker -> % change
        iv_changes: dict[str, float],  # ticker -> pts change
        days_elapsed: int,
    ) -> tuple[float, dict[str, float]]:
        """
        Estimate total portfolio P&L and per-position attribution.
        
        Returns:
            (total_pnl_$, position_pnls) where position_pnls is {ticker: pnl_$}
        """
        total_pnl = 0.0
        position_pnls = {}
        
        for pos in self.positions:
            # Get underlying ticker (strip option suffix if present)
            underlying = pos.ticker.split('/')[0] if '/' in pos.ticker else pos.ticker
            
            underlying_chg = underlying_changes.get(underlying, 0.0)
            iv_chg = iv_changes.get(underlying, 0.0)
            
            pos_pnl = pos.estimate_pnl(underlying_chg, iv_chg, days_elapsed)
            total_pnl += pos_pnl
            position_pnls[pos.ticker] = pos_pnl
        
        return total_pnl, position_pnls
    
    def summary(self) -> dict:
        """Portfolio summary for display."""
        return {
            "nav": self.nav,
            "n_positions": len(self.positions),
            "n_options": sum(1 for p in self.positions if p.is_option),
            "net_delta_pct": self.net_delta_pct,
            "net_vega": self.net_vega,
            "net_theta_per_day": self.net_theta_per_day,
            "net_gamma": self.net_gamma,
            "theta_carry_pct_6m": (self.net_theta_per_day * 180) / self.nav * 100 if self.nav > 0 else 0,
        }


def create_example_portfolio() -> Portfolio:
    """
    Create an example tail-hedge portfolio for testing.
    
    This represents a typical tail-risk fund:
    - Long SPY puts (tail hedge)
    - Short SPY (delta hedge)
    - Long VIX calls (vol spike)
    """
    positions = [
        # Tail hedge: OTM SPY puts
        Position(
            ticker="SPY/250321P00400000",  # SPY Mar 2025 $400 Put
            quantity=10,
            position_type="put",
            strike=400.0,
            expiry=datetime(2025, 3, 21),
            entry_price=5.50,
            entry_underlying_price=585.0,
            entry_iv=0.20,
        ),
        # Delta hedge: Short SPY
        Position(
            ticker="SPY",
            quantity=-20,
            position_type="etf",
            entry_price=585.0,
        ),
        # Vol spike play: VIX calls
        Position(
            ticker="VIX/250221C00025000",  # VIX Feb 2025 $25 Call
            quantity=5,
            position_type="call",
            strike=25.0,
            expiry=datetime(2025, 2, 21),
            entry_price=2.80,
            entry_underlying_price=14.9,
            entry_iv=0.90,
        ),
        # Credit hedge: HYG puts
        Position(
            ticker="HYG/250620P00072000",  # HYG Jun 2025 $72 Put
            quantity=15,
            position_type="put",
            strike=72.0,
            expiry=datetime(2025, 6, 20),
            entry_price=1.20,
            entry_underlying_price=75.5,
            entry_iv=0.18,
        ),
    ]
    
    # Calculate greeks for all positions
    for pos in positions:
        if pos.ticker.startswith("SPY"):
            pos.calculate_greeks(585.0, 0.20)
        elif pos.ticker.startswith("VIX"):
            pos.calculate_greeks(14.9, 0.90)
        elif pos.ticker.startswith("HYG"):
            pos.calculate_greeks(75.5, 0.18)
    
    return Portfolio(positions=positions, cash=50000.0)
