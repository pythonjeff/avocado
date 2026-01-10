from __future__ import annotations

from ai_options_trader.portfolio.universe import STARTER_UNIVERSE


def test_starter_universe_contains_required_proxies():
    tickers = set(STARTER_UNIVERSE.basket_equity)
    assert "GLDM" in tickers  # gold proxy
    assert "SLV" in tickers   # silver proxy
    assert "IBIT" in tickers  # bitcoin proxy
    assert "SPY" in tickers   # S&P proxy


