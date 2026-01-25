from __future__ import annotations

import typer
from rich import print
from rich.panel import Panel

from ai_options_trader.config import load_settings


def run_usd_snapshot(
    *,
    start: str = "2011-01-01",
    refresh: bool = False,
    features: bool = False,
    json_out: bool = False,
    delta: str = "",
    llm: bool = False,
    alert: bool = False,
    calendar: bool = False,
    trades: bool = False,
) -> None:
    """Shared implementation for USD snapshot."""
    from ai_options_trader.cli_commands.shared.labs_utils import (
        handle_output_flags, parse_delta_period, show_delta_summary,
        show_alert_output, show_calendar_output, show_trades_output,
        get_delta_metrics,
    )
    from ai_options_trader.usd.signals import build_usd_state
    from ai_options_trader.usd.features import usd_feature_vector

    settings = load_settings()
    state = build_usd_state(settings=settings, start_date=start, refresh=refresh)

    # Build snapshot data
    snapshot_data = {
        "dxy_level": state.inputs.dxy_level,
        "dxy_ret_60d": state.inputs.dxy_ret_60d,
        "z_dxy_ret_60d": state.inputs.z_dxy_ret_60d,
        "usd_strength_score": state.inputs.usd_strength_score,
        "regime": state.inputs.usd_strength_score,
    }

    vec = usd_feature_vector(state)
    feature_dict = vec.features

    # Handle --features and --json flags
    if handle_output_flags(
        domain="usd",
        snapshot=snapshot_data,
        features=feature_dict,
        regime=f"USD Score: {state.inputs.usd_strength_score:.2f}",
        regime_description=state.notes,
        asof=state.asof,
        output_json=json_out,
        output_features=features,
    ):
        return

    # Handle --alert flag
    if alert:
        show_alert_output("usd", f"USD Score: {state.inputs.usd_strength_score:.2f}", snapshot_data, state.notes)
        return

    # Handle --calendar flag
    if calendar:
        print(Panel.fit(f"[b]USD Strength Score:[/b] {state.inputs.usd_strength_score:.2f}", title="USD", border_style="cyan"))
        show_calendar_output("usd")
        return

    # Handle --trades flag
    if trades:
        print(Panel.fit(f"[b]USD Strength Score:[/b] {state.inputs.usd_strength_score:.2f}", title="USD", border_style="cyan"))
        show_trades_output("usd", "Strong" if state.inputs.usd_strength_score > 0.3 else "Weak" if state.inputs.usd_strength_score < -0.3 else "Neutral")
        return

    # Handle --delta flag
    if delta:
        delta_days = parse_delta_period(delta)
        metric_keys = [
            "DXY Level:dxy_level:",
            "DXY 60d Return:dxy_ret_60d:%",
            "Z DXY 60d:z_dxy_ret_60d:",
            "USD Score:usd_strength_score:",
        ]
        metrics_for_delta, prev_regime = get_delta_metrics("usd", snapshot_data, metric_keys, delta_days)
        show_delta_summary("usd", f"USD Score: {state.inputs.usd_strength_score:.2f}", prev_regime, metrics_for_delta, delta_days)
        return

    # Standard output
    print(state)

    if llm:
        from ai_options_trader.llm.core.analyst import llm_analyze_regime
        from rich.markdown import Markdown

        print("\n[bold cyan]Generating LLM analysis...[/bold cyan]\n")

        analysis = llm_analyze_regime(
            settings=settings,
            domain="usd",
            snapshot=snapshot_data,
            regime_label=f"USD Score: {state.inputs.usd_strength_score:.2f}",
            regime_description=state.notes,
        )

        print(Panel(Markdown(analysis), title="Analysis", expand=False))


def register(usd_app: typer.Typer) -> None:
    # Default callback so `lox labs usd --llm` works without `snapshot`
    @usd_app.callback(invoke_without_command=True)
    def usd_default(
        ctx: typer.Context,
        llm: bool = typer.Option(False, "--llm", help="Get LLM analysis with real-time data"),
        features: bool = typer.Option(False, "--features", help="Export ML-ready feature vector (JSON)"),
        json_out: bool = typer.Option(False, "--json", help="Machine-readable JSON output"),
        delta: str = typer.Option("", "--delta", help="Show changes vs N days ago (e.g., 7d, 1w, 1m)"),
        alert: bool = typer.Option(False, "--alert", help="Only output if regime is extreme (for cron/monitoring)"),
        calendar: bool = typer.Option(False, "--calendar", help="Show upcoming events that could shift this regime"),
        trades: bool = typer.Option(False, "--trades", help="Show quick trade expressions for current regime"),
    ):
        """USD strength/weakness regime"""
        if ctx.invoked_subcommand is None:
            run_usd_snapshot(llm=llm, features=features, json_out=json_out, delta=delta, alert=alert, calendar=calendar, trades=trades)

    @usd_app.command("snapshot")
    def usd_snapshot(
        start: str = typer.Option("2011-01-01", "--start", help="Start date YYYY-MM-DD"),
        refresh: bool = typer.Option(False, "--refresh", help="Force refresh FRED downloads"),
        features: bool = typer.Option(False, "--features", help="Export ML-ready feature vector (JSON)"),
        json_out: bool = typer.Option(False, "--json", help="Machine-readable JSON output"),
        delta: str = typer.Option("", "--delta", help="Show changes vs N days ago (e.g., 7d, 1w, 1m)"),
        llm: bool = typer.Option(False, "--llm", help="Get LLM analysis with real-time data"),
        alert: bool = typer.Option(False, "--alert", help="Only output if regime is extreme (for cron/monitoring)"),
        calendar: bool = typer.Option(False, "--calendar", help="Show upcoming events that could shift this regime"),
        trades: bool = typer.Option(False, "--trades", help="Show quick trade expressions for current regime"),
    ):
        """Compute USD strength/weakness regime snapshot."""
        run_usd_snapshot(
            start=start, refresh=refresh, features=features, json_out=json_out,
            delta=delta, llm=llm, alert=alert, calendar=calendar, trades=trades,
        )

    @usd_app.command("outlook")
    def usd_outlook(
        year: int = typer.Option(2026, "--year", help="Focus year for the outlook (e.g., 2026)"),
        start: str = typer.Option("2011-01-01", "--start", help="Start date YYYY-MM-DD"),
        refresh: bool = typer.Option(False, "--refresh", help="Force refresh FRED downloads"),
        with_context: bool = typer.Option(True, "--with-context/--usd-only", help="Include macro+liquidity context"),
        llm_model: str = typer.Option("", "--llm-model", help="Override OPENAI_MODEL (optional)"),
        llm_temperature: float = typer.Option(0.2, "--llm-temperature", help="LLM temperature (0..2)"),
    ):
        """Ask an LLM for a scenario-style USD outlook (grounded in the USD regime snapshot)."""
        settings = load_settings()

        from ai_options_trader.usd.signals import build_usd_state
        from ai_options_trader.llm.outlooks.usd_outlook import llm_usd_outlook

        usd_state = build_usd_state(settings=settings, start_date=start, refresh=refresh)

        macro_state = None
        liquidity_state = None
        if with_context:
            from ai_options_trader.macro.signals import build_macro_state
            from ai_options_trader.funding.signals import build_funding_state

            macro_state = build_macro_state(settings=settings, start_date=start, refresh=refresh)
            liquidity_state = build_funding_state(settings=settings, start_date=start, refresh=refresh)

        text = llm_usd_outlook(
            settings=settings,
            usd_state=usd_state,
            macro_state=macro_state,
            liquidity_state=liquidity_state,
            year=int(year),
            model=llm_model.strip() or None,
            temperature=float(llm_temperature),
        )
        print(text)


