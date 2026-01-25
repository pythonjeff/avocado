"""
Simplified options scanning CLI commands.

Clean, modular implementation using:
- options/scanner.py for filtering logic
- utils/formatting.py for display
- utils/occ.py for symbol parsing

Author: Lox Capital Research
"""
from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from ai_options_trader.config import load_settings
from ai_options_trader.data.alpaca import make_clients, fetch_option_chain
from ai_options_trader.options.scanner import (
    OptionType,
    OptionContract,
    ScanFilter,
    scan_options,
    rank_by_delta_theta,
    parse_chain_to_contracts,
)
from ai_options_trader.utils.formatting import (
    fmt_usd,
    fmt_pct,
    fmt_delta,
    fmt_theta,
    fmt_iv,
    truncate,
)


def register_scan_commands(app: typer.Typer) -> None:
    """Register simplified scan commands to the options app."""
    
    @app.command("chain")
    def options_chain(
        ticker: str = typer.Option(..., "--ticker", "-t", help="Underlying symbol"),
        option_type: str = typer.Option("both", "--type", help="call|put|both"),
        min_dte: int = typer.Option(7, "--min-dte", help="Minimum days to expiry"),
        max_dte: int = typer.Option(90, "--max-dte", help="Maximum days to expiry"),
        show: int = typer.Option(25, "--show", "-n", help="Number of contracts to display"),
        sort_by: str = typer.Option("strike", "--sort", help="strike|dte|delta|premium"),
    ):
        """
        Display option chain for a ticker with clean formatting.
        
        Examples:
            lox options chain --ticker AAPL --type call --max-dte 45
            lox options chain --ticker SPY --sort delta --show 10
        """
        console = Console()
        settings = load_settings()
        _, data = make_clients(settings)
        
        # Normalize option type
        opt_type = _normalize_type(option_type)
        
        console.print(f"\n[bold cyan]{ticker.upper()} Option Chain[/bold cyan]")
        console.print(f"[dim]Type: {opt_type.value} | DTE: {min_dte}-{max_dte}[/dim]\n")
        
        # Fetch and parse chain
        raw_chain = fetch_option_chain(data, ticker, feed=settings.alpaca_options_feed)
        if not raw_chain:
            console.print("[yellow]No options data available[/yellow]")
            return
        
        contracts = parse_chain_to_contracts(raw_chain, ticker.upper())
        console.print(f"[dim]Loaded {len(contracts)} contracts[/dim]")
        
        # Apply filter
        scan_filter = ScanFilter(
            min_dte=min_dte,
            max_dte=max_dte,
            option_type=opt_type,
            require_delta=False,  # Don't require delta for basic view
        )
        
        filtered = scan_options(contracts, scan_filter)
        
        if not filtered:
            console.print("[yellow]No contracts match filters[/yellow]")
            return
        
        # Sort
        filtered = _sort_contracts(filtered, sort_by)
        
        # Display
        _display_chain_table(console, filtered[:show], ticker.upper())
        console.print(f"\n[dim]Showing {min(show, len(filtered))} of {len(filtered)} contracts[/dim]")
    
    @app.command("find")
    def options_find(
        ticker: str = typer.Option(..., "--ticker", "-t", help="Underlying symbol"),
        option_type: str = typer.Option("put", "--type", help="call|put"),
        target_delta: float = typer.Option(0.30, "--delta", help="Target |delta|"),
        max_premium: float = typer.Option(500.0, "--max-premium", help="Max premium (USD)"),
        min_dte: int = typer.Option(30, "--min-dte", help="Minimum days to expiry"),
        max_dte: int = typer.Option(90, "--max-dte", help="Maximum days to expiry"),
        show: int = typer.Option(5, "--show", "-n", help="Number of top picks"),
    ):
        """
        Find best option contract optimized for delta and theta.
        
        Searches for contracts near target delta with minimal theta decay.
        
        Examples:
            lox options find --ticker NVDA --type put --delta 0.25
            lox options find --ticker SPY --max-premium 200 --delta 0.40
        """
        console = Console()
        settings = load_settings()
        _, data = make_clients(settings)
        
        opt_type = OptionType.CALL if option_type.lower() == "call" else OptionType.PUT
        
        console.print(f"\n[bold cyan]Finding {opt_type.value.upper()}s for {ticker.upper()}[/bold cyan]")
        console.print(f"[dim]Target Δ: {target_delta:.2f} | Max premium: ${max_premium:.0f} | DTE: {min_dte}-{max_dte}[/dim]\n")
        
        # Fetch and parse
        raw_chain = fetch_option_chain(data, ticker, feed=settings.alpaca_options_feed)
        if not raw_chain:
            console.print("[yellow]No options data available[/yellow]")
            return
        
        contracts = parse_chain_to_contracts(raw_chain, ticker.upper())
        
        # Filter
        scan_filter = ScanFilter(
            min_dte=min_dte,
            max_dte=max_dte,
            option_type=opt_type,
            max_premium=max_premium,
            require_delta=True,
            max_spread_pct=0.30,
        )
        
        filtered = scan_options(contracts, scan_filter)
        
        if not filtered:
            console.print("[yellow]No contracts match criteria[/yellow]")
            console.print("[dim]Try increasing --max-premium or widening DTE range[/dim]")
            return
        
        # Rank by delta-theta optimization
        ranked = rank_by_delta_theta(filtered, target_delta=target_delta)
        
        if not ranked:
            console.print("[yellow]No contracts with delta available[/yellow]")
            return
        
        # Display top picks
        _display_picks_table(console, ranked[:show], ticker.upper(), target_delta)
        console.print(f"\n[dim]Top {min(show, len(ranked))} of {len(ranked)} matches[/dim]")


def _normalize_type(s: str) -> OptionType:
    """Convert string to OptionType."""
    s = s.strip().lower()
    if s == "call":
        return OptionType.CALL
    elif s == "put":
        return OptionType.PUT
    return OptionType.BOTH


def _sort_contracts(contracts: list[OptionContract], by: str) -> list[OptionContract]:
    """Sort contracts by specified field."""
    if by == "delta":
        return sorted(contracts, key=lambda c: abs(c.delta) if c.delta else 0, reverse=True)
    elif by == "dte":
        return sorted(contracts, key=lambda c: c.dte)
    elif by == "premium":
        return sorted(contracts, key=lambda c: c.premium_usd)
    else:  # strike
        return sorted(contracts, key=lambda c: c.strike)


def _display_chain_table(console: Console, contracts: list[OptionContract], ticker: str) -> None:
    """Display chain in a clean table."""
    table = Table(title=f"{ticker} Options", show_header=True)
    table.add_column("Symbol", style="cyan", max_width=20)
    table.add_column("Type", justify="center")
    table.add_column("Strike", justify="right")
    table.add_column("Expiry", justify="center")
    table.add_column("DTE", justify="right")
    table.add_column("Bid", justify="right")
    table.add_column("Ask", justify="right", style="yellow")
    table.add_column("Δ", justify="right")
    table.add_column("IV", justify="right")
    
    for c in contracts:
        table.add_row(
            truncate(c.symbol, 18),
            c.option_type.value.upper()[:1],
            f"${c.strike:.2f}",
            str(c.expiry),
            str(c.dte),
            fmt_usd(c.bid) if c.bid else "—",
            fmt_usd(c.ask) if c.ask else "—",
            fmt_delta(c.delta) if c.delta else "—",
            fmt_iv(c.iv) if c.iv else "—",
        )
    
    console.print(table)


def _display_picks_table(
    console: Console, 
    contracts: list[OptionContract], 
    ticker: str,
    target_delta: float,
) -> None:
    """Display ranked picks in a clean table."""
    table = Table(title=f"{ticker} Best Picks (target Δ={target_delta:.2f})", show_header=True)
    table.add_column("Rank", justify="right", style="bold")
    table.add_column("Symbol", style="cyan", max_width=20)
    table.add_column("Strike", justify="right")
    table.add_column("Expiry", justify="center")
    table.add_column("DTE", justify="right")
    table.add_column("Premium", justify="right", style="yellow")
    table.add_column("Δ", justify="right")
    table.add_column("Θ", justify="right")
    table.add_column("IV", justify="right")
    
    for i, c in enumerate(contracts, 1):
        table.add_row(
            str(i),
            truncate(c.symbol, 18),
            f"${c.strike:.2f}",
            str(c.expiry),
            str(c.dte),
            f"${c.premium_usd:.0f}",
            fmt_delta(c.delta),
            fmt_theta(c.theta),
            fmt_iv(c.iv) if c.iv else "—",
        )
    
    console.print(table)
