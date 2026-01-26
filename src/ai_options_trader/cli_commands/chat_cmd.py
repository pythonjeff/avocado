"""
Interactive Research Chat - Continue conversations with the LLM analyst.

Usage:
    lox chat                           # Start fresh with portfolio context
    lox chat -c fiscal                 # Pre-load fiscal snapshot
    lox chat -c vol                    # Pre-load volatility snapshot  
    lox chat -c macro                  # Pre-load macro dashboard
    lox chat -c regimes                # Pre-load all regime data
    lox chat -c fiscal -c funding      # Multiple contexts
    lox chat -c fiscal,funding,monetary  # Comma-separated contexts

After the context loads, you can ask follow-up questions like:
    "How does the Trump tariff announcement affect my IWM position?"
    "What's the risk to my portfolio if VIX spikes to 25?"

Author: Lox Capital Research
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown

from ai_options_trader.config import load_settings

app = typer.Typer(help="Interactive research chat with LLM analyst")


def _get_context_data(context: str, refresh: bool = False) -> tuple[str, dict]:
    """Load context data based on the specified domain."""
    settings = load_settings()
    
    if context == "fiscal":
        from ai_options_trader.fiscal.signals import build_fiscal_deficit_page_data
        from ai_options_trader.fiscal.regime import classify_fiscal_regime_snapshot
        
        data = build_fiscal_deficit_page_data(settings=settings, lookback_years=5, refresh=refresh)
        
        # Extract values for regime classifier
        net = data.get("net_issuance") if isinstance(data.get("net_issuance"), dict) else None
        tga = data.get("tga") if isinstance(data.get("tga"), dict) else None
        
        regime = classify_fiscal_regime_snapshot(
            deficit_pct_gdp=data.get("deficit_pct_gdp"),
            deficit_impulse_pct_gdp=data.get("deficit_impulse_pct_gdp"),
            long_duration_issuance_share=net.get("long_share") if net else None,
            tga_z_d_4w=tga.get("z_d_4w") if tga else None,
        )
        
        return f"US Fiscal Regime: {regime.label}", {
            "domain": "fiscal",
            "regime": regime.label,
            "description": regime.description,
            "snapshot": data,
        }
    
    elif context == "vol" or context == "volatility":
        from ai_options_trader.volatility.signals import build_volatility_state
        from ai_options_trader.volatility.regime import classify_volatility_regime
        
        state = build_volatility_state(settings=settings, start_date="2020-01-01", refresh=refresh)
        regime = classify_volatility_regime(state.inputs)
        regime_label = getattr(regime, 'label', None) or getattr(regime, 'name', 'Unknown')
        
        # Build snapshot from pydantic model
        inputs = state.inputs
        snapshot = {
            "vix": inputs.vix,
            "vix_z": inputs.z_vix,
            "vix_chg_5d_pct": inputs.vix_chg_5d_pct,
            "term_spread": inputs.vix_term_spread,
            "persist_20d": inputs.persist_20d,
            "vol_pressure_score": inputs.vol_pressure_score,
        }
        
        return f"Volatility Regime: {regime_label}", {
            "domain": "volatility",
            "regime": regime_label,
            "description": getattr(regime, 'description', ''),
            "vix": inputs.vix,
            "vix_z": inputs.z_vix,
            "snapshot": snapshot,
        }
    
    elif context == "macro":
        from ai_options_trader.macro.signals import build_macro_state
        from ai_options_trader.macro.regime import classify_macro_regime_from_state
        
        state = build_macro_state(settings=settings, start_date="2020-01-01", refresh=refresh)
        regime = classify_macro_regime_from_state(
            cpi_yoy=state.inputs.cpi_yoy,
            payrolls_3m_annualized=state.inputs.payrolls_3m_annualized,
            inflation_momentum_minus_be5y=state.inputs.inflation_momentum_minus_be5y,
            real_yield_proxy_10y=state.inputs.real_yield_proxy_10y,
        )
        # MacroRegime uses 'name' not 'label'
        regime_label = getattr(regime, 'label', None) or getattr(regime, 'name', 'Unknown')
        return f"Macro Regime: {regime_label}", {
            "domain": "macro",
            "regime": regime_label,
            "description": getattr(regime, 'description', ''),
            "cpi_yoy": state.inputs.cpi_yoy,
            "snapshot": state.inputs.__dict__ if hasattr(state.inputs, '__dict__') else {},
        }
    
    elif context == "commodities" or context == "commod":
        from ai_options_trader.commodities.signals import build_commodities_state
        from ai_options_trader.commodities.regime import classify_commodities_regime
        
        state = build_commodities_state(settings=settings, start_date="2020-01-01", refresh=refresh)
        regime = classify_commodities_regime(state.inputs)
        return f"Commodities Regime: {regime.label}", {
            "domain": "commodities",
            "regime": regime.label,
            "snapshot": state.inputs.__dict__ if hasattr(state.inputs, '__dict__') else {},
        }
    
    elif context == "rates":
        from ai_options_trader.rates.signals import build_rates_state
        from ai_options_trader.rates.regime import classify_rates_regime
        
        state = build_rates_state(settings=settings, start_date="2020-01-01", refresh=refresh)
        regime = classify_rates_regime(state.inputs)
        return f"Rates Regime: {regime.label}", {
            "domain": "rates",
            "regime": regime.label,
            "ust_10y": state.inputs.ust_10y,
            "snapshot": state.inputs.__dict__ if hasattr(state.inputs, '__dict__') else {},
        }
    
    elif context == "funding":
        from ai_options_trader.funding.signals import build_funding_state
        from ai_options_trader.funding.regime import classify_funding_regime
        
        state = build_funding_state(settings=settings, start_date="2020-01-01", refresh=refresh)
        regime = classify_funding_regime(state.inputs)
        
        # Extract key metrics from inputs
        inputs = state.inputs
        snapshot_data = {
            "effr": getattr(inputs, "effr", None),
            "sofr": getattr(inputs, "sofr", None),
            "iorb": getattr(inputs, "iorb", None),
            "spread_sofr_effr_bps": getattr(inputs, "spread_sofr_effr_bps", None),
            "spread_corridor_bps": getattr(inputs, "spread_corridor_bps", None),
            "spread_corridor_name": getattr(inputs, "spread_corridor_name", None),
            "on_rrp_usd_bn": getattr(inputs, "on_rrp_usd_bn", None),
            "bank_reserves_usd_bn": getattr(inputs, "bank_reserves_usd_bn", None),
            "vol_20d_bps": getattr(inputs, "vol_20d_bps", None),
            "spike_5d_bps": getattr(inputs, "spike_5d_bps", None),
            "persistence_20d": getattr(inputs, "persistence_20d", None),
        }
        
        return f"Funding Regime: {regime.label}", {
            "domain": "funding",
            "regime": regime.label,
            "description": regime.description if hasattr(regime, 'description') else "",
            "snapshot": snapshot_data,
        }
    
    elif context == "monetary":
        from ai_options_trader.monetary.signals import build_monetary_page_data
        from ai_options_trader.monetary.regime import classify_monetary_regime
        from ai_options_trader.monetary.models import MonetaryInputs
        
        data = build_monetary_page_data(settings=settings, lookback_years=5, refresh=refresh)
        
        inputs = MonetaryInputs(
            reserves_level=data.get("reserves_level"),
            reserves_z_level=data.get("reserves_z_level"),
            reserves_z_d_4w=data.get("reserves_z_d_4w"),
            on_rrp_level=data.get("on_rrp_level"),
            on_rrp_z_level=data.get("on_rrp_z_level"),
            on_rrp_z_d_4w=data.get("on_rrp_z_d_4w"),
            fed_bs_level=data.get("fed_bs_level"),
            fed_bs_z_d_12w=data.get("fed_bs_z_d_12w"),
            asof=data.get("asof"),
        )
        regime = classify_monetary_regime(inputs)
        
        return f"Monetary Regime: {regime.label}", {
            "domain": "monetary",
            "regime": regime.label,
            "description": regime.description if hasattr(regime, 'description') else "",
            "snapshot": data,
        }
    
    elif context == "regimes" or context == "all":
        # Load all regimes
        contexts = {}
        for ctx in ["fiscal", "vol", "macro", "commodities", "rates", "funding", "monetary"]:
            try:
                _, data = _get_context_data(ctx, refresh=refresh)
                contexts[ctx] = data
            except Exception as e:
                contexts[ctx] = {"error": str(e)}
        
        return "All Regimes Summary", {"domains": contexts}
    
    elif context == "portfolio" or context == "":
        # Default: load portfolio context
        from ai_options_trader.data.alpaca import make_clients
        
        trading, _ = make_clients(settings)
        acct = trading.get_account()
        positions = trading.get_all_positions()
        
        positions_list = []
        for p in positions:
            positions_list.append({
                "symbol": getattr(p, "symbol", ""),
                "qty": float(getattr(p, "qty", 0)),
                "market_value": float(getattr(p, "market_value", 0)),
                "unrealized_pl": float(getattr(p, "unrealized_pl", 0)),
                "unrealized_plpc": float(getattr(p, "unrealized_plpc", 0)),
            })
        
        return "Portfolio Context", {
            "domain": "portfolio",
            "nav": float(getattr(acct, "equity", 0)),
            "cash": float(getattr(acct, "cash", 0)),
            "positions": positions_list,
        }
    
    else:
        raise ValueError(f"Unknown context: {context}. Use: fiscal, vol, macro, commodities, rates, funding, regimes, portfolio")


def _format_context_display(title: str, data: dict, console: Console) -> None:
    """Format and print context data for display using rich panels."""
    from rich.table import Table
    from rich.panel import Panel
    
    if "domains" in data:
        # Multiple regimes
        table = Table(title="Regime Summary", show_header=True)
        table.add_column("Domain", style="cyan")
        table.add_column("Regime", style="bold")
        for domain, info in data["domains"].items():
            if "error" in info:
                table.add_row(domain, f"[red]Error[/red]")
            else:
                table.add_row(domain, info.get('regime', 'N/A'))
        console.print(table)
        
    elif "positions" in data:
        # Portfolio
        console.print(Panel(
            f"[bold]NAV:[/bold] ${data['nav']:,.0f}\n"
            f"[bold]Cash:[/bold] ${data['cash']:,.0f}\n"
            f"[bold]Positions:[/bold] {len(data['positions'])}",
            title="📊 Portfolio Summary",
            border_style="cyan"
        ))
        if data["positions"]:
            table = Table(title="Positions", show_header=True)
            table.add_column("Symbol", style="cyan")
            table.add_column("Value", justify="right")
            table.add_column("P&L", justify="right")
            for p in data["positions"]:
                pnl_style = "green" if p["unrealized_pl"] >= 0 else "red"
                table.add_row(
                    p['symbol'],
                    f"${p['market_value']:,.0f}",
                    f"[{pnl_style}]${p['unrealized_pl']:+,.0f}[/{pnl_style}]"
                )
            console.print(table)
            
    elif data.get("domain") == "fiscal":
        # Full fiscal snapshot display
        snapshot = data.get("snapshot", {})
        
        # Main deficit info (units are USD millions from FRED)
        deficit_12m = snapshot.get("deficit_12m")  # In millions
        deficit_asof = snapshot.get("asof", "N/A")
        
        # Format deficit (convert from millions)
        def fmt_deficit(val):
            if val is None:
                return "N/A"
            val_dollars = val * 1e6  # Convert millions to dollars
            if abs(val_dollars) >= 1e12:
                return f"${val_dollars/1e12:.2f}T"
            elif abs(val_dollars) >= 1e9:
                return f"${val_dollars/1e9:.1f}B"
            else:
                return f"${val_dollars/1e6:.0f}M"
        
        deficit_disp = fmt_deficit(deficit_12m)
        
        # Previous periods
        deficit_30d = snapshot.get("deficit_12m_30d_ago", {})
        deficit_1y = snapshot.get("deficit_12m_1y_ago", {})
        
        lines = [
            f"[bold]As of:[/bold] {deficit_asof}",
            f"[bold]Rolling 12m deficit:[/bold] {deficit_disp}  (positive = larger deficit)",
        ]
        
        if deficit_30d.get("deficit_12m"):
            lines.append(f"[bold]Rolling 12m deficit ~30d ago:[/bold] {fmt_deficit(deficit_30d['deficit_12m'])}  (as of {deficit_30d.get('asof', 'N/A')})")
        
        if deficit_1y.get("deficit_12m"):
            lines.append(f"[bold]Rolling 12m deficit 1y ago:[/bold] {fmt_deficit(deficit_1y['deficit_12m'])}  (as of {deficit_1y.get('asof', 'N/A')})")
        
        # YoY change
        yoy_chg = snapshot.get("deficit_12m_delta_yoy")
        if yoy_chg is not None:
            lines.append(f"[bold]Δ rolling 12m deficit (YoY):[/bold] {fmt_deficit(yoy_chg)}")
        
        # Deficit % GDP
        deficit_pct = snapshot.get("deficit_pct_gdp")
        if deficit_pct is not None:
            context = "Elevated funding pressure" if deficit_pct > 6 else "Moderate funding pressure" if deficit_pct > 4 else "Normal funding"
            lines.append(f"[bold]Deficit level (% GDP):[/bold] {deficit_pct:.1f}%  ({deficit_pct:.1f} % GDP → {context})")
        
        # Deficit impulse
        impulse = snapshot.get("deficit_impulse_pct_gdp")
        if impulse is not None:
            impulse_ctx = "Improving (less thrust)" if impulse < 0 else "Deteriorating (more thrust)"
            lines.append(f"[bold]Deficit impulse (% GDP):[/bold] {impulse:.2f}%")
            lines.append(f"[bold]Context:[/bold] {impulse:.2f} % GDP → {impulse_ctx}")
        
        # Net issuance (also in millions)
        net = snapshot.get("net_issuance")
        if net and isinstance(net, dict):
            net_asof = net.get("asof", "N/A")
            lines.append(f"[bold]Net issuance (Δ outstanding; MSPD as of {net_asof}):[/bold]")
            if net.get("bills") is not None:
                lines.append(f"  Bills: {fmt_deficit(net['bills'])}")
            if net.get("coupons") is not None:
                lines.append(f"  Coupons: {fmt_deficit(net['coupons'])}")
            if net.get("long") is not None:
                lines.append(f"  Long (>=10y): {fmt_deficit(net['long'])}")
            long_share = net.get("long_duration_share")
            if long_share is not None:
                share_pct = long_share * 100 if long_share <= 1 else long_share
                tilt = "Long-duration-tilted (more duration risk)" if share_pct > 30 else "Bill/coupon-tilted (less duration risk)"
                lines.append(f"  [bold]Long-duration share:[/bold] {share_pct:.1f}%")
                lines.append(f"  [bold]Context:[/bold] {share_pct:.1f}% → {tilt}")
        
        # TGA (value is in millions from FRED)
        tga = snapshot.get("tga")
        if tga and isinstance(tga, dict):
            tga_level = tga.get("tga_level")
            tga_asof = tga.get("tga_asof", "N/A")
            if tga_level is not None:
                # TGA is in millions, convert to billions for display
                lines.append(f"[bold]TGA (as of {tga_asof}):[/bold] ${tga_level/1e3:.0f}B")
        
        # Auctions
        auctions = snapshot.get("auctions")
        if auctions and isinstance(auctions, dict):
            tail = auctions.get("tail_bps")
            dealer = auctions.get("dealer_take_pct")
            auct_asof = auctions.get("asof", "N/A")
            if tail is not None or dealer is not None:
                lines.append(f"[bold]Auction quality (as of {auct_asof}):[/bold]")
                if tail is not None:
                    lines.append(f"  Tail: {tail:.1f} bps")
                if dealer is not None:
                    lines.append(f"  Dealer take: {dealer:.1f}%")
        
        console.print(Panel("\n".join(lines), title=f"📊 US Fiscal Snapshot", border_style="cyan"))
        
        # Regime label
        console.print(Panel(
            f"[bold]Regime:[/bold] {data.get('regime', 'N/A')}\n"
            f"[dim]{data.get('description', '')}[/dim]",
            title="Fiscal Regime",
            border_style="green"
        ))
        
    else:
        # Generic single regime display
        console.print(Panel(
            f"[bold]Regime:[/bold] {data.get('regime', 'N/A')}\n"
            f"[dim]{data.get('description', '')}[/dim]",
            title=f"📊 {title}",
            border_style="cyan"
        ))


def _detect_ticker_query(user_input: str, portfolio_tickers: list[str]) -> Optional[str]:
    """Detect if user is asking about a specific ticker in their portfolio."""
    user_upper = user_input.upper()
    
    # Check for direct ticker mentions
    for ticker in portfolio_tickers:
        if ticker.upper() in user_upper:
            return ticker
    
    # Common patterns
    patterns = [
        r"(?:about|on|for|my)\s+([A-Z]{2,5})\b",
        r"\b([A-Z]{2,5})\s+(?:position|trade|holding)",
        r"(?:what|how).*\b([A-Z]{2,5})\b",
    ]
    
    for pattern in patterns:
        match = re.search(pattern, user_upper)
        if match:
            potential = match.group(1)
            if potential in [t.upper() for t in portfolio_tickers]:
                return potential
    
    return None


def _fetch_ticker_deep_data(settings, ticker: str, console: Console) -> dict:
    """Fetch deep ticker data for enhanced analysis."""
    console.print(f"[cyan]Fetching deep data for {ticker}...[/cyan]")
    
    data = {"ticker": ticker}
    
    try:
        # Ticker quantitative snapshot
        from ai_options_trader.ticker.snapshot import build_ticker_snapshot
        snap = build_ticker_snapshot(settings=settings, ticker=ticker, benchmark="SPY", start="2020-01-01")
        data["snapshot"] = snap
    except Exception as e:
        data["snapshot_error"] = str(e)
    
    try:
        # Recent news via FMP stock news
        from ai_options_trader.llm.outlooks.ticker_news import fetch_fmp_stock_news
        from datetime import datetime, timedelta, timezone
        
        now = datetime.now(timezone.utc).date()
        from_date = (now - timedelta(days=7)).isoformat()
        to_date = now.isoformat()
        
        items = fetch_fmp_stock_news(
            settings=settings,
            tickers=[ticker],
            from_date=from_date,
            to_date=to_date,
            max_pages=2,
        )
        if items:
            data["recent_news"] = [
                {"headline": item.title or "", 
                 "source": item.source or "",
                 "created_at": str(item.published_at or "")}
                for item in items[:5]
            ]
    except Exception as e:
        data["news_error"] = str(e)
    
    try:
        # Company profile if available
        import requests
        if settings.FMP_API_KEY:
            url = f"https://financialmodelingprep.com/api/v3/profile/{ticker}"
            resp = requests.get(url, params={"apikey": settings.FMP_API_KEY}, timeout=10)
            profile_data = resp.json()
            if isinstance(profile_data, list) and profile_data:
                p = profile_data[0]
                data["profile"] = {
                    "name": p.get("companyName"),
                    "sector": p.get("sector"),
                    "industry": p.get("industry"),
                    "market_cap": p.get("mktCap"),
                    "beta": p.get("beta"),
                    "description": p.get("description", "")[:500],
                }
    except Exception as e:
        data["profile_error"] = str(e)
    
    try:
        # Current quote
        import requests
        if settings.FMP_API_KEY:
            url = f"https://financialmodelingprep.com/api/v3/quote/{ticker}"
            resp = requests.get(url, params={"apikey": settings.FMP_API_KEY}, timeout=10)
            quote_data = resp.json()
            if isinstance(quote_data, list) and quote_data:
                q = quote_data[0]
                data["quote"] = {
                    "price": q.get("price"),
                    "change": q.get("change"),
                    "change_pct": q.get("changesPercentage"),
                    "day_high": q.get("dayHigh"),
                    "day_low": q.get("dayLow"),
                    "year_high": q.get("yearHigh"),
                    "year_low": q.get("yearLow"),
                    "volume": q.get("volume"),
                    "avg_volume": q.get("avgVolume"),
                }
    except Exception as e:
        data["quote_error"] = str(e)
    
    return data


def _chat_with_llm(
    settings,
    messages: list[dict],
    context_data: dict,
    model: Optional[str] = None,
    temperature: float = 0.3,
    ticker_data: Optional[dict] = None,
) -> str:
    """Send chat to LLM with context."""
    from openai import OpenAI
    
    client = OpenAI(api_key=settings.openai_api_key)
    chosen_model = model or settings.openai_model or "gpt-4o-mini"
    
    # Build system message with context
    context_json = json.dumps(context_data, indent=2, default=str)
    
    ticker_context = ""
    if ticker_data:
        ticker_json = json.dumps(ticker_data, indent=2, default=str)
        ticker_context = f"""

DEEP TICKER DATA (just fetched for this query):
{ticker_json}

When analyzing this ticker, provide hedge-fund level insights:
- Reference specific quantitative metrics (returns, volatility, drawdown, relative strength)
- Analyze the position in context of current macro regime
- Consider sector/industry dynamics
- Note any relevant news catalysts
- Provide specific price levels and risk/reward analysis
- Be direct about whether to hold, add, reduce, or close the position
"""
    
    system_message = f"""You are a senior macro research analyst at a hedge fund. 
You have access to the following market data and regime context:

{context_json}
{ticker_context}

Guidelines:
- Be concise but thorough
- Reference specific data points from the context
- Consider portfolio implications when relevant
- Mention specific tickers, levels, and actionable insights
- If asked about news/events, synthesize with the regime data
- Use professional hedge fund language
- When discussing positions, be specific about risk/reward and actionable recommendations

Current date: {datetime.now().strftime('%Y-%m-%d %H:%M')}
"""
    
    full_messages = [{"role": "system", "content": system_message}] + messages
    
    resp = client.chat.completions.create(
        model=chosen_model,
        messages=full_messages,
        temperature=temperature,
    )
    
    return (resp.choices[0].message.content or "").strip()


def _parse_contexts(context_input: list[str]) -> list[str]:
    """Parse context input which may contain comma-separated values."""
    contexts = []
    for c in context_input:
        # Split by comma and strip whitespace
        parts = [p.strip().lower() for p in c.split(",") if p.strip()]
        contexts.extend(parts)
    return contexts if contexts else ["portfolio"]


def _load_multiple_contexts(contexts: list[str], refresh: bool, console: Console) -> tuple[str, dict]:
    """Load and merge multiple contexts."""
    if len(contexts) == 1:
        return _get_context_data(contexts[0], refresh=refresh)
    
    # Load multiple contexts
    merged_data = {"domains": {}}
    titles = []
    
    for ctx in contexts:
        try:
            title, data = _get_context_data(ctx, refresh=refresh)
            titles.append(ctx.capitalize())
            
            # Store under domain key
            domain = data.get("domain", ctx)
            merged_data["domains"][domain] = data
            
        except Exception as e:
            console.print(f"[yellow]Warning: Could not load {ctx}: {e}[/yellow]")
            merged_data["domains"][ctx] = {"error": str(e)}
    
    combined_title = " + ".join(titles) + " Context"
    return combined_title, merged_data


def _fetch_ticker_context(settings, ticker: str, console: Console) -> tuple[str, dict]:
    """Fetch comprehensive ticker context for chat."""
    t = ticker.strip().upper()
    console.print(f"\n[cyan]Loading deep context for {t}...[/cyan]")
    
    data = {"ticker": t, "domain": "ticker"}
    
    # Profile
    try:
        from ai_options_trader.altdata.fmp import fetch_profile
        profile = fetch_profile(settings=settings, ticker=t)
        if profile:
            data["profile"] = {
                "name": profile.company_name,
                "sector": profile.sector,
                "industry": profile.industry,
                "market_cap": profile.market_cap,
                "description": (profile.description or "")[:500],
            }
    except Exception as e:
        data["profile_error"] = str(e)
    
    # Quantitative snapshot
    try:
        from ai_options_trader.ticker.snapshot import build_ticker_snapshot
        snap = build_ticker_snapshot(settings=settings, ticker=t, benchmark="SPY", start="2020-01-01")
        data["snapshot"] = str(snap)
    except Exception as e:
        data["snapshot_error"] = str(e)
    
    # Earnings
    try:
        from ai_options_trader.altdata.earnings import fetch_earnings_surprises, fetch_upcoming_earnings, analyze_earnings_history
        surprises = fetch_earnings_surprises(settings=settings, ticker=t, limit=8)
        upcoming = fetch_upcoming_earnings(settings=settings, tickers=[t], days_ahead=90)
        
        if surprises:
            analysis = analyze_earnings_history(surprises)
            data["earnings_analysis"] = analysis
            data["recent_quarters"] = [
                {"date": s.date, "eps_actual": s.eps_actual, "eps_estimated": s.eps_estimated, "surprise_pct": s.eps_surprise_pct}
                for s in surprises[:4]
            ]
        
        if upcoming:
            ev = upcoming[0]
            data["next_earnings"] = {
                "date": ev.date,
                "time": ev.time,
                "eps_estimate": ev.eps_estimated,
                "revenue_estimate": ev.revenue_estimated,
            }
    except Exception as e:
        data["earnings_error"] = str(e)
    
    # Analyst targets
    try:
        import requests
        if settings.fmp_api_key:
            url = "https://financialmodelingprep.com/api/v4/price-target-consensus"
            resp = requests.get(url, params={"apikey": settings.fmp_api_key, "symbol": t}, timeout=10)
            if resp.ok:
                targets = resp.json()
                if targets:
                    data["analyst_targets"] = {
                        "consensus": targets[0].get("targetConsensus"),
                        "low": targets[0].get("targetLow"),
                        "high": targets[0].get("targetHigh"),
                        "num_analysts": targets[0].get("numberOfAnalysts"),
                    }
    except Exception as e:
        data["analyst_error"] = str(e)
    
    # Current quote
    try:
        import requests
        if settings.fmp_api_key:
            url = f"https://financialmodelingprep.com/api/v3/quote/{t}"
            resp = requests.get(url, params={"apikey": settings.fmp_api_key}, timeout=10)
            quote_data = resp.json()
            if isinstance(quote_data, list) and quote_data:
                q = quote_data[0]
                data["quote"] = {
                    "price": q.get("price"),
                    "change": q.get("change"),
                    "change_pct": q.get("changesPercentage"),
                    "day_high": q.get("dayHigh"),
                    "day_low": q.get("dayLow"),
                    "year_high": q.get("yearHigh"),
                    "year_low": q.get("yearLow"),
                    "pe": q.get("pe"),
                    "volume": q.get("volume"),
                    "avg_volume": q.get("avgVolume"),
                }
    except Exception as e:
        data["quote_error"] = str(e)
    
    # Recent news
    try:
        from ai_options_trader.llm.outlooks.ticker_news import fetch_fmp_stock_news
        from ai_options_trader.llm.core.sentiment import analyze_article_sentiment, aggregate_sentiment
        from datetime import datetime, timedelta, timezone
        
        now = datetime.now(timezone.utc).date()
        from_date = (now - timedelta(days=14)).isoformat()
        
        items = fetch_fmp_stock_news(
            settings=settings,
            tickers=[t],
            from_date=from_date,
            to_date=now.isoformat(),
            max_pages=2,
        )
        if items:
            # Sentiment analysis
            article_sentiments = [
                analyze_article_sentiment(
                    headline=item.title or "",
                    content=item.snippet or "",
                )
                for item in items[:10]
            ]
            agg = aggregate_sentiment(article_sentiments)
            
            data["news_sentiment"] = {
                "label": agg.label,
                "score": agg.score,
                "positive": agg.positive_count,
                "negative": agg.negative_count,
                "neutral": agg.neutral_count,
            }
            data["recent_headlines"] = [
                {"headline": item.title, "source": item.source, "date": str(item.published_at)}
                for item in items[:5]
            ]
    except Exception as e:
        data["news_error"] = str(e)
    
    # SEC filings
    try:
        from ai_options_trader.altdata.sec import fetch_8k_filings, summarize_filings
        filings = fetch_8k_filings(settings=settings, ticker=t, limit=5)
        if filings:
            data["recent_filings"] = [
                {"date": f.filed_date, "type": f.form_type, "items": f.items[:2]}
                for f in filings[:3]
            ]
    except Exception as e:
        data["filings_error"] = str(e)
    
    title = f"Ticker Deep Dive: {t}"
    if "profile" in data:
        title = f"{data['profile'].get('name', t)} ({t})"
    
    return title, data


@app.command("start")
def chat_start(
    context: list[str] = typer.Option(
        ["portfolio"],
        "--context", "-c",
        help="Context(s) to load: fiscal, vol, macro, commodities, rates, funding, monetary, regimes, portfolio. Use multiple -c flags or comma-separated."
    ),
    ticker: str = typer.Option("", "--ticker", "-t", help="Ticker to analyze (loads deep research context)"),
    refresh: bool = typer.Option(False, "--refresh", help="Force refresh data"),
    model: str = typer.Option("", "--model", "-m", help="Override LLM model"),
):
    """
    Start an interactive research chat session.
    
    Examples:
        lox chat start                      # Portfolio context
        lox chat start -t AAPL              # Ticker-focused chat
        lox chat start -c fiscal            # Fiscal regime context
        lox chat start -c fiscal -c funding # Multiple contexts
        lox chat start -c fiscal,funding,monetary  # Comma-separated
    """
    console = Console()
    settings = load_settings()
    
    if not settings.openai_api_key:
        console.print("[red]Error:[/red] OPENAI_API_KEY not set in .env")
        raise typer.Exit(1)
    
    # If ticker specified, load ticker context
    ticker_context = None
    if ticker.strip():
        try:
            title, ticker_context = _fetch_ticker_context(settings, ticker, console)
            _format_context_display(title, ticker_context, console)
        except Exception as e:
            console.print(f"[yellow]Warning: Could not load ticker context: {e}[/yellow]")
    
    # Parse and load domain contexts
    parsed_contexts = _parse_contexts(context)
    if not ticker.strip():  # Only show context loading if no ticker (otherwise already shown)
        console.print(f"\n[cyan]Loading context(s): {', '.join(parsed_contexts)}...[/cyan]")
    
    try:
        title, context_data = _load_multiple_contexts(parsed_contexts, refresh, console)
    except Exception as e:
        console.print(f"[red]Error loading context:[/red] {e}")
        raise typer.Exit(1)
    
    # Merge ticker context into main context if present
    if ticker_context:
        context_data["ticker_focus"] = ticker_context
        title = f"{ticker.upper()} + {title}"
    
    # Display context (only if no ticker, since ticker context already shown)
    if not ticker.strip():
        _format_context_display(title, context_data, console)
    
    # Chat loop
    console.print("\n[green]Chat started.[/green] Type your questions (or 'quit' to exit):\n")
    if ticker.strip():
        console.print(f"[dim]Focused on {ticker.upper()}. Ask about outlook, earnings, price targets, risks, etc.[/dim]\n")
    else:
        console.print("[dim]Tip: Ask about specific tickers (e.g., 'tell me about FXI') for deep analysis.[/dim]\n")
    
    messages = []
    chosen_model = model.strip() or None
    
    # Extract portfolio tickers for detection
    portfolio_tickers = []
    if "positions" in context_data:
        for p in context_data["positions"]:
            sym = p.get("symbol", "")
            # Extract underlying from options (first 1-6 chars before numbers)
            underlying = re.sub(r'\d.*', '', sym)[:6].strip()
            if underlying and underlying not in portfolio_tickers:
                portfolio_tickers.append(underlying)
    
    while True:
        try:
            user_input = console.input("[bold cyan]You:[/bold cyan] ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[yellow]Chat ended.[/yellow]")
            break
        
        if not user_input:
            continue
        
        if user_input.lower() in ("quit", "exit", "q"):
            console.print("[yellow]Chat ended.[/yellow]")
            break
        
        # Add user message
        messages.append({"role": "user", "content": user_input})
        
        # Check if asking about a specific ticker
        ticker_data = None
        detected_ticker = _detect_ticker_query(user_input, portfolio_tickers)
        if detected_ticker:
            try:
                ticker_data = _fetch_ticker_deep_data(settings, detected_ticker, console)
            except Exception as e:
                console.print(f"[yellow]Could not fetch deep data for {detected_ticker}: {e}[/yellow]")
        
        # Get LLM response
        try:
            with console.status("[cyan]Thinking...[/cyan]"):
                response = _chat_with_llm(
                    settings=settings,
                    messages=messages,
                    context_data=context_data,
                    model=chosen_model,
                    ticker_data=ticker_data,
                )
            
            # Add assistant response to history
            messages.append({"role": "assistant", "content": response})
            
            # Display response
            console.print(f"\n[bold green]Analyst:[/bold green]")
            console.print(Markdown(response))
            console.print()
            
        except Exception as e:
            console.print(f"[red]Error:[/red] {e}")
            messages.pop()  # Remove failed user message


# Default command (when running `lox chat` without subcommand)
@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    context: list[str] = typer.Option(
        ["portfolio"],
        "--context", "-c",
        help="Context(s) to load: fiscal, vol, macro, commodities, rates, funding, monetary, regimes, portfolio. Use multiple -c flags or comma-separated."
    ),
    ticker: str = typer.Option("", "--ticker", "-t", help="Ticker to analyze (loads deep research context)"),
    refresh: bool = typer.Option(False, "--refresh", help="Force refresh data"),
    model: str = typer.Option("", "--model", "-m", help="Override LLM model"),
):
    """
    Interactive research chat with the LLM analyst.
    
    Load market context and have a conversation about trading implications.
    
    Examples:
        lox chat                           # Portfolio context (default)
        lox chat -t AAPL                   # Ticker-focused chat
        lox chat -t META -c macro          # Ticker + macro context
        lox chat -c fiscal                 # Fiscal regime context
        lox chat -c fiscal -c funding      # Multiple contexts
        lox chat -c fiscal,funding,monetary  # Comma-separated contexts
        lox chat -c regimes                # All regimes summary
    """
    if ctx.invoked_subcommand is None:
        chat_start(context=context, ticker=ticker, refresh=refresh, model=model)
