"""
Options CLI - streamlined option scanning and analysis.

Commands split across modules:
- options_cmd.py: scan, most-traded (this file)
- options_pick_cmd.py: pick
- options_scanner_cmd.py: sp500-under-budget, etf-under-budget
- options_moonshot_cmd.py: moonshot
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import typer
from rich import print
from rich.console import Console
from rich.table import Table

from ai_options_trader.config import load_settings
from ai_options_trader.data.alpaca import fetch_option_chain, make_clients, to_candidates
from ai_options_trader.data.polygon import fetch_high_oi_options, fetch_options_chain_polygon, get_liquid_etf_universe
from ai_options_trader.options.historical import fetch_option_bar_volumes
from ai_options_trader.options.most_traded import most_traded_options
from ai_options_trader.utils.occ import parse_occ_option_symbol


def _fmt_int(x: int | None) -> str:
    return f"{int(x):,}" if isinstance(x, int) else "n/a"


def _fmt_price(x: float | None) -> str:
    return f"{float(x):.2f}" if isinstance(x, (int, float)) else "n/a"


def _fmt_pct(x: float | None) -> str:
    return f"{100.0*float(x):.1f}%" if isinstance(x, (int, float)) else "n/a"


def register(options_app: typer.Typer) -> None:
    """Register core options commands."""

    @options_app.command("best")
    def options_best(
        ticker: str = typer.Argument(..., help="Underlying ticker"),
        want: str = typer.Option("put", "--want", "-w", help="call|put"),
        budget: float = typer.Option(200.0, "--budget", "-b", help="Max premium in USD"),
        delta: float = typer.Option(0.30, "--delta", "-d", help="Target delta"),
        min_days: int = typer.Option(30, "--min-days", help="Min DTE"),
        max_days: int = typer.Option(90, "--max-days", help="Max DTE"),
        show: int = typer.Option(3, "--show", "-n", help="Number of picks"),
    ):
        """
        Find best options under a budget.
        
        Examples:
            lox options best FXI --budget 200
            lox options best NVDA --want call --budget 500 --delta 0.40
        """
        settings = load_settings()
        _, data = make_clients(settings)
        
        w = (want or "put").strip().lower()
        if w not in {"call", "put"}:
            w = "put"
        
        console = Console()
        console.print(f"\n[bold cyan]{ticker.upper()} {w.upper()}s[/bold cyan] | Budget: ${budget:.0f} | Target Δ: {delta:.2f}\n")
        
        chain = fetch_option_chain(data, ticker, feed=settings.alpaca_options_feed)
        if not chain:
            console.print("[yellow]No options data[/yellow]")
            return
        
        today = date.today()
        candidates = []
        
        for opt in chain.values():
            symbol = str(getattr(opt, "symbol", ""))
            if not symbol:
                continue
            try:
                expiry, opt_type, strike = parse_occ_option_symbol(symbol, ticker)
                if opt_type != w:
                    continue
                
                dte = (expiry - today).days
                if dte < min_days or dte > max_days:
                    continue
                
                # Get greeks
                greeks = getattr(opt, "greeks", None)
                opt_delta = getattr(greeks, "delta", None) if greeks else None
                opt_gamma = getattr(greeks, "gamma", None) if greeks else None
                opt_theta = getattr(greeks, "theta", None) if greeks else None
                
                # Get bid/ask from latest_quote
                quote = getattr(opt, "latest_quote", None)
                bid = getattr(quote, "bid_price", None) if quote else None
                ask = getattr(quote, "ask_price", None) if quote else None
                
                # Get last from latest_trade
                trade = getattr(opt, "latest_trade", None)
                last = getattr(trade, "price", None) if trade else None
                
                # Calculate premium (use ask for budget filter)
                price = float(ask) if ask else (float(last) if last else None)
                if price is None or price <= 0:
                    continue
                
                premium = price * 100  # Per contract
                if premium > budget:
                    continue
                
                # Need delta for ranking
                if opt_delta is None:
                    continue
                
                candidates.append({
                    "symbol": symbol,
                    "strike": strike,
                    "expiry": expiry,
                    "dte": dte,
                    "delta": float(opt_delta),
                    "gamma": float(opt_gamma) if opt_gamma else None,
                    "theta": float(opt_theta) if opt_theta else None,
                    "bid": float(bid) if bid else None,
                    "ask": float(ask) if ask else None,
                    "last": float(last) if last else None,
                    "premium": premium,
                })
            except Exception:
                continue
        
        if not candidates:
            console.print(f"[yellow]No {w}s under ${budget:.0f} in {min_days}-{max_days} DTE range[/yellow]")
            console.print("[dim]Try increasing --budget or widening DTE range[/dim]")
            return
        
        # Rank by: closest to target delta
        target = abs(delta)
        candidates.sort(key=lambda x: abs(abs(x["delta"]) - target))
        
        top = candidates[:show]
        
        # Display
        table = Table(title=f"Top {len(top)} Picks (under ${budget:.0f})", show_header=True)
        table.add_column("#", justify="right", style="bold", width=3)
        table.add_column("Strike", justify="right", width=8)
        table.add_column("Exp", justify="center", width=10)
        table.add_column("DTE", justify="right", width=4)
        table.add_column("Delta", justify="right", width=7)
        table.add_column("Gamma", justify="right", width=7)
        table.add_column("Theta", justify="right", width=7)
        table.add_column("Bid/Ask", justify="right", width=14)
        table.add_column("Cost", justify="right", style="yellow", width=6)
        
        for i, c in enumerate(top, 1):
            bid_ask = f"${c['bid']:.2f}/${c['ask']:.2f}" if c["bid"] and c["ask"] else "—"
            table.add_row(
                str(i),
                f"${c['strike']:.0f}",
                c["expiry"].strftime("%b %d"),
                str(c["dte"]),
                f"{c['delta']:+.2f}",
                f"{c['gamma']:.3f}" if c["gamma"] else "—",
                f"{c['theta']:.3f}" if c["theta"] else "—",
                bid_ask,
                f"${c['premium']:.0f}",
            )
        
        console.print(table)
        console.print(f"\n[dim]{len(candidates)} contracts matched | Showing top {len(top)}[/dim]")

    @options_app.command("scan")
    def options_scan(
        ticker: str = typer.Option(..., "--ticker", "-t", help="Underlying ticker"),
        want: str = typer.Option("call", "--want", help="call|put"),
        show_top: int = typer.Option(20, "--show-top", "-n"),
        target_delta: float = typer.Option(0.30, "--delta", "-d", help="Target delta (e.g. 0.30)"),
        min_days: int = typer.Option(30, "--min-days", help="Min DTE"),
        max_days: int = typer.Option(120, "--max-days", help="Max DTE"),
    ):
        """Options scanner - sorted by best delta. Auto-expands range if needed."""
        from datetime import date
        
        settings = load_settings()
        _, data = make_clients(settings)

        w = (want or "call").strip().lower()
        if w not in {"call", "put"}:
            w = "call"

        console = Console()
        console.print(f"\n[bold cyan]{ticker.upper()} {w.upper()}s[/bold cyan] (target Δ={target_delta:.2f})\n")

        chain = fetch_option_chain(data, ticker, feed=settings.alpaca_options_feed)
        if not chain:
            console.print("[yellow]No options data[/yellow]")
            return

        console.print(f"[dim]Total contracts: {len(chain)}[/dim]")
        today = date.today()

        # Parse ALL options of the right type first
        all_opts = []
        for opt in chain.values():
            symbol = str(getattr(opt, "symbol", ""))
            if not symbol:
                continue
            try:
                expiry, opt_type, strike = parse_occ_option_symbol(symbol, ticker)
                if opt_type != w:
                    continue
                
                dte = (expiry - today).days
                if dte < 1:  # Skip expired
                    continue
                
                # Get greeks
                greeks = getattr(opt, "greeks", None)
                delta = getattr(greeks, "delta", None) if greeks else None
                
                # Get bid/ask from latest_quote
                quote = getattr(opt, "latest_quote", None)
                bid = getattr(quote, "bid_price", None) if quote else None
                ask = getattr(quote, "ask_price", None) if quote else None
                
                # Get last from latest_trade
                trade = getattr(opt, "latest_trade", None)
                last = getattr(trade, "price", None) if trade else None
                
                all_opts.append({
                    "symbol": symbol,
                    "strike": strike,
                    "expiry": expiry,
                    "dte": dte,
                    "delta": float(delta) if delta is not None else None,
                    "bid": float(bid) if bid is not None else None,
                    "ask": float(ask) if ask is not None else None,
                    "last": float(last) if last is not None else None,
                })
            except Exception:
                continue

        if not all_opts:
            console.print(f"[yellow]No {w}s available for {ticker.upper()}[/yellow]")
            return

        # Try requested range first, then expand if empty
        filtered = [o for o in all_opts if min_days <= o["dte"] <= max_days]
        range_note = f"{min_days}-{max_days} DTE"
        
        # Fallback: expand to nearest available expiries
        if not filtered:
            # Find the closest expiry to requested range
            min_dte_available = min(o["dte"] for o in all_opts)
            max_dte_available = max(o["dte"] for o in all_opts)
            
            # Expand to include nearest 60-day window
            fallback_min = max(1, min(min_days, min_dte_available))
            fallback_max = min(max(max_days, min_dte_available + 60), max_dte_available)
            
            filtered = [o for o in all_opts if fallback_min <= o["dte"] <= fallback_max]
            range_note = f"{fallback_min}-{fallback_max} DTE [auto-expanded]"
            
            # If still empty, just take nearest expiries
            if not filtered:
                unique_dtes = sorted(set(o["dte"] for o in all_opts))[:3]  # Nearest 3 expiries
                filtered = [o for o in all_opts if o["dte"] in unique_dtes]
                range_note = f"nearest expiries: {', '.join(str(d) for d in unique_dtes)} DTE"

        console.print(f"[dim]Found {len(filtered)} {w}s in {range_note}[/dim]\n")
        
        # Sort by: 1) has delta, 2) closest to target delta
        abs_target = abs(target_delta)
        filtered.sort(key=lambda x: (
            0 if x["delta"] is not None else 1,  # Has delta first
            abs(abs(x["delta"] or 0) - abs_target) if x["delta"] is not None else 999,
        ))
        filtered = filtered[:show_top]

        table = Table(show_header=True)
        table.add_column("Symbol", style="cyan")
        table.add_column("Strike", justify="right")
        table.add_column("DTE", justify="right")
        table.add_column("Delta", justify="right", style="bold green")
        table.add_column("Bid", justify="right")
        table.add_column("Ask", justify="right", style="yellow")
        table.add_column("Last", justify="right")

        for item in filtered:
            delta = item["delta"]
            bid = item["bid"]
            ask = item["ask"]
            last = item["last"]

            table.add_row(
                item["symbol"][:22],
                f"${item['strike']:.2f}",
                str(item["dte"]),
                f"{delta:+.3f}" if delta is not None else "—",
                f"${bid:.2f}" if bid else "—",
                f"${ask:.2f}" if ask else "—",
                f"${last:.2f}" if last else "—",
            )

        console.print(table)

    @options_app.command("most-traded")
    def options_most_traded(
        ticker: str = typer.Option("SPY", "--ticker", "-t"),
        min_days: int = typer.Option(0, "--min-days"),
        max_days: int = typer.Option(90, "--max-days"),
        top: int = typer.Option(25, "--top"),
        calls: bool = typer.Option(False, "--calls"),
        puts: bool = typer.Option(False, "--puts"),
        sort: str = typer.Option("volume", "--sort",
            help="volume|open_interest|delta|abs_delta|gamma|theta|vega|iv|hf"),
        mode: str = typer.Option("snapshot", "--mode", help="snapshot|historical"),
        lookback_days: int = typer.Option(1, "--lookback-days"),
        chunk_size: int = typer.Option(200, "--chunk-size"),
    ):
        """Print most-traded option contracts for a ticker."""
        want = "both"
        if calls and not puts:
            want = "call"
        elif puts and not calls:
            want = "put"

        s = sort.strip().lower()
        if s.startswith("open"):
            sort_key = "open_interest"
        elif s == "hf":
            sort_key = "hf"
        elif s in {"delta", "abs_delta", "gamma", "theta", "vega", "iv"}:
            sort_key = s
        else:
            sort_key = "volume"

        settings = load_settings()
        _, data = make_clients(settings)

        chain = fetch_option_chain(data, ticker, feed=settings.alpaca_options_feed)
        candidates = list(to_candidates(chain, ticker))

        mode_norm = mode.strip().lower()
        volume_by_symbol = None

        if mode_norm.startswith("hist"):
            symbols_in_window = [
                c.symbol for c in most_traded_options(
                    candidates, ticker=ticker,
                    min_dte_days=int(min_days), max_dte_days=int(max_days),
                    want=want, top=max(1, len(candidates)),
                    sort="volume", today=date.today(),
                )
            ]
            end = datetime.now(timezone.utc)
            start = end - timedelta(days=int(lookback_days))
            try:
                hv = fetch_option_bar_volumes(
                    data, option_symbols=symbols_in_window,
                    start=start, end=end,
                    feed=settings.alpaca_options_feed, chunk_size=int(chunk_size),
                )
                volume_by_symbol = hv.volume_by_symbol
                print(f"[dim]Historical: {hv.start.isoformat()} → {hv.end.isoformat()}[/dim]")
            except Exception as e:
                print(f"[red]Historical volume failed[/red]: {e}")
                raise typer.Exit(code=2)

        # Auto-fallback if volume missing
        vol_missing = sum(1 for c in candidates if c.volume is None)
        oi_missing = sum(1 for c in candidates if c.oi is None)
        if sort_key == "volume" and candidates and vol_missing == len(candidates) and oi_missing == len(candidates):
            sort_key = "hf"
            print("[yellow]Note:[/yellow] volume/OI missing, falling back to --sort hf")

        ranked = most_traded_options(
            candidates, ticker=ticker,
            min_dte_days=int(min_days), max_dte_days=int(max_days),
            want=want, top=int(top), sort=sort_key,
            volume_by_symbol=volume_by_symbol, today=date.today(),
        )

        delta_missing = sum(1 for c in candidates if c.delta is None)
        iv_missing = sum(1 for c in candidates if c.iv is None)
        print(f"[dim]Chain: {len(candidates)} | vol missing: {vol_missing} | Δ missing: {delta_missing}[/dim]")

        if volume_by_symbol is None and candidates and vol_missing == len(candidates):
            print("[yellow]Warning:[/yellow] Volume not available. Check ALPACA_OPTIONS_FEED.")

        tbl = Table(title=f"{ticker.upper()} options: most traded ({min_days}..{max_days} DTE)")
        tbl.add_column("Rank", justify="right")
        tbl.add_column("Symbol", style="bold")
        tbl.add_column("Type")
        tbl.add_column("Exp")
        tbl.add_column("DTE", justify="right")
        tbl.add_column("Strike", justify="right")
        tbl.add_column("Vol", justify="right")
        show_oi = any(isinstance(o.open_interest, int) for o in ranked)
        if show_oi:
            tbl.add_column("OI", justify="right")
        tbl.add_column("Bid", justify="right")
        tbl.add_column("Ask", justify="right")
        tbl.add_column("Mid", justify="right")
        tbl.add_column("Δ", justify="right")
        tbl.add_column("IV", justify="right")

        for i, o in enumerate(ranked, start=1):
            row = [
                str(i), o.symbol, o.opt_type,
                o.expiry.isoformat(), str(o.dte_days),
                f"{o.strike:.2f}", _fmt_int(o.volume),
            ]
            if show_oi:
                row.append(_fmt_int(o.open_interest))
            row.extend([
                _fmt_price(o.bid), _fmt_price(o.ask),
                _fmt_price(o.mid), _fmt_price(o.delta), _fmt_pct(o.iv),
            ])
            tbl.add_row(*row)

        Console().print(tbl)

    @options_app.command("high-oi")
    def options_high_oi(
        ticker: str = typer.Option(None, "--ticker", "-t", help="Single ticker or 'etfs' for liquid ETF universe"),
        budget: float = typer.Option(150.0, "--budget", "-b", help="Max premium in USD per contract"),
        min_dte: int = typer.Option(14, "--min-dte", help="Min days to expiration"),
        max_dte: int = typer.Option(60, "--max-dte", help="Max days to expiration"),
        min_oi: int = typer.Option(500, "--min-oi", help="Minimum open interest"),
        want: str = typer.Option(None, "--want", "-w", help="call|put or both"),
        show: int = typer.Option(20, "--show", "-n", help="Number of results"),
    ):
        """
        Scan for high OI options using Polygon/Massive data.
        
        Examples:
            lox options high-oi --ticker SPY --budget 200
            lox options high-oi --ticker etfs --budget 150 --want put
            lox options high-oi -t IWM --min-oi 1000
        """
        settings = load_settings()
        console = Console()
        
        if not settings.massive_api_key:
            console.print("[red]MASSIVE_API_KEY not set in .env[/red]")
            console.print("[dim]Sign up at polygon.io (now Massive) for options OI data[/dim]")
            return
        
        # Determine tickers to scan
        if ticker and ticker.lower() == "etfs":
            tickers = get_liquid_etf_universe()[:15]  # Top 15 liquid ETFs
            console.print(f"[bold cyan]Scanning {len(tickers)} liquid ETFs[/bold cyan] | Budget: ${budget:.0f} | Min OI: {min_oi:,}\n")
        elif ticker:
            tickers = [ticker.upper()]
            console.print(f"[bold cyan]{ticker.upper()}[/bold cyan] | Budget: ${budget:.0f} | Min OI: {min_oi:,}\n")
        else:
            # Default to major indices
            tickers = ["SPY", "QQQ", "IWM", "DIA"]
            console.print(f"[bold cyan]Major Indices[/bold cyan] | Budget: ${budget:.0f} | Min OI: {min_oi:,}\n")
        
        contract_type = want.lower() if want else None
        if contract_type and contract_type not in {"call", "put"}:
            contract_type = None
        
        # Convert budget from USD to per-share (Polygon uses per-share pricing)
        max_premium = budget / 100.0
        
        results = fetch_high_oi_options(
            settings,
            tickers,
            max_premium=max_premium,
            min_dte=min_dte,
            max_dte=max_dte,
            min_oi=min_oi,
            contract_type=contract_type,
        )
        
        if not results:
            console.print("[yellow]No options found matching criteria[/yellow]")
            console.print("[dim]Try increasing --budget, lowering --min-oi, or widening DTE range[/dim]")
            return
        
        results = results[:show]
        
        table = Table(title=f"High OI Options ({len(results)} matches)", show_header=True)
        table.add_column("#", justify="right", width=3)
        table.add_column("Symbol", style="cyan", width=24)
        table.add_column("Type", width=5)
        table.add_column("Strike", justify="right", width=8)
        table.add_column("Exp", justify="center", width=10)
        table.add_column("DTE", justify="right", width=4)
        table.add_column("OI", justify="right", style="bold green", width=8)
        table.add_column("Vol", justify="right", width=7)
        table.add_column("Delta", justify="right", width=7)
        table.add_column("IV", justify="right", width=6)
        table.add_column("Bid/Ask", justify="right", width=12)
        table.add_column("Cost", justify="right", style="yellow", width=7)
        
        for i, opt in enumerate(results, 1):
            mid = opt.mid
            cost = mid * 100 if mid else None
            bid_ask = f"{opt.bid:.2f}/{opt.ask:.2f}" if opt.bid and opt.ask else "—"
            
            table.add_row(
                str(i),
                opt.symbol[:24],
                opt.opt_type.upper()[:4],
                f"${opt.strike:.0f}",
                opt.expiry.strftime("%b %d"),
                str(opt.dte_days),
                f"{opt.oi:,}" if opt.oi else "—",
                f"{opt.volume:,}" if opt.volume else "—",
                f"{opt.delta:+.2f}" if opt.delta else "—",
                f"{opt.iv*100:.0f}%" if opt.iv else "—",
                bid_ask,
                f"${cost:.0f}" if cost else "—",
            )
        
        console.print(table)
        console.print(f"\n[dim]Data source: Polygon.io/Massive | Sorted by Open Interest[/dim]")

    @options_app.command("sample")
    def options_sample(
        ticker: str = typer.Argument("SPY", help="Ticker to sample"),
        source: str = typer.Option("polygon", "--source", "-s", help="polygon|alpaca"),
    ):
        """
        Sample options data to verify OI/volume availability.
        
        Examples:
            lox options sample SPY
            lox options sample QQQ --source alpaca
        """
        settings = load_settings()
        console = Console()
        
        console.print(f"\n[bold cyan]Options Data Sample: {ticker.upper()}[/bold cyan] (source: {source})\n")
        
        if source.lower() == "polygon":
            if not settings.massive_api_key:
                console.print("[red]MASSIVE_API_KEY not set[/red]")
                return
            
            from datetime import timedelta
            today = date.today()
            exp_gte = (today + timedelta(days=14)).strftime("%Y-%m-%d")
            exp_lte = (today + timedelta(days=45)).strftime("%Y-%m-%d")
            
            candidates = fetch_options_chain_polygon(
                settings, ticker,
                expiration_date_gte=exp_gte,
                expiration_date_lte=exp_lte,
                limit=10,
            )
            
            if not candidates:
                console.print("[yellow]No data returned[/yellow]")
                return
            
            console.print(f"[green]✓ Polygon returned {len(candidates)} options[/green]\n")
            
            table = Table(show_header=True)
            table.add_column("Symbol", width=24)
            table.add_column("Type", width=5)
            table.add_column("Strike", justify="right")
            table.add_column("DTE", justify="right")
            table.add_column("OI", justify="right", style="bold green")
            table.add_column("Vol", justify="right")
            table.add_column("Delta", justify="right")
            table.add_column("IV", justify="right")
            table.add_column("Bid", justify="right")
            table.add_column("Ask", justify="right")
            
            for opt in candidates[:10]:
                table.add_row(
                    opt.symbol[:24],
                    opt.opt_type[:4].upper(),
                    f"${opt.strike:.0f}",
                    str(opt.dte_days),
                    f"{opt.oi:,}" if opt.oi else "[red]None[/red]",
                    f"{opt.volume:,}" if opt.volume else "[red]None[/red]",
                    f"{opt.delta:+.3f}" if opt.delta else "—",
                    f"{opt.iv*100:.0f}%" if opt.iv else "—",
                    f"${opt.bid:.2f}" if opt.bid else "—",
                    f"${opt.ask:.2f}" if opt.ask else "—",
                )
            
            console.print(table)
            
            # Summary
            has_oi = sum(1 for c in candidates if c.oi is not None)
            has_vol = sum(1 for c in candidates if c.volume is not None)
            has_delta = sum(1 for c in candidates if c.delta is not None)
            console.print(f"\n[dim]OI available: {has_oi}/{len(candidates)} | Vol: {has_vol}/{len(candidates)} | Delta: {has_delta}/{len(candidates)}[/dim]")
            
        else:  # Alpaca
            _, data = make_clients(settings)
            chain = fetch_option_chain(data, ticker, feed=settings.alpaca_options_feed)
            
            if not chain:
                console.print("[yellow]No data returned[/yellow]")
                return
            
            console.print(f"[green]✓ Alpaca returned {len(chain)} options[/green]\n")
            
            table = Table(show_header=True)
            table.add_column("Symbol", width=24)
            table.add_column("OI", justify="right", style="bold green")
            table.add_column("Vol", justify="right")
            table.add_column("Delta", justify="right")
            table.add_column("Bid", justify="right")
            table.add_column("Ask", justify="right")
            
            sample = list(chain.items())[:10]
            for sym, snap in sample:
                greeks = getattr(snap, "greeks", None)
                quote = getattr(snap, "latest_quote", None)
                daily = getattr(snap, "daily_bar", None)
                
                delta = getattr(greeks, "delta", None) if greeks else None
                bid = getattr(quote, "bid_price", None) if quote else None
                ask = getattr(quote, "ask_price", None) if quote else None
                oi = getattr(snap, "open_interest", None)
                vol = getattr(daily, "volume", None) if daily else getattr(snap, "volume", None)
                
                table.add_row(
                    sym[:24],
                    f"{oi:,}" if oi else "[red]None[/red]",
                    f"{vol:,}" if vol else "[red]None[/red]",
                    f"{delta:+.3f}" if delta else "—",
                    f"${bid:.2f}" if bid else "—",
                    f"${ask:.2f}" if ask else "—",
                )
            
            console.print(table)
            
            # Check availability
            candidates = list(to_candidates(chain, ticker))
            has_oi = sum(1 for c in candidates if c.oi is not None)
            has_vol = sum(1 for c in candidates if c.volume is not None)
            console.print(f"\n[dim]OI available: {has_oi}/{len(candidates)} | Vol: {has_vol}/{len(candidates)}[/dim]")
            if has_oi == 0:
                console.print("[yellow]⚠ Alpaca does not provide OI in snapshots - use Polygon instead[/yellow]")
