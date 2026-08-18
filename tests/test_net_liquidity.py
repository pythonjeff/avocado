"""Smoke tests for net liquidity composite (lox.funding.net_liquidity)."""
from __future__ import annotations

from datetime import date

import pandas as pd

import lox.funding.net_liquidity as nl


def _fake_tga_daily(*, refresh: bool = False, lookback_days: int = 60) -> pd.DataFrame:
    return pd.DataFrame({
        "date": pd.bdate_range("2026-04-01", periods=22, freq="B").date,
        "tga_close_b": [800 + i * 5 for i in range(22)],  # rising → drains
    })


class _FakeFred:
    def __init__(self, *args, **kwargs):
        pass

    def fetch_series(self, *, series_id, start_date, refresh):
        idx = pd.bdate_range("2026-04-01", periods=22, freq="B")
        if series_id == "RRPONTSYD":
            return pd.DataFrame({"date": idx, "value": [10.0] * 22})
        if series_id == "WALCL":
            # weekly Wed-only series, in $millions
            wed_idx = pd.date_range("2026-04-01", periods=5, freq="W-WED")
            return pd.DataFrame({"date": wed_idx, "value": [7_000_000.0 + i * 5_000 for i in range(5)]})
        raise ValueError(f"unexpected series {series_id}")


def test_compute_net_liquidity_metrics_shapes(monkeypatch):
    from lox.config import Settings

    monkeypatch.setattr(nl, "fetch_tga_daily", _fake_tga_daily)
    monkeypatch.setattr(nl, "FredClient", _FakeFred)
    monkeypatch.setattr(nl, "load_settings", lambda: Settings(FRED_API_KEY="fake"))

    m = nl.compute_net_liquidity_metrics()
    assert isinstance(m["asof"], str)
    assert isinstance(m["level_t"], float)
    assert isinstance(m["delta_1d_b"], float)
    assert isinstance(m["delta_5d_b"], float)
    assert isinstance(m["delta_30d_b"], float)
    comps = m["components_b"]
    assert set(comps.keys()) == {"tga_b", "rrp_b", "walcl_b"}
    # net = (walcl - tga - rrp); rising TGA + steady RRP + slow-moving WALCL
    # → composite should be falling over the window
    assert m["delta_30d_b"] < 0
    series = m["series_30d_t"]
    assert len(series) >= 4


def test_compute_net_liquidity_metrics_no_api_key(monkeypatch):
    from lox.config import Settings

    monkeypatch.setattr(nl, "load_settings", lambda: Settings(FRED_API_KEY=None))
    m = nl.compute_net_liquidity_metrics()
    assert m["level_t"] is None
    assert m["asof"] is None
    assert m["components_b"] is None
