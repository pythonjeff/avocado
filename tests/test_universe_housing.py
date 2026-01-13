from __future__ import annotations

from ai_options_trader.portfolio.universe import get_universe


def test_housing_universe_is_defined_and_resolvable():
    uni = get_universe("housing")
    assert "MBB" in set(uni.basket_equity)
    assert "ITB" in set(uni.basket_equity)
    assert "VNQ" in set(uni.basket_equity)
    assert "REK" in set(uni.basket_equity)
    assert "SRS" in set(uni.basket_equity)

