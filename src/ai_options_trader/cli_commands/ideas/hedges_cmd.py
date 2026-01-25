"""
Simplified hedge recommendation command.

Shows 2-3 positions that would complement your portfolio in the current regime.
"""
from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from ai_options_trader.utils.settings import safe_load_settings
from ai_options_trader.utils.regimes import get_current_macro_regime


def register(labs_app: typer.Typer) -> None:
    @labs_app.command("hedge")
    def hedge_ideas(
        max_ideas: int = typer.Option(3, "--max", "-n", help="Max hedge ideas to show"),
        budget: float = typer.Option(500.0, "--budget", "-b", help="Max $ to allocate"),
    ):
        """
        Defensive trade ideas: hedges, protection, tail risk.
        
        Shows regime-aware hedges that complement your portfolio.
        Can be specific picks or directional guidance.
        
        Example:
            lox labs hedge
            lox labs hedge --budget 1000 --max 5
        """
        settings = safe_load_settings()
        c = Console()
        
        c.print("\n[bold cyan]═══ Lox Hedge Recommendations ═══[/bold cyan]\n")
        
        # === 1. SHOW CURRENT REGIME ===
        
        c.print("[bold]Current Regime:[/bold]")
        regimes = get_current_macro_regime(settings, start="2020-01-01")
        
        macro_regime = regimes["macro_regime"]
        liq_state = regimes["liquidity_state"]
        
        regime_table = Table(show_header=False, box=None, padding=(0, 1))
        regime_table.add_column("Category", style="cyan", width=12)
        regime_table.add_column("Status")
        
        regime_table.add_row("Macro", f"{macro_regime.name}")
        
        # Liquidity status
        rrp_val = liq_state.inputs.on_rrp_usd_bn / 1000.0 if liq_state.inputs.on_rrp_usd_bn else None
        if rrp_val and rrp_val < 50:
            liq_status = "FRAGILE (RRP depleted)"
        else:
            liq_status = "ORDERLY"
        regime_table.add_row("Liquidity", liq_status)
        
        # VIX level
        macro_state = regimes["macro_state"]
        if macro_state.inputs.vix:
            vix = macro_state.inputs.vix
            if vix < 15:
                vol_status = f"LOW (VIX {vix:.1f} - hedges cheap)"
            elif vix < 25:
                vol_status = f"NORMAL (VIX {vix:.1f})"
            else:
                vol_status = f"ELEVATED (VIX {vix:.1f} - hedges expensive)"
            regime_table.add_row("Volatility", vol_status)
        
        c.print(Panel(regime_table, border_style="cyan"))
        
        # === 2. ANALYZE PORTFOLIO GAPS ===
        
        c.print("\n[bold]Your Portfolio:[/bold]")
        
        # Fetch positions from Alpaca
        from ai_options_trader.data.alpaca import make_clients
        trading, _ = make_clients(settings)
        
        try:
            positions = trading.get_all_positions()
            
            # Categorize positions
            equity_long = []
            equity_short = []
            puts = []
            calls = []
            vol_exposure = []
            
            for p in positions:
                symbol = str(getattr(p, "symbol", ""))
                qty = float(getattr(p, "qty", 0.0))
                
                if "VIX" in symbol.upper():
                    vol_exposure.append(symbol)
                elif "P" in symbol and len(symbol) > 10:  # Put option
                    puts.append(symbol)
                elif "C" in symbol and len(symbol) > 10:  # Call option
                    calls.append(symbol)
                elif qty > 0:
                    equity_long.append(symbol)
                else:
                    equity_short.append(symbol)
            
            # Show summary
            pos_table = Table(show_header=False, box=None, padding=(0, 1))
            pos_table.add_column("Category", style="dim", width=15)
            pos_table.add_column("Count")
            
            pos_table.add_row("Long equity", f"{len(equity_long)} positions")
            pos_table.add_row("Short equity", f"{len(equity_short)} positions")
            pos_table.add_row("Put hedges", f"{len(puts)} contracts")
            pos_table.add_row("Call hedges", f"{len(calls)} contracts")
            pos_table.add_row("Vol exposure", f"{len(vol_exposure)} positions")
            
            c.print(pos_table)
            
            # === 3. CALCULATE NET EXPOSURE ===
            
            c.print("\n[bold]Net Exposure:[/bold]")
            
            # Simple heuristic: puts are short, calls/shares are long, vol is special
            net_long = len(equity_long) + len(calls)
            net_short = len(puts)
            net_vol = len(vol_exposure)
            
            exposure_table = Table(show_header=False, box=None, padding=(0, 1))
            exposure_table.add_column("Category", style="dim", width=15)
            exposure_table.add_column("Net")
            
            if net_short > net_long + 1:
                net_bias = "NET SHORT (over-hedged)"
                bias_color = "yellow"
            elif net_long > net_short + 1:
                net_bias = "NET LONG (under-hedged)"
                bias_color = "yellow"
            else:
                net_bias = "BALANCED"
                bias_color = "green"
            
            exposure_table.add_row("Long exposure", f"{net_long} positions")
            exposure_table.add_row("Short exposure", f"{net_short} positions")
            exposure_table.add_row("Vol exposure", f"{net_vol} positions")
            exposure_table.add_row("Net bias", f"[{bias_color}]{net_bias}[/{bias_color}]")
            
            c.print(exposure_table)
            
            # Identify specific offsetting needs
            offsetting_needs = []
            for p in positions:
                symbol = str(getattr(p, "symbol", ""))
                # Extract tickers from puts to suggest inverse
                if "P" in symbol and len(symbol) > 10:
                    underlying = symbol[:symbol.index("2")] if "2" in symbol else symbol[:4]
                    offsetting_needs.append(f"Long {underlying} (to offset {symbol[:15]}... put)")
            
            if net_short > net_long + 1:
                c.print(f"\n[yellow]Portfolio is over-hedged ({net_short} puts vs {net_long} longs)[/yellow]")
                c.print("[yellow]Suggestion: Add long exposure or trim puts[/yellow]")
            elif net_long > net_short + 1:
                c.print(f"\n[yellow]Portfolio is under-hedged ({net_long} longs vs {net_short} puts)[/yellow]")
                c.print("[yellow]Suggestion: Add downside protection[/yellow]")
            else:
                c.print("\n[green]✓ Portfolio exposure is balanced[/green]")
        
        except Exception as e:
            c.print(f"[yellow]Could not fetch positions: {e}[/yellow]")
            # Set defaults for error case
            positions = []
            equity_long = []
            equity_short = []
            puts = []
            calls = []
            vol_exposure = []
            net_long = 0
            net_short = 0
            net_vol = 0
        
        # === 4. GENERATE OFFSETTING IDEAS ===
        
        c.print("\n[bold cyan]═══ Offsetting Positions (Balance Portfolio) ═══[/bold cyan]\n")
        
        ideas = _generate_offsetting_ideas(
            positions=positions,
            net_long=net_long,
            net_short=net_short,
            vix=macro_state.inputs.vix,
            budget=budget,
            max_ideas=max_ideas,
        )
        
        if not ideas:
            c.print("[yellow]No hedge ideas for current regime[/yellow]")
            return
        
        # Show ideas as table
        ideas_table = Table(show_header=True)
        ideas_table.add_column("#", style="cyan", width=3)
        ideas_table.add_column("Trade", style="bold")
        ideas_table.add_column("Why", style="dim")
        ideas_table.add_column("Payoff If", style="green")
        ideas_table.add_column("Cost", justify="right")
        
        for i, idea in enumerate(ideas, 1):
            ideas_table.add_row(
                str(i),
                idea["trade"],
                idea["why"],
                idea["payoff"],
                idea["cost"],
            )
        
        c.print(ideas_table)
        
        # === 5. EXECUTION PROMPT ===
        
        c.print("\n[dim]To execute:[/dim]")
        c.print("[dim]  • Run: lox options recommend --ticker <TICKER> --direction bearish[/dim]")
        c.print("[dim]  • Or manually enter trades in your broker[/dim]")
    
    
    @labs_app.command("grow")
    def growth_ideas(
        max_ideas: int = typer.Option(3, "--max", "-n", help="Max growth ideas to show"),
        budget: float = typer.Option(500.0, "--budget", "-b", help="Max $ to allocate"),
    ):
        """
        Offensive trade ideas: growth, momentum, convexity.
        
        Shows regime-aware opportunities for portfolio expansion.
        Can be specific picks or directional guidance.
        
        Example:
            lox labs grow
            lox labs grow --budget 1000 --max 5
        """
        settings = safe_load_settings()
        c = Console()
        
        c.print("\n[bold green]═══ Lox Growth Opportunities ═══[/bold green]\n")
        
        # === 1. SHOW CURRENT REGIME ===
        
        c.print("[bold]Current Regime:[/bold]")
        regimes = get_current_macro_regime(settings, start="2020-01-01")
        
        macro_regime = regimes["macro_regime"]
        liq_state = regimes["liquidity_state"]
        macro_state = regimes["macro_state"]
        
        regime_table = Table(show_header=False, box=None, padding=(0, 1))
        regime_table.add_column("Category", style="cyan", width=12)
        regime_table.add_column("Status")
        
        regime_table.add_row("Macro", f"{macro_regime.name}")
        
        # Liquidity status
        rrp_val = liq_state.inputs.on_rrp_usd_bn / 1000.0 if liq_state.inputs.on_rrp_usd_bn else None
        if rrp_val and rrp_val < 50:
            liq_status = "FRAGILE (RRP depleted)"
        else:
            liq_status = "ORDERLY"
        regime_table.add_row("Liquidity", liq_status)
        
        # VIX level
        if macro_state.inputs.vix:
            vix = macro_state.inputs.vix
            if vix < 15:
                vol_status = f"LOW (VIX {vix:.1f} - calm markets)"
            elif vix < 25:
                vol_status = f"NORMAL (VIX {vix:.1f})"
            else:
                vol_status = f"ELEVATED (VIX {vix:.1f} - risk-off)"
            regime_table.add_row("Volatility", vol_status)
        
        c.print(Panel(regime_table, border_style="green"))
        
        # === 2. GENERATE GROWTH IDEAS ===
        
        c.print("\n[bold green]═══ Recommended Opportunities ═══[/bold green]\n")
        
        ideas = _generate_growth_ideas(
            macro_regime=macro_regime.name,
            vix=macro_state.inputs.vix,
            budget=budget,
            max_ideas=max_ideas,
        )
        
        if not ideas:
            c.print("[yellow]No growth ideas for current regime - consider hedging[/yellow]")
            return
        
        # Show ideas as table
        ideas_table = Table(show_header=True)
        ideas_table.add_column("#", style="cyan", width=3)
        ideas_table.add_column("Trade", style="bold")
        ideas_table.add_column("Why", style="dim")
        ideas_table.add_column("Target", style="green")
        ideas_table.add_column("Allocation", justify="right")
        
        for i, idea in enumerate(ideas, 1):
            ideas_table.add_row(
                str(i),
                idea["trade"],
                idea["why"],
                idea["target"],
                idea["allocation"],
            )
        
        c.print(ideas_table)
        
        # === 3. EXECUTION PROMPT ===
        
        c.print("\n[dim]To execute:[/dim]")
        c.print("[dim]  • Run: lox options recommend --ticker <TICKER> --direction bullish[/dim]")
        c.print("[dim]  • Or manually enter trades in your broker[/dim]")


def _generate_offsetting_ideas(
    positions: list,
    net_long: int,
    net_short: int,
    vix: float | None,
    budget: float,
    max_ideas: int,
) -> list[dict]:
    """
    Generate offsetting positions to balance portfolio.
    
    Hedge fund approach: If you have puts, suggest calls. If you have calls, suggest puts.
    If you're net short, add long. If you're net long, add protection.
    """
    
    ideas = []
    
    # Parse positions to find specific underlyings
    put_underlyings = set()
    call_underlyings = set()
    equity_tickers = set()
    
    for p in positions:
        symbol = str(getattr(p, "symbol", ""))
        qty = float(getattr(p, "qty", 0.0))
        
        if "P" in symbol and len(symbol) > 10:  # Put option
            underlying = symbol[:symbol.index("2")] if "2" in symbol else symbol[:4]
            put_underlyings.add(underlying)
        elif "C" in symbol and len(symbol) > 10:  # Call option
            underlying = symbol[:symbol.index("2")] if "2" in symbol else symbol[:4]
            call_underlyings.add(underlying)
        elif qty > 0:
            equity_tickers.add(symbol)
    
    # === CASE 1: NET SHORT (over-hedged with puts) ===
    # Suggest LONG positions to offset puts
    
    if net_short > net_long + 1:
        # Suggest offsetting the specific puts they have
        if put_underlyings:
            first_put = list(put_underlyings)[0]
            ideas.append({
                "trade": f"{first_put} 3M calls (ATM or slight OTM)",
                "why": f"OFFSET: You have {first_put} puts → add calls to balance",
                "payoff": f"{first_put} rallies → calls offset put losses",
                "cost": f"~${budget * 0.35:.0f} (35% of budget)",
            })
        
        # Suggest broad market long to offset general short bias
        ideas.append({
            "trade": "SPY shares or SPY 3M calls (ATM)",
            "why": "OFFSET: Portfolio is net short → add long exposure",
            "payoff": "Market rallies → offsets put losses",
            "cost": f"~${budget * 0.30:.0f} (30% of budget)",
        })
        
        # Suggest trimming existing puts
        if put_underlyings:
            second_put = list(put_underlyings)[1] if len(put_underlyings) > 1 else list(put_underlyings)[0]
            ideas.append({
                "trade": f"Trim {second_put} puts by 30-50%",
                "why": "REDUCE: Over-hedged → reduce short exposure",
                "payoff": "Preserve capital, reduce theta drag",
                "cost": "$0 (reduces exposure)",
            })
    
    # === CASE 2: NET LONG (under-hedged) ===
    # Suggest SHORT/protection positions to offset longs
    
    elif net_long > net_short + 1:
        # Suggest offsetting specific equity longs
        if equity_tickers:
            first_ticker = list(equity_tickers)[0]
            ideas.append({
                "trade": f"{first_ticker} 3M puts (10% OTM)",
                "why": f"OFFSET: You're long {first_ticker} → add puts to protect",
                "payoff": f"{first_ticker} drops → puts offset equity losses",
                "cost": f"~${budget * 0.30:.0f} (30% of budget)",
            })
        
        # Suggest calls turning into call spreads or offsetting with puts
        if call_underlyings:
            first_call = list(call_underlyings)[0]
            ideas.append({
                "trade": f"{first_call} put spreads (buy ATM, sell 10% OTM)",
                "why": f"OFFSET: You have {first_call} calls → add put spreads for balance",
                "payoff": f"{first_call} drops → spreads offset call losses",
                "cost": f"~${budget * 0.25:.0f} (25% of budget)",
            })
        
        # Broad market protection
        ideas.append({
            "trade": "SPY 3M puts (10% OTM)",
            "why": "OFFSET: Portfolio is net long → add broad protection",
            "payoff": "Market correction → puts offset equity losses",
            "cost": f"~${budget * 0.30:.0f} (30% of budget)",
        })
        
        # VIX hedge if vol is cheap
        if vix and vix < 18:
            ideas.append({
                "trade": "VIX 1M calls (strike ~VIX+5)",
                "why": "OFFSET: Vol is cheap → add convex protection",
                "payoff": "Vol spike → calls offset equity drawdown",
                "cost": f"~${budget * 0.15:.0f} (15% of budget)",
            })
    
    # === CASE 3: BALANCED PORTFOLIO ===
    # Suggest tactical adjustments based on specific positions
    
    else:
        ideas.append({
            "trade": "Portfolio is balanced ✓",
            "why": "Equal long/short exposure → no major offsetting needed",
            "payoff": "Maintain balance, tactical adjustments only",
            "cost": "$0 (no action)",
        })
        
        # Suggest tactical pair trades
        if put_underlyings and equity_tickers:
            ideas.append({
                "trade": "Pair trade: long/short same sector",
                "why": "NEUTRAL: Balance within sectors to reduce beta",
                "payoff": "Market neutral → profit from relative moves",
                "cost": f"~${budget * 0.3:.0f} (30% of budget)",
            })
        
        # Suggest vol adjustment if needed
        if vix and vix < 15:
            ideas.append({
                "trade": "Add small VIX hedge (5-10% of portfolio)",
                "why": "INSURANCE: Vol is very cheap (VIX <15)",
                "payoff": "Vol spike → insurance pays off",
                "cost": f"~${budget * 0.10:.0f} (10% of budget)",
            })
        elif vix and vix > 25:
            ideas.append({
                "trade": "Trim vol exposure by 20-30%",
                "why": "TRIM: Vol is expensive (VIX >25)",
                "payoff": "Lock in gains, reduce premium decay",
                "cost": "$0 (reduces exposure)",
            })
    
    return ideas[:max_ideas]


def _generate_growth_ideas(
    macro_regime: str,
    vix: float | None,
    budget: float,
    max_ideas: int,
) -> list[dict]:
    """Generate regime-aware growth/offensive trade ideas."""
    
    ideas = []
    
    # === STAGFLATION REGIME ===
    
    if macro_regime == "STAGFLATION":
        ideas.append({
            "trade": "Sector rotation → commodities",
            "why": "Inflation regime favors hard assets",
            "target": "Look at: GLD, GLDM, DBC, USO",
            "allocation": f"~${budget * 0.3:.0f} (30%)",
        })
        
        ideas.append({
            "trade": "Defensive sectors",
            "why": "Weak growth → utilities, consumer staples hold up",
            "target": "Look at: XLU, XLP, VDC",
            "allocation": f"~${budget * 0.25:.0f} (25%)",
        })
        
        ideas.append({
            "trade": "Avoid growth / stay small",
            "why": "High inflation + weak growth = bad for growth",
            "target": "No new tech/growth exposure",
            "allocation": f"~${0:.0f} (trim existing)",
        })
    
    # === GOLDILOCKS REGIME ===
    
    elif macro_regime == "GOLDILOCKS":
        ideas.append({
            "trade": "Tech / growth equities",
            "why": "Low inflation + strong growth = multiple expansion",
            "target": "Look at: QQQ, XLK, ARKK, SMH (semiconductors)",
            "allocation": f"~${budget * 0.4:.0f} (40%)",
        })
        
        ideas.append({
            "trade": "Sell short-dated premium",
            "why": "Low vol = high theta, collect premium",
            "target": "Sell covered calls on existing longs",
            "allocation": f"~${budget * 0.2:.0f} (20%)",
        })
        
        if vix and vix < 15:
            ideas.append({
                "trade": "Long-dated calls on quality names",
                "why": "Vol is cheap, extend duration for leverage",
                "target": "SPY, QQQ 6M calls (ATM or slightly OTM)",
                "allocation": f"~${budget * 0.25:.0f} (25%)",
            })
    
    # === DISINFLATIONARY REGIME ===
    
    elif macro_regime == "DISINFLATIONARY":
        ideas.append({
            "trade": "Long duration bonds",
            "why": "Disinflation → bond rally",
            "target": "TLT, EDV (20Y+ treasuries)",
            "allocation": f"~${budget * 0.3:.0f} (30%)",
        })
        
        ideas.append({
            "trade": "Quality growth at a discount",
            "why": "Disinflation often = recession fears → buying opportunity",
            "target": "Look at: MSFT, GOOGL, AAPL if down 15%+",
            "allocation": f"~${budget * 0.3:.0f} (30%)",
        })
        
        ideas.append({
            "trade": "Avoid cyclicals",
            "why": "Weak growth = cyclicals underperform",
            "target": "Stay away from: XLI, XLB, industrials",
            "allocation": f"~${0:.0f} (avoid)",
        })
    
    # === INFLATIONARY REGIME ===
    
    elif macro_regime == "INFLATIONARY":
        ideas.append({
            "trade": "Energy / commodities",
            "why": "Inflation → pricing power matters",
            "target": "Look at: XLE, USO, DBC, commodity producers",
            "allocation": f"~${budget * 0.35:.0f} (35%)",
        })
        
        ideas.append({
            "trade": "Gold / inflation hedges",
            "why": "Persistent inflation = gold strength",
            "target": "GLDM, GLD, IAU",
            "allocation": f"~${budget * 0.25:.0f} (25%)",
        })
        
        ideas.append({
            "trade": "Short bonds tactically",
            "why": "Inflation → rates up → bonds down",
            "target": "TBT (2x short 20Y+), or TLT puts",
            "allocation": f"~${budget * 0.2:.0f} (20%)",
        })
    
    # === DEFAULT / NEUTRAL ===
    
    else:
        ideas.append({
            "trade": "Balanced equity exposure",
            "why": "No clear regime → stay diversified",
            "target": "Look at: SPY, VOO, VTI (broad market)",
            "allocation": f"~${budget * 0.4:.0f} (40%)",
        })
        
        ideas.append({
            "trade": "Factor rotation",
            "why": "Unclear regime → use factor momentum",
            "target": "Look at: MTUM (momentum), QUAL (quality), USMV (low vol)",
            "allocation": f"~${budget * 0.3:.0f} (30%)",
        })
        
        if vix and vix < 18:
            ideas.append({
                "trade": "Strategic call spreads",
                "why": "Vol below median = cheap leverage",
                "target": "SPY 3M call spreads (buy ATM, sell 10% OTM)",
                "allocation": f"~${budget * 0.2:.0f} (20%)",
            })
    
    return ideas[:max_ideas]
