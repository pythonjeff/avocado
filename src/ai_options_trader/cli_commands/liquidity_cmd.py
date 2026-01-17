from __future__ import annotations

import typer
from rich import print

from ai_options_trader.config import load_settings


def register(liquidity_app: typer.Typer) -> None:
    @liquidity_app.command("snapshot")
    def liquidity_snapshot(
        start: str = typer.Option("2011-01-01", "--start", help="Start date YYYY-MM-DD"),
        refresh: bool = typer.Option(False, "--refresh", help="Force refresh FRED downloads"),
        features: bool = typer.Option(False, "--features", help="Print ML-friendly scalar feature vector too"),
    ):
        """
        DEPRECATED: Use `lox funding snapshot`.

        This command remains as a backwards-compatible alias.
        """
        from ai_options_trader.cli_commands.funding_cmd import run_funding_snapshot

        run_funding_snapshot(start=start, refresh=bool(refresh), features=bool(features))

    @liquidity_app.command("outlook")
    def liquidity_outlook(
        start: str = typer.Option("2011-01-01", "--start", help="Start date YYYY-MM-DD"),
        refresh: bool = typer.Option(False, "--refresh", help="Force refresh FRED downloads"),
        features: bool = typer.Option(False, "--features", help="Print ML-friendly scalar feature vector too"),
    ):
        """Alias for `snapshot` (back-compat UX)."""
        from ai_options_trader.cli_commands.funding_cmd import run_funding_snapshot

        run_funding_snapshot(start=start, refresh=bool(refresh), features=bool(features))


