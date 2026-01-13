from __future__ import annotations

import typer
from rich import print
from rich.panel import Panel


def register(housing_app: typer.Typer) -> None:
    @housing_app.command("snapshot")
    def snapshot(
        start: str = typer.Option("2011-01-01", "--start"),
        refresh: bool = typer.Option(False, "--refresh"),
    ):
        """
        Housing / MBS snapshot: mortgage spread stress + market proxies (MBS/homebuilders/REITs relative strength).
        """
        from ai_options_trader.config import load_settings
        from ai_options_trader.housing.signals import build_housing_state
        from ai_options_trader.housing.regime import classify_housing_regime

        settings = load_settings()
        state = build_housing_state(settings=settings, start_date=start, refresh=refresh)
        regime = classify_housing_regime(state.inputs)

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

