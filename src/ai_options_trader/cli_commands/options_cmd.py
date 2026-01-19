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

    @options_app.command("scan")
    def options_scan(
        ticker: str = typer.Option(..., "--ticker", "-t", help="Underlying ticker"),
        want: str = typer.Option("call", "--want", help="call|put"),
        show_top: int = typer.Option(20, "--show-top", "-n"),
        target_delta: float = typer.Option(0.30, "--delta", "-d", help="Target delta (e.g. 0.30)"),
        min_days: int = typer.Option(30, "--min-days", help="Min DTE"),
        max_days: int = typer.Option(120, "--max-days", help="Max DTE"),
    ):
        """Options scanner - sorted by best delta (closest to target)."""
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

        filtered = []
        for opt in chain.values():
            symbol = str(getattr(opt, "symbol", ""))
            if not symbol:
                continue
            try:
                expiry, opt_type, strike = parse_occ_option_symbol(symbol, ticker)
                if opt_type != w:
                    continue
                
                # Filter by DTE
                dte = (expiry - today).days
                if dte < min_days or dte > max_days:
                    continue
                
                # Get greeks from nested object
                greeks = getattr(opt, "greeks", None)
                delta = getattr(greeks, "delta", None) if greeks else None
                
                # Get bid/ask from latest_quote (Alpaca structure)
                quote = getattr(opt, "latest_quote", None)
                bid = getattr(quote, "bid_price", None) if quote else None
                ask = getattr(quote, "ask_price", None) if quote else None
                
                # Get last from latest_trade
                trade = getattr(opt, "latest_trade", None)
                last = getattr(trade, "price", None) if trade else None
                
                filtered.append({
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

        if not filtered:
            console.print(f"[yellow]No {w}s found in {min_days}-{max_days} DTE range[/yellow]")
            return

        console.print(f"[dim]Found {len(filtered)} {w}s in range[/dim]\n")
        
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
