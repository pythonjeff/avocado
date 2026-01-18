"""
ML-enhanced scenario analysis CLI commands.
"""
from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from ai_options_trader.config import Settings
from ai_options_trader.utils.settings import safe_load_settings
from ai_options_trader.utils.regimes import get_current_macro_regime
from ai_options_trader.llm.scenario_ml import (
    HISTORICAL_EVENTS,
    FACTOR_SCENARIOS,
    ScenarioFactors,
    apply_historical_event,
    apply_factor_scenario,
)
from ai_options_trader.llm.scenario_forward import (
    generate_plausible_scenarios,
    ForwardScenario,
)
from ai_options_trader.llm.scenario_custom import build_custom_scenario
from ai_options_trader.llm.scenario_impact import estimate_portfolio_impact
from ai_options_trader.llm.scenario_diagnostics import diagnose_scenario_estimate

# Import v3 Monte Carlo registration
from ai_options_trader.cli_commands.monte_carlo_cmd import register_v3

# Import v0.1 Monte Carlo registration
from ai_options_trader.cli_commands.monte_carlo_v01_cmd import register_v01


def register_ml(labs_app: typer.Typer) -> None:
    # Register v3 Monte Carlo commands
    register_v3(labs_app)
    
    # Register v0.1 Monte Carlo (position-level)
    register_v01(labs_app)
    
    @labs_app.command("scenarios-custom")
    def scenarios_custom(
        name: str = typer.Option("My Custom Scenario", "--name", help="Scenario name"),
        ust_10y: float = typer.Option(None, "--10y", help="Target 10Y yield (e.g., 4.5 for 4.5%)"),
        ust_2y: float = typer.Option(None, "--2y", help="Target 2Y yield"),
        cpi: float = typer.Option(None, "--cpi", help="Target CPI YoY (e.g., 3.5 for 3.5%)"),
        unemployment: float = typer.Option(None, "--unemployment", help="Target unemployment rate"),
        vix: float = typer.Option(None, "--vix", help="Target VIX level"),
        hy_oas: float = typer.Option(None, "--hy-oas", help="Target HY OAS (bps)"),
        # Portfolio params
        net_delta: float = typer.Option(-0.2, "--net-delta"),
        vega: float = typer.Option(0.1, "--vega"),
        theta: float = typer.Option(-0.0005, "--theta"),
        has_tail_hedges: bool = typer.Option(True, "--tail-hedges/--no-tail-hedges"),
        horizon_months: int = typer.Option(3, "--horizon", help="Time horizon in months"),
        diagnose: bool = typer.Option(False, "--diagnose", help="Show detailed diagnostic breakdown"),
        start: str = typer.Option("2011-01-01", "--start"),
        refresh: bool = typer.Option(False, "--refresh"),
    ):
        """
        Test portfolio under YOUR specific macro view.
        
        Instead of predefined scenarios, specify exactly what you think will happen:
        - Where will rates go?
        - What will inflation be?
        - Will unemployment change?
        
        Examples:
            # Your scenario: 10Y to 4.5%, CPI stays 3%+, unemployment flat
            lox labs scenarios-custom --10y 4.5 --cpi 3.2 --unemployment 4.6 --name "Persistent Inflation"
            
            # Rates spike
            lox labs scenarios-custom --10y 5.0 --2y 4.8 --vix 25 --name "Rate Shock"
            
            # Goldilocks
            lox labs scenarios-custom --10y 3.5 --cpi 2.2 --vix 13 --name "Soft Landing"
        """
        settings = safe_load_settings()
        c = Console()
        
        # Validate at least one input
        if all(v is None for v in [ust_10y, ust_2y, cpi, unemployment, vix, hy_oas]):
            c.print("[red]Error: Must specify at least one target value[/red]")
            c.print("Example: --10y 4.5 --cpi 3.2 --unemployment 4.6")
            return
        
        # Get current market state
        c.print("[cyan]Fetching current market state...[/cyan]")
        
        import warnings
        warnings.filterwarnings("ignore", message=".*Optional series.*unavailable.*")
        
        regimes = get_current_macro_regime(settings, start=start, refresh=refresh)
        baseline_macro = regimes["macro_state"]
        baseline_funding = regimes["liquidity_state"]
        macro_regime = regimes["macro_regime"]
        regime_name = macro_regime.name if hasattr(macro_regime, 'name') else str(macro_regime)
        
        c.print(f"[green]✓[/green] Current regime: [bold]{regime_name}[/bold]")
        
        # Show current levels
        c.print("\n[bold]Current Levels:[/bold]")
        if baseline_macro.inputs.ust_10y:
            c.print(f"  10Y yield: {baseline_macro.inputs.ust_10y:.2f}%")
        if baseline_macro.inputs.ust_2y:
            c.print(f"  2Y yield: {baseline_macro.inputs.ust_2y:.2f}%")
        if baseline_macro.inputs.cpi_yoy:
            c.print(f"  CPI YoY: {baseline_macro.inputs.cpi_yoy:.2f}%")
        if baseline_macro.inputs.unemployment_rate:
            c.print(f"  Unemployment: {baseline_macro.inputs.unemployment_rate:.1f}%")
        if baseline_macro.inputs.vix:
            c.print(f"  VIX: {baseline_macro.inputs.vix:.1f}")
        if baseline_macro.inputs.hy_oas:
            c.print(f"  HY OAS: {baseline_macro.inputs.hy_oas:.0f} bps")
        
        # Build description
        changes = []
        if ust_10y is not None:
            changes.append(f"10Y → {ust_10y:.2f}%")
        if ust_2y is not None:
            changes.append(f"2Y → {ust_2y:.2f}%")
        if cpi is not None:
            changes.append(f"CPI → {cpi:.2f}%")
        if unemployment is not None:
            changes.append(f"Unemployment → {unemployment:.1f}%")
        if vix is not None:
            changes.append(f"VIX → {vix:.1f}")
        if hy_oas is not None:
            changes.append(f"HY OAS → {hy_oas:.0f} bps")
        
        description = ", ".join(changes)
        
        # Build custom scenario
        c.print(f"\n[cyan]Building custom scenario: {name}[/cyan]")
        scenario_macro, scenario_funding = build_custom_scenario(
            name=name,
            description=description,
            baseline_macro=baseline_macro,
            baseline_funding=baseline_funding,
            ust_10y_target=ust_10y,
            ust_2y_target=ust_2y,
            cpi_yoy_target=cpi,
            unemployment_target=unemployment,
            vix_target=vix,
            hy_oas_target=hy_oas,
        )
        
        # Estimate impact
        impact = estimate_portfolio_impact(
            baseline_macro=baseline_macro,
            baseline_funding=baseline_funding,
            scenario_macro=scenario_macro,
            scenario_funding=scenario_funding,
            portfolio_net_delta=net_delta,
            portfolio_vega=vega,
            portfolio_theta=theta,
            has_tail_hedges=has_tail_hedges,
            horizon_months=horizon_months,
        )
        
        # Display results
        c.print("\n")
        c.print(Panel(
            f"[bold]Scenario:[/bold] {name}\n"
            f"[bold]Changes:[/bold] {description}\n"
            f"[bold]Horizon:[/bold] {horizon_months} months\n"
            f"[bold]Portfolio:[/bold] Net Delta {net_delta*100:+.0f}%, Vega {vega:.2f}, Tail Hedges: {'Yes' if has_tail_hedges else 'No'}",
            title="Custom Scenario Analysis",
            border_style="cyan",
        ))
        
        # Impact summary
        pnl_pct = impact.expected_pnl_pct * 100
        pnl_color = "green" if pnl_pct > 0 else "red" if pnl_pct < 0 else "yellow"
        
        c.print(Panel(
            f"[bold {pnl_color}]Portfolio P&L: {pnl_pct:+.1f}%[/bold {pnl_color}]\n"
            f"[bold]Confidence:[/bold] {impact.confidence}\n\n"
            f"[bold]Summary:[/bold] {impact.summary}",
            title="Impact Estimate",
            border_style="yellow",
        ))
        
        # Show drivers
        if impact.key_drivers:
            c.print("\n[bold cyan]Key Drivers:[/bold cyan]")
            for driver in impact.key_drivers:
                c.print(f"  • {driver}")
        
        if impact.risks:
            c.print("\n[bold red]Risks:[/bold red]")
            for risk in impact.risks:
                c.print(f"  • {risk}")
        
        # Diagnostics if requested
        if diagnose:
            c.print("\n")
            c.print(Panel("[bold]DIAGNOSTIC MODE[/bold]", border_style="magenta"))
            
            diag = diagnose_scenario_estimate(
                baseline_macro=baseline_macro,
                baseline_funding=baseline_funding,
                scenario_macro=scenario_macro,
                scenario_funding=scenario_funding,
                portfolio_net_delta=net_delta,
                portfolio_vega=vega,
                portfolio_theta=theta,
                has_tail_hedges=has_tail_hedges,
                horizon_months=horizon_months,
            )
            
            # Show market moves detected
            c.print("\n[bold cyan]Market Moves Detected:[/bold cyan]")
            if diag.vix_change_abs is not None:
                c.print(f"  VIX: {diag.vix_change_abs:+.1f} points ({diag.vix_change_pct*100:+.1f}%)")
                if diag.spx_implied_move_pct is not None:
                    c.print(f"    → Implied SPX move: {diag.spx_implied_move_pct*100:+.1f}%")
            if diag.ust_10y_change_bps is not None:
                c.print(f"  10Y yield: {diag.ust_10y_change_bps:+.0f} bps")
            if diag.ust_2y_change_bps is not None:
                c.print(f"  2Y yield: {diag.ust_2y_change_bps:+.0f} bps")
            if diag.curve_change_bps is not None:
                c.print(f"  Curve (2s10s): {diag.curve_change_bps:+.0f} bps")
            if diag.cpi_change_pp is not None:
                c.print(f"  CPI: {diag.cpi_change_pp:+.1f}pp")
            if diag.hy_oas_change_bps is not None:
                c.print(f"  HY OAS: {diag.hy_oas_change_bps:+.0f} bps")
            
            # Show P&L breakdown
            c.print("\n[bold cyan]P&L Breakdown:[/bold cyan]")
            c.print(f"  Equity exposure: {diag.equity_pnl_pct*100:+.1f}%")
            c.print(f"  Vega: {diag.vega_pnl_pct*100:+.1f}%")
            c.print(f"  Theta: {diag.theta_pnl_pct*100:+.1f}%")
            c.print(f"  Tail hedges: {diag.tail_hedge_pnl_pct*100:+.1f}%")
            c.print(f"  Credit: {diag.credit_pnl_pct*100:+.1f}%")
            c.print(f"  [bold]Total: {diag.total_pnl_pct*100:+.1f}%[/bold]")
            
            # Show assumptions
            if diag.assumptions:
                c.print("\n[bold yellow]Model Assumptions:[/bold yellow]")
                for assumption in diag.assumptions:
                    c.print(f"  • {assumption}")
            
            # Show missing inputs
            if diag.missing_inputs:
                c.print("\n[bold yellow]Missing Inputs:[/bold yellow]")
                for missing in diag.missing_inputs:
                    c.print(f"  • {missing}")
            
            # Show warnings
            if diag.warnings:
                c.print("\n[bold red]⚠️  WARNINGS:[/bold red]")
                for warning in diag.warnings:
                    c.print(f"  {warning}")
        
        # Recommendations
        c.print("\n[bold yellow]Recommendations:[/bold yellow]")
        if pnl_pct < -5:
            c.print("  • Consider adding hedges or reducing exposure")
            c.print("  • This scenario would cause significant losses")
        elif pnl_pct < -2:
            c.print("  • Portfolio vulnerable in this scenario")
            c.print("  • Monitor leading indicators closely")
        elif pnl_pct > 10:
            c.print("  • Portfolio well-positioned for this outcome")
            c.print("  • Tail hedges performing as designed")
        elif pnl_pct > 5:
            c.print("  • Portfolio benefits from this scenario")
        else:
            c.print("  • Portfolio relatively neutral to this outcome")
            c.print("  • Theta decay is main driver")
    
    @labs_app.command("scenarios-horizon")
    def scenarios_horizon(
        net_delta: float = typer.Option(-0.2, "--net-delta"),
        vega: float = typer.Option(0.1, "--vega"),
        theta: float = typer.Option(-0.0005, "--theta"),
        has_tail_hedges: bool = typer.Option(True, "--tail-hedges/--no-tail-hedges"),
        start: str = typer.Option("2011-01-01", "--start"),
        refresh: bool = typer.Option(False, "--refresh"),
    ):
        """
        Compare portfolio outcomes across 3M and 6M horizons side-by-side.
        
        This shows how theta decay and scenario probabilities change over time.
        Useful for portfolios with options at different maturities.
        
        Examples:
            # Standard view
            lox labs scenarios-horizon
            
            # Custom portfolio
            lox labs scenarios-horizon --net-delta -0.25 --vega 0.12 --theta -0.0008
        """
        settings = safe_load_settings()
        c = Console()
        
        # Get current market state
        c.print("[cyan]Fetching current market state...[/cyan]")
        
        import warnings
        warnings.filterwarnings("ignore", message=".*Optional series.*unavailable.*")
        
        regimes = get_current_macro_regime(settings, start=start, refresh=refresh)
        baseline_macro = regimes["macro_state"]
        baseline_funding = regimes["liquidity_state"]
        macro_regime = regimes["macro_regime"]
        regime_name = macro_regime.name if hasattr(macro_regime, 'name') else str(macro_regime)
        
        c.print(f"[green]✓[/green] Current regime: [bold]{regime_name}[/bold]")
        
        # Generate scenarios for both horizons
        results_3m = []
        results_6m = []
        
        for horizon_months in [3, 6]:
            c.print(f"\n[cyan]Generating scenarios for {horizon_months}-month horizon...[/cyan]")
            
            forward_scenarios = generate_plausible_scenarios(
                current_regime=macro_regime,
                macro_state=baseline_macro,
                funding_state=baseline_funding,
                horizon_months=horizon_months,
            )
            
            c.print(f"[green]✓[/green] Generated {len(forward_scenarios)} plausible scenarios")
            
            results = []
            for fwd_scenario in forward_scenarios:
                # Apply factor scenario
                scenario_macro, scenario_funding = apply_factor_scenario(
                    fwd_scenario.factors, baseline_macro, baseline_funding
                )
                
                # Estimate impact
                impact = estimate_portfolio_impact(
                    baseline_macro=baseline_macro,
                    baseline_funding=baseline_funding,
                    scenario_macro=scenario_macro,
                    scenario_funding=scenario_funding,
                    portfolio_net_delta=net_delta,
                    portfolio_vega=vega,
                    portfolio_theta=theta,
                    has_tail_hedges=has_tail_hedges,
                    horizon_months=horizon_months,
                )
                impact.scenario_id = fwd_scenario.id
                impact.scenario_name = fwd_scenario.name
                
                results.append((fwd_scenario, impact))
            
            # Sort by probability
            results.sort(key=lambda x: x[0].probability, reverse=True)
            
            if horizon_months == 3:
                results_3m = results
            else:
                results_6m = results
        
        # Display comparison
        c.print("\n")
        c.print(Panel(
            f"[bold]Current Regime:[/bold] {regime_name}\n"
            f"[bold]Portfolio:[/bold] Net Delta {net_delta*100:+.0f}%, Vega {vega:.2f}, Theta {theta*100:.2f} bps/day, Tail Hedges: {'Yes' if has_tail_hedges else 'No'}",
            title="Multi-Horizon Scenario Analysis",
            border_style="cyan",
        ))
        
        # Build comparison table
        table = Table(show_header=True, header_style="bold cyan", box=None, padding=(0, 1))
        table.add_column("Scenario", style="bold", width=30)
        table.add_column("3M Prob", justify="right", width=8)
        table.add_column("3M P&L", justify="right", width=10)
        table.add_column("6M Prob", justify="right", width=8)
        table.add_column("6M P&L", justify="right", width=10)
        table.add_column("Key Difference", width=35)
        
        # Match scenarios by ID
        scenario_ids = set([s[0].id for s in results_3m]) | set([s[0].id for s in results_6m])
        
        for sid in sorted(scenario_ids, key=lambda x: (
            next((s[0].probability for s in results_3m if s[0].id == x), 0),
            next((s[0].probability for s in results_6m if s[0].id == x), 0)
        ), reverse=True):
            
            scenario_3m = next((s for s in results_3m if s[0].id == sid), None)
            scenario_6m = next((s for s in results_6m if s[0].id == sid), None)
            
            if not scenario_3m and not scenario_6m:
                continue
            
            name = scenario_3m[0].name if scenario_3m else scenario_6m[0].name
            
            # 3M data
            prob_3m = f"{scenario_3m[0].probability*100:.0f}%" if scenario_3m else "—"
            pnl_3m_val = scenario_3m[1].expected_pnl_pct if scenario_3m else None
            pnl_3m = f"{pnl_3m_val*100:+.1f}%" if pnl_3m_val is not None else "—"
            pnl_3m_color = "green" if pnl_3m_val and pnl_3m_val > 0 else "red" if pnl_3m_val and pnl_3m_val < 0 else "white"
            
            # 6M data
            prob_6m = f"{scenario_6m[0].probability*100:.0f}%" if scenario_6m else "—"
            pnl_6m_val = scenario_6m[1].expected_pnl_pct if scenario_6m else None
            pnl_6m = f"{pnl_6m_val*100:+.1f}%" if pnl_6m_val is not None else "—"
            pnl_6m_color = "green" if pnl_6m_val and pnl_6m_val > 0 else "red" if pnl_6m_val and pnl_6m_val < 0 else "white"
            
            # Key difference
            if pnl_3m_val is not None and pnl_6m_val is not None:
                diff = (pnl_6m_val - pnl_3m_val) * 100
                if abs(diff) < 0.5:
                    diff_desc = "Similar outcomes"
                elif diff > 0:
                    diff_desc = f"+{diff:.1f}pp worse in 6M (more theta)"
                else:
                    diff_desc = f"{diff:.1f}pp better in 6M"
            else:
                diff_desc = "—"
            
            table.add_row(
                name,
                prob_3m,
                f"[{pnl_3m_color}]{pnl_3m}[/{pnl_3m_color}]",
                prob_6m,
                f"[{pnl_6m_color}]{pnl_6m}[/{pnl_6m_color}]",
                diff_desc,
            )
        
        c.print(table)
        
        # Summary stats
        weighted_pnl_3m = sum(s[0].probability * s[1].expected_pnl_pct for s in results_3m)
        weighted_pnl_6m = sum(s[0].probability * s[1].expected_pnl_pct for s in results_6m)
        
        c.print(Panel(
            f"[bold]Expected P&L (probability-weighted):[/bold]\n"
            f"  3 months: {weighted_pnl_3m*100:+.1f}%\n"
            f"  6 months: {weighted_pnl_6m*100:+.1f}%\n"
            f"  Difference: {(weighted_pnl_6m - weighted_pnl_3m)*100:+.1f}pp\n\n"
            f"[bold]Theta impact:[/bold] ~{theta*90*100:.1f} bps over 3M, ~{theta*180*100:.1f} bps over 6M\n\n"
            f"[cyan]Interpretation:[/cyan] {'Theta decay is significant - consider rolling positions' if theta * 180 < -0.05 else 'Theta manageable - current structure sustainable'}",
            title="Horizon Comparison Summary",
            border_style="yellow",
        ))
    
    @labs_app.command("scenarios-forward")
    def scenarios_forward(
        horizon_months: int = typer.Option(
            3,
            "--horizon",
            help="Forward horizon in months (3, 6, or 12)",
        ),
        net_delta: float = typer.Option(-0.2, "--net-delta"),
        vega: float = typer.Option(0.1, "--vega"),
        has_tail_hedges: bool = typer.Option(True, "--tail-hedges/--no-tail-hedges"),
        show_catalysts: bool = typer.Option(
            False,
            "--show-catalysts",
            help="Show catalysts and early warning signs for each scenario",
        ),
        start: str = typer.Option("2011-01-01", "--start"),
        refresh: bool = typer.Option(False, "--refresh"),
    ):
        """
        Stress test portfolio using PLAUSIBLE forward-looking scenarios.
        
        This generates realistic scenarios for the next 3-6 months based on:
        - Current regime (different risks in different regimes)
        - Current market levels (constrains plausible moves)
        - Known catalysts on the horizon
        - Conditional probabilities
        
        Examples:
            # Next 3 months (default)
            lox labs scenarios-forward
            
            # Next 6 months
            lox labs scenarios-forward --horizon 6
            
            # Show catalysts and early warning signs
            lox labs scenarios-forward --show-catalysts
        """
        settings = safe_load_settings()
        c = Console()
        
        # Get current market state
        c.print("[cyan]Fetching current market state...[/cyan]")
        
        # Suppress optional series warnings
        import warnings
        warnings.filterwarnings("ignore", message=".*Optional series.*unavailable.*")
        
        regimes = get_current_macro_regime(settings, start=start, refresh=refresh)
        baseline_macro = regimes["macro_state"]
        baseline_funding = regimes["liquidity_state"]
        macro_regime = regimes["macro_regime"]
        
        c.print(f"[green]✓[/green] Current regime: [bold]{macro_regime.name if hasattr(macro_regime, 'name') else macro_regime}[/bold]")
        c.print(f"[green]✓[/green] Forward horizon: [bold]{horizon_months} months[/bold]")
        
        # Generate plausible scenarios
        c.print(f"\n[cyan]Generating plausible scenarios for {horizon_months}-month horizon...[/cyan]")
        
        # Get clean regime name
        regime_name = macro_regime.name if hasattr(macro_regime, 'name') else str(macro_regime)
        
        forward_scenarios = generate_plausible_scenarios(
            current_regime=macro_regime,
            macro_state=baseline_macro,
            funding_state=baseline_funding,
            horizon_months=horizon_months,
        )
        
        c.print(f"[green]✓[/green] Generated {len(forward_scenarios)} plausible scenarios")
        
        # Run scenarios
        results = []
        for fwd_scenario in forward_scenarios:
            # Apply factor scenario
            scenario_macro, scenario_funding = apply_factor_scenario(
                fwd_scenario.factors, baseline_macro, baseline_funding
            )
            
            # Estimate impact
            impact = estimate_portfolio_impact(
                baseline_macro=baseline_macro,
                baseline_funding=baseline_funding,
                scenario_macro=scenario_macro,
                scenario_funding=scenario_funding,
                portfolio_net_delta=net_delta,
                portfolio_vega=vega,
                portfolio_theta=-0.0005,
                has_tail_hedges=has_tail_hedges,
                horizon_months=horizon_months,  # Pass horizon to impact calculator
            )
            impact.scenario_id = fwd_scenario.id
            impact.scenario_name = fwd_scenario.name
            
            results.append((fwd_scenario, impact))
        
        # Sort by probability (most likely first)
        results.sort(key=lambda x: x[0].probability, reverse=True)
        
        # Display results
        c.print("\n")
        c.print(Panel(
            f"[bold]Current Regime:[/bold] {regime_name}\n"
            f"[bold]Forward Horizon:[/bold] {horizon_months} months\n"
            f"[bold]Portfolio:[/bold] Net Delta {net_delta*100:+.0f}%, Vega {vega:.2f}, Tail Hedges: {'Yes' if has_tail_hedges else 'No'}",
            title=f"Forward-Looking Scenario Analysis ({horizon_months}M)",
            border_style="cyan",
        ))
        
        # Build comparison table
        table = Table(show_header=True, header_style="bold cyan", box=None, padding=(0, 1))
        table.add_column("Scenario", style="bold", width=30)
        table.add_column("Prob", justify="right", width=8)
        table.add_column("Portfolio P&L", justify="right", width=15)
        table.add_column("Confidence", width=10)
        table.add_column("Description", width=40)
        
        for fwd_scenario, impact in results:
            # Color code probability
            prob = fwd_scenario.probability * 100
            if prob > 25:
                prob_color = "bold yellow"
            elif prob > 15:
                prob_color = "yellow"
            elif prob < 5:
                prob_color = "dim"
            else:
                prob_color = "white"
            
            # Color code P&L
            pnl_pct = impact.expected_pnl_pct * 100
            if pnl_pct > 5:
                pnl_color = "bold green"
            elif pnl_pct > 1:
                pnl_color = "green"
            elif pnl_pct < -5:
                pnl_color = "bold red"
            elif pnl_pct < -1:
                pnl_color = "red"
            else:
                pnl_color = "white"
            
            conf_color = {"high": "green", "medium": "yellow", "low": "red"}.get(impact.confidence, "white")
            
            table.add_row(
                fwd_scenario.name,
                f"[{prob_color}]{prob:.0f}%[/{prob_color}]",
                f"[{pnl_color}]{pnl_pct:+.1f}%[/{pnl_color}]",
                f"[{conf_color}]{impact.confidence}[/{conf_color}]",
                fwd_scenario.description,
            )
        
        c.print(table)
        
        # Calculate probability-weighted P&L
        weighted_pnl = sum(
            fwd.probability * impact.expected_pnl_pct
            for fwd, impact in results
        )
        
        # Best/worst scenarios
        sorted_by_pnl = sorted(results, key=lambda x: x[1].expected_pnl_pct, reverse=True)
        best = sorted_by_pnl[0]
        worst = sorted_by_pnl[-1]
        
        # Most likely scenario
        most_likely = results[0]  # Already sorted by probability
        
        c.print(Panel(
            f"[bold]Probability-Weighted Expected P&L:[/bold] {weighted_pnl*100:+.1f}%\n\n"
            f"[bold green]Best scenario:[/bold green] {best[0].name} ({best[1].expected_pnl_pct*100:+.1f}%, {best[0].probability*100:.0f}% prob)\n"
            f"[bold red]Worst scenario:[/bold red] {worst[0].name} ({worst[1].expected_pnl_pct*100:+.1f}%, {worst[0].probability*100:.0f}% prob)\n"
            f"[bold yellow]Most likely:[/bold yellow] {most_likely[0].name} ({most_likely[1].expected_pnl_pct*100:+.1f}%, {most_likely[0].probability*100:.0f}% prob)\n\n"
            f"[cyan]Range:[/cyan] {(best[1].expected_pnl_pct - worst[1].expected_pnl_pct)*100:.1f}% spread",
            title="Risk Summary",
            border_style="yellow",
        ))
        
        # Show catalysts if requested
        if show_catalysts:
            c.print("\n[bold cyan]Scenario Details:[/bold cyan]\n")
            for fwd_scenario, impact in results:
                c.print(f"[bold yellow]{fwd_scenario.name}[/bold yellow] ({fwd_scenario.probability*100:.0f}% probability)")
                c.print(f"  [dim]{fwd_scenario.description}[/dim]")
                
                if fwd_scenario.catalysts:
                    c.print("  [cyan]Catalysts:[/cyan]")
                    for catalyst in fwd_scenario.catalysts:
                        c.print(f"    • {catalyst}")
                
                if fwd_scenario.early_warning_signs:
                    c.print("  [yellow]Early warning signs:[/yellow]")
                    for sign in fwd_scenario.early_warning_signs:
                        c.print(f"    • {sign}")
                
                c.print()
    
    @labs_app.command("scenarios-historical")
    def scenarios_historical(
        event_ids: str = typer.Option(
            "gfc_2008,covid_crash_2020,volmageddon_2018,taper_tantrum_2022,svb_2023",
            "--events",
            help="Comma-separated list of historical event IDs",
        ),
        severity: float = typer.Option(
            1.0,
            "--severity",
            help="Scale factor for historical moves (1.0 = actual, 0.5 = half, 2.0 = double)",
        ),
        net_delta: float = typer.Option(-0.2, "--net-delta"),
        vega: float = typer.Option(0.1, "--vega"),
        theta: float = typer.Option(-0.0005, "--theta"),
        has_tail_hedges: bool = typer.Option(True, "--tail-hedges/--no-tail-hedges"),
        list_events: bool = typer.Option(False, "--list", help="List all historical events"),
        start: str = typer.Option("2011-01-01", "--start"),
        refresh: bool = typer.Option(False, "--refresh"),
    ):
        """
        Stress test portfolio using REAL historical events.
        
        Instead of synthetic scenarios, this uses actual observed market moves
        from past crises (2008 GFC, 2020 COVID, etc.).
        
        Examples:
            # List all historical events
            lox labs scenarios-historical --list
            
            # Run all major crises
            lox labs scenarios-historical
            
            # Run only 2008 + COVID
            lox labs scenarios-historical --events "gfc_2008,covid_crash_2020"
            
            # Run at half severity
            lox labs scenarios-historical --severity 0.5
            
            # Run at double severity (tail scenario)
            lox labs scenarios-historical --severity 2.0
        """
        settings = safe_load_settings()
        c = Console()
        
        if list_events:
            c.print(Panel("[bold cyan]Historical Events Library[/bold cyan]", expand=False))
            c.print()
            
            for event_id, event in HISTORICAL_EVENTS.items():
                c.print(f"[bold yellow]{event_id}[/bold yellow]")
                c.print(f"  Name: {event.name}")
                c.print(f"  Date: {event.date_range}")
                c.print(f"  Description: {event.description}")
                c.print(f"  Observed moves:")
                if event.vix_change_pct:
                    c.print(f"    VIX: {event.vix_change_pct*100:+.0f}%")
                if event.spy_change_pct:
                    c.print(f"    SPY: {event.spy_change_pct*100:+.0f}%")
                if event.ust_10y_change_bps:
                    c.print(f"    10Y yield: {event.ust_10y_change_bps:+.0f} bps")
                if event.hy_oas_change_bps:
                    c.print(f"    HY OAS: {event.hy_oas_change_bps:+.0f} bps")
                c.print()
            
            return
        
        # Get current market state
        c.print("[cyan]Fetching current market state...[/cyan]")
        regimes = get_current_macro_regime(settings, start=start, refresh=refresh)
        baseline_macro = regimes["macro_state"]
        baseline_funding = regimes["liquidity_state"]
        macro_regime = regimes["macro_regime"]
        
        c.print(f"[green]✓[/green] Current regime: [bold]{macro_regime}[/bold]")
        c.print(f"[green]✓[/green] Severity scale: [bold]{severity}x[/bold] historical")
        
        # Run scenarios
        event_ids_list = [e.strip() for e in event_ids.split(",")]
        c.print(f"\n[cyan]Running {len(event_ids_list)} historical event(s)...[/cyan]")
        
        results = []
        for event_id in event_ids_list:
            if event_id not in HISTORICAL_EVENTS:
                c.print(f"[yellow]Warning: Unknown event '{event_id}', skipping[/yellow]")
                continue
            
            event = HISTORICAL_EVENTS[event_id]
            
            # Apply historical event
            scenario_macro, scenario_funding = apply_historical_event(
                event_id, baseline_macro, baseline_funding, severity=severity
            )
            
            # Estimate impact
            impact = estimate_portfolio_impact(
                baseline_macro=baseline_macro,
                baseline_funding=baseline_funding,
                scenario_macro=scenario_macro,
                scenario_funding=scenario_funding,
                portfolio_net_delta=net_delta,
                portfolio_vega=vega,
                portfolio_theta=theta,
                has_tail_hedges=has_tail_hedges,
            )
            impact.scenario_id = event_id
            impact.scenario_name = event.name
            
            results.append((event, impact))
        
        # Display results
        c.print("\n")
        c.print(Panel(
            f"[bold]Baseline Regime:[/bold] {macro_regime}\n"
            f"[bold]Portfolio:[/bold] Net Delta {net_delta*100:+.0f}%, Vega {vega:.2f}, Tail Hedges: {'Yes' if has_tail_hedges else 'No'}\n"
            f"[bold]Severity:[/bold] {severity}x historical moves",
            title="Historical Scenario Analysis",
            border_style="cyan",
        ))
        
        # Build comparison table
        table = Table(show_header=True, header_style="bold cyan", box=None, padding=(0, 1))
        table.add_column("Historical Event", style="bold", width=35)
        table.add_column("Date", width=20)
        table.add_column("Portfolio P&L", justify="right", width=15)
        table.add_column("Confidence", width=10)
        
        for event, impact in results:
            pnl_pct = impact.expected_pnl_pct * 100
            if pnl_pct > 5:
                pnl_color = "bold green"
            elif pnl_pct > 1:
                pnl_color = "green"
            elif pnl_pct < -5:
                pnl_color = "bold red"
            elif pnl_pct < -1:
                pnl_color = "red"
            else:
                pnl_color = "white"
            
            conf_color = {"high": "green", "medium": "yellow", "low": "red"}.get(impact.confidence, "white")
            
            table.add_row(
                event.name,
                event.date_range.split(" to ")[0],  # Just start date
                f"[{pnl_color}]{pnl_pct:+.1f}%[/{pnl_color}]",
                f"[{conf_color}]{impact.confidence}[/{conf_color}]",
            )
        
        c.print(table)
        
        # Risk summary
        sorted_results = sorted(results, key=lambda x: x[1].expected_pnl_pct, reverse=True)
        best = sorted_results[0]
        worst = sorted_results[-1]
        
        c.print(Panel(
            f"[bold green]Best historical scenario:[/bold green] {best[0].name} ({best[1].expected_pnl_pct*100:+.1f}%)\n"
            f"[bold red]Worst historical scenario:[/bold red] {worst[0].name} ({worst[1].expected_pnl_pct*100:+.1f}%)\n"
            f"[bold]Range:[/bold] {(best[1].expected_pnl_pct - worst[1].expected_pnl_pct)*100:.1f}% spread\n\n"
            f"[cyan]Historical context:[/cyan] These are ACTUAL market moves from past crises.\n"
            f"Severity {severity}x means we're modeling {severity*100:.0f}% of the historical move.",
            title="Historical Risk Summary",
            border_style="yellow",
        ))
    
    @labs_app.command("scenarios-factors")
    def scenarios_factors(
        risk_appetite: float = typer.Option(
            -0.8,
            "--risk-appetite",
            help="Risk appetite: -1 (extreme risk-off) to +1 (extreme risk-on)",
        ),
        growth_shock: float = typer.Option(
            -0.3,
            "--growth",
            help="Growth shock: -1 (severe contraction) to +1 (strong growth)",
        ),
        inflation_shock: float = typer.Option(
            0.0,
            "--inflation",
            help="Inflation shock: -1 (deflation) to +1 (high inflation)",
        ),
        liquidity_stress: float = typer.Option(
            0.5,
            "--liquidity",
            help="Liquidity stress: -1 (abundant) to +1 (crisis)",
        ),
        policy_shock: float = typer.Option(
            0.0,
            "--policy",
            help="Policy shock: -1 (dovish surprise) to +1 (hawkish surprise)",
        ),
        net_delta: float = typer.Option(-0.2, "--net-delta"),
        vega: float = typer.Option(0.1, "--vega"),
        has_tail_hedges: bool = typer.Option(True, "--tail-hedges/--no-tail-hedges"),
        list_presets: bool = typer.Option(False, "--list", help="List preset factor scenarios"),
        preset: str = typer.Option(None, "--preset", help="Use a preset factor scenario"),
        start: str = typer.Option("2011-01-01", "--start"),
        refresh: bool = typer.Option(False, "--refresh"),
    ):
        """
        Stress test portfolio using HIGH-LEVEL FACTORS instead of individual variables.
        
        This is easier than specifying "VIX up X%, 10Y yield +Y bps, HY OAS +Z bps".
        Instead, you specify:
        - Risk appetite (risk-on vs risk-off)
        - Growth expectations
        - Inflation expectations
        - Liquidity conditions
        - Policy stance
        
        The model then maps these factors to specific market moves using learned relationships.
        
        Examples:
            # List preset scenarios
            lox labs scenarios-factors --list
            
            # Extreme risk-off + liquidity stress
            lox labs scenarios-factors --risk-appetite -1.0 --liquidity 0.8
            
            # Stagflation (high inflation + weak growth)
            lox labs scenarios-factors --inflation 0.9 --growth -0.7 --policy 0.6
            
            # Use a preset
            lox labs scenarios-factors --preset "extreme_risk_off"
        """
        settings = safe_load_settings()
        c = Console()
        
        if list_presets:
            c.print(Panel("[bold cyan]Preset Factor Scenarios[/bold cyan]", expand=False))
            c.print()
            
            for preset_id, factors in FACTOR_SCENARIOS.items():
                c.print(f"[bold yellow]{preset_id}[/bold yellow]")
                c.print(f"  Name: {factors.name}")
                c.print(f"  Factors:")
                c.print(f"    Risk appetite: {factors.risk_appetite:+.1f}")
                c.print(f"    Growth: {factors.growth_shock:+.1f}")
                c.print(f"    Inflation: {factors.inflation_shock:+.1f}")
                c.print(f"    Liquidity: {factors.liquidity_stress:+.1f}")
                c.print(f"    Policy: {factors.policy_shock:+.1f}")
                c.print()
            
            return
        
        # Get current market state
        c.print("[cyan]Fetching current market state...[/cyan]")
        regimes = get_current_macro_regime(settings, start=start, refresh=refresh)
        baseline_macro = regimes["macro_state"]
        baseline_funding = regimes["liquidity_state"]
        macro_regime = regimes["macro_regime"]
        
        c.print(f"[green]✓[/green] Current regime: [bold]{macro_regime}[/bold]")
        
        # Use preset or custom factors
        if preset:
            if preset not in FACTOR_SCENARIOS:
                c.print(f"[red]Error: Unknown preset '{preset}'[/red]")
                c.print("Run --list to see available presets")
                return
            factors = FACTOR_SCENARIOS[preset]
            c.print(f"[green]✓[/green] Using preset: [bold]{preset}[/bold]")
        else:
            factors = ScenarioFactors(
                risk_appetite=risk_appetite,
                growth_shock=growth_shock,
                inflation_shock=inflation_shock,
                liquidity_stress=liquidity_stress,
                policy_shock=policy_shock,
            )
            c.print(f"[green]✓[/green] Custom factors: [bold]{factors.name}[/bold]")
        
        # Apply factor scenario
        scenario_macro, scenario_funding = apply_factor_scenario(
            factors, baseline_macro, baseline_funding
        )
        
        # Estimate impact
        impact = estimate_portfolio_impact(
            baseline_macro=baseline_macro,
            baseline_funding=baseline_funding,
            scenario_macro=scenario_macro,
            scenario_funding=scenario_funding,
            portfolio_net_delta=net_delta,
            portfolio_vega=vega,
            portfolio_theta=-0.0005,
            has_tail_hedges=has_tail_hedges,
        )
        
        # Display results
        c.print("\n")
        c.print(Panel(
            f"[bold]Baseline Regime:[/bold] {macro_regime}\n"
            f"[bold]Scenario:[/bold] {factors.name}\n"
            f"[bold]Portfolio:[/bold] Net Delta {net_delta*100:+.0f}%, Vega {vega:.2f}, Tail Hedges: {'Yes' if has_tail_hedges else 'No'}",
            title="Factor-Based Scenario Analysis",
            border_style="cyan",
        ))
        
        # Show factor inputs
        factor_table = Table(show_header=False, box=None, padding=(0, 2))
        factor_table.add_row("[bold]Risk Appetite[/bold]", f"{factors.risk_appetite:+.2f}", _get_factor_desc(factors.risk_appetite, "risk"))
        factor_table.add_row("[bold]Growth[/bold]", f"{factors.growth_shock:+.2f}", _get_factor_desc(factors.growth_shock, "growth"))
        factor_table.add_row("[bold]Inflation[/bold]", f"{factors.inflation_shock:+.2f}", _get_factor_desc(factors.inflation_shock, "inflation"))
        factor_table.add_row("[bold]Liquidity[/bold]", f"{factors.liquidity_stress:+.2f}", _get_factor_desc(factors.liquidity_stress, "liquidity"))
        factor_table.add_row("[bold]Policy[/bold]", f"{factors.policy_shock:+.2f}", _get_factor_desc(factors.policy_shock, "policy"))
        
        c.print(Panel(factor_table, title="Scenario Factors", border_style="blue"))
        
        # Show estimated P&L
        pnl_pct = impact.expected_pnl_pct * 100
        pnl_color = "green" if pnl_pct > 0 else "red"
        
        c.print(Panel(
            f"[bold {pnl_color}]Portfolio P&L: {pnl_pct:+.1f}%[/bold {pnl_color}]\n"
            f"[bold]Confidence:[/bold] {impact.confidence}\n\n"
            f"[bold]Summary:[/bold] {impact.summary}",
            title="Impact Estimate",
            border_style="yellow",
        ))
        
        # Show drivers
        if impact.key_drivers:
            c.print("\n[bold cyan]Key Drivers:[/bold cyan]")
            for driver in impact.key_drivers:
                c.print(f"  • {driver}")
        
        if impact.risks:
            c.print("\n[bold red]Risks:[/bold red]")
            for risk in impact.risks:
                c.print(f"  • {risk}")


def _get_factor_desc(value: float, factor_type: str) -> str:
    """Get human-readable description for a factor value."""
    if factor_type == "risk":
        if value < -0.7:
            return "(extreme risk-off)"
        elif value < -0.3:
            return "(risk-off)"
        elif value > 0.7:
            return "(extreme risk-on)"
        elif value > 0.3:
            return "(risk-on)"
        else:
            return "(neutral)"
    elif factor_type == "growth":
        if value < -0.7:
            return "(severe contraction)"
        elif value < -0.3:
            return "(weak growth)"
        elif value > 0.7:
            return "(strong expansion)"
        elif value > 0.3:
            return "(solid growth)"
        else:
            return "(stable)"
    elif factor_type == "inflation":
        if value < -0.5:
            return "(deflation risk)"
        elif value > 0.7:
            return "(high inflation)"
        elif value > 0.3:
            return "(elevated)"
        else:
            return "(contained)"
    elif factor_type == "liquidity":
        if value > 0.7:
            return "(liquidity crisis)"
        elif value > 0.3:
            return "(tightening)"
        elif value < -0.3:
            return "(abundant)"
        else:
            return "(orderly)"
    elif factor_type == "policy":
        if value > 0.7:
            return "(very hawkish)"
        elif value > 0.3:
            return "(hawkish)"
        elif value < -0.7:
            return "(very dovish)"
        elif value < -0.3:
            return "(dovish)"
        else:
            return "(neutral)"
    return ""
