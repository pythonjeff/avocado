"""
Model CLI - ML model training, evaluation, and inspection.

Commands:
- predict: Run model on current data
- eval: Walk-forward backtest evaluation
- inspect: View dataset and features

Author: Lox Capital Research
"""
from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ai_options_trader.config import load_settings


def register_model(model_app: typer.Typer) -> None:
    """Register model commands."""
    
    @model_app.command("predict")
    def predict(
        basket: str = typer.Option("starter", "--basket", "-b", help="starter|extended"),
        horizon: int = typer.Option(63, "--horizon", help="Forward horizon (trading days)"),
        top: int = typer.Option(10, "--top", "-n", help="Top predictions to show"),
        explain: bool = typer.Option(False, "--explain", help="Show feature contributions"),
    ):
        """
        Run ML model and show predictions.
        
        Examples:
            lox model predict
            lox model predict --basket extended --top 20
            lox model predict --explain
        """
        console = Console()
        settings = load_settings()
        
        from ai_options_trader.portfolio.universe import get_universe
        from ai_options_trader.data.market import fetch_equity_daily_closes
        from ai_options_trader.regimes.feature_matrix import build_regime_feature_matrix
        from ai_options_trader.portfolio.panel import build_macro_panel_dataset
        from ai_options_trader.portfolio.panel_model import fit_latest_with_models
        
        console.print("[dim]Loading data and fitting model...[/dim]\n")
        
        uni = get_universe(basket)
        tickers = list(uni.basket_equity)
        
        px = fetch_equity_daily_closes(
            settings=settings, symbols=sorted(set(uni.tradable)),
            start="2012-01-01", refresh=False
        ).sort_index().ffill()
        
        Xr = build_regime_feature_matrix(settings=settings, start_date="2012-01-01", refresh_fred=False)
        
        ds = build_macro_panel_dataset(
            regime_features=Xr, prices=px, tickers=tickers,
            horizon_days=horizon, interaction_mode="whitelist", whitelist_extra="none",
        )
        
        preds, meta, clf, reg, Xte = fit_latest_with_models(X=ds.X, y=ds.y)
        
        if meta.get("status") != "ok":
            console.print(f"[red]Model error:[/red] {meta}")
            raise typer.Exit(1)
        
        # Display predictions
        table = Table(title=f"ML Predictions ({horizon}d horizon)")
        table.add_column("Rank", justify="right")
        table.add_column("Ticker", style="bold")
        table.add_column("P(Up)", justify="right")
        table.add_column("Exp Return", justify="right")
        table.add_column("Signal")
        
        for i, p in enumerate(preds[:top], 1):
            signal = "LONG" if (p.exp_return and p.exp_return > 0) else "SHORT"
            signal_style = "green" if signal == "LONG" else "red"
            
            table.add_row(
                str(i),
                p.ticker,
                f"{p.prob_up:.2f}" if p.prob_up else "—",
                f"{p.exp_return:+.1f}%" if p.exp_return else "—",
                f"[{signal_style}]{signal}[/{signal_style}]",
            )
        
        console.print(table)
        console.print(Panel(
            f"Train: {meta.get('train_rows'):,} rows | Test: {meta.get('test_rows')} tickers",
            title="Model Info",
            expand=False,
        ))
        
        # Explain top predictions if requested
        if explain and clf and reg and Xte is not None:
            _explain_predictions(console, preds[:5], reg, Xte)
    
    @model_app.command("eval")
    def eval_cmd(
        basket: str = typer.Option("starter", "--basket", "-b", help="starter|extended"),
        horizon: int = typer.Option(63, "--horizon", help="Forward horizon (trading days)"),
        step: int = typer.Option(5, "--step", help="Evaluate every N days"),
        book: str = typer.Option("longshort", "--book", help="longshort|longonly"),
    ):
        """
        Walk-forward model evaluation (out-of-sample).
        
        Metrics:
        - Spearman correlation (rank accuracy)
        - Hit rate (directional accuracy)
        - Top/bottom spread (long-short returns)
        
        Examples:
            lox model eval
            lox model eval --book longonly
        """
        console = Console()
        settings = load_settings()
        
        from ai_options_trader.portfolio.universe import get_universe
        from ai_options_trader.data.market import fetch_equity_daily_closes
        from ai_options_trader.regimes.feature_matrix import build_regime_feature_matrix
        from ai_options_trader.portfolio.panel import build_macro_panel_dataset
        from ai_options_trader.portfolio.panel_eval import walk_forward_panel_eval, walk_forward_panel_portfolio
        
        console.print("[dim]Running walk-forward evaluation...[/dim]\n")
        
        uni = get_universe(basket)
        tickers = list(uni.basket_equity)
        
        px = fetch_equity_daily_closes(
            settings=settings, symbols=sorted(set(tickers)),
            start="2012-01-01", refresh=False
        ).sort_index().ffill()
        
        Xr = build_regime_feature_matrix(settings=settings, start_date="2012-01-01", refresh_fred=False)
        
        ds = build_macro_panel_dataset(
            regime_features=Xr, prices=px, tickers=tickers,
            horizon_days=horizon, interaction_mode="whitelist", whitelist_extra="none",
        )
        
        res = walk_forward_panel_eval(X=ds.X, y=ds.y, horizon_days=horizon, step_days=step, top_k=3)
        port = walk_forward_panel_portfolio(
            X=ds.X, y=ds.y, horizon_days=horizon, step_days=step,
            top_k=3, tc_bps=5.0, book=book,
        )
        
        ret_col = "long_ret_net" if book == "longonly" else "ls_ret_net"
        
        # Display results
        table = Table(title="Walk-Forward Evaluation")
        table.add_column("Metric", style="bold")
        table.add_column("Value", justify="right")
        
        table.add_row("Dates evaluated", str(res.n_dates))
        table.add_row("Predictions scored", f"{res.n_preds:,}")
        table.add_row("Spearman (mean)", f"{res.spearman_mean:.3f}" if res.spearman_mean else "—")
        table.add_row("Hit rate (mean)", f"{res.hit_rate_mean:.1%}" if res.hit_rate_mean else "—")
        table.add_row("Top-bottom spread", f"{res.top_bottom_spread_mean:.2f}%" if res.top_bottom_spread_mean else "—")
        table.add_row("", "")
        table.add_row("Book type", book)
        table.add_row("Avg return (net)", f"{port[ret_col].mean():.2f}%" if not port.empty else "—")
        
        console.print(table)
        
        # Interpretation
        interpretation = []
        if res.spearman_mean and res.spearman_mean > 0.1:
            interpretation.append("✓ Positive rank correlation — model has predictive signal")
        if res.hit_rate_mean and res.hit_rate_mean > 0.52:
            interpretation.append("✓ Hit rate above 50% — directional accuracy")
        if res.top_bottom_spread_mean and res.top_bottom_spread_mean > 0:
            interpretation.append("✓ Positive spread — long winners beat short losers")
        
        if interpretation:
            console.print(Panel("\n".join(interpretation), title="Interpretation", expand=False))
    
    @model_app.command("inspect")
    def inspect(
        basket: str = typer.Option("starter", "--basket", "-b", help="starter|extended"),
        horizon: int = typer.Option(63, "--horizon", help="Forward horizon (trading days)"),
        rows: int = typer.Option(20, "--rows", "-n", help="Rows to display"),
        export: str = typer.Option("", "--export", help="Export to CSV path"),
    ):
        """
        Inspect the training dataset.
        
        Shows:
        - Dataset dimensions
        - Feature coverage
        - Sample rows
        
        Examples:
            lox model inspect
            lox model inspect --export data/dataset.csv
        """
        console = Console()
        settings = load_settings()
        
        import pandas as pd
        from ai_options_trader.portfolio.universe import get_universe
        from ai_options_trader.data.market import fetch_equity_daily_closes
        from ai_options_trader.regimes.feature_matrix import build_regime_feature_matrix
        from ai_options_trader.portfolio.panel import build_macro_panel_dataset
        
        console.print("[dim]Building dataset...[/dim]\n")
        
        uni = get_universe(basket)
        tickers = list(uni.basket_equity)
        
        px = fetch_equity_daily_closes(
            settings=settings, symbols=sorted(set(tickers)),
            start="2012-01-01", refresh=False
        ).sort_index().ffill()
        
        Xr = build_regime_feature_matrix(settings=settings, start_date="2012-01-01", refresh_fred=False)
        
        ds = build_macro_panel_dataset(
            regime_features=Xr, prices=px, tickers=tickers,
            horizon_days=horizon, interaction_mode="whitelist", whitelist_extra="none",
        )
        
        if ds.X.empty:
            console.print("[yellow]Dataset is empty[/yellow]")
            raise typer.Exit(1)
        
        # Summary
        dates = ds.X.index.get_level_values(0)
        tickers_in_ds = ds.X.index.get_level_values(1)
        
        table = Table(title="Dataset Summary")
        table.add_column("Property", style="bold")
        table.add_column("Value", justify="right")
        
        table.add_row("Total rows", f"{len(ds.X):,}")
        table.add_row("Features", str(ds.X.shape[1]))
        table.add_row("Unique dates", str(len(set(dates))))
        table.add_row("Unique tickers", str(len(set(tickers_in_ds))))
        table.add_row("Date range", f"{pd.to_datetime(dates.min()).date()} to {pd.to_datetime(dates.max()).date()}")
        table.add_row("Horizon (days)", str(horizon))
        
        console.print(table)
        
        # Feature coverage
        coverage = ds.X.notna().mean().sort_values()
        worst = coverage.head(5)
        
        console.print(Panel(
            "\n".join(f"{k}: {v:.1%}" for k, v in worst.items()),
            title="Lowest Feature Coverage",
            expand=False,
        ))
        
        # Sample rows
        joined = ds.X.join(ds.y.rename("y_fwd_ret"), how="inner")
        sample = joined.reset_index().rename(columns={"level_0": "date", "level_1": "ticker"})
        sample = sample.sort_values(["date", "ticker"]).tail(rows)
        
        # Show subset of columns
        cols_to_show = ["date", "ticker", "y_fwd_ret"] + list(ds.X.columns[:5])
        console.print(Panel(
            sample[cols_to_show].to_string(index=False),
            title=f"Sample Rows (last {rows})",
            expand=False,
        ))
        
        # Export
        if export.strip():
            joined.reset_index().to_csv(export.strip(), index=False)
            console.print(f"[green]Exported to {export}[/green]")


def _explain_predictions(console, preds, reg, Xte):
    """Explain top predictions with feature contributions."""
    from ai_options_trader.portfolio.explain import explain_linear_pipeline
    
    console.print("\n[bold]Feature Contributions (top predictions)[/bold]\n")
    
    for p in preds:
        try:
            xrow = Xte.xs(p.ticker, level=1).iloc[0]
            exp = explain_linear_pipeline(pipe=reg, x=xrow, top_n=5)
            
            pos = exp.get("top_positive", [])[:3]
            neg = exp.get("top_negative", [])[:3]
            
            pos_str = ", ".join(f"{x['feature']}: +{x['contribution']:.2f}" for x in pos)
            neg_str = ", ".join(f"{x['feature']}: {x['contribution']:.2f}" for x in neg)
            
            console.print(f"[cyan]{p.ticker}[/cyan] ({p.exp_return:+.1f}%)")
            console.print(f"  + {pos_str}")
            console.print(f"  - {neg_str}")
            console.print()
        except Exception:
            continue
