from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
import os
import typer
from rich import print
from rich.console import Console
from rich.panel import Panel
from rich.pretty import Pretty
from rich.table import Table

from ai_options_trader.config import load_settings
from ai_options_trader.overlay.context import extract_underlyings
from ai_options_trader.utils.settings import safe_load_settings


def register(ticker_app: typer.Typer) -> None:
    @ticker_app.command("snapshot")
    def ticker_snapshot(
        ticker: str = typer.Option(..., "--ticker", "-t", help="Ticker symbol (e.g., AAPL)"),
        benchmark: str = typer.Option("SPY", "--benchmark", help="Benchmark symbol for relative strength (default SPY)"),
        start: str = typer.Option("2011-01-01", "--start", help="Start date YYYY-MM-DD"),
    ):
        """Print a quantitative snapshot for a ticker (returns, vol, drawdown, rel strength)."""
        settings = load_settings()
        from ai_options_trader.ticker.snapshot import build_ticker_snapshot

        snap = build_ticker_snapshot(settings=settings, ticker=ticker, benchmark=benchmark, start=start)
        print(snap)

    @ticker_app.command("outlook")
    def ticker_outlook(
        ticker: str = typer.Option(..., "--ticker", "-t", help="Ticker symbol (e.g., AAPL)"),
        benchmark: str = typer.Option("SPY", "--benchmark", help="Benchmark symbol for relative strength (default SPY)"),
        year: int = typer.Option(2026, "--year", help="Focus year for the outlook (e.g., 2026)"),
        start: str = typer.Option("2011-01-01", "--start", help="Start date YYYY-MM-DD"),
        refresh: bool = typer.Option(False, "--refresh", help="Force refresh FRED downloads (for regimes)"),
        llm_model: str = typer.Option("", "--llm-model", help="Override OPENAI_MODEL (optional)"),
        llm_temperature: float = typer.Option(0.2, "--llm-temperature", help="LLM temperature (0..2)"),
    ):
        """
        Ask an LLM for a 3/6/12 month outlook for a ticker, grounded in:
        - ticker quantitative snapshot (Alpaca daily closes)
        - current regimes (macro/liquidity/usd + optional tariff summary)
        """
        settings = load_settings()

        # --- Ticker snapshot ---
        from ai_options_trader.ticker.snapshot import build_ticker_snapshot

        snap = build_ticker_snapshot(settings=settings, ticker=ticker, benchmark=benchmark, start=start)

        # --- Regime context (keep it lightweight / non-leaky) ---
        from ai_options_trader.macro.signals import build_macro_state
        from ai_options_trader.macro.regime import classify_macro_regime_from_state
        from ai_options_trader.funding.signals import build_funding_state
        from ai_options_trader.usd.signals import build_usd_state

        macro_state = build_macro_state(settings=settings, start_date=start, refresh=refresh)
        macro_regime = classify_macro_regime_from_state(
            cpi_yoy=macro_state.inputs.cpi_yoy,
            payrolls_3m_annualized=macro_state.inputs.payrolls_3m_annualized,
            inflation_momentum_minus_be5y=macro_state.inputs.inflation_momentum_minus_be5y,
            real_yield_proxy_10y=macro_state.inputs.real_yield_proxy_10y,
            z_inflation_momentum_minus_be5y=macro_state.inputs.components.get("z_infl_mom_minus_be5y") if macro_state.inputs.components else None,
            z_real_yield_proxy_10y=macro_state.inputs.components.get("z_real_yield_proxy_10y") if macro_state.inputs.components else None,
            use_zscores=True,
            cpi_target=3.0,
            infl_thresh=0.0,
            real_thresh=0.0,
        )
        liq_state = build_funding_state(settings=settings, start_date=start, refresh=refresh)
        usd_state = build_usd_state(settings=settings, start_date=start, refresh=refresh)

        regimes = {
            "macro": {"state": macro_state.model_dump(), "regime": macro_regime.__dict__},
            "liquidity": liq_state.model_dump(),
            "usd": usd_state.model_dump(),
        }

        # --- LLM ---
        from ai_options_trader.llm.ticker_outlook import llm_ticker_outlook

        text = llm_ticker_outlook(
            settings=settings,
            ticker_snapshot=snap,
            regimes=regimes,
            year=int(year),
            model=llm_model.strip() or None,
            temperature=float(llm_temperature),
        )
        print(text)

    @ticker_app.command("dossier")
    def ticker_dossier(
        ticker: str = typer.Option(..., "--ticker", "-t", help="Ticker symbol (e.g., AAPL)"),
        days_ahead: int = typer.Option(180, "--days-ahead", help="How far ahead to look for next earnings (days)"),
    ):
        """
        Build a minimal alternative-data dossier for a ticker (start slow):
        - company profile (sector/industry/market cap)
        - next earnings date (if available)
        """
        settings = load_settings()
        from ai_options_trader.altdata.fmp import build_ticker_dossier

        d = build_ticker_dossier(settings=settings, ticker=ticker, days_ahead=int(days_ahead))
        Console().print(Panel(Pretty(d, expand_all=True), title=f"Dossier: {ticker.upper()}", expand=False))

    @ticker_app.command("news")
    def ticker_news(
        ticker: str = typer.Option("", "--ticker", "-t", help="Ticker symbol (e.g., NVDA)"),
        from_options: bool = typer.Option(
            False,
            "--from-options",
            help="If set, pick the top option underlying from current positions (by abs market value).",
        ),
        lookback_days: int = typer.Option(7, "--days", help="Lookback window for news (days)"),
        max_items: int = typer.Option(10, "--max-items", help="Max news items to show"),
        llm: bool = typer.Option(True, "--llm/--no-llm", help="Enable LLM summary"),
        llm_model: str = typer.Option("", "--llm-model", help="Override OPENAI_MODEL (optional)"),
        llm_temperature: float = typer.Option(0.2, "--llm-temperature", help="LLM temperature (0..2)"),
    ):
        """
        Build a basic ticker profile + recent news summary.
        """
        settings = safe_load_settings()
        if not settings:
            raise typer.BadParameter("Settings unavailable (missing env/.env).")
        c = Console()

        if from_options and not ticker:
            try:
                from ai_options_trader.data.alpaca import make_clients

                trading, _data = make_clients(settings)
                positions = trading.get_all_positions()
            except Exception:
                positions = []

            option_syms: list[tuple[float, str]] = []
            for p in positions or []:
                sym = str(getattr(p, "symbol", "") or "").upper()
                if re.search(r"\d{6}[CP]\d{8}$", sym):
                    mv = float(getattr(p, "market_value", 0.0) or 0.0)
                    option_syms.append((abs(mv), sym))
            if option_syms:
                top_sym = sorted(option_syms, key=lambda x: x[0], reverse=True)[0][1]
                underlying = next(iter(extract_underlyings([top_sym])), "")
                ticker = underlying or ticker

        if not ticker:
            raise typer.BadParameter("Provide --ticker or use --from-options.")

        t = ticker.strip().upper()

        # --- Ticker profile (basic) ---
        from ai_options_trader.altdata.fmp import build_ticker_dossier

        dossier = build_ticker_dossier(settings=settings, ticker=t, days_ahead=180)
        prof = dossier.get("profile") or {}
        next_ev = dossier.get("next_earnings") or {}
        prof_lines = [
            f"Ticker: {t}",
            f"Company: {prof.get('company_name') or 'DATA NOT PROVIDED'}",
            f"Sector/Industry: {(prof.get('sector') or '—')} / {(prof.get('industry') or '—')}",
            f"Exchange: {prof.get('exchange') or 'DATA NOT PROVIDED'}",
            f"Market cap: {prof.get('market_cap') or 'DATA NOT PROVIDED'}",
        ]
        if next_ev:
            prof_lines.append(f"Next earnings: {next_ev.get('date')} {next_ev.get('time') or ''}".strip())
        c.print(Panel("\n".join(prof_lines), title=f"Ticker Profile: {t}", expand=False))

        # --- News ---
        from ai_options_trader.llm.ticker_news import fetch_fmp_stock_news, llm_recent_news_brief

        now = datetime.now(timezone.utc).date()
        from_date = (now - timedelta(days=int(lookback_days))).isoformat()
        to_date = now.isoformat()

        try:
            items = fetch_fmp_stock_news(
                settings=settings,
                tickers=[t],
                from_date=from_date,
                to_date=to_date,
                max_pages=3,
            )
        except Exception as e:
            items = []
            c.print(Panel(f"News fetch failed: {e}", title="Ticker News", expand=False))

        if items:
            t_news = Table(title=f"Recent News ({lookback_days}d)")
            t_news.add_column("date")
            t_news.add_column("source")
            t_news.add_column("title")
            t_news.add_column("url")
            for it in items[: max(1, int(max_items))]:
                t_news.add_row(
                    str(it.published_at),
                    str(it.source or "—"),
                    str(it.title or ""),
                    str(it.url or "—"),
                )
            c.print(t_news)
        else:
            c.print(Panel("No news items available for this lookback.", title="Ticker News", expand=False))

        # --- LLM summary ---
        if bool(llm):
            try:
                summary = llm_recent_news_brief(
                    settings=settings,
                    ticker=t,
                    items=items,
                    model=llm_model.strip() or None,
                    temperature=float(llm_temperature),
                    lookback_label=f"the last {int(lookback_days)} days",
                )
                c.print(Panel(summary, title="LLM News Brief", expand=False))
            except Exception as e:
                c.print(Panel(f"LLM summary unavailable: {e}", title="LLM News Brief", expand=False))


