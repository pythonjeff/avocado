"""
Core CLI commands - Clean, elegant, hedge-fund grade.

Design principles:
1. Progressive disclosure - simple by default, advanced when needed
2. Single responsibility - each command does ONE thing well
3. Clear naming - commands describe WHAT, not HOW
4. Sensible defaults - works out of the box

Author: Lox Capital Research
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ai_options_trader.config import load_settings
from ai_options_trader.data.alpaca import make_clients


def _safe_float(x) -> float:
    """Safe float conversion with 0.0 default."""
    try:
        return float(x) if x is not None else 0.0
    except (ValueError, TypeError):
        return 0.0


def register_core(app: typer.Typer) -> None:
    """Register core commands directly on the main app."""
    
    @app.command("status")
    def status(
        verbose: bool = typer.Option(False, "--verbose", "-v", help="Show position details"),
    ):
        """
        Portfolio health at a glance. Fast, no LLM.
        
        Shows: NAV, cash, positions summary, P&L, risk flags.
        
        Examples:
            lox status
            lox status -v
        """
        console = Console()
        settings = load_settings()
        trading, _ = make_clients(settings)
        
        # Account
        try:
            acct = trading.get_account()
        except Exception as e:
            console.print(f"[red]Connection failed:[/red] {e}")
            raise typer.Exit(1)
        
        mode = "PAPER" if settings.alpaca_paper else "LIVE"
        cash = _safe_float(getattr(acct, "cash", 0))
        equity = _safe_float(getattr(acct, "equity", 0))
        bp = _safe_float(getattr(acct, "buying_power", 0))
        
        # Positions
        positions = trading.get_all_positions()
        n_positions = len(positions)
        
        # Get total capital from investor flows or env var
        total_capital = float(os.environ.get("FUND_TOTAL_CAPITAL", 950))
        try:
            from ai_options_trader.nav.investors import read_investor_flows
            flows = read_investor_flows()
            if flows:
                total_capital = sum(f.amount for f in flows)
        except Exception:
            pass  # Fall back to env var
        
        # Fund-level P&L (NAV - Total Capital)
        fund_pnl = equity - total_capital
        fund_pnl_pct = (fund_pnl / total_capital * 100) if total_capital > 0 else 0.0
        
        # Position-level unrealized P&L (for reference)
        position_pnl = sum(_safe_float(getattr(p, "unrealized_pl", 0)) for p in positions)
        
        # Risk flags
        losers = [p for p in positions if _safe_float(getattr(p, "unrealized_plpc", 0)) < -0.20]
        expiring = []  # Would need option parsing
        
        # Build status panel
        status_lines = [
            f"[bold]NAV:[/bold] ${equity:,.0f}",
            f"[bold]Cash:[/bold] ${cash:,.0f} ({cash/equity*100:.0f}% of NAV)" if equity > 0 else f"[bold]Cash:[/bold] ${cash:,.0f}",
            f"[bold]Positions:[/bold] {n_positions}",
            f"[bold]Fund P&L:[/bold] ${fund_pnl:+,.0f} ({fund_pnl_pct:+.1f}%)",
        ]
        
        if losers:
            status_lines.append(f"[yellow]⚠ {len(losers)} position(s) down >20%[/yellow]")
        
        console.print(Panel(
            "\n".join(status_lines),
            title=f"Lox Portfolio [{mode}]",
            subtitle=datetime.now().strftime("%Y-%m-%d %H:%M"),
            expand=False,
        ))
        
        # Verbose: show positions
        if verbose and positions:
            table = Table(title="Positions", show_header=True)
            table.add_column("Symbol", style="cyan")
            table.add_column("Qty", justify="right")
            table.add_column("Entry", justify="right")
            table.add_column("Current", justify="right")
            table.add_column("P&L", justify="right")
            table.add_column("P&L %", justify="right")
            
            for p in sorted(positions, key=lambda x: _safe_float(getattr(x, "unrealized_pl", 0))):
                sym = str(getattr(p, "symbol", ""))
                qty = _safe_float(getattr(p, "qty", 0))
                entry = _safe_float(getattr(p, "avg_entry_price", 0))
                current = _safe_float(getattr(p, "current_price", 0))
                pnl = _safe_float(getattr(p, "unrealized_pl", 0))
                pnl_pc = _safe_float(getattr(p, "unrealized_plpc", 0)) * 100
                
                pnl_style = "green" if pnl >= 0 else "red"
                
                table.add_row(
                    sym[:20],
                    f"{qty:+.1f}" if abs(qty) < 10 else f"{qty:+.0f}",
                    f"${entry:.2f}",
                    f"${current:.2f}",
                    f"[{pnl_style}]${pnl:+,.0f}[/{pnl_style}]",
                    f"[{pnl_style}]{pnl_pc:+.1f}%[/{pnl_style}]",
                )
            
            console.print(table)
    
    @app.command("report")
    def report(
        period: str = typer.Option("week", "--period", "-p", help="day|week|month"),
    ):
        """
        Generate portfolio report. Clean summary for investors.
        
        Examples:
            lox report
            lox report --period month
        """
        console = Console()
        settings = load_settings()
        trading, _ = make_clients(settings)
        
        # Get current data
        acct = trading.get_account()
        positions = trading.get_all_positions()
        
        mode = "PAPER" if settings.alpaca_paper else "LIVE"
        cash = _safe_float(getattr(acct, "cash", 0))
        equity = _safe_float(getattr(acct, "equity", 0))
        
        # P&L
        total_pnl = sum(_safe_float(getattr(p, "unrealized_pl", 0)) for p in positions)
        
        # Report header
        console.print(Panel(
            f"[bold]Lox Capital {period.title()}ly Report[/bold]\n"
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
            f"Mode: {mode}",
            expand=False,
        ))
        
        # NAV Summary
        console.print("\n[bold cyan]Portfolio Summary[/bold cyan]")
        nav_table = Table(show_header=False)
        nav_table.add_column("Metric", style="bold")
        nav_table.add_column("Value", justify="right")
        nav_table.add_row("NAV (Equity)", f"${equity:,.0f}")
        nav_table.add_row("Cash", f"${cash:,.0f}")
        nav_table.add_row("Invested", f"${equity - cash:,.0f}")
        nav_table.add_row("Unrealized P&L", f"${total_pnl:+,.0f}")
        console.print(nav_table)
        
        # Positions
        if positions:
            console.print("\n[bold cyan]Current Positions[/bold cyan]")
            pos_table = Table(show_header=True)
            pos_table.add_column("Symbol", style="cyan")
            pos_table.add_column("Qty", justify="right")
            pos_table.add_column("Value", justify="right")
            pos_table.add_column("P&L", justify="right")
            pos_table.add_column("P&L %", justify="right")
            
            for p in sorted(positions, key=lambda x: -abs(_safe_float(getattr(x, "market_value", 0)))):
                sym = str(getattr(p, "symbol", ""))[:15]
                qty = _safe_float(getattr(p, "qty", 0))
                mv = _safe_float(getattr(p, "market_value", 0))
                pnl = _safe_float(getattr(p, "unrealized_pl", 0))
                pnl_pc = _safe_float(getattr(p, "unrealized_plpc", 0)) * 100
                
                style = "green" if pnl >= 0 else "red"
                pos_table.add_row(
                    sym,
                    f"{qty:+.1f}" if abs(qty) < 10 else f"{qty:+.0f}",
                    f"${abs(mv):,.0f}",
                    f"[{style}]${pnl:+,.0f}[/{style}]",
                    f"[{style}]{pnl_pc:+.1f}%[/{style}]",
                )
            
            console.print(pos_table)
        
        # For weekly report, also run the full report
        if period == "week":
            console.print("\n[dim]For detailed weekly report: lox weekly report[/dim]")
    
    @app.command("analyze")
    def analyze(
        depth: str = typer.Option("quick", "--depth", "-d", help="quick|deep"),
    ):
        """
        AI-powered portfolio analysis. Identifies risks and opportunities.
        
        Examples:
            lox analyze
            lox analyze --depth deep
        """
        console = Console()
        settings = load_settings()
        
        if depth == "quick":
            # Quick analysis without full LLM
            console.print("[dim]Running quick analysis...[/dim]")
            # Use existing account summary but with minimal LLM
            from ai_options_trader.cli_commands.core.account_cmd import _to_float
            trading, _ = make_clients(settings)
            
            acct = trading.get_account()
            positions = trading.get_all_positions()
            
            # Simple risk assessment
            risks = []
            total_pnl = sum(_safe_float(getattr(p, "unrealized_pl", 0)) for p in positions)
            
            losers = [p for p in positions if _safe_float(getattr(p, "unrealized_plpc", 0)) < -0.15]
            if losers:
                risks.append(f"• {len(losers)} position(s) down >15% - consider stop-loss")
            
            # Concentration check
            if len(positions) > 0:
                values = [abs(_safe_float(getattr(p, "market_value", 0))) for p in positions]
                total = sum(values)
                if total > 0:
                    max_weight = max(values) / total
                    if max_weight > 0.30:
                        risks.append(f"• Largest position is {max_weight:.0%} of portfolio - high concentration")
            
            # Cash check
            cash = _safe_float(getattr(acct, "cash", 0))
            equity = _safe_float(getattr(acct, "equity", 0))
            if equity > 0 and cash / equity < 0.05:
                risks.append("• Cash below 5% - limited dry powder")
            
            if risks:
                console.print(Panel(
                    "\n".join(risks),
                    title="[yellow]Risk Flags[/yellow]",
                    expand=False,
                ))
            else:
                console.print(Panel(
                    "[green]No major risk flags detected[/green]",
                    title="Analysis",
                    expand=False,
                ))
        else:
            # Deep analysis with LLM
            console.print("[dim]Running deep analysis with LLM...[/dim]")
            # Delegate to account summary
            from ai_options_trader.cli_commands.core.account_cmd import register as _unused
            # Call the summary logic directly
            from ai_options_trader.llm.account_summary import llm_account_summary
            from ai_options_trader.overlay.context import build_trackers
            
            trading, _ = make_clients(settings)
            acct = trading.get_account()
            mode = "PAPER" if settings.alpaca_paper else "LIVE"
            cash = _safe_float(getattr(acct, "cash", 0))
            equity = _safe_float(getattr(acct, "equity", 0))
            bp = _safe_float(getattr(acct, "buying_power", 0))
            
            positions = []
            for p in trading.get_all_positions():
                positions.append({
                    "symbol": getattr(p, "symbol", ""),
                    "qty": _safe_float(getattr(p, "qty", 0)),
                    "avg_entry_price": _safe_float(getattr(p, "avg_entry_price", 0)),
                    "current_price": _safe_float(getattr(p, "current_price", 0)),
                    "unrealized_pl": _safe_float(getattr(p, "unrealized_pl", 0)),
                    "unrealized_plpc": _safe_float(getattr(p, "unrealized_plpc", 0)),
                })
            
            _, risk_watch = build_trackers(settings=settings, start_date="2012-01-01", refresh_fred=False)
            
            asof = datetime.now(timezone.utc).date().isoformat()
            text = llm_account_summary(
                settings=settings,
                asof=asof,
                account={"mode": mode, "cash": cash, "equity": equity, "buying_power": bp},
                positions=positions,
                recent_orders=[],
                risk_watch=risk_watch,
                news={},
                model=None,
                temperature=0.2,
            )
            console.print(Panel(text, title="Deep Analysis (LLM)", expand=False))
    
    @app.command("suggest")
    def suggest(
        style: str = typer.Option("balanced", "--style", "-s", help="defensive|balanced|aggressive"),
        count: int = typer.Option(5, "--count", "-n", help="Number of ideas to generate"),
    ):
        """
        Quick trade suggestions based on current regime.
        
        Styles:
            defensive: Focus on hedges and protection
            balanced: Mix of hedges and opportunities
            aggressive: Growth and momentum plays
        
        Examples:
            lox suggest
            lox suggest --style defensive
            lox suggest --style aggressive --count 10
        """
        console = Console()
        settings = load_settings()
        
        console.print(f"[dim]Generating {style} trade ideas...[/dim]\n")
        
        if style == "defensive":
            # Use hedge command
            from ai_options_trader.cli_commands.ideas.hedges_cmd import _generate_offsetting_ideas
            from ai_options_trader.utils.regimes import get_current_macro_regime
            
            regime_info = get_current_macro_regime(settings)
            regime = regime_info.get("regime", "UNKNOWN")
            
            trading, _ = make_clients(settings)
            positions = trading.get_all_positions()
            
            ideas = _generate_offsetting_ideas(positions, regime, count)
            
            if ideas:
                table = Table(title=f"Defensive Ideas (Regime: {regime})")
                table.add_column("Type", style="cyan")
                table.add_column("Ticker")
                table.add_column("Action")
                table.add_column("Rationale")
                
                for idea in ideas[:count]:
                    table.add_row(
                        idea.get("type", ""),
                        idea.get("ticker", ""),
                        idea.get("action", ""),
                        idea.get("rationale", "")[:50],
                    )
                console.print(table)
            else:
                console.print("[yellow]No defensive ideas generated[/yellow]")
        
        elif style == "aggressive":
            # Use grow command
            from ai_options_trader.cli_commands.ideas.hedges_cmd import _generate_growth_ideas
            from ai_options_trader.utils.regimes import get_current_macro_regime
            
            regime_info = get_current_macro_regime(settings)
            regime = regime_info.get("regime", "UNKNOWN")
            
            ideas = _generate_growth_ideas(regime, count)
            
            if ideas:
                table = Table(title=f"Aggressive Ideas (Regime: {regime})")
                table.add_column("Type", style="cyan")
                table.add_column("Ticker")
                table.add_column("Action")
                table.add_column("Rationale")
                
                for idea in ideas[:count]:
                    table.add_row(
                        idea.get("type", ""),
                        idea.get("ticker", ""),
                        idea.get("action", ""),
                        idea.get("rationale", "")[:50],
                    )
                console.print(table)
            else:
                console.print("[yellow]No aggressive ideas generated[/yellow]")
        
        else:  # balanced
            console.print("[bold]Balanced Ideas[/bold]\n")
            
            # Show both defensive and growth
            from ai_options_trader.utils.regimes import get_current_macro_regime
            regime_info = get_current_macro_regime(settings)
            regime = regime_info.get("regime", "UNKNOWN")
            
            console.print(f"[dim]Current regime: {regime}[/dim]\n")
            
            # Simplified balanced recommendation
            recommendations = [
                {"action": "HEDGE", "suggestion": "Consider VIX calls or put spreads for tail protection"},
                {"action": "INCOME", "suggestion": "Covered calls on long positions for premium"},
                {"action": "GROWTH", "suggestion": "Look at sector ETFs aligned with regime"},
            ]
            
            for rec in recommendations:
                console.print(f"[cyan]{rec['action']}:[/cyan] {rec['suggestion']}")
    
    @app.command("run")
    def run(
        mode: str = typer.Option("scan", "--mode", "-m", help="scan|execute"),
        strategy: str = typer.Option("balanced", "--strategy", "-s", help="defensive|balanced|aggressive"),
    ):
        """
        Full portfolio workflow: analyze, generate ideas, optionally execute.
        
        Modes:
            scan: Analysis only, no trading (default)
            execute: May execute trades after confirmation
        
        Examples:
            lox run
            lox run --mode execute --strategy defensive
        """
        console = Console()
        
        console.print(Panel(
            f"[bold]Lox Portfolio Workflow[/bold]\n\n"
            f"Mode: {mode}\n"
            f"Strategy: {strategy}",
            expand=False,
        ))
        
        # Step 1: Status
        console.print("\n[bold cyan]Step 1: Portfolio Status[/bold cyan]")
        status(verbose=False)
        
        # Step 2: Quick analysis
        console.print("\n[bold cyan]Step 2: Risk Analysis[/bold cyan]")
        analyze(depth="quick")
        
        # Step 3: Suggestions
        console.print("\n[bold cyan]Step 3: Trade Suggestions[/bold cyan]")
        suggest(style=strategy, count=3)
        
        if mode == "execute":
            console.print("\n[yellow]Execute mode: Review ideas above and use specific commands to trade[/yellow]")
            console.print("[dim]Examples:[/dim]")
            console.print("  lox options pick --ticker SPY --want put")
            console.print("  lox account buy-shares --ticker SQQQ")
