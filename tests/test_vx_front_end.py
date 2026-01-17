from __future__ import annotations

from datetime import date

import pytest

from ai_options_trader.volatility.vx_front_end import parse_vx_front_end_from_settlement_csv


def test_parse_vx_front_end_prefers_monthlies_over_weeklies():
    csv_text = """Product,Symbol,Expiration Date,Price
VX,VX02/F6,2026-01-14,16.1224
VX,VX/F6,2026-01-21,16.1224
VX,VX04/F6,2026-01-28,16.1224
VX,VX/G6,2026-02-18,17.9274
"""
    fe = parse_vx_front_end_from_settlement_csv(dt=date(2026, 1, 12), csv_text=csv_text, spot_vix=15.0)
    assert fe.m1_symbol == "VX/F6"
    assert fe.m2_symbol == "VX/G6"
    assert fe.m1_expiration == date(2026, 1, 21)
    assert fe.m2_expiration == date(2026, 2, 18)
    assert fe.contango_pct == pytest.approx((17.9274 / 16.1224 - 1.0) * 100.0, rel=1e-9)
    assert fe.spot_minus_m1 == pytest.approx(15.0 - 16.1224)


def test_parse_vx_front_end_raises_when_no_vx_rows():
    csv_text = """Product,Symbol,Expiration Date,Price
ES,ES/H6,2026-03-20,5000
"""
    with pytest.raises(ValueError):
        parse_vx_front_end_from_settlement_csv(dt=date(2026, 1, 12), csv_text=csv_text)

