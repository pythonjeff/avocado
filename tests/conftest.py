"""
Pytest configuration and shared fixtures for ai_options_trader tests.

Usage:
    @pytest.fixture functions are automatically available to all tests.
    Import helpers from conftest when needed.
"""
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pandas as pd
import pytest


def pytest_configure():
    """
    Ensure `src/` is on sys.path for the src-layout package import (`ai_options_trader`).
    This keeps tests runnable without requiring an editable install.
    """
    root = Path(__file__).resolve().parents[1]
    src = root / "src"
    if src.exists():
        sys.path.insert(0, str(src))


# =============================================================================
# Mock Settings Fixture
# =============================================================================

@dataclass
class MockSettings:
    """Mock settings object for tests that don't need real API keys."""
    alpaca_api_key: str = "test_key"
    alpaca_api_secret: str = "test_secret"
    alpaca_paper: bool = True
    openai_api_key: str = "test_openai_key"
    openai_model: str = "gpt-4o-mini"
    fred_api_key: str = "test_fred_key"
    fmp_api_key: str = "test_fmp_key"
    aot_cache_dir: str = "/tmp/test_cache"
    aot_price_source: str = "fmp"


@pytest.fixture
def mock_settings() -> MockSettings:
    """Provide mock settings for tests that don't need real API credentials."""
    return MockSettings()


# =============================================================================
# Sample Data Fixtures
# =============================================================================

@pytest.fixture
def sample_price_df() -> pd.DataFrame:
    """Sample price DataFrame for testing."""
    dates = pd.date_range("2024-01-01", periods=30, freq="D")
    return pd.DataFrame({
        "date": dates,
        "SPY": 450.0 + (pd.Series(range(30)) * 0.5),
        "QQQ": 380.0 + (pd.Series(range(30)) * 0.4),
        "IWM": 195.0 + (pd.Series(range(30)) * 0.2),
    }).set_index("date")


@pytest.fixture
def sample_fred_series() -> pd.DataFrame:
    """Sample FRED macro data for testing."""
    dates = pd.date_range("2024-01-01", periods=30, freq="D")
    return pd.DataFrame({
        "date": dates,
        "DGS10": 4.2 + (pd.Series(range(30)) * 0.01),  # 10Y yield
        "VIXCLS": 15.0 + (pd.Series(range(30)) * 0.1),  # VIX
        "DFF": 5.25,  # Fed funds rate (constant)
    }).set_index("date")


@pytest.fixture
def sample_positions() -> list[dict]:
    """Sample portfolio positions for testing."""
    return [
        {
            "symbol": "SPY",
            "qty": 100,
            "side": "long",
            "market_value": 45000.0,
            "avg_entry_price": 440.0,
            "current_price": 450.0,
            "unrealized_pl": 1000.0,
        },
        {
            "symbol": "SPY250117C00480000",  # SPY call option
            "qty": 2,
            "side": "long",
            "market_value": 500.0,
            "avg_entry_price": 2.0,
            "current_price": 2.50,
            "unrealized_pl": 100.0,
        },
    ]


# =============================================================================
# Mock API Client Fixtures
# =============================================================================

@pytest.fixture
def mock_alpaca_trading_client() -> MagicMock:
    """Mock Alpaca TradingClient for tests."""
    client = MagicMock()
    
    # Mock account
    mock_account = MagicMock()
    mock_account.equity = "100000.00"
    mock_account.cash = "50000.00"
    mock_account.buying_power = "80000.00"
    client.get_account.return_value = mock_account
    
    # Mock positions (empty by default)
    client.get_all_positions.return_value = []
    
    return client


@pytest.fixture
def mock_fred_client() -> MagicMock:
    """Mock FredClient for tests."""
    client = MagicMock()
    
    # Mock series retrieval
    def mock_get_series(series_id: str, **kwargs) -> pd.Series:
        dates = pd.date_range("2024-01-01", periods=30, freq="D")
        return pd.Series(
            [4.2 + i * 0.01 for i in range(30)],
            index=dates,
            name=series_id,
        )
    
    client.get_series.side_effect = mock_get_series
    return client


# =============================================================================
# Test Data Helpers
# =============================================================================

def make_option_candidate(
    symbol: str = "SPY250117C00450000",
    delta: float = 0.35,
    bid: float = 2.50,
    ask: float = 2.60,
    oi: int = 5000,
    volume: int = 1000,
) -> Any:
    """
    Create a mock OptionCandidate for testing.
    
    Usage:
        candidate = make_option_candidate(delta=0.40, bid=3.0, ask=3.10)
    """
    from ai_options_trader.data.alpaca import OptionCandidate
    
    mid = (bid + ask) / 2
    return OptionCandidate(
        symbol=symbol,
        bid=bid,
        ask=ask,
        mid=mid,
        last=mid,
        delta=delta,
        gamma=0.02,
        theta=-0.05,
        vega=0.15,
        iv=0.22,
        oi=oi,
        volume=volume,
    )


def make_regime_state(
    regime: str = "RISK-ON",
    vix: float = 15.0,
    hy_spread: float = 350.0,
    dxy: float = 103.0,
) -> dict:
    """
    Create a sample regime state dict for testing.
    
    Usage:
        state = make_regime_state(regime="CAUTIOUS", vix=22.0)
    """
    return {
        "regime": regime,
        "vix": vix,
        "vix_zscore": (vix - 18.0) / 5.0,
        "hy_spread": hy_spread,
        "dxy": dxy,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
