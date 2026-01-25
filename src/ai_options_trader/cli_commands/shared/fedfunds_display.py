"""Display helpers for Fed funds outlook command."""

from __future__ import annotations

from rich.table import Table
from rich.text import Text
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ai_options_trader.macro.models import MacroState
    from ai_options_trader.funding.models import FundingState


def build_regime_table(
    macro_regime,
    fed_stance: str,
    fed_desc: str,
    liq_status: str,
    liq_desc: str,
    buffer_status: str,
) -> Table:
    """Build the regime dashboard table."""
    t = Table(show_header=False, box=None, padding=(0, 1))
    t.add_column("Category", style="bold cyan", no_wrap=True, width=15)
    t.add_column("Status")
    
    # Macro regime
    macro_criteria = f"CPI YoY > 3.0% and job growth < 0 (PAYEMS 3m annualized)"
    t.add_row(
        "MACRO",
        f"[bold]{macro_regime.name.upper()}[/bold]        {macro_criteria}"
    )
    
    # Fed policy
    t.add_row(
        "FED POLICY",
        f"[bold]{fed_stance}[/bold]        {fed_desc}"
    )
    
    # Liquidity (with buffer status in parentheses)
    t.add_row(
        "LIQUIDITY",
        f"[bold]{liq_status}[/bold]            {liq_desc}"
    )
    t.add_row(
        "",
        f"[bold](ORDERLY FUNDING)[/bold]                                                   [Buffer: {buffer_status}]"
    )
    
    return t


def build_portfolio_relevance_table() -> Table:
    """Build the portfolio relevance table."""
    t = Table(show_header=False, box=None, padding=(0, 1))
    t.add_column("Pillar", style="bold yellow", no_wrap=True, width=15)
    t.add_column("Relevance")
    
    t.add_row(
        "Macro",
        "Stagflation raises downside/multiple-compression risk — supportive for equity/credit downside hedges"
    )
    t.add_row(
        "Policy",
        "Restrictive real rates keep risk assets sensitive to bad data — supportive for vol and downside protection"
    )
    t.add_row(
        "Liquidity",
        "Buffer depleted increases probability of jumpy selloffs (needs funding confirmation) — supportive for convex hedges"
    )
    
    return t


def add_growth_inflation_section(t: Table, macro_state: MacroState) -> None:
    """Add Growth & Inflation section to market data table."""
    t.add_row("[bold]Growth & Inflation[/bold]", "")
    
    # Inflation: headline + momentum + stickiness
    t.add_row("  CPI (YoY)", f"{macro_state.inputs.cpi_yoy:.2f}%")
    if macro_state.inputs.cpi_3m_annualized is not None:
        mom_trend = "(rising)" if macro_state.inputs.cpi_3m_annualized > macro_state.inputs.cpi_yoy else "(falling)"
        t.add_row("    -> 3m momentum", f"{macro_state.inputs.cpi_3m_annualized:.2f}% {mom_trend}")
    if macro_state.inputs.median_cpi_yoy is not None:
        t.add_row("  Median CPI (YoY)", f"{macro_state.inputs.median_cpi_yoy:.2f}% (stickiness)")
    if macro_state.inputs.core_cpi_yoy is not None:
        t.add_row("    -> Core CPI", f"{macro_state.inputs.core_cpi_yoy:.2f}%")
    
    # Market inflation expectations
    if macro_state.inputs.breakeven_5y5y is not None:
        t.add_row("  5y5y breakeven", f"{macro_state.inputs.breakeven_5y5y:.2f}% (mkt expectations)")
        if macro_state.inputs.cpi_yoy:
            infl_vs_5y5y = macro_state.inputs.cpi_yoy - macro_state.inputs.breakeven_5y5y
            infl_flag = " [running hot]" if infl_vs_5y5y > 0.3 else ""
            t.add_row("    -> Inflation - 5y5y", f"{infl_vs_5y5y:+.2f}pp{infl_flag}")
    
    t.add_row("", "")
    
    # Labor: payrolls + unemployment/claims (cycle indicators)
    t.add_row("  Payrolls (3m ann)", f"{macro_state.inputs.payrolls_3m_annualized:.2f}%")
    if macro_state.inputs.payrolls_yoy is not None:
        t.add_row("    -> YoY", f"{macro_state.inputs.payrolls_yoy:.2f}%")
    
    if macro_state.inputs.unemployment_rate is not None:
        t.add_row("  Unemployment rate", f"{macro_state.inputs.unemployment_rate:.1f}% (cycle read)")
    elif macro_state.inputs.initial_claims_4w is not None:
        claims_k = macro_state.inputs.initial_claims_4w / 1000
        t.add_row("  Initial claims (4w)", f"{claims_k:.0f}k (cycle read)")


def add_policy_conditions_section(t: Table, macro_state: MacroState) -> None:
    """Add Policy Conditions section to market data table."""
    t.add_row("", "")
    t.add_row("[bold]Policy Conditions[/bold]", "")
    
    # Market-implied policy path
    if macro_state.inputs.ust_2y is not None:
        t.add_row("  2Y yield", f"{macro_state.inputs.ust_2y:.2f}% (mkt policy path)")
    
    # Nominal + real yields (show both for context)
    if macro_state.inputs.ust_10y is not None:
        t.add_row("  10Y yield", f"{macro_state.inputs.ust_10y:.2f}%")
    t.add_row("  10Y real yield", f"{macro_state.inputs.real_yield_proxy_10y:.2f}% (policy restrictiveness)")
    
    if macro_state.inputs.curve_2s10s is not None:
        curve_flag = " [inverted]" if macro_state.inputs.curve_2s10s < 0 else ""
        t.add_row("    -> Curve (2s10s)", f"{macro_state.inputs.curve_2s10s:.0f} bps{curve_flag}")
    
    if macro_state.inputs.inflation_momentum_minus_be5y is not None:
        delta_sym = "+" if macro_state.inputs.inflation_momentum_minus_be5y >= 0 else ""
        policy_flag = " [inflation > breakevens]" if macro_state.inputs.inflation_momentum_minus_be5y > 0.3 else ""
        t.add_row("    -> Infl vs BE5Y", f"{delta_sym}{macro_state.inputs.inflation_momentum_minus_be5y:.2f}pp{policy_flag}")


def add_overnight_funding_section(t: Table, liq_state: FundingState) -> None:
    """Add Overnight Funding section to market data table."""
    t.add_row("", "")
    t.add_row("[bold]Overnight Funding[/bold]", "")
    
    rrp_floor = (liq_state.inputs.effr - 0.25) if liq_state.inputs.effr else None
    iorb = liq_state.inputs.iorb
    
    if rrp_floor and iorb:
        t.add_row("  Policy corridor", f"{rrp_floor:.2f}% (RRP) - {iorb:.2f}% (IORB)")
    
    if liq_state.inputs.effr:
        t.add_row("  EFFR", f"{liq_state.inputs.effr:.2f}% (policy anchor)")
        if iorb:
            effr_iorb = (liq_state.inputs.effr - iorb) * 100
            t.add_row("    -> EFFR-IORB", f"{effr_iorb:.1f} bps (corridor tightness)")
    
    if liq_state.inputs.sofr:
        t.add_row("  SOFR", f"{liq_state.inputs.sofr:.2f}% (secured repo)")
        if iorb:
            sofr_iorb = (liq_state.inputs.sofr - iorb) * 100
            t.add_row("    -> SOFR-IORB", f"{sofr_iorb:.1f} bps (repo tightness)")
        
        if liq_state.inputs.tgcr and iorb:
            tgcr_iorb = (liq_state.inputs.tgcr - iorb) * 100
            t.add_row("    -> TGCR-IORB", f"{tgcr_iorb:.1f} bps (tri-party)")
    
    # Funding status assessment
    funding_status = "ORDERLY (rates within corridor)"
    if liq_state.inputs.spread_corridor_bps and liq_state.inputs.spread_corridor_bps > 10:
        funding_status = "STRESSED (spreads widened)"
    elif liq_state.inputs.spread_corridor_bps and liq_state.inputs.spread_corridor_bps > 5:
        funding_status = "TIGHTENING (spreads rising)"
    
    t.add_row("  Funding status", funding_status)


def add_system_liquidity_section(t: Table, liq_state: FundingState) -> None:
    """Add System Liquidity section to market data table."""
    t.add_row("", "")
    t.add_row("[bold]System Liquidity[/bold]", "")
    
    # Calculate net liquidity
    rrp_b = (liq_state.inputs.on_rrp_usd_bn or 0) / 1000
    reserves_b = (liq_state.inputs.bank_reserves_usd_bn or 0) / 1000
    tga_b = (liq_state.inputs.tga_usd_bn or 0) / 1000
    net_liq_b = reserves_b + rrp_b - tga_b
    
    # Net liquidity trend
    reserves_d13w_b = (liq_state.inputs.bank_reserves_chg_13w or 0) / 1000
    rrp_d13w_b = (liq_state.inputs.on_rrp_chg_13w or 0) / 1000
    tga_d4w_b = (liq_state.inputs.tga_chg_4w or 0) / 1000
    net_liq_d1w_b = (reserves_d13w_b / 13) + (rrp_d13w_b / 13) - (tga_d4w_b / 4)
    
    net_liq_trend = "(tighter)" if net_liq_d1w_b < -1 else "(easing)" if net_liq_d1w_b > 1 else "(flat)"
    
    t.add_row("  Net Liquidity", f"${net_liq_b:.0f}B {net_liq_trend}")
    t.add_row("    (Reserves + RRP - TGA)", "")
    t.add_row("    -> Delta 1w (est)", f"${net_liq_d1w_b:+.0f}B")
    
    # ON RRP with buffer status
    rrp_status = "(depleted buffer)" if rrp_b < 50 else "(thinning)" if rrp_b < 200 else "(ample buffer)"
    t.add_row("  ON RRP", f"${rrp_b:.0f}B {rrp_status}")
    
    # Reserves with trend
    reserves_trend = "(down)" if reserves_d13w_b < -10 else "(up)" if reserves_d13w_b > 10 else "(stable)"
    t.add_row("  Reserves", f"${reserves_b:.0f}B {reserves_trend}")
    
    # TGA with liquidity impact
    tga_impact = "(adding liquidity)" if tga_d4w_b < -10 else "(draining liquidity)" if tga_d4w_b > 10 else "(neutral)"
    t.add_row("  TGA", f"${tga_b:.0f}B {tga_impact}")
    t.add_row("    -> Delta 1w (est)", f"${tga_d4w_b/4:+.0f}B")
    t.add_row("    -> Delta 4w", f"${tga_d4w_b:+.0f}B")
    
    # Fed balance sheet (QT mechanics)
    fed_assets_t = (liq_state.inputs.fed_assets_usd_bn or 0) / 1_000_000
    fed_assets_d13w_b = (liq_state.inputs.fed_assets_chg_13w or 0) / 1000
    
    # QT pace (annualized)
    qt_pace_annual_b = (fed_assets_d13w_b / 13) * 52
    
    # Peak was ~$9T in April 2022 (commonly known reference)
    fed_peak_t = 9.0
    qt_from_peak_t = fed_peak_t - fed_assets_t
    qt_pct_from_peak = (qt_from_peak_t / fed_peak_t) * 100 if fed_peak_t > 0 else 0
    
    # QT runway: if pace continues, months until reserves stress (~$2.5T threshold)
    reserves_stress_threshold_b = 2500
    reserves_cushion_b = reserves_b - reserves_stress_threshold_b
    # Combined drain rate (QT + TGA if draining)
    combined_drain_weekly = abs(fed_assets_d13w_b / 13) + (abs(tga_d4w_b / 4) if tga_d4w_b > 0 else 0)
    months_to_stress = (reserves_cushion_b / (combined_drain_weekly * 4.33)) if combined_drain_weekly > 5 else 999
    
    qt_status = f"(QT active: {qt_from_peak_t:.1f}T off peak)"
    t.add_row("  Fed balance sheet", f"${fed_assets_t:.1f}T {qt_status}")
    t.add_row("    -> Peak (Apr '22)", f"${fed_peak_t:.1f}T (-{qt_pct_from_peak:.1f}% from peak)")
    t.add_row("    -> QT pace (13w)", f"${fed_assets_d13w_b:+.0f}B (${qt_pace_annual_b:+.0f}B/yr annualized)")
    
    # Runway to stress (conditional on current pace)
    if months_to_stress < 12 and reserves_cushion_b > 0:
        stress_flag = " [approaching stress threshold]" if months_to_stress < 6 else ""
        t.add_row("    -> Reserves runway", f"~{months_to_stress:.0f} months at current drain pace{stress_flag}")
    elif reserves_cushion_b <= 0:
        t.add_row("    -> Reserves runway", "[BELOW STRESS THRESHOLD]")
    
    t.add_row("", "")
    t.add_row("  Trigger:", "If TGA rises (drain) while RRP depleted + reserves fall, watch SOFR-IORB > +10 bps or repeated spikes")


def add_fed_policy_expectations_section(c, settings, current_effr: float) -> None:
    """
    Add section showing market-implied Fed policy expectations.
    
    Shows forward rates from SOFR/Fed Funds futures and divergence from Fed guidance.
    """
    from rich.console import Console
    from rich.table import Table
    from ai_options_trader.funding.futures import fetch_fed_policy_expectations
    
    c.print("\n[bold cyan]═══ Fed Policy Expectations (Market-Implied) ═══[/bold cyan]")
    
    # Fetch expectations
    expectations = fetch_fed_policy_expectations(
        settings=settings,
        current_effr=current_effr,
        fed_dot_plot=4.50,  # Update this with actual SEP projection
    )
    
    t = Table(show_header=False, box=None, padding=(0, 1))
    t.add_column("Metric", style="dim", no_wrap=True, width=28)
    t.add_column("Value", justify="right")
    
    # Current rate (IORB is the ceiling of the Fed Funds target range)
    t.add_row("Fed Funds Target (ceiling)", f"{expectations.current_effr:.2f}%")
    t.add_row("", "")
    
    # Forward expectations
    if expectations.implied_3m is not None:
        chg_3m = expectations.change_3m_bps
        direction_3m = "cut" if chg_3m and chg_3m < -5 else "hike" if chg_3m and chg_3m > 5 else "hold"
        t.add_row("Market expects (in 3M)", f"{expectations.implied_3m:.2f}%  ({chg_3m:+.0f}bps {direction_3m})")
    
    if expectations.implied_6m is not None:
        chg_6m = expectations.change_6m_bps
        direction_6m = "cuts" if chg_6m and chg_6m < -25 else "hikes" if chg_6m and chg_6m > 25 else "hold"
        t.add_row("Market expects (in 6M)", f"{expectations.implied_6m:.2f}%  ({chg_6m:+.0f}bps {direction_6m})")
    
    if expectations.implied_12m is not None:
        chg_12m = expectations.change_12m_bps
        direction_12m = "cuts" if chg_12m and chg_12m < -50 else "hikes" if chg_12m and chg_12m > 50 else "stable"
        t.add_row("Market expects (in 12M)", f"{expectations.implied_12m:.2f}%  ({chg_12m:+.0f}bps {direction_12m})")
    
    t.add_row("", "")
    
    # Comparison to Fed guidance
    if expectations.fed_dot_plot_eoy is not None:
        t.add_row("Fed's Dot Plot (EOY 2026)", f"{expectations.fed_dot_plot_eoy:.2f}%")
        
        if expectations.divergence_from_fed_bps is not None:
            div = expectations.divergence_from_fed_bps
            if abs(div) < 10:
                div_text = "aligned"
            elif div < 0:
                div_text = f"market MORE dovish ({div:+.0f}bps)"
            else:
                div_text = f"market MORE hawkish ({div:+.0f}bps)"
            t.add_row("Divergence", div_text)
    
    t.add_row("", "")
    
    # Curve signal
    t.add_row("Curve Signal", expectations.curve_signal)
    t.add_row("Policy Bias", expectations.policy_bias)
    
    # Add note about data source
    t.add_row("", "")
    t.add_row("[dim]Note:[/dim]", "[dim]v0: Placeholder values. Will integrate actual SOFR/ZQ futures data.[/dim]")
    
    c.print(t)
