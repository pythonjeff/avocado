from __future__ import annotations

from ai_options_trader.altdata.fmp import normalize_earnings_calendar


def test_normalize_earnings_calendar_handles_common_fields():
    rows = [
        {
            "symbol": "AAPL",
            "date": "2026-01-28",
            "time": "amc",
            "eps": "2.10",
            "epsEstimated": "2.00",
            "revenue": "120000000000",
            "revenueEstimated": "118000000000",
        }
    ]
    ev = normalize_earnings_calendar(rows)
    assert len(ev) == 1
    e = ev[0]
    assert e.ticker == "AAPL"
    assert e.date.isoformat() == "2026-01-28"
    assert e.time == "amc"
    assert e.eps == 2.10
    assert e.eps_estimated == 2.00

