"""
Bubble Finder CLI command.
"""

from __future__ import annotations

import typer
from rich import print
from rich.panel import Panel
from rich.table import Table
from rich.console import Console


def _run_bubble_finder(
    universe: str = "sp500",
    min_score: float = 50,
    top_n: int = 10,
    bubbles_only: bool = False,
    crashes_only: bool = False,
    show_reasons: bool = True,
    json_out: bool = False,
):
    """Run the bubble finder scan."""
    from ai_options_trader.config import load_settings
    from ai_options_trader.scanner.bubble_finder import scan_for_bubbles
    
    console = Console()
    settings = load_settings()
    
    console.print(f"\n[bold cyan]Scanning {universe.upper()} for extreme moves...[/bold cyan]\n")
    
    try:
        result = scan_for_bubbles(
            settings=settings,
            universe=universe,
            min_bubble_score=min_score,
            min_crash_score=-min_score,
            include_news=show_reasons,
            include_earnings=show_reasons,
            top_n=top_n,
        )
    except Exception as e:
        console.print(f"[red]Error scanning: {e}[/red]")
        return
    
    if json_out:
        import json
        output = {
            "scan_date": result.scan_date.isoformat(),
            "universe": result.universe,
            "total_scanned": result.total_scanned,
            "bubbles": [_candidate_to_dict(b) for b in result.bubbles],
            "crashes": [_candidate_to_dict(c) for c in result.crashes],
        }
        print(json.dumps(output, indent=2))
        return
    
    # Summary panel
    summary_lines = [
        f"[bold]Scan Date:[/bold] {result.scan_date}",
        f"[bold]Universe:[/bold] {result.universe.upper()}",
        f"[bold]Stocks Scanned:[/bold] {result.total_scanned}",
        f"[bold]Bubbles Found:[/bold] [red]{result.bubble_count}[/red]",
        f"[bold]Crashes Found:[/bold] [green]{result.crash_count}[/green]",
    ]
    print(Panel("\n".join(summary_lines), title="Bubble Finder Results", expand=False))
    
    # Show bubbles (run-ups)
    if not crashes_only and result.bubbles:
        _show_candidates_table(result.bubbles, "bubble", console, show_reasons)
    
    # Show crashes (run-downs)
    if not bubbles_only and result.crashes:
        _show_candidates_table(result.crashes, "crash", console, show_reasons)
    
    # No results message
    if not result.bubbles and not result.crashes:
        console.print("\n[yellow]No extreme moves found with current thresholds.[/yellow]")
        console.print("[dim]Try lowering --min-score or scanning a different universe.[/dim]")


def _candidate_to_dict(c) -> dict:
    """Convert candidate to dict for JSON output."""
    return {
        "ticker": c.ticker,
        "price": c.price,
        "move_type": c.move_type,
        "bubble_score": c.bubble_score,
        "ret_5d_pct": c.ret_5d_pct,
        "ret_20d_pct": c.ret_20d_pct,
        "ret_60d_pct": c.ret_60d_pct,
        "zscore_20d": c.zscore_20d,
        "rsi_14": c.rsi_14,
        "extension_pct": c.extension_pct,
        "reversion_score": c.reversion_score,
        "reversion_direction": c.reversion_direction,
        "has_recent_earnings": c.has_recent_earnings,
        "earnings_surprise_pct": c.earnings_surprise_pct,
        "has_recent_news": c.has_recent_news,
        "news_sentiment": c.news_sentiment,
        "trade_recommendation": c.trade_recommendation,
        "confidence": c.confidence,
    }


def _show_candidates_table(candidates: list, move_type: str, console: Console, show_reasons: bool):
    """Display candidates in a rich table."""
    
    if move_type == "bubble":
        title = "🫧 BUBBLE CANDIDATES (Run-Ups) 🫧"
        title_color = "red"
        score_color = "red"
    else:
        title = "📉 CRASH CANDIDATES (Run-Downs) 📉"
        title_color = "green"
        score_color = "green"
    
    # Main metrics table
    table = Table(title=f"[bold {title_color}]{title}[/bold {title_color}]", expand=False)
    
    table.add_column("Ticker", style="bold")
    table.add_column("Price", justify="right")
    table.add_column("Bubble\nScore", justify="right")
    table.add_column("20d\nReturn", justify="right")
    table.add_column("60d\nReturn", justify="right")
    table.add_column("Z-Score\n(20d)", justify="right")
    table.add_column("RSI", justify="right")
    table.add_column("From\n200MA", justify="right")
    table.add_column("Reversion\nProb", justify="right")
    
    for c in candidates:
        # Color coding
        if abs(c.bubble_score) >= 70:
            score_style = f"bold {score_color}"
        elif abs(c.bubble_score) >= 50:
            score_style = score_color
        else:
            score_style = "dim"
        
        rsi_style = "red" if c.rsi_14 > 70 else "green" if c.rsi_14 < 30 else "white"
        
        ret_20d_style = "red" if c.ret_20d_pct > 0 else "green"
        ret_60d_style = "red" if c.ret_60d_pct > 0 else "green"
        
        reversion_style = "green" if c.reversion_score >= 70 else "yellow" if c.reversion_score >= 50 else "dim"
        
        # Format RSI without markup if neutral
        rsi_str = f"[{rsi_style}]{c.rsi_14:.0f}[/{rsi_style}]" if rsi_style != "white" else f"{c.rsi_14:.0f}"
        
        table.add_row(
            c.ticker,
            f"${c.price:.2f}",
            f"[{score_style}]{c.bubble_score:+.0f}[/{score_style}]",
            f"[{ret_20d_style}]{c.ret_20d_pct:+.1f}%[/{ret_20d_style}]",
            f"[{ret_60d_style}]{c.ret_60d_pct:+.1f}%[/{ret_60d_style}]",
            f"{c.zscore_20d:+.1f}σ",
            rsi_str,
            f"{c.extension_pct:+.0f}%",
            f"[{reversion_style}]{c.reversion_score:.0f}%[/{reversion_style}]",
        )
    
    print()
    print(table)
    
    # Detailed analysis for each candidate
    if show_reasons:
        print()
        _show_detailed_analysis(candidates, move_type)


def _show_detailed_analysis(candidates: list, move_type: str):
    """Show detailed analysis for each candidate."""
    
    lines = []
    
    for i, c in enumerate(candidates[:5], 1):  # Top 5 with details
        lines.append(f"[bold]{i}. {c.ticker}[/bold] - ${c.price:.2f}")
        lines.append("")
        
        # Move summary
        if move_type == "bubble":
            lines.append(f"   [red]▲ UP {c.ret_20d_pct:+.1f}% (20d) | {c.ret_60d_pct:+.1f}% (60d)[/red]")
        else:
            lines.append(f"   [green]▼ DOWN {c.ret_20d_pct:+.1f}% (20d) | {c.ret_60d_pct:+.1f}% (60d)[/green]")
        
        lines.append(f"   Bubble Score: {c.bubble_score:+.0f} | Z-Score: {c.zscore_20d:+.1f}σ | RSI: {c.rsi_14:.0f}")
        lines.append("")
        
        # Reason analysis
        lines.append("   [bold]Possible Reasons:[/bold]")
        
        if c.has_recent_earnings:
            surprise = f" ({c.earnings_surprise_pct:+.1f}% surprise)" if c.earnings_surprise_pct else ""
            lines.append(f"   • Recent earnings{surprise}")
        
        if c.has_recent_news:
            sentiment = f" [{c.news_sentiment}]" if c.news_sentiment else ""
            lines.append(f"   • News activity{sentiment}")
        
        if not c.has_recent_earnings and not c.has_recent_news:
            if abs(c.zscore_20d) > 2:
                lines.append("   • Technical/momentum driven (no clear catalyst)")
            else:
                lines.append("   • Sector rotation or macro factors")
        
        lines.append("")
        
        # Reversion analysis
        lines.append("   [bold]Reversion Analysis:[/bold]")
        
        if c.reversion_score >= 70:
            lines.append(f"   [green]★★★ HIGH probability ({c.reversion_score:.0f}%) of {c.reversion_direction} reversion[/green]")
        elif c.reversion_score >= 50:
            lines.append(f"   [yellow]★★ MODERATE probability ({c.reversion_score:.0f}%) of {c.reversion_direction} reversion[/yellow]")
        else:
            lines.append(f"   [dim]★ LOW probability ({c.reversion_score:.0f}%) - move may continue[/dim]")
        
        # Trade recommendation
        if c.trade_recommendation:
            if "STRONG" in c.trade_recommendation:
                rec_style = "bold green"
            elif "MODERATE" in c.trade_recommendation:
                rec_style = "yellow"
            else:
                rec_style = "dim"
            lines.append(f"   [{rec_style}]→ {c.trade_recommendation} (Confidence: {c.confidence:.0f}%)[/{rec_style}]")
        
        lines.append("")
        lines.append("   " + "─" * 50)
        lines.append("")
    
    print(Panel("\n".join(lines), title="Detailed Analysis", expand=False))


def register(labs_app: typer.Typer) -> None:
    """Register bubble finder commands."""
    
    @labs_app.command("bubble-finder")
    def bubble_finder(
        universe: str = typer.Option("mega", "--universe", "-u", help="Universe to scan: sp500, etfs, mega, tech, or comma-separated tickers"),
        min_score: float = typer.Option(50, "--min-score", "-m", help="Minimum bubble/crash score (0-100)"),
        top_n: int = typer.Option(10, "--top", "-n", help="Number of results to show"),
        bubbles_only: bool = typer.Option(False, "--bubbles", help="Show only bubbles (run-ups)"),
        crashes_only: bool = typer.Option(False, "--crashes", help="Show only crashes (run-downs)"),
        no_reasons: bool = typer.Option(False, "--no-reasons", help="Skip news/earnings lookup (faster)"),
        json_out: bool = typer.Option(False, "--json", help="Output as JSON"),
    ):
        """
        Find stocks with extreme run-ups (bubbles) or run-downs (crashes).
        
        Analyzes price action, z-scores, and technicals to identify
        candidates for mean reversion trades.
        
        Examples:
            lox labs bubble-finder                    # Scan mega-caps
            lox labs bubble-finder -u sp500           # Scan S&P 500
            lox labs bubble-finder -u etfs --bubbles  # ETF bubbles only
            lox labs bubble-finder -u AAPL,NVDA,TSLA  # Custom tickers
        """
        _run_bubble_finder(
            universe=universe,
            min_score=min_score,
            top_n=top_n,
            bubbles_only=bubbles_only,
            crashes_only=crashes_only,
            show_reasons=not no_reasons,
            json_out=json_out,
        )
