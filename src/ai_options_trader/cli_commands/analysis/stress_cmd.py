"""
Stress Test CLI Command.

Provides portfolio stress testing across predefined and custom scenarios.
"""
import os
import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from ai_options_trader.portfolio.positions import create_example_portfolio
from ai_options_trader.portfolio.alpaca_adapter import alpaca_to_portfolio
from ai_options_trader.portfolio.stress_test import (
    StressScenario,
    StressParameters,
    run_stress_test,
    run_all_stress_tests,
    calculate_pnl_attribution,
)
from ai_options_trader.utils.settings import safe_load_settings


def register_stress(labs_app: typer.Typer) -> None:
    @labs_app.command("stress")
    def stress_test(
        scenario: str = typer.Option(
            "all",
            "--scenario", "-s",
            help="Scenario: all, equity_crash, rates_shock_up, rates_shock_down, credit_event, flash_crash, stagflation, vol_crush",
        ),
        spx: float = typer.Option(None, "--spx", help="Custom SPX change % (e.g., -0.10 for -10%)"),
        vix: float = typer.Option(None, "--vix", help="Custom VIX change pts (e.g., 10 for +10)"),
        rates: float = typer.Option(None, "--rates", help="Custom 10Y change bps (e.g., 50)"),
        hy: float = typer.Option(None, "--hy", help="Custom HY OAS change bps (e.g., 100)"),
        live: bool = typer.Option(True, "--live/--paper", help="Use live account (default)"),
        example: bool = typer.Option(False, "--example", help="Use example portfolio"),
        json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
    ):
        """
        Run stress tests on the portfolio.
        
        Examples:
            lox labs stress                        # All predefined scenarios
            lox labs stress -s equity_crash        # Single scenario
            lox labs stress --spx -0.10 --vix 15   # Custom scenario
        """
        c = Console()
        
        # Load portfolio
        if example:
            portfolio = create_example_portfolio()
            account_type = "EXAMPLE"
        else:
            if live:
                os.environ["ALPACA_PAPER"] = "false"
                account_type = "🟢 LIVE"
            else:
                os.environ["ALPACA_PAPER"] = "true"
                account_type = "🟡 PAPER"
            
            settings = safe_load_settings()
            portfolio = alpaca_to_portfolio(settings)
            
            if len(portfolio.positions) == 0:
                c.print("[yellow]⚠️  No positions found. Using example portfolio.[/yellow]")
                portfolio = create_example_portfolio()
                account_type = "EXAMPLE"
        
        # Calculate greeks
        summary = portfolio.summary()
        nav = portfolio.nav
        
        # Portfolio summary
        c.print(f"\n[bold]Portfolio Stress Test[/bold] ({account_type})")
        c.print(f"NAV: ${nav:,.0f}  |  Delta: {summary['net_delta_pct']:+.1f}%  |  Vega: ${summary['net_vega']:+,.0f}  |  Theta: ${summary['net_theta_per_day']:+,.0f}/day\n")
        
        # Check for custom scenario
        if spx is not None or vix is not None:
            custom_params = StressParameters.custom(
                spx_pct=spx or 0,
                vix_pts=vix or 0,
                rate_bps=rates or 0,
                hy_bps=hy or 0,
            )
            result = run_stress_test(portfolio, custom_params)
            _display_single_result(c, result, nav)
            return
        
        # Single predefined scenario
        if scenario.lower() != "all":
            try:
                scenario_enum = StressScenario(scenario.lower())
            except ValueError:
                c.print(f"[red]Unknown scenario: {scenario}[/red]")
                c.print("Available: equity_crash, rates_shock_up, rates_shock_down, credit_event, flash_crash, stagflation, vol_crush")
                return
            
            result = run_stress_test(portfolio, scenario_enum)
            _display_single_result(c, result, nav)
            return
        
        # All scenarios
        results = run_all_stress_tests(portfolio)
        
        if json_output:
            import json
            output = {k: v.to_dict() for k, v in results.items()}
            c.print(json.dumps(output, indent=2))
            return
        
        _display_all_results(c, results, nav)


def _display_single_result(c: Console, result, nav: float):
    """Display single stress test result."""
    
    # Scenario details
    c.print(Panel(
        f"[bold]{result.scenario.name}[/bold]\n"
        f"{result.scenario.description}\n"
        f"Historical analog: {result.scenario.historical_analog or 'N/A'}",
        title="Scenario",
        border_style="cyan",
    ))
    
    # Market moves
    moves_table = Table(show_header=False, box=None, padding=(0, 2))
    moves_table.add_column("Move", style="dim")
    moves_table.add_column("Value", justify="right")
    moves_table.add_row("S&P 500", f"{result.scenario.spx_change_pct*100:+.1f}%")
    moves_table.add_row("VIX", f"{result.scenario.vix_change_pts:+.1f} pts")
    moves_table.add_row("10Y Yield", f"{result.scenario.rate_10y_change_bps:+.0f} bp")
    moves_table.add_row("HY OAS", f"{result.scenario.hy_oas_change_bps:+.0f} bp")
    moves_table.add_row("Horizon", f"{result.scenario.horizon_days} days")
    c.print(Panel(moves_table, title="Market Moves", border_style="blue"))
    
    # P&L breakdown
    pnl_table = Table(show_header=True)
    pnl_table.add_column("Component", style="bold")
    pnl_table.add_column("P&L $", justify="right")
    pnl_table.add_column("% NAV", justify="right")
    
    pnl_table.add_row(
        "Delta",
        f"${result.delta_pnl:+,.0f}",
        f"{result.delta_pnl/nav*100:+.1f}%",
    )
    pnl_table.add_row(
        "Vega",
        f"${result.vega_pnl:+,.0f}",
        f"{result.vega_pnl/nav*100:+.1f}%",
    )
    pnl_table.add_row(
        "Theta",
        f"${result.theta_pnl:+,.0f}",
        f"{result.theta_pnl/nav*100:+.1f}%",
    )
    pnl_table.add_row(
        "Gamma",
        f"${result.gamma_pnl:+,.0f}",
        f"{result.gamma_pnl/nav*100:+.1f}%",
    )
    pnl_table.add_row("", "", "")
    
    total_color = "green" if result.total_pnl_usd >= 0 else "red"
    pnl_table.add_row(
        f"[{total_color}]TOTAL[/{total_color}]",
        f"[{total_color}]${result.total_pnl_usd:+,.0f}[/{total_color}]",
        f"[{total_color}]{result.total_pnl_pct*100:+.1f}%[/{total_color}]",
    )
    
    c.print(Panel(pnl_table, title="P&L Attribution", border_style="yellow"))
    
    # Position breakdown
    if result.position_pnls:
        c.print("\n[bold]Position-Level Impact:[/bold]")
        pos_table = Table(show_header=True)
        pos_table.add_column("Position")
        pos_table.add_column("P&L $", justify="right")
        pos_table.add_column("% NAV", justify="right")
        
        sorted_positions = sorted(result.position_pnls.items(), key=lambda x: x[1])
        for ticker, pnl in sorted_positions:
            color = "green" if pnl >= 0 else "red"
            pos_table.add_row(
                ticker,
                f"[{color}]${pnl:+,.0f}[/{color}]",
                f"[{color}]{pnl/nav*100:+.2f}%[/{color}]",
            )
        
        c.print(pos_table)


def _display_all_results(c: Console, results, nav: float):
    """Display all stress test results in a summary table."""
    
    table = Table(title="Stress Test Results", show_header=True)
    table.add_column("Scenario", style="cyan")
    table.add_column("SPX", justify="right")
    table.add_column("VIX", justify="right")
    table.add_column("10Y", justify="right")
    table.add_column("P&L $", justify="right")
    table.add_column("% NAV", justify="right")
    table.add_column("Delta", justify="right", style="dim")
    table.add_column("Vega", justify="right", style="dim")
    
    for name, result in sorted(results.items(), key=lambda x: x[1].total_pnl_usd):
        pnl_color = "green" if result.total_pnl_usd >= 0 else "red"
        
        table.add_row(
            result.scenario.name,
            f"{result.scenario.spx_change_pct*100:+.0f}%",
            f"{result.scenario.vix_change_pts:+.0f}",
            f"{result.scenario.rate_10y_change_bps:+.0f}bp",
            f"[{pnl_color}]${result.total_pnl_usd:+,.0f}[/{pnl_color}]",
            f"[{pnl_color}]{result.total_pnl_pct*100:+.1f}%[/{pnl_color}]",
            f"${result.delta_pnl:+,.0f}",
            f"${result.vega_pnl:+,.0f}",
        )
    
    c.print(table)
    
    # Summary statistics
    c.print("\n[bold]Summary:[/bold]")
    worst = min(results.values(), key=lambda x: x.total_pnl_usd)
    best = max(results.values(), key=lambda x: x.total_pnl_usd)
    
    c.print(f"  Worst scenario: {worst.scenario.name} → ${worst.total_pnl_usd:+,.0f} ({worst.total_pnl_pct*100:+.1f}%)")
    c.print(f"  Best scenario:  {best.scenario.name} → ${best.total_pnl_usd:+,.0f} ({best.total_pnl_pct*100:+.1f}%)")
    
    # Tail protection assessment
    tail_scenarios = ["equity_crash", "credit_event", "flash_crash"]
    tail_results = [results[s] for s in tail_scenarios if s in results]
    if tail_results:
        avg_tail_pnl = sum(r.total_pnl_usd for r in tail_results) / len(tail_results)
        c.print(f"\n  Avg tail scenario P&L: ${avg_tail_pnl:+,.0f}")
        if avg_tail_pnl > 0:
            c.print("  [green]✓ Portfolio has positive tail convexity[/green]")
        else:
            c.print("  [yellow]⚠ Portfolio vulnerable to tail events[/yellow]")
