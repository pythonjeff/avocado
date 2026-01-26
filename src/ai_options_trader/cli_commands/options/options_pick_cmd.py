"""Options pick command - single contract selector with delta/theta optimization."""
from __future__ import annotations

from datetime import date

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ai_options_trader.config import load_settings
from ai_options_trader.data.alpaca import fetch_option_chain, make_clients, to_candidates
from ai_options_trader.data.quotes import fetch_stock_last_prices
from ai_options_trader.data.polygon import fetch_oi_map, enrich_candidates_with_oi
from ai_options_trader.execution.alpaca import submit_option_order
from ai_options_trader.options.budget_scan import (
    affordable_options_for_ticker,
    pick_best_delta_theta,
    score_delta_oi,
)
from ai_options_trader.options.targets import (
    format_required_move,
    required_underlying_move_for_profit_pct,
)


def register_pick(options_app: typer.Typer) -> None:
    """Register the options pick command."""

    @options_app.command("pick")
    def options_pick(
        ticker: str = typer.Option(..., "--ticker", "-t", help="Underlying ticker"),
        want: str = typer.Option("put", "--want", help="call|put"),
        budget: float = typer.Option(
            0.0, "--budget", "-b",
            help="Max premium (USD). If not specified, shows top options without budget filter.",
        ),
        min_days: int = typer.Option(30, "--min-days", help="Min DTE"),
        max_days: int = typer.Option(120, "--max-days", help="Max DTE"),
        target_abs_delta: float = typer.Option(0.30, "--target-abs-delta"),
        delta_weight: float = typer.Option(1.0, "--delta-weight"),
        theta_weight: float = typer.Option(1.0, "--theta-weight"),
        price_basis: str = typer.Option("ask", "--price-basis", help="ask|mid|last"),
        min_price: float = typer.Option(0.05, "--min-price"),
        max_spread_pct: float = typer.Option(0.30, "--max-spread-pct"),
        require_delta: bool = typer.Option(True, "--require-delta/--no-require-delta"),
        require_liquidity: bool = typer.Option(True, "--require-liquidity/--no-require-liquidity"),
        min_oi: int = typer.Option(10, "--min-oi", help="Minimum open interest (default 10)"),
        min_volume: int = typer.Option(10, "--min-vol", help="Minimum volume (default 10)"),
        top_n: int = typer.Option(10, "--top", "-n", help="Number of options to show when no budget specified"),
        execute: bool = typer.Option(False, "--execute"),
        live: bool = typer.Option(False, "--live"),
    ):
        """
        Pick ONE option contract optimized for delta and theta.
        
        If --budget is not specified, shows top N options sorted by delta/theta score.
        If --budget is specified, filters to affordable options and picks the best one.
        """
        console = Console()
        w = (want or "put").strip().lower()
        if w not in {"call", "put"}:
            w = "put"
        pb = price_basis.strip().lower()
        if pb not in {"ask", "mid", "last"}:
            pb = "ask"

        settings = load_settings()
        trading, data = make_clients(settings)
        
        # Determine if we have an explicit budget
        has_budget = float(budget) > 0
        max_premium_usd = float(budget) if has_budget else 1_000_000.0  # Large value to not filter

        # Safety checks
        live_ok = bool(live) and not bool(settings.alpaca_paper)
        if execute and not settings.alpaca_paper and not live_ok:
            console.print(Panel(
                "[red]Refusing to execute[/red]: ALPACA_PAPER is false.\n"
                "Re-run with --live --execute for live trading.",
                title="Safety", expand=False,
            ))
            raise typer.Exit(code=1)

        if execute and live_ok:
            console.print(Panel(
                "[yellow]LIVE MODE[/yellow]\nOrders go to your LIVE account.",
                title="Safety", expand=False,
            ))
            if not typer.confirm("Confirm LIVE mode?", default=False):
                raise typer.Exit(code=0)
            if not typer.confirm("Second confirmation?", default=False):
                raise typer.Exit(code=0)

        chain = fetch_option_chain(data, ticker, feed=settings.alpaca_options_feed)
        candidates = list(to_candidates(chain, ticker))
        if not candidates:
            print(f"[yellow]No options for {ticker}[/yellow]")
            raise typer.Exit(code=0)

        # Enrich candidates with OI from Polygon (Alpaca lacks OI data)
        try:
            oi_map = fetch_oi_map(
                settings,
                ticker.upper(),
                min_dte=int(min_days),
                max_dte=int(max_days) + 7,  # Slightly wider to ensure coverage
            )
            if oi_map:
                candidates = enrich_candidates_with_oi(candidates, oi_map)
                console.print(f"[dim]Enriched {len(oi_map)} contracts with OI from Polygon[/dim]")
        except Exception as e:
            console.print(f"[dim]OI enrichment skipped: {e}[/dim]")

        def _scan(require_liq: bool):
            return affordable_options_for_ticker(
                candidates,
                ticker=ticker.upper(),
                max_premium_usd=float(max_premium_usd),
                min_dte_days=int(min_days),
                max_dte_days=int(max_days),
                want=w,
                price_basis=pb,
                min_price=float(min_price),
                max_spread_pct=float(max_spread_pct),
                require_delta=bool(require_delta),
                require_liquidity=bool(require_liq),
                min_open_interest=int(min_oi),
                min_volume=int(min_volume),
                today=date.today(),
            )

        opts = _scan(bool(require_liquidity))

        # Fallback if OI/volume missing
        if not opts and bool(require_liquidity):
            oi_missing = sum(1 for c in candidates if c.oi is None)
            vol_missing = sum(1 for c in candidates if c.volume is None)
            if candidates and oi_missing == len(candidates) and vol_missing == len(candidates):
                print("[yellow]Note:[/yellow] OI/volume missing, falling back.")
                opts = _scan(False)

        # Fallback if delta missing
        if not opts and bool(require_delta):
            delta_missing = sum(1 for c in candidates if c.delta is None)
            if candidates and delta_missing == len(candidates):
                print("[yellow]Note:[/yellow] Delta missing, falling back.")
                opts = _scan(bool(require_liquidity))

        if not opts:
            # Diagnostic: show why contracts were filtered
            console.print("\n[yellow]No contracts matched.[/yellow] Diagnostic breakdown:\n")
            
            from ai_options_trader.utils.occ import parse_occ_option_symbol
            
            diag = {
                "total_raw": len(candidates),
                "wrong_type": 0,
                "dte_out_of_range": 0,
                "no_price": 0,
                "price_too_low": 0,
                "premium_too_high": 0,
                "no_delta": 0,
                "spread_too_wide": 0,
                "low_liquidity": 0,
                "passed": 0,
            }
            
            for c in candidates:
                try:
                    expiry, opt_type, strike = parse_occ_option_symbol(c.symbol, ticker.upper())
                except Exception:
                    continue
                
                if w != "both" and opt_type != w:
                    diag["wrong_type"] += 1
                    continue
                
                dte = (expiry - date.today()).days
                if dte < int(min_days) or dte > int(max_days):
                    diag["dte_out_of_range"] += 1
                    continue
                
                px = c.ask if pb == "ask" else (c.mid if pb == "mid" else c.last)
                if px is None or px <= 0:
                    diag["no_price"] += 1
                    continue
                
                if px < float(min_price):
                    diag["price_too_low"] += 1
                    continue
                
                prem = px * 100.0
                if prem > float(max_premium_usd):
                    diag["premium_too_high"] += 1
                    continue
                
                if require_delta and c.delta is None:
                    diag["no_delta"] += 1
                    continue
                
                mid = c.mid
                sp = ((c.ask - c.bid) / mid) if c.bid and c.ask and mid and mid > 0 else None
                if sp is None or float(sp) > float(max_spread_pct):
                    diag["spread_too_wide"] += 1
                    continue
                
                if require_liquidity:
                    oi_ok = (c.oi is not None) and (c.oi >= int(min_oi))
                    vol_ok = (c.volume is not None) and (c.volume >= int(min_volume))
                    if not (oi_ok or vol_ok):
                        diag["low_liquidity"] += 1
                        continue
                
                diag["passed"] += 1
            
            console.print(f"  Total raw candidates: {diag['total_raw']}")
            console.print(f"  Wrong type (not {w}): {diag['wrong_type']}")
            console.print(f"  DTE out of range ({min_days}-{max_days}): {diag['dte_out_of_range']}")
            console.print(f"  No price data: {diag['no_price']}")
            console.print(f"  Price < ${min_price}: {diag['price_too_low']}")
            console.print(f"  Premium > ${max_premium_usd:,.0f}: {diag['premium_too_high']}")
            console.print(f"  Missing delta: {diag['no_delta']}")
            console.print(f"  Spread > {max_spread_pct*100:.0f}%: {diag['spread_too_wide']}")
            console.print(f"  Low liquidity (OI<{min_oi} & Vol<{min_volume}): {diag['low_liquidity']}")
            console.print(f"  [green]Passed all filters: {diag['passed']}[/green]")
            
            console.print("\n[dim]Try: --max-spread-pct 0.50, --min-oi 1, --min-vol 1, --no-require-delta[/dim]")
            raise typer.Exit(code=0)

        # Underlying price
        und_px = None
        try:
            last_px, _, _ = fetch_stock_last_prices(
                settings=settings, symbols=[ticker.upper()], max_symbols_for_live=5
            )
            und_px = last_px.get(ticker.upper())
        except Exception:
            pass

        # If no budget specified, show top N options
        if not has_budget:
            # Sort by delta + OI score (prioritizes liquidity)
            scored = []
            for opt in opts:
                sc = score_delta_oi(
                    opt,
                    target_abs_delta=float(target_abs_delta),
                    delta_weight=float(delta_weight),
                    oi_weight=1.0,  # Equal weight to OI
                    theta_weight=float(theta_weight) * 0.3,  # Reduced theta weight
                )
                scored.append((opt, sc))
            
            scored.sort(key=lambda x: x[1], reverse=True)
            top_opts = scored[:int(top_n)]
            
            title = f"Top {len(top_opts)} {ticker.upper()} {w.upper()}s (DTE {min_days}-{max_days})"
            if und_px:
                title += f" | Underlying: ${und_px:.2f}"
            
            tbl = Table(title=title)
            tbl.add_column("#", justify="right", style="dim")
            tbl.add_column("Contract", style="bold")
            tbl.add_column("Exp")
            tbl.add_column("DTE", justify="right")
            tbl.add_column("Strike", justify="right")
            tbl.add_column("Price", justify="right")
            tbl.add_column("Premium", justify="right", style="cyan")
            tbl.add_column("Δ", justify="right")
            tbl.add_column("Θ", justify="right")
            tbl.add_column("OI", justify="right")
            tbl.add_column("Vol", justify="right")
            tbl.add_column("Score", justify="right")
            
            for i, (opt, sc) in enumerate(top_opts, 1):
                move = required_underlying_move_for_profit_pct(
                    opt_entry_price=float(opt.price),
                    delta=float(opt.delta) if opt.delta else None,
                    profit_pct=0.05,
                    underlying_px=und_px,
                    opt_type=str(opt.opt_type),
                )
                # Format OI and Volume
                oi_str = f"{int(opt.oi):,}" if opt.oi is not None else "—"
                vol_str = f"{int(opt.volume):,}" if opt.volume is not None else "—"
                
                tbl.add_row(
                    str(i),
                    opt.symbol,
                    opt.expiry.isoformat(),
                    str(int(opt.dte_days)),
                    f"${float(opt.strike):.2f}",
                    f"${float(opt.price):.2f}",
                    f"${float(opt.premium_usd):,.0f}",
                    f"{float(opt.delta):.2f}" if opt.delta else "n/a",
                    f"{float(opt.theta):.3f}" if opt.theta else "n/a",
                    oi_str,
                    vol_str,
                    f"{sc:.2f}",
                )
            
            console.print(tbl)
            console.print(f"\n[dim]Tip: Use --budget <amount> to filter and pick the best option under your budget.[/dim]")
            raise typer.Exit(code=0)

        # With budget: pick the single best option
        best = pick_best_delta_theta(
            opts,
            target_abs_delta=float(target_abs_delta),
            delta_weight=float(delta_weight),
            theta_weight=float(theta_weight),
        )
        if best is None:
            print("[yellow]No contract selected[/yellow]")
            raise typer.Exit(code=0)

        move5 = required_underlying_move_for_profit_pct(
            opt_entry_price=float(best.price),
            delta=float(best.delta) if best.delta else None,
            profit_pct=0.05,
            underlying_px=und_px,
            opt_type=str(best.opt_type),
        )

        qty = 1
        try:
            if float(best.premium_usd) > 0:
                qty = max(1, int(float(max_premium_usd) // float(best.premium_usd)))
        except Exception:
            pass

        # Display
        tbl = Table(title=f"Pick: {ticker.upper()} {w.upper()} under ${max_premium_usd:.0f}")
        tbl.add_column("Underlying", style="bold")
        tbl.add_column("Und px", justify="right")
        tbl.add_column("Contract", style="bold")
        tbl.add_column("Exp")
        tbl.add_column("DTE", justify="right")
        tbl.add_column("Strike", justify="right")
        tbl.add_column("Price", justify="right")
        tbl.add_column("Premium", justify="right")
        tbl.add_column("Δ", justify="right")
        tbl.add_column("Θ", justify="right")
        tbl.add_column("OI", justify="right")
        tbl.add_column("Vol", justify="right")
        tbl.add_column("Move@+5%", justify="right")
        tbl.add_column("Qty", justify="right")

        sp = (100.0 * float(best.spread_pct)) if best.spread_pct else None
        oi_str = f"{int(best.oi):,}" if best.oi is not None else "—"
        vol_str = f"{int(best.volume):,}" if best.volume is not None else "—"
        
        tbl.add_row(
            best.ticker,
            "—" if und_px is None else f"${und_px:.2f}",
            best.symbol,
            best.expiry.isoformat(),
            str(int(best.dte_days)),
            f"{float(best.strike):.2f}",
            f"{float(best.price):.2f}",
            f"${float(best.premium_usd):,.0f}",
            f"{float(best.delta):.2f}" if best.delta else "n/a",
            f"{float(best.theta):.3f}" if best.theta else "n/a",
            oi_str,
            vol_str,
            format_required_move(move5),
            str(int(qty)),
        )
        console.print(tbl)

        label = "LIVE" if live_ok else "PAPER"
        if typer.confirm(f"Execute: BUY {qty}x {best.symbol}? [{label}]", default=False):
            if not execute:
                print("[dim]DRY RUN[/dim]: add --execute to submit")
                raise typer.Exit(code=0)

            try:
                resp = submit_option_order(
                    trading=trading,
                    symbol=str(best.symbol),
                    qty=int(qty),
                    side="buy",
                    limit_price=float(best.price),
                    tif="day",
                )
                print(f"[green]Submitted {label}[/green]: {resp}")
            except Exception as e:
                print(f"[red]Order failed[/red]: {e}")
                raise typer.Exit(code=2)
