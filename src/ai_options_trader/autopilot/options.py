"""Option leg attachment for autopilot."""
from __future__ import annotations

from datetime import date


def attach_option_legs(
    candidates: list[dict],
    data_client,
    settings,
    *,
    max_premium_usd: float = 100.0,
    min_days: int = 30,
    max_days: int = 90,
    target_abs_delta: float = 0.30,
    max_spread_pct: float = 0.30,
    budget_mode: str = "strict",
    budget_total: float = 0.0,
    max_candidates: int = 30,
) -> dict[str, dict]:
    """
    Attach option legs to candidates.
    
    Args:
        candidates: List of candidate dicts with ticker and direction
        data_client: Alpaca data client
        settings: App settings
        max_premium_usd: Max premium per contract (strict mode)
        min_days: Min DTE
        max_days: Max DTE
        target_abs_delta: Target delta
        max_spread_pct: Max bid/ask spread
        budget_mode: "strict" or "flex"
        budget_total: Total budget (flex mode)
        max_candidates: Max candidates to scan
    
    Returns:
        Dict mapping ticker to leg dict
    """
    from ai_options_trader.data.alpaca import fetch_option_chain, to_candidates
    from ai_options_trader.options.budget_scan import (
        affordable_options_for_ticker,
        pick_best_affordable,
    )
    
    legs: dict[str, dict] = {}
    
    # Determine premium cap
    precompute_max_premium = (
        float(budget_total) if budget_mode == "flex" 
        else float(max_premium_usd)
    )
    
    for it in candidates[:max(10, max_candidates)]:
        tkr = str(it.get("ticker") or "")
        if not tkr:
            continue
        
        want = "call" if it.get("direction") == "bullish" else "put"
        
        try:
            chain = fetch_option_chain(
                data_client, tkr, 
                feed=settings.alpaca_options_feed
            )
            cands = list(to_candidates(chain, tkr))
            
            opts = affordable_options_for_ticker(
                cands,
                ticker=tkr,
                max_premium_usd=float(precompute_max_premium),
                min_dte_days=int(min_days),
                max_dte_days=int(max_days),
                want=want,
                price_basis="ask",
                min_price=0.05,
                max_spread_pct=float(max_spread_pct),
                require_delta=True,
                today=date.today(),
            )
            
            best = pick_best_affordable(
                opts,
                target_abs_delta=float(target_abs_delta),
                max_spread_pct=float(max_spread_pct),
            )
            
            if best:
                legs[tkr] = {
                    "symbol": best.symbol,
                    "type": best.opt_type,
                    "premium_usd": float(best.premium_usd),
                    "price": float(best.price),
                    "delta": float(best.delta) if best.delta is not None else None,
                }
        except Exception:
            continue
    
    return legs
