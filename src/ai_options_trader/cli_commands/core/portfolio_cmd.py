from __future__ import annotations

import json

import typer
from rich.console import Console
from rich.panel import Panel

from ai_options_trader.config import load_settings
from ai_options_trader.data.alpaca import make_clients
from ai_options_trader.data.market import fetch_equity_daily_closes
from ai_options_trader.execution.alpaca import submit_equity_order
from ai_options_trader.funding.signals import build_funding_state
from ai_options_trader.macro.regime import classify_macro_regime_from_state
from ai_options_trader.macro.signals import build_macro_state
from ai_options_trader.portfolio.dataset import build_portfolio_dataset
from ai_options_trader.portfolio.model import HORIZON_TO_DAYS, build_forecasts, model_debug_report, walk_forward_evaluation
from ai_options_trader.portfolio.planner import plan_portfolio
from ai_options_trader.portfolio.universe import DEFAULT_UNIVERSE, STARTER_UNIVERSE
from ai_options_trader.usd.signals import build_usd_state


def register(app: typer.Typer) -> None:
    @app.command("portfolio")
    def portfolio(
        start: str = typer.Option("2012-01-01", "--start", help="Start date YYYY-MM-DD for price + regime datasets"),
        refresh: bool = typer.Option(False, "--refresh", help="Force refresh FRED downloads (regimes)"),
        universe: str = typer.Option(
            "default",
            "--universe",
            help="Which basket to forecast: default|starter",
        ),
        max_risk_pct_cash: float = typer.Option(
            0.50, "--max-risk-pct-cash", help="Max fraction of Alpaca cash to deploy (0..1)"
        ),
        execute: bool = typer.Option(False, "--execute", help="Submit PAPER orders (still asks for confirmation)"),
        show_features: bool = typer.Option(False, "--features", help="Print the latest feature vector JSON used for prediction"),
        model_debug: bool = typer.Option(False, "--model-debug", help="Print what the ML models are using (top coefficients)"),
        model_debug_top: int = typer.Option(12, "--model-debug-top", help="How many top +/- coefficients to show per model"),
        calibrate: bool = typer.Option(True, "--calibrate/--no-calibrate", help="Calibrate probabilities (recommended)"),
        explain: bool = typer.Option(False, "--explain", help="Explain the latest prediction (feature contributions)"),
        explain_top: int = typer.Option(12, "--explain-top", help="How many top +/- contributions to show"),
    ):
        """
        Build regimes + train a simple ML forecaster + propose a macro-ETF portfolio, then ask permission to execute.

        v1:
        - Equities/ETFs only (no options, no crypto execution)
        - Long-only (risk-off = rotate to defensives + cash)
        - Paper-only execution enforced
        """
        settings = load_settings()
        console = Console()

        u = universe.strip().lower()
        uni = STARTER_UNIVERSE if u.startswith("s") else DEFAULT_UNIVERSE

        if not settings.alpaca_api_key:
            console.print(Panel("[red]Missing Alpaca API keys[/red]", title="Error", expand=False))
            raise typer.Exit(code=1)
        if not settings.fred_api_key:
            console.print(Panel("[red]Missing FRED_API_KEY[/red]", title="Error", expand=False))
            raise typer.Exit(code=1)

        trading, _ = make_clients(settings)
        acct = trading.get_account()
        cash = float(getattr(acct, "cash", 0.0) or 0.0)

        # --- Latest regimes (for qualitative gating + report) ---
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

        # --- Prices for basket + tradables ---
        symbols = sorted(set(uni.tradable))
        px = fetch_equity_daily_closes(settings=settings, symbols=symbols, start=start, refresh=bool(refresh))
        latest = px.dropna(how="all").iloc[-1].to_dict()
        latest_prices = {k: float(v) for k, v in latest.items() if v is not None}

        # --- Build dataset + forecasts ---
        ds = build_portfolio_dataset(
            settings=settings,
            equity_prices=px,
            basket_tickers=list(uni.basket_equity),
            start_date=start,
            refresh_fred=refresh,
        )
        forecasts = build_forecasts(ds.X, ds.y, calibrate=calibrate, calibration_method="sigmoid")

        if model_debug:
            dbg = model_debug_report(X=ds.X, y_df=ds.y, top_n=int(model_debug_top))
            console.print(Panel(json.dumps(dbg, indent=2, default=str), title="Model debug (coefficients)", expand=False))

        if explain:
            # Explain using the fitted (raw) models for each horizon. Calibration affects probabilities,
            # but the directional "drivers" are still best read from the linear coefficients + scaled features.
            from ai_options_trader.portfolio.explain import explain_linear_pipeline
            from ai_options_trader.portfolio.model import fit_models_for_debug, HORIZON_TO_DAYS

            x_last = ds.X.iloc[-1]
            rep = {}
            for h, col in [("3m", "fwd_ret_3m"), ("6m", "fwd_ret_6m"), ("12m", "fwd_ret_12m")]:
                clf, reg, _auc = fit_models_for_debug(X=ds.X, y=ds.y[col].dropna())
                if clf is None or reg is None:
                    rep[h] = {"status": "insufficient_data"}
                    continue
                rep[h] = {
                    "purge_n": int(HORIZON_TO_DAYS[h]),  # type: ignore[index]
                    "classifier": explain_linear_pipeline(pipe=clf, x=x_last, top_n=int(explain_top)),
                    "regressor": explain_linear_pipeline(pipe=reg, x=x_last, top_n=int(explain_top)),
                }
            console.print(Panel(json.dumps(rep, indent=2, default=str), title="Prediction explain (contributions)", expand=False))

        # --- Plan portfolio ---
        plan = plan_portfolio(
            forecasts=forecasts,
            cash_usd=cash,
            max_risk_pct_cash=float(max_risk_pct_cash),
            liquidity_tight=liq_state.inputs.is_liquidity_tight,
            usd_strong=usd_state.inputs.is_usd_strong,
            latest_prices=latest_prices,
        )

        # --- Print report ---
        lines = []
        lines.append(f"Cash available: ${cash:,.2f}")
        lines.append(f"Max risk budget: ${plan.risk_budget_usd:,.2f} ({float(max_risk_pct_cash)*100:.0f}% of cash)")
        lines.append(f"Planned cash deployed: ${plan.risk_used_usd:,.2f}")
        lines.append("")
        lines.append(f"Macro regime: {macro_regime.name} (asof={macro_state.asof})")
        lines.append(f"Liquidity tight: {liq_state.inputs.is_liquidity_tight} (score={liq_state.inputs.liquidity_tightness_score}) asof={liq_state.asof}")
        lines.append(f"USD strong: {usd_state.inputs.is_usd_strong} (score={usd_state.inputs.usd_strength_score}) asof={usd_state.asof}")
        lines.append("")
        lines.append("Model forecasts (basket fwd returns):")
        for f in forecasts:
            p = f.prob_up
            r = f.exp_return
            auc = f.auc_cv
            raw = f.prob_up_raw
            note = f.notes
            lines.append(
                f"- {f.horizon}: P(up)={p:.3f} (raw={raw:.3f}, {note}) exp_ret={r:.2f}% auc_cv={(auc if auc is not None else float('nan')):.3f}"
                if (p is not None and raw is not None and r is not None)
                else f"- {f.horizon}: insufficient data"
            )
        lines.append("")
        lines.append("Planned orders (preview):")
        if not plan.orders:
            lines.append("- (no orders)")
        for o in plan.orders:
            px0 = latest_prices.get(o.symbol)
            est = (float(px0) * o.qty) if px0 else 0.0
            lines.append(f"- {o.side.upper()} {o.qty} {o.symbol} (est=${est:,.2f}, px≈{px0})")
        if plan.notes:
            lines.append("")
            lines.append("Notes:")
            for n in plan.notes:
                lines.append(f"- {n}")

        console.print(Panel("\n".join(lines), title="Lox Portfolio (v1)", expand=False))

        if show_features:
            last_row = ds.X.iloc[-1].to_dict()
            console.print(Panel(json.dumps(last_row, indent=2, default=str), title="Latest feature vector", expand=False))

        # --- Execute (paper-only) ---
        if execute:
            if not settings.alpaca_paper:
                console.print(Panel("[red]Refusing to execute because ALPACA_PAPER is false.[/red]", title="Safety", expand=False))
                raise typer.Exit(code=1)
            if not plan.orders:
                console.print(Panel("No orders to execute.", title="Done", expand=False))
                raise typer.Exit(code=0)
            if not typer.confirm(f"Submit {len(plan.orders)} PAPER equity orders now?", default=False):
                console.print(Panel("Cancelled.", title="Done", expand=False))
                raise typer.Exit(code=0)

            for o in plan.orders:
                if not typer.confirm(f"Submit PAPER order: {o.side} {o.qty} {o.symbol}?", default=False):
                    continue
                submit_equity_order(trading=trading, symbol=o.symbol, qty=o.qty, side=o.side, limit_price=o.limit_price, tif=o.tif)
            console.print(Panel("Submitted selected orders (paper).", title="Done", expand=False))

    @app.command("portfolio-eval")
    def portfolio_eval(
        start: str = typer.Option("2012-01-01", "--start", help="Start date YYYY-MM-DD for price + regime datasets"),
        refresh: bool = typer.Option(False, "--refresh", help="Force refresh FRED downloads (regimes)"),
        splits: int = typer.Option(6, "--splits", help="TimeSeriesSplit folds for walk-forward eval"),
        prob_threshold: float = typer.Option(0.50, "--prob-threshold", help="Classifier threshold for confusion matrix"),
        dump_dataset_summary: bool = typer.Option(True, "--summary/--no-summary", help="Print dataset shape/missingness summary"),
        json_out: bool = typer.Option(False, "--json", help="Print raw JSON output (otherwise print a readable report)"),
        json_plain: bool = typer.Option(False, "--json-plain", help="Print JSON only (no Rich panels/tables; best for redirecting to a file)"),
        calibrate: bool = typer.Option(True, "--calibrate/--no-calibrate", help="Compute calibrated metrics (recommended)"),
    ):
        """
        Offline evaluation of the portfolio ML models (walk-forward, time-series split).

        Prints per-horizon metrics:
        - Classification: AUC / logloss / brier / accuracy / confusion matrix
        - Regression: MAE / RMSE / R2
        """
        settings = load_settings()
        console = Console()

        if not settings.alpaca_api_key:
            console.print(Panel("[red]Missing Alpaca API keys[/red]", title="Error", expand=False))
            raise typer.Exit(code=1)
        if not settings.fred_api_key:
            console.print(Panel("[red]Missing FRED_API_KEY[/red]", title="Error", expand=False))
            raise typer.Exit(code=1)

        symbols = sorted(set(uni.tradable))
        symbols = sorted(set(uni.tradable))
        px = fetch_equity_daily_closes(settings=settings, symbols=symbols, start=start, refresh=bool(refresh))
        ds = build_portfolio_dataset(
            settings=settings,
            equity_prices=px,
            basket_tickers=list(DEFAULT_UNIVERSE.basket_equity),
            start_date=start,
            refresh_fred=refresh,
        )

        if dump_dataset_summary and not json_plain:
            summary = {
                "X_rows": int(ds.X.shape[0]),
                "X_cols": int(ds.X.shape[1]),
                "y_rows": int(ds.y.shape[0]),
                "y_cols": int(ds.y.shape[1]),
                "date_start": str(ds.X.index.min().date()) if len(ds.X.index) else None,
                "date_end": str(ds.X.index.max().date()) if len(ds.X.index) else None,
                "requested_start": start,
            }
            console.print(Panel(json.dumps(summary, indent=2), title="Dataset summary", expand=False))

        out = {}
        out["3m"] = walk_forward_evaluation(
            X=ds.X,
            y=ds.y["fwd_ret_3m"],
            splits=int(splits),
            prob_threshold=float(prob_threshold),
            purge_n=int(HORIZON_TO_DAYS["3m"]),
            calibrate=bool(calibrate),
        )
        out["6m"] = walk_forward_evaluation(
            X=ds.X,
            y=ds.y["fwd_ret_6m"],
            splits=int(splits),
            prob_threshold=float(prob_threshold),
            purge_n=int(HORIZON_TO_DAYS["6m"]),
            calibrate=bool(calibrate),
        )
        out["12m"] = walk_forward_evaluation(
            X=ds.X,
            y=ds.y["fwd_ret_12m"],
            splits=int(splits),
            prob_threshold=float(prob_threshold),
            purge_n=int(HORIZON_TO_DAYS["12m"]),
            calibrate=bool(calibrate),
        )

        if json_plain:
            print(json.dumps(out, indent=2, default=str))
            return

        if json_out:
            console.print(Panel(json.dumps(out, indent=2, default=str), title="Portfolio model eval (JSON)", expand=False))
            return

        from rich.table import Table

        def _get(d: dict, path: str, default=None):
            cur = d
            for part in path.split("."):
                if not isinstance(cur, dict) or part not in cur:
                    return default
                cur = cur[part]
            return cur

        t = Table(title="Portfolio model eval (walk-forward)", show_lines=True)
        t.add_column("Horizon", style="bold")
        t.add_column("n")
        t.add_column("pos_rate")
        t.add_column("AUC raw (fold-wtd)")
        t.add_column("AUC cal (fold-wtd)")
        t.add_column("logloss raw")
        t.add_column("logloss cal")
        t.add_column("logloss baseline")
        t.add_column("brier raw")
        t.add_column("brier cal")
        t.add_column("prob_mean raw")
        t.add_column("prob_mean cal")
        t.add_column("valid_folds")
        t.add_column("acc")
        t.add_column("CM [[tn,fp],[fn,tp]]")
        t.add_column("MAE")
        t.add_column("RMSE")
        t.add_column("R²")

        for h in ("3m", "6m", "12m"):
            d = out[h]
            status = d.get("status")
            if status != "ok":
                t.add_row(h, str(d.get("n", "")), "", "", "", "", "", "", str(status), "", "", "")
                continue
            cm = _get(d, "classification.confusion_matrix", default=None)
            t.add_row(
                h,
                str(d.get("n")),
                f"{_get(d, 'classification.pos_rate', 0.0):.2f}",
                f"{_get(d, 'classification.auc', float('nan')):.3f}",
                f"{_get(d, 'classification.auc_cal', float('nan')):.3f}",
                f"{_get(d, 'classification.logloss', float('nan')):.3f}",
                f"{_get(d, 'classification.logloss_cal', float('nan')):.3f}",
                f"{_get(d, 'classification.baseline_logloss', float('nan')):.3f}",
                f"{_get(d, 'classification.brier', float('nan')):.3f}",
                f"{_get(d, 'classification.brier_cal', float('nan')):.3f}",
                f"{_get(d, 'classification.prob_mean', float('nan')):.3f}",
                f"{_get(d, 'classification.prob_cal_mean', float('nan')):.3f}",
                str(_get(d, "classification.valid_folds", "")),
                f"{_get(d, 'classification.accuracy', float('nan')):.3f}",
                json.dumps(cm),
                f"{_get(d, 'regression.mae', float('nan')):.2f}",
                f"{_get(d, 'regression.rmse', float('nan')):.2f}",
                f"{_get(d, 'regression.r2', float('nan')):.3f}",
            )

        console.print(t)


