from __future__ import annotations

import typer
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
    investor_app = typer.Typer(add_completion=False, help="Investor ledger (initials + amounts) using unitized NAV")
    nav_app.add_typer(investor_app, name="investor")

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

    @investor_app.command("report")
    def investor_report_cmd(
        sheet_path: str = typer.Option("", "--sheet-path", help="Override AOT_NAV_SHEET (CSV)."),
        investor_flows_path: str = typer.Option("", "--investor-flows-path", help="Override AOT_NAV_INVESTOR_FLOWS (CSV)."),
    ):
        """Show investor ownership + P&L using unitized NAV."""
        from ai_options_trader.nav.investors import investor_report, default_investor_flows_path
        from ai_options_trader.nav.store import default_nav_sheet_path

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

    @investor_app.command("contribute")
    def investor_contribute(
        code: str = typer.Argument(..., help="Investor code/initials (e.g., JL)"),
        amount: float = typer.Argument(..., help="Signed USD amount. Deposit=positive, withdrawal=negative."),
        note: str = typer.Option("", "--note"),
        ts: str = typer.Option("", "--ts", help="Optional ISO timestamp (defaults to now UTC)."),
        flows_path: str = typer.Option("", "--flows-path", help="Override AOT_NAV_FLOWS (CSV)."),
        investor_flows_path: str = typer.Option("", "--investor-flows-path", help="Override AOT_NAV_INVESTOR_FLOWS (CSV)."),
    ):
        """Log a contribution that updates BOTH the fund cashflow ledger and the investor ledger (same timestamp)."""
        from ai_options_trader.nav.store import append_cashflow
        from ai_options_trader.nav.investors import append_investor_flow

        path_fund = append_cashflow(ts=ts or None, amount=float(amount), note=note, path=flows_path or None)
        path_inv = append_investor_flow(
            code=code, amount=float(amount), note=note, ts=ts or None, path=investor_flows_path or None
        )
        Console().print(
            Panel(
                f"Logged contribution: {code.upper()} {amount:+.2f}\nfund_flows: {path_fund}\ninvestor_flows: {path_inv}",
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
        c.print(
            Panel(
                f"sheet: {path}\n"
                f"equity=${snap.equity:,.2f} cash=${snap.cash:,.2f} buying_power=${snap.buying_power:,.2f}\n"
                f"positions={snap.positions_count}\n"
                f"net_flow_since_prev={nf}  pnl_since_prev={pnl}  twr_since_prev={delta}  twr_cum={cum}",
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

