from __future__ import annotations

import json

import typer
from rich.console import Console
from rich.panel import Panel

from ai_options_trader.config import load_settings
from ai_options_trader.data.alpaca import make_clients
from ai_options_trader.data.market import fetch_equity_daily_closes
from ai_options_trader.execution.alpaca import submit_equity_order
from ai_options_trader.liquidity.signals import build_liquidity_state
from ai_options_trader.macro.regime import classify_macro_regime_from_state
from ai_options_trader.macro.signals import build_macro_state
from ai_options_trader.portfolio.dataset import build_portfolio_dataset
from ai_options_trader.portfolio.model import build_forecasts, model_debug_report
from ai_options_trader.portfolio.planner import plan_portfolio
from ai_options_trader.portfolio.universe import DEFAULT_UNIVERSE
from ai_options_trader.usd.signals import build_usd_state


def register(app: typer.Typer) -> None:
    @app.command("portfolio")
    def portfolio(
        start: str = typer.Option("2011-01-01", "--start", help="Start date YYYY-MM-DD for price + regime datasets"),
        refresh: bool = typer.Option(False, "--refresh", help="Force refresh FRED downloads (regimes)"),
        max_risk_pct_cash: float = typer.Option(
            0.50, "--max-risk-pct-cash", help="Max fraction of Alpaca cash to deploy (0..1)"
        ),
        execute: bool = typer.Option(False, "--execute", help="Submit PAPER orders (still asks for confirmation)"),
        show_features: bool = typer.Option(False, "--features", help="Print the latest feature vector JSON used for prediction"),
        model_debug: bool = typer.Option(False, "--model-debug", help="Print what the ML models are using (top coefficients)"),
        model_debug_top: int = typer.Option(12, "--model-debug-top", help="How many top +/- coefficients to show per model"),
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
        liq_state = build_liquidity_state(settings=settings, start_date=start, refresh=refresh)
        usd_state = build_usd_state(settings=settings, start_date=start, refresh=refresh)

        # --- Prices for basket + tradables ---
        symbols = sorted(set(DEFAULT_UNIVERSE.tradable))
        px = fetch_equity_daily_closes(
            api_key=settings.alpaca_data_key or settings.alpaca_api_key,
            api_secret=settings.alpaca_data_secret or settings.alpaca_api_secret,
            symbols=symbols,
            start=start,
        )
        latest = px.dropna(how="all").iloc[-1].to_dict()
        latest_prices = {k: float(v) for k, v in latest.items() if v is not None}

        # --- Build dataset + forecasts ---
        ds = build_portfolio_dataset(
            settings=settings,
            equity_prices=px,
            basket_tickers=list(DEFAULT_UNIVERSE.basket_equity),
            start_date=start,
            refresh_fred=refresh,
        )
        forecasts = build_forecasts(ds.X, ds.y)

        if model_debug:
            dbg = model_debug_report(X=ds.X, y_df=ds.y, top_n=int(model_debug_top))
            console.print(Panel(json.dumps(dbg, indent=2, default=str), title="Model debug (coefficients)", expand=False))

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
            lines.append(
                f"- {f.horizon}: P(up)={p:.3f} exp_ret={r:.2f}% auc_cv={(auc if auc is not None else float('nan')):.3f}"
                if (p is not None and r is not None)
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


