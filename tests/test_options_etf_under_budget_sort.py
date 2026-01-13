from __future__ import annotations

from datetime import date

from ai_options_trader.data.alpaca import OptionCandidate
from ai_options_trader.options.budget_scan import affordable_options_for_ticker, pick_best_affordable


def _c(symbol: str, *, bid: float, ask: float, delta: float | None, oi: int | None = 500, volume: int | None = 500) -> OptionCandidate:
    return OptionCandidate(
        symbol=symbol,
        opt_type="",
        expiry=date(1970, 1, 1),
        strike=0.0,
        dte_days=0,
        delta=delta,
        gamma=None,
        theta=None,
        vega=None,
        iv=None,
        oi=oi,
        volume=volume,
        bid=bid,
        ask=ask,
        last=None,
    )


def test_etf_under_budget_delta_required_and_best_pick_prefers_spread_ok():
    today = date(2026, 1, 7)
    # Both under $100 (ask), but b has terrible spread; a should be picked.
    a = _c("SPLG260117C00050000", bid=0.95, ask=1.00, delta=0.30)  # spread ~5%
    b = _c("SPLG260117C00055000", bid=0.50, ask=1.00, delta=0.30)  # spread ~67%
    c = _c("SPLG260117C00060000", bid=0.10, ask=0.20, delta=None)  # filtered (delta required)

    opts = affordable_options_for_ticker(
        [a, b, c],
        ticker="SPLG",
        max_premium_usd=100.0,
        min_dte_days=7,
        max_dte_days=45,
        want="call",
        price_basis="ask",
        min_price=0.05,
        require_delta=True,
        today=today,
    )
    best = pick_best_affordable(opts, target_abs_delta=0.30, max_spread_pct=0.30)
    assert best is not None
    assert best.symbol == a.symbol


