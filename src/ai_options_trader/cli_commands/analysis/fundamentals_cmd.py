"""
Fundamentals Analysis CLI - CFA-level financial modeling.
"""

from __future__ import annotations

import typer
from rich import print
from rich.panel import Panel
from rich.table import Table
from rich.console import Console


def _run_sensitivity_model(
    ticker: str,
    pe_target: float = 25,
    rev_min: float = -0.1,
    rev_max: float = 0.5,
    margin_min: float = 0.10,
    margin_max: float = 0.40,
    json_out: bool = False,
):
    """Run revenue/margin sensitivity analysis."""
    from ai_options_trader.config import load_settings
    from ai_options_trader.fundamentals.sensitivity import build_sensitivity_model, fetch_financial_data
    
    console = Console()
    settings = load_settings()
    t = ticker.strip().upper()
    
    console.print(f"\n[bold cyan]Building sensitivity model for {t}...[/bold cyan]\n")
    
    try:
        model = build_sensitivity_model(
            settings=settings,
            ticker=t,
            revenue_growth_range=(rev_min, rev_max, 0.1),
            margin_range=(margin_min, margin_max, 0.05),
            target_pe=pe_target,
        )
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        return
    
    inputs = model.base_inputs
    
    if json_out:
        import json
        output = {
            "ticker": t,
            "inputs": {
                "revenue_ttm": inputs.revenue_ttm,
                "net_margin": inputs.net_margin,
                "eps_ttm": inputs.eps_ttm,
                "current_price": inputs.current_price,
                "pe_ratio": inputs.pe_ratio,
            },
            "scenarios": {
                "revenue_growth": model.revenue_growth_scenarios,
                "margins": model.margin_scenarios,
            },
            "eps_matrix": model.eps_matrix,
            "upside_matrix": model.upside_matrix,
            "fair_values": {
                "base_case": model.base_case_fair_value,
                "bull_case": model.bull_case_fair_value,
                "bear_case": model.bear_case_fair_value,
            },
            "insights": model.insights,
        }
        print(json.dumps(output, indent=2))
        return
    
    # Company overview
    overview_lines = [
        f"[bold]{inputs.company_name}[/bold] ({t})",
        "",
        f"[bold]Current Price:[/bold] ${inputs.current_price:.2f}",
        f"[bold]Market Cap:[/bold] ${inputs.market_cap:,.0f}M",
        f"[bold]P/E Ratio:[/bold] {inputs.pe_ratio:.1f}x",
        "",
        f"[bold]Revenue (TTM):[/bold] ${inputs.revenue_ttm:,.0f}M",
        f"[bold]Net Income (TTM):[/bold] ${inputs.net_income_ttm:,.0f}M",
        f"[bold]EPS (TTM):[/bold] ${inputs.eps_ttm:.2f}",
        "",
        f"[bold]Gross Margin:[/bold] {inputs.gross_margin*100:.1f}%",
        f"[bold]Operating Margin:[/bold] {inputs.operating_margin*100:.1f}%",
        f"[bold]Net Margin:[/bold] {inputs.net_margin*100:.1f}%",
        "",
        f"[bold]Revenue Growth (YoY):[/bold] {inputs.revenue_growth_yoy*100:+.1f}%",
        f"[bold]EPS Growth (YoY):[/bold] {inputs.eps_growth_yoy*100:+.1f}%",
    ]
    
    if inputs.revenue_est_next_fy:
        overview_lines.append("")
        overview_lines.append(f"[bold cyan]Consensus Estimates:[/bold cyan]")
        overview_lines.append(f"  Revenue (Next FY): ${inputs.revenue_est_next_fy:,.0f}M ({inputs.revenue_growth_est*100:+.1f}%)")
        if inputs.eps_est_next_fy:
            overview_lines.append(f"  EPS (Next FY): ${inputs.eps_est_next_fy:.2f}")
    
    print(Panel("\n".join(overview_lines), title="Financial Overview", expand=False))
    
    # EPS Sensitivity Table
    print()
    print(f"[bold]EPS Sensitivity Matrix[/bold] (Target P/E: {pe_target}x)")
    print("[dim]Rows = Revenue Growth | Columns = Net Margin[/dim]")
    print()
    
    eps_table = Table(title="Projected EPS by Scenario", expand=False)
    eps_table.add_column("Rev Growth", style="bold")
    
    for m in model.margin_scenarios:
        eps_table.add_column(f"{m*100:.0f}%", justify="right")
    
    for i, rev_g in enumerate(model.revenue_growth_scenarios):
        row = [f"{rev_g*100:+.0f}%"]
        for j, eps in enumerate(model.eps_matrix[i]):
            # Highlight current margin
            margin = model.margin_scenarios[j]
            if abs(margin - inputs.net_margin) < 0.03:
                row.append(f"[bold cyan]${eps:.2f}[/bold cyan]")
            else:
                row.append(f"${eps:.2f}")
        eps_table.add_row(*row)
    
    print(eps_table)
    
    # Fair Value / Upside Table
    print()
    print(f"[bold]Fair Value & Upside/Downside[/bold] (at {pe_target}x P/E)")
    print()
    
    upside_table = Table(title=f"Upside vs Current (${inputs.current_price:.2f})", expand=False)
    upside_table.add_column("Rev Growth", style="bold")
    
    for m in model.margin_scenarios:
        upside_table.add_column(f"{m*100:.0f}%", justify="right")
    
    for i, rev_g in enumerate(model.revenue_growth_scenarios):
        row = [f"{rev_g*100:+.0f}%"]
        for j, upside in enumerate(model.upside_matrix[i]):
            if upside > 20:
                style = "green"
            elif upside > 0:
                style = "yellow"
            elif upside > -20:
                style = "orange1"
            else:
                style = "red"
            row.append(f"[{style}]{upside:+.0f}%[/{style}]")
        upside_table.add_row(*row)
    
    print(upside_table)
    
    # Summary panel
    summary_lines = [
        f"[bold]Valuation Summary[/bold] (at {pe_target}x target P/E)",
        "",
        f"[green]Bull Case:[/green] ${model.bull_case_fair_value:.2f} ({(model.bull_case_fair_value/inputs.current_price-1)*100:+.0f}%)",
        f"[yellow]Base Case:[/yellow] ${model.base_case_fair_value:.2f} ({(model.base_case_fair_value/inputs.current_price-1)*100:+.0f}%)",
        f"[red]Bear Case:[/red] ${model.bear_case_fair_value:.2f} ({(model.bear_case_fair_value/inputs.current_price-1)*100:+.0f}%)",
        "",
        "[bold]Key Insights:[/bold]",
    ]
    
    for insight in model.insights:
        summary_lines.append(f"  • {insight}")
    
    print()
    print(Panel("\n".join(summary_lines), title="Valuation Summary", expand=False))


def _run_dcf_model(
    ticker: str,
    growth_phase1: float = 0.20,
    growth_phase2: float = 0.10,
    terminal_growth: float = 0.025,
    discount_rate: float = 0.10,
    json_out: bool = False,
):
    """Run DCF valuation model."""
    from ai_options_trader.config import load_settings
    from ai_options_trader.fundamentals.valuation import build_dcf_model
    
    console = Console()
    settings = load_settings()
    t = ticker.strip().upper()
    
    console.print(f"\n[bold cyan]Building DCF model for {t}...[/bold cyan]\n")
    
    try:
        model = build_dcf_model(
            settings=settings,
            ticker=t,
            growth_phase1=growth_phase1,
            growth_phase2=growth_phase2,
            terminal_growth=terminal_growth,
            discount_rate=discount_rate,
        )
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        return
    
    if json_out:
        import json
        output = {
            "ticker": t,
            "fcf_base": model.fcf_base,
            "assumptions": {
                "growth_phase1": growth_phase1,
                "growth_phase2": growth_phase2,
                "terminal_growth": terminal_growth,
                "discount_rate": discount_rate,
            },
            "valuation": {
                "pv_phase1": model.pv_phase1,
                "pv_phase2": model.pv_phase2,
                "pv_terminal": model.pv_terminal,
                "enterprise_value": model.enterprise_value,
                "equity_value": model.equity_value,
                "fair_value_per_share": model.fair_value_per_share,
            },
            "upside_vs_current": model.upside_vs_current,
            "fcf_projections": model.fcf_projections,
        }
        print(json.dumps(output, indent=2))
        return
    
    # Assumptions panel
    assumptions = [
        f"[bold]DCF Model Assumptions[/bold]",
        "",
        f"Base FCF: ${model.fcf_base:,.0f}M",
        f"Phase 1 Growth (Yr 1-5): {growth_phase1*100:.0f}%",
        f"Phase 2 Growth (Yr 6-10): {growth_phase2*100:.0f}%",
        f"Terminal Growth: {terminal_growth*100:.1f}%",
        f"Discount Rate (WACC): {discount_rate*100:.0f}%",
    ]
    print(Panel("\n".join(assumptions), title="Assumptions", expand=False))
    
    # FCF projections
    print()
    fcf_table = Table(title="FCF Projections ($M)", expand=False)
    fcf_table.add_column("Year", justify="center")
    for i in range(1, 11):
        fcf_table.add_column(f"Y{i}", justify="right")
    
    fcf_table.add_row("FCF", *[f"${fcf:,.0f}" for fcf in model.fcf_projections])
    print(fcf_table)
    
    # Valuation breakdown
    print()
    val_lines = [
        f"[bold]Valuation Breakdown[/bold]",
        "",
        f"PV of Phase 1 (Yr 1-5):  ${model.pv_phase1:>12,.0f}M",
        f"PV of Phase 2 (Yr 6-10): ${model.pv_phase2:>12,.0f}M",
        f"PV of Terminal Value:    ${model.pv_terminal:>12,.0f}M",
        f"{'─' * 40}",
        f"[bold]Enterprise Value:        ${model.enterprise_value:>12,.0f}M[/bold]",
        f"",
        f"[bold]Equity Value:            ${model.equity_value:>12,.0f}M[/bold]",
        f"[bold]Fair Value per Share:    ${model.fair_value_per_share:>12.2f}[/bold]",
    ]
    
    if model.upside_vs_current > 0:
        val_lines.append(f"[green]Upside vs Current:       {model.upside_vs_current:>+12.1f}%[/green]")
    else:
        val_lines.append(f"[red]Downside vs Current:     {model.upside_vs_current:>+12.1f}%[/red]")
    
    val_lines.append(f"Implied 5-Year Return:   {model.implied_return:>+12.1f}% CAGR")
    
    print(Panel("\n".join(val_lines), title="DCF Valuation", expand=False))


def _run_reverse_dcf(
    ticker: str,
    terminal_growth: float = 0.025,
    discount_rate: float = 0.10,
    json_out: bool = False,
):
    """Run reverse DCF to find implied growth."""
    from ai_options_trader.config import load_settings
    from ai_options_trader.fundamentals.valuation import reverse_dcf
    
    console = Console()
    settings = load_settings()
    t = ticker.strip().upper()
    
    console.print(f"\n[bold cyan]Running reverse DCF for {t}...[/bold cyan]\n")
    
    try:
        result = reverse_dcf(
            settings=settings,
            ticker=t,
            terminal_growth=terminal_growth,
            discount_rate=discount_rate,
        )
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        return
    
    if json_out:
        import json
        output = {
            "ticker": t,
            "current_price": result.current_price,
            "implied_growth_rate": result.implied_growth_rate,
            "growth_assessment": result.growth_assessment,
            "comparison_vs_historical": result.comparison_vs_historical,
            "comparison_vs_consensus": result.comparison_vs_consensus,
        }
        print(json.dumps(output, indent=2))
        return
    
    # Color based on assessment
    if result.growth_assessment == "aggressive":
        color = "red"
    elif result.growth_assessment == "reasonable":
        color = "green"
    else:
        color = "yellow"
    
    lines = [
        f"[bold]What Growth is Priced In?[/bold]",
        "",
        f"Current Price: ${result.current_price:.2f}",
        f"Discount Rate: {result.discount_rate*100:.0f}%",
        f"Terminal Growth: {result.terminal_growth*100:.1f}%",
        "",
        f"[bold {color}]Implied Growth Rate: {result.implied_growth_rate*100:.1f}%[/bold {color}]",
        f"Assessment: [{color}]{result.growth_assessment.upper()}[/{color}]",
        "",
    ]
    
    if result.comparison_vs_historical:
        diff = result.comparison_vs_historical * 100
        comp_color = "red" if diff > 5 else "green" if diff < -5 else "yellow"
        lines.append(f"vs Historical Growth: [{comp_color}]{diff:+.1f}%[/{comp_color}]")
    
    if result.comparison_vs_consensus is not None:
        diff = result.comparison_vs_consensus * 100
        comp_color = "red" if diff > 5 else "green" if diff < -5 else "yellow"
        lines.append(f"vs Consensus Estimates: [{comp_color}]{diff:+.1f}%[/{comp_color}]")
    
    lines.extend([
        "",
        "[dim]Interpretation:[/dim]",
        f"  • Price implies {result.implied_growth_rate*100:.1f}% annual FCF growth for 10 years",
    ])
    
    if result.growth_assessment == "aggressive":
        lines.append("  • [red]Market expects exceptional growth - high expectations risk[/red]")
    elif result.growth_assessment == "reasonable":
        lines.append("  • [green]Market expectations appear achievable[/green]")
    else:
        lines.append("  • [yellow]Conservative valuation - potential upside if growth exceeds[/yellow]")
    
    print(Panel("\n".join(lines), title="Reverse DCF Analysis", expand=False))


def _run_research_deep_dive(
    ticker: str,
    llm: bool = False,
):
    """Run deep research aggregation for a ticker."""
    from ai_options_trader.config import load_settings
    from ai_options_trader.altdata.sec import fetch_8k_filings, fetch_annual_quarterly_reports
    from ai_options_trader.llm.outlooks.ticker_news import fetch_fmp_stock_news
    from datetime import datetime, timedelta
    
    console = Console()
    settings = load_settings()
    t = ticker.strip().upper()
    
    console.print(f"\n[bold cyan]Deep Research Dive: {t}[/bold cyan]\n")
    
    # Fetch SEC filings
    console.print("[dim]Fetching SEC filings...[/dim]")
    filings_8k = fetch_8k_filings(settings=settings, ticker=t, limit=10)
    filings_periodic = fetch_annual_quarterly_reports(settings=settings, ticker=t, limit=4)
    
    if filings_8k or filings_periodic:
        filing_lines = ["[bold]Recent SEC Filings[/bold]", ""]
        
        all_filings = sorted(filings_8k + filings_periodic, key=lambda x: x.filed_date, reverse=True)
        for f in all_filings[:10]:
            items_str = f" ({', '.join(f.items[:2])})" if f.items else ""
            filing_lines.append(f"  • {f.filed_date}: [bold]{f.form_type}[/bold]{items_str}")
            link = getattr(f, 'filing_url', None) or getattr(f, 'link', None)
            if link:
                filing_lines.append(f"    [dim]{link}[/dim]")
        
        print(Panel("\n".join(filing_lines), title="SEC Filings", expand=False))
    
    # Fetch news
    console.print("[dim]Fetching recent news...[/dim]")
    from_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    to_date = datetime.now().strftime("%Y-%m-%d")
    
    try:
        news = fetch_fmp_stock_news(
            settings=settings,
            tickers=[t],
            from_date=from_date,
            to_date=to_date,
            max_pages=3,
        )
        
        if news:
            news_lines = ["[bold]Recent News (30 days)[/bold]", ""]
            
            # Categorize news
            partnerships = []
            earnings = []
            products = []
            other = []
            
            for n in news[:20]:
                # Handle both dict and object formats
                if isinstance(n, dict):
                    title = n.get("title", "").lower()
                    item = {
                        "date": n.get("publishedDate", "")[:10],
                        "title": n.get("title", ""),
                        "url": n.get("url", ""),
                    }
                else:
                    title = getattr(n, "title", "").lower()
                    pub_date = getattr(n, "publishedDate", "") or getattr(n, "published_date", "") or ""
                    item = {
                        "date": pub_date[:10] if pub_date else "",
                        "title": getattr(n, "title", ""),
                        "url": getattr(n, "url", ""),
                    }
                
                if any(w in title for w in ["partner", "deal", "agreement", "collaborat", "alliance"]):
                    partnerships.append(item)
                elif any(w in title for w in ["earning", "revenue", "profit", "quarter", "fiscal"]):
                    earnings.append(item)
                elif any(w in title for w in ["product", "launch", "chip", "gpu", "ai ", "data center"]):
                    products.append(item)
                else:
                    other.append(item)
            
            if partnerships:
                news_lines.append("[bold cyan]Partnerships & Deals:[/bold cyan]")
                for n in partnerships[:5]:
                    news_lines.append(f"  • {n['date']}: {n['title'][:80]}")
                news_lines.append("")
            
            if earnings:
                news_lines.append("[bold cyan]Earnings & Financials:[/bold cyan]")
                for n in earnings[:5]:
                    news_lines.append(f"  • {n['date']}: {n['title'][:80]}")
                news_lines.append("")
            
            if products:
                news_lines.append("[bold cyan]Products & Technology:[/bold cyan]")
                for n in products[:5]:
                    news_lines.append(f"  • {n['date']}: {n['title'][:80]}")
                news_lines.append("")
            
            if other:
                news_lines.append("[bold cyan]Other News:[/bold cyan]")
                for n in other[:5]:
                    news_lines.append(f"  • {n['date']}: {n['title'][:80]}")
            
            print(Panel("\n".join(news_lines), title="News Analysis", expand=False))
    except Exception as e:
        console.print(f"[yellow]Could not fetch news: {e}[/yellow]")
    
    # Fetch CapEx and R&D data
    console.print("[dim]Fetching CapEx and R&D data...[/dim]")
    
    try:
        import requests
        base_url = "https://financialmodelingprep.com/api/v3"
        
        resp = requests.get(
            f"{base_url}/cash-flow-statement/{t}",
            params={"apikey": settings.fmp_api_key, "period": "annual", "limit": 5},
            timeout=15,
        )
        
        if resp.ok:
            data = resp.json()
            if data:
                capex_lines = ["[bold]CapEx & Investment Trends[/bold]", ""]
                
                capex_table = Table(expand=False)
                capex_table.add_column("Year", justify="center")
                capex_table.add_column("CapEx", justify="right")
                capex_table.add_column("R&D", justify="right")
                capex_table.add_column("FCF", justify="right")
                capex_table.add_column("CapEx % Rev", justify="right")
                
                for cf in data[:5]:
                    year = cf.get("date", "")[:4]
                    capex = cf.get("capitalExpenditure", 0) / 1e9
                    fcf = cf.get("freeCashFlow", 0) / 1e9
                    
                    # Try to get R&D from income statement
                    rd = 0
                    
                    # CapEx as % of revenue (estimate)
                    capex_pct = "—"
                    
                    capex_table.add_row(
                        year,
                        f"${abs(capex):.1f}B",
                        f"${rd:.1f}B" if rd else "—",
                        f"${fcf:.1f}B",
                        capex_pct,
                    )
                
                print()
                print(capex_table)
                
                # Calculate trends
                if len(data) >= 2:
                    latest_capex = abs(data[0].get("capitalExpenditure", 0))
                    prev_capex = abs(data[1].get("capitalExpenditure", 0))
                    if prev_capex > 0:
                        capex_growth = (latest_capex / prev_capex - 1) * 100
                        trend_color = "green" if capex_growth > 10 else "yellow" if capex_growth > 0 else "red"
                        print(f"\n[{trend_color}]CapEx YoY Change: {capex_growth:+.1f}%[/{trend_color}]")
    except Exception as e:
        console.print(f"[yellow]Could not fetch CapEx data: {e}[/yellow]")
    
    # LLM Analysis if requested
    if llm:
        console.print("\n[bold cyan]Generating LLM Research Summary...[/bold cyan]\n")
        
        try:
            from ai_options_trader.llm.core.analyst import llm_analyze_regime
            
            # Build context for LLM
            context = {
                "ticker": t,
                "analysis_type": "deep_research",
                "focus_areas": ["partnerships", "capex_trends", "competitive_position", "ai_exposure"],
            }
            
            analysis = llm_analyze_regime(
                settings=settings,
                domain="ticker_research",
                snapshot=context,
                regime_label="Deep Research",
                regime_description=f"CFA-level deep research analysis for {t}. Focus on: CapEx trends, partnership landscape, competitive moat, AI/chip industry positioning, and key risks.",
            )
            
            from rich.markdown import Markdown
            print(Panel(Markdown(analysis), title="LLM Research Analysis", expand=False))
        except Exception as e:
            console.print(f"[yellow]LLM analysis unavailable: {e}[/yellow]")


def _show_partner_health(json_out: bool = False):
    """Show NVDA partner ecosystem health report."""
    from ai_options_trader.config import load_settings
    from ai_options_trader.fundamentals.partnerships import (
        build_partner_health_report,
        get_partner_capex_trend,
        NVDA_PARTNERS,
        PRIVATE_AI_PLAYERS,
    )
    
    console = Console()
    settings = load_settings()
    
    console.print("\n[bold cyan]NVDA Partner Ecosystem Health Report[/bold cyan]")
    console.print("[dim]Testing the bear thesis: Are NVDA's customers making money on AI?[/dim]\n")
    
    console.print("[dim]Fetching partner financials...[/dim]")
    report = build_partner_health_report(settings)
    
    if json_out:
        import json
        output = {
            "as_of": report.as_of,
            "partners": [
                {
                    "ticker": p.ticker,
                    "name": p.name,
                    "revenue_ttm_b": p.revenue_ttm,
                    "capex_ttm_b": p.capex_ttm,
                    "ai_capex_est_b": p.ai_capex_est,
                    "operating_margin": p.operating_margin,
                    "capex_growth_yoy": p.capex_growth_yoy,
                }
                for p in report.partners
            ],
            "aggregates": {
                "total_partner_capex_b": report.total_partner_capex,
                "avg_capex_growth": report.avg_partner_capex_growth,
                "private_ai_burn_b": report.private_ai_burn_rate_est,
            },
            "risks": {
                "concentration": report.customer_concentration_risk,
                "capex_sustainability": report.capex_sustainability_risk,
                "ai_roi": report.ai_roi_risk,
            },
            "bear_evidence": report.bear_thesis_evidence,
            "bull_evidence": report.bull_thesis_evidence,
        }
        print(json.dumps(output, indent=2))
        return
    
    # Partner financials table
    partner_table = Table(title="NVDA Partner Financials", expand=False)
    partner_table.add_column("Ticker", style="bold")
    partner_table.add_column("Name", style="cyan")
    partner_table.add_column("Rev ($B)", justify="right")
    partner_table.add_column("CapEx ($B)", justify="right")
    partner_table.add_column("AI CapEx Est", justify="right")
    partner_table.add_column("Op Margin", justify="right")
    partner_table.add_column("CapEx Δ YoY", justify="right")
    partner_table.add_column("CapEx/Rev", justify="right")
    
    for p in sorted(report.partners, key=lambda x: x.ai_capex_est or 0, reverse=True):
        # Color coding for margins
        if p.operating_margin > 0.25:
            margin_style = "green"
        elif p.operating_margin > 0.15:
            margin_style = "yellow"
        else:
            margin_style = "red"
        
        # Color for CapEx growth
        if p.capex_growth_yoy > 0.3:
            capex_style = "red"  # Concerning if not profitable
        elif p.capex_growth_yoy > 0.1:
            capex_style = "yellow"
        else:
            capex_style = "green"
        
        # CapEx intensity warning
        if p.capex_to_revenue > 0.15:
            intensity_style = "red"
        elif p.capex_to_revenue > 0.10:
            intensity_style = "yellow"
        else:
            intensity_style = "white"
        
        partner_table.add_row(
            p.ticker,
            p.name[:15],
            f"${p.revenue_ttm:.1f}",
            f"${p.capex_ttm:.1f}",
            f"[{capex_style}]${p.ai_capex_est:.1f}[/{capex_style}]" if p.ai_capex_est else "—",
            f"[{margin_style}]{p.operating_margin*100:.1f}%[/{margin_style}]",
            f"[{capex_style}]{p.capex_growth_yoy*100:+.0f}%[/{capex_style}]",
            f"[{intensity_style}]{p.capex_to_revenue*100:.1f}%[/{intensity_style}]",
        )
    
    print(partner_table)
    
    # Private AI companies panel
    private_lines = ["[bold]Private AI Companies (NVDA Customers)[/bold]", ""]
    for name, info in PRIVATE_AI_PLAYERS.items():
        profit_status = "[red]Unprofitable[/red]" if not info["profitable"] else "[green]Profitable[/green]"
        private_lines.append(f"[bold]{name}[/bold]")
        private_lines.append(f"  Funding: {info['funding']} | Valuation: {info['valuation']}")
        private_lines.append(f"  Revenue Est: {info['revenue_est']} | {profit_status}")
        private_lines.append(f"  [dim]{info['notes']}[/dim]")
        private_lines.append("")
    
    print()
    print(Panel("\n".join(private_lines), title="Private AI Labs", expand=False))
    
    # Risk assessment panel
    risk_lines = [
        "[bold]Risk Assessment[/bold]",
        "",
        f"[bold]Customer Concentration:[/bold] {report.customer_concentration_risk}",
        f"[bold]CapEx Sustainability:[/bold] {report.capex_sustainability_risk}",
        f"[bold]AI ROI Risk:[/bold] {report.ai_roi_risk}",
    ]
    
    print()
    print(Panel("\n".join(risk_lines), title="Risk Assessment", expand=False))
    
    # Aggregate metrics
    agg_lines = [
        "[bold]Aggregate Metrics[/bold]",
        "",
        f"Total Partner CapEx: ${report.total_partner_capex:.1f}B",
        f"Estimated AI CapEx: ${sum(p.ai_capex_est or 0 for p in report.partners):.1f}B",
        f"Avg CapEx Growth: {report.avg_partner_capex_growth*100:+.1f}%",
        f"Avg Operating Margin: {report.avg_partner_margin*100:.1f}%",
        "",
        f"[red]Private AI Burn Rate Est: ${report.private_ai_burn_rate_est:.0f}B/year[/red]",
    ]
    
    print()
    print(Panel("\n".join(agg_lines), title="Aggregate Metrics", expand=False))
    
    # Bear thesis evidence
    if report.bear_thesis_evidence:
        bear_lines = ["[bold red]🐻 BEAR THESIS EVIDENCE[/bold red]", ""]
        for e in report.bear_thesis_evidence:
            bear_lines.append(f"  • {e}")
        print()
        print(Panel("\n".join(bear_lines), title="Bear Case", border_style="red", expand=False))
    
    # Bull thesis evidence
    if report.bull_thesis_evidence:
        bull_lines = ["[bold green]🐂 BULL THESIS EVIDENCE[/bold green]", ""]
        for e in report.bull_thesis_evidence:
            bull_lines.append(f"  • {e}")
        print()
        print(Panel("\n".join(bull_lines), title="Bull Case", border_style="green", expand=False))
    
    # Key insights
    if report.insights:
        insight_lines = ["[bold]Key Insights[/bold]", ""]
        for i in report.insights:
            insight_lines.append(f"  • {i}")
        print()
        print(Panel("\n".join(insight_lines), title="Summary", expand=False))


def _show_coreweave_analysis():
    """Show CoreWeave and NVDA circular dependency analysis."""
    from ai_options_trader.config import load_settings
    import requests
    
    console = Console()
    settings = load_settings()
    
    console.print("\n[bold cyan]CoreWeave (CRWV) - NVIDIA Circular Dependency Analysis[/bold cyan]")
    console.print("[dim]Following the money in the GPU cloud ecosystem[/dim]\n")
    
    base_url = "https://financialmodelingprep.com/api/v3"
    
    # Fetch CRWV data
    crwv_price = 0
    crwv_mkt_cap = 0
    
    try:
        resp = requests.get(
            f"{base_url}/profile/CRWV",
            params={"apikey": settings.fmp_api_key},
            timeout=15,
        )
        if resp.ok and resp.json():
            p = resp.json()[0]
            crwv_price = p.get("price", 0)
            crwv_mkt_cap = p.get("mktCap", 0) / 1e9
    except Exception:
        pass
    
    # Fetch NVDA data
    nvda_price = 0
    try:
        resp = requests.get(
            f"{base_url}/profile/NVDA",
            params={"apikey": settings.fmp_api_key},
            timeout=15,
        )
        if resp.ok and resp.json():
            nvda_price = resp.json()[0].get("price", 0)
    except Exception:
        pass
    
    # Current prices
    price_lines = [
        "[bold]Current Prices[/bold]",
        "",
        f"CRWV: ${crwv_price:.2f} (Mkt Cap: ${crwv_mkt_cap:.1f}B)",
        f"NVDA: ${nvda_price:.2f}",
        "",
        f"IPO Price: $40.00 | IPO Return: {(crwv_price/40 - 1)*100:+.1f}%",
    ]
    print(Panel("\n".join(price_lines), title="CRWV Current State", expand=False))
    
    # The circular dependency diagram
    circular_diagram = """
[bold red]THE CIRCULAR REVENUE LOOP[/bold red]

    ┌─────────────────────────────────────────────────────────┐
    │                                                         │
    │   [cyan]NVIDIA[/cyan]                                            │
    │     │                                                   │
    │     │ 1. Invests ~$500M in CoreWeave                    │
    │     ▼                                                   │
    │   [yellow]COREWEAVE[/yellow]                                          │
    │     │                                                   │
    │     │ 2. Uses investment to buy $8.7B in NVDA GPUs      │
    │     ▼                                                   │
    │   [cyan]NVIDIA[/cyan] books GPU sale as revenue ←───────────────┘
    │                                                         │
    └─────────────────────────────────────────────────────────┘

[bold]Net Effect:[/bold] NVIDIA's investment is partially paying itself
"""
    print()
    print(Panel(circular_diagram, title="Circular Dependency", expand=False))
    
    # CoreWeave financials
    fin_lines = [
        "[bold]CoreWeave Financials (2024)[/bold]",
        "",
        f"Revenue: $1.92B",
        f"Net Income: [red]-$0.86B[/red]",
        f"Gross Margin: 74%",
        f"[red]CapEx: $8.7B[/red] (mostly NVDA GPUs)",
        "",
        "[bold]Key Metrics:[/bold]",
        f"  Revenue/CapEx Ratio: 0.22x (buying $4.50 in GPUs for every $1 revenue)",
        f"  Profitable: [red]No[/red]",
        f"  Cash Burn: Massive (depreciation + losses)",
    ]
    print()
    print(Panel("\n".join(fin_lines), title="CRWV Financials", expand=False))
    
    # Customer concentration
    customer_lines = [
        "[bold]CoreWeave Customer Concentration[/bold]",
        "",
        "[red]Microsoft: ~60% of revenue[/red]",
        "  └─ Azure overflow capacity",
        "  └─ If MSFT/OpenAI scales back → CRWV demand drops",
        "",
        "OpenAI: ~15% of revenue",
        "  └─ Training infrastructure (via Microsoft)",
        "",
        "Meta: ~10% of revenue", 
        "  └─ AI training workloads",
        "",
        "[yellow]⚠️ WARNING: 75%+ revenue from 2 customers[/yellow]",
    ]
    print()
    print(Panel("\n".join(customer_lines), title="Customer Risk", expand=False))
    
    # NVDA investment timeline
    timeline_lines = [
        "[bold]NVIDIA Investment Timeline in CoreWeave[/bold]",
        "",
        "[bold]Aug 2023[/bold] - Series B ($2.3B round)",
        "  └─ NVDA participated alongside Magnetar Capital",
        "  └─ Valued CoreWeave at ~$8B",
        "",
        "[bold]May 2024[/bold] - Debt Financing ($7.5B)",
        "  └─ BlackRock, Magnetar led",
        "  └─ NVDA reportedly involved",
        "",
        "[bold]Mar 2025[/bold] - IPO",
        "  └─ Priced at $40, valued at ~$23B",
        "  └─ NVDA retained ~5-10% stake (~$500M-1B)",
        "",
        f"[bold]Today[/bold] - NVDA stake worth ~${crwv_mkt_cap * 0.07:.1f}B (if 7%)",
    ]
    print()
    print(Panel("\n".join(timeline_lines), title="NVDA Investment History", expand=False))
    
    # Bear thesis implications
    bear_lines = [
        "[bold red]Bear Thesis: Why CoreWeave is NVDA's Achilles Heel[/bold red]",
        "",
        "[bold]1. Circular Revenue[/bold]",
        "   NVDA invests → CRWV buys GPUs → NVDA books revenue",
        "   This inflates NVDA's 'organic' demand narrative",
        "",
        "[bold]2. Customer Concentration Risk[/bold]",
        "   CRWV's business depends on Microsoft overflow",
        "   If Azure builds enough capacity, CRWV demand drops",
        "",
        "[bold]3. Profitability Impossible?[/bold]",
        "   GPU depreciation faster than revenue can grow",
        "   Classic CapEx-heavy business with margin squeeze",
        "",
        "[bold]4. Leading Indicator[/bold]",
        "   CRWV stock may signal AI demand before NVDA reacts",
        "   Watch for: CRWV weakness → NVDA weakness (beta: 1.14)",
        "",
        "[bold]5. If CoreWeave Fails:[/bold]",
        "   - NVDA loses ~$500M investment",
        "   - NVDA loses ~$5-10B/year customer",
        "   - AI demand narrative takes major hit",
    ]
    print()
    print(Panel("\n".join(bear_lines), title="Bear Thesis Implications", expand=False))
    
    # What to watch
    watch_lines = [
        "[bold]What to Monitor[/bold]",
        "",
        "📉 [bold]CRWV Stock[/bold] - Leading indicator for AI demand",
        "   Current: ${:.2f} | IPO: $40 | Watch for breakdown below $70".format(crwv_price),
        "",
        "📊 [bold]CRWV Earnings[/bold] - Customer concentration changes",
        "   If Microsoft % drops → they're building own capacity",
        "",
        "💰 [bold]CRWV CapEx[/bold] - GPU purchase slowdown",
        "   Q/Q decline = weakening demand",
        "",
        "📈 [bold]NVDA-CRWV Correlation[/bold] - Currently 0.39",
        "   If correlation increases, CRWV becomes better NVDA proxy",
    ]
    print()
    print(Panel("\n".join(watch_lines), title="Monitoring Points", expand=False))


def _show_openai_exposure(json_out: bool = False):
    """Show OpenAI exposure analysis."""
    from ai_options_trader.config import load_settings
    from ai_options_trader.fundamentals.openai_exposure import (
        build_openai_exposure_report,
        get_openai_thesis_summary,
        OPENAI_FINANCIALS,
    )
    
    console = Console()
    settings = load_settings()
    
    console.print("\n[bold cyan]OpenAI Exposure Tracker[/bold cyan]")
    console.print("[dim]Who's tied to OpenAI's success or failure?[/dim]\n")
    
    console.print("[dim]Building exposure report...[/dim]")
    report = build_openai_exposure_report(settings)
    
    if json_out:
        import json
        output = {
            "as_of": report.as_of,
            "openai_health": {
                "valuation_m": report.openai_health.valuation,
                "revenue_m": report.openai_health.annual_revenue,
                "burn_m": report.openai_health.annual_burn,
                "health_score": report.openai_health.health_score,
            },
            "exposures": [
                {
                    "ticker": e.ticker,
                    "name": e.name,
                    "relationship": e.relationship,
                    "investment_m": e.investment_amount,
                    "exposure_risk": e.exposure_risk_score,
                }
                for e in report.exposed_companies
            ],
            "insights": report.insights,
        }
        print(json.dumps(output, indent=2))
        return
    
    # OpenAI Health Panel
    health = report.openai_health
    
    # Health score gauge
    score = health.health_score
    if score >= 60:
        health_color = "green"
        health_label = "RELATIVELY HEALTHY"
    elif score >= 40:
        health_color = "yellow"
        health_label = "MODERATE CONCERN"
    else:
        health_color = "red"
        health_label = "HIGH RISK"
    
    filled = int(score / 5)
    gauge = "█" * filled + "░" * (20 - filled)
    
    openai_lines = [
        "[bold]OpenAI Financial Health (Estimated)[/bold]",
        "",
        f"Valuation: ${health.valuation/1000:.0f}B",
        f"Annual Revenue: ${health.annual_revenue/1000:.1f}B",
        f"Revenue Growth: {health.revenue_growth*100:.0f}%",
        f"[red]Annual Burn: ${health.annual_burn/1000:.1f}B[/red]",
        f"[yellow]Cash Runway: ~{health.cash_runway_months} months[/yellow]",
        f"Profitable: [red]{'Yes' if health.profitable else 'No'}[/red]",
        "",
        f"[{health_color}]Health Score: {score}/100 - {health_label}[/{health_color}]",
        f"[{health_color}]{gauge}[/{health_color}]",
        "",
        "[bold]Key Risks:[/bold]",
    ]
    
    for risk in health.key_risks[:4]:
        openai_lines.append(f"  • {risk}")
    
    print(Panel("\n".join(openai_lines), title="OpenAI Health", expand=False))
    
    # Exposed Companies Table
    print()
    exp_table = Table(title="Companies with OpenAI Exposure", expand=False)
    exp_table.add_column("Ticker", style="bold")
    exp_table.add_column("Name")
    exp_table.add_column("Relationship", style="cyan")
    exp_table.add_column("Investment", justify="right")
    exp_table.add_column("Rev Exposure")
    exp_table.add_column("Risk Score", justify="right")
    exp_table.add_column("If OpenAI Fails")
    
    for e in report.exposed_companies:
        # Color code risk score
        if e.exposure_risk_score >= 60:
            risk_style = "red"
        elif e.exposure_risk_score >= 40:
            risk_style = "yellow"
        else:
            risk_style = "green"
        
        # Revenue exposure color
        rev_exp_colors = {
            "very_high": "red",
            "high": "orange1",
            "medium": "yellow",
            "low": "green",
        }
        rev_color = rev_exp_colors.get(e.revenue_exposure, "white")
        
        downside_short = e.downside_if_failure[:40] + "..." if len(e.downside_if_failure) > 40 else e.downside_if_failure
        
        exp_table.add_row(
            e.ticker,
            e.name[:12],
            e.relationship.replace("_", " ").title()[:15],
            f"${e.investment_amount/1000:.0f}B" if e.investment_amount > 0 else "—",
            f"[{rev_color}]{e.revenue_exposure.upper()}[/{rev_color}]",
            f"[{risk_style}]{e.exposure_risk_score}[/{risk_style}]",
            downside_short,
        )
    
    print(exp_table)
    
    # Exposure Details Panel
    for e in report.exposed_companies[:3]:  # Top 3 most exposed
        detail_lines = [
            f"[bold]{e.name} ({e.ticker})[/bold]",
            "",
            f"[dim]{e.exposure_description}[/dim]",
            "",
            f"[bold]Market Cap:[/bold] ${e.market_cap:.0f}B",
            f"[bold]Revenue:[/bold] ${e.revenue_ttm:.0f}B",
            f"[bold]Operating Margin:[/bold] {e.operating_margin*100:.1f}%",
        ]
        
        if e.investment_amount > 0:
            detail_lines.append(f"[bold]Investment:[/bold] ${e.investment_amount/1000:.0f}B ({e.investment_pct_of_mcap:.2f}% of mkt cap)")
        
        if e.openai_revenue_pct_est > 0:
            detail_lines.append(f"[bold]OpenAI Revenue Est:[/bold] ~{e.openai_revenue_pct_est:.1f}% of revenue")
        
        detail_lines.extend([
            "",
            f"[green]If OpenAI Succeeds:[/green] {e.upside_if_success}",
            f"[red]If OpenAI Fails:[/red] {e.downside_if_failure}",
        ])
        
        print()
        print(Panel("\n".join(detail_lines), title=f"{e.ticker} Exposure Detail", expand=False))
    
    # Disruption Targets
    if report.disruption_risks:
        disrupt_lines = ["[bold]Companies at Disruption Risk from OpenAI[/bold]", ""]
        for d in report.disruption_risks:
            risk_color = "red" if d["risk_level"] == "high" else "yellow" if d["risk_level"] == "medium" else "green"
            disrupt_lines.append(f"[bold]{d['ticker']}[/bold] ({d['name']}): [{risk_color}]{d['risk_level'].upper()}[/{risk_color}]")
            disrupt_lines.append(f"  {d['description']}")
            disrupt_lines.append("")
        
        print()
        print(Panel("\n".join(disrupt_lines), title="Disruption Targets", expand=False))
    
    # Thesis Summary
    thesis = get_openai_thesis_summary()
    thesis_lines = [
        f"[bold]Bear Thesis:[/bold] {thesis['thesis']}",
        "",
        "[bold]Key Questions:[/bold]",
    ]
    for q in thesis["key_questions"]:
        thesis_lines.append(f"  • {q}")
    
    thesis_lines.extend(["", "[bold red]Bear Triggers to Watch:[/bold red]"])
    for t in thesis["bear_triggers"][:4]:
        thesis_lines.append(f"  • {t}")
    
    thesis_lines.extend(["", "[bold cyan]Monitoring Points:[/bold cyan]"])
    for m in thesis["monitoring"][:4]:
        thesis_lines.append(f"  • {m}")
    
    print()
    print(Panel("\n".join(thesis_lines), title="Investment Thesis", expand=False))
    
    # Key insights
    if report.insights:
        insight_lines = ["[bold]Key Insights[/bold]", ""]
        for i in report.insights:
            insight_lines.append(f"  • {i}")
        print()
        print(Panel("\n".join(insight_lines), title="Summary", expand=False))
    
    # Thesis implications
    if report.thesis_implications:
        impl_lines = ["[bold]Scenario Analysis[/bold]", ""]
        for i in report.thesis_implications:
            impl_lines.append(i)
        print()
        print(Panel("\n".join(impl_lines), title="If OpenAI Succeeds/Fails", expand=False))


def _show_demand_peak_signals():
    """Show signals that AI/GPU demand may be peaking."""
    from ai_options_trader.config import load_settings
    from ai_options_trader.fundamentals.partnerships import analyze_demand_peak_signals
    
    console = Console()
    settings = load_settings()
    
    console.print("\n[bold cyan]AI/GPU Demand Peak Signal Monitor[/bold cyan]")
    console.print("[dim]Your thesis: LLM scaling limits will reduce demand[/dim]\n")
    
    console.print("[dim]Analyzing demand signals...[/dim]")
    signals = analyze_demand_peak_signals(settings)
    
    # Peak risk gauge
    score = signals.peak_risk_score
    
    if score >= 70:
        risk_color = "red"
        risk_label = "HIGH PEAK RISK"
    elif score >= 40:
        risk_color = "yellow"
        risk_label = "MODERATE PEAK RISK"
    else:
        risk_color = "green"
        risk_label = "LOW PEAK RISK"
    
    # Create visual gauge
    filled = int(score / 5)  # 20 chars total
    gauge = "█" * filled + "░" * (20 - filled)
    
    gauge_lines = [
        f"[bold]Demand Peak Risk Score: [{risk_color}]{score}/100[/{risk_color}][/bold]",
        "",
        f"[{risk_color}]{gauge}[/{risk_color}]",
        f"[{risk_color}]{risk_label}[/{risk_color}]",
        "",
        "0          50         100",
        "└──────────┴──────────┘",
        "Healthy    Moderate    Peak",
    ]
    
    print(Panel("\n".join(gauge_lines), title="Demand Peak Gauge", expand=False))
    
    # Warning signals
    if signals.warning_signals:
        warn_lines = ["[bold red]⚠️ WARNING SIGNALS[/bold red]", ""]
        for w in signals.warning_signals:
            warn_lines.append(f"  • {w}")
        print()
        print(Panel("\n".join(warn_lines), title="Peak Warning Signs", border_style="red", expand=False))
    
    # Healthy signals
    if signals.healthy_signals:
        healthy_lines = ["[bold green]✓ HEALTHY SIGNALS[/bold green]", ""]
        for h in signals.healthy_signals:
            healthy_lines.append(f"  • {h}")
        print()
        print(Panel("\n".join(healthy_lines), title="Demand Strength Signs", border_style="green", expand=False))
    
    # Signal details
    detail_lines = [
        "[bold]Signal Details[/bold]",
        "",
        f"CapEx Growth Decelerating: {'🔴 Yes' if signals.capex_growth_decelerating else '🟢 No'}",
        f"NVDA Margin Pressure: {'🔴 Yes' if signals.nvda_margin_pressure else '🟢 No'}",
        f"Custom Silicon Momentum: {'🔴 Yes (NVDA risk)' if signals.custom_silicon_momentum else '🟢 No'}",
        f"Model Efficiency Improving: {'🔴 Yes (less GPU/query)' if signals.model_efficiency_improving else '🟢 No'}",
        f"AI Startup Funding Declining: {'🔴 Yes' if signals.ai_startup_funding_declining else '🟢 No'}",
    ]
    
    print()
    print(Panel("\n".join(detail_lines), title="Signal Breakdown", expand=False))
    
    # Thesis assessment
    thesis_lines = [
        "[bold]Your Thesis Assessment[/bold]",
        "",
        "[bold cyan]Thesis:[/bold cyan] NVDA customers are running revenue-negative LLM businesses,",
        "demand will lessen as LLM limits are reached, AGI won't come from data centers.",
        "",
        "[bold]Evidence Supporting Your Thesis:[/bold]",
        "  • Private AI labs (OpenAI, Anthropic, xAI) remain unprofitable",
        "  • Model efficiency improving 50%+ yearly → less GPU needed per query",
        "  • Custom silicon (TPU, Trainium) reducing NVDA lock-in",
        "  • Hyperscaler CapEx intensity unsustainable long-term",
        "",
        "[bold]Evidence Against Your Thesis:[/bold]",
        "  • Hyperscalers maintaining strong margins despite CapEx",
        "  • AI revenue actually growing (Copilot, Bedrock, GCP AI)",
        "  • Inference demand exploding (may offset efficiency gains)",
        "  • Training compute still scaling with new model generations",
    ]
    
    print()
    print(Panel("\n".join(thesis_lines), title="Thesis Check", expand=False))


def _show_partner_capex_detail(ticker: str):
    """Show detailed CapEx trend for a specific partner."""
    from ai_options_trader.config import load_settings
    from ai_options_trader.fundamentals.partnerships import get_partner_capex_trend, NVDA_PARTNERS
    
    console = Console()
    settings = load_settings()
    t = ticker.strip().upper()
    
    partner_info = NVDA_PARTNERS.get(t, {"name": t})
    
    console.print(f"\n[bold cyan]CapEx Trend: {partner_info.get('name', t)}[/bold cyan]")
    console.print(f"[dim]AI Exposure: {partner_info.get('ai_exposure', 'N/A')}[/dim]\n")
    
    trend = get_partner_capex_trend(settings, t, years=5)
    
    if not trend:
        console.print("[yellow]No CapEx data available[/yellow]")
        return
    
    # Create trend table
    trend_table = Table(title=f"{t} CapEx Trend", expand=False)
    trend_table.add_column("Year", justify="center")
    trend_table.add_column("CapEx ($B)", justify="right")
    trend_table.add_column("FCF ($B)", justify="right")
    trend_table.add_column("CapEx Growth", justify="right")
    
    prev_capex = None
    for item in trend:
        growth = ""
        if prev_capex and prev_capex > 0:
            g = (item["capex"] / prev_capex - 1) * 100
            color = "red" if g > 30 else "yellow" if g > 10 else "green"
            growth = f"[{color}]{g:+.0f}%[/{color}]"
        
        fcf_color = "green" if item["fcf"] > 0 else "red"
        
        trend_table.add_row(
            item["year"],
            f"${item['capex']:.1f}",
            f"[{fcf_color}]${item['fcf']:.1f}[/{fcf_color}]",
            growth,
        )
        prev_capex = item["capex"]
    
    print(trend_table)
    
    # Calculate CAGR
    if len(trend) >= 2:
        first_capex = trend[0]["capex"]
        last_capex = trend[-1]["capex"]
        years = len(trend) - 1
        if first_capex > 0 and years > 0:
            cagr = (last_capex / first_capex) ** (1 / years) - 1
            print(f"\n[bold]CapEx CAGR ({years} years):[/bold] {cagr*100:+.1f}%")
    
    # Sustainability check
    if trend:
        latest = trend[-1]
        if latest["fcf"] < 0:
            print("\n[red]⚠️ Warning: FCF negative - CapEx exceeds operating cash flow[/red]")
        elif latest["capex"] > latest["fcf"] * 0.8:
            print("\n[yellow]⚠️ Caution: CapEx consuming >80% of FCF[/yellow]")
        else:
            print("\n[green]✓ CapEx appears sustainable relative to FCF[/green]")


def register(labs_app: typer.Typer) -> None:
    """Register fundamentals commands."""
    
    @labs_app.command("nvda-partners")
    def nvda_partners_cmd(
        ticker: str = typer.Option(None, "--ticker", "-t", help="Show detailed CapEx for specific partner"),
        json_out: bool = typer.Option(False, "--json", help="Output as JSON"),
    ):
        """
        NVDA Partner Ecosystem Health Report.
        
        Analyzes NVDA's major customers (hyperscalers, AI companies) to test
        the bear thesis: Are they making money on AI investments?
        
        Tracks:
        - Partner CapEx and growth
        - AI CapEx estimates
        - Margin vs CapEx trends
        - Private AI company burn rates
        
        Examples:
            lox labs nvda-partners
            lox labs nvda-partners -t MSFT
            lox labs nvda-partners -t META
        """
        if ticker:
            _show_partner_capex_detail(ticker)
        else:
            _show_partner_health(json_out=json_out)
    
    @labs_app.command("nvda-demand")
    def nvda_demand_cmd():
        """
        AI/GPU Demand Peak Signal Monitor.
        
        Monitors early warning signals that GPU/AI demand may be peaking:
        - CapEx growth deceleration at hyperscalers
        - NVDA margin pressure
        - Custom silicon adoption (TPU, Trainium)
        - Model efficiency improvements
        - AI startup funding trends
        
        Useful for testing the bear thesis that LLM scaling limits
        will reduce demand for NVDA chips.
        
        Examples:
            lox labs nvda-demand
        """
        _show_demand_peak_signals()
    
    @labs_app.command("openai")
    def openai_exposure_cmd(
        json_out: bool = typer.Option(False, "--json", help="Output as JSON"),
    ):
        """
        OpenAI Exposure Tracker.
        
        Tracks companies directly tied to OpenAI's success/failure:
        - MSFT: $13B+ investor, 49% profit share, Azure OpenAI
        - NVDA: Primary GPU supplier for training
        - ORCL: Cloud infrastructure partner
        - AAPL: Apple Intelligence integration
        
        Also tracks companies at disruption risk from OpenAI.
        
        Bear thesis: OpenAI is revenue-negative, burning $5B/year,
        and if it fails or scales back, these companies take the hit.
        
        Examples:
            lox labs openai
            lox labs openai --json
        """
        _show_openai_exposure(json_out=json_out)
    
    @labs_app.command("nvda-basket")
    def nvda_basket_cmd(
        basket: str = typer.Option("all", "--basket", "-b", help="Basket: all, investments, customers, suppliers, hyperscalers, bear_thesis"),
        json_out: bool = typer.Option(False, "--json", help="Output as JSON"),
    ):
        """
        NVDA Ecosystem Basket - All Related Tickers.
        
        Shows all public companies with NVDA relationships:
        - investments: Companies NVDA has equity stakes in (CRWV, ARM, SNOW, etc.)
        - customers: Companies that buy NVDA GPUs (MSFT, META, GOOGL, etc.)
        - suppliers: Companies in NVDA supply chain (TSM, MU, ASML, etc.)
        - hyperscalers: Big tech GPU buyers
        - bear_thesis: Key tickers for AI demand bear thesis
        
        Examples:
            lox labs nvda-basket
            lox labs nvda-basket -b investments
            lox labs nvda-basket -b bear_thesis
            lox labs nvda-basket -b customers
        """
        from ai_options_trader.config import load_settings
        from ai_options_trader.fundamentals.nvda_ecosystem import (
            build_ecosystem_report,
            NVDA_ECOSYSTEM,
            NVDA_BASKETS,
            NVDA_DEPENDENT_TICKERS,
            get_ecosystem_summary,
        )
        
        console = Console()
        settings = load_settings()
        
        basket_info = NVDA_BASKETS.get(basket, NVDA_BASKETS["all"])
        
        console.print(f"\n[bold cyan]NVDA Ecosystem: {basket_info['name']}[/bold cyan]")
        console.print(f"[dim]{basket_info['description']}[/dim]\n")
        
        if json_out:
            import json
            output = {
                "basket": basket,
                "tickers": basket_info["tickers"],
                "details": {t: NVDA_ECOSYSTEM.get(t, {}) for t in basket_info["tickers"]},
            }
            print(json.dumps(output, indent=2))
            return
        
        console.print("[dim]Fetching market data...[/dim]")
        report = build_ecosystem_report(settings, basket)
        
        # Show NVDA reference
        print(Panel(
            f"[bold]NVDA Reference[/bold]\n\n"
            f"Price: ${report.nvda_price:.2f}\n"
            f"Today: {report.nvda_return_1d:+.2f}%",
            title="NVDA",
            expand=False,
        ))
        
        # Main table
        eco_table = Table(title=f"NVDA Ecosystem Basket ({len(report.tickers)} tickers)", expand=False)
        eco_table.add_column("Ticker", style="bold")
        eco_table.add_column("Name")
        eco_table.add_column("Relationship", style="cyan")
        eco_table.add_column("Category")
        eco_table.add_column("NVDA Stake", justify="right")
        eco_table.add_column("Pays NVDA", justify="center")
        eco_table.add_column("NVDA Impact")
        eco_table.add_column("Price", justify="right")
        eco_table.add_column("Today", justify="right")
        
        for t in sorted(report.tickers, key=lambda x: x.nvda_revenue_impact, reverse=True):
            # Relationship color
            rel_colors = {
                "investment": "green",
                "customer": "cyan",
                "supplier": "yellow",
                "partner": "blue",
                "competitor": "red",
                "ecosystem": "white",
            }
            rel_color = rel_colors.get(t.relationship, "white")
            
            # Impact color
            impact_colors = {
                "very_high": "red",
                "high": "orange1",
                "medium": "yellow",
                "low": "green",
                "none": "dim",
            }
            impact_color = impact_colors.get(t.nvda_revenue_impact, "white")
            
            # Today's return color
            ret_color = "green" if t.return_1d > 0 else "red" if t.return_1d < 0 else "white"
            
            eco_table.add_row(
                t.ticker,
                t.name[:15],
                f"[{rel_color}]{t.relationship}[/{rel_color}]",
                t.category,
                f"{t.nvda_stake_pct}%" if t.nvda_stake_pct > 0 else "—",
                "✓" if t.revenue_to_nvda else "—",
                f"[{impact_color}]{t.nvda_revenue_impact}[/{impact_color}]",
                f"${t.price:.2f}" if t.price > 0 else "—",
                f"[{ret_color}]{t.return_1d:+.2f}%[/{ret_color}]" if t.price > 0 else "—",
            )
        
        print()
        print(eco_table)
        
        # Summary by relationship
        summary_lines = ["[bold]By Relationship[/bold]", ""]
        for rel, tickers in sorted(report.by_relationship.items()):
            summary_lines.append(f"  {rel}: {', '.join(tickers)}")
        
        summary_lines.extend(["", "[bold]By Category[/bold]", ""])
        for cat, tickers in sorted(report.by_category.items()):
            summary_lines.append(f"  {cat}: {', '.join(tickers)}")
        
        print()
        print(Panel("\n".join(summary_lines), title="Groupings", expand=False))
        
        # Available baskets
        basket_lines = ["[bold]Available Baskets[/bold]", ""]
        for bname, binfo in NVDA_BASKETS.items():
            marker = " ← current" if bname == basket else ""
            basket_lines.append(f"  [cyan]{bname}[/cyan]: {binfo['description']} ({len(binfo['tickers'])} tickers){marker}")
        
        print()
        print(Panel("\n".join(basket_lines), title="Run with --basket <name>", expand=False))
        
        # Special handling for dependent basket - show dependency details
        if basket in ["dependent", "critical"]:
            dep_lines = ["[bold red]NVDA-DEPENDENCY ANALYSIS[/bold red]", ""]
            dep_lines.append("These companies have NO significant fallback if AI demand fades:")
            dep_lines.append("")
            
            for t in report.tickers:
                dep_info = NVDA_DEPENDENT_TICKERS.get(t.ticker, {})
                if dep_info:
                    dep_level = dep_info.get("dependency", "unknown")
                    ai_pct = dep_info.get("ai_revenue_pct", 0)
                    why = dep_info.get("why_dependent", "")
                    fallback = dep_info.get("fallback_business", "None")
                    survival = dep_info.get("survival_without_nvda", "Unknown")
                    
                    dep_color = "red" if dep_level == "critical" else "orange1" if dep_level == "high" else "yellow"
                    
                    dep_lines.append(f"[bold]{t.ticker}[/bold] - [{dep_color}]{dep_level.upper()} DEPENDENCY[/{dep_color}]")
                    dep_lines.append(f"  AI Revenue %: ~{ai_pct}%")
                    dep_lines.append(f"  Why Dependent: {why}")
                    dep_lines.append(f"  Fallback Business: {fallback or 'NONE'}")
                    dep_lines.append(f"  Without NVDA/AI: [{dep_color}]{survival}[/{dep_color}]")
                    dep_lines.append("")
            
            print()
            print(Panel("\n".join(dep_lines), title="Dependency Analysis", border_style="red", expand=False))
        
        # Ticker list for copy/paste
        ticker_list = ", ".join(t.ticker for t in report.tickers)
        print()
        print(Panel(ticker_list, title="Copy/Paste Ticker List", expand=False))
    
    @labs_app.command("coreweave")
    def coreweave_cmd():
        """
        CoreWeave (CRWV) - NVIDIA Circular Dependency Analysis.
        
        Analyzes the NVDA → CRWV → NVDA circular revenue relationship:
        - NVIDIA invests in CoreWeave
        - CoreWeave uses investment to buy NVIDIA GPUs
        - NVIDIA books GPU sale as revenue
        
        Key concerns:
        - CRWV is unprofitable (losing $860M in 2024)
        - 60%+ revenue from Microsoft (concentration risk)
        - $8.7B CapEx for $1.9B revenue (unsustainable?)
        - If CRWV fails, NVDA loses major customer + investment
        
        Examples:
            lox labs coreweave
        """
        _show_coreweave_analysis()
    
    @labs_app.command("model")
    def model_cmd(
        ticker: str = typer.Option(..., "--ticker", "-t", help="Ticker symbol"),
        model_type: str = typer.Option("sensitivity", "--type", help="Model type: sensitivity, dcf, reverse-dcf"),
        pe_target: float = typer.Option(25, "--pe", help="Target P/E multiple for sensitivity model"),
        growth1: float = typer.Option(0.20, "--growth1", help="Phase 1 growth rate for DCF"),
        growth2: float = typer.Option(0.10, "--growth2", help="Phase 2 growth rate for DCF"),
        discount: float = typer.Option(0.10, "--discount", help="Discount rate (WACC) for DCF"),
        json_out: bool = typer.Option(False, "--json", help="Output as JSON"),
    ):
        """
        CFA-level financial modeling.
        
        Model Types:
        - sensitivity: Revenue/margin sensitivity matrix
        - dcf: Discounted cash flow valuation
        - reverse-dcf: What growth is priced in?
        
        Examples:
            lox labs model -t NVDA --type sensitivity --pe 30
            lox labs model -t NVDA --type dcf --growth1 0.25
            lox labs model -t NVDA --type reverse-dcf
        """
        if model_type == "sensitivity":
            _run_sensitivity_model(ticker, pe_target=pe_target, json_out=json_out)
        elif model_type == "dcf":
            _run_dcf_model(ticker, growth_phase1=growth1, growth_phase2=growth2, discount_rate=discount, json_out=json_out)
        elif model_type == "reverse-dcf":
            _run_reverse_dcf(ticker, discount_rate=discount, json_out=json_out)
        else:
            print(f"[red]Unknown model type: {model_type}[/red]")
    
    @labs_app.command("research")
    def research_cmd(
        ticker: str = typer.Option(..., "--ticker", "-t", help="Ticker symbol"),
        llm: bool = typer.Option(False, "--llm", help="Include LLM research summary"),
    ):
        """
        Deep research aggregation for a ticker.
        
        Gathers:
        - SEC filings (10-K, 10-Q, 8-K)
        - Recent news (categorized)
        - CapEx and R&D trends
        - Partnership announcements
        
        Examples:
            lox labs research -t NVDA
            lox labs research -t NVDA --llm
        """
        _run_research_deep_dive(ticker, llm=llm)
