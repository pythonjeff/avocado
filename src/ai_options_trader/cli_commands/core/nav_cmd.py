from __future__ import annotations

import typer
import re
from rich.console import Console
from rich.panel import Panel
from rich.table import Table


def _to_float(x) -> float | None:
    try:
        if x is None:
            return None
        return float(x)
    except Exception:
        return None


def register(nav_app: typer.Typer) -> None:
    investor_app = typer.Typer(add_completion=False, help="Investor ledger (initials + amounts) using unitized NAV", invoke_without_command=True)
    nav_app.add_typer(investor_app, name="investor")

    @investor_app.callback()
    def investor_default(ctx: typer.Context):
        """Show investor ownership (shortcut for `lox nav investor report`)."""
        if ctx.invoked_subcommand is None:
            # No subcommand given - show quick summary
            _show_investor_summary()

    def _show_investor_summary():
        """Quick investor summary when no subcommand given."""
        from ai_options_trader.nav.investors import investor_report, default_investor_flows_path
        from ai_options_trader.nav.store import default_nav_sheet_path
        
        c = Console()
        path_sheet = default_nav_sheet_path()
        path_inv = default_investor_flows_path()
        
        try:
            rep = investor_report(nav_sheet_path=path_sheet, investor_flows_path=path_inv)
        except Exception as e:
            c.print(f"[red]Error loading investor data:[/red] {e}")
            c.print("[dim]Try: lox nav investor seed 'JL:1000,TG:500'[/dim]")
            return
        
        rows = rep.get("rows") or []
        if not rows:
            c.print(Panel(
                "No investors yet.\n"
                "Seed with: lox nav investor seed 'JL:1000,TG:500'",
                title="Investors",
                expand=False,
            ))
            return
        
        # Summary header
        nav_per_unit = float(rep.get("nav_per_unit") or 1.0)
        equity = float(rep.get("equity") or 0.0)
        asof = rep.get("asof") or "—"
        
        c.print(Panel(
            f"Equity: ${equity:,.2f} | NAV/Unit: {nav_per_unit:.4f} | As of: {str(asof)[:19]}",
            title="Investor Summary",
            expand=False,
        ))
        
        # Investor table
        tbl = Table()
        tbl.add_column("Investor", style="bold cyan")
        tbl.add_column("Ownership", justify="right")
        tbl.add_column("Value", justify="right", style="green")
        tbl.add_column("P&L", justify="right")
        tbl.add_column("Return", justify="right")
        
        for r in rows:
            own = r.get("ownership")
            ret = r.get("return")
            pnl = float(r.get("pnl") or 0.0)
            pnl_style = "green" if pnl >= 0 else "red"
            
            tbl.add_row(
                str(r.get("code") or ""),
                "—" if own is None else f"{float(own)*100:.1f}%",
                f"${float(r.get('value') or 0.0):,.2f}",
                f"[{pnl_style}]${pnl:+,.2f}[/{pnl_style}]",
                "—" if ret is None else f"{float(ret)*100:+.1f}%",
            )
        
        c.print(tbl)
        c.print("[dim]For detailed report: lox nav investor report[/dim]")

    @nav_app.command("summary")
    def nav_summary():
        """
        Quick NAV summary with investor ownership.
        
        This is the easiest way to see current NAV and who owns what.
        """
        from ai_options_trader.config import load_settings
        from ai_options_trader.data.alpaca import make_clients
        from ai_options_trader.nav.investors import investor_report, default_investor_flows_path
        from ai_options_trader.nav.store import default_nav_sheet_path
        
        c = Console()
        settings = load_settings()
        
        # Get live account data
        try:
            trading, _data = make_clients(settings)
            acct = trading.get_account()
            equity = _to_float(getattr(acct, "equity", None)) or 0.0
            cash = _to_float(getattr(acct, "cash", None)) or 0.0
        except Exception as e:
            c.print(f"[red]Failed to connect to Alpaca:[/red] {e}")
            raise typer.Exit(1)
        
        # Get investor report
        path_sheet = default_nav_sheet_path()
        path_inv = default_investor_flows_path()
        
        try:
            rep = investor_report(nav_sheet_path=path_sheet, investor_flows_path=path_inv)
        except Exception:
            rep = {}
        
        # NAV header
        nav_per_unit = float(rep.get("nav_per_unit") or 1.0)
        total_units = float(rep.get("total_units") or 0.0)
        asof = rep.get("asof") or "—"
        
        c.print(Panel(
            f"[bold]Live Equity:[/bold] ${equity:,.2f}\n"
            f"[bold]Cash:[/bold] ${cash:,.2f}\n"
            f"[bold]NAV/Unit:[/bold] {nav_per_unit:.4f}\n"
            f"[bold]Last Snapshot:[/bold] {str(asof)[:19]}",
            title="NAV Summary",
            expand=False,
        ))
        
        # Investor table
        rows = rep.get("rows") or []
        if not rows:
            c.print(Panel(
                "No investors yet.\n"
                "Seed with: lox nav investor seed 'JL:1000,TG:500'",
                title="Investors",
                expand=False,
            ))
            return
        
        tbl = Table(title="Investor Ownership")
        tbl.add_column("Investor", style="bold cyan")
        tbl.add_column("Ownership", justify="right")
        tbl.add_column("Value", justify="right", style="green")
        tbl.add_column("Basis", justify="right")
        tbl.add_column("P&L", justify="right")
        tbl.add_column("Return", justify="right")
        
        for r in rows:
            own = r.get("ownership")
            ret = r.get("return")
            pnl = float(r.get("pnl") or 0.0)
            pnl_style = "green" if pnl >= 0 else "red"
            
            tbl.add_row(
                str(r.get("code") or ""),
                "—" if own is None else f"{float(own)*100:.1f}%",
                f"${float(r.get('value') or 0.0):,.2f}",
                f"${float(r.get('basis') or 0.0):,.2f}",
                f"[{pnl_style}]${pnl:+,.2f}[/{pnl_style}]",
                "—" if ret is None else f"{float(ret)*100:+.1f}%",
            )
        
        c.print(tbl)
        
        # Quick commands hint
        c.print(Panel(
            "[dim]Quick commands:[/dim]\n"
            "  lox nav snapshot              # Record NAV point\n"
            "  lox nav investor contribute JL 500  # Add investment\n"
            "  lox nav investor report       # Detailed report",
            expand=False,
        ))

    @nav_app.command("flow")
    def nav_flow(
        amount: float = typer.Argument(..., help="Signed USD amount. Deposit=positive, withdrawal=negative."),
        note: str = typer.Option("", "--note", help="Optional note (e.g., 'added funds' / 'withdrew')."),
        ts: str = typer.Option("", "--ts", help="Optional ISO timestamp (defaults to now UTC)."),
        flows_path: str = typer.Option("", "--flows-path", help="Override AOT_NAV_FLOWS (CSV)."),
    ):
        """Log a user cashflow (deposit/withdrawal) used to compute NAV returns."""
        from ai_options_trader.nav.store import append_cashflow

        path = append_cashflow(ts=ts or None, amount=float(amount), note=note, path=flows_path or None)
        Console().print(Panel(f"Logged cashflow: {amount:+.2f}\nflows: {path}", title="NAV flow", expand=False))
        Console().print(
            Panel(
                "Note: This updates the fund cashflow ledger only.\n"
                "For investor deposits/withdrawals that must also update ownership, use:\n"
                "`lox nav investor contribute ...`",
                title="Ledger note",
                expand=False,
            )
        )

    @investor_app.command("seed")
    def investor_seed(
        entries: str = typer.Argument(..., help='Comma-separated entries like "JL:75,TG:100,MG:100"'),
        note: str = typer.Option("seed", "--note"),
        ts: str = typer.Option("", "--ts", help="Optional ISO timestamp (defaults to now UTC)."),
        investor_flows_path: str = typer.Option("", "--investor-flows-path", help="Override AOT_NAV_INVESTOR_FLOWS (CSV)."),
    ):
        """Seed initial investor contributions from a compact string."""
        from ai_options_trader.nav.investors import append_investor_flow

        c = Console()
        pairs = [p.strip() for p in entries.split(",") if p.strip()]
        if not pairs:
            raise typer.BadParameter("No entries parsed.")
        written = 0
        for p in pairs:
            if ":" not in p:
                raise typer.BadParameter(f"Bad entry '{p}'. Expected CODE:AMOUNT.")
            code, amt = p.split(":", 1)
            code = code.strip().upper()
            if not code:
                raise typer.BadParameter(f"Bad code in '{p}'.")
            try:
                amount = float(amt.strip().replace("$", ""))
            except Exception:
                raise typer.BadParameter(f"Bad amount in '{p}'.")
            append_investor_flow(code=code, amount=amount, note=note, ts=ts or None, path=investor_flows_path or None)
            written += 1
        c.print(Panel(f"Seeded {written} investor flow(s).", title="NAV investor seed", expand=False))

    @investor_app.command("flow")
    def investor_flow(
        code: str = typer.Argument(..., help="Investor code/initials (e.g., JL)"),
        amount: float = typer.Argument(..., help="Signed USD amount. Deposit=positive, withdrawal=negative."),
        note: str = typer.Option("", "--note"),
        ts: str = typer.Option("", "--ts", help="Optional ISO timestamp (defaults to now UTC)."),
        investor_flows_path: str = typer.Option("", "--investor-flows-path", help="Override AOT_NAV_INVESTOR_FLOWS (CSV)."),
    ):
        """Log an investor deposit/withdrawal (internal ledger)."""
        from ai_options_trader.nav.investors import append_investor_flow

        path = append_investor_flow(code=code, amount=float(amount), note=note, ts=ts or None, path=investor_flows_path or None)
        Console().print(
            Panel(f"Logged investor flow: {code.upper()} {amount:+.2f}\nflows: {path}", title="NAV investor flow", expand=False)
        )
        Console().print(
            Panel(
                "Note: This updates the investor ledger only.\n"
                "If this is a real cash contribution/withdrawal, also log the fund cashflow with:\n"
                "`lox nav flow ...` or use `lox nav investor contribute ...` to update both in one step.",
                title="Ledger note",
                expand=False,
            )
        )

    @investor_app.command("report")
    def investor_report_cmd(
        sheet_path: str = typer.Option("", "--sheet-path", help="Override AOT_NAV_SHEET (CSV)."),
        investor_flows_path: str = typer.Option("", "--investor-flows-path", help="Override AOT_NAV_INVESTOR_FLOWS (CSV)."),
        orders_csv: str = typer.Option("", "--orders-csv", help="Optional Alpaca Orders CSV export to compute realized P&L for closed trades."),
        crypto_orders_csv: str = typer.Option("", "--crypto-orders-csv", help="Optional Alpaca Crypto Orders CSV export (for closed crypto trades)."),
        days: int = typer.Option(30, "--days", help="Lookback window (days) for recent trades section."),
        debug: bool = typer.Option(False, "--debug", help="Print debug counts for activities/orders/fills."),
    ):
        """Show investor ownership + P&L using unitized NAV."""
        from ai_options_trader.nav.investors import investor_report, default_investor_flows_path, read_investor_flows
        from ai_options_trader.nav.store import default_nav_sheet_path
        from ai_options_trader.nav.store import _parse_ts

        path_sheet = sheet_path or default_nav_sheet_path()
        path_inv = investor_flows_path or default_investor_flows_path()
        rep = investor_report(nav_sheet_path=path_sheet, investor_flows_path=path_inv)

        c = Console()
        c.print(
            Panel(
                f"asof: {rep.get('asof')}\n"
                f"equity=${float(rep.get('equity') or 0.0):,.2f}\n"
                f"nav_per_unit={float(rep.get('nav_per_unit') or 0.0):.6f}  total_units={float(rep.get('total_units') or 0.0):.6f}\n"
                f"sheet: {path_sheet}\n"
                f"investor_flows: {path_inv}",
                title="NAV investor report",
                expand=False,
            )
        )

        rows = rep.get("rows") or []
        if not rows:
            c.print(Panel("No investor flows yet. Use `lox nav investor seed ...`", title="NAV", expand=False))
            raise typer.Exit(code=0)

        # Show investor flows since the latest NAV snapshot (these should not affect other investors' PnL if timestamped properly).
        try:
            asof = rep.get("asof")
            if asof:
                t0 = _parse_ts(str(asof))
                flows = read_investor_flows(path=path_inv)
                recent = [f for f in flows if _parse_ts(f.ts) > t0]
                if recent:
                    lines = []
                    for f in recent[-10:]:
                        lines.append(f"- {f.ts[:19]}  {f.code}  {float(f.amount):+,.2f}  {f.note or ''}".rstrip())
                    c.print(
                        Panel(
                            "Recent investor flows since last NAV snapshot (priced at the last NAV-per-unit once you run the next `lox nav snapshot`):\n"
                            + "\n".join(lines),
                            title="Recent investor flows (since NAV asof)",
                            expand=False,
                        )
                    )
        except Exception:
            pass

        tbl = Table(title="Investor ledger (unitized)")
        tbl.add_column("code", style="bold")
        tbl.add_column("ownership", justify="right")
        tbl.add_column("basis", justify="right")
        tbl.add_column("value", justify="right")
        tbl.add_column("pnl", justify="right")
        tbl.add_column("return", justify="right")
        for r in rows:
            own = r.get("ownership")
            ret = r.get("return")
            tbl.add_row(
                str(r.get("code") or ""),
                "—" if own is None else f"{float(own)*100:.1f}%",
                f"{float(r.get('basis') or 0.0):,.2f}",
                f"{float(r.get('value') or 0.0):,.2f}",
                f"{float(r.get('pnl') or 0.0):+,.2f}",
                "—" if ret is None else f"{float(ret)*100:+.1f}%",
            )
        c.print(tbl)

        # Best-effort: recent trade P&L snapshot (last 30 days, open + closed).
        try:
            from ai_options_trader.config import load_settings
            from ai_options_trader.data.alpaca import make_clients
            from ai_options_trader.nav.store import _parse_ts
            from datetime import datetime, timezone, timedelta

            settings = load_settings()
            trading, _data = make_clients(settings)
            positions = trading.get_all_positions()

            pos_rows = []
            for p in positions or []:
                sym = str(getattr(p, "symbol", "") or "")
                if not sym:
                    continue
                pnl = _to_float(getattr(p, "unrealized_pl", None))
                pnlpc = _to_float(getattr(p, "unrealized_plpc", None))
                qty = _to_float(getattr(p, "qty", None))
                if pnl is None:
                    continue
                pos_rows.append({
                    "symbol": sym,
                    "pnl": float(pnl),
                    "pnlpc": pnlpc,
                    "qty": qty,
                    "status": "open",
                })

            lookback_days = max(1, int(days))
            cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
            # For realized P&L we need entry fills that may predate the report window.
            fills_lookback_days = max(lookback_days, 365)
            fills_cutoff = datetime.now(timezone.utc) - timedelta(days=fills_lookback_days)

            # Pull recent closed orders to infer "recent" symbols for open positions.
            last_order: dict[str, datetime] = {}
            try:
                from alpaca.trading.requests import GetOrdersRequest  # type: ignore
                from alpaca.trading.enums import QueryOrderStatus  # type: ignore

                req = GetOrdersRequest(status=QueryOrderStatus.CLOSED, limit=200, nested=True)
                ords = trading.get_orders(req)
                for o in ords or []:
                    sym = str(getattr(o, "symbol", "") or "")
                    if not sym:
                        continue
                    ts = (
                        getattr(o, "filled_at", None)
                        or getattr(o, "submitted_at", None)
                        or getattr(o, "created_at", None)
                    )
                    if not ts:
                        continue
                    dt = _parse_ts(str(ts))
                    if dt < cutoff:
                        continue
                    prev = last_order.get(sym)
                    if prev is None or dt > prev:
                        last_order[sym] = dt
            except Exception:
                last_order = {}

            # Build realized P&L from fills/orders (best-effort FIFO).
            closed_rows = []
            try:
                def _act_time(ts_val) -> datetime:
                    if not ts_val:
                        return datetime.min.replace(tzinfo=timezone.utc)
                    return _parse_ts(str(ts_val))

                def _to_f(x):
                    try:
                        return float(x) if x is not None else None
                    except Exception:
                        return None

                def _get(a, key: str):
                    if isinstance(a, dict):
                        return a.get(key)
                    return getattr(a, key, None)

                def _sym_from(obj) -> str:
                    sym = (
                        _get(obj, "symbol")
                        or _get(obj, "option_symbol")
                        or _get(obj, "option_symbol_id")
                        or ""
                    )
                    return str(sym or "")

                def _is_occ(sym: str) -> bool:
                    return bool(re.search(r"\d{6}[CP]\d{8}$", sym))

                def _price_mult(sym: str) -> float:
                    return 100.0 if _is_occ(sym) else 1.0

                fills = []

                # 1) Account activities (fills) if available.
                activities = []
                try:
                    from alpaca.trading.requests import GetAccountActivitiesRequest  # type: ignore
                    try:
                        from alpaca.trading.enums import ActivityType  # type: ignore
                        act_types = [ActivityType.FILL]
                    except Exception:
                        act_types = ["FILL"]

                    req = GetAccountActivitiesRequest(
                        activity_types=act_types,
                        after=fills_cutoff.date().isoformat(),
                        direction="asc",
                        page_size=500,
                    )
                    activities = trading.get_account_activities(req) or []
                except Exception:
                    try:
                        activities = trading.get_activities(activity_types="FILL", after=fills_cutoff.date().isoformat()) or []
                    except Exception:
                        activities = []

                if not activities:
                    try:
                        activities = trading.get_account_activities() or []
                    except Exception:
                        try:
                            activities = trading.get_activities() or []
                        except Exception:
                            activities = []

                for a in activities:
                    sym = _sym_from(a)
                    if not sym:
                        continue
                    side = str(_get(a, "side") or "").lower()
                    qty = _to_f(_get(a, "qty") or _get(a, "quantity"))
                    price = _to_f(_get(a, "price"))
                    ts = (
                        _get(a, "transaction_time")
                        or _get(a, "timestamp")
                        or _get(a, "created_at")
                    )
                    act_type = str(_get(a, "activity_type") or _get(a, "type") or "").lower()
                    if act_type and act_type not in {"fill", "partial_fill", "fill"}:
                        continue
                    if qty is None or price is None:
                        continue
                    dt = _act_time(ts)
                    if dt < fills_cutoff:
                        continue
                    mult = _price_mult(sym)
                    fills.append({
                        "symbol": sym,
                        "side": side,
                        "qty": abs(float(qty)),
                        "price": float(price) * mult,
                        "ts": dt,
                    })

                # 2) Orders page (filled orders only). Handles options legs when present.
                ords = []
                try:
                    from alpaca.trading.requests import GetOrdersRequest  # type: ignore
                    from alpaca.trading.enums import QueryOrderStatus  # type: ignore

                    status_val = getattr(QueryOrderStatus, "ALL", QueryOrderStatus.CLOSED)
                    req = GetOrdersRequest(status=status_val, limit=500, nested=True)
                    ords = trading.get_orders(req) or []
                    for o in ords:
                        legs = getattr(o, "legs", None)
                        if legs:
                            for leg in legs:
                                sym = _sym_from(leg) or _sym_from(o)
                                if not sym:
                                    continue
                                side = str(_get(leg, "side") or _get(o, "side") or "").lower()
                                qty = _to_f(_get(leg, "filled_qty") or _get(leg, "qty") or _get(o, "filled_qty") or _get(o, "qty"))
                                price = _to_f(_get(leg, "filled_avg_price") or _get(leg, "price") or _get(o, "filled_avg_price") or _get(o, "price"))
                                status = str(_get(leg, "status") or _get(o, "status") or "").lower()
                                ts = (
                                    _get(leg, "filled_at")
                                    or _get(leg, "submitted_at")
                                    or _get(o, "filled_at")
                                    or _get(o, "submitted_at")
                                    or _get(o, "created_at")
                                )
                                if qty is None or price is None or not ts:
                                    continue
                                if status and status not in {"filled", "partially_filled"}:
                                    continue
                                dt = _act_time(ts)
                                if dt < fills_cutoff:
                                    continue
                                mult = _price_mult(sym)
                                fills.append({
                                    "symbol": sym,
                                    "side": side,
                                    "qty": abs(float(qty)),
                                    "price": float(price) * mult,
                                    "ts": dt,
                                })
                        else:
                            sym = _sym_from(o)
                            if not sym:
                                continue
                            side = str(_get(o, "side") or "").lower()
                            qty = _to_f(_get(o, "filled_qty") or _get(o, "qty"))
                            price = _to_f(_get(o, "filled_avg_price") or _get(o, "price"))
                            status = str(_get(o, "status") or "").lower()
                            ts = (
                                _get(o, "filled_at")
                                or _get(o, "submitted_at")
                                or _get(o, "created_at")
                            )
                            if qty is None or price is None or not ts:
                                continue
                            if status and status not in {"filled", "partially_filled"}:
                                continue
                            dt = _act_time(ts)
                            if dt < fills_cutoff:
                                continue
                            mult = _price_mult(sym)
                            fills.append({
                                "symbol": sym,
                                "side": side,
                                "qty": abs(float(qty)),
                                "price": float(price) * mult,
                                "ts": dt,
                            })
                except Exception:
                    ords = []

                # Optional: merge in Alpaca Orders CSV export (UI)
                if orders_csv:
                    try:
                        import csv
                        from pathlib import Path as _P

                        p = _P(orders_csv)
                        if p.exists():
                            with p.open(newline="") as f:
                                reader = csv.DictReader(f)
                                for row in reader:
                                    r = {str(k).strip().lower(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()}
                                    sym = str(
                                        r.get("symbol")
                                        or r.get("option_symbol")
                                        or r.get("option symbol")
                                        or ""
                                    )
                                    side = str(r.get("side") or "").lower()
                                    status = str(r.get("status") or "").lower()
                                    qty = _to_f(r.get("filled_qty") or r.get("filled quantity") or r.get("qty") or r.get("quantity"))
                                    price = _to_f(
                                        r.get("filled_avg_price")
                                        or r.get("filled avg price")
                                        or r.get("average fill price")
                                        or r.get("avg fill price")
                                        or r.get("price")
                                    )
                                    ts = (
                                        r.get("filled_at") or r.get("filled at")
                                        or r.get("submitted_at") or r.get("submitted at")
                                        or r.get("created_at") or r.get("created at")
                                    )
                                    if not sym or qty is None or price is None or not ts:
                                        continue
                                    if status and status not in {"filled", "partially_filled"}:
                                        continue
                                    dt = _act_time(ts)
                                    if dt < fills_cutoff:
                                        continue
                                    mult = _price_mult(sym)
                                    fills.append({
                                        "symbol": sym,
                                        "side": side,
                                        "qty": abs(float(qty)),
                                        "price": float(price) * mult,
                                        "ts": dt,
                                    })
                    except Exception:
                        pass

                # Optional: merge in Alpaca Crypto Orders CSV export
                if crypto_orders_csv:
                    try:
                        import csv
                        from pathlib import Path as _P

                        p = _P(crypto_orders_csv)
                        if p.exists():
                            with p.open(newline="") as f:
                                reader = csv.DictReader(f)
                                for row in reader:
                                    r = {str(k).strip().lower(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()}
                                    sym = str(r.get("symbol") or r.get("pair") or "")
                                    side = str(r.get("side") or "").lower()
                                    status = str(r.get("status") or "").lower()
                                    qty = _to_f(r.get("filled_qty") or r.get("filled quantity") or r.get("qty") or r.get("quantity"))
                                    price = _to_f(r.get("filled_avg_price") or r.get("filled avg price") or r.get("average fill price") or r.get("avg fill price") or r.get("price"))
                                    ts = (
                                        r.get("filled_at") or r.get("filled at")
                                        or r.get("submitted_at") or r.get("submitted at")
                                        or r.get("created_at") or r.get("created at")
                                    )
                                    if not sym or qty is None or price is None or not ts:
                                        continue
                                    if status and status not in {"filled", "partially_filled"}:
                                        continue
                                    dt = _act_time(ts)
                                    if dt < fills_cutoff:
                                        continue
                                    fills.append({
                                        "symbol": sym,
                                        "side": side,
                                        "qty": abs(float(qty)),
                                        "price": float(price),
                                        "ts": dt,
                                    })
                    except Exception:
                        pass

                fills = sorted(fills, key=lambda x: x["ts"])

                # Debug counts: helps verify Alpaca is returning data.
                if debug:
                    try:
                        sample_syms = ",".join(sorted({f.get('symbol','') for f in fills})[:12])
                        c.print(Panel(
                            f"activities={len(activities)}  fills={len(fills)}  orders={len(ords)}\nfill_symbols={sample_syms}",
                            title="Recent trades debug",
                            expand=False,
                        ))
                    except Exception:
                        pass

                long_lots: dict[str, list[list[float]]] = {}
                short_lots: dict[str, list[list[float]]] = {}

                for f in fills:
                    sym = f["symbol"]
                    side = f["side"]
                    qty = float(f["qty"])
                    price = float(f["price"])
                    ts = f["ts"]

                    if side == "buy":
                        rem = qty
                        lots = short_lots.get(sym, [])
                        while rem > 0 and lots:
                            lot_qty, lot_price = lots[0]
                            m = min(rem, lot_qty)
                            pnl = (lot_price - price) * m
                            pnlpc = (pnl / (lot_price * m)) if lot_price and m else None
                            if ts >= cutoff:
                                closed_rows.append({
                                    "symbol": sym,
                                    "pnl": float(pnl),
                                    "pnlpc": pnlpc,
                                    "qty": m,
                                    "last_order": ts,
                                    "status": "closed",
                                })
                            lot_qty -= m
                            rem -= m
                            if lot_qty <= 0:
                                lots.pop(0)
                            else:
                                lots[0][0] = lot_qty
                        if rem > 0:
                            long_lots.setdefault(sym, []).append([rem, price])

                    elif side == "sell":
                        rem = qty
                        lots = long_lots.get(sym, [])
                        while rem > 0 and lots:
                            lot_qty, lot_price = lots[0]
                            m = min(rem, lot_qty)
                            pnl = (price - lot_price) * m
                            pnlpc = (pnl / (lot_price * m)) if lot_price and m else None
                            if ts >= cutoff:
                                closed_rows.append({
                                    "symbol": sym,
                                    "pnl": float(pnl),
                                    "pnlpc": pnlpc,
                                    "qty": m,
                                    "last_order": ts,
                                    "status": "closed",
                                })
                            lot_qty -= m
                            rem -= m
                            if lot_qty <= 0:
                                lots.pop(0)
                            else:
                                lots[0][0] = lot_qty
                        if rem > 0:
                            short_lots.setdefault(sym, []).append([rem, price])
            except Exception:
                closed_rows = []

            # Keep positions with recent activity in the last 30 days.
            recent = []
            for r in pos_rows:
                dt = last_order.get(r["symbol"])
                if dt is None or dt < cutoff:
                    continue
                r2 = dict(r)
                r2["last_order"] = dt
                recent.append(r2)

            # Add closed trades from the last 30 days.
            for r in closed_rows:
                dt = r.get("last_order")
                if dt is None or dt < cutoff:
                    continue
                recent.append(r)

            if recent:
                winners = sorted(recent, key=lambda x: x["pnl"], reverse=True)[:3]
                losers = sorted(recent, key=lambda x: x["pnl"])[:3]

                # Separate closed-only list for clarity.
                closed_only = [r for r in recent if str(r.get("status") or "") == "closed"]

                t_win = Table(title=f"Recent trades (last {lookback_days}d) — top 3 by P&L")
                t_win.add_column("symbol", style="bold")
                t_win.add_column("status", justify="left")
                t_win.add_column("asof", justify="right")
                t_win.add_column("qty", justify="right")
                t_win.add_column("pnl", justify="right")
                t_win.add_column("pnl%", justify="right")
                for r in winners:
                    dt = r.get("last_order")
                    t_win.add_row(
                        r["symbol"],
                        r.get("status", ""),
                        (dt.date().isoformat() if dt else "—"),
                        "—" if r.get("qty") is None else f"{float(r.get('qty') or 0):.0f}",
                        f"{float(r['pnl']):+,.2f}",
                        "—" if r.get("pnlpc") is None else f"{float(r['pnlpc'])*100:+.1f}%",
                    )

                t_lose = Table(title=f"Recent trades (last {lookback_days}d) — worst 3 by P&L")
                t_lose.add_column("symbol", style="bold")
                t_lose.add_column("status", justify="left")
                t_lose.add_column("asof", justify="right")
                t_lose.add_column("qty", justify="right")
                t_lose.add_column("pnl", justify="right")
                t_lose.add_column("pnl%", justify="right")
                for r in losers:
                    dt = r.get("last_order")
                    t_lose.add_row(
                        r["symbol"],
                        r.get("status", ""),
                        (dt.date().isoformat() if dt else "—"),
                        "—" if r.get("qty") is None else f"{float(r.get('qty') or 0):.0f}",
                        f"{float(r['pnl']):+,.2f}",
                        "—" if r.get("pnlpc") is None else f"{float(r['pnlpc'])*100:+.1f}%",
                    )

                c.print(t_win)
                c.print(t_lose)

                if closed_only:
                    t_closed = Table(title=f"Closed trades (last {lookback_days}d) — top/bottom by P&L")
                    t_closed.add_column("symbol", style="bold")
                    t_closed.add_column("status", justify="left")
                    t_closed.add_column("asof", justify="right")
                    t_closed.add_column("qty", justify="right")
                    t_closed.add_column("pnl", justify="right")
                    t_closed.add_column("pnl%", justify="right")

                    top_closed = sorted(closed_only, key=lambda x: x["pnl"], reverse=True)[:3]
                    bot_closed = sorted(closed_only, key=lambda x: x["pnl"])[:3]
                    for r in top_closed + bot_closed:
                        dt = r.get("last_order")
                        t_closed.add_row(
                            r["symbol"],
                            r.get("status", ""),
                            (dt.date().isoformat() if dt else "—"),
                            "—" if r.get("qty") is None else f"{float(r.get('qty') or 0):.0f}",
                            f"{float(r['pnl']):+,.2f}",
                            "—" if r.get("pnlpc") is None else f"{float(r['pnlpc'])*100:+.1f}%",
                        )

                    c.print(t_closed)
                else:
                    c.print(Panel("No closed trades found in the last 30 days (orders/fills may be empty).", title="Closed trades", expand=False))
            else:
                c.print(Panel("No recent trades found in the last 30 days (best-effort).", title="Recent trades", expand=False))
        except Exception:
            c.print(Panel("Trade P&L snapshot unavailable (best-effort).", title="Recent trades", expand=False))

    @investor_app.command("import")
    def investor_import(
        csv_path: str = typer.Argument(..., help="Path to CSV/XLSX export (headers: code/investor, amount, joined/date)."),
        note: str = typer.Option("import", "--note", help="Default note for imported rows (unless CSV has a note column)."),
        dry_run: bool = typer.Option(False, "--dry-run", help="Parse and validate but do not write flows."),
        ts: str = typer.Option("", "--ts", help="Override join date/timestamp for ALL imported rows (ISO date/time)."),
        after_latest_nav: bool = typer.Option(
            False,
            "--after-latest-nav",
            help="Ignore per-row joined dates and price ALL imported rows just after the latest NAV snapshot.",
        ),
        sheet_path: str = typer.Option("", "--sheet-path", help="Override AOT_NAV_SHEET (CSV) used by --after-latest-nav."),
        investor_flows_path: str = typer.Option("", "--investor-flows-path", help="Override AOT_NAV_INVESTOR_FLOWS (CSV)."),
    ):
        """Import investor join dates + amounts from a CSV (e.g., Excel export)."""
        from ai_options_trader.nav.investors import import_investors_csv
        from ai_options_trader.nav.store import default_nav_sheet_path, read_nav_sheet, _parse_ts
        from datetime import timedelta

        ts_override = ts.strip() or ""
        if after_latest_nav:
            path_sheet = sheet_path or default_nav_sheet_path()
            rows = read_nav_sheet(path=path_sheet)
            if not rows:
                raise typer.BadParameter(
                    f"--after-latest-nav requires at least one NAV snapshot. Run `lox nav snapshot` first.\nnav_sheet: {path_sheet}"
                )
            last_ts = _parse_ts(rows[-1].ts) + timedelta(seconds=1)
            ts_override = last_ts.isoformat()

        rep = import_investors_csv(
            csv_path=csv_path,
            investor_flows_path=investor_flows_path or None,
            note=note,
            dry_run=bool(dry_run),
            ts_override=ts_override or None,
        )
        Console().print(
            Panel(
                f"{'DRY RUN — ' if dry_run else ''}Imported {int(rep.get('rows') or 0)} row(s)\n"
                f"investor_flows: {rep.get('path')}\n"
                f"preview: {rep.get('preview')}",
                title="NAV investor import",
                expand=False,
            )
        )
        Console().print(
            Panel(
                "Note: Import updates the investor ledger only. If these rows represent real cash flows,\n"
                "log matching fund flows with `lox nav flow ...` (or re-import via `lox nav investor contribute`).",
                title="Ledger note",
                expand=False,
            )
        )

    @investor_app.command("contribute")
    def investor_contribute(
        code: str = typer.Argument(..., help="Investor code/initials (e.g., JL)"),
        amount: float = typer.Argument(..., help="Signed USD amount. Deposit=positive, withdrawal=negative."),
        note: str = typer.Option("", "--note"),
        ts: str = typer.Option("", "--ts", help="Optional ISO timestamp (defaults to now UTC)."),
        after_latest_nav: bool = typer.Option(
            True,
            "--after-latest-nav/--at-time",
            help="If true (default), timestamp the contribution just AFTER the latest NAV snapshot so it is priced at the latest NAV per unit (prevents flow timing from distorting investor PnL). Ignored when --ts is provided.",
        ),
        flows_path: str = typer.Option("", "--flows-path", help="Override AOT_NAV_FLOWS (CSV)."),
        investor_flows_path: str = typer.Option("", "--investor-flows-path", help="Override AOT_NAV_INVESTOR_FLOWS (CSV)."),
    ):
        """Log a contribution that updates BOTH the fund cashflow ledger and the investor ledger (same timestamp)."""
        from ai_options_trader.nav.store import append_cashflow
        from ai_options_trader.nav.investors import append_investor_flow
        from ai_options_trader.nav.store import read_nav_sheet, _parse_ts
        from datetime import timedelta

        ts_use: str | None = ts.strip() or None
        if ts_use is None and bool(after_latest_nav):
            # Use the latest NAV snapshot timestamp as the pricing anchor (unitization).
            # If there are no NAV snapshots yet, fall back to "now".
            rows = read_nav_sheet()
            if rows:
                try:
                    last_ts = _parse_ts(rows[-1].ts) + timedelta(seconds=1)
                    ts_use = last_ts.isoformat()
                except Exception:
                    ts_use = None

        path_fund = append_cashflow(ts=ts_use, amount=float(amount), note=note, path=flows_path or None)
        path_inv = append_investor_flow(
            code=code, amount=float(amount), note=note, ts=ts_use, path=investor_flows_path or None
        )
        Console().print(
            Panel(
                f"Logged contribution: {code.upper()} {amount:+.2f}\n"
                f"ts: {ts_use or '(now UTC)'}\n"
                f"fund_flows: {path_fund}\n"
                f"investor_flows: {path_inv}",
                title="NAV investor contribute",
                expand=False,
            )
        )

    @nav_app.command("snapshot")
    def nav_snapshot(
        note: str = typer.Option("", "--note", help="Optional note (e.g., 'before trades', 'after trades')."),
        ts: str = typer.Option("", "--ts", help="Optional ISO timestamp (defaults to now UTC)."),
        sheet_path: str = typer.Option("", "--sheet-path", help="Override AOT_NAV_SHEET (CSV)."),
        flows_path: str = typer.Option("", "--flows-path", help="Override AOT_NAV_FLOWS (CSV)."),
        tail: int = typer.Option(10, "--tail", help="Show last N NAV rows after writing."),
    ):
        """Write a NAV snapshot row (equity/cash/buying power) and compute returns."""
        from ai_options_trader.config import load_settings
        from ai_options_trader.data.alpaca import make_clients
        from ai_options_trader.nav.store import append_nav_snapshot, read_nav_sheet

        settings = load_settings()
        trading, _data = make_clients(settings)
        acct = trading.get_account()
        equity = _to_float(getattr(acct, "equity", None)) or 0.0
        cash = _to_float(getattr(acct, "cash", None)) or 0.0
        bp = _to_float(getattr(acct, "buying_power", None)) or 0.0
        try:
            positions = trading.get_all_positions()
            positions_count = len(list(positions))
        except Exception:
            positions_count = 0

        # Capture prev snapshot so we can emit a helpful warning for flow/equity timing mismatches.
        path_sheet_pre = sheet_path or ""
        rows_pre = read_nav_sheet(path=path_sheet_pre) if path_sheet_pre else read_nav_sheet()
        prev = rows_pre[-1] if rows_pre else None

        path, snap = append_nav_snapshot(
            ts=ts or None,
            equity=equity,
            cash=cash,
            buying_power=bp,
            positions_count=positions_count,
            note=note,
            sheet_path=sheet_path or None,
            flows_path=flows_path or None,
        )

        c = Console()
        delta = "—" if snap.twr_since_prev is None else f"{snap.twr_since_prev*100:+.2f}%"
        cum = f"{snap.twr_cum*100:+.2f}%"
        nf = "—" if snap.net_flow_since_prev is None else f"{snap.net_flow_since_prev:+.2f}"
        pnl = "—" if snap.pnl_since_prev is None else f"{snap.pnl_since_prev:+.2f}"
        warn = ""
        try:
            if prev is not None and snap.net_flow_since_prev is not None:
                net_flow = float(snap.net_flow_since_prev)
                if abs(net_flow) > 1e-6:
                    equity_delta = float(snap.equity) - float(prev.equity)
                    # If you log a flow (e.g., +$100) but Alpaca equity hasn't moved by ~that amount yet,
                    # pnl will show roughly -flow until the deposit/withdrawal is reflected in the account.
                    if abs(equity_delta) < 0.20 * abs(net_flow):
                        warn = (
                            "\n\n[b]Warning[/b]: A cashflow was logged, but account equity did not change by a similar amount between snapshots.\n"
                            "This usually means the deposit/withdrawal has not posted to Alpaca equity yet (timing/settlement),\n"
                            "or the flow timestamp doesn't match when the cash hit the brokerage. If the cash just moved, wait and run another snapshot,\n"
                            "or re-log the flow with a corrected `--ts` that matches the posting time."
                        )
        except Exception:
            warn = ""
        c.print(
            Panel(
                f"sheet: {path}\n"
                f"equity=${snap.equity:,.2f} cash=${snap.cash:,.2f} buying_power=${snap.buying_power:,.2f}\n"
                f"positions={snap.positions_count}\n"
                f"net_flow_since_prev={nf}  pnl_since_prev={pnl}  twr_since_prev={delta}  twr_cum={cum}"
                f"{warn}",
                title="NAV snapshot",
                expand=False,
            )
        )

        rows = read_nav_sheet(path=path)
        show = rows[-int(tail) :] if tail and len(rows) > tail else rows
        tbl = Table(title=f"NAV sheet (last {len(show)})")
        tbl.add_column("ts")
        tbl.add_column("equity", justify="right")
        tbl.add_column("net_flow", justify="right")
        tbl.add_column("pnl", justify="right")
        tbl.add_column("twr", justify="right")
        tbl.add_column("twr_cum", justify="right")
        for r in show:
            tbl.add_row(
                r.ts[:19],
                f"{r.equity:,.2f}",
                "—" if r.net_flow_since_prev is None else f"{r.net_flow_since_prev:+.2f}",
                "—" if r.pnl_since_prev is None else f"{r.pnl_since_prev:+.2f}",
                "—" if r.twr_since_prev is None else f"{r.twr_since_prev*100:+.2f}%",
                f"{r.twr_cum*100:+.2f}%",
            )
        c.print(tbl)

    @nav_app.command("show")
    def nav_show(
        tail: int = typer.Option(25, "--tail", help="Show last N NAV rows."),
        sheet_path: str = typer.Option("", "--sheet-path", help="Override AOT_NAV_SHEET (CSV)."),
    ):
        """Show the NAV sheet (CSV) as a Rich table."""
        from ai_options_trader.nav.store import read_nav_sheet, default_nav_sheet_path

        path = sheet_path or default_nav_sheet_path()
        rows = read_nav_sheet(path=path)
        rows = rows[-int(tail) :] if tail and len(rows) > tail else rows
        c = Console()
        if not rows:
            c.print(Panel(f"No NAV rows yet.\nsheet: {path}", title="NAV", expand=False))
            raise typer.Exit(code=0)

        tbl = Table(title=f"NAV sheet (last {len(rows)})")
        tbl.add_column("ts")
        tbl.add_column("equity", justify="right")
        tbl.add_column("twr", justify="right")
        tbl.add_column("twr_cum", justify="right")
        tbl.add_column("note")
        for r in rows:
            tbl.add_row(
                r.ts[:19],
                f"{r.equity:,.2f}",
                "—" if r.twr_since_prev is None else f"{r.twr_since_prev*100:+.2f}%",
                f"{r.twr_cum*100:+.2f}%",
                r.note or "",
            )
        c.print(Panel(f"sheet: {path}", title="NAV", expand=False))
        c.print(tbl)

