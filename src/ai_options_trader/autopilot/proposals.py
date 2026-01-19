"""Trade proposal generation and allocation."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ai_options_trader.autopilot.utils import (
    to_float,
    HEDGE_TICKERS,
    LEVERED_INVERSE_EQUITY,
    INVERSE_PROXY,
)
from ai_options_trader.autopilot.budget import BudgetPlan


@dataclass
class TradeProposal:
    """A proposed trade."""
    kind: str  # OPEN_OPTION or OPEN_SHARES
    ticker: str
    idea: dict
    est_cost_usd: float
    exposure: str  # bullish or bearish
    leg: dict | None = None  # Option leg details
    qty: int = 1
    limit: float | None = None
    meta: dict = field(default_factory=dict)


@dataclass
class AllocationResult:
    """Result of trade allocation."""
    proposals: list[TradeProposal]
    remaining_equity: float
    remaining_options: float
    remaining_total: float
    n_bullish: int
    n_bearish: int


def build_proposals(
    *,
    candidates: list[dict],
    legs: dict[str, dict],
    prices,  # DataFrame
    plan: BudgetPlan,
    held_underlyings: set[str],
    budget_mode: str,
    flex_prefer: str = "options",
    with_options: bool = True,
    max_premium_usd: float = 100.0,
    shares_budget_usd: float = 100.0,
    max_new_trades: int = 3,
    min_new_trades: int = 2,
) -> AllocationResult:
    """
    Build trade proposals from candidates within budget constraints.
    
    Args:
        candidates: Ranked trade ideas
        legs: Option legs by ticker
        prices: Price DataFrame
        plan: Budget allocation plan
        held_underlyings: Already-held tickers to skip
        budget_mode: "strict" or "flex"
        flex_prefer: "options" or "shares" (flex mode preference)
        with_options: Whether to include options
        max_premium_usd: Max premium per option (strict mode)
        shares_budget_usd: Budget per share position (strict mode)
        max_new_trades: Maximum proposals
        min_new_trades: Minimum proposals to target
    
    Returns:
        AllocationResult with proposals and remaining budgets
    """
    # Initialize budgets
    budget_total = plan.total
    remaining_total = max(0.0, budget_total)
    remaining_equity = max(0.0, plan.budget_equity) if budget_mode == "strict" else 0.0
    remaining_options = max(0.0, plan.budget_options) if budget_mode == "strict" else 0.0
    
    proposals: list[TradeProposal] = []
    opened: set[str] = set()
    n_bullish = 0
    n_bearish = 0
    
    def _has_hedge_exposure() -> bool:
        return any(p.exposure == "bearish" for p in proposals)
    
    def _has_levered_inverse() -> bool:
        return any(
            p.kind == "OPEN_SHARES" and p.ticker in LEVERED_INVERSE_EQUITY
            for p in proposals
        )
    
    def _add_option(tkr: str, it: dict) -> bool:
        nonlocal remaining_total, remaining_options, n_bullish, n_bearish
        
        leg = legs.get(tkr)
        if not leg:
            return False
        
        prem = float(leg.get("premium_usd") or 0.0)
        if prem <= 0 or len(proposals) >= max_new_trades:
            return False
        
        if budget_mode == "flex":
            if prem > remaining_total + 1e-9:
                return False
            remaining_needed = max(1, min_new_trades - len(proposals))
            per_trade_cap = remaining_total / max(1, remaining_needed)
            if len(proposals) < min_new_trades and prem > per_trade_cap + 1e-9:
                return False
            
            direction = str(it.get("direction") or "")
            proposals.append(TradeProposal(
                kind="OPEN_OPTION",
                ticker=tkr,
                leg=leg,
                idea=it,
                est_cost_usd=prem,
                exposure=direction,
            ))
            remaining_total -= prem
        else:
            if prem > max_premium_usd or prem > remaining_options:
                return False
            
            direction = str(it.get("direction") or "")
            proposals.append(TradeProposal(
                kind="OPEN_OPTION",
                ticker=tkr,
                leg=leg,
                idea=it,
                est_cost_usd=prem,
                exposure=direction,
            ))
            remaining_options -= prem
        
        if str(it.get("direction") or "") == "bearish":
            n_bearish += 1
        else:
            n_bullish += 1
        return True
    
    def _add_shares(tkr: str, it: dict) -> bool:
        nonlocal remaining_total, remaining_equity, n_bullish, n_bearish
        
        last_px = None
        try:
            if tkr in prices.columns:
                col = prices[tkr].dropna()
                if not col.empty:
                    last_px = to_float(col.iloc[-1])
        except Exception:
            pass
        
        if not last_px or last_px <= 0:
            return False
        if len(proposals) >= max_new_trades:
            return False
        if tkr in opened:
            return False
        
        if budget_mode == "flex":
            if remaining_total <= 0:
                return False
            remaining_needed = max(1, min_new_trades - len(proposals))
            per_trade_cap = remaining_total / max(1, remaining_needed)
            qty = int(per_trade_cap // last_px)
            if qty <= 0:
                return False
            cost = qty * last_px
            if cost > remaining_total + 1e-9:
                return False
            
            exposure = str(it.get("exposure") or it.get("direction") or "")
            proposals.append(TradeProposal(
                kind="OPEN_SHARES",
                ticker=tkr,
                qty=qty,
                limit=last_px,
                idea=it,
                est_cost_usd=cost,
                exposure=exposure,
            ))
            opened.add(tkr)
            remaining_total -= cost
        else:
            if remaining_equity <= 0:
                return False
            alloc = min(shares_budget_usd, remaining_equity)
            qty = int(alloc // last_px)
            if qty <= 0:
                return False
            cost = qty * last_px
            if cost > remaining_equity + 1e-9:
                return False
            
            exposure = str(it.get("exposure") or it.get("direction") or "")
            proposals.append(TradeProposal(
                kind="OPEN_SHARES",
                ticker=tkr,
                qty=qty,
                limit=last_px,
                idea=it,
                est_cost_usd=cost,
                exposure=exposure,
            ))
            opened.add(tkr)
            remaining_equity -= cost
        
        exposure = str(it.get("exposure") or it.get("direction") or "")
        if exposure == "bearish":
            n_bearish += 1
        else:
            n_bullish += 1
        return True
    
    # Main allocation loop
    for it in candidates:
        if len(proposals) >= max_new_trades:
            break
        
        tkr = str(it.get("ticker") or "").strip().upper()
        if not tkr or tkr in held_underlyings:
            continue
        
        direction = str(it.get("direction") or "")
        
        # Handle hedge instruments specially
        if tkr in HEDGE_TICKERS:
            if _has_hedge_exposure():
                continue
            if tkr in LEVERED_INVERSE_EQUITY and _has_levered_inverse():
                continue
            it2 = dict(it)
            it2["direction"] = "bullish"
            it2["exposure"] = "bearish"
            if _add_shares(tkr, it2):
                continue
        
        # Flex preference
        if budget_mode == "flex" and flex_prefer == "shares":
            if direction == "bullish" and _add_shares(tkr, it):
                continue
        
        # Try options first when enabled
        if with_options and legs.get(tkr):
            opt_type = legs.get(tkr, {}).get("type")
            if direction == "bullish" and opt_type == "call":
                if _add_option(tkr, it):
                    continue
            if direction == "bearish" and opt_type == "put":
                if _add_option(tkr, it):
                    continue
        
        # Fallback to shares for bullish
        if direction == "bullish":
            if _add_shares(tkr, it):
                continue
        
        # Bearish via inverse proxy
        if not with_options and direction == "bearish":
            inv = INVERSE_PROXY.get(tkr)
            if inv and inv not in held_underlyings:
                it2 = dict(it)
                it2["ticker"] = inv
                it2["direction"] = "bullish"
                it2["exposure"] = "bearish"
                it2["notes"] = f"inverse_proxy_for={tkr}"
                _add_shares(inv, it2)
    
    # Ensure two-sided exposure
    if (n_bullish == 0 or n_bearish == 0) and len(proposals) < max_new_trades:
        need = "bearish" if n_bearish == 0 else "bullish"
        for it in candidates:
            if len(proposals) >= max_new_trades:
                break
            tkr = str(it.get("ticker") or "").strip().upper()
            if not tkr or tkr in held_underlyings:
                continue
            if str(it.get("direction") or "") != need:
                continue
            
            if need == "bearish":
                if with_options and legs.get(tkr, {}).get("type") == "put":
                    if _add_option(tkr, it):
                        break
                inv = INVERSE_PROXY.get(tkr)
                if inv and inv not in held_underlyings:
                    it2 = dict(it)
                    it2["ticker"] = inv
                    it2["direction"] = "bullish"
                    it2["exposure"] = "bearish"
                    if _add_shares(inv, it2):
                        break
            else:
                if with_options and legs.get(tkr, {}).get("type") == "call":
                    if _add_option(tkr, it):
                        break
                if _add_shares(tkr, it):
                    break
    
    return AllocationResult(
        proposals=proposals,
        remaining_equity=remaining_equity,
        remaining_options=remaining_options,
        remaining_total=remaining_total,
        n_bullish=n_bullish,
        n_bearish=n_bearish,
    )
