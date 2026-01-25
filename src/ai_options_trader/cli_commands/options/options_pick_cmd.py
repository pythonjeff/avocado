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
from ai_options_trader.execution.alpaca import submit_option_order
from ai_options_trader.options.budget_scan import (
    affordable_options_for_ticker,
    pick_best_delta_theta,
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
        max_premium_usd: float = typer.Option(
            0.0, "--max-premium",
            help="Max premium (USD). If 0, compute from Alpaca cash via --budget-pct.",
        ),
        budget_pct: float = typer.Option(
            0.10, "--budget-pct",
            help="(when --max-premium=0) Budget as % of account cash",
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
        execute: bool = typer.Option(False, "--execute"),
        live: bool = typer.Option(False, "--live"),
    ):
        """
        Pick ONE option contract optimized for delta and theta.
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

        # Dynamic budget
        if float(max_premium_usd) <= 0:
            cash = 0.0
            try:
                acct = trading.get_account()
                cash = float(getattr(acct, "cash", 0.0) or 0.0)
            except Exception:
                pass
            pct = max(0.0, min(1.0, float(budget_pct)))
            max_premium_usd = max(0.0, pct * cash)
            print(f"[dim]Budget: {pct:.0%} of ${cash:,.2f} = ${max_premium_usd:,.2f}[/dim]")
            if max_premium_usd <= 0:
                print("[yellow]No budget available[/yellow]")
                raise typer.Exit(code=0)

        chain = fetch_option_chain(data, ticker, feed=settings.alpaca_options_feed)
        candidates = list(to_candidates(chain, ticker))
        if not candidates:
            print(f"[yellow]No options for {ticker}[/yellow]")
            raise typer.Exit(code=0)

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
            print("[yellow]No contracts matched[/yellow]. Try widening constraints.")
            raise typer.Exit(code=0)

        best = pick_best_delta_theta(
            opts,
            target_abs_delta=float(target_abs_delta),
            delta_weight=float(delta_weight),
            theta_weight=float(theta_weight),
        )
        if best is None:
            print("[yellow]No contract selected[/yellow]")
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
        tbl.add_column("Move@+5%", justify="right")
        tbl.add_column("Qty", justify="right")

        sp = (100.0 * float(best.spread_pct)) if best.spread_pct else None
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
