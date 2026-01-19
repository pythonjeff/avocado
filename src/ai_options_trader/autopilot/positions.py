"""Position analysis for autopilot."""
from __future__ import annotations

from ai_options_trader.autopilot.utils import to_float, extract_underlying


def fetch_positions(trading) -> list[dict]:
    """
    Fetch all positions from Alpaca and normalize to dicts.
    
    Args:
        trading: Alpaca trading client
    
    Returns:
        List of position dicts with normalized fields
    """
    try:
        raw_positions = trading.get_all_positions()
    except Exception as e:
        raise RuntimeError(f"Failed to fetch Alpaca positions: {e}")
    
    positions: list[dict] = []
    for p in raw_positions:
        positions.append({
            "symbol": getattr(p, "symbol", ""),
            "qty": to_float(getattr(p, "qty", None)),
            "avg_entry_price": to_float(getattr(p, "avg_entry_price", None)),
            "current_price": to_float(getattr(p, "current_price", None)),
            "unrealized_pl": to_float(getattr(p, "unrealized_pl", None)),
            "unrealized_plpc": to_float(getattr(p, "unrealized_plpc", None)),
        })
    
    return positions


def stop_candidates(
    positions: list[dict],
    *,
    stop_loss_pct: float,
) -> list[dict]:
    """
    Find positions that should be considered for stop-loss.
    
    Args:
        positions: List of position dicts
        stop_loss_pct: Threshold (e.g., 0.30 = -30%)
    
    Returns:
        Positions with unrealized_plpc <= -stop_loss_pct
    """
    out = []
    threshold = -abs(float(stop_loss_pct))
    
    for p in positions:
        uplpc = p.get("unrealized_plpc")
        if isinstance(uplpc, (int, float)) and uplpc <= threshold:
            out.append(p)
    
    return out


def get_held_underlyings(positions: list[dict]) -> set[str]:
    """
    Get set of underlying tickers currently held.
    
    Extracts underlyings from both equity and option symbols.
    """
    held: set[str] = set()
    
    for p in positions:
        sym = str(p.get("symbol") or "").strip().upper()
        if not sym:
            continue
        
        held.add(sym)
        und = extract_underlying(sym)
        if und:
            held.add(und)
    
    return held


def is_option_position(symbol: str) -> bool:
    """Check if a symbol is an option (contains digits after letters)."""
    s = (symbol or "").strip().upper()
    und = extract_underlying(s)
    return und is not None and s != und and any(c.isdigit() for c in s)


def get_option_underlyings(positions: list[dict]) -> set[str]:
    """Get underlying tickers for option positions only."""
    unds: set[str] = set()
    
    for p in positions:
        sym = str(p.get("symbol") or "").strip().upper()
        if is_option_position(sym):
            und = extract_underlying(sym)
            if und:
                unds.add(und)
    
    return unds
