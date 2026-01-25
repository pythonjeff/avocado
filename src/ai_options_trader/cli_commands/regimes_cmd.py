from __future__ import annotations

import pandas as pd
import typer
from rich import print
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ai_options_trader.config import load_settings
from ai_options_trader.macro.regime import classify_macro_regime_from_state
from ai_options_trader.macro.signals import build_macro_state


def register(app: typer.Typer) -> None:
    
    @app.command("unified")
    def unified_regimes(
        start: str = typer.Option("2020-01-01", "--start", help="Start date YYYY-MM-DD"),
        refresh: bool = typer.Option(False, "--refresh", help="Force refresh data"),
        json_output: bool = typer.Option(False, "--json", help="Output as JSON for ML"),
    ):
        """
        Show unified regime state across all domains.
        
        This is the recommended view for understanding the current market regime
        and extracting ML-friendly features.
        """
        from ai_options_trader.regimes import build_unified_regime_state
        import json as json_module
        
        console = Console()
        settings = load_settings()
        
        with console.status("[cyan]Building unified regime state...[/cyan]"):
            state = build_unified_regime_state(
                settings=settings,
                start_date=start,
                refresh=refresh,
            )
        
        if json_output:
            features = state.to_feature_dict()
            print(json_module.dumps(features, indent=2, default=str))
            return
        
        # Display as rich table
        console.print()
        console.print(Panel(
            f"[bold]Overall: {state.overall_category.upper()}[/bold] (score: {state.overall_risk_score:.0f}/100)",
            title=f"🎯 Unified Regime State — {state.asof}",
            border_style="cyan",
        ))
        
        # Core 4 pillars table
        core_table = Table(title="Core Pillars (Monte Carlo)", show_header=True, header_style="bold cyan")
        core_table.add_column("Domain", style="bold")
        core_table.add_column("Regime")
        core_table.add_column("Score", justify="right")
        core_table.add_column("Description")
        
        for domain in ["macro", "volatility", "rates", "funding"]:
            regime = getattr(state, domain, None)
            if regime:
                score_color = "green" if regime.score < 40 else ("red" if regime.score > 60 else "yellow")
                core_table.add_row(
                    domain.title(),
                    regime.label,
                    f"[{score_color}]{regime.score:.0f}[/{score_color}]",
                    regime.description[:60] + "..." if len(regime.description) > 60 else regime.description,
                )
            else:
                core_table.add_row(domain.title(), "N/A", "-", "Data unavailable")
        
        console.print(core_table)
        console.print()
        
        # Extended regimes table
        ext_table = Table(title="Extended Regimes (Context)", show_header=True, header_style="bold magenta")
        ext_table.add_column("Domain", style="bold")
        ext_table.add_column("Regime")
        ext_table.add_column("Score", justify="right")
        ext_table.add_column("Description")
        
        for domain in ["fiscal", "commodities", "housing", "monetary", "usd", "crypto"]:
            regime = getattr(state, domain, None)
            if regime:
                score_color = "green" if regime.score < 40 else ("red" if regime.score > 60 else "yellow")
                ext_table.add_row(
                    domain.title(),
                    regime.label,
                    f"[{score_color}]{regime.score:.0f}[/{score_color}]",
                    regime.description[:60] + "..." if len(regime.description) > 60 else regime.description,
                )
            else:
                ext_table.add_row(domain.title(), "N/A", "-", "Data unavailable")
        
        console.print(ext_table)
        console.print()
        
        # Monte Carlo parameters
        mc_params = state.to_monte_carlo_params()
        mc_table = Table(title="Monte Carlo Adjustments", show_header=True, header_style="bold green")
        mc_table.add_column("Parameter")
        mc_table.add_column("Value", justify="right")
        mc_table.add_column("Effect")
        
        def fmt_adj(val, base=0.0, mult=False):
            if mult:
                if val > 1.0:
                    return f"[red]+{(val-1)*100:.0f}%[/red]"
                elif val < 1.0:
                    return f"[green]{(val-1)*100:.0f}%[/green]"
                else:
                    return "0%"
            else:
                if val > base:
                    return f"[red]+{val*100:.1f}%[/red]"
                elif val < base:
                    return f"[green]{val*100:.1f}%[/green]"
                else:
                    return "0%"
        
        mc_table.add_row("Equity Drift Adj", fmt_adj(mc_params["equity_drift_adj"]), "Annual return modifier")
        mc_table.add_row("Equity Vol Adj", fmt_adj(mc_params["equity_vol_adj"], mult=True), "Volatility multiplier")
        mc_table.add_row("IV Drift Adj", fmt_adj(mc_params["iv_drift_adj"]), "Implied vol shift")
        mc_table.add_row("Jump Prob Adj", fmt_adj(mc_params["jump_prob_adj"], mult=True), "Tail event likelihood")
        mc_table.add_row("Spread Drift Adj", fmt_adj(mc_params["spread_drift_adj"]), "Credit spread shift")
        
        console.print(mc_table)
        console.print()
        
        console.print("[dim]Run with --json for ML-friendly feature export[/dim]")
    
    @app.command("transitions")
    def regime_transitions(
        domain: str = typer.Option("risk_category", "--domain", "-d", help="Regime domain"),
        horizon: int = typer.Option(21, "--horizon", help="Horizon in trading days (21=1mo, 63=3mo, 126=6mo)"),
        current: str = typer.Option("cautious", "--current", "-c", help="Current regime state"),
        adjust: bool = typer.Option(True, "--adjust/--no-adjust", help="Adjust for leading indicators"),
        refresh: bool = typer.Option(False, "--refresh", help="Force refresh regime data"),
    ):
        """
        Show regime transition probabilities for Monte Carlo.
        
        By default, adjusts probabilities based on leading indicators
        (yield curve, VIX, credit spreads, funding stress).
        
        Use --no-adjust for raw historical frequencies.
        """
        from ai_options_trader.regimes import get_transition_matrix, build_unified_regime_state
        from ai_options_trader.regimes.transitions import (
            get_adjusted_transition_matrix, 
            LEADING_INDICATORS,
            LeadingIndicatorSignals,
        )
        
        console = Console()
        settings = load_settings()
        
        # Get adjusted or base matrix
        signals = LeadingIndicatorSignals()
        if adjust:
            with console.status("[cyan]Loading regime data for signal analysis...[/cyan]"):
                try:
                    unified_state = build_unified_regime_state(settings=settings, refresh=refresh)
                    matrix, signals = get_adjusted_transition_matrix(domain, horizon, unified_state)
                except Exception as e:
                    console.print(f"[yellow]Warning: Could not load signals ({e}), using base matrix[/yellow]")
                    matrix = get_transition_matrix(domain, horizon_days=horizon)
        else:
            matrix = get_transition_matrix(domain, horizon_days=horizon)
        
        # Header with clear explanation
        console.print()
        console.print(Panel(
            "[bold]What is this?[/bold]\n"
            "Probability of the market regime changing over the forecast horizon.\n"
            "Used to weight Monte Carlo scenarios by how likely each regime is.\n\n"
            "[bold]Methodology:[/bold] Historical frequency analysis\n"
            "• Based on empirical regime transitions from 2000-2024 market data\n"
            "• NOT ML/PCA - these are observed frequencies of regime changes\n"
            "• Longer horizons mean-revert toward equal probabilities\n\n"
            f"[bold]Horizon:[/bold] {horizon} trading days (~{horizon//21} month{'s' if horizon > 21 else ''})",
            title=f"📊 Regime Transition Matrix — {domain.replace('_', ' ').title()}",
            border_style="cyan",
        ))
        
        # Transition matrix with clear labels
        console.print()
        console.print("[bold]Transition Probabilities[/bold]")
        console.print("[dim]Read as: If TODAY is (row), what's the probability NEXT PERIOD is (column)?[/dim]")
        console.print()
        
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("If TODAY is...", style="bold")
        for state in matrix.states:
            table.add_column(f"→ {state.replace('_', ' ').title()}", justify="right")
        
        for i, from_state in enumerate(matrix.states):
            row = [from_state.replace("_", " ").title()]
            for j, to_state in enumerate(matrix.states):
                prob = matrix.matrix[i, j]
                # Highlight diagonal (persistence) vs off-diagonal (change)
                if i == j:  # Staying in same regime
                    row.append(f"[bold cyan]{prob:.0%}[/bold cyan] (stay)")
                elif prob > 0.2:
                    row.append(f"[yellow]{prob:.0%}[/yellow]")
                else:
                    row.append(f"[dim]{prob:.0%}[/dim]")
            table.add_row(*row)
        
        console.print(table)
        console.print()
        
        # Forecast from current state
        console.print(f"[bold]Your Forecast (starting from '{current}'):[/bold]")
        console.print(f"[dim]In {horizon} trading days (~{horizon//21} month{'s' if horizon > 21 else ''}), the market will likely be:[/dim]")
        console.print()
        
        probs = matrix.get_next_state_probs(current)
        for state, prob in sorted(probs.items(), key=lambda x: -x[1]):
            bar_len = int(prob * 40)
            bar = "█" * bar_len + "░" * (40 - bar_len)
            
            # Add interpretation
            if state == current:
                interp = "(no change)"
            elif state == "risk_off":
                interp = "(deterioration)"
            elif state == "risk_on":
                interp = "(improvement)"
            else:
                interp = ""
            
            console.print(f"  {state.replace('_', ' ').title():12} {bar} [bold]{prob:.0%}[/bold] {interp}")
        
        # Show active leading indicators if adjusting
        active_signals = signals.active_signals()
        if adjust and active_signals:
            console.print()
            console.print("[bold yellow]⚠ Active Warning Signals (adjusting probabilities):[/bold yellow]")
            risk_off_mult, risk_on_mult = signals.risk_adjustment_factor()
            for sig in active_signals:
                indicator = LEADING_INDICATORS.get(sig, {})
                console.print(f"  • [yellow]{sig.replace('_', ' ').title()}[/yellow]: {indicator.get('description', '')}")
            console.print()
            console.print(f"  [dim]Combined adjustment: risk_off ×{risk_off_mult:.1f}, risk_on ×{risk_on_mult:.1f}[/dim]")
        elif adjust:
            console.print()
            console.print("[green]✓ No warning signals active - using base historical probabilities[/green]")
        
        console.print()
        console.print("[dim]Usage: These probabilities weight Monte Carlo scenarios.[/dim]")
        console.print("[dim]       Use --no-adjust to see raw historical frequencies.[/dim]")
    @app.command("regimes")
    def regimes(
        start: str = typer.Option("2011-01-01", "--start", help="Start date YYYY-MM-DD"),
        refresh: bool = typer.Option(False, "--refresh", help="Force refresh FRED downloads"),
        benchmark: str = typer.Option("XLY", "--benchmark", help="Sector or market benchmark (e.g., XLY, SPY)"),
        baskets: str = typer.Option(
            "all",
            "--baskets",
            help="Comma-separated basket names, or 'all' (see: ai-options-trader tariff baskets)",
        ),
        llm: bool = typer.Option(False, "--llm", help="Ask an LLM to summarize regimes + follow-ups"),
        llm_model: str = typer.Option("", "--llm-model", help="Override OPENAI_MODEL (optional)"),
        llm_temperature: float = typer.Option(0.2, "--llm-temperature", help="LLM temperature (0..2)"),
    ):
        """
        Print the current macro regime and all tariff/cost-push regimes (by basket).
        """
        from ai_options_trader.data.fred import FredClient
        from ai_options_trader.data.market import fetch_equity_daily_closes
        from ai_options_trader.funding.signals import build_funding_state
        from ai_options_trader.tariff.universe import BASKETS
        from ai_options_trader.tariff.proxies import DEFAULT_COST_PROXY_SERIES
        from ai_options_trader.tariff.signals import build_tariff_regime_state

        settings = load_settings()

        # --- Macro ---
        macro_state = build_macro_state(settings=settings, start_date=start, refresh=refresh)
        print(macro_state)
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
        print("\nMACRO REGIME")
        print(macro_regime)

        # --- Liquidity ---
        liquidity_state = build_funding_state(settings=settings, start_date=start, refresh=refresh)
        print("\nLIQUIDITY (CREDIT + RATES)")
        print(liquidity_state)

        # --- Tariff baskets selection ---
        if baskets.strip().lower() == "all":
            basket_names = list(BASKETS.keys())
        else:
            basket_names = [b.strip() for b in baskets.split(",") if b.strip()]

        unknown = [b for b in basket_names if b not in BASKETS]
        if unknown:
            raise typer.BadParameter(f"Unknown basket(s): {unknown}. Choose from: {list(BASKETS.keys())}")

        # --- Cost proxies (FRED) fetched once ---
        if not settings.FRED_API_KEY:
            raise RuntimeError("Missing FRED_API_KEY in environment / .env")
        fred = FredClient(api_key=settings.FRED_API_KEY)

        frames = []
        for col, sid in DEFAULT_COST_PROXY_SERIES.items():
            df = fred.fetch_series(sid, start_date=start, refresh=refresh)
            df = df.rename(columns={"value": col}).set_index("date")
            frames.append(df[[col]])
        cost_df = pd.concat(frames, axis=1).sort_index().resample("D").ffill()

        # --- Equities (historical closes; default: FMP) fetched once ---
        all_universe = sorted({sym for b in basket_names for sym in BASKETS[b].tickers})
        symbols = sorted(set(all_universe + [benchmark.strip().upper()]))
        px = fetch_equity_daily_closes(settings=settings, symbols=symbols, start=start, refresh=bool(refresh))
        px = px.sort_index().ffill().dropna(how="all")

        print("\nTARIFF / COST-PUSH REGIMES")
        tariff_results = []
        for b in basket_names:
            basket = BASKETS[b]
            print(f"\n[b]{basket.name}[/b] — {basket.description}")
            state = build_tariff_regime_state(
                cost_df=cost_df,
                equity_prices=px,
                universe=basket.tickers,
                benchmark=benchmark,
                basket_name=basket.name,
                start_date=start,
            )
            print(state)
            tariff_results.append(
                {
                    "basket": basket.name,
                    "description": basket.description,
                    "benchmark": benchmark,
                    "state": state,
                }
            )

        if llm:
            from ai_options_trader.llm.regime_summary import llm_regime_summary

            print("\nLLM SUMMARY")
            summary = llm_regime_summary(
                settings=settings,
                macro_state=macro_state,
                macro_regime=macro_regime,
                tariff_regimes=tariff_results,
                model=llm_model.strip() or None,
                temperature=float(llm_temperature),
            )
            print(summary)

    @app.command("regime-features")
    def regime_features(
        start: str = typer.Option("2011-01-01", "--start", help="Start date YYYY-MM-DD"),
        refresh: bool = typer.Option(False, "--refresh", help="Force refresh FRED downloads"),
        benchmark: str = typer.Option("XLY", "--benchmark", help="Sector or market benchmark (e.g., XLY, SPY)"),
        baskets: str = typer.Option(
            "all",
            "--baskets",
            help="Comma-separated basket names, or 'all' (see: ai-options-trader tariff baskets)",
        ),
        pretty: bool = typer.Option(True, "--pretty/--compact", help="Pretty-print JSON"),
    ):
        """
        Print a single merged, ML-friendly feature vector (floats only) for:
        - macro regime
        - liquidity regime (credit + rates)
        - tariff/cost-push regimes (per basket + aggregates)
        """
        import json

        from ai_options_trader.data.fred import FredClient
        from ai_options_trader.data.market import fetch_equity_daily_closes
        from ai_options_trader.funding.features import funding_feature_vector
        from ai_options_trader.funding.signals import build_funding_state
        from ai_options_trader.macro.features import macro_feature_vector
        from ai_options_trader.rates.features import rates_feature_vector
        from ai_options_trader.rates.regime import classify_rates_regime
        from ai_options_trader.rates.signals import build_rates_state
        from ai_options_trader.regimes.schema import merge_feature_dicts
        from ai_options_trader.tariff.features import tariff_feature_vector
        from ai_options_trader.tariff.proxies import DEFAULT_COST_PROXY_SERIES
        from ai_options_trader.tariff.signals import build_tariff_regime_state
        from ai_options_trader.tariff.universe import BASKETS
        from ai_options_trader.usd.features import usd_feature_vector
        from ai_options_trader.usd.signals import build_usd_state
        from ai_options_trader.volatility.features import volatility_feature_vector
        from ai_options_trader.volatility.regime import classify_volatility_regime
        from ai_options_trader.volatility.signals import build_volatility_state
        from ai_options_trader.commodities.features import commodities_feature_vector
        from ai_options_trader.commodities.regime import classify_commodities_regime
        from ai_options_trader.commodities.signals import build_commodities_state

        settings = load_settings()

        # Macro
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
        macro_vec = macro_feature_vector(macro_state=macro_state, macro_regime=macro_regime)

        # Liquidity
        liq_state = build_funding_state(settings=settings, start_date=start, refresh=refresh)
        liq_vec = funding_feature_vector(liq_state)

        # USD
        usd_state = build_usd_state(settings=settings, start_date=start, refresh=refresh)
        usd_vec = usd_feature_vector(usd_state)

        # Rates
        rates_state = build_rates_state(settings=settings, start_date=start, refresh=refresh)
        rates_regime = classify_rates_regime(rates_state.inputs)
        rates_vec = rates_feature_vector(rates_state, rates_regime)

        # Volatility
        vol_state = build_volatility_state(settings=settings, start_date=start, refresh=refresh)
        vol_regime = classify_volatility_regime(vol_state.inputs)
        vol_vec = volatility_feature_vector(vol_state, vol_regime)

        # Commodities
        commod_state = build_commodities_state(settings=settings, start_date=start, refresh=refresh)
        commod_regime = classify_commodities_regime(commod_state.inputs)
        commod_vec = commodities_feature_vector(commod_state, commod_regime)

        # Tariff basket selection
        if baskets.strip().lower() == "all":
            basket_names = list(BASKETS.keys())
        else:
            basket_names = [b.strip() for b in baskets.split(",") if b.strip()]
        unknown = [b for b in basket_names if b not in BASKETS]
        if unknown:
            raise typer.BadParameter(f"Unknown basket(s): {unknown}. Choose from: {list(BASKETS.keys())}")

        # Cost proxies (FRED) fetched once
        if not settings.FRED_API_KEY:
            raise RuntimeError("Missing FRED_API_KEY in environment / .env")
        fred = FredClient(api_key=settings.FRED_API_KEY)
        frames = []
        for col, sid in DEFAULT_COST_PROXY_SERIES.items():
            df = fred.fetch_series(sid, start_date=start, refresh=refresh)
            df = df.rename(columns={"value": col}).set_index("date")
            frames.append(df[[col]])
        cost_df = pd.concat(frames, axis=1).sort_index().resample("D").ffill()

        # Equities (historical closes; default: FMP) fetched once
        all_universe = sorted({sym for b in basket_names for sym in BASKETS[b].tickers})
        symbols = sorted(set(all_universe + [benchmark.strip().upper()]))
        px = fetch_equity_daily_closes(settings=settings, symbols=symbols, start=start, refresh=bool(refresh))
        px = px.sort_index().ffill().dropna(how="all")

        tariff_states = []
        for b in basket_names:
            basket = BASKETS[b]
            state = build_tariff_regime_state(
                cost_df=cost_df,
                equity_prices=px,
                universe=basket.tickers,
                benchmark=benchmark,
                basket_name=basket.name,
                start_date=start,
            )
            tariff_states.append(state)
        tariff_vec = tariff_feature_vector(tariff_states, asof=tariff_states[-1].asof if tariff_states else macro_state.asof)

        # Merge into one flat mapping (floats only)
        merged = merge_feature_dicts(
            macro_vec.features,
            liq_vec.features,
            usd_vec.features,
            rates_vec.features,
            vol_vec.features,
            commod_vec.features,
            tariff_vec.features,
        )
        out = {"asof": macro_state.asof, **{k: merged[k] for k in sorted(merged.keys())}}

        if pretty:
            print(json.dumps(out, indent=2, sort_keys=False))
        else:
            print(json.dumps(out, separators=(",", ":"), sort_keys=False))


