from __future__ import annotations

import pandas as pd
import typer
from rich import print
from rich.panel import Panel

from ai_options_trader.config import Settings, load_settings
from ai_options_trader.macro.regime import classify_macro_regime_from_state
from ai_options_trader.macro.signals import build_macro_state


def run_macro_snapshot(
    *,
    start: str = "2011-01-01",
    asof: str = "",
    refresh: bool = False,
    raw: bool = False,
    cpi_target: float = 3.0,
    infl_thresh: float = 0.0,
    real_thresh: float = 0.0,
    features: bool = False,
    json_out: bool = False,
    delta: str = "",
    llm: bool = False,
    alert: bool = False,
    calendar: bool = False,
    trades: bool = False,
) -> None:
    """Shared implementation for macro snapshot."""
    from ai_options_trader.cli_commands.shared.labs_utils import (
        handle_output_flags, parse_delta_period, show_delta_summary,
        show_alert_output, show_calendar_output, show_trades_output,
        get_delta_metrics,
    )

    settings = load_settings()
    if asof.strip():
        from ai_options_trader.macro.signals import build_macro_state_at
        state = build_macro_state_at(settings=settings, start_date=start, refresh=refresh, asof=asof.strip())
    else:
        state = build_macro_state(settings=settings, start_date=start, refresh=refresh)

    regime = classify_macro_regime_from_state(
        cpi_yoy=state.inputs.cpi_yoy,
        payrolls_3m_annualized=state.inputs.payrolls_3m_annualized,
        inflation_momentum_minus_be5y=state.inputs.inflation_momentum_minus_be5y,
        real_yield_proxy_10y=state.inputs.real_yield_proxy_10y,
        z_inflation_momentum_minus_be5y=state.inputs.components.get("z_infl_mom_minus_be5y") if state.inputs.components else None,
        z_real_yield_proxy_10y=state.inputs.components.get("z_real_yield_proxy_10y") if state.inputs.components else None,
        use_zscores=not raw,
        cpi_target=cpi_target,
        infl_thresh=infl_thresh,
        real_thresh=real_thresh,
    )

    # Build snapshot data
    snapshot_data = {
        "cpi_yoy": state.inputs.cpi_yoy,
        "payrolls_3m_annualized": state.inputs.payrolls_3m_annualized,
        "inflation_momentum": state.inputs.inflation_momentum_minus_be5y,
        "real_yield_10y": state.inputs.real_yield_proxy_10y,
        "be5y": state.inputs.breakeven_5y,
        "ust_10y": state.inputs.ust_10y,
        "regime": regime.name,
    }

    # Build features from components
    feature_dict = state.inputs.components or {}

    # Handle --features and --json flags
    if handle_output_flags(
        domain="macro",
        snapshot=snapshot_data,
        features=feature_dict,
        regime=regime.name,
        regime_description=regime.description,
        asof=state.asof,
        output_json=json_out,
        output_features=features,
    ):
        return

    # Handle --alert flag
    if alert:
        show_alert_output("macro", regime.name, snapshot_data, regime.description)
        return

    # Handle --calendar flag
    if calendar:
        print(Panel.fit(f"[b]Regime:[/b] {regime.name}", title="Macro", border_style="cyan"))
        show_calendar_output("macro")
        return

    # Handle --trades flag
    if trades:
        print(Panel.fit(f"[b]Regime:[/b] {regime.name}", title="Macro", border_style="cyan"))
        show_trades_output("macro", regime.name)
        return

    # Handle --delta flag
    if delta:
        delta_days = parse_delta_period(delta)
        metric_keys = [
            "CPI YoY:cpi_yoy:%",
            "Payrolls 3M Ann:payrolls_3m_annualized:k",
            "Inflation Momentum:inflation_momentum:",
            "Real Yield 10Y:real_yield_10y:%",
            "BE 5Y:be5y:%",
        ]
        metrics_for_delta, prev_regime = get_delta_metrics("macro", snapshot_data, metric_keys, delta_days)
        show_delta_summary("macro", regime.name, prev_regime, metrics_for_delta, delta_days)
        return

    # Standard output
    print(state)
    print("\nMACRO REGIME")
    print(regime)

    if llm:
        from ai_options_trader.llm.core.analyst import llm_analyze_regime
        from rich.markdown import Markdown

        print("\n[bold cyan]Generating LLM analysis...[/bold cyan]\n")

        analysis = llm_analyze_regime(
            settings=settings,
            domain="macro",
            snapshot=snapshot_data,
            regime_label=regime.name,
            regime_description=regime.description,
        )

        print(Panel(Markdown(analysis), title="Analysis", expand=False))


def register(macro_app: typer.Typer) -> None:
    # Default callback so `lox labs macro --llm` works without `snapshot`
    @macro_app.callback(invoke_without_command=True)
    def macro_default(
        ctx: typer.Context,
        llm: bool = typer.Option(False, "--llm", help="Get LLM analysis with real-time data"),
        features: bool = typer.Option(False, "--features", help="Export ML-ready feature vector (JSON)"),
        json_out: bool = typer.Option(False, "--json", help="Machine-readable JSON output"),
        delta: str = typer.Option("", "--delta", help="Show changes vs N days ago (e.g., 7d, 1w, 1m)"),
        alert: bool = typer.Option(False, "--alert", help="Only output if regime is extreme (for cron/monitoring)"),
        calendar: bool = typer.Option(False, "--calendar", help="Show upcoming events that could shift this regime"),
        trades: bool = typer.Option(False, "--trades", help="Show quick trade expressions for current regime"),
    ):
        """Macro signals (inflation, growth, rates) and datasets"""
        if ctx.invoked_subcommand is None:
            run_macro_snapshot(llm=llm, features=features, json_out=json_out, delta=delta, alert=alert, calendar=calendar, trades=trades)

    @macro_app.command("snapshot")
    def macro_snapshot(
        start: str = typer.Option("2011-01-01", "--start", help="Start date YYYY-MM-DD"),
        asof: str = typer.Option("", "--asof", help="As-of date YYYY-MM-DD (use last observation on/before this date)"),
        refresh: bool = typer.Option(False, "--refresh", help="Force refresh FRED downloads"),
        raw: bool = typer.Option(False, "--raw", help="Use raw thresholds instead of z-scored thresholds (debug/back-compat)"),
        cpi_target: float = typer.Option(3.0, "--cpi-target", help="Inflation stage threshold for CPI YoY (percent)"),
        infl_thresh: float = typer.Option(0.0, "--infl-thresh", help="Inflation threshold (z units if default mode; raw units if --raw)"),
        real_thresh: float = typer.Option(0.0, "--real-thresh", help="Real-yield threshold (z units if default mode; raw units if --raw)"),
        features: bool = typer.Option(False, "--features", help="Export ML-ready feature vector (JSON)"),
        json_out: bool = typer.Option(False, "--json", help="Machine-readable JSON output"),
        delta: str = typer.Option("", "--delta", help="Show changes vs N days ago (e.g., 7d, 1w, 1m)"),
        llm: bool = typer.Option(False, "--llm", help="Get LLM analysis with real-time data"),
        alert: bool = typer.Option(False, "--alert", help="Only output if regime is extreme (for cron/monitoring)"),
        calendar: bool = typer.Option(False, "--calendar", help="Show upcoming events that could shift this regime"),
        trades: bool = typer.Option(False, "--trades", help="Show quick trade expressions for current regime"),
    ):
        """Print current macro state (inflation + rates + expectations)."""
        run_macro_snapshot(
            start=start, asof=asof, refresh=refresh, raw=raw, cpi_target=cpi_target,
            infl_thresh=infl_thresh, real_thresh=real_thresh,
            features=features, json_out=json_out, delta=delta, llm=llm,
            alert=alert, calendar=calendar, trades=trades,
        )

    @macro_app.command("equity-sensitivity")
    def macro_equity_sensitivity(
        start: str = typer.Option("2011-01-01", "--start", help="Start date YYYY-MM-DD"),
        window: int = typer.Option(252, "--window", help="Rolling window (trading days)"),
        tickers: str = typer.Option("NVDA,AMD,MSFT,GOOGL", "--tickers", help="Comma-separated tickers"),
        benchmark: str = typer.Option("QQQ", "--benchmark", help="Benchmark ticker"),
        refresh: bool = typer.Option(False, "--refresh", help="Force refresh FRED downloads"),
    ):
        """
        Quantify how equities move with rates/inflation expectations.
        """
        from ai_options_trader.macro.signals import build_macro_dataset
        from ai_options_trader.data.market import fetch_equity_daily_closes
        from ai_options_trader.macro.equity import returns, delta, latest_sensitivity_table

        settings = load_settings()

        # Macro dataset for rates/breakevens (daily)
        m = build_macro_dataset(settings=settings, start_date=start, refresh=refresh).set_index("date")

        # Build explanatory daily changes
        d_10y = delta(m["DGS10"]).rename("d_10y")
        d_real = delta(m["REAL_YIELD_PROXY_10Y"]).rename("d_real")
        d_be5 = delta(m["T5YIE"]).rename("d_be5")

        syms = [s.strip().upper() for s in tickers.split(",") if s.strip()]
        syms_all = sorted(set(syms + [benchmark.strip().upper()]))

        px = fetch_equity_daily_closes(settings=settings, symbols=syms_all, start=start, refresh=bool(refresh))
        r = returns(px)

        # Build table
        tbl = latest_sensitivity_table(
            rets=r,
            d_real=d_real,
            d_10y=d_10y,
            d_be5y=d_be5,
            window=window,
        )

        print(tbl)

    @macro_app.command("beta-adjusted-sensitivity")
    def macro_beta_adjusted_sensitivity(
        start: str = typer.Option("2011-01-01", "--start"),
        window: int = typer.Option(252, "--window"),
        tickers: str = typer.Option("NVDA,AMD,MSFT,GOOGL", "--tickers"),
        benchmark: str = typer.Option("QQQ", "--benchmark"),
        refresh: bool = typer.Option(False, "--refresh"),
    ):
        """
        Compute beta-adjusted macro sensitivity for single-name equities.
        """
        from ai_options_trader.macro.signals import build_macro_dataset
        from ai_options_trader.data.market import fetch_equity_daily_closes
        from ai_options_trader.macro.equity import returns, delta
        from ai_options_trader.macro.equity_beta_adjusted import (
            strip_market_beta,
            macro_sensitivity_on_residuals,
        )

        settings = Settings()

        # --- Macro data ---
        macro = build_macro_dataset(
            settings=settings,
            start_date=start,
            refresh=refresh,
        ).set_index("date")

        d_real = delta(macro["REAL_YIELD_PROXY_10Y"])
        d_nominal = delta(macro["DGS10"])
        d_be = delta(macro["T5YIE"])

        macro_changes = (
            pd.concat([d_real, d_nominal, d_be], axis=1)
            .rename(
                columns={
                    "REAL_YIELD_PROXY_10Y": "real",
                    "DGS10": "nominal",
                    "T5YIE": "breakeven",
                }
            )
            .dropna()
        )

        # --- Equity data ---
        syms = [s.strip().upper() for s in tickers.split(",")]
        syms_all = sorted(set(syms + [benchmark]))

        px = fetch_equity_daily_closes(settings=settings, symbols=syms_all, start=start, refresh=bool(refresh))

        r = returns(px)

        tables = []

        for sym in syms:
            resid = strip_market_beta(
                stock_returns=r[sym],
                market_returns=r[benchmark],
                window=window,
            )

            sens = macro_sensitivity_on_residuals(
                residuals=resid.rename(sym),
                macro_changes=macro_changes,
                window=window,
            )

            latest = sens.iloc[-1].to_frame(name=sym)
            tables.append(latest)

        result = pd.concat(tables, axis=1).T
        print(result)


