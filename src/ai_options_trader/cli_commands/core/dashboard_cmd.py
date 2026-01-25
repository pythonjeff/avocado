"""
Dashboard CLI Command - Unified regime dashboard.

Usage:
    lox dashboard                    # Full dashboard
    lox dashboard --focus inflation  # Deep-dive into inflation
    lox dashboard --features         # Export ML features
    lox dashboard --json             # JSON output

Author: Lox Capital Research
"""
from __future__ import annotations

import json
from typing import Optional

import typer
from rich.console import Console

from ai_options_trader.config import load_settings


def register(app: typer.Typer) -> None:
    """Register dashboard commands."""
    
    @app.command("dashboard")
    def dashboard(
        focus: Optional[str] = typer.Option(
            None, "--focus", "-f",
            help="Deep-dive into specific pillar: inflation|growth|liquidity|volatility"
        ),
        features: bool = typer.Option(
            False, "--features",
            help="Output ML features as JSON"
        ),
        output_json: bool = typer.Option(
            False, "--json",
            help="Output full dashboard as JSON"
        ),
    ):
        """
        Unified regime dashboard - all economic factors at a glance.
        
        Shows:
        - Inflation (CPI, breakevens, stickiness)
        - Growth (payrolls, unemployment, claims)
        - Liquidity (Fed balance sheet, funding rates)
        - Volatility (VIX, term structure)
        
        Examples:
            lox dashboard                     # Full summary
            lox dashboard --focus inflation   # Inflation deep-dive
            lox dashboard --focus liquidity   # Liquidity deep-dive
            lox dashboard --features          # ML features JSON
        """
        console = Console()
        settings = load_settings()
        
        # Create and compute dashboard
        from ai_options_trader.regimes.dashboard import create_default_dashboard
        
        console.print("[dim]Loading regime data...[/dim]\n")
        
        dash = create_default_dashboard()
        dash.compute_all(settings)
        
        # Output modes
        if features:
            feature_dict = dash.to_features()
            console.print(json.dumps(feature_dict, indent=2, default=str))
            return
        
        if output_json:
            output = {
                "asof": dash.asof.isoformat() if dash.asof else None,
                "overall_regime": dash.overall_regime(),
                "pillars": {},
            }
            for name, pillar in dash.pillars.items():
                output["pillars"][name] = {
                    "regime": pillar.regime,
                    "score": pillar.composite_score,
                    "metrics": {m.name: m.value for m in pillar.metrics},
                }
            console.print(json.dumps(output, indent=2, default=str))
            return
        
        # Visual dashboard
        dash.render(console, focus=focus)
        
        # Tips
        console.print("\n[dim]Deep-dive: lox dashboard --focus <pillar>[/dim]")
        console.print("[dim]ML features: lox dashboard --features[/dim]")


def register_pillar_commands(app: typer.Typer) -> None:
    """Register individual pillar commands for quick access."""
    
    def _run_llm_analysis(settings, domain: str, snapshot: dict, regime_label: str, regime_description: str, console: Console):
        """Shared LLM analysis runner."""
        from ai_options_trader.llm.core.analyst import llm_analyze_regime
        from rich.markdown import Markdown
        from rich.panel import Panel
        
        console.print("\n[bold cyan]Generating LLM analysis...[/bold cyan]\n")
        
        analysis = llm_analyze_regime(
            settings=settings,
            domain=domain,
            snapshot=snapshot,
            regime_label=regime_label,
            regime_description=regime_description,
        )
        
        console.print(Panel(Markdown(analysis), title="Analysis", expand=False))
    
    @app.command("inflation")
    def inflation_cmd(
        llm: bool = typer.Option(False, "--llm", help="Get PhD-level LLM analysis with real-time data"),
        features: bool = typer.Option(False, "--features", help="Export ML-ready feature vector (JSON)"),
        json_out: bool = typer.Option(False, "--json", help="Machine-readable JSON output"),
        delta: str = typer.Option("", "--delta", help="Show changes vs N days ago (e.g., 7d, 1w, 1m)"),
        alert: bool = typer.Option(False, "--alert", help="Only output if regime is extreme (for cron/monitoring)"),
        calendar: bool = typer.Option(False, "--calendar", help="Show upcoming events that could shift this regime"),
        trades: bool = typer.Option(False, "--trades", help="Show quick trade expressions for current regime"),
    ):
        """Quick inflation regime view."""
        from rich.panel import Panel
        from ai_options_trader.cli_commands.shared.labs_utils import (
            handle_output_flags, parse_delta_period, show_delta_summary,
            show_alert_output, show_calendar_output, show_trades_output,
        )
        
        console = Console()
        settings = load_settings()
        
        from ai_options_trader.regimes.pillars import InflationPillar
        
        pillar = InflationPillar()
        pillar.compute(settings)
        
        # Build snapshot and features
        snapshot = {m.name: m.value for m in pillar.metrics}
        snapshot["composite_score"] = pillar.composite_score
        snapshot["regime"] = pillar.regime
        
        feature_dict = {m.name.lower().replace(" ", "_"): m.value for m in pillar.metrics}
        feature_dict["composite_score"] = pillar.composite_score
        
        # Handle --features and --json flags
        if handle_output_flags(
            domain="inflation",
            snapshot=snapshot,
            features=feature_dict,
            regime=pillar.regime or "unknown",
            regime_description=pillar._interpret(),
            output_json=json_out,
            output_features=features,
        ):
            return
        
        # Handle --alert flag (silent unless extreme)
        if alert:
            show_alert_output("inflation", pillar.regime or "unknown", snapshot, pillar._interpret())
            return
        
        # Handle --calendar flag
        if calendar:
            console.print(Panel(f"[b]Regime:[/b] {pillar.regime}", title="Inflation", expand=False))
            show_calendar_output("inflation")
            return
        
        # Handle --trades flag
        if trades:
            console.print(Panel(f"[b]Regime:[/b] {pillar.regime}", title="Inflation", expand=False))
            show_trades_output("inflation", pillar.regime or "unknown")
            return
        
        # Handle --delta flag
        if delta:
            from ai_options_trader.cli_commands.shared.labs_utils import get_delta_metrics
            
            delta_days = parse_delta_period(delta)
            # Build metric keys from pillar metrics
            metric_keys = [f"{m.name}:{m.name.lower().replace(' ', '_')}:{m.unit}" for m in pillar.metrics]
            metric_keys.append("Score:composite_score:")
            metrics_for_delta, prev_regime = get_delta_metrics("inflation", snapshot, metric_keys, delta_days)
            show_delta_summary("inflation", pillar.regime or "unknown", prev_regime, metrics_for_delta, delta_days)
            
            if prev_regime is None:
                console.print(f"\n[dim]No cached data from {delta_days}d ago. Run `lox labs inflation` daily to build history.[/dim]")
            return
        
        # Standard panel output
        metrics_lines = []
        for m in pillar.metrics:
            delta_str = f" ({m.format_delta('3m')} 3m)" if m.delta_3m else ""
            metrics_lines.append(f"  {m.name}: [bold]{m.format_value()}[/bold]{delta_str}")
        
        body = "\n".join([
            f"[b]Regime:[/b] {pillar.regime}",
            f"[b]Score:[/b] {pillar.composite_score:.0f}/100" if pillar.composite_score else "",
            "",
            *metrics_lines,
            "",
            f"[dim]{pillar._interpret()}[/dim]",
        ])
        console.print(Panel(body, title="Inflation", expand=False))
        
        if llm:
            _run_llm_analysis(settings, "inflation", snapshot, pillar.regime or "unknown", pillar._interpret(), console)
    
    @app.command("growth")
    def growth_cmd(
        llm: bool = typer.Option(False, "--llm", help="Get PhD-level LLM analysis with real-time data"),
        features: bool = typer.Option(False, "--features", help="Export ML-ready feature vector (JSON)"),
        json_out: bool = typer.Option(False, "--json", help="Machine-readable JSON output"),
        delta: str = typer.Option("", "--delta", help="Show changes vs N days ago (e.g., 7d, 1w, 1m)"),
        alert: bool = typer.Option(False, "--alert", help="Only output if regime is extreme (for cron/monitoring)"),
        calendar: bool = typer.Option(False, "--calendar", help="Show upcoming events that could shift this regime"),
        trades: bool = typer.Option(False, "--trades", help="Show quick trade expressions for current regime"),
    ):
        """Quick growth regime view."""
        from rich.panel import Panel
        from ai_options_trader.cli_commands.shared.labs_utils import (
            handle_output_flags, parse_delta_period, show_delta_summary,
            show_alert_output, show_calendar_output, show_trades_output,
        )
        
        console = Console()
        settings = load_settings()
        
        from ai_options_trader.regimes.pillars import GrowthPillar
        
        pillar = GrowthPillar()
        pillar.compute(settings)
        
        # Build snapshot and features
        snapshot = {m.name: m.value for m in pillar.metrics}
        snapshot["composite_score"] = pillar.composite_score
        snapshot["regime"] = pillar.regime
        
        feature_dict = {m.name.lower().replace(" ", "_"): m.value for m in pillar.metrics}
        feature_dict["composite_score"] = pillar.composite_score
        
        # Handle --features and --json flags
        if handle_output_flags(
            domain="growth",
            snapshot=snapshot,
            features=feature_dict,
            regime=pillar.regime or "unknown",
            regime_description=pillar._interpret(),
            output_json=json_out,
            output_features=features,
        ):
            return
        
        # Handle --alert flag (silent unless extreme)
        if alert:
            show_alert_output("growth", pillar.regime or "unknown", snapshot, pillar._interpret())
            return
        
        # Handle --calendar flag
        if calendar:
            console.print(Panel(f"[b]Regime:[/b] {pillar.regime}", title="Growth", expand=False))
            show_calendar_output("growth")
            return
        
        # Handle --trades flag
        if trades:
            console.print(Panel(f"[b]Regime:[/b] {pillar.regime}", title="Growth", expand=False))
            show_trades_output("growth", pillar.regime or "unknown")
            return
        
        # Handle --delta flag
        if delta:
            from ai_options_trader.cli_commands.shared.labs_utils import get_delta_metrics
            
            delta_days = parse_delta_period(delta)
            metric_keys = [f"{m.name}:{m.name.lower().replace(' ', '_')}:{m.unit}" for m in pillar.metrics]
            metric_keys.append("Score:composite_score:")
            metrics_for_delta, prev_regime = get_delta_metrics("growth", snapshot, metric_keys, delta_days)
            show_delta_summary("growth", pillar.regime or "unknown", prev_regime, metrics_for_delta, delta_days)
            
            if prev_regime is None:
                console.print(f"\n[dim]No cached data from {delta_days}d ago. Run `lox labs growth` daily to build history.[/dim]")
            return
        
        # Standard panel output
        metrics_lines = [f"  {m.name}: [bold]{m.format_value()}[/bold]" for m in pillar.metrics]
        
        body = "\n".join([
            f"[b]Regime:[/b] {pillar.regime}",
            f"[b]Score:[/b] {pillar.composite_score:.0f}/100" if pillar.composite_score else "",
            "",
            *metrics_lines,
            "",
            f"[dim]{pillar._interpret()}[/dim]",
        ])
        console.print(Panel(body, title="Growth", expand=False))
        
        if llm:
            _run_llm_analysis(settings, "growth", snapshot, pillar.regime or "unknown", pillar._interpret(), console)
    
    @app.command("liquidity")
    def liquidity_cmd(
        llm: bool = typer.Option(False, "--llm", help="Get PhD-level LLM analysis with real-time data"),
        features: bool = typer.Option(False, "--features", help="Export ML-ready feature vector (JSON)"),
        json_out: bool = typer.Option(False, "--json", help="Machine-readable JSON output"),
        delta: str = typer.Option("", "--delta", help="Show changes vs N days ago (e.g., 7d, 1w, 1m)"),
        alert: bool = typer.Option(False, "--alert", help="Only output if regime is extreme (for cron/monitoring)"),
        calendar: bool = typer.Option(False, "--calendar", help="Show upcoming events that could shift this regime"),
        trades: bool = typer.Option(False, "--trades", help="Show quick trade expressions for current regime"),
    ):
        """Quick liquidity regime view."""
        from rich.panel import Panel
        from ai_options_trader.cli_commands.shared.labs_utils import (
            handle_output_flags, parse_delta_period, show_delta_summary,
            show_alert_output, show_calendar_output, show_trades_output,
        )
        
        console = Console()
        settings = load_settings()
        
        from ai_options_trader.regimes.pillars import LiquidityPillar
        
        pillar = LiquidityPillar()
        pillar.compute(settings)
        
        # Build snapshot and features
        snapshot = {m.name: m.value for m in pillar.metrics}
        snapshot["composite_score"] = pillar.composite_score
        snapshot["buffer_status"] = pillar.buffer_status()
        snapshot["regime"] = pillar.regime
        
        feature_dict = {m.name.lower().replace(" ", "_"): m.value for m in pillar.metrics}
        feature_dict["composite_score"] = pillar.composite_score
        
        # Handle --features and --json flags
        if handle_output_flags(
            domain="liquidity",
            snapshot=snapshot,
            features=feature_dict,
            regime=pillar.regime or "unknown",
            regime_description=pillar._interpret(),
            output_json=json_out,
            output_features=features,
        ):
            return
        
        # Handle --alert flag (silent unless extreme)
        if alert:
            show_alert_output("liquidity", pillar.regime or "unknown", snapshot, pillar._interpret())
            return
        
        # Handle --calendar flag
        if calendar:
            console.print(Panel(f"[b]Regime:[/b] {pillar.regime}", title="Liquidity", expand=False))
            show_calendar_output("liquidity")
            return
        
        # Handle --trades flag
        if trades:
            console.print(Panel(f"[b]Regime:[/b] {pillar.regime}", title="Liquidity", expand=False))
            show_trades_output("liquidity", pillar.regime or "unknown")
            return
        
        # Handle --delta flag
        if delta:
            from ai_options_trader.cli_commands.shared.labs_utils import get_delta_metrics
            
            delta_days = parse_delta_period(delta)
            metric_keys = [f"{m.name}:{m.name.lower().replace(' ', '_')}:{m.unit}" for m in pillar.metrics]
            metric_keys.append("Score:composite_score:")
            metrics_for_delta, prev_regime = get_delta_metrics("liquidity", snapshot, metric_keys, delta_days)
            show_delta_summary("liquidity", pillar.regime or "unknown", prev_regime, metrics_for_delta, delta_days)
            
            if prev_regime is None:
                console.print(f"\n[dim]No cached data from {delta_days}d ago. Run `lox labs liquidity` daily to build history.[/dim]")
            return
        
        # Standard panel output
        metrics_lines = []
        for m in pillar.metrics:
            delta_str = f" ({m.format_delta('1m')} 1m)" if m.delta_1m else ""
            metrics_lines.append(f"  {m.name}: [bold]{m.format_value()}[/bold]{delta_str}")
        
        triggers = pillar._triggers() if hasattr(pillar, "_triggers") else []
        trigger_line = f"\n[yellow]Triggers: {', '.join(triggers)}[/yellow]" if triggers else ""
        
        body = "\n".join([
            f"[b]Regime:[/b] {pillar.regime}",
            f"[b]Score:[/b] {pillar.composite_score:.0f}/100" if pillar.composite_score else "",
            f"[b]Buffer:[/b] {pillar.buffer_status()}",
            "",
            *metrics_lines,
            trigger_line,
            "",
            f"[dim]{pillar._interpret()}[/dim]",
        ])
        console.print(Panel(body, title="Liquidity", expand=False))
        
        if llm:
            _run_llm_analysis(settings, "liquidity", snapshot, pillar.regime or "unknown", pillar._interpret(), console)
    
    @app.command("vol")
    def vol_cmd(
        llm: bool = typer.Option(False, "--llm", help="Get PhD-level LLM analysis with real-time data"),
        features: bool = typer.Option(False, "--features", help="Export ML-ready feature vector (JSON)"),
        json_out: bool = typer.Option(False, "--json", help="Machine-readable JSON output"),
        delta: str = typer.Option("", "--delta", help="Show changes vs N days ago (e.g., 7d, 1w, 1m)"),
        alert: bool = typer.Option(False, "--alert", help="Only output if regime is extreme (for cron/monitoring)"),
        calendar: bool = typer.Option(False, "--calendar", help="Show upcoming events that could shift this regime"),
        trades: bool = typer.Option(False, "--trades", help="Show quick trade expressions for current regime"),
    ):
        """Quick volatility regime view (VIX level, term structure, percentile)."""
        from rich.panel import Panel
        from ai_options_trader.cli_commands.shared.labs_utils import (
            handle_output_flags, parse_delta_period, show_delta_summary,
            show_alert_output, show_calendar_output, show_trades_output,
        )
        
        console = Console()
        settings = load_settings()
        
        from ai_options_trader.regimes.pillars import VolatilityPillar
        
        pillar = VolatilityPillar()
        pillar.compute(settings)
        
        # Build snapshot and features
        snapshot = {m.name: m.value for m in pillar.metrics}
        snapshot["composite_score"] = pillar.composite_score
        snapshot["term_structure"] = pillar.term_structure_status()
        snapshot["regime"] = pillar.regime
        # Add VIX to snapshot with standard key for alert thresholds
        snapshot["VIX"] = next((m.value for m in pillar.metrics if m.name == "VIX"), None)
        
        feature_dict = {m.name.lower().replace(" ", "_"): m.value for m in pillar.metrics}
        feature_dict["composite_score"] = pillar.composite_score
        feature_dict["vix_percentile"] = next((m.percentile for m in pillar.metrics if m.name == "VIX"), None)
        
        # Handle --features and --json flags
        if handle_output_flags(
            domain="volatility",
            snapshot=snapshot,
            features=feature_dict,
            regime=pillar.regime or "unknown",
            regime_description=pillar._interpret(),
            output_json=json_out,
            output_features=features,
        ):
            return
        
        # Handle --alert flag (silent unless extreme)
        if alert:
            show_alert_output("volatility", pillar.regime or "unknown", snapshot, pillar._interpret())
            return
        
        # Handle --calendar flag
        if calendar:
            console.print(Panel(f"[b]Regime:[/b] {pillar.regime}", title="Volatility", expand=False))
            show_calendar_output("volatility")
            return
        
        # Handle --trades flag
        if trades:
            console.print(Panel(f"[b]Regime:[/b] {pillar.regime}", title="Volatility", expand=False))
            show_trades_output("volatility", pillar.regime or "unknown")
            return
        
        # Handle --delta flag
        if delta:
            from ai_options_trader.cli_commands.shared.labs_utils import get_delta_metrics
            
            delta_days = parse_delta_period(delta)
            # Keys must match snapshot keys exactly (with spaces/caps)
            metric_keys = [
                "VIX:VIX:",
                "VIX %ile:VIX Percentile:%",
                "VIX 3M:VIX 3M:",
                "Term Struct:VIX Term Structure:",
                "Score:composite_score:",
            ]
            metrics_for_delta, prev_regime = get_delta_metrics("volatility", snapshot, metric_keys, delta_days)
            show_delta_summary("volatility", pillar.regime or "unknown", prev_regime, metrics_for_delta, delta_days)
            
            if prev_regime is None:
                console.print(f"\n[dim]No cached data from {delta_days}d ago. Run `lox labs vol` daily to build history.[/dim]")
            return
        
        # Build metrics lines
        metrics_lines = []
        for m in pillar.metrics:
            pct = f" ({m.percentile:.0f}%ile)" if m.percentile else ""
            metrics_lines.append(f"  {m.name}: [bold]{m.format_value()}[/bold]{pct}")
        
        # Build implications
        implications = pillar._trade_implications() if hasattr(pillar, "_trade_implications") else []
        impl_lines = [f"  • {impl}" for impl in implications] if implications else []
        
        body_parts = [
            f"[b]Regime:[/b] {pillar.regime}",
            f"[b]Score:[/b] {pillar.composite_score:.0f}/100" if pillar.composite_score else "",
            f"[b]Term Structure:[/b] {pillar.term_structure_status()}",
            "",
            *metrics_lines,
        ]
        if impl_lines:
            body_parts.extend(["", "[dim]Trade implications:[/dim]", *impl_lines])
        body_parts.extend(["", f"[dim]{pillar._interpret()}[/dim]"])
        
        body = "\n".join([l for l in body_parts if l or l == ""])
        console.print(Panel(body, title="Volatility", expand=False))
        
        if llm:
            _run_llm_analysis(settings, "volatility", snapshot, pillar.regime or "unknown", pillar._interpret(), console)
