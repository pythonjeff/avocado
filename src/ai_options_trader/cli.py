from __future__ import annotations

import typer

app = typer.Typer(add_completion=False, help="AI Options Trader CLI")
macro_app = typer.Typer(add_completion=False, help="Macro signals and datasets")
app.add_typer(macro_app, name="macro")
tariff_app = typer.Typer(add_completion=False, help="Tariff / cost-push regime signals")
app.add_typer(tariff_app, name="tariff")
liquidity_app = typer.Typer(add_completion=False, help="Liquidity regime (credit + rates)")
app.add_typer(liquidity_app, name="liquidity")
usd_app = typer.Typer(add_completion=False, help="USD strength/weakness regime")
app.add_typer(usd_app, name="usd")
crypto_app = typer.Typer(add_completion=False, help="Crypto snapshots and LLM outlooks")
app.add_typer(crypto_app, name="crypto")
ticker_app = typer.Typer(add_completion=False, help="Ticker snapshots and LLM outlooks")
app.add_typer(ticker_app, name="ticker")
ideas_app = typer.Typer(add_completion=False, help="Trade idea generation from thesis + regimes")
app.add_typer(ideas_app, name="ideas")
track_app = typer.Typer(add_completion=False, help="Track recommendations, executions, and performance")
app.add_typer(track_app, name="track")

_COMMANDS_REGISTERED = False

def _register_commands() -> None:
    global _COMMANDS_REGISTERED
    if _COMMANDS_REGISTERED:
        return
    # Import here to keep `ai_options_trader.cli` lightweight at import time.
    from ai_options_trader.cli_commands.select_cmd import register as register_select
    from ai_options_trader.cli_commands.macro_cmd import register as register_macro
    from ai_options_trader.cli_commands.tariff_cmd import register as register_tariff
    from ai_options_trader.cli_commands.liquidity_cmd import register as register_liquidity
    from ai_options_trader.cli_commands.usd_cmd import register as register_usd
    from ai_options_trader.cli_commands.crypto_cmd import register as register_crypto
    from ai_options_trader.cli_commands.ticker_cmd import register as register_ticker
    from ai_options_trader.cli_commands.regimes_cmd import register as register_regimes
    from ai_options_trader.cli_commands.ideas_cmd import register as register_ideas
    from ai_options_trader.cli_commands.track_cmd import register as register_track

    register_select(app)
    register_macro(macro_app)
    register_tariff(tariff_app)
    register_liquidity(liquidity_app)
    register_usd(usd_app)
    register_crypto(crypto_app)
    register_ticker(ticker_app)
    register_regimes(app)
    register_ideas(ideas_app)
    register_track(track_app)
    _COMMANDS_REGISTERED = True


def main():
    _register_commands()
    app()

# Register commands when imported as a console-script entrypoint (`pyproject.toml` uses `ai_options_trader.cli:app`).
_register_commands()


if __name__ == "__main__":
    main()
