"""
Ideas CLI - Clean, unified trade idea generation.

Commands:
- catalyst: Event/news driven ideas (FOMC, CPI, earnings)
- screen: ML/kNN ranked tickers across a basket

Author: Lox Capital Research
"""
from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ai_options_trader.config import load_settings


def register_ideas(ideas_app: typer.Typer) -> None:
    """Register clean ideas commands."""
    
    @ideas_app.command("catalyst")
    def catalyst(
        url: str = typer.Option("", "--url", "-u", help="News/article URL"),
        text: str = typer.Option("", "--text", "-t", help="Paste event text directly"),
        thesis: str = typer.Option("", "--thesis", help="Your context/thesis"),
        focus: str = typer.Option("equities", "--focus", "-f", help="equities|treasuries|vol"),
        direction: str = typer.Option("hedge", "--direction", "-d", help="hedge|long|short"),
        count: int = typer.Option(3, "--count", "-n", help="Number of ideas"),
    ):
        """
        Turn news/events into trade ideas.
        
        Examples:
            lox ideas catalyst --url "<cpi_article>" --thesis "inflation sticky"
            lox ideas catalyst --text "FOMC hawkish" --direction hedge
        """
        console = Console()
        settings = load_settings()
        
        if not url.strip() and not text.strip():
            console.print("[red]Provide --url or --text[/red]")
            raise typer.Exit(1)
        
        # Get event text
        if text.strip():
            event_text = text.strip()
        else:
            from ai_options_trader.llm.url_tools import fetch_url_text
            try:
                event_text = fetch_url_text(url.strip())
            except Exception as e:
                console.print(f"[red]Failed to fetch URL:[/red] {e}")
                raise typer.Exit(1)
        
        # Generate ideas via LLM
        from ai_options_trader.llm.event_trade_ideas import llm_event_trade_ideas_json
        from ai_options_trader.portfolio.universe import get_universe
        
        uni = get_universe("starter")
        universe = list(uni.basket_equity)
        
        obj = llm_event_trade_ideas_json(
            settings=settings,
            event_text=event_text,
            event_url=url.strip() or None,
            user_thesis=thesis.strip() or "Generate trade ideas consistent with the event.",
            focus=focus,
            direction=direction,
            universe=universe,
            max_trades=count,
            max_premium_usd=150.0,
            model=None,
            temperature=0.2,
        )
        
        # Display
        trades = obj.get("trades") or []
        if not trades:
            console.print("[yellow]No trade ideas generated[/yellow]")
            return
        
        table = Table(title=f"Catalyst Ideas ({focus} / {direction})")
        table.add_column("#", justify="right")
        table.add_column("Ticker", style="bold")
        table.add_column("Action")
        table.add_column("Rationale")
        
        for i, t in enumerate(trades[:count], 1):
            table.add_row(
                str(i),
                str(t.get("underlying", "")),
                str(t.get("action", "")),
                str(t.get("rationale", ""))[:60],
            )
        
        console.print(table)
        
        # Summary
        summary = obj.get("event_summary") or []
        if summary:
            console.print(Panel(
                "\n".join(f"• {s}" for s in summary[:4]),
                title="Event Summary",
                expand=False,
            ))
    
    @ideas_app.command("screen")
    def screen(
        engine: str = typer.Option("knn", "--engine", "-e", help="knn|ml (kNN regime matching or ML model)"),
        basket: str = typer.Option("starter", "--basket", "-b", help="starter|extended"),
        horizon: int = typer.Option(63, "--horizon", help="Forward horizon in trading days (~63=3M)"),
        top: int = typer.Option(10, "--top", "-n", help="Number of ideas to show"),
        with_options: bool = typer.Option(False, "--with-options", help="Attach option legs"),
        llm: bool = typer.Option(False, "--llm", help="Get LLM review of ideas"),
    ):
        """
        Screen tickers by predicted forward return.
        
        Engines:
            knn: Find similar historical regimes, rank by forward returns
            ml: Cross-sectional ML model predicting 63-day returns
        
        Examples:
            lox ideas screen                      # kNN, starter basket
            lox ideas screen --engine ml          # ML model
            lox ideas screen --with-options       # Include option legs
        """
        console = Console()
        settings = load_settings()
        
        console.print(f"[dim]Running {engine.upper()} screen on {basket} basket...[/dim]\n")
        
        if engine.lower() == "knn":
            _screen_knn(console, settings, basket, horizon, top, with_options, llm)
        else:
            _screen_ml(console, settings, basket, horizon, top, with_options)


def _screen_knn(console, settings, basket, horizon, top, with_options, llm):
    """kNN regime-matching screen."""
    import pandas as pd
    from pathlib import Path
    
    from ai_options_trader.data.market import fetch_equity_daily_closes
    from ai_options_trader.portfolio.universe import get_universe, STARTER_UNIVERSE
    from ai_options_trader.ideas.macro_playbook import rank_macro_playbook
    from ai_options_trader.regimes.feature_matrix import build_regime_feature_matrix
    
    uni = get_universe(basket)
    symbols = sorted(set(uni.basket_equity))
    
    px = fetch_equity_daily_closes(
        settings=settings, symbols=symbols, start="2012-01-01", refresh=False
    ).sort_index().ffill()
    
    # Use cached features if available
    cache_path = Path("data/cache/playbook/regime_features_2012-01-01.csv")
    if cache_path.exists():
        X = pd.read_csv(cache_path, parse_dates=["date"]).set_index("date")
    else:
        X = build_regime_feature_matrix(settings=settings, start_date="2012-01-01", refresh_fred=False)
    
    ideas = rank_macro_playbook(
        features=X,
        prices=px,
        tickers=list(STARTER_UNIVERSE.basket_equity),
        horizon_days=horizon,
        k=250,
        lookback_days=365 * 7,
        min_matches=60,
        asof=pd.to_datetime(X.index.max()),
    )[:top]
    
    # Option legs if requested
    legs = {}
    if with_options and ideas:
        legs = _fetch_option_legs(settings, ideas, "knn")
    
    # Display
    table = Table(title=f"kNN Regime Screen (horizon={horizon}d)")
    table.add_column("Ticker", style="bold")
    table.add_column("Direction")
    table.add_column("Score", justify="right")
    table.add_column("Exp Ret", justify="right")
    table.add_column("Hit Rate", justify="right")
    table.add_column("Matches", justify="right")
    if with_options:
        table.add_column("Option Leg")
    
    for idea in ideas:
        leg = legs.get(idea.ticker)
        row = [
            idea.ticker,
            "UP" if idea.direction == "bullish" else "DOWN",
            f"{idea.score:.2f}",
            f"{idea.exp_return:+.1f}%",
            f"{idea.hit_rate:.0%}",
            str(idea.n_matches),
        ]
        if with_options:
            if leg:
                row.append(f"{leg['symbol']} ${leg['premium_usd']:.0f}")
            else:
                row.append("—")
        table.add_row(*row)
    
    console.print(table)
    
    # LLM review
    if llm:
        _llm_review(console, settings, X, ideas, legs)


def _screen_ml(console, settings, basket, horizon, top, with_options):
    """ML cross-sectional screen."""
    from ai_options_trader.portfolio.universe import get_universe
    from ai_options_trader.data.market import fetch_equity_daily_closes
    from ai_options_trader.regimes.feature_matrix import build_regime_feature_matrix
    from ai_options_trader.portfolio.panel import build_macro_panel_dataset
    from ai_options_trader.portfolio.panel_model import fit_latest_with_models
    
    uni = get_universe(basket)
    tickers = list(uni.basket_equity)
    
    px = fetch_equity_daily_closes(
        settings=settings, symbols=sorted(set(uni.tradable)), start="2012-01-01", refresh=False
    ).sort_index().ffill()
    
    Xr = build_regime_feature_matrix(settings=settings, start_date="2012-01-01", refresh_fred=False)
    
    ds = build_macro_panel_dataset(
        regime_features=Xr,
        prices=px,
        tickers=tickers,
        horizon_days=horizon,
        interaction_mode="whitelist",
        whitelist_extra="none",
    )
    
    preds, meta, _, _, _ = fit_latest_with_models(X=ds.X, y=ds.y)
    
    if meta.get("status") != "ok":
        console.print(f"[red]Model error:[/red] {meta}")
        return
    
    preds = preds[:top]
    
    # Option legs if requested
    legs = {}
    if with_options and preds:
        legs = _fetch_option_legs_ml(settings, preds)
    
    # Display
    table = Table(title=f"ML Screen (horizon={horizon}d)")
    table.add_column("Ticker", style="bold")
    table.add_column("P(Up)", justify="right")
    table.add_column("Exp Ret", justify="right")
    if with_options:
        table.add_column("Option Leg")
    
    for p in preds:
        row = [
            p.ticker,
            f"{p.prob_up:.2f}" if p.prob_up else "—",
            f"{p.exp_return:+.1f}%" if p.exp_return else "—",
        ]
        if with_options:
            leg = legs.get(p.ticker)
            if leg:
                row.append(f"{leg['symbol']} ${leg['premium_usd']:.0f}")
            else:
                row.append("—")
        table.add_row(*row)
    
    console.print(table)
    console.print(Panel(
        f"Train rows: {meta.get('train_rows')} | Test rows: {meta.get('test_rows')}",
        title="Model Info",
        expand=False,
    ))


def _fetch_option_legs(settings, ideas, engine):
    """Fetch affordable option legs for kNN ideas."""
    from ai_options_trader.data.alpaca import make_clients, fetch_option_chain, to_candidates
    from ai_options_trader.options.budget_scan import affordable_options_for_ticker, pick_best_affordable
    
    legs = {}
    _, data = make_clients(settings)
    
    for idea in ideas:
        want = "call" if idea.direction == "bullish" else "put"
        try:
            chain = fetch_option_chain(data, idea.ticker, feed=settings.alpaca_options_feed)
            candidates = list(to_candidates(chain, idea.ticker))
            opts = affordable_options_for_ticker(
                candidates, ticker=idea.ticker, max_premium_usd=100.0,
                min_dte_days=30, max_dte_days=90, want=want,
                price_basis="ask", min_price=0.05, max_spread_pct=0.30,
                require_delta=True,
            )
            best = pick_best_affordable(opts, target_abs_delta=0.30, max_spread_pct=0.30)
            if best:
                legs[idea.ticker] = {
                    "symbol": best.symbol,
                    "type": best.opt_type,
                    "premium_usd": best.premium_usd,
                    "delta": best.delta,
                }
        except Exception:
            continue
    
    return legs


def _fetch_option_legs_ml(settings, preds):
    """Fetch affordable option legs for ML predictions."""
    from ai_options_trader.data.alpaca import make_clients, fetch_option_chain, to_candidates
    from ai_options_trader.options.budget_scan import affordable_options_for_ticker, pick_best_affordable
    
    legs = {}
    _, data = make_clients(settings)
    
    for p in preds:
        want = "call" if (p.exp_return and p.exp_return >= 0) else "put"
        try:
            chain = fetch_option_chain(data, p.ticker, feed=settings.alpaca_options_feed)
            candidates = list(to_candidates(chain, p.ticker))
            opts = affordable_options_for_ticker(
                candidates, ticker=p.ticker, max_premium_usd=100.0,
                min_dte_days=30, max_dte_days=90, want=want,
                price_basis="ask", min_price=0.05, max_spread_pct=0.30,
                require_delta=True,
            )
            best = pick_best_affordable(opts, target_abs_delta=0.30, max_spread_pct=0.30)
            if best:
                legs[p.ticker] = {
                    "symbol": best.symbol,
                    "type": best.opt_type,
                    "premium_usd": best.premium_usd,
                    "delta": best.delta,
                }
        except Exception:
            continue
    
    return legs


def _llm_review(console, settings, X, ideas, legs):
    """LLM review of playbook ideas."""
    import pandas as pd
    from ai_options_trader.llm.macro_playbook_review import llm_macro_playbook_review
    
    asof = str(pd.to_datetime(X.index.max()).date())
    feat_row = X.loc[pd.to_datetime(X.index.max())].to_dict()
    
    ideas_payload = []
    for idea in ideas:
        leg = legs.get(idea.ticker)
        ideas_payload.append({
            "ticker": idea.ticker,
            "direction": idea.direction,
            "horizon_days": idea.horizon_days,
            "n_matches": idea.n_matches,
            "exp_return": idea.exp_return,
            "hit_rate": idea.hit_rate,
            "score": idea.score,
            "option_leg": leg,
        })
    
    text = llm_macro_playbook_review(
        settings=settings,
        asof=asof,
        regime_features=feat_row,
        playbook_ideas=ideas_payload,
        positions=None,
        account=None,
        model=None,
        temperature=0.2,
    )
    
    console.print(Panel(text, title="LLM Review", expand=False))
