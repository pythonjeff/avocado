"""Fed funds outlook command."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ai_options_trader.utils.settings import safe_load_settings
from ai_options_trader.utils.regimes import get_current_macro_regime
from ai_options_trader.cli_commands.shared.fedfunds_display import (
    build_regime_table,
    build_portfolio_relevance_table,
    add_growth_inflation_section,
    add_policy_conditions_section,
    add_fed_policy_expectations_section,
    add_overnight_funding_section,
    add_system_liquidity_section,
)
from ai_options_trader.cli_commands.shared.fedfunds_display_extended import (
    add_credit_stress_section,
    add_volatility_section,
    add_dollar_commodities_section,
    add_housing_section,
)


def register(monetary_app: typer.Typer) -> None:
    @monetary_app.command("fedfunds-outlook")
    def fedfunds_outlook(
        start: str = typer.Option("2011-01-01", "--start", help="Start date YYYY-MM-DD"),
        refresh: bool = typer.Option(False, "--refresh", help="Force refresh FRED downloads"),
        llm: bool = typer.Option(True, "--llm/--no-llm", help="Enable LLM outlook"),
        llm_model: str = typer.Option("", "--llm-model", help="Override OPENAI_MODEL (optional)"),
        llm_temperature: float = typer.Option(0.2, "--llm-temperature", help="LLM temperature (0..2)"),
    ):
        """
        Fed funds outlook: current regime + LLM synthesis of likely path.
        """
        settings = safe_load_settings()
        if not settings:
            raise typer.BadParameter("Settings unavailable (missing env/.env).")
        c = Console()

        # Get current regimes
        regimes = get_current_macro_regime(settings, start=start, refresh=refresh)
        macro_state = regimes["macro_state"]
        macro_regime = regimes["macro_regime"]
        liq_state = regimes["liquidity_state"]

        # === REGIME CLASSIFICATION ===
        
        # Fed Policy Stance
        real_yield = macro_state.inputs.real_yield_proxy_10y
        fed_stance = "NEUTRAL"
        fed_desc = "Policy is neither clearly restrictive nor accommodative"
        if real_yield and real_yield > 1.5:
            fed_stance = "RESTRICTIVE"
            fed_desc = "Real yields elevated — policy is weighing on growth"
        elif real_yield and real_yield < 0.5:
            fed_stance = "ACCOMMODATIVE"
            fed_desc = "Real yields low — policy is supportive"
        
        # Liquidity Regime (buffer status vs funding stress)
        rrp_val = liq_state.inputs.on_rrp_usd_bn / 1000.0 if liq_state.inputs.on_rrp_usd_bn else None
        reserves_val = liq_state.inputs.bank_reserves_usd_bn / 1000.0 if liq_state.inputs.bank_reserves_usd_bn else None
        sofr_iorb_spread = liq_state.inputs.spread_corridor_bps or 0
        
        # Buffer status
        if rrp_val and rrp_val < 50:
            buffer_status = "RRP depleted — reserves absorb drains"
        elif rrp_val and rrp_val < 200:
            buffer_status = "RRP buffer thinning"
        else:
            buffer_status = "RRP buffer ample"
        
        # Liquidity status (conditional on funding stress)
        if sofr_iorb_spread > 10:
            liq_status = "STRESSED"
            liq_desc = "SOFR-IORB widened/spiked — actual market stress"
        elif rrp_val and rrp_val < 50 and reserves_val and reserves_val < 2000:
            liq_status = "FRAGILE"
            liq_desc = "RRP buffer depleted; reserves absorbing drains. Funding still orderly (SOFR-IORB near 0)"
        elif rrp_val and rrp_val < 200:
            liq_status = "TIGHTENING"
            liq_desc = "Buffers draining but rates stable"
        else:
            liq_status = "ORDERLY"
            liq_desc = "Funding still orderly (SOFR-IORB near 0)"

        # === DISPLAY ===
        
        # Regime Dashboard
        regime_table = build_regime_table(
            macro_regime=macro_regime,
            fed_stance=fed_stance,
            fed_desc=fed_desc,
            liq_status=liq_status,
            liq_desc=liq_desc,
            buffer_status=buffer_status,
        )
        c.print(Panel(regime_table, title="Regime Dashboard", border_style="cyan"))

        # Portfolio Relevance
        portfolio_table = build_portfolio_relevance_table()
        c.print(Panel(portfolio_table, title="Portfolio Relevance", border_style="yellow"))

        # Market Data
        data_table = Table(show_header=False, box=None, padding=(0, 1))
        data_table.add_column("Metric", style="bold blue", no_wrap=True, width=20)
        data_table.add_column("Value")
        
        add_growth_inflation_section(data_table, macro_state)
        add_policy_conditions_section(data_table, macro_state)
        add_credit_stress_section(data_table, macro_state)
        add_volatility_section(data_table, macro_state)
        add_overnight_funding_section(data_table, liq_state)
        add_system_liquidity_section(data_table, liq_state)
        add_dollar_commodities_section(data_table, macro_state)
        add_housing_section(data_table, macro_state)
        
        c.print(Panel(data_table, title="Market Data", border_style="blue"))
        
        # === FED POLICY EXPECTATIONS (from futures) ===
        
        # Get current EFFR from funding state
        # Use IORB (Interest on Reserve Balances) as the Fed's target ceiling
        current_effr = (liq_state.inputs.iorb or 5.50)  # IORB is the ceiling of Fed Funds corridor
        add_fed_policy_expectations_section(c, settings, current_effr)

        # === LLM OUTLOOK ===
        
        if llm:
            try:
                from ai_options_trader.llm.outlooks.monetary_outlook import llm_fedfunds_outlook

                outlook = llm_fedfunds_outlook(
                    settings=settings,
                    regimes=regimes,
                    model=llm_model.strip() or None,
                    temperature=float(llm_temperature),
                )
                c.print("\n")  # Add spacing
                c.print(Panel(
                    outlook, 
                    title="[bold cyan]Institutional Liquidity Forecast[/bold cyan]", 
                    subtitle="[dim]Conditional 1-3 Month Outlook[/dim]",
                    border_style="cyan", 
                    padding=(1, 2)
                ))
            except Exception as e:
                c.print(Panel(
                    f"[yellow]LLM unavailable:[/yellow] {e}", 
                    title="Institutional Liquidity Forecast", 
                    border_style="yellow"
                ))
