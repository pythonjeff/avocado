from __future__ import annotations

import typer

app = typer.Typer(
    add_completion=False, 
    help="""Lox Capital CLI — Regime-aware portfolio research & management.

\b
QUICK START:
  lox status              Portfolio health (NAV, P&L, cash)
  lox dashboard           All regime pillars at a glance
  lox chat                Interactive research chat with LLM
  lox suggest             Trade ideas based on current regime

\b
RESEARCH:
  lox labs vol --llm      Volatility research brief
  lox labs fiscal snapshot US fiscal data (deficits, TGA)
  lox labs mc-v01 --real  Monte Carlo scenario analysis

\b
Run 'lox <command> --help' for details on any command.
"""
)

# ---------------------------------------------------------------------------
# Core command groups (most commonly used)
# ---------------------------------------------------------------------------

# Chat - interactive research conversations (most useful, first)
from ai_options_trader.cli_commands.chat_cmd import app as chat_app
app.add_typer(chat_app, name="chat")

nav_app = typer.Typer(add_completion=False, help="Fund accounting: NAV tracking, investor ledger, cash flows")
app.add_typer(nav_app, name="nav")

# ---------------------------------------------------------------------------
# Trade execution & ideas
# ---------------------------------------------------------------------------
autopilot_app = typer.Typer(add_completion=False, help="Automated trade workflow with regime-aware sizing")
app.add_typer(autopilot_app, name="autopilot")

options_app = typer.Typer(add_completion=False, help="Options scanners: moonshot, picks, budget filters")
app.add_typer(options_app, name="options")

ideas_app = typer.Typer(add_completion=False, help="Trade ideas from catalysts, screens, and events")
app.add_typer(ideas_app, name="ideas")

# ---------------------------------------------------------------------------
# Analytics & reporting
# ---------------------------------------------------------------------------
model_app = typer.Typer(add_completion=False, help="ML models: regime prediction, backtesting, evaluation")
app.add_typer(model_app, name="model")

live_app = typer.Typer(add_completion=False, help="Live monitoring console with real-time alerts")
app.add_typer(live_app, name="live")

weekly_app = typer.Typer(add_completion=False, help="Weekly performance reports and summaries")
app.add_typer(weekly_app, name="weekly")

# ---------------------------------------------------------------------------
# Power-user tools under `lox labs ...`
# ---------------------------------------------------------------------------
labs_app = typer.Typer(
    add_completion=False, 
    help="""Deep research tools: regime analysis, Monte Carlo, ticker outlook.

\b
REGIMES:
  lox labs vol --llm         Volatility regime with LLM analysis
  lox labs fiscal snapshot   US fiscal data (deficits, issuance, TGA)
  lox labs funding snapshot  Funding markets (SOFR, repo, reserves)
  lox labs rates snapshot    Rates/yield curve analysis

\b
SCENARIOS:
  lox labs mc-v01 --real     Monte Carlo with live positions
  lox labs hedge             Defensive trade ideas
  lox labs grow              Offensive trade ideas

\b
TICKERS:
  lox labs ticker outlook -t AAPL   Ticker outlook with regime context
  lox labs ticker news -t NVDA      Recent news for ticker
"""
)
app.add_typer(labs_app, name="labs")
macro_app = typer.Typer(add_completion=False, help="Macro signals and datasets")
labs_app.add_typer(macro_app, name="macro")
tariff_app = typer.Typer(add_completion=False, help="Tariff / cost-push regime signals")
labs_app.add_typer(tariff_app, name="tariff")
funding_app = typer.Typer(add_completion=False, help="Funding markets (SOFR, repo spreads) — price of money in daily markets")
labs_app.add_typer(funding_app, name="funding")
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
household_app = typer.Typer(add_completion=False, help="Household wealth regime (MMT sectoral balances: where deficit dollars flow)")
labs_app.add_typer(household_app, name="household")
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
    
    # Core commands
    from ai_options_trader.cli_commands.core.core_cmd import register_core
    from ai_options_trader.cli_commands.core.dashboard_cmd import register as register_dashboard
    from ai_options_trader.cli_commands.core.dashboard_cmd import register_pillar_commands
    from ai_options_trader.cli_commands.core.nav_cmd import register as register_nav
    from ai_options_trader.cli_commands.core.account_cmd import register as register_account
    from ai_options_trader.cli_commands.core.weekly_report_cmd import register as register_weekly_report
    from ai_options_trader.cli_commands.core.closed_trades_cmd import register as register_closed_trades
    from ai_options_trader.cli_commands.core.live_cmd import register as register_live
    from ai_options_trader.cli_commands.core.portfolio_cmd import register as register_portfolio
    
    # Regime commands
    from ai_options_trader.cli_commands.regimes.macro_cmd import register as register_macro
    from ai_options_trader.cli_commands.regimes.tariff_cmd import register as register_tariff
    from ai_options_trader.cli_commands.regimes.funding_cmd import register as register_funding
    from ai_options_trader.cli_commands.regimes.usd_cmd import register as register_usd
    from ai_options_trader.cli_commands.regimes.monetary_cmd import register as register_monetary
    from ai_options_trader.cli_commands.regimes.rates_cmd import register as register_rates
    from ai_options_trader.cli_commands.regimes.fiscal_cmd import register as register_fiscal
    from ai_options_trader.cli_commands.regimes.volatility_cmd import register as register_volatility
    from ai_options_trader.cli_commands.regimes.commodities_cmd import register as register_commodities
    from ai_options_trader.cli_commands.regimes.crypto_cmd import register as register_crypto
    from ai_options_trader.cli_commands.regimes.housing_cmd import register as register_housing
    from ai_options_trader.cli_commands.regimes.household_cmd import register as register_household
    from ai_options_trader.cli_commands.regimes.solar_cmd import register as register_solar
    from ai_options_trader.cli_commands.regimes.regimes_cmd import register as register_regimes
    from ai_options_trader.cli_commands.regimes.fedfunds_cmd import register as register_fedfunds
    
    # Options commands
    from ai_options_trader.cli_commands.options.select_cmd import register as register_select
    from ai_options_trader.cli_commands.options.options_cmd import register as register_options
    from ai_options_trader.cli_commands.options.options_pick_cmd import register_pick
    from ai_options_trader.cli_commands.options.options_scanner_cmd import register_scanners
    from ai_options_trader.cli_commands.options.options_moonshot_cmd import register_moonshot
    from ai_options_trader.cli_commands.options.options_scan_cmd import register_scan_commands
    
    # Analysis commands
    from ai_options_trader.cli_commands.analysis.scenarios_cmd import register as register_scenarios
    from ai_options_trader.cli_commands.analysis.scenarios_ml_cmd import register_ml as register_scenarios_ml
    from ai_options_trader.cli_commands.analysis.model_cmd import register_model
    from ai_options_trader.cli_commands.analysis.ticker_cmd import register as register_ticker
    from ai_options_trader.cli_commands.analysis.deep_cmd import register as register_deep
    from ai_options_trader.cli_commands.analysis.stress_cmd import register_stress
    
    # Ideas commands
    from ai_options_trader.cli_commands.ideas.ideas_cmd import register as register_ideas_legacy
    from ai_options_trader.cli_commands.ideas.ideas_clean import register_ideas as register_ideas_clean
    from ai_options_trader.cli_commands.ideas.hedges_cmd import register as register_hedges
    
    # Other commands (remain at root)
    from ai_options_trader.cli_commands.track_cmd import register as register_track
    from ai_options_trader.cli_commands.autopilot_cmd import register as register_autopilot

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
    register_household(household_app)
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
