from __future__ import annotations

import typer
from rich import print
from rich.panel import Panel

from ai_options_trader.config import load_settings


def run_housing_snapshot(
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
    """Shared implementation for housing snapshot."""
    from ai_options_trader.cli_commands.shared.labs_utils import (
        handle_output_flags, parse_delta_period, show_delta_summary,
        show_alert_output, show_calendar_output, show_trades_output,
        get_delta_metrics,
    )
    from ai_options_trader.housing.signals import build_housing_state
    from ai_options_trader.housing.regime import classify_housing_regime

    settings = load_settings()
    state = build_housing_state(settings=settings, start_date=start, refresh=refresh)
    regime = classify_housing_regime(state.inputs)

    # Build snapshot data
    snapshot_data = {
        "mortgage_30y": state.inputs.mortgage_30y,
        "ust_10y": state.inputs.ust_10y,
        "mortgage_spread": state.inputs.mortgage_spread,
        "z_mortgage_spread": state.inputs.z_mortgage_spread,
        "z_mbs_rel_ret_60d": state.inputs.z_mbs_rel_ret_60d,
        "z_homebuilder_rel_ret_60d": state.inputs.z_homebuilder_rel_ret_60d,
        "z_reit_rel_ret_60d": state.inputs.z_reit_rel_ret_60d,
        "housing_pressure_score": state.inputs.housing_pressure_score,
        "regime": regime.label,
    }

    feature_dict = {
        "mortgage_30y": state.inputs.mortgage_30y,
        "ust_10y": state.inputs.ust_10y,
        "mortgage_spread": state.inputs.mortgage_spread,
        "z_mortgage_spread": state.inputs.z_mortgage_spread,
        "z_mbs_rel_ret_60d": state.inputs.z_mbs_rel_ret_60d,
        "z_homebuilder_rel_ret_60d": state.inputs.z_homebuilder_rel_ret_60d,
        "z_reit_rel_ret_60d": state.inputs.z_reit_rel_ret_60d,
        "housing_pressure_score": state.inputs.housing_pressure_score,
    }

    # Handle --features and --json flags
    if handle_output_flags(
        domain="housing",
        snapshot=snapshot_data,
        features=feature_dict,
        regime=regime.label,
        regime_description=regime.description,
        asof=state.asof,
        output_json=json_out,
        output_features=features,
    ):
        return

    # Handle --alert flag
    if alert:
        show_alert_output("housing", regime.label, snapshot_data, regime.description)
        return

    # Handle --calendar flag
    if calendar:
        print(Panel.fit(f"[b]Regime:[/b] {regime.label}", title="Housing / MBS", border_style="cyan"))
        show_calendar_output("housing")
        return

    # Handle --trades flag
    if trades:
        print(Panel.fit(f"[b]Regime:[/b] {regime.label}", title="Housing / MBS", border_style="cyan"))
        show_trades_output("housing", regime.label)
        return

    # Handle --delta flag
    if delta:
        delta_days = parse_delta_period(delta)
        metric_keys = [
            "Mortgage 30Y:mortgage_30y:%",
            "UST 10Y:ust_10y:%",
            "Mortgage Spread:mortgage_spread:bp",
            "Z Mortgage Spread:z_mortgage_spread:",
            "Housing Pressure:housing_pressure_score:",
        ]
        metrics_for_delta, prev_regime = get_delta_metrics("housing", snapshot_data, metric_keys, delta_days)
        show_delta_summary("housing", regime.label, prev_regime, metrics_for_delta, delta_days)
        return

    # Standard output
    print(
        Panel(
            f"[b]Regime:[/b] {regime.label}\n"
            f"[b]Mortgage 30y:[/b] {state.inputs.mortgage_30y}\n"
            f"[b]UST 10y:[/b] {state.inputs.ust_10y}\n"
            f"[b]Mortgage spread:[/b] {state.inputs.mortgage_spread}\n"
            f"[b]Z mortgage spread:[/b] {state.inputs.z_mortgage_spread}\n"
            f"[b]Z MBS rel (MBB-IEF) 60d:[/b] {state.inputs.z_mbs_rel_ret_60d}\n"
            f"[b]Z Homebuilders rel (ITB-SPY) 60d:[/b] {state.inputs.z_homebuilder_rel_ret_60d}\n"
            f"[b]Z REIT rel (VNQ-SPY) 60d:[/b] {state.inputs.z_reit_rel_ret_60d}\n"
            f"[b]Housing pressure score:[/b] {state.inputs.housing_pressure_score}\n\n"
            f"[dim]{regime.description}[/dim]\n"
            f"[dim]{state.notes}[/dim]",
            title="Housing / MBS snapshot",
            expand=False,
        )
    )

    if llm:
        from ai_options_trader.llm.core.analyst import llm_analyze_regime
        from rich.markdown import Markdown

        print("\n[bold cyan]Generating LLM analysis...[/bold cyan]\n")

        analysis = llm_analyze_regime(
            settings=settings,
            domain="housing",
            snapshot=snapshot_data,
            regime_label=regime.label,
            regime_description=regime.description,
        )

        print(Panel(Markdown(analysis), title="Analysis", expand=False))


def register(housing_app: typer.Typer) -> None:
    # Default callback so `lox labs housing --llm` works without `snapshot`
    @housing_app.callback(invoke_without_command=True)
    def housing_default(
        ctx: typer.Context,
        llm: bool = typer.Option(False, "--llm", help="Get LLM analysis with real-time data"),
        features: bool = typer.Option(False, "--features", help="Export ML-ready feature vector (JSON)"),
        json_out: bool = typer.Option(False, "--json", help="Machine-readable JSON output"),
        delta: str = typer.Option("", "--delta", help="Show changes vs N days ago (e.g., 7d, 1w, 1m)"),
        alert: bool = typer.Option(False, "--alert", help="Only output if regime is extreme (for cron/monitoring)"),
        calendar: bool = typer.Option(False, "--calendar", help="Show upcoming events that could shift this regime"),
        trades: bool = typer.Option(False, "--trades", help="Show quick trade expressions for current regime"),
    ):
        """Housing / MBS regime (mortgage spreads + housing proxies)"""
        if ctx.invoked_subcommand is None:
            run_housing_snapshot(llm=llm, features=features, json_out=json_out, delta=delta, alert=alert, calendar=calendar, trades=trades)

    @housing_app.command("snapshot")
    def snapshot(
        start: str = typer.Option("2011-01-01", "--start"),
        refresh: bool = typer.Option(False, "--refresh"),
        features: bool = typer.Option(False, "--features", help="Export ML-ready feature vector (JSON)"),
        json_out: bool = typer.Option(False, "--json", help="Machine-readable JSON output"),
        delta: str = typer.Option("", "--delta", help="Show changes vs N days ago (e.g., 7d, 1w, 1m)"),
        llm: bool = typer.Option(False, "--llm", help="Get LLM analysis with real-time data"),
        alert: bool = typer.Option(False, "--alert", help="Only output if regime is extreme (for cron/monitoring)"),
        calendar: bool = typer.Option(False, "--calendar", help="Show upcoming events that could shift this regime"),
        trades: bool = typer.Option(False, "--trades", help="Show quick trade expressions for current regime"),
    ):
        """Housing / MBS snapshot: mortgage spread stress + market proxies."""
        run_housing_snapshot(
            start=start, refresh=refresh, features=features, json_out=json_out,
            delta=delta, llm=llm, alert=alert, calendar=calendar, trades=trades,
        )

