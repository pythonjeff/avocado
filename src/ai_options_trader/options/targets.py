from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RequiredMove:
    """
    Delta-based approximation of the underlying move required to achieve a target option P&L.

    Notes:
    - Uses first-order delta only (ignores gamma/theta/vega/IV changes, bid/ask, and time).
    - Treat as a quick intuition aid, not a pricing model.
    """

    direction: str  # "up" for calls, "down" for puts
    move_usd: float
    move_pct: float | None


def required_underlying_move_for_profit_pct(
    *,
    opt_entry_price: float | None,
    delta: float | None,
    profit_pct: float = 0.05,
    underlying_px: float | None = None,
    opt_type: str | None = None,  # "call"|"put"
) -> RequiredMove | None:
    """
    Compute the underlying $ move required for a target option profit percent.

    Approximation:
        dOption ≈ delta * dUnderlying
        target profit = profit_pct * opt_entry_price
        => dUnderlying ≈ (profit_pct * opt_entry_price) / |delta|

    Inputs are per-share option price (e.g., 1.23 means $123/contract).
    """
    try:
        px = float(opt_entry_price) if opt_entry_price is not None else None
        d = float(delta) if delta is not None else None
        p = float(profit_pct)
    except Exception:
        return None

    if px is None or d is None:
        return None
    if px <= 0 or p <= 0:
        return None
    if abs(d) <= 1e-9:
        return None

    # Magnitude in underlying dollars per share.
    move_usd = (p * px) / abs(d)

    move_pct = None
    try:
        if underlying_px is not None and float(underlying_px) > 0:
            move_pct = float(move_usd) / float(underlying_px)
    except Exception:
        move_pct = None

    ot = (opt_type or "").strip().lower()
    direction = "down" if ot == "put" else "up"
    return RequiredMove(direction=direction, move_usd=float(move_usd), move_pct=move_pct)


def format_required_move(m: RequiredMove | None) -> str:
    if m is None:
        return "n/a"
    sign = "+" if m.direction == "up" else "-"
    if m.move_pct is not None:
        return f"{sign}${m.move_usd:.2f} ({sign}{100.0*m.move_pct:.2f}%)"
    return f"{sign}${m.move_usd:.2f}"

