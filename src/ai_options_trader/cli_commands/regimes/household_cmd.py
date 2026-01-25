"""
Household Wealth Regime CLI Command

Tracks where government deficit dollars flow and what household behavior they drive.
Based on MMT sectoral balances: S = (G-T) + I + NX
"""
from __future__ import annotations

import typer
from rich import print
from rich.panel import Panel
from rich.table import Table


def _fmt(val: float | None, decimals: int = 2, suffix: str = "") -> str:
    """Format a float value for display."""
    if val is None:
        return "—"
    return f"{val:.{decimals}f}{suffix}"


def _fmt_pct(val: float | None) -> str:
    """Format a percentage value."""
    if val is None:
        return "—"
    return f"{val:+.2f}%"


def _fmt_z(val: float | None) -> str:
    """Format a z-score value."""
    if val is None:
        return "—"
    return f"{val:+.2f}σ"


def _run_household_snapshot(
    start: str = "2011-01-01",
    refresh: bool = False,
    llm: bool = False,
    features: bool = False,
    json_output: bool = False,
):
    """Shared implementation for household snapshot."""
    from ai_options_trader.config import load_settings
    from ai_options_trader.household.signals import build_household_state
    from ai_options_trader.household.regime import classify_household_regime
    
    settings = load_settings()
    state = build_household_state(settings=settings, start_date=start, refresh=refresh)
    regime = classify_household_regime(state.inputs)
    inp = state.inputs
    
    # JSON output mode
    if json_output:
        import json
        from dataclasses import asdict
        output = {
            "asof": state.asof,
            "regime": {
                "name": regime.name,
                "label": regime.label,
                "description": regime.description,
                "tags": list(regime.tags),
                "market_implications": regime.market_implications,
            },
            "inputs": {
                k: v for k, v in (
                    inp.components if isinstance(inp.components, dict) else {}
                ).items()
            } | {
                "savings_rate": inp.savings_rate,
                "debt_service_ratio": inp.debt_service_ratio,
                "consumer_sentiment": inp.consumer_sentiment,
                "wealth_score": inp.wealth_score,
                "debt_stress_score": inp.debt_stress_score,
                "behavioral_score": inp.behavioral_score,
                "prosperity_score": inp.household_prosperity_score,
            },
        }
        if inp.sectoral:
            output["sectoral_balances"] = {
                "govt_deficit_pct_gdp": inp.sectoral.govt_deficit_pct_gdp,
                "net_exports_pct_gdp": inp.sectoral.net_exports_pct_gdp,
                "private_balance_pct_gdp": inp.sectoral.private_balance_pct_gdp,
                "notes": inp.sectoral.notes,
            }
        print(json.dumps(output, indent=2, default=str))
        return
    
    # Features output mode
    if features:
        from ai_options_trader.household.features import household_feature_vector
        vec = household_feature_vector(state, regime)
        
        tbl = Table(title="Household Regime Features")
        tbl.add_column("Feature", style="cyan")
        tbl.add_column("Value", justify="right")
        
        for k, v in sorted(vec.features.items()):
            tbl.add_row(k, f"{v:.4f}" if isinstance(v, float) else str(v))
        
        print(tbl)
        return
    
    # Standard output
    # Sectoral balances context
    sectoral_text = ""
    if inp.sectoral and inp.sectoral.govt_deficit_pct_gdp is not None:
        sectoral_text = (
            f"\n[bold cyan]MMT Sectoral Balances[/bold cyan] (S = G-T + I + NX)\n"
            f"  Govt Deficit (G-T):  {_fmt_pct(inp.sectoral.govt_deficit_pct_gdp)} of GDP\n"
            f"  Net Exports (NX):    {_fmt_pct(inp.sectoral.net_exports_pct_gdp)} of GDP\n"
            f"  Private Balance:     {_fmt_pct(inp.sectoral.private_balance_pct_gdp)} of GDP\n"
        )
    
    # Main display
    print(
        Panel(
            f"[b]Regime:[/b] {regime.label}\n"
            f"[b]As of:[/b] {state.asof}\n\n"
            f"[dim]{regime.description}[/dim]\n"
            f"{sectoral_text}\n"
            f"[bold cyan]Wealth Metrics[/bold cyan]\n"
            f"  Net Worth YoY:       {_fmt_pct(inp.net_worth_yoy_pct)}  (z={_fmt_z(inp.z_net_worth_yoy)})\n"
            f"  Real Net Worth YoY:  {_fmt_pct(inp.net_worth_real_yoy_pct)}\n"
            f"  Savings Rate:        {_fmt(inp.savings_rate, 1, '%')}  (z={_fmt_z(inp.z_savings_rate)})\n"
            f"\n[bold cyan]Debt Metrics[/bold cyan]\n"
            f"  Debt Service Ratio:  {_fmt(inp.debt_service_ratio, 1, '%')}  (z={_fmt_z(inp.z_debt_service)})\n"
            f"  Consumer Credit YoY: {_fmt_pct(inp.consumer_credit_yoy_pct)}  (z={_fmt_z(inp.z_consumer_credit_yoy)})\n"
            f"  Revolving Cred YoY:  {_fmt_pct(inp.revolving_credit_yoy_pct)}\n"
            f"  Mortgage Delinq:     {_fmt(inp.mortgage_delinquency_rate, 2, '%')}\n"
            f"\n[bold cyan]Behavioral Metrics[/bold cyan]\n"
            f"  Consumer Sentiment:  {_fmt(inp.consumer_sentiment, 1)}  (z={_fmt_z(inp.z_consumer_sentiment)})\n"
            f"  M2 Velocity:         {_fmt(inp.m2_velocity, 2)}  (z={_fmt_z(inp.z_m2_velocity)})\n"
            f"  Real DPI YoY:        {_fmt_pct(inp.real_dpi_yoy_pct)}  (z={_fmt_z(inp.z_real_dpi_yoy)})\n"
            f"  Retail Sales YoY:    {_fmt_pct(inp.retail_sales_yoy_pct)}  (z={_fmt_z(inp.z_retail_sales_yoy)})\n"
            f"\n[bold cyan]Composite Scores[/bold cyan]\n"
            f"  Wealth Score:        {_fmt_z(inp.wealth_score)}\n"
            f"  Debt Stress Score:   {_fmt_z(inp.debt_stress_score)}\n"
            f"  Behavioral Score:    {_fmt_z(inp.behavioral_score)}\n"
            f"  [b]Prosperity Score:[/b]  {_fmt_z(inp.household_prosperity_score)}\n",
            title="Household Wealth Regime",
            expand=False,
        )
    )
    
    # Market implications
    if regime.market_implications:
        print(
            Panel(
                regime.market_implications,
                title="Market Implications",
                expand=False,
            )
        )
    
    # LLM analysis
    if llm:
        from ai_options_trader.llm.core.analyst import llm_analyze_regime
        
        print("\n[bold cyan]Generating LLM analysis...[/bold cyan]\n")
        
        snapshot_data = {
            "regime": regime.name,
            "regime_label": regime.label,
            # Sectoral balances
            "govt_deficit_pct_gdp": inp.sectoral.govt_deficit_pct_gdp if inp.sectoral else None,
            "net_exports_pct_gdp": inp.sectoral.net_exports_pct_gdp if inp.sectoral else None,
            "private_balance_pct_gdp": inp.sectoral.private_balance_pct_gdp if inp.sectoral else None,
            # Wealth
            "net_worth_yoy_pct": inp.net_worth_yoy_pct,
            "net_worth_real_yoy_pct": inp.net_worth_real_yoy_pct,
            "savings_rate": inp.savings_rate,
            "z_savings_rate": inp.z_savings_rate,
            # Debt
            "debt_service_ratio": inp.debt_service_ratio,
            "z_debt_service": inp.z_debt_service,
            "consumer_credit_yoy_pct": inp.consumer_credit_yoy_pct,
            # Behavior
            "consumer_sentiment": inp.consumer_sentiment,
            "z_consumer_sentiment": inp.z_consumer_sentiment,
            "m2_velocity": inp.m2_velocity,
            "z_m2_velocity": inp.z_m2_velocity,
            # Composites
            "wealth_score": inp.wealth_score,
            "debt_stress_score": inp.debt_stress_score,
            "behavioral_score": inp.behavioral_score,
            "prosperity_score": inp.household_prosperity_score,
        }
        
        analysis = llm_analyze_regime(
            settings=settings,
            domain="household",
            snapshot=snapshot_data,
            regime_label=regime.label,
            regime_description=regime.description,
        )
        
        from rich.markdown import Markdown
        print(Panel(Markdown(analysis), title="LLM Analysis", expand=False))


def register(household_app: typer.Typer) -> None:
    """Register household regime commands."""
    
    @household_app.callback(invoke_without_command=True)
    def household_default(
        ctx: typer.Context,
        llm: bool = typer.Option(False, "--llm", help="Get LLM analysis of household regime"),
        features: bool = typer.Option(False, "--features", help="Output ML feature vector"),
        json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
    ):
        """
        Household wealth regime: where do deficit dollars flow?
        
        Based on MMT sectoral balances: S = (G-T) + I + NX
        
        Regimes:
        - WEALTH_ACCUMULATION: Deficit → net worth gains, healthy savings
        - DELEVERAGING: Deficit → debt paydown, elevated savings, low velocity
        - CREDIT_EXPANSION: Deficit → leverage-driven gains, fragile
        - INFLATIONARY_EROSION: Nominal gains but real purchasing power down
        - CORPORATE_CAPTURE: Deficit not reaching households
        """
        if ctx.invoked_subcommand is None:
            _run_household_snapshot(llm=llm, features=features, json_output=json_output)
    
    @household_app.command("snapshot")
    def snapshot(
        start: str = typer.Option("2011-01-01", "--start", help="Start date for historical data"),
        refresh: bool = typer.Option(False, "--refresh", help="Refresh cached FRED data"),
        llm: bool = typer.Option(False, "--llm", help="Get LLM analysis of household regime"),
        features: bool = typer.Option(False, "--features", help="Output ML feature vector"),
        json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
    ):
        """
        Household wealth regime snapshot.
        
        Shows current state of household balance sheets and behavior,
        contextualized by MMT sectoral balances (where deficit dollars flow).
        """
        _run_household_snapshot(
            start=start,
            refresh=refresh,
            llm=llm,
            features=features,
            json_output=json_output,
        )
    
    @household_app.command("sectoral")
    def sectoral_balances(
        start: str = typer.Option("2011-01-01", "--start", help="Start date"),
        refresh: bool = typer.Option(False, "--refresh", help="Refresh cached data"),
    ):
        """
        Display MMT sectoral balances: S = (G-T) + I + NX
        
        Government deficits create private surpluses by accounting identity.
        This shows where the money flows.
        """
        from ai_options_trader.config import load_settings
        from ai_options_trader.household.signals import build_sectoral_balances
        
        settings = load_settings()
        sb = build_sectoral_balances(settings=settings, start_date=start, refresh=refresh)
        
        print(
            Panel(
                f"[b]MMT Sectoral Balances Identity[/b]\n"
                f"S = (G - T) + I + NX\n\n"
                f"Where:\n"
                f"  S   = Private Sector Savings\n"
                f"  G-T = Government Deficit\n"
                f"  I   = Net Investment\n"
                f"  NX  = Net Exports\n\n"
                f"[b]As of:[/b] {sb.asof or 'N/A'}\n\n"
                f"[bold cyan]Current Values (% of GDP)[/bold cyan]\n"
                f"  Government Deficit (G-T): {_fmt_pct(sb.govt_deficit_pct_gdp)}\n"
                f"  Net Exports (NX):         {_fmt_pct(sb.net_exports_pct_gdp)}\n"
                f"  Private Investment (I):   {_fmt_pct(sb.private_investment_pct_gdp)}\n"
                f"  [b]Private Balance (S):[/b]     {_fmt_pct(sb.private_balance_pct_gdp)}\n\n"
                f"[dim]Key insight: Government deficits necessarily create private surpluses.[/dim]\n"
                f"[dim]The question is WHERE they accumulate (households vs corporations)[/dim]\n"
                f"[dim]and what BEHAVIOR they drive (saving, spending, or deleveraging).[/dim]",
                title="Sectoral Balances (MMT Framework)",
                expand=False,
            )
        )
    
    @household_app.command("debt")
    def debt_detail(
        start: str = typer.Option("2011-01-01", "--start", help="Start date"),
        refresh: bool = typer.Option(False, "--refresh", help="Refresh cached data"),
    ):
        """
        Detailed household debt metrics.
        
        Shows debt service burden, credit dynamics, and stress indicators.
        """
        from ai_options_trader.config import load_settings
        from ai_options_trader.household.signals import build_household_state
        
        settings = load_settings()
        state = build_household_state(settings=settings, start_date=start, refresh=refresh)
        inp = state.inputs
        
        tbl = Table(title="Household Debt Metrics")
        tbl.add_column("Metric", style="cyan")
        tbl.add_column("Value", justify="right")
        tbl.add_column("Z-Score", justify="right")
        tbl.add_column("Interpretation")
        
        # Debt service
        dsr = inp.debt_service_ratio
        z_dsr = inp.z_debt_service
        dsr_interp = "Normal"
        if z_dsr is not None:
            if z_dsr >= 1.0:
                dsr_interp = "Elevated burden"
            elif z_dsr <= -1.0:
                dsr_interp = "Low burden"
        tbl.add_row(
            "Debt Service Ratio",
            _fmt(dsr, 1, "%"),
            _fmt_z(z_dsr),
            dsr_interp,
        )
        
        # Consumer credit
        cc_yoy = inp.consumer_credit_yoy_pct
        z_cc = inp.z_consumer_credit_yoy
        cc_interp = "Normal"
        if z_cc is not None:
            if z_cc >= 1.5:
                cc_interp = "Rapid expansion"
            elif z_cc <= -1.0:
                cc_interp = "Contraction"
        tbl.add_row(
            "Consumer Credit YoY",
            _fmt_pct(cc_yoy),
            _fmt_z(z_cc),
            cc_interp,
        )
        
        # Revolving credit
        rev_yoy = inp.revolving_credit_yoy_pct
        tbl.add_row(
            "Revolving (Cards) YoY",
            _fmt_pct(rev_yoy),
            "—",
            "Credit card growth",
        )
        
        # Mortgage delinquency
        mdq = inp.mortgage_delinquency_rate
        z_mdq = inp.z_mortgage_delinquency
        mdq_interp = "Normal"
        if z_mdq is not None:
            if z_mdq >= 1.0:
                mdq_interp = "Elevated stress"
            elif z_mdq <= -1.0:
                mdq_interp = "Low stress"
        tbl.add_row(
            "Mortgage Delinquency",
            _fmt(mdq, 2, "%"),
            _fmt_z(z_mdq),
            mdq_interp,
        )
        
        print(tbl)
        
        # Debt stress composite
        print(
            Panel(
                f"[b]Debt Stress Score:[/b] {_fmt_z(inp.debt_stress_score)}\n\n"
                f"Components:\n"
                f"  Z(Debt Service):     {_fmt_z(inp.z_debt_service)} × 40%\n"
                f"  Z(Credit Growth):    {_fmt_z(inp.z_consumer_credit_yoy)} × 30%\n"
                f"  Z(Delinquency):      {_fmt_z(inp.z_mortgage_delinquency)} × 30%\n\n"
                f"[dim]Positive = more debt stress, negative = healthy debt dynamics[/dim]",
                title="Debt Stress Composite",
                expand=False,
            )
        )
