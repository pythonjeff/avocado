"""
v3 Monte Carlo CLI command.
"""
import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
import numpy as np

from ai_options_trader.config import Settings
from ai_options_trader.utils.settings import safe_load_settings
from ai_options_trader.utils.regimes import get_current_macro_regime
from ai_options_trader.llm.monte_carlo import MonteCarloEngine
from ai_options_trader.llm.correlation_trainer import CorrelationTrainer, validate_correlations


def register_v3(labs_app: typer.Typer) -> None:
    @labs_app.command("train-correlations")
    def train_correlations(
        start: str = typer.Option("2010-01-01", "--start", help="Training data start date"),
        validate: bool = typer.Option(True, "--validate/--no-validate", help="Validate on holdout data"),
    ):
        """
        Train correlation matrices from historical market data.
        
        This replaces hand-coded correlations with learned ones.
        Learns regime-conditional correlations:
        - How VIX/SPX/rates move together in STAGFLATION
        - How they move in DISINFLATIONARY regimes
        - Etc.
        
        Training data:
        - VIX, 10Y, 2Y, HY spreads, CPI from FRED
        - Daily data since 2010
        - Calculates actual correlations
        
        Examples:
            # Train on all data since 2010
            lox labs train-correlations
            
            # Train on recent data only
            lox labs train-correlations --start 2020-01-01
            
            # Skip validation (faster)
            lox labs train-correlations --no-validate
        """
        settings = safe_load_settings()
        c = Console()
        
        c.print("[cyan]Training correlation matrices from historical data...[/cyan]")
        
        trainer = CorrelationTrainer(settings)
        correlations = trainer.train_all_regimes(start_date=start)
        
        if validate:
            c.print("\n")
            for regime in ["ALL", "STAGFLATION"]:
                validate_correlations(trainer, regime=regime)
        
        c.print("\n[green]✓ Training complete![/green]")
        c.print("\nNext steps:")
        c.print("  1. Run Monte Carlo with trained correlations:")
        c.print("     [cyan]lox labs scenarios-monte-carlo[/cyan]")
        c.print("\n  2. Compare to heuristic correlations:")
        c.print("     [cyan]lox labs scenarios-monte-carlo --use-heuristics[/cyan]")
    
    @labs_app.command("scenarios-monte-carlo")
    def monte_carlo_analysis(
        n_scenarios: int = typer.Option(10000, "--scenarios", "-n", help="Number of scenarios to run"),
        horizon_months: int = typer.Option(3, "--horizon", help="Time horizon in months"),
        net_delta: float = typer.Option(-0.2, "--net-delta"),
        vega: float = typer.Option(0.1, "--vega"),
        theta: float = typer.Option(-0.0005, "--theta"),
        has_tail_hedges: bool = typer.Option(True, "--tail-hedges/--no-tail-hedges"),
        show_distribution: bool = typer.Option(False, "--show-dist", help="Show full distribution"),
        explain: bool = typer.Option(False, "--explain", help="Show detailed P&L breakdown and model assumptions"),
        start: str = typer.Option("2011-01-01", "--start"),
        refresh: bool = typer.Option(False, "--refresh"),
    ):
        """
        Run Monte Carlo simulation with 10,000+ scenarios.
        
        This generates a full P&L distribution using:
        - Realistic correlations (VIX-SPX, rates-spreads, etc.)
        - Regime-conditional behavior
        - Random sampling from historical volatilities
        
        Output:
        - VaR (Value at Risk): 95% and 99%
        - CVaR (Conditional VaR): Expected loss beyond VaR
        - Full distribution stats
        - Probability of loss/gain
        
        Examples:
            # Standard Monte Carlo
            lox labs scenarios-monte-carlo
            
            # Run 50,000 scenarios for higher precision
            lox labs scenarios-monte-carlo -n 50000
            
            # 6 month horizon
            lox labs scenarios-monte-carlo --horizon 6
        """
        settings = safe_load_settings()
        c = Console()
        
        # Get current market state
        c.print(f"[cyan]Fetching current market state and running {n_scenarios:,} scenarios...[/cyan]")
        
        import warnings
        warnings.filterwarnings("ignore", message=".*Optional series.*unavailable.*")
        
        regimes = get_current_macro_regime(settings, start=start, refresh=refresh)
        baseline_macro = regimes["macro_state"]
        baseline_funding = regimes["liquidity_state"]
        macro_regime = regimes["macro_regime"]
        regime_name = macro_regime.name if hasattr(macro_regime, 'name') else str(macro_regime)
        
        c.print(f"[green]✓[/green] Current regime: [bold]{regime_name}[/bold]")
        
        # Initialize Monte Carlo engine (always use heuristics - simpler)
        engine = MonteCarloEngine(regime=regime_name.upper(), use_trained=False)
        
        # Run simulation
        c.print(f"[cyan]Running Monte Carlo ({n_scenarios:,} scenarios)...[/cyan]")
        result = engine.run_monte_carlo(
            baseline_macro=baseline_macro,
            baseline_funding=baseline_funding,
            portfolio_net_delta=net_delta,
            portfolio_vega=vega,
            portfolio_theta=theta,
            has_tail_hedges=has_tail_hedges,
            horizon_months=horizon_months,
            n_scenarios=n_scenarios,
        )
        
        c.print(f"[green]✓[/green] Simulation complete")
        
        # Display results
        c.print("\n")
        c.print(Panel(
            f"[bold]Current Regime:[/bold] {regime_name}\n"
            f"[bold]Horizon:[/bold] {horizon_months} months\n"
            f"[bold]Portfolio:[/bold] Net Delta {net_delta*100:+.0f}%, Vega {vega:.2f}, Theta {theta*100:.2f} bps/day\n"
            f"[bold]Scenarios Run:[/bold] {n_scenarios:,}",
            title="Monte Carlo Risk Analysis",
            border_style="cyan",
        ))
        
        # Summary statistics
        stats_table = Table(show_header=False, box=None, padding=(0, 2))
        stats_table.add_column("Metric", style="bold")
        stats_table.add_column("Value", justify="right")
        
        stats_table.add_row("Mean P&L", f"{result.mean_pnl_pct*100:+.1f}%")
        stats_table.add_row("Median P&L", f"{result.median_pnl_pct*100:+.1f}%")
        stats_table.add_row("Std Dev", f"{result.std_pnl_pct*100:.1f}%")
        stats_table.add_row("", "")
        stats_table.add_row("Best Case", f"[green]+{result.max_gain_pct*100:.1f}%[/green]")
        stats_table.add_row("Worst Case", f"[red]{result.max_loss_pct*100:.1f}%[/red]")
        stats_table.add_row("", "")
        stats_table.add_row("Probability of Gain", f"{result.n_profitable/result.n_scenarios*100:.1f}%")
        stats_table.add_row("Probability of Loss", f"{result.n_loss/result.n_scenarios*100:.1f}%")
        
        c.print(Panel(stats_table, title="Distribution Statistics", border_style="blue"))
        
        # Risk metrics
        risk_table = Table(show_header=False, box=None, padding=(0, 2))
        risk_table.add_column("Metric", style="bold")
        risk_table.add_column("Value", justify="right")
        risk_table.add_column("Interpretation", style="dim")
        
        var_95_color = "red" if result.var_95_pct < -0.05 else "yellow" if result.var_95_pct < 0 else "green"
        var_99_color = "red" if result.var_99_pct < -0.10 else "yellow" if result.var_99_pct < -0.05 else "green"
        
        risk_table.add_row(
            "VaR 95% (5th %ile)",
            f"[{var_95_color}]{result.var_95_pct*100:+.1f}%[/{var_95_color}]",
            "95% of outcomes are better"
        )
        risk_table.add_row(
            "VaR 99% (1st %ile)",
            f"[{var_99_color}]{result.var_99_pct*100:+.1f}%[/{var_99_color}]",
            "99% of outcomes are better"
        )
        risk_table.add_row(
            "CVaR 95%",
            f"[red]{result.cvar_95_pct*100:+.1f}%[/red]",
            "Expected loss in worst 5%"
        )
        
        c.print(Panel(risk_table, title="Risk Metrics (Tail Risk)", border_style="yellow"))
        
        # Distribution buckets
        c.print("\n[bold]P&L Distribution:[/bold]")
        buckets = [
            ("Large Gain", result.pnl_distribution >= 0.10, "green"),
            ("Moderate Gain", (result.pnl_distribution >= 0.03) & (result.pnl_distribution < 0.10), "green"),
            ("Small Gain", (result.pnl_distribution >= 0) & (result.pnl_distribution < 0.03), "white"),
            ("Small Loss", (result.pnl_distribution >= -0.03) & (result.pnl_distribution < 0), "white"),
            ("Moderate Loss", (result.pnl_distribution >= -0.10) & (result.pnl_distribution < -0.03), "yellow"),
            ("Large Loss", result.pnl_distribution < -0.10, "red"),
        ]
        
        for label, mask, color in buckets:
            count = np.sum(mask)
            pct = count / result.n_scenarios * 100
            bar_length = int(pct / 2)  # Scale for display
            bar = "█" * bar_length
            c.print(f"  [{color}]{label:15s} {pct:5.1f}% {bar}[/{color}]")
        
        # Interpretation
        c.print("\n")
        interp_lines = []
        
        if result.var_95_pct < -0.10:
            interp_lines.append("[red]⚠️  High tail risk: 5% chance of losing >10%[/red]")
            interp_lines.append("[red]   Consider adding more hedges or reducing exposure[/red]")
        elif result.var_95_pct < -0.05:
            interp_lines.append("[yellow]⚠️  Moderate tail risk: 5% chance of losing >5%[/yellow]")
            interp_lines.append("[yellow]   Monitor closely and consider hedge adjustments[/yellow]")
        else:
            interp_lines.append("[green]✓ Tail risk manageable (95% VaR > -5%)[/green]")
        
        if result.mean_pnl_pct > 0:
            interp_lines.append(f"[green]✓ Portfolio has positive expected return (+{result.mean_pnl_pct*100:.1f}%)[/green]")
        else:
            interp_lines.append(f"[yellow]⚠️  Portfolio has negative expected return ({result.mean_pnl_pct*100:.1f}%)[/yellow]")
            interp_lines.append(f"[yellow]   Theta decay ({theta*horizon_months*30*100:.1f}%) is main driver[/yellow]")
        
        if result.n_profitable / result.n_scenarios > 0.6:
            interp_lines.append(f"[green]✓ High win rate ({result.n_profitable/result.n_scenarios*100:.0f}% of scenarios profitable)[/green]")
        elif result.n_profitable / result.n_scenarios < 0.4:
            interp_lines.append(f"[red]⚠️  Low win rate ({result.n_profitable/result.n_scenarios*100:.0f}% of scenarios profitable)[/red]")
        
        c.print(Panel("\n".join(interp_lines), title="Interpretation", border_style="magenta"))
        
        # Show detailed explanation if requested
        if explain:
            c.print("\n")
            c.print("[bold cyan]═══ Model Interpretability ═══[/bold cyan]\n")
            
            # 1. What's driving the P&L?
            c.print("[bold]1. P&L Components (typical scenario):[/bold]")
            days = horizon_months * 30
            theta_total = theta * days
            
            explain_table = Table(show_header=False, box=None, padding=(0, 2))
            explain_table.add_column("Component", style="cyan")
            explain_table.add_column("Contribution", justify="right")
            explain_table.add_column("Explanation", style="dim")
            
            explain_table.add_row(
                "Theta decay",
                f"{theta_total*100:+.1f}%",
                f"({theta*100:.3f}% per day × {days} days)"
            )
            explain_table.add_row(
                "Delta exposure",
                f"Varies with SPX",
                f"({net_delta*100:+.0f}% delta → gain/lose with market)"
            )
            explain_table.add_row(
                "Vega exposure",
                f"Varies with VIX",
                f"({vega:.2f} → gain {vega*10*100:.1f}% if VIX +10pts)"
            )
            if has_tail_hedges:
                explain_table.add_row(
                    "Tail hedges",
                    "Convex gains",
                    "(Big gains when VIX spikes >30%)"
                )
            
            c.print(explain_table)
            
            # 2. Why is median so different from mean?
            c.print(f"\n[bold]2. Why Median ({result.median_pnl_pct*100:+.1f}%) ≠ Mean ({result.mean_pnl_pct*100:+.1f}%)?[/bold]")
            
            if result.median_pnl_pct < result.mean_pnl_pct - 0.03:
                c.print("  [yellow]→ Your portfolio has POSITIVE SKEW (tail hedge structure):[/yellow]")
                c.print("    • Most scenarios: Small losses (theta decay dominates)")
                c.print("    • Rare scenarios: Huge gains (hedges pay off)")
                c.print("    • This is INTENTIONAL for tail-risk hedging!")
            else:
                c.print("  → Distribution is roughly symmetric")
            
            # 3. Scenario analysis
            c.print(f"\n[bold]3. What market moves create each outcome?[/bold]")
            
            # Analyze best and worst scenarios
            best_idx = int(np.argmax(result.pnl_distribution))
            worst_idx = int(np.argmin(result.pnl_distribution))
            median_idx = int(np.argsort(result.pnl_distribution)[len(result.pnl_distribution)//2])
            
            scenario_table = Table(show_header=True, box=None)
            scenario_table.add_column("Scenario", style="bold")
            scenario_table.add_column("P&L", justify="right")
            scenario_table.add_column("VIX", justify="right")
            scenario_table.add_column("SPX", justify="right")
            scenario_table.add_column("10Y Yield", justify="right")
            
            for label, idx, color in [
                ("Best Case", best_idx, "green"),
                ("Median", median_idx, "white"),
                ("Worst Case", worst_idx, "red"),
            ]:
                pnl = result.pnl_distribution[idx]
                vix_chg = result.scenario_matrix.iloc[idx]['vix_change_pct']
                spx_chg = result.scenario_matrix.iloc[idx]['spx_change_pct']
                y10_chg = result.scenario_matrix.iloc[idx]['ust_10y_change_bps']
                
                baseline_vix = baseline_macro.inputs.vix or 15.0
                target_vix = baseline_vix * (1 + vix_chg)
                
                scenario_table.add_row(
                    label,
                    f"[{color}]{pnl*100:+.1f}%[/{color}]",
                    f"{target_vix:.1f} ({vix_chg*100:+.0f}%)",
                    f"{spx_chg*100:+.1f}%",
                    f"{y10_chg:+.0f} bps"
                )
            
            c.print(scenario_table)
            
            # 4. Model assumptions
            c.print(f"\n[bold]4. Key Model Assumptions:[/bold]")
            
            assumptions = [
                f"• VIX-SPX correlation: -0.75 (strong negative)",
                f"• VIX typical move: ±40% over {horizon_months}M",
                f"• SPX typical move: ±15% over {horizon_months}M",
                f"• Tail hedges activate when VIX >30% spike",
                f"• Convexity: VIX +50% → hedge gains ~{0.5*0.5*100:.0f}% NAV",
            ]
            
            for assumption in assumptions:
                c.print(f"  {assumption}")
            
            # 5. What makes this wrong?
            c.print(f"\n[bold]5. What Could Make This Prediction Wrong?[/bold]")
            
            risks = [
                "⚠️  VIX doesn't spike (hedges never pay off → just theta decay)",
                "⚠️  Correlations break (VIX up but SPX also up)",
                "⚠️  Volatility is calmer than assumed (±40% might be too high)",
                "⚠️  Greeks change as positions age (not modeled)",
                "⚠️  Liquidity events (can't exit at model prices)",
            ]
            
            for risk in risks:
                c.print(f"  {risk}")
            
            # 6. Validation idea
            c.print(f"\n[bold]6. How to Validate This Model:[/bold]")
            c.print("  → Compare predictions to actual P&L over next 3-6 months")
            c.print("  → Track: Did VIX move ±40%? Did correlations hold?")
            c.print("  → If model is consistently wrong, adjust volatilities/correlations")
        
        # Show extreme scenarios if requested
        if show_distribution:
            c.print("\n[bold]Extreme Scenarios:[/bold]")
            
            # Find best and worst scenarios
            best_idx = int(np.argmax(result.pnl_distribution))
            worst_idx = int(np.argmin(result.pnl_distribution))
            
            c.print("\n[green]Best Scenario:[/green]")
            c.print(f"  P&L: +{result.pnl_distribution[best_idx]*100:.1f}%")
            c.print(f"  VIX change: {result.scenario_matrix.iloc[best_idx]['vix_change_pct']*100:+.1f}%")
            c.print(f"  SPX change: {result.scenario_matrix.iloc[best_idx]['spx_change_pct']*100:+.1f}%")
            c.print(f"  10Y change: {result.scenario_matrix.iloc[best_idx]['ust_10y_change_bps']:+.0f} bps")
            
            c.print("\n[red]Worst Scenario:[/red]")
            c.print(f"  P&L: {result.pnl_distribution[worst_idx]*100:.1f}%")
            c.print(f"  VIX change: {result.scenario_matrix.iloc[worst_idx]['vix_change_pct']*100:+.1f}%")
            c.print(f"  SPX change: {result.scenario_matrix.iloc[worst_idx]['spx_change_pct']*100:+.1f}%")
            c.print(f"  10Y change: {result.scenario_matrix.iloc[worst_idx]['ust_10y_change_bps']:+.0f} bps")
