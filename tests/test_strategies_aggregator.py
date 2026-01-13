from __future__ import annotations

from ai_options_trader.strategies.aggregator import PortfolioAggregator
from ai_options_trader.strategies.base import CandidateTrade


def _c(
    *,
    sleeve: str,
    ticker: str,
    score: float,
    risk_factors: tuple[str, ...],
    est_cost_usd: float = 100.0,
    probe: bool = False,
) -> CandidateTrade:
    return CandidateTrade(
        sleeve=sleeve,
        ticker=ticker,
        action="OPEN_OPTION",
        instrument_type="option",
        direction="bearish",
        score=float(score),
        expRet=None,
        prob=None,
        rationale=None,
        expr="X",
        est_cost_usd=float(est_cost_usd),
        risk_factors=risk_factors,
        probe=bool(probe),
        meta={},
    )


def test_aggregator_blocks_multiple_levered_inverse_equity():
    agg = PortfolioAggregator(factor_cap=10)
    c1 = _c(sleeve="macro", ticker="SQQQ", score=10, risk_factors=("equity_beta_down", "inverse_equity"))
    c2 = _c(sleeve="vol", ticker="SPXU", score=9, risk_factors=("equity_beta_down", "inverse_equity"))
    res = agg.aggregate(candidates=[c1, c2], total_budget_usd=1000.0, sleeve_budgets_pct={"macro": 0.5, "vol": 0.5})
    assert [c.ticker for c in res.selected] == ["SQQQ"]
    assert any(r == "levered_inverse_equity_cap" for _c0, r in res.dropped)


def test_aggregator_blocks_psq_and_sqqq_together():
    agg = PortfolioAggregator(factor_cap=10)
    c1 = _c(sleeve="macro", ticker="PSQ", score=10, risk_factors=("equity_beta_down", "inverse_equity"))
    c2 = _c(sleeve="vol", ticker="SQQQ", score=9, risk_factors=("equity_beta_down", "inverse_equity"))
    res = agg.aggregate(candidates=[c1, c2], total_budget_usd=1000.0, sleeve_budgets_pct={"macro": 0.5, "vol": 0.5})
    assert [c.ticker for c in res.selected] == ["PSQ"]
    assert any(r == "psq_sqqq_exclusive" for _c0, r in res.dropped)


def test_aggregator_dedups_same_risk_signature_keeps_highest_score():
    agg = PortfolioAggregator(factor_cap=10)
    c1 = _c(sleeve="macro", ticker="SH", score=5, risk_factors=("equity_beta_down", "inverse_equity"))
    c2 = _c(sleeve="vol", ticker="RWM", score=7, risk_factors=("equity_beta_down", "inverse_equity"))
    res = agg.aggregate(candidates=[c1, c2], total_budget_usd=1000.0, sleeve_budgets_pct={"macro": 0.5, "vol": 0.5})
    assert [c.ticker for c in res.selected] == ["RWM"]
    assert any(r == "duplicate_risk_signature" for _c0, r in res.dropped)


def test_aggregator_factor_cap_allows_probe_exceptions():
    agg = PortfolioAggregator(factor_cap=1)
    c1 = _c(sleeve="macro", ticker="SH", score=10, risk_factors=("equity_beta_down",))
    c2 = _c(sleeve="vol", ticker="PSQ", score=9, risk_factors=("equity_beta_down",), probe=True)
    res = agg.aggregate(candidates=[c1, c2], total_budget_usd=1000.0, sleeve_budgets_pct={"macro": 0.5, "vol": 0.5})
    assert [c.ticker for c in res.selected] == ["SH", "PSQ"]


def test_aggregator_enforces_sleeve_budgets():
    agg = PortfolioAggregator(factor_cap=10)
    # macro sleeve budget=100, vol sleeve budget=100 (total=200)
    c1 = _c(sleeve="macro", ticker="A", score=10, risk_factors=("f1",), est_cost_usd=120.0)
    c2 = _c(sleeve="vol", ticker="B", score=9, risk_factors=("f2",), est_cost_usd=90.0)
    res = agg.aggregate(candidates=[c1, c2], total_budget_usd=200.0, sleeve_budgets_pct={"macro": 0.5, "vol": 0.5})
    assert [c.ticker for c in res.selected] == ["B"]
    assert any(r == "sleeve_budget" for _c0, r in res.dropped)

