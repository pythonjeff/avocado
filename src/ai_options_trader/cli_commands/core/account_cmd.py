from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel

from datetime import datetime, timedelta, timezone

from ai_options_trader.config import load_settings
from ai_options_trader.data.alpaca import make_clients
from ai_options_trader.overlay.context import build_trackers, extract_underlyings, fetch_calendar_events, fetch_news_payload
from ai_options_trader.data.quotes import fetch_stock_last_prices


def _to_float(x) -> float | None:
    try:
        return float(x) if x is not None else None
    except Exception:
        return None


def register(app: typer.Typer) -> None:
    account_app = typer.Typer(add_completion=False, help="Account tools")
    app.add_typer(account_app, name="account")

    def _account_panel(console: Console) -> None:
        settings = load_settings()
        trading, _data = make_clients(settings)
        mode = "PAPER" if bool(settings.alpaca_paper) else "LIVE"
        try:
            acct = trading.get_account()
        except Exception as e:
            raise RuntimeError(
                f"Alpaca authorization failed (mode={mode}). "
                "Most common cause: ALPACA_PAPER=false but you're using PAPER keys. "
                "Fix by setting ALPACA_PAPER=true, or by creating LIVE keys and setting ALPACA_API_KEY/ALPACA_API_SECRET."
            ) from e

        cash = _to_float(getattr(acct, "cash", None)) or 0.0
        equity = _to_float(getattr(acct, "equity", None)) or 0.0
        bp = _to_float(getattr(acct, "buying_power", None)) or 0.0
        opt_bp = _to_float(getattr(acct, "options_buying_power", None))
        # Some Alpaca accounts expose these fields; best-effort only.
        cash_withdrawable = _to_float(getattr(acct, "cash_withdrawable", None))
        cash_transferable = _to_float(getattr(acct, "cash_transferable", None))

        console.print(
            Panel(
                f"[b]Mode:[/b] {mode}\n"
                f"[b]Cash:[/b] ${cash:,.2f}\n"
                f"[b]Equity:[/b] ${equity:,.2f}\n"
                f"[b]Buying power:[/b] ${bp:,.2f}\n"
                f"[b]Options BP:[/b] {('n/a' if opt_bp is None else f'${opt_bp:,.2f}')}\n"
                f"[b]Cash withdrawable:[/b] {('n/a' if cash_withdrawable is None else f'${cash_withdrawable:,.2f}')}\n"
                f"[b]Cash transferable:[/b] {('n/a' if cash_transferable is None else f'${cash_transferable:,.2f}')}",
                title="Alpaca account",
                expand=False,
            )
        )

    @account_app.callback(invoke_without_command=True)
    def account_root(ctx: typer.Context):
        """
        Verify Alpaca connectivity and print current capital.

        Uses `ALPACA_PAPER` to choose paper vs live.
        """
        if ctx.invoked_subcommand is not None:
            return
        console = Console()
        _account_panel(console)

    @account_app.command("summary")
    def account_summary(
        orders: int = typer.Option(10, "--orders", help="Best-effort: include this many recent closed orders (0 disables)"),
        news: bool = typer.Option(True, "--news/--no-news", help="Include recent headlines + reading links (FMP) and sentiment"),
        news_days: int = typer.Option(7, "--news-days", help="Lookback window (days) for news"),
        news_max_items: int = typer.Option(18, "--news-max-items", help="Max news items to include in the LLM payload"),
        calendar_days: int = typer.Option(10, "--calendar-days", help="How many days ahead to include economic calendar events"),
        calendar_max_items: int = typer.Option(18, "--calendar-max-items", help="Max calendar events to include"),
        model: str = typer.Option("", "--model", help="Optional OpenAI model override"),
        temperature: float = typer.Option(0.2, "--temperature", help="LLM temperature"),
    ):
        """
        LLM summary of your account + open positions: trades, themes, and risks to watch.
        """
        settings = load_settings()
        console = Console()
        trading, _data = make_clients(settings)

        acct = trading.get_account()
        cash = _to_float(getattr(acct, "cash", None)) or 0.0
        equity = _to_float(getattr(acct, "equity", None)) or 0.0
        bp = _to_float(getattr(acct, "buying_power", None)) or 0.0
        opt_bp = _to_float(getattr(acct, "options_buying_power", None))
        mode = "PAPER" if bool(settings.alpaca_paper) else "LIVE"

        # Positions
        raw_positions = trading.get_all_positions()
        positions: list[dict] = []
        for p in raw_positions:
            positions.append(
                {
                    "symbol": getattr(p, "symbol", ""),
                    "qty": _to_float(getattr(p, "qty", None)),
                    "avg_entry_price": _to_float(getattr(p, "avg_entry_price", None)),
                    "current_price": _to_float(getattr(p, "current_price", None)),
                    "unrealized_pl": _to_float(getattr(p, "unrealized_pl", None)),
                    "unrealized_plpc": _to_float(getattr(p, "unrealized_plpc", None)),
                }
            )

        held = extract_underlyings([str(p.get("symbol") or "") for p in positions])

        # Best-effort recent orders (Alpaca SDK versions differ; tolerate absence).
        recent_orders: list[dict] = []
        if int(orders) > 0:
            try:
                from alpaca.trading.requests import GetOrdersRequest  # type: ignore
                from alpaca.trading.enums import QueryOrderStatus  # type: ignore

                req = GetOrdersRequest(status=QueryOrderStatus.CLOSED, limit=int(orders), nested=True)
                ords = trading.get_orders(req)
                for o in ords or []:
                    recent_orders.append(
                        {
                            "id": getattr(o, "id", None),
                            "symbol": getattr(o, "symbol", None),
                            "side": str(getattr(o, "side", None) or ""),
                            "type": str(getattr(o, "type", None) or ""),
                            "qty": str(getattr(o, "qty", None) or ""),
                            "filled_qty": str(getattr(o, "filled_qty", None) or ""),
                            "filled_avg_price": str(getattr(o, "filled_avg_price", None) or ""),
                            "status": str(getattr(o, "status", None) or ""),
                            "submitted_at": str(getattr(o, "submitted_at", None) or ""),
                            "filled_at": str(getattr(o, "filled_at", None) or ""),
                        }
                    )
            except Exception:
                recent_orders = []

        from ai_options_trader.llm.account_summary import llm_account_summary
        # Risk watch: current trackers + upcoming econ events (best-effort; uses caches where available).
        _feat_row, risk_watch = build_trackers(settings=settings, start_date="2012-01-01", refresh_fred=False)
        try:
            risk_watch["events"] = fetch_calendar_events(settings=settings, days_ahead=int(calendar_days), max_items=int(calendar_max_items))
        except Exception:
            risk_watch["events"] = []

        # News + sentiment (URLs for "reading list").
        news_payload: dict = {}
        if bool(news) and held:
            try:
                news_payload = fetch_news_payload(
                    settings=settings,
                    tickers=sorted(held),
                    lookback_days=int(news_days),
                    max_items=int(news_max_items),
                )
            except Exception:
                news_payload = {}

        asof = datetime.now(timezone.utc).date().isoformat()
        text = llm_account_summary(
            settings=settings,
            asof=asof,
            account={"mode": mode, "cash": cash, "equity": equity, "buying_power": bp, "options_buying_power": opt_bp},
            positions=positions,
            recent_orders=recent_orders,
            risk_watch=risk_watch,
            news=news_payload,
            model=(model.strip() or None),
            temperature=float(temperature),
        )
        console.print(Panel(text, title="Account summary (LLM)", expand=False))


    @account_app.command("buy-shares")
    def buy_shares(
        ticker: str = typer.Option(..., "--ticker", "-t", help="Equity/ETF symbol (e.g., SQQQ)"),
        pct_cash: float = typer.Option(1.0, "--pct-cash", help="Percent of Alpaca cash to spend (0..1). Default 1.0 = all cash."),
        usd: float = typer.Option(0.0, "--usd", help="Optional override: spend exactly $USD (overrides --pct-cash)."),
        execute: bool = typer.Option(False, "--execute", help="If set, can submit the order after confirmation (paper by default; use --live for live)."),
        live: bool = typer.Option(False, "--live", help="Allow LIVE execution when ALPACA_PAPER is false (guarded with extra confirmations)."),
    ):
        """
        Buy shares using a notional budget derived from your Alpaca cash (default: 100%).

        This uses a NOTIONAL market order when supported (fractional shares),
        with a fallback to whole-share qty when notional is unavailable.
        """
        settings = load_settings()
        console = Console()
        trading, _data = make_clients(settings)
        mode = "PAPER" if bool(settings.alpaca_paper) else "LIVE"
        live_ok = bool(live) and (not bool(settings.alpaca_paper))
        if execute and (not settings.alpaca_paper) and (not live_ok):
            console.print(
                Panel(
                    "[red]Refusing to execute[/red] because ALPACA_PAPER is false.\n"
                    "If you intend LIVE trading, re-run with [b]--live --execute[/b].",
                    title="Safety",
                    expand=False,
                )
            )
            raise typer.Exit(code=1)
        if execute and live_ok:
            console.print(
                Panel(
                    "[yellow]LIVE MODE ENABLED[/yellow]\n"
                    "Orders will be submitted to your LIVE Alpaca account.\n"
                    "You will be asked to confirm again before submission.",
                    title="Safety",
                    expand=False,
                )
            )
            if not typer.confirm("Confirm LIVE mode (ALPACA_PAPER=false) and proceed?", default=False):
                raise typer.Exit(code=0)
            if not typer.confirm("Second confirmation: proceed with LIVE trading now?", default=False):
                raise typer.Exit(code=0)

        acct = trading.get_account()
        cash = _to_float(getattr(acct, "cash", None)) or 0.0
        pct = float(max(0.0, min(1.0, float(pct_cash))))
        budget = float(usd) if float(usd) > 0 else float(pct * cash)
        budget = float(max(0.0, budget))
        if budget <= 0:
            console.print(Panel("Budget is $0. Set --usd or ensure cash is available.", title="Budget", expand=False))
            raise typer.Exit(code=0)

        sym = str(ticker).strip().upper()
        # Best-effort live-ish underlying price (for preview + qty fallback)
        px = None
        try:
            last_px, _asof_map, _src = fetch_stock_last_prices(settings=settings, symbols=[sym], max_symbols_for_live=5)
            px = last_px.get(sym)
        except Exception:
            px = None

        console.print(
            Panel(
                f"[b]Mode:[/b] {mode}\n"
                f"[b]Cash:[/b] ${cash:,.2f}\n"
                f"[b]Budget:[/b] ${budget:,.2f} ({pct:.0%} of cash)\n"
                f"[b]Ticker:[/b] {sym}\n"
                f"[b]Last px:[/b] {('—' if px is None else f'${px:.2f}')}\n",
                title="Order preview",
                expand=False,
            )
        )
        label = "LIVE" if live_ok else "PAPER"
        if not typer.confirm(f"Execute: BUY {sym} using ~${budget:,.2f} notional? [{label}]", default=False):
            raise typer.Exit(code=0)

        if not execute:
            console.print("[dim]DRY RUN[/dim]: re-run with `--execute` to submit this order.")
            raise typer.Exit(code=0)

        # Submit: prefer notional market order (fractional shares). Fallback to whole-share qty.
        try:
            from ai_options_trader.execution.alpaca import submit_equity_notional_order, submit_equity_order

            try:
                resp = submit_equity_notional_order(trading=trading, symbol=sym, notional=float(budget), side="buy", tif="day")
                console.print(f"[green]Submitted {label} notional order[/green]: {resp}")
                raise typer.Exit(code=0)
            except TypeError:
                # SDK doesn't accept notional; fall back to qty.
                pass

            if px is None or float(px) <= 0:
                console.print("[yellow]Cannot compute qty fallback[/yellow] (missing price).")
                raise typer.Exit(code=2)
            qty = int(float(budget) // float(px))
            qty = max(1, qty)
            resp = submit_equity_order(trading=trading, symbol=sym, qty=int(qty), side="buy", limit_price=None, tif="day")
            console.print(f"[green]Submitted {label} qty order[/green]: {resp}")
        except Exception as e:
            console.print(f"[red]Order submission failed[/red]: {type(e).__name__}: {e}")
            raise typer.Exit(code=2)