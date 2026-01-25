"""
Deep Dive Command - Hedge fund grade ticker analysis (v0)

Works for both stocks and ETFs with appropriate metrics for each.
"""
from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.columns import Columns
from datetime import datetime, timedelta

from ai_options_trader.config import load_settings

console = Console()


def register(app: typer.Typer) -> None:
    @app.command("deep")
    def deep_dive(
        ticker: str = typer.Argument(..., help="Ticker symbol (stock or ETF)"),
        refresh: bool = typer.Option(False, "--refresh", help="Force refresh data"),
        llm: bool = typer.Option(False, "--llm", help="Add geopolitical macro analysis"),
        thesis: str = typer.Option("", "--thesis", help="Your directional thesis (e.g., 'bearish due to tariffs')"),
    ):
        """
        Hedge fund grade deep dive on a ticker.
        
        For STOCKS: profile, earnings, key ratios, performance
        For ETFs: profile, flows, holdings exposure, performance
        
        Use --llm for geopolitical macro context and trade thesis.
        """
        from rich.markdown import Markdown
        
        settings = load_settings()
        t = ticker.strip().upper()
        
        console.print(f"\n[bold cyan]Deep Dive: {t}[/bold cyan]")
        console.print("[dim]Loading...[/dim]\n")
        
        # Determine if ETF or stock
        is_etf = _is_etf(t, settings)
        
        # Collect data for LLM
        data_context = {"ticker": t, "is_etf": is_etf}
        
        if is_etf:
            data_context.update(_etf_deep_dive(t, settings, refresh))
        else:
            data_context.update(_stock_deep_dive(t, settings, refresh))
        
        # LLM Analysis
        if llm:
            console.print("[dim]Generating macro analysis...[/dim]\n")
            analysis = _generate_macro_analysis(t, settings, data_context, thesis=thesis)
            if analysis:
                console.print(Panel(Markdown(analysis), title="Geopolitical Macro Analysis", border_style="magenta"))


def _is_etf(ticker: str, settings) -> bool:
    """Detect if ticker is an ETF."""
    # Common ETF patterns
    known_etfs = {
        "SPY", "QQQ", "IWM", "DIA", "VTI", "VOO", "VXX", "VIXY", "UVXY",
        "XLF", "XLE", "XLK", "XLV", "XLY", "XLP", "XLI", "XLB", "XLU", "XLRE",
        "GLD", "SLV", "USO", "UNG", "DBC", "GLDM",
        "TLT", "IEF", "SHY", "HYG", "LQD", "JNK", "TBF", "TBT",
        "EEM", "EFA", "VWO", "FXI", "MCHI", "KWEB",
        "SMH", "SOXX", "XRT", "XHB", "ITB", "IYT", "XAR",
        "ARKK", "ARKG", "ARKW", "ARKF",
        "SQQQ", "TQQQ", "SPXU", "UPRO", "PSQ",
        "SLX", "MOO", "DBA", "CORN", "SOYB", "PAVE", "TAN", "ICLN",
        "IBIT", "BITO", "VIXM",
    }
    return ticker.upper() in known_etfs


def _stock_deep_dive(ticker: str, settings, refresh: bool) -> dict:
    """Deep dive for individual stocks. Returns data context for LLM."""
    import requests
    
    # 1. Company Profile
    profile = _fetch_company_profile(ticker, settings)
    
    # 2. Key Metrics
    metrics = _fetch_key_metrics(ticker, settings)
    
    # 3. Earnings Calendar
    earnings = _fetch_earnings(ticker, settings)
    
    # 4. Price Performance
    perf = _fetch_performance(ticker, settings)
    
    # 5. Analyst Estimates
    estimates = _fetch_analyst_estimates(ticker, settings)
    
    # === DISPLAY ===
    
    # Profile Panel
    if profile:
        employees = profile.get('fullTimeEmployees')
        try:
            employees_str = f"{int(employees):,}" if employees else "N/A"
        except (ValueError, TypeError):
            employees_str = str(employees) if employees else "N/A"
        profile_text = (
            f"[bold]{profile.get('companyName', ticker)}[/bold]\n"
            f"[dim]{profile.get('exchange', '')} | {profile.get('currency', 'USD')}[/dim]\n\n"
            f"[bold]Sector:[/bold] {profile.get('sector', 'N/A')}\n"
            f"[bold]Industry:[/bold] {profile.get('industry', 'N/A')}\n"
            f"[bold]Market Cap:[/bold] {_fmt_large_num(profile.get('mktCap', 0))}\n"
            f"[bold]Employees:[/bold] {employees_str}"
        )
        console.print(Panel(profile_text, title="Company Profile", border_style="blue"))
    
    # Key Metrics Table
    if metrics:
        metrics_table = Table(title="Key Metrics", show_header=False, box=None)
        metrics_table.add_column("Metric", style="dim", width=20)
        metrics_table.add_column("Value", style="bold", width=15)
        
        metrics_table.add_row("P/E Ratio", f"{metrics.get('peRatioTTM', 'N/A'):.1f}" if metrics.get('peRatioTTM') else "N/A")
        metrics_table.add_row("P/S Ratio", f"{metrics.get('priceToSalesRatioTTM', 'N/A'):.1f}" if metrics.get('priceToSalesRatioTTM') else "N/A")
        metrics_table.add_row("P/B Ratio", f"{metrics.get('pbRatioTTM', 'N/A'):.1f}" if metrics.get('pbRatioTTM') else "N/A")
        metrics_table.add_row("EV/EBITDA", f"{metrics.get('enterpriseValueOverEBITDATTM', 'N/A'):.1f}" if metrics.get('enterpriseValueOverEBITDATTM') else "N/A")
        metrics_table.add_row("Debt/Equity", f"{metrics.get('debtToEquityTTM', 'N/A'):.2f}" if metrics.get('debtToEquityTTM') else "N/A")
        metrics_table.add_row("ROE", f"{metrics.get('roeTTM', 0)*100:.1f}%" if metrics.get('roeTTM') else "N/A")
        metrics_table.add_row("Gross Margin", f"{metrics.get('grossProfitMarginTTM', 0)*100:.1f}%" if metrics.get('grossProfitMarginTTM') else "N/A")
        metrics_table.add_row("Net Margin", f"{metrics.get('netProfitMarginTTM', 0)*100:.1f}%" if metrics.get('netProfitMarginTTM') else "N/A")
        metrics_table.add_row("Dividend Yield", f"{metrics.get('dividendYieldTTM', 0)*100:.2f}%" if metrics.get('dividendYieldTTM') else "N/A")
        
        console.print(metrics_table)
    
    # Earnings & Estimates
    earnings_parts = []
    if earnings:
        e = earnings
        earnings_text = (
            f"[bold]Next Earnings:[/bold] {e.get('date', 'N/A')} {e.get('time', '').upper()}\n"
            f"[bold]EPS Estimate:[/bold] ${e.get('epsEstimated', 'N/A')}\n"
            f"[bold]Rev Estimate:[/bold] {_fmt_large_num(e.get('revenueEstimated', 0))}"
        )
        earnings_parts.append(Panel(earnings_text, title="📅 Upcoming Earnings", border_style="yellow"))
    
    if estimates:
        est_text = (
            f"[bold]Target Price:[/bold] ${estimates.get('targetConsensus', 'N/A')}\n"
            f"[bold]Range:[/bold] ${estimates.get('targetLow', 'N/A')} - ${estimates.get('targetHigh', 'N/A')}\n"
            f"[bold]# Analysts:[/bold] {estimates.get('numberOfAnalysts', 'N/A')}"
        )
        earnings_parts.append(Panel(est_text, title="🎯 Analyst Targets", border_style="green"))
    
    if earnings_parts:
        console.print(Columns(earnings_parts))
    
    # Performance Table
    _print_performance_table(ticker, perf)
    
    console.print()
    
    # Return context for LLM
    return {
        "profile": profile,
        "metrics": metrics,
        "earnings": earnings,
        "performance": perf,
        "estimates": estimates,
    }


def _etf_deep_dive(ticker: str, settings, refresh: bool) -> dict:
    """Deep dive for ETFs. Returns data context for LLM."""
    import requests
    
    # 1. ETF Profile
    profile = _fetch_etf_profile(ticker, settings)
    
    # 2. Holdings (top 10)
    holdings = _fetch_etf_holdings(ticker, settings)
    
    # 3. Performance
    perf = _fetch_performance(ticker, settings)
    
    # 4. ETF-specific metrics
    hf_metrics = _calculate_hf_etf_metrics(ticker, settings, perf)
    
    # === DISPLAY ===
    
    # Profile Panel
    if profile:
        expense = profile.get('expenseRatio')
        expense_str = f"{expense:.2%}" if expense else "N/A"
        avg_vol = profile.get('avgVolume', 0)
        avg_vol_str = f"{avg_vol:,.0f}" if avg_vol else "N/A"
        profile_text = (
            f"[bold]{profile.get('name', ticker)}[/bold]\n"
            f"[dim]{profile.get('exchange', '')}[/dim]\n\n"
            f"[bold]Expense Ratio:[/bold] {expense_str}\n"
            f"[bold]AUM:[/bold] {_fmt_large_num(profile.get('totalAssets', 0))}\n"
            f"[bold]Avg Volume:[/bold] {avg_vol_str}\n"
            f"[bold]Inception:[/bold] {profile.get('inceptionDate', 'N/A')}"
        )
        console.print(Panel(profile_text, title="ETF Profile", border_style="blue"))
    
    # Top Holdings Table
    if holdings:
        holdings_table = Table(title="Top 10 Holdings", show_header=True, header_style="bold")
        holdings_table.add_column("#", style="dim", width=3)
        holdings_table.add_column("Ticker", style="cyan", width=8)
        holdings_table.add_column("Name", width=30)
        holdings_table.add_column("Weight", justify="right", width=10)
        
        for i, h in enumerate(holdings[:10], 1):
            weight = h.get('weightPercentage', 0)
            holdings_table.add_row(
                str(i),
                h.get('asset', 'N/A'),
                h.get('name', '')[:30],
                f"{weight:.2f}%" if weight else "N/A",
            )
        
        console.print(holdings_table)
    
    # Hedge Fund Metrics Panel
    if hf_metrics:
        hf_text = (
            f"[bold]Concentration:[/bold] Top 10 = {hf_metrics.get('top10_weight', 0):.1f}%\n"
            f"[bold]Vol (30d Ann):[/bold] {hf_metrics.get('vol_30d', 0):.1f}%\n"
            f"[bold]Sharpe (YTD):[/bold] {hf_metrics.get('sharpe_ytd', 0):.2f}\n"
            f"[bold]Max Drawdown:[/bold] {hf_metrics.get('max_dd', 0):.1f}%\n"
            f"[bold]Beta (vs SPY):[/bold] {hf_metrics.get('beta', 0):.2f}"
        )
        console.print(Panel(hf_text, title="📊 HF-Grade Metrics", border_style="magenta"))
    
    # Performance Table
    _print_performance_table(ticker, perf)
    
    console.print()
    
    # Return context for LLM
    return {
        "profile": profile,
        "holdings": holdings[:10] if holdings else [],
        "performance": perf,
        "hf_metrics": hf_metrics,
    }


def _fetch_company_profile(ticker: str, settings) -> dict:
    """Fetch company profile from FMP."""
    try:
        import requests
        url = f"https://financialmodelingprep.com/api/v3/profile/{ticker}"
        resp = requests.get(url, params={"apikey": settings.FMP_API_KEY}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return data[0] if data else {}
    except Exception:
        return {}


def _fetch_key_metrics(ticker: str, settings) -> dict:
    """Fetch key metrics TTM from FMP."""
    try:
        import requests
        url = f"https://financialmodelingprep.com/api/v3/key-metrics-ttm/{ticker}"
        resp = requests.get(url, params={"apikey": settings.FMP_API_KEY}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return data[0] if data else {}
    except Exception:
        return {}


def _fetch_earnings(ticker: str, settings) -> dict:
    """Fetch next earnings date from FMP."""
    try:
        import requests
        now = datetime.now()
        from_date = now.strftime("%Y-%m-%d")
        to_date = (now + timedelta(days=90)).strftime("%Y-%m-%d")
        
        url = "https://financialmodelingprep.com/api/v3/earning_calendar"
        resp = requests.get(url, params={
            "apikey": settings.FMP_API_KEY,
            "from": from_date,
            "to": to_date,
        }, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        
        for e in data:
            if e.get("symbol", "").upper() == ticker.upper():
                return e
        return {}
    except Exception:
        return {}


def _fetch_analyst_estimates(ticker: str, settings) -> dict:
    """Fetch analyst price targets from FMP."""
    try:
        import requests
        url = f"https://financialmodelingprep.com/api/v4/price-target-consensus"
        resp = requests.get(url, params={"apikey": settings.FMP_API_KEY, "symbol": ticker}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return data[0] if data else {}
    except Exception:
        return {}


def _fetch_etf_profile(ticker: str, settings) -> dict:
    """Fetch ETF profile from FMP."""
    try:
        import requests
        url = f"https://financialmodelingprep.com/api/v3/etf-info"
        resp = requests.get(url, params={"apikey": settings.FMP_API_KEY, "symbol": ticker}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return data[0] if data else {}
    except Exception:
        return {}


def _fetch_etf_holdings(ticker: str, settings) -> list:
    """Fetch ETF holdings from FMP."""
    try:
        import requests
        url = f"https://financialmodelingprep.com/api/v3/etf-holder/{ticker}"
        resp = requests.get(url, params={"apikey": settings.FMP_API_KEY}, timeout=10)
        resp.raise_for_status()
        return resp.json() or []
    except Exception:
        return []


def _fetch_performance(ticker: str, settings) -> dict:
    """Fetch price data and calculate returns."""
    try:
        from ai_options_trader.data.market import fetch_equity_daily_closes
        import pandas as pd
        
        px = fetch_equity_daily_closes(settings=settings, symbols=[ticker], start="2024-01-01", refresh=False)
        if px is None or px.empty or ticker not in px.columns:
            return {}
        
        prices = px[ticker].dropna()
        if len(prices) < 10:
            return {}
        
        current = prices.iloc[-1]
        
        returns = {}
        returns["price"] = current
        
        # 1 week
        if len(prices) >= 5:
            returns["1w"] = (current / prices.iloc[-5] - 1) * 100
        
        # 1 month
        if len(prices) >= 21:
            returns["1m"] = (current / prices.iloc[-21] - 1) * 100
        
        # 3 months
        if len(prices) >= 63:
            returns["3m"] = (current / prices.iloc[-63] - 1) * 100
        
        # YTD
        ytd_prices = prices[prices.index >= "2025-01-01"]
        if len(ytd_prices) > 1:
            returns["ytd"] = (current / ytd_prices.iloc[0] - 1) * 100
        
        # 52-week high/low
        if len(prices) >= 252:
            h52 = prices.iloc[-252:].max()
            l52 = prices.iloc[-252:].min()
            returns["52w_high"] = h52
            returns["52w_low"] = l52
            returns["from_52w_high"] = (current / h52 - 1) * 100
        
        # Volatility (30-day annualized)
        if len(prices) >= 30:
            daily_rets = prices.pct_change().dropna()
            returns["vol_30d"] = daily_rets.iloc[-30:].std() * (252 ** 0.5) * 100
        
        return returns
    except Exception as e:
        console.print(f"[dim]Performance fetch error: {e}[/dim]")
        return {}


def _calculate_hf_etf_metrics(ticker: str, settings, perf: dict) -> dict:
    """Calculate hedge-fund grade ETF metrics."""
    try:
        from ai_options_trader.data.market import fetch_equity_daily_closes
        import pandas as pd
        import numpy as np
        
        # Get ETF and SPY prices for beta calculation
        px = fetch_equity_daily_closes(settings=settings, symbols=[ticker, "SPY"], start="2024-01-01", refresh=False)
        if px is None or px.empty:
            return {}
        
        metrics = {}
        
        # Get holdings for concentration
        holdings = _fetch_etf_holdings(ticker, settings)
        if holdings:
            top10_weight = sum(h.get('weightPercentage', 0) for h in holdings[:10])
            metrics["top10_weight"] = top10_weight
        
        # Volatility from perf
        metrics["vol_30d"] = perf.get("vol_30d", 0)
        
        # Beta vs SPY
        if ticker in px.columns and "SPY" in px.columns:
            etf_rets = px[ticker].pct_change().dropna()
            spy_rets = px["SPY"].pct_change().dropna()
            
            # Align
            aligned = pd.concat([etf_rets, spy_rets], axis=1).dropna()
            if len(aligned) > 20:
                cov = aligned.cov().iloc[0, 1]
                var = aligned.iloc[:, 1].var()
                beta = cov / var if var > 0 else 1.0
                metrics["beta"] = beta
        
        # Sharpe YTD (simplified)
        if ticker in px.columns:
            ytd_prices = px[ticker][px.index >= "2025-01-01"].dropna()
            if len(ytd_prices) > 20:
                ytd_rets = ytd_prices.pct_change().dropna()
                mean_ret = ytd_rets.mean() * 252
                std_ret = ytd_rets.std() * (252 ** 0.5)
                sharpe = mean_ret / std_ret if std_ret > 0 else 0
                metrics["sharpe_ytd"] = sharpe
        
        # Max Drawdown
        if ticker in px.columns:
            prices = px[ticker].dropna()
            if len(prices) > 20:
                rolling_max = prices.expanding().max()
                drawdown = (prices / rolling_max - 1) * 100
                metrics["max_dd"] = drawdown.min()
        
        return metrics
    except Exception:
        return {}


def _print_performance_table(ticker: str, perf: dict):
    """Print performance table."""
    if not perf:
        return
    
    table = Table(title=f"Price Performance: {ticker}", show_header=True, header_style="bold")
    table.add_column("Metric", style="dim", width=15)
    table.add_column("Value", justify="right", width=15)
    
    table.add_row("Current Price", f"${perf.get('price', 0):.2f}")
    
    for period, label in [("1w", "1 Week"), ("1m", "1 Month"), ("3m", "3 Months"), ("ytd", "YTD")]:
        val = perf.get(period)
        if val is not None:
            style = "green" if val > 0 else "red" if val < 0 else ""
            table.add_row(label, f"[{style}]{val:+.2f}%[/{style}]")
    
    if perf.get("52w_high"):
        table.add_row("52W High", f"${perf['52w_high']:.2f}")
        table.add_row("From 52W High", f"{perf.get('from_52w_high', 0):.1f}%")
    
    if perf.get("vol_30d"):
        table.add_row("30D Vol (Ann)", f"{perf['vol_30d']:.1f}%")
    
    console.print(table)


def _fmt_large_num(n) -> str:
    """Format large numbers (billions, millions)."""
    if not n:
        return "N/A"
    try:
        n = float(n)
        if n >= 1e12:
            return f"${n/1e12:.2f}T"
        elif n >= 1e9:
            return f"${n/1e9:.2f}B"
        elif n >= 1e6:
            return f"${n/1e6:.1f}M"
        else:
            return f"${n:,.0f}"
    except:
        return "N/A"


def _fetch_news(ticker: str, settings, days: int = 7) -> list:
    """Fetch recent news for the ticker."""
    try:
        import requests
        url = f"https://financialmodelingprep.com/api/v3/stock_news"
        resp = requests.get(url, params={
            "apikey": settings.FMP_API_KEY,
            "tickers": ticker,
            "limit": 15,
        }, timeout=10)
        resp.raise_for_status()
        return resp.json() or []
    except Exception:
        return []


def _fetch_economic_calendar(settings, days_ahead: int = 30) -> list:
    """Fetch upcoming economic events."""
    try:
        import requests
        from datetime import datetime, timedelta
        
        now = datetime.now()
        from_date = now.strftime("%Y-%m-%d")
        to_date = (now + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
        
        url = "https://financialmodelingprep.com/api/v3/economic_calendar"
        resp = requests.get(url, params={
            "apikey": settings.FMP_API_KEY,
            "from": from_date,
            "to": to_date,
        }, timeout=10)
        resp.raise_for_status()
        data = resp.json() or []
        
        # Filter for high-impact events related to China, trade, Fed
        keywords = ["china", "gdp", "trade", "tariff", "fed", "fomc", "pmi", "cpi", "employment", "retail"]
        filtered = []
        for e in data:
            event_name = (e.get("event", "") or "").lower()
            country = (e.get("country", "") or "").lower()
            if any(kw in event_name or kw in country for kw in keywords) or e.get("impact") == "High":
                filtered.append({
                    "date": e.get("date"),
                    "event": e.get("event"),
                    "country": e.get("country"),
                    "impact": e.get("impact"),
                    "forecast": e.get("estimate"),
                    "previous": e.get("previous"),
                })
        return filtered[:15]
    except Exception:
        return []


def _fetch_holdings_earnings(holdings: list, settings) -> list:
    """Fetch earnings dates for ETF holdings."""
    try:
        import requests
        from datetime import datetime, timedelta
        
        now = datetime.now()
        from_date = now.strftime("%Y-%m-%d")
        to_date = (now + timedelta(days=60)).strftime("%Y-%m-%d")
        
        url = "https://financialmodelingprep.com/api/v3/earning_calendar"
        resp = requests.get(url, params={
            "apikey": settings.FMP_API_KEY,
            "from": from_date,
            "to": to_date,
        }, timeout=10)
        resp.raise_for_status()
        all_earnings = resp.json() or []
        
        # Match holdings to earnings
        # Map HK tickers to US ADRs for matching
        ticker_map = {
            "9988.HK": "BABA",
            "0700.HK": "TCEHY", 
            "1810.HK": "XIACF",
            "3690.HK": "MPNGY",
            "9999.HK": "NTES",
            "1211.HK": "BYDDY",
            "9888.HK": "BIDU",
            "2318.HK": "PNGAY",
        }
        
        holding_tickers = set()
        for h in holdings[:10]:
            hk_ticker = h.get("asset", "")
            if hk_ticker in ticker_map:
                holding_tickers.add(ticker_map[hk_ticker])
            # Also try the name
            name = (h.get("name", "") or "").upper()
            if "ALIBABA" in name:
                holding_tickers.add("BABA")
            elif "TENCENT" in name:
                holding_tickers.add("TCEHY")
            elif "BAIDU" in name:
                holding_tickers.add("BIDU")
            elif "NETEASE" in name:
                holding_tickers.add("NTES")
            elif "BYD" in name:
                holding_tickers.add("BYDDY")
        
        results = []
        for e in all_earnings:
            sym = (e.get("symbol", "") or "").upper()
            if sym in holding_tickers:
                results.append({
                    "symbol": sym,
                    "date": e.get("date"),
                    "time": e.get("time"),
                    "eps_estimate": e.get("epsEstimated"),
                    "revenue_estimate": e.get("revenueEstimated"),
                })
        
        return results[:10]
    except Exception:
        return []


def _generate_macro_analysis(ticker: str, settings, data_context: dict, thesis: str = "") -> str:
    """Generate geopolitical macro analysis using LLM."""
    import json
    
    if not settings.openai_api_key:
        return "OPENAI_API_KEY not configured."
    
    try:
        from openai import OpenAI
    except ImportError:
        return "OpenAI package not installed."
    
    client = OpenAI(api_key=settings.openai_api_key)
    
    # Fetch news
    news = _fetch_news(ticker, settings)
    news_summary = []
    for n in news[:10]:
        news_summary.append({
            "title": n.get("title", ""),
            "source": n.get("site", ""),
            "date": n.get("publishedDate", ""),
        })
    
    # Fetch REAL economic calendar events
    econ_calendar = _fetch_economic_calendar(settings, days_ahead=45)
    
    # Fetch REAL earnings dates for holdings
    holdings = data_context.get("holdings", [])
    holdings_earnings = _fetch_holdings_earnings(holdings, settings) if holdings else []
    
    # Build context
    context = {
        "ticker": ticker,
        "is_etf": data_context.get("is_etf", False),
        "performance": data_context.get("performance", {}),
        "holdings": holdings,
        "profile": data_context.get("profile", {}),
        "hf_metrics": data_context.get("hf_metrics", {}),
        "recent_news": news_summary,
        "economic_calendar": econ_calendar,
        "holdings_earnings": holdings_earnings,
    }
    
    # Determine asset-specific context
    etf_context = ""
    if data_context.get("is_etf"):
        if holdings:
            top_names = [h.get("name", "") for h in holdings[:5]]
            etf_context = f"This ETF's top holdings include: {', '.join(top_names)}."
    
    # User's thesis directive
    thesis_directive = ""
    if thesis:
        thesis_directive = f"""
**IMPORTANT**: The trader's thesis is: "{thesis}"
Evaluate this thesis critically. If it has merit, structure the analysis to support it with evidence.
If the thesis has flaws, point them out but still provide actionable guidance aligned with their view.
"""
    
    # Get current date for context
    from datetime import datetime
    current_date = datetime.now().strftime("%Y-%m-%d")
    
    prompt = f"""You are a senior macro strategist at a $5B+ hedge fund writing a research note for the PM.

DATE: {current_date}
ASSET: {ticker}
{etf_context}
{thesis_directive}

RAW DATA:
{json.dumps(context, indent=2, default=str)}

Write a RESEARCH-GRADE analysis. Be specific, quantitative, and actionable.

---

## MACRO REGIME ASSESSMENT

Current positioning on key macro factors (rate each 1-5):
- US-China Trade Tension: [1=low, 5=max] — cite specific recent policy actions
- USD Strength: [1=weak, 5=strong] — note DXY level and trend
- China Growth Momentum: [1=contracting, 5=accelerating] — cite latest GDP/PMI
- Global Risk Appetite: [1=risk-off, 5=risk-on] — note VIX, credit spreads

## CATALYST CALENDAR

**IMPORTANT: Use ONLY dates from the data provided. If economic_calendar or holdings_earnings is empty, state "No confirmed catalysts in data window."**

Format (only include events from the actual data):
```
DATE        EVENT                           CONSENSUS    TRADE IMPLICATION
─────────────────────────────────────────────────────────────────────────────
[date]      [event from data]               [estimate]   [specific impact on thesis]
```

## POSITION RECOMMENDATION

**Time Horizon: 3-6 months (90-180 days)**

### Primary Expression
- Direction: [LONG/SHORT]
- Vehicle: [Equity / Put / Call / Put Spread]
- Entry: $[price] (current: ${context.get('performance', {}).get('price', 'N/A')})
- Target: $[price] ([X]% move)
- Stop: $[price] ([X]% risk)
- Position Size: [X]% of portfolio (based on conviction)

### Options Structure (if applicable)
- Contract: [TICKER] [STRIKE] [PUT/CALL] [EXPIRY]
- Premium: ~$[X] per contract
- Max Risk: $[X] per contract
- Breakeven: $[price] by expiry
- Risk/Reward: [X]:1

### Key Levels
- Support: $[price], $[price]
- Resistance: $[price], $[price]
- Invalidation: Close above/below $[price]

## THESIS SUMMARY

[2-3 sentences: Why this trade, why now, what's the edge]

Conviction: [HIGH/MEDIUM/LOW]
Primary Risk: [One sentence on what kills this trade]"""

    try:
        resp = client.chat.completions.create(
            model=settings.openai_model or "gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        return f"LLM error: {e}"
