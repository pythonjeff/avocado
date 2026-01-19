"""Options scanner commands - bulk scanning across universes."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

import typer
from rich import print
from rich.console import Console
from rich.table import Table

from ai_options_trader.config import load_settings
from ai_options_trader.data.alpaca import fetch_option_chain, make_clients, to_candidates
from ai_options_trader.options.budget_scan import affordable_options_for_ticker, pick_best_affordable
from ai_options_trader.portfolio.universe import STARTER_UNIVERSE
from ai_options_trader.universe.sp500 import load_sp500_universe


def _fmt_price(x: float | None) -> str:
    return f"{float(x):.2f}" if isinstance(x, (int, float)) else "n/a"


def _fmt_pct(x: float | None) -> str:
    return f"{100.0*float(x):.1f}%" if isinstance(x, (int, float)) else "n/a"


def register_scanners(options_app: typer.Typer) -> None:
    """Register scanner commands."""

    @options_app.command("sp500-under-budget")
    def sp500_under_budget(
        max_premium_usd: float = typer.Option(100.0, "--max-premium"),
        min_days: int = typer.Option(7, "--min-days"),
        max_days: int = typer.Option(45, "--max-days"),
        calls: bool = typer.Option(False, "--calls"),
        puts: bool = typer.Option(False, "--puts"),
        price_basis: str = typer.Option("ask", "--price-basis"),
        min_price: float = typer.Option(0.05, "--min-price"),
        target_abs_delta: float = typer.Option(0.30, "--target-abs-delta"),
        max_spread_pct: float = typer.Option(0.30, "--max-spread-pct"),
        limit: int = typer.Option(500, "--limit"),
        workers: int = typer.Option(8, "--workers"),
        refresh_universe: bool = typer.Option(False, "--refresh-universe"),
        max_results: int = typer.Option(200, "--max-results"),
    ):
        """Scan S&P 500 for options under budget (scanner only)."""
        want = "both"
        if calls and not puts:
            want = "call"
        elif puts and not calls:
            want = "put"

        pb = price_basis.strip().lower()
        if pb not in {"ask", "mid", "last"}:
            pb = "ask"

        settings = load_settings()
        _, data = make_clients(settings)

        uni = load_sp500_universe(refresh=bool(refresh_universe), fmp_api_key=settings.fmp_api_key)
        tickers = uni.tickers[:max(0, int(limit))]
        if uni.skipped:
            print(f"[dim]Skipped dotted: {len(uni.skipped)}[/dim]")
        print(f"[dim]Universe: {len(tickers)} tickers (source={uni.source})[/dim]")

        def _scan_one(t: str):
            chain = fetch_option_chain(data, t, feed=settings.alpaca_options_feed)
            cands = list(to_candidates(chain, t))
            opts = affordable_options_for_ticker(
                cands, ticker=t, max_premium_usd=float(max_premium_usd),
                min_dte_days=int(min_days), max_dte_days=int(max_days),
                want=want, price_basis=pb, min_price=float(min_price),
                max_spread_pct=float(max_spread_pct), require_delta=True,
                today=date.today(),
            )
            return t, pick_best_affordable(opts, target_abs_delta=float(target_abs_delta), max_spread_pct=float(max_spread_pct))

        results = []
        errors = 0
        with ThreadPoolExecutor(max_workers=max(1, int(workers))) as ex:
            futs = {ex.submit(_scan_one, t): t for t in tickers}
            for fut in as_completed(futs):
                t = futs[fut]
                try:
                    _, best = fut.result()
                    if best:
                        results.append(best)
                except Exception as e:
                    errors += 1
                    if errors <= 5:
                        print(f"[dim]{t}: {type(e).__name__}[/dim]")

        results.sort(key=lambda o: (-abs(float(o.delta)), o.premium_usd, o.ticker))
        shown = results[:max(0, int(max_results))]

        tbl = Table(title=f"S&P 500: options under ${float(max_premium_usd):.0f}")
        tbl.add_column("Ticker", style="bold")
        tbl.add_column("Symbol", style="bold")
        tbl.add_column("Type")
        tbl.add_column("Exp")
        tbl.add_column("DTE", justify="right")
        tbl.add_column("Strike", justify="right")
        tbl.add_column("Price", justify="right")
        tbl.add_column("Premium", justify="right")
        tbl.add_column("Δ", justify="right")
        tbl.add_column("IV", justify="right")

        for o in shown:
            tbl.add_row(
                o.ticker, o.symbol, o.opt_type,
                o.expiry.isoformat(), str(o.dte_days),
                f"{o.strike:.2f}", _fmt_price(o.price),
                f"${o.premium_usd:,.0f}", _fmt_price(o.delta), _fmt_pct(o.iv),
            )

        Console().print(tbl)
        print(f"[dim]Found: {len(results)}/{len(tickers)} | Errors: {errors}[/dim]")

    @options_app.command("etf-under-budget")
    def etf_under_budget(
        max_premium_usd: float = typer.Option(100.0, "--max-premium"),
        min_days: int = typer.Option(7, "--min-days"),
        max_days: int = typer.Option(45, "--max-days"),
        calls: bool = typer.Option(False, "--calls"),
        puts: bool = typer.Option(False, "--puts"),
        price_basis: str = typer.Option("ask", "--price-basis"),
        min_price: float = typer.Option(0.05, "--min-price"),
        target_abs_delta: float = typer.Option(0.30, "--target-abs-delta"),
        max_spread_pct: float = typer.Option(0.30, "--max-spread-pct"),
        workers: int = typer.Option(6, "--workers"),
        tickers: str = typer.Option("", "--tickers"),
        max_results: int = typer.Option(50, "--max-results"),
    ):
        """Scan ETF universe for options under budget."""
        want = "both"
        if calls and not puts:
            want = "call"
        elif puts and not calls:
            want = "put"

        pb = price_basis.strip().lower()
        if pb not in {"ask", "mid", "last"}:
            pb = "ask"

        if tickers.strip():
            uni = [t.strip().upper() for t in tickers.split(",") if t.strip()]
        else:
            uni = [t.strip().upper() for t in STARTER_UNIVERSE.basket_equity]

        settings = load_settings()
        _, data = make_clients(settings)

        def _scan_one(t: str):
            chain = fetch_option_chain(data, t, feed=settings.alpaca_options_feed)
            cands = list(to_candidates(chain, t))
            opts = affordable_options_for_ticker(
                cands, ticker=t, max_premium_usd=float(max_premium_usd),
                min_dte_days=int(min_days), max_dte_days=int(max_days),
                want=want, price_basis=pb, min_price=float(min_price),
                max_spread_pct=float(max_spread_pct), require_delta=True,
                today=date.today(),
            )
            return t, pick_best_affordable(opts, target_abs_delta=float(target_abs_delta), max_spread_pct=float(max_spread_pct))

        results = []
        errors = 0
        with ThreadPoolExecutor(max_workers=max(1, int(workers))) as ex:
            futs = {ex.submit(_scan_one, t): t for t in uni}
            for fut in as_completed(futs):
                t = futs[fut]
                try:
                    _, best = fut.result()
                    if best:
                        results.append(best)
                except Exception as e:
                    errors += 1
                    if errors <= 5:
                        print(f"[dim]{t}: {type(e).__name__}[/dim]")

        results.sort(key=lambda o: (-abs(float(o.delta)), o.premium_usd, o.ticker))
        shown = results[:max(0, int(max_results))]

        tbl = Table(title=f"ETF options under ${float(max_premium_usd):.0f}")
        tbl.add_column("Ticker", style="bold")
        tbl.add_column("Symbol", style="bold")
        tbl.add_column("Type")
        tbl.add_column("Exp")
        tbl.add_column("DTE", justify="right")
        tbl.add_column("Strike", justify="right")
        tbl.add_column("Price", justify="right")
        tbl.add_column("Premium", justify="right")
        tbl.add_column("Δ", justify="right")
        tbl.add_column("IV", justify="right")

        for o in shown:
            tbl.add_row(
                o.ticker, o.symbol, o.opt_type,
                o.expiry.isoformat(), str(o.dte_days),
                f"{o.strike:.2f}", _fmt_price(o.price),
                f"${o.premium_usd:,.0f}", _fmt_price(o.delta), _fmt_pct(o.iv),
            )

        Console().print(tbl)
        print(f"[dim]Found: {len(results)}/{len(uni)} | Errors: {errors}[/dim]")
