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
from rich.markdown import Markdown

from ai_options_trader.config import load_settings
from ai_options_trader.overlay.context import extract_underlyings
from ai_options_trader.utils.settings import safe_load_settings


def _fmt_market_cap(val: float | None) -> str:
    """Format market cap for display."""
    if val is None:
        return "—"
    if val >= 1e12:
        return f"${val/1e12:.2f}T"
    if val >= 1e9:
        return f"${val/1e9:.1f}B"
    if val >= 1e6:
        return f"${val/1e6:.0f}M"
    return f"${val:,.0f}"


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
        from ai_options_trader.llm.outlooks.ticker_outlook import llm_ticker_outlook

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
        from ai_options_trader.llm.outlooks.ticker_news import fetch_fmp_stock_news, llm_recent_news_brief

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

    @ticker_app.command("filings")
    def ticker_filings(
        ticker: str = typer.Option(..., "--ticker", "-t", help="Ticker symbol (e.g., AAPL)"),
        form_types: str = typer.Option("8-K,10-K,10-Q", "--forms", help="Comma-separated form types"),
        limit: int = typer.Option(15, "--limit", help="Max filings to show"),
    ):
        """
        Show recent SEC filings (8-K, 10-K, 10-Q, etc.) for a ticker.
        
        Uses SEC EDGAR API directly (no API key required).
        """
        settings = safe_load_settings()
        if not settings:
            raise typer.BadParameter("Settings unavailable.")
        c = Console()
        
        from ai_options_trader.altdata.sec import fetch_sec_filings, summarize_filings, categorize_8k_items
        
        t = ticker.strip().upper()
        forms = [f.strip().upper() for f in form_types.split(",") if f.strip()]
        
        filings = fetch_sec_filings(
            settings=settings,
            ticker=t,
            form_types=forms if forms else None,
            limit=int(limit),
        )
        
        if not filings:
            c.print(Panel(f"No SEC filings found for {t}", title="SEC Filings", expand=False))
            return
        
        # Summary
        summary = summarize_filings(filings)
        summary_lines = [
            f"[bold]Total filings:[/bold] {summary['total']}",
            f"[bold]By type:[/bold] {summary['by_type']}",
            f"[bold]Most recent:[/bold] {summary['most_recent_form']} on {summary['most_recent_date']}",
        ]
        
        if summary.get("8k_categories"):
            cats = summary["8k_categories"]
            flags = [k.replace("has_", "").replace("_", " ") for k, v in cats.items() if v]
            if flags:
                summary_lines.append(f"[bold]8-K categories:[/bold] {', '.join(flags)}")
        
        c.print(Panel("\n".join(summary_lines), title=f"SEC Filings Summary: {t}", expand=False))
        
        # Table
        tbl = Table(title=f"Recent Filings ({limit})")
        tbl.add_column("Date", style="cyan")
        tbl.add_column("Form")
        tbl.add_column("Description")
        tbl.add_column("Items")
        tbl.add_column("URL", no_wrap=True)
        
        for f in filings:
            items_str = ", ".join(f.items[:3]) if f.items else "—"
            url_short = f.filing_url[:60] + "..." if len(f.filing_url) > 60 else f.filing_url
            tbl.add_row(
                f.filed_date,
                f.form_type,
                f.description[:40] + "..." if len(f.description) > 40 else f.description or "—",
                items_str,
                url_short or "—",
            )
        
        c.print(tbl)

    @ticker_app.command("earnings")
    def ticker_earnings(
        ticker: str = typer.Option(..., "--ticker", "-t", help="Ticker symbol"),
        history: int = typer.Option(8, "--history", help="Number of historical quarters"),
        transcript: bool = typer.Option(False, "--transcript", help="Show most recent transcript excerpt"),
    ):
        """
        Show earnings history, surprises, and analysis for a ticker.
        """
        settings = safe_load_settings()
        if not settings:
            raise typer.BadParameter("Settings unavailable.")
        c = Console()
        
        t = ticker.strip().upper()
        
        from ai_options_trader.altdata.earnings import (
            fetch_earnings_surprises,
            fetch_recent_transcripts,
            fetch_upcoming_earnings,
            analyze_earnings_history,
            extract_transcript_insights,
        )
        
        # Earnings surprises
        surprises = fetch_earnings_surprises(settings=settings, ticker=t, limit=int(history))
        
        if surprises:
            analysis = analyze_earnings_history(surprises)
            
            c.print(Panel(
                f"[bold]Quarters analyzed:[/bold] {analysis['count']}\n"
                f"[bold]Beat rate:[/bold] {analysis['beat_rate']:.0f}% ({analysis['beats']}/{analysis['beats']+analysis['misses']})\n"
                f"[bold]Avg surprise:[/bold] {analysis['avg_surprise_pct']:+.1f}%\n"
                f"[bold]Current streak:[/bold] {analysis['streak']} {analysis['streak_type'] or 'N/A'}",
                title=f"Earnings Analysis: {t}",
                expand=False,
            ))
            
            tbl = Table(title="Earnings History")
            tbl.add_column("Date", style="cyan")
            tbl.add_column("EPS Actual", justify="right")
            tbl.add_column("EPS Est", justify="right")
            tbl.add_column("Surprise", justify="right")
            tbl.add_column("Surprise %", justify="right")
            
            for s in surprises[:8]:
                surprise_style = "green" if (s.eps_surprise or 0) > 0 else "red" if (s.eps_surprise or 0) < 0 else ""
                tbl.add_row(
                    s.date,
                    f"${s.eps_actual:.2f}" if s.eps_actual is not None else "—",
                    f"${s.eps_estimated:.2f}" if s.eps_estimated is not None else "—",
                    f"[{surprise_style}]${s.eps_surprise:+.2f}[/{surprise_style}]" if s.eps_surprise is not None else "—",
                    f"[{surprise_style}]{s.eps_surprise_pct:+.1f}%[/{surprise_style}]" if s.eps_surprise_pct is not None else "—",
                )
            
            c.print(tbl)
        else:
            c.print(Panel(f"No earnings data found for {t}", title="Earnings", expand=False))
        
        # Upcoming earnings
        upcoming = fetch_upcoming_earnings(settings=settings, tickers=[t], days_ahead=90)
        if upcoming:
            next_event = upcoming[0]
            c.print(Panel(
                f"[bold]Date:[/bold] {next_event.date}\n"
                f"[bold]Time:[/bold] {next_event.time or 'TBD'}\n"
                f"[bold]EPS Est:[/bold] ${next_event.eps_estimated:.2f}" if next_event.eps_estimated else "",
                title=f"Next Earnings: {t}",
                expand=False,
            ))
        
        # Transcript
        if transcript:
            transcripts = fetch_recent_transcripts(settings=settings, ticker=t, num_quarters=1)
            if transcripts:
                tr = transcripts[0]
                insights = extract_transcript_insights(tr)
                
                c.print(Panel(
                    f"[bold]Quarter:[/bold] {insights['quarter']}\n"
                    f"[bold]Date:[/bold] {insights['date']}\n"
                    f"[bold]Length:[/bold] {insights['length']:,} chars\n\n"
                    f"[bold]Key mentions:[/bold]\n"
                    + "\n".join([f"  {k}: {v}" for k, v in insights['mentions'].items() if v > 0])
                    + f"\n\n[dim]{insights['preview']}[/dim]",
                    title=f"Latest Transcript: {t}",
                    expand=False,
                ))
            else:
                c.print(Panel(f"No transcripts available for {t}", title="Transcript", expand=False))

    @ticker_app.command("deep")
    def ticker_deep(
        ticker: str = typer.Option(..., "--ticker", "-t", help="Ticker symbol"),
        llm: bool = typer.Option(True, "--llm/--no-llm", help="Include LLM analysis"),
        llm_model: str = typer.Option("", "--llm-model", help="Override LLM model"),
    ):
        """
        Deep dive on a ticker: profile, filings, earnings, news, sentiment.
        
        This is the comprehensive research command that pulls together all
        available data sources for a single ticker.
        """
        settings = safe_load_settings()
        if not settings:
            raise typer.BadParameter("Settings unavailable.")
        c = Console()
        
        t = ticker.strip().upper()
        c.print(f"\n[bold cyan]Deep dive: {t}[/bold cyan]\n")
        
        # 1. Profile & ETF Detection
        from ai_options_trader.altdata.fmp import fetch_profile
        from ai_options_trader.altdata.etf import fetch_etf_data, get_flow_signal_label, format_holding_name
        from datetime import datetime, timedelta, timezone
        import requests
        
        profile = fetch_profile(settings=settings, ticker=t)
        
        # Fetch all ETF data (detection, holdings, performance, institutional holders)
        etf_result = fetch_etf_data(settings, t, profile)
        is_etf = etf_result.is_etf
        etf_data = etf_result.etf_info
        etf_holdings = etf_result.holdings
        etf_perf_data = etf_result.performance
        etf_flow_estimate = etf_result.flow_signal
        etf_institutional = etf_result.institutional_holders
        if profile:
            if is_etf:
                # ETF-specific profile
                profile_lines = [
                    f"[bold]Fund:[/bold] {profile.company_name or t}",
                    f"[bold]Type:[/bold] [cyan]ETF[/cyan]",
                    f"[bold]Category:[/bold] {profile.sector or '—'} / {profile.industry or '—'}",
                    f"[bold]Exchange:[/bold] {profile.exchange or '—'}",
                    f"[bold]AUM:[/bold] {_fmt_market_cap(profile.market_cap)}",
                ]
                
                # Add ETF-specific data if available
                if etf_data:
                    if etf_data.get('expenseRatio'):
                        profile_lines.append(f"[bold]Expense Ratio:[/bold] {etf_data['expenseRatio']*100:.2f}%")
                    if etf_data.get('avgVolume'):
                        profile_lines.append(f"[bold]Avg Volume:[/bold] {etf_data['avgVolume']:,.0f}")
                    if etf_data.get('holdingsCount'):
                        profile_lines.append(f"[bold]Holdings:[/bold] {etf_data['holdingsCount']}")
                
                if profile.description:
                    desc = (profile.description[:300] + '...') if len(profile.description) > 300 else profile.description
                    profile_lines.append(f"\n[dim]{desc}[/dim]")
                
                c.print(Panel("\n".join(profile_lines), title="ETF Profile", expand=False))
                
                # Show top holdings for ETFs
                if etf_holdings:
                    holdings_lines = ["[bold]Top Holdings:[/bold]"]
                    for h in etf_holdings[:10]:
                        weight = h.get('weightPercentage', 0)
                        asset = format_holding_name(h)
                        holdings_lines.append(f"  • {asset}: {weight:.2f}%")
                    c.print(Panel("\n".join(holdings_lines), title="Holdings", expand=False))
                
                # Display ETF Performance & Fund Flows (data already fetched)
                if etf_perf_data:
                    perf_lines = ["[bold]Performance Returns:[/bold]"]
                    for period, ret in etf_perf_data.items():
                        color = "green" if ret >= 0 else "red"
                        sign = "+" if ret >= 0 else ""
                        perf_lines.append(f"  {period}: [{color}]{sign}{ret:.2f}%[/{color}]")
                    
                    # Add flow estimate
                    if etf_flow_estimate:
                        flow_label, flow_color = get_flow_signal_label(etf_flow_estimate)
                        vol_trend = etf_flow_estimate["volume_trend"]
                        perf_lines.append("")
                        perf_lines.append(f"[bold]Fund Flow Signal:[/bold] [{flow_color}]{flow_label}[/{flow_color}]")
                        perf_lines.append(f"  Volume Trend (20d): [{flow_color}]{vol_trend:+.1f}%[/{flow_color}]")
                        perf_lines.append(f"  [dim]Recent Avg Vol: {etf_flow_estimate['recent_avg_vol']:,.0f}[/dim]")
                        perf_lines.append(f"  [dim]Prior Avg Vol: {etf_flow_estimate['prior_avg_vol']:,.0f}[/dim]")
                    
                    c.print(Panel("\n".join(perf_lines), title="ETF Performance & Flows", expand=False))
                
                # Display ETF Institutional Holders (data already fetched)
                if etf_institutional:
                    from rich.table import Table
                    tbl = Table(title="Top Institutional Holders", expand=False)
                    tbl.add_column("Institution", style="bold")
                    tbl.add_column("Shares", justify="right")
                    tbl.add_column("Change", justify="right")
                    tbl.add_column("Reported")
                    
                    for h in etf_institutional:
                        name = h.get('holder', 'Unknown')
                        if len(name) > 30:
                            name = name[:27] + "..."
                        shares = h.get('shares', 0)
                        change = h.get('change', 0)
                        date_rep = h.get('dateReported', '')[:10] if h.get('dateReported') else '—'
                        
                        # Color the change
                        if change > 0:
                            chg_str = f"[green]+{change:,}[/green]"
                        elif change < 0:
                            chg_str = f"[red]{change:,}[/red]"
                        else:
                            chg_str = "—"
                        
                        tbl.add_row(name, f"{shares:,}", chg_str, date_rep)
                    
                    c.print(tbl)
            else:
                # Regular stock profile
                c.print(Panel(
                    f"[bold]Company:[/bold] {profile.company_name or t}\n"
                    f"[bold]Sector:[/bold] {profile.sector or '—'} / {profile.industry or '—'}\n"
                    f"[bold]Exchange:[/bold] {profile.exchange or '—'}\n"
                    f"[bold]Market Cap:[/bold] {_fmt_market_cap(profile.market_cap)}\n"
                    f"[dim]{(profile.description or '')[:300]}...[/dim]" if profile.description and len(profile.description) > 300 else f"[dim]{profile.description or ''}[/dim]",
                    title="Company Profile",
                    expand=False,
                ))
        
        # 2. Current Price & Technicals (prominent display)
        quote_data = None
        try:
            url = f"https://financialmodelingprep.com/api/v3/quote/{t}"
            resp = requests.get(url, params={"apikey": settings.fmp_api_key}, timeout=10)
            if resp.ok:
                data = resp.json()
                if data:
                    quote_data = data[0]
        except Exception:
            pass
        
        if quote_data:
            price = quote_data.get("price", 0)
            change = quote_data.get("change", 0)
            change_pct = quote_data.get("changesPercentage", 0)
            day_high = quote_data.get("dayHigh", 0)
            day_low = quote_data.get("dayLow", 0)
            year_high = quote_data.get("yearHigh", 0)
            year_low = quote_data.get("yearLow", 0)
            volume = quote_data.get("volume", 0)
            avg_volume = quote_data.get("avgVolume", 0)
            pe = quote_data.get("pe")
            
            # Color for change
            chg_color = "green" if change >= 0 else "red"
            chg_sign = "+" if change >= 0 else ""
            
            # Calculate technical levels
            pct_from_high = ((price - year_high) / year_high * 100) if year_high else 0
            pct_from_low = ((price - year_low) / year_low * 100) if year_low else 0
            day_range_pct = ((price - day_low) / (day_high - day_low) * 100) if (day_high - day_low) > 0 else 50
            
            # Volume analysis
            vol_ratio = (volume / avg_volume) if avg_volume else 1
            vol_desc = "Heavy" if vol_ratio > 1.5 else "Light" if vol_ratio < 0.5 else "Normal"
            
            price_lines = [
                f"[bold white on blue] ${price:,.2f} [/bold white on blue]  [{chg_color}]{chg_sign}{change:.2f} ({chg_sign}{change_pct:.2f}%)[/{chg_color}]",
                "",
                f"[bold]Day Range:[/bold]  ${day_low:,.2f} — ${day_high:,.2f}  [dim](now at {day_range_pct:.0f}% of range)[/dim]",
                f"[bold]52-Wk Range:[/bold] ${year_low:,.2f} — ${year_high:,.2f}",
                f"[bold]From 52-Wk High:[/bold] [{chg_color}]{pct_from_high:+.1f}%[/{chg_color}]  |  [bold]From Low:[/bold] [green]+{pct_from_low:.1f}%[/green]",
                "",
                f"[bold]Volume:[/bold] {volume:,.0f}  ({vol_ratio:.1f}x avg — {vol_desc})",
            ]
            
            c.print(Panel("\n".join(price_lines), title=f"Price & Technicals: {t}", expand=False))
        
        # 3. Hedge Fund Grade Metrics
        hf_metrics = {}
        
        # Key ratios
        try:
            url = f"https://financialmodelingprep.com/api/v3/ratios-ttm/{t}"
            resp = requests.get(url, params={"apikey": settings.fmp_api_key}, timeout=10)
            if resp.ok:
                data = resp.json()
                if data:
                    hf_metrics["ratios"] = data[0]
        except Exception:
            pass
        
        # Key metrics (includes more detailed data)
        try:
            url = f"https://financialmodelingprep.com/api/v3/key-metrics-ttm/{t}"
            resp = requests.get(url, params={"apikey": settings.fmp_api_key}, timeout=10)
            if resp.ok:
                data = resp.json()
                if data:
                    hf_metrics["key"] = data[0]
        except Exception:
            pass
        
        # Short interest / institutional
        try:
            # Analyst estimates for growth
            url = f"https://financialmodelingprep.com/api/v3/analyst-estimates/{t}"
            resp = requests.get(url, params={"apikey": settings.fmp_api_key, "period": "annual", "limit": 2}, timeout=10)
            if resp.ok:
                data = resp.json()
                if data and len(data) >= 2:
                    hf_metrics["growth"] = {
                        "eps_next_year": data[0].get("estimatedEpsAvg"),
                        "eps_this_year": data[1].get("estimatedEpsAvg") if len(data) > 1 else None,
                        "rev_next_year": data[0].get("estimatedRevenueAvg"),
                    }
        except Exception:
            pass
        
        if hf_metrics:
            ratios = hf_metrics.get("ratios", {})
            key = hf_metrics.get("key", {})
            growth = hf_metrics.get("growth", {})
            
            # Build display
            metric_lines = []
            
            # Valuation
            pe_val = ratios.get("peRatioTTM") or (quote_data.get("pe") if quote_data else None)
            ps_val = ratios.get("priceToSalesRatioTTM")
            pb_val = ratios.get("priceToBookRatioTTM")
            ev_ebitda = ratios.get("enterpriseValueOverEBITDATTM") or key.get("evToOperatingCashFlowTTM")
            
            val_parts = []
            if pe_val: val_parts.append(f"P/E: {pe_val:.1f}")
            if ps_val: val_parts.append(f"P/S: {ps_val:.1f}")
            if pb_val: val_parts.append(f"P/B: {pb_val:.1f}")
            if ev_ebitda: val_parts.append(f"EV/EBITDA: {ev_ebitda:.1f}")
            if val_parts:
                metric_lines.append(f"[bold cyan]Valuation:[/bold cyan] {' | '.join(val_parts)}")
            
            # Profitability
            roe = ratios.get("returnOnEquityTTM")
            roa = ratios.get("returnOnAssetsTTM")
            roic = ratios.get("roicTTM") or key.get("roicTTM")
            gross_margin = ratios.get("grossProfitMarginTTM")
            net_margin = ratios.get("netProfitMarginTTM")
            
            prof_parts = []
            if roe: prof_parts.append(f"ROE: {roe*100:.1f}%")
            if roic: prof_parts.append(f"ROIC: {roic*100:.1f}%")
            if gross_margin: prof_parts.append(f"Gross: {gross_margin*100:.1f}%")
            if net_margin: prof_parts.append(f"Net: {net_margin*100:.1f}%")
            if prof_parts:
                metric_lines.append(f"[bold cyan]Profitability:[/bold cyan] {' | '.join(prof_parts)}")
            
            # Leverage & Liquidity
            debt_equity = ratios.get("debtEquityRatioTTM")
            current_ratio = ratios.get("currentRatioTTM")
            quick_ratio = ratios.get("quickRatioTTM")
            fcf_yield = key.get("freeCashFlowYieldTTM")
            
            lev_parts = []
            if debt_equity is not None: lev_parts.append(f"D/E: {debt_equity:.2f}")
            if current_ratio: lev_parts.append(f"Current: {current_ratio:.1f}")
            if fcf_yield: lev_parts.append(f"FCF Yield: {fcf_yield*100:.1f}%")
            if lev_parts:
                metric_lines.append(f"[bold cyan]Leverage:[/bold cyan] {' | '.join(lev_parts)}")
            
            # Growth (if available)
            if growth:
                eps_next = growth.get("eps_next_year")
                eps_this = growth.get("eps_this_year")
                if eps_next and eps_this and eps_this != 0:
                    eps_growth = ((eps_next - eps_this) / abs(eps_this)) * 100
                    growth_color = "green" if eps_growth > 0 else "red"
                    metric_lines.append(f"[bold cyan]Est. EPS Growth:[/bold cyan] [{growth_color}]{eps_growth:+.1f}%[/{growth_color}] (${eps_this:.2f} → ${eps_next:.2f})")
            
            # PEG ratio if we have growth
            if pe_val and growth.get("eps_next_year") and growth.get("eps_this_year"):
                eps_growth_rate = ((growth["eps_next_year"] - growth["eps_this_year"]) / abs(growth["eps_this_year"])) * 100 if growth["eps_this_year"] else 0
                if eps_growth_rate > 0:
                    peg = pe_val / eps_growth_rate
                    peg_color = "green" if peg < 1 else "yellow" if peg < 2 else "red"
                    metric_lines.append(f"[bold cyan]PEG Ratio:[/bold cyan] [{peg_color}]{peg:.2f}[/{peg_color}]")
            
            if metric_lines:
                c.print(Panel("\n".join(metric_lines), title="Hedge Fund Metrics", expand=False))
        
        # 4. Quantitative snapshot (price behavior)
        try:
            from ai_options_trader.ticker.snapshot import build_ticker_snapshot
            snap = build_ticker_snapshot(settings=settings, ticker=t, benchmark="SPY", start="2020-01-01")
            
            # Format nicely instead of raw dataclass
            snap_lines = [
                f"[bold cyan]Returns:[/bold cyan]",
                f"  1M: {snap.ret_1m_pct:+.1f}%  |  3M: {snap.ret_3m_pct:+.1f}%  |  6M: {snap.ret_6m_pct:+.1f}%" if snap.ret_6m_pct else f"  1M: {snap.ret_1m_pct:+.1f}%  |  3M: {snap.ret_3m_pct:+.1f}%",
            ]
            if snap.ret_12m_pct:
                snap_lines[-1] += f"  |  12M: {snap.ret_12m_pct:+.1f}%"
            
            snap_lines.append(f"[bold cyan]Volatility:[/bold cyan] {snap.vol_20d_ann_pct:.1f}% (20d) | {snap.vol_60d_ann_pct:.1f}% (60d)")
            
            if snap.max_drawdown_12m_pct:
                snap_lines.append(f"[bold cyan]Max Drawdown (12M):[/bold cyan] {snap.max_drawdown_12m_pct:.1f}%")
            
            if snap.rel_ret_3m_pct is not None:
                rel_color = "green" if snap.rel_ret_3m_pct > 0 else "red"
                snap_lines.append(f"[bold cyan]vs SPY (3M):[/bold cyan] [{rel_color}]{snap.rel_ret_3m_pct:+.1f}%[/{rel_color}]")
            
            c.print(Panel("\n".join(snap_lines), title="Price Behavior", expand=False))
        except Exception as e:
            c.print(Panel(f"Snapshot unavailable: {e}", title="Price Behavior", expand=False))
        
        # 3. SEC Filings summary
        from ai_options_trader.altdata.sec import fetch_8k_filings, fetch_annual_quarterly_reports, summarize_filings
        
        filings_8k = fetch_8k_filings(settings=settings, ticker=t, limit=5)
        filings_periodic = fetch_annual_quarterly_reports(settings=settings, ticker=t, limit=4)
        all_filings = sorted(filings_8k + filings_periodic, key=lambda x: x.filed_date, reverse=True)
        
        if all_filings:
            summary = summarize_filings(all_filings)
            filing_lines = [f"[bold]Recent filings:[/bold] {summary['total']} ({summary['by_type']})"]
            
            for f in all_filings[:5]:
                items_str = f" ({', '.join(f.items[:2])})" if f.items else ""
                filing_lines.append(f"  • {f.filed_date}: {f.form_type}{items_str}")
            
            c.print(Panel("\n".join(filing_lines), title="SEC Filings", expand=False))
        
        # 4. Earnings & Analyst Estimates
        from ai_options_trader.altdata.earnings import fetch_earnings_surprises, fetch_upcoming_earnings, analyze_earnings_history
        import requests
        
        surprises = fetch_earnings_surprises(settings=settings, ticker=t, limit=8)
        upcoming = fetch_upcoming_earnings(settings=settings, tickers=[t], days_ahead=90)
        
        # Fetch analyst price targets
        analyst_targets = {}
        try:
            url = "https://financialmodelingprep.com/api/v4/price-target-consensus"
            resp = requests.get(url, params={"apikey": settings.fmp_api_key, "symbol": t}, timeout=10)
            if resp.ok:
                data = resp.json()
                analyst_targets = data[0] if data else {}
        except Exception:
            pass
        
        # Fetch analyst EPS estimates
        eps_estimates = {}
        try:
            url = f"https://financialmodelingprep.com/api/v3/analyst-estimates/{t}"
            resp = requests.get(url, params={"apikey": settings.fmp_api_key, "period": "quarter", "limit": 4}, timeout=10)
            if resp.ok:
                data = resp.json()
                eps_estimates = data[0] if data else {}
        except Exception:
            pass
        
        earnings_lines = []
        
        # Upcoming earnings with estimates
        if upcoming:
            next_ev = upcoming[0]
            earnings_lines.append(f"[bold cyan]Next Earnings:[/bold cyan] {next_ev.date} {(next_ev.time or '').upper()}")
            if next_ev.eps_estimated is not None:
                earnings_lines.append(f"  [bold]EPS Estimate:[/bold] ${next_ev.eps_estimated:.2f}")
            if next_ev.revenue_estimated is not None:
                earnings_lines.append(f"  [bold]Rev Estimate:[/bold] ${next_ev.revenue_estimated / 1e9:.2f}B")
            
            # Add context from recent performance
            if surprises:
                last_eps_actual = surprises[0].eps_actual
                if last_eps_actual and next_ev.eps_estimated:
                    implied_growth = ((next_ev.eps_estimated - last_eps_actual) / abs(last_eps_actual)) * 100 if last_eps_actual else 0
                    growth_color = "green" if implied_growth > 0 else "red"
                    earnings_lines.append(f"  [bold]Implied YoY:[/bold] [{growth_color}]{implied_growth:+.1f}%[/{growth_color}]")
            earnings_lines.append("")
        
        # Analyst price targets
        if analyst_targets:
            target_consensus = analyst_targets.get('targetConsensus')
            target_low = analyst_targets.get('targetLow')
            target_high = analyst_targets.get('targetHigh')
            num_analysts = analyst_targets.get('numberOfAnalysts')
            
            earnings_lines.append(f"[bold cyan]Analyst Targets:[/bold cyan]")
            if target_consensus:
                # Calculate upside/downside if we have current price
                try:
                    from ai_options_trader.data.quotes import fetch_stock_last_prices
                    last_px, _, _ = fetch_stock_last_prices(settings=settings, symbols=[t], max_symbols_for_live=5)
                    current_px = last_px.get(t)
                    if current_px and target_consensus:
                        upside = ((target_consensus - current_px) / current_px) * 100
                        upside_color = "green" if upside > 0 else "red"
                        earnings_lines.append(f"  [bold]Consensus:[/bold] ${target_consensus:.2f} ([{upside_color}]{upside:+.1f}%[/{upside_color}])")
                    else:
                        earnings_lines.append(f"  [bold]Consensus:[/bold] ${target_consensus:.2f}")
                except Exception:
                    earnings_lines.append(f"  [bold]Consensus:[/bold] ${target_consensus:.2f}")
            if target_low and target_high:
                earnings_lines.append(f"  [bold]Range:[/bold] ${target_low:.2f} - ${target_high:.2f}")
            if num_analysts:
                earnings_lines.append(f"  [bold]# Analysts:[/bold] {num_analysts}")
            earnings_lines.append("")
        
        # Historical performance
        if surprises:
            analysis = analyze_earnings_history(surprises)
            earnings_lines.append(f"[bold cyan]Earnings History:[/bold cyan]")
            earnings_lines.append(f"  [bold]Beat rate:[/bold] {analysis['beat_rate']:.0f}% (last {analysis['count']} quarters)")
            earnings_lines.append(f"  [bold]Avg surprise:[/bold] {analysis['avg_surprise_pct']:+.1f}%")
            if analysis['streak'] > 1:
                streak_color = "green" if analysis['streak_type'] == 'beat' else "red"
                earnings_lines.append(f"  [bold]Streak:[/bold] [{streak_color}]{analysis['streak']} consecutive {analysis['streak_type']}s[/{streak_color}]")
            
            # Show last 4 quarters inline
            if len(surprises) >= 1:
                recent_surprises = []
                for s in surprises[:4]:
                    if s.eps_surprise_pct is not None:
                        icon = "✓" if s.eps_surprise_pct > 0 else "✗"
                        recent_surprises.append(f"{icon}{s.eps_surprise_pct:+.0f}%")
                if recent_surprises:
                    earnings_lines.append(f"  [bold]Recent:[/bold] {' → '.join(recent_surprises)}")
        
        if earnings_lines:
            c.print(Panel("\n".join(earnings_lines), title="Earnings & Estimates", expand=False))
        
        # 5. News with sentiment
        from ai_options_trader.llm.outlooks.ticker_news import fetch_fmp_stock_news
        from ai_options_trader.llm.core.sentiment import analyze_article_sentiment, aggregate_sentiment
        
        now = datetime.now(timezone.utc).date()
        from_date = (now - timedelta(days=14)).isoformat()
        
        try:
            news_items = fetch_fmp_stock_news(
                settings=settings,
                tickers=[t],
                from_date=from_date,
                to_date=now.isoformat(),
                max_pages=2,
            )
            
            if news_items:
                # Analyze sentiment
                article_sentiments = [
                    analyze_article_sentiment(
                        headline=item.title or "",
                        content=item.snippet or "",
                        source=item.source or "",
                        url=item.url or "",
                        published_at=str(item.published_at or ""),
                    )
                    for item in news_items[:10]
                ]
                
                agg = aggregate_sentiment(article_sentiments)
                
                sentiment_color = "green" if agg.label == "positive" else "red" if agg.label == "negative" else "yellow"
                
                news_lines = [
                    f"[bold]Aggregate sentiment:[/bold] [{sentiment_color}]{agg.label.upper()}[/{sentiment_color}] (score: {agg.score:+.2f})",
                    f"[bold]Articles:[/bold] {agg.positive_count} positive, {agg.negative_count} negative, {agg.neutral_count} neutral",
                    "",
                    "[bold]Recent headlines:[/bold]",
                ]
                
                for item in news_items[:5]:
                    sent = analyze_article_sentiment(item.title or "")
                    sent_icon = "🟢" if sent.sentiment.label == "positive" else "🔴" if sent.sentiment.label == "negative" else "⚪"
                    news_lines.append(f"  {sent_icon} {item.title[:70]}...")
                
                c.print(Panel("\n".join(news_lines), title="News & Sentiment (14d)", expand=False))
        except Exception as e:
            c.print(Panel(f"News unavailable: {e}", title="News", expand=False))
        
        # 6. LLM Analysis
        if llm and settings.openai_api_key:
            c.print("\n[bold cyan]Generating LLM analysis...[/bold cyan]\n")
            
            try:
                from openai import OpenAI
                import json
                
                # Build context - different for ETFs vs stocks
                if is_etf:
                    # ETF context
                    context = {
                        "ticker": t,
                        "asset_type": "ETF",
                        "profile": profile.__dict__ if profile else None,
                        "etf_info": etf_data,
                        "top_holdings": [
                            {"asset": format_holding_name(h), "weight": h.get("weightPercentage")}
                            for h in etf_holdings[:10]
                        ] if etf_holdings else [],
                        "performance": etf_perf_data or None,
                        "fund_flow_signal": etf_flow_estimate,
                        "top_institutional_holders": [
                            {"holder": h.get("holder"), "shares": h.get("shares"), "change": h.get("change")}
                            for h in etf_institutional[:5]
                        ] if etf_institutional else [],
                        "news_sentiment": {
                            "label": agg.label,
                            "score": agg.score,
                            "positive": agg.positive_count,
                            "negative": agg.negative_count,
                        } if 'agg' in dir() else None,
                    }
                else:
                    # Stock context
                    next_earnings_ctx = None
                    if upcoming:
                        next_ev = upcoming[0]
                        next_earnings_ctx = {
                            "date": next_ev.date,
                            "time": next_ev.time,
                            "eps_estimate": next_ev.eps_estimated,
                            "revenue_estimate": next_ev.revenue_estimated,
                        }
                    
                    analyst_ctx = None
                    if analyst_targets:
                        analyst_ctx = {
                            "consensus_target": analyst_targets.get('targetConsensus'),
                            "low_target": analyst_targets.get('targetLow'),
                            "high_target": analyst_targets.get('targetHigh'),
                            "num_analysts": analyst_targets.get('numberOfAnalysts'),
                        }
                    
                    context = {
                        "ticker": t,
                        "asset_type": "Stock",
                        "profile": profile.__dict__ if profile else None,
                        "recent_filings": [
                            {"date": f.filed_date, "form": f.form_type, "items": f.items}
                            for f in all_filings[:5]
                        ] if all_filings else [],
                        "earnings_analysis": analyze_earnings_history(surprises) if surprises else None,
                        "next_earnings": next_earnings_ctx,
                        "analyst_targets": analyst_ctx,
                        "news_sentiment": {
                            "label": agg.label,
                            "score": agg.score,
                            "positive": agg.positive_count,
                            "negative": agg.negative_count,
                        } if 'agg' in dir() else None,
                    }
                
                client = OpenAI(api_key=settings.openai_api_key)
                model = llm_model.strip() or settings.openai_model or "gpt-4o-mini"
                
                if is_etf:
                    # ETF-specific prompt
                    prompt = f"""You are a senior portfolio strategist specializing in ETF analysis. Provide a concise analysis for {t}.

IMPORTANT: This is an ETF (Exchange-Traded Fund), NOT a stock. Do NOT mention company earnings, EPS, revenue, or other single-stock metrics. Focus on fund-level analysis.

Context data:
{json.dumps(context, indent=2, default=str)}

Provide:
1. **Fund Thesis** (2-3 sentences): What exposure does this ETF provide? What's the investment case?
2. **Holdings Analysis**: Analyze the top holdings concentration and sector exposure
3. **Performance & Flows**: Analyze the performance returns (1W, 1M, 3M, YTD, 1Y) and fund flow signals. Is money flowing in or out? What does this suggest about investor sentiment?
4. **Risk Factors** (2-3 sentences): Key risks (expense ratio, tracking error, concentration, underlying asset risks)
5. **Market Environment**: What macro conditions favor or hurt this ETF? When would an investor use this?

Be specific about the ETF's strategy, holdings, and flow dynamics. Do NOT reference earnings or company-specific metrics. Keep total response under 350 words."""
                else:
                    # Stock-specific prompt  
                    prompt = f"""You are a senior equity research analyst. Provide a concise investment analysis for {t}.

Context data:
{json.dumps(context, indent=2, default=str)}

Provide:
1. **Bull Case** (2-3 sentences): Key positives and upside catalysts
2. **Bear Case** (2-3 sentences): Key risks and concerns  
3. **Earnings Preview**: Analyze upcoming earnings expectations vs historical beat rate. What would constitute a beat/miss? Any particular metrics to watch?
4. **Near-term View** (2-3 sentences): What to watch in next 30-60 days, referencing analyst targets and earnings date
5. **Sentiment Summary**: How does recent news/filings affect the thesis?

Be specific and reference the data provided (analyst estimates, beat rate, price targets). Keep total response under 350 words."""

                resp = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3,
                    max_tokens=500,
                )
                
                analysis = resp.choices[0].message.content or ""
                c.print(Panel(Markdown(analysis), title="LLM Analysis", expand=False))
                
            except Exception as e:
                c.print(Panel(f"LLM analysis unavailable: {e}", title="LLM Analysis", expand=False))
        
        c.print(f"\n[dim]Deep dive complete for {t}[/dim]\n")


