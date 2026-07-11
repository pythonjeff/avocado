"""Tests for the funding regime synthesis brief."""
from __future__ import annotations

from types import SimpleNamespace

from lox.funding.synthesis import (
    ActiveSignal,
    FundingBrief,
    TradeIdea,
    build_funding_brief,
)


def _fi(reserves_t=3.4, rrp_b=45, fed_assets_chg_b=-25):
    """Build a FundingInputs-shaped object (using SimpleNamespace to avoid pydantic)."""
    return SimpleNamespace(
        bank_reserves_usd_bn=reserves_t * 1_000_000,  # millions
        on_rrp_usd_bn=rrp_b * 1000,                    # millions
        fed_assets_chg_13w=fed_assets_chg_b * 1000,   # millions
        tga_chg_4w=None,
    )


def _regime(score=50, label="Normal funding"):
    return SimpleNamespace(score=score, label=label, name=label.lower().replace(" ", "_"))


def _all_eq_broken_report():
    """A correlation report where every Fed→equity channel is decoupled."""
    return {
        "asof": "2026-05-15",
        "pairs": [],
        "lags": [],
        "equity_pairs": [
            {"name": "SOFR-IORB ↔ VIX", "current": 0.10, "baseline": -0.10, "status": "broken"},
            {"name": "Net Liquidity ↔ VIX", "current": 0.15, "baseline": -0.05, "status": "flipped"},
            {"name": "ΔNet Liquidity ↔ ΔSPX", "current": 0.05, "baseline": 0.20, "status": "broken"},
            {"name": "ΔReserves ↔ ΔSPX", "current": 0.10, "baseline": -0.05, "status": "broken"},
            {"name": "ΔRRP ↔ ΔSPX", "current": -0.05, "baseline": 0.25, "status": "broken"},
        ],
        "equity_lags": [
            {"name": "SOFR-IORB → VIX", "best_corr": 0.51, "best_lag": 25, "tradeable": True,
             "interpretation": "Funding stress leading equity vol expansion."},
            {"name": "ΔWALCL → ΔSPX", "best_corr": 0.35, "best_lag": 25, "tradeable": True,
             "interpretation": "Fed balance-sheet pace leading equity drift."},
        ],
        "regime": "DECOUPLED",
        "rationale": "corridor moving independent of plumbing",
    }


def test_brief_detects_all_broken_equity_couplings():
    """Headline regime should call out plumbing-decoupled when all eq pairs broken."""
    fi = _fi()
    regime = _regime(score=42)
    rep = _all_eq_broken_report()
    brief = build_funding_brief(fi, regime, rep, cross_scores={}, nl_metrics={"level_t": 5.5, "delta_30d_b": -20.0})

    assert "Plumbing-decoupled" in brief.regime_line
    # Mentions reserves and RRP levels
    assert "3.40T" in brief.regime_line or "3.4" in brief.regime_line
    assert "RRP cushion essentially gone" in brief.regime_line


def test_brief_surfaces_tradeable_leads_as_active_signals():
    fi = _fi()
    regime = _regime(score=42)
    rep = _all_eq_broken_report()
    brief = build_funding_brief(fi, regime, rep)

    names = {s.name for s in brief.active_signals}
    assert "SOFR-IORB → VIX" in names
    assert "ΔWALCL → ΔSPX" in names
    assert all(s.tradeable for s in brief.active_signals)


def test_brief_emits_vol_trade_from_sofr_vix_lead():
    """When SOFR-IORB → VIX is active, brief must include a long-vol expression."""
    fi = _fi()
    regime = _regime(score=42)
    rep = _all_eq_broken_report()
    brief = build_funding_brief(fi, regime, rep)

    vol_trades = [t for t in brief.trade_ideas if "MOVE" in t.expression or "VIX" in t.expression]
    assert len(vol_trades) >= 1
    # Rationale must reference the actual active signal so user can verify
    assert any("SOFR-IORB" in t.rationale for t in vol_trades)


def test_brief_warns_against_equity_beta_when_all_channels_broken():
    fi = _fi()
    regime = _regime(score=42)
    rep = _all_eq_broken_report()
    brief = build_funding_brief(fi, regime, rep)

    do_not = [t for t in brief.trade_ideas if "DO NOT" in t.expression]
    assert len(do_not) == 1
    assert do_not[0].conviction == "high"


def test_brief_reserve_scarcity_triggers_kre_short():
    """Reserves <$3.2T + RRP <$100B should trigger the KRE-short idea."""
    fi = _fi(reserves_t=3.05, rrp_b=30)
    regime = _regime(score=72, label="Funding stress")
    rep = {
        "equity_pairs": [], "equity_lags": [],
        "pairs": [], "lags": [],
        "regime": "RESERVE-CONSTRAINED",
        "rationale": "reserves dominant",
    }
    brief = build_funding_brief(fi, regime, rep)

    kre_trades = [t for t in brief.trade_ideas if "KRE" in t.expression]
    assert len(kre_trades) == 1
    assert kre_trades[0].conviction == "high"


def test_brief_late_cycle_cross_regime_emits_size_warning():
    """Credit Euphoria + Bear Flatten should trigger a size-down trade idea."""
    fi = _fi()
    regime = _regime(score=42)
    rep = {"equity_pairs": [], "equity_lags": [], "pairs": [], "lags": []}
    cross = {
        "credit": {"score": 22, "label": "Credit Euphoria"},
        "rates": {"score": 65, "label": "Bear flattener"},
    }
    brief = build_funding_brief(fi, regime, rep, cross_scores=cross)

    size_warnings = [t for t in brief.trade_ideas if "Reduce gross" in t.expression or "size down" in t.expression.lower()]
    assert len(size_warnings) >= 1
    # The risk line should also mention late-cycle
    assert "Late-cycle" in brief.risk_line or "late-cycle" in brief.risk_line


def test_brief_lean_mapping_by_score():
    """Lean categorization should map cleanly from regime score."""
    cases = [
        (10, "constructive"),
        (35, "neutral-constructive"),
        (50, "neutral"),
        (65, "neutral-defensive"),
        (80, "defensive"),
    ]
    rep = {"equity_pairs": [], "equity_lags": [], "pairs": [], "lags": []}
    for score, expected_lean in cases:
        brief = build_funding_brief(_fi(), _regime(score=score), rep)
        assert brief.risk_lean == expected_lean, f"score={score} → expected {expected_lean}, got {brief.risk_lean}"


def test_brief_no_active_signals_no_active_section():
    """When nothing is tradeable, active_signals stays empty (not synthesized)."""
    rep = {"equity_pairs": [], "equity_lags": [], "pairs": [],
           "lags": [{"name": "X", "best_corr": 0.1, "best_lag": 2, "tradeable": False}]}
    brief = build_funding_brief(_fi(), _regime(score=42), rep)
    assert brief.active_signals == []


def test_brief_walcl_drift_bearish_idea():
    """ΔWALCL → ΔSPX active + WALCL shrinking → 'fade strength' trade idea."""
    fi = _fi(fed_assets_chg_b=-50)  # WALCL shrinking $50B/13w
    regime = _regime(score=42)
    rep = {
        "equity_pairs": [], "pairs": [],
        "equity_lags": [{"name": "ΔWALCL → ΔSPX", "best_corr": 0.35, "best_lag": 25, "tradeable": True,
                         "interpretation": "Fed balance-sheet pace leading equity drift."}],
        "lags": [],
    }
    brief = build_funding_brief(fi, regime, rep)

    walcl_trades = [t for t in brief.trade_ideas if "WALCL" in t.expression and "fade" in t.expression.lower()]
    assert len(walcl_trades) == 1
