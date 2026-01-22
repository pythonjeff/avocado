"""
v0.1 Monte Carlo CLI with position-level representation.
"""
import os
import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from ai_options_trader.portfolio.positions import create_example_portfolio
from ai_options_trader.portfolio.alpaca_adapter import alpaca_to_portfolio
from ai_options_trader.llm.monte_carlo_v01 import MonteCarloV01, ScenarioAssumptions
from ai_options_trader.utils.settings import safe_load_settings


def register_v01(labs_app: typer.Typer) -> None:
    @labs_app.command("mc-v01")
    def monte_carlo_v01(
        n_scenarios: int = typer.Option(10000, "--scenarios", "-n"),
        horizon_months: int = typer.Option(6, "--horizon"),
        regime: str = typer.Option("ALL", "--regime", help="ALL, STAGFLATION, GOLDILOCKS, RISK_OFF, etc."),
        live: bool = typer.Option(True, "--live/--paper", help="Use LIVE account (default) or paper account"),
        example: bool = typer.Option(False, "--example", help="Use example portfolio instead of real positions"),
    ):
        """
        v0.1 Monte Carlo with position-level representation.
        
        Defaults to LIVE account with real positions.
        
        Examples:
            lox labs mc-v01                    # Live account
            lox labs mc-v01 --paper            # Paper account
            lox labs mc-v01 --example          # Example portfolio
            lox labs mc-v01 --regime STAGFLATION
        """
        c = Console()
        
        if example:
            c.print("[cyan]Building example portfolio...[/cyan]")
            portfolio = create_example_portfolio()
            account_type = "EXAMPLE"
        else:
            # Force live or paper via environment override
            if live:
                os.environ["ALPACA_PAPER"] = "false"
                account_type = "🟢 LIVE"
            else:
                os.environ["ALPACA_PAPER"] = "true"
                account_type = "🟡 PAPER"
            
            c.print(f"[cyan]Fetching positions from {account_type} account...[/cyan]")
            settings = safe_load_settings()
            portfolio = alpaca_to_portfolio(settings)
            
            if len(portfolio.positions) == 0:
                c.print(f"[yellow]⚠️  No positions found in {account_type} account. Using example portfolio.[/yellow]")
                portfolio = create_example_portfolio()
                account_type = "EXAMPLE (no positions)"
        
        c.print("[cyan]Calculating greeks...[/cyan]")
        summary = portfolio.summary()
        
        # ✅ SANITY CHECK: Verify greeks sum correctly
        manual_vega = sum(p.position_vega_usd for p in portfolio.positions)
        manual_theta = sum(p.position_theta_usd for p in portfolio.positions)
        
        vega_mismatch = abs(manual_vega - summary['net_vega']) > 0.01
        theta_mismatch = abs(manual_theta - summary['net_theta_per_day']) > 0.01
        
        if vega_mismatch or theta_mismatch:
            c.print(Panel(
                f"[red]⚠️  GREEKS SANITY CHECK FAILED:[/red]\n\n"
                f"Portfolio vega: ${summary['net_vega']:.2f}\n"
                f"Sum of position vegas: ${manual_vega:.2f}\n"
                f"Portfolio theta: ${summary['net_theta_per_day']:.2f}\n"
                f"Sum of position thetas: ${manual_theta:.2f}\n\n"
                f"[yellow]Skipping Monte Carlo until greeks are fixed.[/yellow]",
                title="Calculation Error",
                border_style="red"
            ))
            return
        
        # Show portfolio summary
        c.print("\n")
        port_table = Table(show_header=False, box=None, padding=(0, 2))
        port_table.add_column("Metric", style="bold cyan")
        port_table.add_column("Value", justify="right")
        
        port_table.add_row("Account", f"[bold]{account_type}[/bold]")
        port_table.add_row("NAV", f"${summary['nav']:,.0f}")
        port_table.add_row("Positions", f"{summary['n_positions']} ({summary['n_options']} options)")
        port_table.add_row("Delta (per +1% move)", f"${portfolio.net_delta_usd_per_1pct:+,.0f}  ({summary['net_delta_pct']:+.1f}% NAV)")
        port_table.add_row("Net Vega", f"${summary['net_vega']:+,.0f} per 1pt IV")
        port_table.add_row("Net Theta", f"${summary['net_theta_per_day']:+,.0f} /day")
        port_table.add_row("Theta Carry (3M)", f"${summary['net_theta_per_day']*63:+,.0f}  ({summary['net_theta_per_day']*63/summary['nav']*100:+.1f}% NAV)")
        port_table.add_row("Theta Carry (6M)", f"${summary['net_theta_per_day']*126:+,.0f}  ({summary['theta_carry_pct_6m']:+.1f}% NAV)")
        
        c.print(Panel(port_table, title="Portfolio Summary", border_style="cyan"))
        
        # Show positions
        c.print("\n[bold]Positions:[/bold]")
        pos_table = Table(show_header=True)
        pos_table.add_column("Ticker", style="cyan")
        pos_table.add_column("Type")
        pos_table.add_column("Qty", justify="right")
        pos_table.add_column("Notional", justify="right")
        pos_table.add_column("Delta", justify="right")
        pos_table.add_column("Vega", justify="right")
        pos_table.add_column("Theta/day", justify="right")
        pos_table.add_column("DTE", justify="right")
        
        for pos in portfolio.positions:
            pos_table.add_row(
                pos.ticker,
                pos.position_type.upper(),
                f"{pos.quantity:+.0f}",
                f"${pos.notional:,.0f}",
                f"{pos.delta:+.2f}",
                f"${pos.position_vega_usd:+,.0f}" if pos.is_option else "-",
                f"${pos.position_theta_usd:+,.0f}" if pos.is_option else "-",
                f"{pos.dte}d" if pos.is_option else "-",
            )
        
        c.print(pos_table)
        
        # Get scenario assumptions
        assumptions = ScenarioAssumptions.for_regime(regime, horizon_months)
        
        c.print(f"\n[cyan]Running {n_scenarios:,} scenarios ({regime} regime, {horizon_months}M horizon)...[/cyan]")
        
        # Show assumptions
        c.print("\n[bold]Model Assumptions (regime-conditioned):[/bold]")
        assump_table = Table(show_header=False, box=None, padding=(0, 2))
        assump_table.add_column("Parameter", style="dim")
        assump_table.add_column("Value", justify="right")
        
        assump_table.add_row("Equity drift (ann.)", f"{assumptions.equity_drift*100:+.1f}%")
        assump_table.add_row("Equity vol (ann.)", f"{assumptions.equity_vol*100:.1f}%")
        assump_table.add_row("IV mean reversion", f"{assumptions.iv_mean_reversion_speed:.2f}")
        assump_table.add_row("IV vol-of-vol", f"{assumptions.iv_vol_of_vol:.2f}")
        assump_table.add_row("Corr(S, IV)", f"{assumptions.corr_return_iv:+.2f}")
        assump_table.add_row("Jump probability", f"{assumptions.jump_probability*100:.1f}%")
        assump_table.add_row("Jump size (mean)", f"{assumptions.jump_size_mean*100:.0f}%")
        assump_table.add_row("Jump IV spike", f"+{assumptions.jump_iv_spike:.1f}pts")
        
        c.print(assump_table)
        
        # Run simulation
        engine = MonteCarloV01(portfolio, assumptions)
        results = engine.generate_scenarios(n_scenarios)
        analysis = engine.analyze_results(results)
        
        c.print(f"[green]✓[/green] Simulation complete")
        
        # Results
        c.print("\n")
        stats_table = Table(show_header=False, box=None, padding=(0, 2))
        stats_table.add_column("Metric", style="bold")
        stats_table.add_column("% of NAV", justify="right")
        stats_table.add_column("$", justify="right", style="dim")
        
        nav = portfolio.nav
        stats_table.add_row("Mean P&L", 
                           f"{analysis['mean_pnl_pct']*100:+.1f}%",
                           f"${analysis['mean_pnl_pct']*nav:+,.0f}")
        stats_table.add_row("Median P&L", 
                           f"{analysis['median_pnl_pct']*100:+.1f}%",
                           f"${analysis['median_pnl_pct']*nav:+,.0f}")
        stats_table.add_row("Std Dev", 
                           f"{analysis['std_pnl_pct']*100:.1f}%",
                           f"${analysis['std_pnl_pct']*nav:,.0f}")
        stats_table.add_row("Skewness", 
                           f"{analysis['skewness']:+.2f}",
                           "higher = positive skew")
        
        c.print(Panel(stats_table, title="Distribution Statistics", border_style="blue"))
        
        # Risk metrics
        c.print("\n")
        risk_table = Table(show_header=False, box=None, padding=(0, 2))
        risk_table.add_column("Metric", style="bold")
        risk_table.add_column("% of NAV", justify="right")
        risk_table.add_column("Interpretation", style="dim")
        
        risk_table.add_row("VaR 95%", 
                          f"{analysis['var_95_pct']*100:+.1f}%",
                          "5% chance of worse")
        risk_table.add_row("VaR 99%", 
                          f"{analysis['var_99_pct']*100:+.1f}%",
                          "1% chance of worse")
        risk_table.add_row("CVaR 95%", 
                          f"{analysis['cvar_95_pct']*100:+.1f}%",
                          "Expected loss in worst 5%")
        risk_table.add_row("", "", "")
        risk_table.add_row("P(gain)", 
                          f"{analysis['prob_positive']*100:.1f}%",
                          "Probability of profit")
        risk_table.add_row("P(loss > 10%)", 
                          f"{analysis['prob_loss_gt_10pct']*100:.1f}%",
                          "Tail risk")
        risk_table.add_row("P(loss > 20%)", 
                          f"{analysis['prob_loss_gt_20pct']*100:.1f}%",
                          "Severe tail risk")
        
        c.print(Panel(risk_table, title="Risk Metrics", border_style="yellow"))
        
        # CVaR attribution
        c.print("\n[bold]CVaR Attribution (worst 5% scenarios):[/bold]")
        c.print("Contributors to tail losses (negative = helped, positive = hurt)\n")
        
        for ticker, contrib_pct in list(analysis['cvar_attribution'].items())[:5]:
            bar_len = int(abs(contrib_pct) / 5)
            bar = "█" * bar_len
            # Negative contrib = helped in tail (good for hedges), Positive = hurt
            color = "green" if contrib_pct < 0 else "red"
            c.print(f"  [{color}]{ticker:25s} {contrib_pct:+6.1f}% {bar}[/{color}]")
        
        # Top 3 losers
        c.print("\n[bold]Top 3 Losing Scenarios:[/bold]")
        for i, scenario in enumerate(analysis['top_3_losers'], 1):
            c.print(f"\n[red]#{i} Loss: {scenario['pnl_pct']*100:.1f}%[/red]")
            c.print(f"  Jump event: {'YES' if scenario['had_jump'] else 'no'}")
            for ticker, ret in scenario['equity_moves'].items():
                # Only show IV for options, not for stocks/ETFs
                is_option_ticker = '/' in ticker or any(c in ticker for c in ['C', 'P']) and len(ticker) > 10
                if is_option_ticker:
                    iv_chg = scenario['iv_moves'].get(ticker, 0)
                    c.print(f"  {ticker}: {ret*100:+.1f}% (IV {iv_chg:+.1f}pts)")
                else:
                    c.print(f"  {ticker}: {ret*100:+.1f}%")
            c.print(f"  Worst position: {scenario['top_detractor']}")
        
        # Top 3 winners
        c.print("\n[bold]Top 3 Winning Scenarios:[/bold]")
        for i, scenario in enumerate(analysis['top_3_winners'], 1):
            c.print(f"\n[green]#{i} Gain: {scenario['pnl_pct']*100:.1f}%[/green]")
            c.print(f"  Jump event: {'YES' if scenario['had_jump'] else 'no'}")
            for ticker, ret in scenario['equity_moves'].items():
                # Only show IV for options, not for stocks/ETFs
                is_option_ticker = '/' in ticker or any(c in ticker for c in ['C', 'P']) and len(ticker) > 10
                if is_option_ticker:
                    iv_chg = scenario['iv_moves'].get(ticker, 0)
                    c.print(f"  {ticker}: {ret*100:+.1f}% (IV {iv_chg:+.1f}pts)")
                else:
                    c.print(f"  {ticker}: {ret*100:+.1f}%")
            c.print(f"  Best position: {scenario['top_contributor']}")
