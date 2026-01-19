"""Shared utilities for autopilot module."""
from __future__ import annotations

import re


def to_float(x) -> float | None:
    """Safely convert to float, returning None on failure."""
    try:
        return float(x) if x is not None else None
    except Exception:
        return None


def extract_underlying(symbol: str) -> str | None:
    """
    Extract underlying ticker from option symbol.
    
    Examples:
        VIXY260220C00028000 -> VIXY
        IEF260227P00095500  -> IEF
        AAPL -> AAPL (equity passthrough)
    """
    s = (symbol or "").strip().upper()
    if not s:
        return None
    m = re.match(r"^([A-Z]+)", s)
    return str(m.group(1)) if m else s


# Hedge-like tickers (inverse/vol instruments)
HEDGE_TICKERS: set[str] = {
    # Long vol
    "VIXY",
    # Inverse equity ETFs
    "SH", "SDS", "SPXU", "PSQ", "QID", "SQQQ",
    "RWM", "TWM", "TZA", "DOG", "DXD",
    # Rates / credit inverse
    "TBF", "TMV", "TBT", "SJB",
}

# Leveraged inverse equity (avoid stacking)
LEVERED_INVERSE_EQUITY: set[str] = {
    "SQQQ", "SPXU", "TZA", "SDS", "QID", "TWM", "DXD",
}

# Inverse ETF proxies for bearish exposure
INVERSE_PROXY: dict[str, str] = {
    "SPLG": "SH", "SPY": "SH",
    "QQQM": "PSQ", "QQQ": "PSQ",
    "IWM": "RWM", "DIA": "DOG",
    "TLT": "TBF", "HYG": "SJB",
}
