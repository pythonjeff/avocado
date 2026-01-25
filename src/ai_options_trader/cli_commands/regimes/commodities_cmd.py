from __future__ import annotations

import typer
from rich import print
from rich.panel import Panel


def _run_commodities_snapshot(
    start: str = "2011-01-01",
    refresh: bool = False,
    llm: bool = False,
    features: bool = False,
    json_out: bool = False,
    delta: str = "",
    alert: bool = False,
    calendar: bool = False,
    trades: bool = False,
):
    """Shared implementation for commodities snapshot."""
    import numpy as np
    import pandas as pd
    from rich.console import Console

    from ai_options_trader.config import load_settings
    from ai_options_trader.data.market import fetch_equity_daily_closes
    from ai_options_trader.commodities.signals import build_commodities_state
    from ai_options_trader.commodities.regime import classify_commodities_regime
    from ai_options_trader.cli_commands.shared.labs_utils import (
        handle_output_flags, parse_delta_period, show_delta_summary,
        show_alert_output, show_calendar_output, show_trades_output,
    )

    console = Console()
    settings = load_settings()
    state = build_commodities_state(settings=settings, start_date=start, refresh=refresh)
    regime = classify_commodities_regime(state.inputs)

    # Build snapshot and features
    snapshot_data = {
        "wti": state.inputs.wti,
        "wti_ret_20d_pct": state.inputs.wti_ret_20d_pct,
        "z_wti_ret_20d": state.inputs.z_wti_ret_20d,
        "gold": state.inputs.gold,
        "gold_ret_20d_pct": state.inputs.gold_ret_20d_pct,
        "z_gold_ret_20d": state.inputs.z_gold_ret_20d,
        "copper": state.inputs.copper,
        "copper_ret_60d_pct": state.inputs.copper_ret_60d_pct,
        "z_copper_ret_60d": state.inputs.z_copper_ret_60d,
        "broad_index": state.inputs.broad_index,
        "broad_ret_60d_pct": state.inputs.broad_ret_60d_pct,
        "z_broad_ret_60d": state.inputs.z_broad_ret_60d,
        "commodity_pressure_score": state.inputs.commodity_pressure_score,
        "energy_shock": state.inputs.energy_shock,
        "metals_impulse": state.inputs.metals_impulse,
        "regime": regime.label,
    }

    feature_dict = {
        "wti": state.inputs.wti,
        "wti_ret_20d_pct": state.inputs.wti_ret_20d_pct,
        "z_wti_ret_20d": state.inputs.z_wti_ret_20d,
        "gold": state.inputs.gold,
        "gold_ret_20d_pct": state.inputs.gold_ret_20d_pct,
        "z_gold_ret_20d": state.inputs.z_gold_ret_20d,
        "copper": state.inputs.copper,
        "copper_ret_60d_pct": state.inputs.copper_ret_60d_pct,
        "z_copper_ret_60d": state.inputs.z_copper_ret_60d,
        "broad_index": state.inputs.broad_index,
        "broad_ret_60d_pct": state.inputs.broad_ret_60d_pct,
        "z_broad_ret_60d": state.inputs.z_broad_ret_60d,
        "commodity_pressure_score": state.inputs.commodity_pressure_score,
        "energy_shock": state.inputs.energy_shock,
        "metals_impulse": state.inputs.metals_impulse,
    }

    # Handle --features and --json flags
    if handle_output_flags(
        domain="commodities",
        snapshot=snapshot_data,
        features=feature_dict,
        regime=regime.label,
        regime_description=regime.description,
        asof=state.asof if hasattr(state, 'asof') else None,
        output_json=json_out,
        output_features=features,
    ):
        return

    # Handle --alert flag (silent unless extreme)
    if alert:
        show_alert_output("commodities", regime.label, snapshot_data, regime.description)
        return

    # Handle --calendar flag
    if calendar:
        print(Panel(f"[b]Regime:[/b] {regime.label}", title="Commodities", expand=False))
        show_calendar_output("commodities")
        return

    # Handle --trades flag
    if trades:
        print(Panel(f"[b]Regime:[/b] {regime.label}", title="Commodities", expand=False))
        show_trades_output("commodities", regime.label)
        return

    # Handle --delta flag
    if delta:
        from ai_options_trader.cli_commands.shared.labs_utils import get_delta_metrics
        
        delta_days = parse_delta_period(delta)
        metric_keys = [
            "WTI:wti:$",
            "Gold:gold:$",
            "Copper:copper:$",
            "Broad Index:broad_index:$",
            "Pressure Score:commodity_pressure_score:",
            "WTI 20d%:wti_ret_20d_pct:%",
        ]
        metrics_for_delta, prev_regime = get_delta_metrics("commodities", snapshot_data, metric_keys, delta_days)
        show_delta_summary("commodities", regime.label, prev_regime, metrics_for_delta, delta_days)
        
        if prev_regime is None:
            console.print(f"\n[dim]No cached data from {delta_days}d ago. Run `lox labs commodities` daily to build history.[/dim]")
        return

    # Daily tradable proxies for trend context
    proxy = {
        "Gold (proxy)": "GLDM",
        "Broad commod (proxy)": "DBC",
        "Copper (proxy)": "CPER",
        "Oil (proxy)": "USO",
    }

    trend_lines: list[str] = []
    try:
        px = fetch_equity_daily_closes(settings=settings, symbols=list(proxy.values()), start=start, refresh=bool(refresh))
        px = px.sort_index().ffill()

        def _ret(s: pd.Series, d: int) -> float | None:
            s = pd.to_numeric(s, errors="coerce").dropna()
            if s.shape[0] <= d:
                return None
            v = (s.iloc[-1] / s.iloc[-1 - d] - 1.0) * 100.0
            return float(v) if np.isfinite(v) else None

        def _rv(s: pd.Series, d: int = 20) -> float | None:
            s = pd.to_numeric(s, errors="coerce").dropna()
            if s.shape[0] <= d + 2:
                return None
            r = s.pct_change().dropna()
            v = r.tail(d).std(ddof=0) * np.sqrt(252) * 100.0
            return float(v) if np.isfinite(v) else None

        for label, sym in proxy.items():
            if sym not in px.columns:
                continue
            last = float(pd.to_numeric(px[sym], errors="coerce").dropna().iloc[-1])
            r20 = _ret(px[sym], 20)
            r60 = _ret(px[sym], 60)
            r252 = _ret(px[sym], 252)
            rv20 = _rv(px[sym], 20)
            trend_lines.append(
                f"- [b]{label}[/b] {sym}: px={last:.2f}  20d={r20:+.1f}%  60d={r60:+.1f}%  1y={r252:+.1f}%  rv20≈{(rv20 if rv20 is not None else float('nan')):.1f}%"
            )
    except Exception:
        trend_lines = []

    # Helper for safe float formatting
    def _fmt(v, decimals=2, pct=False):
        if v is None or (isinstance(v, float) and not np.isfinite(v)):
            return "n/a"
        suffix = "%" if pct else ""
        return f"{v:+.{decimals}f}{suffix}" if pct else f"{v:.{decimals}f}{suffix}"

    def _z(v):
        if v is None or (isinstance(v, float) and not np.isfinite(v)):
            return "n/a"
        return f"{v:+.2f}"

    body = (
        f"[b]Regime:[/b] {regime.label}\n"
        f"[b]WTI:[/b] ${_fmt(state.inputs.wti)}  [b]20d:[/b] {_fmt(state.inputs.wti_ret_20d_pct, 1, True)}  [b]z:[/b] {_z(state.inputs.z_wti_ret_20d)}\n"
        f"[b]Gold:[/b] ${_fmt(state.inputs.gold)}  [b]20d:[/b] {_fmt(state.inputs.gold_ret_20d_pct, 1, True)}  [b]z:[/b] {_z(state.inputs.z_gold_ret_20d)}\n"
        f"[b]Copper:[/b] ${_fmt(state.inputs.copper)}  [b]60d:[/b] {_fmt(state.inputs.copper_ret_60d_pct, 1, True)}  [b]z:[/b] {_z(state.inputs.z_copper_ret_60d)}\n"
        f"[b]Broad:[/b] ${_fmt(state.inputs.broad_index)}  [b]60d:[/b] {_fmt(state.inputs.broad_ret_60d_pct, 1, True)}  [b]z:[/b] {_z(state.inputs.z_broad_ret_60d)}\n"
        f"[b]Pressure score:[/b] {_fmt(state.inputs.commodity_pressure_score, 2)} / 1.0\n"
        f"[b]Energy shock:[/b] {'[red]YES[/red]' if state.inputs.energy_shock else '[green]No[/green]'}  "
        f"[b]Metals impulse:[/b] {'[yellow]YES[/yellow]' if state.inputs.metals_impulse else '[green]No[/green]'}\n\n"
    )
    if trend_lines:
        body += "[b]Proxy price trends (daily):[/b]\n" + "\n".join(trend_lines) + "\n\n"
    body += f"[dim]{regime.description}[/dim]"

    print(Panel(body, title="Commodities", expand=False))

    if llm:
        from ai_options_trader.llm.core.analyst import llm_analyze_regime
        from rich.markdown import Markdown
        
        print("\n[bold cyan]Generating LLM analysis...[/bold cyan]\n")
        
        analysis = llm_analyze_regime(
            settings=settings,
            domain="commodities",
            snapshot=snapshot_data,
            regime_label=regime.label,
            regime_description=regime.description,
        )
        
        print(Panel(Markdown(analysis), title="Analysis", expand=False))


def register(commod_app: typer.Typer) -> None:
    # Default callback so `lox labs commodities --llm` works without `snapshot`
    @commod_app.callback(invoke_without_command=True)
    def commodities_default(
        ctx: typer.Context,
        llm: bool = typer.Option(False, "--llm", help="Get PhD-level LLM analysis with real-time data"),
        features: bool = typer.Option(False, "--features", help="Export ML-ready feature vector (JSON)"),
        json_out: bool = typer.Option(False, "--json", help="Machine-readable JSON output"),
        delta: str = typer.Option("", "--delta", help="Show changes vs N days ago (e.g., 7d, 1w, 1m)"),
        alert: bool = typer.Option(False, "--alert", help="Only output if regime is extreme (for cron/monitoring)"),
        calendar: bool = typer.Option(False, "--calendar", help="Show upcoming events that could shift this regime"),
        trades: bool = typer.Option(False, "--trades", help="Show quick trade expressions for current regime"),
    ):
        """Commodities regime (oil/gold/copper/broad index)"""
        if ctx.invoked_subcommand is None:
            _run_commodities_snapshot(llm=llm, features=features, json_out=json_out, delta=delta, alert=alert, calendar=calendar, trades=trades)

    @commod_app.command("snapshot")
    def snapshot(
        start: str = typer.Option("2011-01-01", "--start"),
        refresh: bool = typer.Option(False, "--refresh"),
        llm: bool = typer.Option(False, "--llm", help="Get PhD-level LLM analysis with real-time data"),
        features: bool = typer.Option(False, "--features", help="Export ML-ready feature vector (JSON)"),
        json_out: bool = typer.Option(False, "--json", help="Machine-readable JSON output"),
        delta: str = typer.Option("", "--delta", help="Show changes vs N days ago (e.g., 7d, 1w, 1m)"),
        alert: bool = typer.Option(False, "--alert", help="Only output if regime is extreme (for cron/monitoring)"),
        calendar: bool = typer.Option(False, "--calendar", help="Show upcoming events that could shift this regime"),
        trades: bool = typer.Option(False, "--trades", help="Show quick trade expressions for current regime"),
    ):
        """Commodities snapshot: oil/gold/copper/broad index."""
        _run_commodities_snapshot(start=start, refresh=refresh, llm=llm, features=features, json_out=json_out, delta=delta, alert=alert, calendar=calendar, trades=trades)
