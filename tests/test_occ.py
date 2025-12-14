from datetime import date
import pytest
from ai_options_trader.utils.occ import parse_occ_option_symbol

def test_parse_occ_call():
    exp, t, k = parse_occ_option_symbol("NVDA251219C00100000", "NVDA")
    assert exp == date(2025, 12, 19)
    assert t == "call"
    assert k == 100.0

def test_parse_occ_put():
    exp, t, k = parse_occ_option_symbol("AAPL260117P00200000", "AAPL")
    assert exp == date(2026, 1, 17)
    assert t == "put"
    assert k == 200.0

def test_bad_prefix():
    with pytest.raises(ValueError):
        parse_occ_option_symbol("TSLA251219C00100000", "NVDA")
