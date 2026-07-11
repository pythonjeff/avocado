"""Tests for the offshore USD funding stress composite."""
from __future__ import annotations

from types import SimpleNamespace

from lox.funding.offshore import OffshoreStress, _score_offshore
from lox.funding.synthesis import build_funding_brief


def _fi():
    return SimpleNamespace(
        bank_reserves_usd_bn=3_400_000,
        on_rrp_usd_bn=200_000,
        fed_assets_chg_13w=None,
        tga_chg_4w=None,
    )


def _regime(score=50):
    return SimpleNamespace(score=score, label="Normal funding", name="normal_funding")


def _empty_rep():
    return {"pairs": [], "lags": [], "equity_pairs": [], "equity_lags": []}


# ── _score_offshore unit tests ──────────────────────────────────────────────

def test_score_offshore_calm_when_all_signals_quiet():
    score, label, drivers = _score_offshore(
        swap_lines_m=40, swap_max_4w_m=40, broad_z=0.1, eme_afe_z=0.0
    )
    assert score == 0
    assert label == "calm"


def test_score_offshore_swap_lines_active_drives_score():
    """SWPT >$50B (crisis territory) should push score >= 60."""
    score, label, drivers = _score_offshore(
        swap_lines_m=100_000, swap_max_4w_m=100_000, broad_z=0.0, eme_afe_z=0.0
    )
    assert score >= 60
    assert label in ("stress", "crisis")
    assert any("swap lines active" in d for d in drivers)


def test_score_offshore_broad_dollar_bid_adds_to_score():
    """Broad dollar Z > 2 in addition to swap-line draws → crisis-level score."""
    score, label, drivers = _score_offshore(
        swap_lines_m=10_000, swap_max_4w_m=10_000, broad_z=2.5, eme_afe_z=0.0
    )
    assert score >= 60
    assert any("broad dollar bid" in d for d in drivers)


def test_score_offshore_em_led_demand_attributed():
    """EM dollar > AFE dollar by >1.5σ → EM-led attribution, watch-level score."""
    score, label, drivers = _score_offshore(
        swap_lines_m=0, swap_max_4w_m=0, broad_z=1.7, eme_afe_z=1.8
    )
    assert any("EM-led" in d for d in drivers)
    assert score >= 20  # watch level minimum (broad +15 + EM +15 = 30)


def test_score_offshore_weak_dollar_reduces_score():
    """Dollar weakening = less offshore stress; weak-dollar driver noted."""
    score, label, drivers = _score_offshore(
        swap_lines_m=0, swap_max_4w_m=0, broad_z=-2.0, eme_afe_z=0.0
    )
    assert label == "calm"
    assert any("offered" in d for d in drivers)


# ── Brief integration tests ─────────────────────────────────────────────────

def test_brief_skips_offshore_block_when_calm():
    """Calm offshore (score<20) → no offshore_label, summarized in context notes."""
    offshore = OffshoreStress(
        asof="2026-05-13",
        swap_lines_usd_m=40,
        swap_lines_active=False,
        broad_dollar_z=-1.3,
        composite_score=0,
        composite_label="calm",
        drivers=["no offshore USD stress signals active"],
    )
    brief = build_funding_brief(_fi(), _regime(), _empty_rep(), offshore=offshore)
    assert brief.offshore_label is None
    # Single-line summary in context notes
    assert any("Offshore USD: calm" in n for n in brief.context_notes)


def test_brief_shows_offshore_block_when_watch():
    """Watch+ level → offshore block populated."""
    offshore = OffshoreStress(
        asof="2026-05-13",
        swap_lines_usd_m=0,
        broad_dollar_z=1.7,
        composite_score=25,
        composite_label="watch",
        drivers=["broad dollar bidding: Z +1.7σ vs 3y"],
    )
    brief = build_funding_brief(_fi(), _regime(), _empty_rep(), offshore=offshore)
    assert brief.offshore_label == "watch"
    assert brief.offshore_score == 25
    assert len(brief.offshore_drivers) == 1


def test_brief_promotes_active_swap_lines_to_active_signal_and_trade():
    """SWPT actively drawing → ActiveSignal + Long-DXY trade idea."""
    offshore = OffshoreStress(
        asof="2026-05-13",
        swap_lines_usd_m=8000,  # $8B drawn
        swap_lines_active=True,
        broad_dollar_z=1.2,
        composite_score=45,
        composite_label="stress",
        drivers=["swap lines drawing: $8.0B (elevated stress)"],
    )
    brief = build_funding_brief(_fi(), _regime(), _empty_rep(), offshore=offshore)

    swap_sigs = [s for s in brief.active_signals if "swap lines" in s.name.lower()]
    assert len(swap_sigs) == 1
    assert swap_sigs[0].tradeable

    swap_trades = [t for t in brief.trade_ideas if "DXY" in t.expression or "EM FX" in t.expression]
    assert len(swap_trades) >= 1
    assert swap_trades[0].conviction == "high"


def test_brief_no_offshore_arg_works():
    """Brief still works when offshore arg is None (backwards compat)."""
    brief = build_funding_brief(_fi(), _regime(), _empty_rep(), offshore=None)
    assert brief.offshore_label is None
    assert brief.offshore_drivers == []


def test_brief_broad_dollar_bid_without_swap_lines_emits_dxy_trade():
    """Broad-$ Z > 1.5 without active swap lines → moderate-conviction DXY call spread."""
    offshore = OffshoreStress(
        asof="2026-05-13",
        swap_lines_usd_m=0,
        swap_lines_active=False,
        broad_dollar_z=1.8,
        composite_score=25,
        composite_label="watch",
        drivers=["broad dollar bidding: Z +1.8σ"],
    )
    brief = build_funding_brief(_fi(), _regime(), _empty_rep(), offshore=offshore)
    dxy_trades = [t for t in brief.trade_ideas if "DXY call spread" in t.expression]
    assert len(dxy_trades) == 1
    assert dxy_trades[0].conviction == "moderate"
