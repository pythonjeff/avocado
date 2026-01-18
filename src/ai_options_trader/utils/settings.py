"""Centralized settings utilities."""

from __future__ import annotations

import os

from ai_options_trader.config import Settings, load_settings


def safe_load_settings() -> Settings | None:
    """
    Load settings with graceful fallback.

    If .env is unreadable (e.g., sandbox), construct Settings directly from environment variables.
    Returns None if settings cannot be constructed.
    """
    try:
        return load_settings()
    except Exception:
        try:
            return Settings.model_construct(
                AOT_PRICE_SOURCE=os.getenv("AOT_PRICE_SOURCE", "fmp"),
                ALPACA_API_KEY=os.getenv("ALPACA_API_KEY", ""),
                ALPACA_API_SECRET=os.getenv("ALPACA_API_SECRET", ""),
                ALPACA_PAPER=str(os.getenv("ALPACA_PAPER", "true")).lower() not in {"0", "false", "no"},
                ALPACA_DATA_KEY=os.getenv("ALPACA_DATA_KEY"),
                ALPACA_DATA_SECRET=os.getenv("ALPACA_DATA_SECRET"),
                ALPACA_OPTIONS_FEED=os.getenv("ALPACA_OPTIONS_FEED"),
                OPENAI_API_KEY=os.getenv("OPENAI_API_KEY"),
                OPENAI_MODEL=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                FRED_API_KEY=os.getenv("FRED_API_KEY"),
                FMP_API_KEY=os.getenv("FMP_API_KEY"),
            )
        except Exception:
            return None
