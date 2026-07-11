"""Tests for the broadened historical-bubble comparison + similarity scorer."""
from __future__ import annotations

import pytest

from lox.bubble.history import (
    HISTORICAL_BUBBLES,
    SimilarityResult,
    compute_similarity,
    format_recover_months,
)


# ── Data integrity ──────────────────────────────────────────────────────────

def test_all_peaks_have_required_identity_fields():
    for p in HISTORICAL_BUBBLES:
        assert p.name and isinstance(p.name, str)
        assert isinstance(p.year, int)
        assert p.region in ("US", "Japan", "China")
        assert p.note and isinstance(p.note, str)


def test_at_least_one_peak_per_corridor():
    regions = {p.region for p in HISTORICAL_BUBBLES}
    assert "US" in regions
    # Adding international peaks was a goal of the broadening
    assert "Japan" in regions
    assert "China" in regions


def test_us_peaks_cover_concentration_and_leverage_eras():
    """The US set should include 1929 (leverage), 1968 (concentration), 2000, 2021."""
    us_years = {p.year for p in HISTORICAL_BUBBLES if p.region == "US"}
    for required_year in (1929, 1968, 2000, 2007, 2021):
        assert required_year in us_years, f"missing required US peak: {required_year}"


def test_drawdown_values_negative_or_none():
    for p in HISTORICAL_BUBBLES:
        if p.drawdown_pct is not None:
            assert p.drawdown_pct < 0, f"{p.name} has non-negative drawdown {p.drawdown_pct}"


def test_nikkei_is_tail_risk_anchor():
    nikkei = next((p for p in HISTORICAL_BUBBLES if "Nikkei" in p.name), None)
    assert nikkei is not None
    assert nikkei.region == "Japan"
    # 30y+ recovery is the headline tail-risk number
    assert nikkei.recover_months is not None and nikkei.recover_months >= 360


# ── format_recover_months ──────────────────────────────────────────────────

def test_format_recover_months_buckets():
    assert format_recover_months(None) == "—"
    assert format_recover_months(8) == "8m"
    assert format_recover_months(18) == "1.5y"
    assert format_recover_months(66) == "5.5y"
    assert format_recover_months(120) == "10y"
    assert format_recover_months(420) == "35y"


# ── compute_similarity ─────────────────────────────────────────────────────

def test_similarity_returns_us_peaks_only_by_default():
    today = {"buffett_pct": 200.0, "top10_share_pct": 30.0, "margin_to_gdp_pct": 3.6}
    results = compute_similarity(today)
    names = [r.peak_name for r in results]
    # No international peaks (Japan, China) in default results
    for n in names:
        assert "Nikkei" not in n
        assert "Shanghai" not in n


def test_similarity_orders_descending():
    today = {"buffett_pct": 200.0, "top10_share_pct": 30.0, "margin_to_gdp_pct": 3.6}
    results = compute_similarity(today)
    sims = [r.similarity for r in results]
    assert sims == sorted(sims, reverse=True)


def test_similarity_identifies_2021_when_today_equals_2021():
    """If today's values are exactly 2021's, similarity should rank 2021 first."""
    today = {"buffett_pct": 200.0, "top10_share_pct": 30.0, "margin_to_gdp_pct": 3.6}
    results = compute_similarity(today)
    assert results[0].peak_name.startswith("2021")
    assert results[0].similarity == pytest.approx(1.0)  # perfect match


def test_similarity_ranges_zero_to_one():
    today = {"buffett_pct": 233.0, "top10_share_pct": 40.0, "margin_to_gdp_pct": 1.9}
    results = compute_similarity(today)
    for r in results:
        assert 0.0 <= r.similarity <= 1.0


def test_similarity_handles_partial_today_data():
    """If only one metric available, similarity still works (single-dim L2)."""
    today = {"buffett_pct": 200.0}  # missing top10 + margin
    results = compute_similarity(today)
    assert len(results) > 0


def test_similarity_with_international_pool():
    """Setting same_region_only=None lets international peaks compete."""
    today = {"buffett_pct": 140.0, "top10_share_pct": 30.0, "margin_to_gdp_pct": 1.5}
    results = compute_similarity(today, same_region_only=None)
    names = [r.peak_name for r in results]
    # When unrestricted, Japan can appear
    assert any("Nikkei" in n for n in names)


def test_similarity_no_data_returns_empty():
    today = {"buffett_pct": None, "top10_share_pct": None, "margin_to_gdp_pct": None}
    results = compute_similarity(today)
    assert results == []


def test_similarity_today_2026_resembles_2021_more_than_1987():
    """
    Live-ish sanity check using today's actual measured values from the live
    CLI (Buffett 233%, top-10 40%, margin 1.9%). 2021 should rank above 1987.
    """
    today = {"buffett_pct": 233.0, "top10_share_pct": 40.0, "margin_to_gdp_pct": 1.9}
    results = compute_similarity(today)
    rank = {r.peak_name: i for i, r in enumerate(results)}
    p2021 = next(k for k in rank if k.startswith("2021"))
    p1987 = next(k for k in rank if k.startswith("1987"))
    assert rank[p2021] < rank[p1987], "2021 should rank higher than 1987 — more similar today"


def test_similarity_result_components_are_per_metric_squared():
    """Sanity check that components dict exposes per-metric contributions."""
    today = {"buffett_pct": 200.0, "top10_share_pct": 30.0, "margin_to_gdp_pct": 3.6}
    results = compute_similarity(today)
    top = results[0]
    assert isinstance(top.components, dict)
    # All similarity-metric keys should be present (we passed values for all 3)
    for m in ("buffett_pct", "top10_share_pct", "margin_to_gdp_pct"):
        assert m in top.components
