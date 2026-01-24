from __future__ import annotations

import typer

app = typer.Typer(add_completion=False, help="AI Options Trader CLI")

# ---------------------------------------------------------------------------
# "Institutional" CLI surface (intentionally small)
# ---------------------------------------------------------------------------
autopilot_app = typer.Typer(add_completion=False, help="Autopilot (run-once workflow)")
app.add_typer(autopilot_app, name="autopilot")
nav_app = typer.Typer(add_completion=False, help="NAV sheet + investor ledger (fund accounting)")
app.add_typer(nav_app, name="nav")
options_app = typer.Typer(add_completion=False, help="Options scanners (moonshot + helpers)")
app.add_typer(options_app, name="options")
ideas_app = typer.Typer(add_completion=False, help="Trade ideas (catalyst + screen)")
app.add_typer(ideas_app, name="ideas")
model_app = typer.Typer(add_completion=False, help="ML model (predict/eval/inspect)")
app.add_typer(model_app, name="model")
live_app = typer.Typer(add_completion=False, help="Live console (interactive monitoring + manual crypto execution)")
app.add_typer(live_app, name="live")
weekly_app = typer.Typer(add_completion=False, help="Weekly report")
app.add_typer(weekly_app, name="weekly")

# Chat - interactive research conversations
from ai_options_trader.cli_commands.chat_cmd import app as chat_app
app.add_typer(chat_app, name="chat")

# ---------------------------------------------------------------------------
# Power-user tools tucked under `lox labs ...` so `lox --help` stays clean
# ---------------------------------------------------------------------------
labs_app = typer.Typer(add_completion=False, help="Labs (power-user regime datasets, diagnostics, legacy tools)")
app.add_typer(labs_app, name="labs")
macro_app = typer.Typer(add_completion=False, help="Macro signals and datasets")
labs_app.add_typer(macro_app, name="macro")
tariff_app = typer.Typer(add_completion=False, help="Tariff / cost-push regime signals")
labs_app.add_typer(tariff_app, name="tariff")
funding_app = typer.Typer(add_completion=False, help="Funding markets (SOFR, repo spreads) — price of money in daily markets")
labs_app.add_typer(funding_app, name="funding")
# Back-compat alias; keep it in labs to avoid clutter.
liquidity_app = typer.Typer(add_completion=False, help="(deprecated) Alias for funding regime")
labs_app.add_typer(liquidity_app, name="liquidity")
usd_app = typer.Typer(add_completion=False, help="USD strength/weakness regime")
labs_app.add_typer(usd_app, name="usd")
monetary_app = typer.Typer(add_completion=False, help="Fed liquidity (reserves, balance sheet, RRP) — quantity of money in system")
labs_app.add_typer(monetary_app, name="monetary")
rates_app = typer.Typer(add_completion=False, help="Rates / yield curve regime (UST level/slope/momentum)")
labs_app.add_typer(rates_app, name="rates")
fiscal_app = typer.Typer(add_completion=False, help="US fiscal regime (deficits, issuance mix, auctions, TGA)")
labs_app.add_typer(fiscal_app, name="fiscal")
vol_app = typer.Typer(add_completion=False, help="Volatility regime (VIX: level/momentum/term structure)")
labs_app.add_typer(vol_app, name="volatility")
commod_app = typer.Typer(add_completion=False, help="Commodities regime (oil/gold/broad index)")
labs_app.add_typer(commod_app, name="commodities")
crypto_app = typer.Typer(add_completion=False, help="Crypto snapshots and LLM outlooks")
labs_app.add_typer(crypto_app, name="crypto")
ticker_app = typer.Typer(add_completion=False, help="Ticker snapshots and LLM outlooks")
labs_app.add_typer(ticker_app, name="ticker")
housing_app = typer.Typer(add_completion=False, help="Housing / MBS regime (mortgage spreads + housing proxies)")
labs_app.add_typer(housing_app, name="housing")
solar_app = typer.Typer(add_completion=False, help="Solar / silver regime (solar basket vs SLV)")
labs_app.add_typer(solar_app, name="solar")
track_app = typer.Typer(add_completion=False, help="Track recommendations, executions, and performance")
labs_app.add_typer(track_app, name="track")

_COMMANDS_REGISTERED = False

def _register_commands() -> None:
    global _COMMANDS_REGISTERED
    if _COMMANDS_REGISTERED:
        return
    # Import here to keep `ai_options_trader.cli` lightweight at import time.
    from ai_options_trader.cli_commands.select_cmd import register as register_select
    from ai_options_trader.cli_commands.macro_cmd import register as register_macro
    from ai_options_trader.cli_commands.tariff_cmd import register as register_tariff
    from ai_options_trader.cli_commands.options_cmd import register as register_options
    from ai_options_trader.cli_commands.options_pick_cmd import register_pick
    from ai_options_trader.cli_commands.options_scanner_cmd import register_scanners
    from ai_options_trader.cli_commands.options_moonshot_cmd import register_moonshot
    from ai_options_trader.cli_commands.funding_cmd import register as register_funding
    from ai_options_trader.cli_commands.liquidity_cmd import register as register_liquidity
    from ai_options_trader.cli_commands.usd_cmd import register as register_usd
    from ai_options_trader.cli_commands.monetary_cmd import register as register_monetary
    from ai_options_trader.cli_commands.rates_cmd import register as register_rates
    from ai_options_trader.cli_commands.fiscal_cmd import register as register_fiscal
    from ai_options_trader.cli_commands.volatility_cmd import register as register_volatility
    from ai_options_trader.cli_commands.scenarios_cmd import register as register_scenarios
    from ai_options_trader.cli_commands.scenarios_ml_cmd import register_ml as register_scenarios_ml
    from ai_options_trader.cli_commands.commodities_cmd import register as register_commodities
    from ai_options_trader.cli_commands.crypto_cmd import register as register_crypto
    from ai_options_trader.cli_commands.ticker_cmd import register as register_ticker
    from ai_options_trader.cli_commands.housing_cmd import register as register_housing
    from ai_options_trader.cli_commands.solar_cmd import register as register_solar
    from ai_options_trader.cli_commands.regimes_cmd import register as register_regimes
    from ai_options_trader.cli_commands.ideas_cmd import register as register_ideas_legacy
    from ai_options_trader.cli_commands.ideas_clean import register_ideas as register_ideas_clean
    from ai_options_trader.cli_commands.model_cmd import register_model
    from ai_options_trader.cli_commands.live_cmd import register as register_live
    from ai_options_trader.cli_commands.track_cmd import register as register_track
    from ai_options_trader.cli_commands.nav_cmd import register as register_nav
    from ai_options_trader.cli_commands.autopilot_cmd import register as register_autopilot
    from ai_options_trader.cli_commands.portfolio_cmd import register as register_portfolio
    from ai_options_trader.cli_commands.account_cmd import register as register_account
    from ai_options_trader.cli_commands.weekly_report_cmd import register as register_weekly_report
    from ai_options_trader.cli_commands.fedfunds_cmd import register as register_fedfunds
    from ai_options_trader.cli_commands.hedges_cmd import register as register_hedges
    from ai_options_trader.cli_commands.options_scan_cmd import register_scan_commands
    from ai_options_trader.cli_commands.core_cmd import register_core
    from ai_options_trader.cli_commands.dashboard_cmd import register as register_dashboard
    from ai_options_trader.cli_commands.dashboard_cmd import register_pillar_commands
    from ai_options_trader.cli_commands.closed_trades_cmd import register as register_closed_trades
    from ai_options_trader.cli_commands.deep_cmd import register as register_deep
    from ai_options_trader.cli_commands.stress_cmd import register_stress

    # Core commands (top-level for quick access)
    register_core(app)
    register_dashboard(app)  # Main dashboard command
    register_closed_trades(app)  # Closed trades P&L
    
    # Options: modular command registration
    register_options(options_app)       # scan, most-traded
    register_pick(options_app)          # pick
    register_scanners(options_app)      # sp500-under-budget, etf-under-budget
    register_moonshot(options_app)      # moonshot
    register_scan_commands(options_app) # Additional scan commands
    
    # Ideas: new clean commands + legacy for back-compat
    register_ideas_clean(ideas_app)  # catalyst, screen
    register_ideas_legacy(ideas_app)  # event, macro-playbook (legacy aliases)
    
    # Model: clean unified commands
    register_model(model_app)  # predict, eval, inspect
    
    register_track(track_app)
    register_nav(nav_app)
    register_autopilot(autopilot_app)
    register_account(app)
    register_live(live_app)
    register_weekly_report(weekly_app)

    # Labs: keep everything else accessible under `lox labs ...`
    register_select(labs_app)
    register_portfolio(labs_app)
    register_regimes(labs_app)
    register_scenarios(labs_app)
    register_scenarios_ml(labs_app)  # ML-enhanced scenarios
    register_hedges(labs_app)  # Simplified hedge recommendations
    register_deep(labs_app)  # Deep dive ticker analysis
    register_stress(labs_app)  # Stress testing
    register_macro(macro_app)
    register_tariff(tariff_app)
    register_funding(funding_app)
    register_liquidity(liquidity_app)
    register_usd(usd_app)
    register_monetary(monetary_app)
    register_fedfunds(monetary_app)
    register_rates(rates_app)
    register_fiscal(fiscal_app)
    register_volatility(vol_app)
    register_commodities(commod_app)
    register_crypto(crypto_app)
    register_ticker(ticker_app)
    register_housing(housing_app)
    register_solar(solar_app)
    
    # Quick pillar access under labs
    register_pillar_commands(labs_app)
    _COMMANDS_REGISTERED = True


def main():
    _register_commands()
    app()

# Register commands when imported as a console-script entrypoint (`pyproject.toml` uses `ai_options_trader.cli:app`).
_register_commands()


if __name__ == "__main__":
    main()
