"""Utility functions for autopilot command."""

from __future__ import annotations


def to_float(x) -> float | None:
    """Safely convert to float."""
    try:
        return float(x) if x is not None else None
    except Exception:
        return None


def stop_candidates(positions: list[dict], *, stop_loss_pct: float) -> list[dict]:
    """Find positions that meet stop-loss criteria."""
    out = []
    for p in positions:
        uplpc = p.get("unrealized_plpc")
        if isinstance(uplpc, (int, float)) and uplpc <= -abs(float(stop_loss_pct)):
            out.append(p)
    return out
