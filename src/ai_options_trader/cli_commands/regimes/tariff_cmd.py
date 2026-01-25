from __future__ import annotations

import pandas as pd
import typer
from rich import print
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from ai_options_trader.config import load_settings

console = Console()


def _run_tariff_snapshot(
    *,
    basket: str = "import_retail_apparel",
    start: str = "2011-01-01",
    benchmark: str = "XLY",
    refresh: bool = False,
    llm: bool = False,
    features: bool = False,
    json_out: bool = False,
) -> None:
    """Shared implementation for tariff snapshot."""
    from ai_options_trader.cli_commands.shared.labs_utils import handle_output_flags
    from ai_options_trader.data.fred import FredClient
    from ai_options_trader.data.market import fetch_equity_daily_closes
    from ai_options_trader.tariff.universe import BASKETS
    from ai_options_trader.tariff.proxies import DEFAULT_COST_PROXY_SERIES
    from ai_options_trader.tariff.signals import build_tariff_regime_state

    settings = load_settings()

    if basket not in BASKETS:
        console.print(f"[red]Unknown basket: {basket}. Choose from: {list(BASKETS.keys())}[/red]")
        return

    universe = BASKETS[basket].tickers

    # --- Cost proxies (FRED) ---
    fred = FredClient(api_key=settings.FRED_API_KEY)

    frames = []
    for col, sid in DEFAULT_COST_PROXY_SERIES.items():
        df = fred.fetch_series(sid, start_date=start, refresh=refresh)
        df = df.rename(columns={"value": col}).set_index("date")
        frames.append(df[[col]])

    cost_df = pd.concat(frames, axis=1).sort_index()
    cost_df = cost_df.resample("D").ffill()

    # --- Equities ---
    symbols = sorted(set(universe + [benchmark]))
    px = fetch_equity_daily_closes(settings=settings, symbols=symbols, start=start, refresh=bool(refresh))
    px = px.sort_index().ffill().dropna(how="all")

    state = build_tariff_regime_state(
        cost_df=cost_df,
        equity_prices=px,
        universe=universe,
        benchmark=benchmark,
        basket_name=basket,
        start_date=start,
    )

    inputs = state.inputs
    
    # Build snapshot data
    snapshot_data = {
        "tariff_regime_score": inputs.tariff_regime_score,
        "is_tariff_regime": inputs.is_tariff_regime,
        "z_cost_pressure": inputs.z_cost_pressure,
        "equity_denial_beta": inputs.equity_denial_beta,
        "z_earnings_fragility": inputs.z_earnings_fragility,
        "basket": state.basket,
        "benchmark": state.benchmark,
    }

    feature_dict = {
        "tariff_regime_score": inputs.tariff_regime_score,
        "z_cost_pressure": inputs.z_cost_pressure,
        "equity_denial_beta": inputs.equity_denial_beta,
        "z_earnings_fragility": inputs.z_earnings_fragility,
        "is_tariff_regime": 1.0 if inputs.is_tariff_regime else 0.0,
    }

    regime_label = "Tariff Regime ACTIVE" if inputs.is_tariff_regime else "Tariff Regime Inactive"

    # Handle --features and --json flags
    if handle_output_flags(
        domain="tariff",
        snapshot=snapshot_data,
        features=feature_dict,
        regime=regime_label,
        regime_description=f"Score: {inputs.tariff_regime_score:.2f}",
        asof=state.asof,
        output_json=json_out,
        output_features=features,
    ):
        return

    if llm:
        _llm_tariff_analysis(state, settings)
    else:
        in_regime = "✅ YES" if inputs.is_tariff_regime else "❌ NO"
        
        console.print()
        console.print(Panel(
            f"[bold]Basket:[/bold] {state.basket}\n"
            f"[bold]Universe:[/bold] {', '.join(state.universe)}\n"
            f"[bold]Benchmark:[/bold] {state.benchmark}\n"
            f"[bold]As of:[/bold] {state.asof}\n\n"
            f"[bold cyan]Tariff Regime Score:[/bold cyan] {inputs.tariff_regime_score:.2f}\n"
            f"[bold]In Tariff Regime:[/bold] {in_regime}\n\n"
            f"[dim]Components:[/dim]\n"
            f"  Cost Pressure (z): {inputs.z_cost_pressure:+.2f}\n"
            f"  Equity Denial Beta: {inputs.equity_denial_beta:.4f}\n"
            f"  Earnings Fragility (z): {inputs.z_earnings_fragility:.2f}",
            title="Tariff Regime Snapshot",
            border_style="yellow"
        ))


def register(tariff_app: typer.Typer) -> None:
    # Default callback so `lox labs tariff --llm` works without `snapshot`
    @tariff_app.callback(invoke_without_command=True)
    def tariff_default(
        ctx: typer.Context,
        llm: bool = typer.Option(False, "--llm", help="Get LLM analysis with real-time data"),
        features: bool = typer.Option(False, "--features", help="Export ML-ready feature vector (JSON)"),
        json_out: bool = typer.Option(False, "--json", help="Machine-readable JSON output"),
    ):
        """Tariff / cost-push regime signals"""
        if ctx.invoked_subcommand is None:
            # Run default snapshot with flags
            _run_tariff_snapshot(llm=llm, features=features, json_out=json_out)

    @tariff_app.command("baskets")
    def tariff_baskets():
        """List available tariff baskets."""
        from ai_options_trader.tariff.universe import BASKETS

        for name, b in BASKETS.items():
            print(f"- {name}: {b.description} (tickers={','.join(b.tickers)})")

    @tariff_app.command("etfs")
    def tariff_etfs(
        exposure: str = typer.Option(None, "--exposure", "-e", help="Filter by exposure level: high, medium, low"),
        direction: str = typer.Option(None, "--direction", "-d", help="Filter by impact direction: hurt, benefit"),
        category: str = typer.Option(None, "--category", "-c", help="Filter by category"),
    ):
        """Screen ETFs by tariff/import duty exposure."""
        from ai_options_trader.tariff.etf_impact import get_all_tariff_etfs, TARIFF_EXPOSED_ETFS

        etfs = get_all_tariff_etfs()
        
        # Apply filters
        if exposure:
            etfs = [e for e in etfs if e.tariff_exposure == exposure.lower()]
        if direction:
            etfs = [e for e in etfs if e.direction == direction.lower()]
        if category:
            etfs = [e for e in etfs if category.lower() in e.category.lower()]
        
        if not etfs:
            console.print("[yellow]No ETFs match the filters.[/yellow]")
            return
        
        # Build table
        table = Table(title="ETFs by Tariff/Import Duty Exposure", show_header=True, header_style="bold")
        table.add_column("Ticker", style="cyan", width=8)
        table.add_column("Name", width=30)
        table.add_column("Category", width=15)
        table.add_column("Exposure", justify="center", width=10)
        table.add_column("Impact", justify="center", width=10)
        table.add_column("Rationale", width=50)
        
        for etf in sorted(etfs, key=lambda x: (x.tariff_exposure != "high", x.direction != "hurt", x.ticker)):
            exp_style = {"high": "red bold", "medium": "yellow", "low": "green"}.get(etf.tariff_exposure, "")
            dir_style = {"hurt": "red", "benefit": "green", "mixed": "yellow"}.get(etf.direction, "")
            
            table.add_row(
                etf.ticker,
                etf.name,
                etf.category,
                f"[{exp_style}]{etf.tariff_exposure.upper()}[/{exp_style}]",
                f"[{dir_style}]{etf.direction.upper()}[/{dir_style}]",
                etf.exposure_rationale[:50] + "..." if len(etf.exposure_rationale) > 50 else etf.exposure_rationale,
            )
        
        console.print()
        console.print(table)
        console.print()
        console.print(Panel(
            "[bold]Exposure Levels:[/bold]\n"
            "[red]HIGH[/red] = Direct tariff target or primary import dependency\n"
            "[yellow]MEDIUM[/yellow] = Partial supply chain or secondary exposure\n"
            "[green]LOW[/green] = Limited trade sensitivity\n\n"
            "[bold]Impact Direction:[/bold]\n"
            "[red]HURT[/red] = Negatively impacted by increased duties\n"
            "[green]BENEFIT[/green] = May gain from import protection\n"
            "[yellow]MIXED[/yellow] = Varies by sub-sector",
            title="Legend",
            border_style="blue"
        ))

    @tariff_app.command("screen")
    def tariff_screen(
        refresh: bool = typer.Option(False, "--refresh", help="Refresh price data"),
    ):
        """Screen high-exposure ETFs with current performance metrics."""
        from ai_options_trader.tariff.etf_impact import get_high_exposure_etfs
        from ai_options_trader.data.market import fetch_equity_daily_closes
        
        settings = load_settings()
        etfs = get_high_exposure_etfs()
        tickers = [e.ticker for e in etfs]
        
        console.print("[dim]Loading...[/dim]")
        
        try:
            px = fetch_equity_daily_closes(settings=settings, symbols=tickers, start="2024-01-01", refresh=refresh)
            px = px.sort_index().ffill().dropna(how="all")
        except Exception as e:
            console.print(f"[red]Error fetching prices: {e}[/red]")
            return
        
        # Calculate returns
        table = Table(title="High Tariff Exposure ETFs - Performance Screen", show_header=True, header_style="bold")
        table.add_column("Ticker", style="cyan", width=8)
        table.add_column("Name", width=28)
        table.add_column("Impact", justify="center", width=8)
        table.add_column("Price", justify="right", width=10)
        table.add_column("1W %", justify="right", width=10)
        table.add_column("1M %", justify="right", width=10)
        table.add_column("YTD %", justify="right", width=10)
        
        for etf in etfs:
            if etf.ticker not in px.columns:
                continue
            
            prices = px[etf.ticker].dropna()
            if len(prices) < 30:
                continue
            
            current = prices.iloc[-1]
            
            # 1 week return
            if len(prices) >= 5:
                ret_1w = (current / prices.iloc[-5] - 1) * 100
            else:
                ret_1w = 0
            
            # 1 month return
            if len(prices) >= 21:
                ret_1m = (current / prices.iloc[-21] - 1) * 100
            else:
                ret_1m = 0
            
            # YTD return (from Jan 1 2025)
            ytd_start = prices[prices.index >= "2025-01-01"]
            if len(ytd_start) > 1:
                ret_ytd = (current / ytd_start.iloc[0] - 1) * 100
            else:
                ret_ytd = 0
            
            dir_style = {"hurt": "red", "benefit": "green", "mixed": "yellow"}.get(etf.direction, "")
            
            def fmt_ret(r):
                style = "green" if r > 0 else "red" if r < 0 else ""
                return f"[{style}]{r:+.1f}%[/{style}]" if style else f"{r:+.1f}%"
            
            table.add_row(
                etf.ticker,
                etf.name[:28],
                f"[{dir_style}]{etf.direction.upper()}[/{dir_style}]",
                f"${current:.2f}",
                fmt_ret(ret_1w),
                fmt_ret(ret_1m),
                fmt_ret(ret_ytd),
            )
        
        console.print()
        console.print(table)
        console.print()
        console.print("[dim]Tip: Use 'lox labs tariff etfs --exposure high' for details on each ETF[/dim]")

    @tariff_app.command("ideas")
    def tariff_ideas(
        lookback: int = typer.Option(21, "--lookback", "-l", help="Days to measure performance (default: 21 = 1 month)"),
        max_strike_pct: float = typer.Option(10.0, "--max-strike-pct", help="Max % from current price for strikes"),
        min_days: int = typer.Option(14, "--min-days", help="Min DTE for options"),
        max_days: int = typer.Option(60, "--max-days", help="Max DTE for options"),
        refresh: bool = typer.Option(False, "--refresh", help="Refresh price data"),
    ):
        """
        Generate contrarian options ideas on tariff-exposed ETFs.
        
        Logic: If an ETF moved UP recently → recommend PUTS (mean reversion)
               If an ETF moved DOWN recently → recommend CALLS (bounce play)
        
        Strikes within --max-strike-pct of current price.
        """
        from ai_options_trader.tariff.etf_impact import get_all_tariff_etfs
        from ai_options_trader.data.market import fetch_equity_daily_closes
        from ai_options_trader.data.alpaca import make_clients
        from datetime import datetime, timedelta
        
        settings = load_settings()
        etfs = get_all_tariff_etfs()
        tickers = [e.ticker for e in etfs]
        
        console.print("[dim]Loading...[/dim]")
        
        try:
            px = fetch_equity_daily_closes(settings=settings, symbols=tickers, start="2024-01-01", refresh=refresh)
            px = px.sort_index().ffill().dropna(how="all")
        except Exception as e:
            console.print(f"[red]Error fetching prices: {e}[/red]")
            return
        
        # Calculate returns and identify candidates
        candidates = []
        for etf in etfs:
            if etf.ticker not in px.columns:
                continue
            
            prices = px[etf.ticker].dropna()
            if len(prices) < lookback + 5:
                continue
            
            current = prices.iloc[-1]
            past = prices.iloc[-lookback] if len(prices) >= lookback else prices.iloc[0]
            ret = (current / past - 1) * 100
            
            # Determine direction: opposite of recent move
            if ret > 2:  # Up more than 2% -> recommend puts
                direction = "PUT"
                target_strike = current * (1 - max_strike_pct / 100)
                rationale = f"Up {ret:+.1f}% over {lookback}d → mean reversion play"
            elif ret < -2:  # Down more than 2% -> recommend calls
                direction = "CALL"
                target_strike = current * (1 + max_strike_pct / 100)
                rationale = f"Down {ret:+.1f}% over {lookback}d → bounce play"
            else:
                continue  # Skip if move is too small
            
            candidates.append({
                "etf": etf,
                "price": current,
                "return": ret,
                "direction": direction,
                "target_strike": target_strike,
                "rationale": rationale,
                "abs_return": abs(ret),
            })
        
        if not candidates:
            console.print("[yellow]No strong moves found for contrarian plays.[/yellow]")
            return
        
        # Sort by absolute return (biggest movers first)
        candidates.sort(key=lambda x: x["abs_return"], reverse=True)
        
        # Fetch options for top candidates
        console.print(f"[dim]Scanning options for {min(len(candidates), 10)} candidates...[/dim]")
        
        try:
            trading, _ = make_clients(settings)
        except Exception as e:
            console.print(f"[red]Error connecting to broker: {e}[/red]")
            # Still show candidates without options
            _show_candidates_table(candidates[:10])
            return
        
        # Build results with options data
        results = []
        for c in candidates[:10]:
            ticker = c["etf"].ticker
            try:
                from alpaca.trading.requests import GetOptionContractsRequest
                from alpaca.trading.enums import AssetStatus
                
                # Calculate date range
                now = datetime.now()
                min_exp = (now + timedelta(days=min_days)).strftime("%Y-%m-%d")
                max_exp = (now + timedelta(days=max_days)).strftime("%Y-%m-%d")
                
                req = GetOptionContractsRequest(
                    underlying_symbols=[ticker],
                    status=AssetStatus.ACTIVE,
                    expiration_date_gte=min_exp,
                    expiration_date_lte=max_exp,
                    type=c["direction"].lower(),
                )
                
                contracts = trading.get_option_contracts(req)
                
                if not contracts or not contracts.option_contracts:
                    c["option"] = None
                    results.append(c)
                    continue
                
                # Find best strike within range
                best_contract = None
                best_distance = float('inf')
                
                for contract in contracts.option_contracts:
                    strike = float(contract.strike_price)
                    distance_pct = abs(strike - c["price"]) / c["price"] * 100
                    
                    if distance_pct <= max_strike_pct:
                        if c["direction"] == "PUT":
                            # For puts, want strike below current price
                            if strike <= c["price"] and distance_pct < best_distance:
                                best_distance = distance_pct
                                best_contract = contract
                        else:
                            # For calls, want strike above current price
                            if strike >= c["price"] and distance_pct < best_distance:
                                best_distance = distance_pct
                                best_contract = contract
                
                c["option"] = best_contract
                c["strike_distance"] = best_distance if best_contract else None
                results.append(c)
                
            except Exception as e:
                c["option"] = None
                c["option_error"] = str(e)
                results.append(c)
        
        # Display results
        _show_ideas_table(results)

    @tariff_app.command("snapshot")
    def tariff_snapshot(
        basket: str = typer.Option("import_retail_apparel", "--basket"),
        start: str = typer.Option("2011-01-01", "--start"),
        benchmark: str = typer.Option("XLY", "--benchmark", help="Sector or market benchmark (e.g., XLY, SPY)"),
        refresh: bool = typer.Option(False, "--refresh"),
        llm: bool = typer.Option(False, "--llm", help="Get LLM analysis with real-time data"),
        features: bool = typer.Option(False, "--features", help="Export ML-ready feature vector (JSON)"),
        json_out: bool = typer.Option(False, "--json", help="Machine-readable JSON output"),
    ):
        """Compute tariff/cost-push regime snapshot for an import-exposed basket."""
        _run_tariff_snapshot(
            basket=basket, start=start, benchmark=benchmark, refresh=refresh,
            llm=llm, features=features, json_out=json_out,
        )


def _show_candidates_table(candidates):
    """Show candidates without options data."""
    table = Table(title="Tariff ETF Contrarian Ideas (No Options Data)", show_header=True, header_style="bold")
    table.add_column("Ticker", style="cyan", width=8)
    table.add_column("Name", width=25)
    table.add_column("Price", justify="right", width=10)
    table.add_column("Move", justify="right", width=10)
    table.add_column("Direction", justify="center", width=10)
    table.add_column("Rationale", width=40)
    
    for c in candidates:
        dir_style = "red" if c["direction"] == "PUT" else "green"
        ret_style = "green" if c["return"] > 0 else "red"
        
        table.add_row(
            c["etf"].ticker,
            c["etf"].name[:25],
            f"${c['price']:.2f}",
            f"[{ret_style}]{c['return']:+.1f}%[/{ret_style}]",
            f"[{dir_style}]{c['direction']}[/{dir_style}]",
            c["rationale"],
        )
    
    console.print()
    console.print(table)


def _show_ideas_table(results):
    """Show ideas with options data."""
    table = Table(title="🎯 Tariff ETF Contrarian Options Ideas", show_header=True, header_style="bold")
    table.add_column("Ticker", style="cyan", width=8)
    table.add_column("Price", justify="right", width=9)
    table.add_column("Move", justify="right", width=9)
    table.add_column("Play", justify="center", width=8)
    table.add_column("Strike", justify="right", width=9)
    table.add_column("Expiry", width=12)
    table.add_column("Rationale", width=35)
    
    for r in results:
        dir_style = "red" if r["direction"] == "PUT" else "green"
        ret_style = "green" if r["return"] > 0 else "red"
        
        if r.get("option"):
            opt = r["option"]
            strike = f"${float(opt.strike_price):.0f}"
            expiry = str(opt.expiration_date)[:10]
        else:
            strike = "—"
            expiry = "—"
        
        table.add_row(
            r["etf"].ticker,
            f"${r['price']:.2f}",
            f"[{ret_style}]{r['return']:+.1f}%[/{ret_style}]",
            f"[{dir_style}]{r['direction']}[/{dir_style}]",
            strike,
            expiry,
            r["rationale"][:35],
        )
    
    console.print()
    console.print(table)
    console.print()
    console.print(Panel(
        "[bold]Strategy:[/bold] Contrarian mean-reversion on tariff-exposed ETFs\n\n"
        "[red]PUT[/red] = ETF moved UP recently → expect pullback\n"
        "[green]CALL[/green] = ETF moved DOWN recently → expect bounce\n\n"
        "[dim]Strikes are within 10% of current price, 14-60 DTE[/dim]",
        title="Legend",
        border_style="blue"
    ))


def _llm_tariff_analysis(state, settings):
    """Generate LLM analysis of tariff regime state."""
    from ai_options_trader.tariff.etf_impact import get_high_exposure_etfs
    
    if not hasattr(settings, 'openai_api_key') or not settings.openai_api_key:
        console.print("[red]OpenAI API key not configured. Set OPENAI_API_KEY in .env[/red]")
        return
    
    try:
        from openai import OpenAI
    except ImportError:
        console.print("[red]OpenAI package not installed. Run: pip install openai[/red]")
        return
    
    client = OpenAI(api_key=settings.openai_api_key)
    
    inputs = state.inputs
    etfs = get_high_exposure_etfs()
    etf_list = "\n".join([f"  - {e.ticker}: {e.name} ({e.direction})" for e in etfs[:10]])
    
    prompt = f"""You are a macro strategist analyzing tariff/trade policy impact on equities.

TARIFF REGIME STATE:
- Basket: {state.basket}
- Universe: {', '.join(state.universe)}
- Benchmark: {state.benchmark}
- As of: {state.asof}

REGIME METRICS:
- Tariff Regime Score: {inputs.tariff_regime_score:.2f} (threshold: 0.5)
- In Tariff Regime: {"YES" if inputs.is_tariff_regime else "NO"}
- Cost Pressure (z-score): {inputs.z_cost_pressure:+.2f}
- Equity Denial Beta: {inputs.equity_denial_beta:.4f}
- Denial Active: {inputs.components.get('denial_active', 0)}

HIGH TARIFF EXPOSURE ETFS:
{etf_list}

Provide analysis in this format:

REGIME ASSESSMENT
[2-3 sentences on current tariff regime status and what the metrics indicate]

COST PRESSURE ANALYSIS
[Interpret the z-score: what's driving cost pressure? Import prices, PPI, commodities?]

EQUITY BEHAVIOR
[Is the market pricing in tariff risk or in denial? What does the beta tell us?]

TRADE IMPLICATIONS
[Which sectors/ETFs are most vulnerable? Any beneficiaries? Specific trade ideas?]

RISK FACTORS
[What could escalate or de-escalate the tariff regime? Key dates/events to watch?]

Keep it concise and actionable for a portfolio manager."""

    console.print("[dim]Generating LLM analysis...[/dim]")
    
    response = client.chat.completions.create(
        model=settings.openai_model or "gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=800,
    )
    
    analysis = response.choices[0].message.content.strip()
    
    console.print()
    console.print(Panel(
        analysis,
        title=f"🌐 Tariff Regime Analysis | {state.basket}",
        border_style="yellow",
        padding=(1, 2)
    ))


