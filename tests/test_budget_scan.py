from __future__ import annotations

from datetime import date

from ai_options_trader.data.alpaca import OptionCandidate
from ai_options_trader.options.budget_scan import affordable_options_for_ticker, pick_best_affordable


def _c(
    symbol: str,
    *,
    bid: float | None,
    ask: float | None,
    last: float | None = None,
    delta: float | None = None,
    iv: float | None = None,
    oi: int | None = 500,
    volume: int | None = 500,
) -> OptionCandidate:
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
        iv=iv,
        oi=oi,
        volume=volume,
        bid=bid,
        ask=ask,
        last=last,
    )


def test_affordable_options_filters_by_premium_and_dte():
    today = date(2026, 1, 7)
    # DTE=10, ask=$0.80 => $80 premium
    a = _c("SPY260117C00600000", bid=0.79, ask=0.80, delta=0.30)
    # DTE=10, ask=$1.20 => $120 premium (excluded)
    b = _c("SPY260117C00605000", bid=1.10, ask=1.20, delta=0.30)
    # DTE=3 => excluded by min_dte_days=7
    c = _c("SPY260110C00600000", bid=0.50, ask=0.60, delta=0.30)
    # Missing delta => excluded by require_delta=True
    d = _c("SPY260117C00610000", bid=0.20, ask=0.30, delta=None)

    out = affordable_options_for_ticker(
        [a, b, c, d],
        ticker="SPY",
        max_premium_usd=100.0,
        min_dte_days=7,
        max_dte_days=30,
        want="call",
        price_basis="ask",
        require_delta=True,
        today=today,
    )
    assert [o.symbol for o in out] == [a.symbol]


def test_pick_best_affordable_prefers_spread_ok_and_delta_near_target():
    today = date(2026, 1, 7)
    # Good spread, delta near target
    a = _c("SPY260117C00600000", bid=0.79, ask=0.80, delta=0.28)
    # Worse spread, delta exact
    b = _c("SPY260117C00605000", bid=0.60, ask=0.90, delta=0.30)
    opts = affordable_options_for_ticker(
        [a, b],
        ticker="SPY",
        max_premium_usd=100.0,
        min_dte_days=7,
        max_dte_days=30,
        want="call",
        price_basis="ask",
        today=today,
    )
    best = pick_best_affordable(opts, target_abs_delta=0.30, max_spread_pct=0.30)
    assert best is not None
    assert best.symbol == a.symbol


