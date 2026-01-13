from __future__ import annotations

from datetime import date

from ai_options_trader.options.budget_scan import AffordableOption, pick_best_delta_theta


def _o(
    *,
    delta: float,
    theta: float,
    premium_usd: float,
) -> AffordableOption:
    return AffordableOption(
        ticker="X",
        symbol=f"X_{delta}_{theta}",
        opt_type="put",
        expiry=date(2026, 3, 20),
        dte_days=67,
        strike=50.0,
        price=premium_usd / 100.0,
        premium_usd=float(premium_usd),
        spread_pct=0.10,
        delta=float(delta),
        gamma=0.01,
        theta=float(theta),
        vega=0.10,
        iv=0.40,
    )


def test_pick_best_delta_theta_prefers_delta_target_and_low_theta():
    # Target |delta|=0.30; option A has delta close but worse theta, option B has perfect theta but delta far.
    a = _o(delta=-0.28, theta=-0.020, premium_usd=200)
    b = _o(delta=-0.10, theta=-0.005, premium_usd=200)
    best = pick_best_delta_theta([a, b], target_abs_delta=0.30, delta_weight=1.0, theta_weight=1.0)
    assert best is not None
    assert best.symbol == a.symbol


def test_pick_best_delta_theta_theta_weight_can_flip_choice():
    a = _o(delta=-0.28, theta=-0.020, premium_usd=200)
    b = _o(delta=-0.10, theta=-0.005, premium_usd=200)
    # With sufficiently large theta weight, lower decay can dominate delta proximity.
    best = pick_best_delta_theta([a, b], target_abs_delta=0.30, delta_weight=1.0, theta_weight=50.0)
    assert best is not None
    assert best.symbol == b.symbol

