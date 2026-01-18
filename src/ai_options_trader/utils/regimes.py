"""Macro regime helpers to reduce boilerplate."""

from __future__ import annotations

from ai_options_trader.config import Settings
from ai_options_trader.macro.signals import build_macro_state
from ai_options_trader.macro.regime import classify_macro_regime_from_state
from ai_options_trader.funding.signals import build_funding_state
from ai_options_trader.usd.signals import build_usd_state


def get_current_macro_regime(settings: Settings, start: str = "2011-01-01", refresh: bool = False) -> dict:
    """
    Build current macro regime snapshot with standard thresholds.
    
    Returns:
    {
        "macro_state": MacroState,
        "macro_regime": MacroRegime,
        "liquidity_state": FundingState,
        "usd_state": UsdState,
    }
    """
    macro_state = build_macro_state(settings=settings, start_date=start, refresh=refresh)
    macro_regime = classify_macro_regime_from_state(
        cpi_yoy=macro_state.inputs.cpi_yoy,
        payrolls_3m_annualized=macro_state.inputs.payrolls_3m_annualized,
        inflation_momentum_minus_be5y=macro_state.inputs.inflation_momentum_minus_be5y,
        real_yield_proxy_10y=macro_state.inputs.real_yield_proxy_10y,
        z_inflation_momentum_minus_be5y=(
            macro_state.inputs.components.get("z_infl_mom_minus_be5y") if macro_state.inputs.components else None
        ),
        z_real_yield_proxy_10y=(
            macro_state.inputs.components.get("z_real_yield_proxy_10y") if macro_state.inputs.components else None
        ),
        use_zscores=True,
        cpi_target=3.0,
        infl_thresh=0.0,
        real_thresh=0.0,
    )
    liq_state = build_funding_state(settings=settings, start_date=start, refresh=refresh)
    usd_state = build_usd_state(settings=settings, start_date=start, refresh=refresh)

    return {
        "macro_state": macro_state,
        "macro_regime": macro_regime,
        "liquidity_state": liq_state,
        "usd_state": usd_state,
    }
