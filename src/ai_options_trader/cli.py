from __future__ import annotations

from datetime import date
import typer

app = typer.Typer(
    add_completion=False, 
    help="""Lox Capital CLI — Portfolio research and options trading.

\b
DAILY USE:
  lox status                 Portfolio health (NAV, P&L, cash)
  lox dashboard              All regime pillars at a glance
  lox scan -t NVDA           Options chain scanner
  lox research -t NVDA       Deep research on a ticker

\b
RESEARCH:
  lox regime vol             Volatility regime
  lox regime fiscal          Fiscal regime (deficits, TGA)
  lox scenario monte-carlo   Monte Carlo simulation

\b
TRADING:
  lox trade                  Automated trade workflow
  lox ideas                  Trade ideas from screens

\b
Run 'lox <command> --help' for details.
"""
)

# ---------------------------------------------------------------------------
# TOP-LEVEL COMMANDS (flat, most commonly used)
# ---------------------------------------------------------------------------

@app.command("scan")
def scan_cmd(
    ticker: str = typer.Option(..., "--ticker", "-t", help="Ticker symbol"),
    want: str = typer.Option("put", "--want", "-w", help="call or put"),
    min_days: int = typer.Option(30, "--min-days", help="Min DTE"),
    max_days: int = typer.Option(365, "--max-days", help="Max DTE"),
    show: int = typer.Option(30, "--show", "-n", help="Number of results"),
):
    """
    Options chain scanner.
    
    Examples:
        lox scan -t NVDA
        lox scan -t CRWV --want put --min-days 100
    """
    from ai_options_trader.config import load_settings
    from ai_options_trader.data.alpaca import fetch_option_chain, make_clients
    from ai_options_trader.utils.occ import parse_occ_option_symbol
    from rich.console import Console
    from rich.table import Table
    
    settings = load_settings()
    _, data = make_clients(settings)
    
    w = want.strip().lower()
    if w not in {"call", "put"}:
        w = "put"
    
    console = Console()
    t = ticker.upper()
    today = date.today()
    
    console.print(f"\n[bold cyan]{t} {w.upper()}s[/bold cyan] | DTE: {min_days}-{max_days}\n")
    
    chain = fetch_option_chain(data, t, feed=settings.alpaca_options_feed)
    if not chain:
        console.print("[yellow]No options data[/yellow]")
        return
    
    opts = []
    for opt in chain.values():
        symbol = str(getattr(opt, "symbol", ""))
        if not symbol:
            continue
        try:
            expiry, opt_type, strike = parse_occ_option_symbol(symbol, t)
            if opt_type != w:
                continue
            dte = (expiry - today).days
            if dte < min_days or dte > max_days:
                continue
            
            greeks = getattr(opt, "greeks", None)
            delta = getattr(greeks, "delta", None) if greeks else None
            quote = getattr(opt, "latest_quote", None)
            bid = getattr(quote, "bid_price", None) if quote else None
            ask = getattr(quote, "ask_price", None) if quote else None
            trade = getattr(opt, "latest_trade", None)
            last = getattr(trade, "price", None) if trade else None
            
            opts.append({
                "symbol": symbol, "strike": strike, "dte": dte,
                "delta": float(delta) if delta else None,
                "bid": float(bid) if bid else None,
                "ask": float(ask) if ask else None,
                "last": float(last) if last else None,
            })
        except Exception:
            continue
    
    if not opts:
        console.print(f"[yellow]No {w}s in {min_days}-{max_days} DTE[/yellow]")
        return
    
    opts.sort(key=lambda x: (x["strike"], x["dte"]))
    opts = opts[:show]
    
    console.print(f"[dim]Found {len(opts)} contracts[/dim]\n")
    
    table = Table(show_header=True, expand=False)
    table.add_column("Symbol", style="cyan")
    table.add_column("Strike", justify="right")
    table.add_column("DTE", justify="right")
    table.add_column("Delta", justify="right")
    table.add_column("Bid", justify="right")
    table.add_column("Ask", justify="right", style="yellow")
    table.add_column("Last", justify="right")
    
    for o in opts:
        table.add_row(
            o["symbol"],
            f"${o['strike']:.2f}",
            str(o["dte"]),
            f"{o['delta']:+.3f}" if o["delta"] else "—",
            f"${o['bid']:.2f}" if o["bid"] else "—",
            f"${o['ask']:.2f}" if o["ask"] else "—",
            f"${o['last']:.2f}" if o["last"] else "—",
        )
    console.print(table)


@app.command("research")
def research_cmd(
    ticker: str = typer.Option(..., "--ticker", "-t", help="Ticker symbol"),
    llm: bool = typer.Option(False, "--llm", help="Include LLM analysis"),
):
    """
    Deep research on a ticker.
    
    Examples:
        lox research -t NVDA
        lox research -t AAPL --llm
    """
    from ai_options_trader.cli_commands.analysis.fundamentals_cmd import _run_research_deep_dive
    _run_research_deep_dive(ticker, llm=llm)


# ---------------------------------------------------------------------------
# REGIME SUBGROUP (consolidated)
# ---------------------------------------------------------------------------
regime_app = typer.Typer(add_completion=False, help="Economic regime analysis")
app.add_typer(regime_app, name="regime")


@regime_app.command("vol")
def regime_vol(llm: bool = typer.Option(False, "--llm", help="Include LLM analysis")):
    """Volatility regime (VIX level, term structure)."""
    from ai_options_trader.cli_commands.regimes.volatility_cmd import volatility_snapshot
    volatility_snapshot(llm=llm)


@regime_app.command("fiscal")
def regime_fiscal():
    """US fiscal regime (deficits, TGA, issuance)."""
    from ai_options_trader.cli_commands.regimes.fiscal_cmd import fiscal_snapshot
    fiscal_snapshot()


@regime_app.command("funding")
def regime_funding():
    """Funding markets (SOFR, repo spreads)."""
    from ai_options_trader.cli_commands.regimes.funding_cmd import funding_snapshot
    funding_snapshot()


@regime_app.command("rates")
def regime_rates():
    """Rates / yield curve analysis."""
    from ai_options_trader.cli_commands.regimes.rates_cmd import rates_snapshot
    rates_snapshot()


@regime_app.command("macro")
def regime_macro():
    """Macro regime overview."""
    from ai_options_trader.cli_commands.regimes.macro_cmd import macro_snapshot
    macro_snapshot()


# ---------------------------------------------------------------------------
# SCENARIO SUBGROUP (consolidated)
# ---------------------------------------------------------------------------
scenario_app = typer.Typer(add_completion=False, help="Portfolio scenario analysis")
app.add_typer(scenario_app, name="scenario")


@scenario_app.command("monte-carlo")
def scenario_monte_carlo(
    real: bool = typer.Option(False, "--real", help="Use real positions"),
):
    """Monte Carlo simulation with 10,000+ scenarios."""
    from ai_options_trader.cli_commands.analysis.scenarios_cmd import scenarios_monte_carlo
    scenarios_monte_carlo(real=real)


@scenario_app.command("stress")
def scenario_stress():
    """Stress test portfolio under extreme conditions."""
    from ai_options_trader.cli_commands.analysis.stress_cmd import stress_test
    stress_test()


# ---------------------------------------------------------------------------
# SUBGROUPS (organized by function)
# ---------------------------------------------------------------------------

# Chat - interactive research
from ai_options_trader.cli_commands.chat_cmd import app as chat_app
app.add_typer(chat_app, name="chat")

# Trade execution (renamed from autopilot)
trade_app = typer.Typer(add_completion=False, help="Trade execution and automation")
app.add_typer(trade_app, name="trade")

# Options (full commands)
options_app = typer.Typer(add_completion=False, help="Full options toolset")
app.add_typer(options_app, name="options")

# Ideas
ideas_app = typer.Typer(add_completion=False, help="Trade ideas from screens and catalysts")
app.add_typer(ideas_app, name="ideas")

# Account
nav_app = typer.Typer(add_completion=False, help="NAV tracking and fund accounting")
app.add_typer(nav_app, name="nav")

# Labs - advanced/power user
labs_app = typer.Typer(add_completion=False, help="Advanced research tools (power users)")
app.add_typer(labs_app, name="labs")

# Hidden/legacy subgroups for labs
macro_app = typer.Typer(add_completion=False, help="Macro signals")
labs_app.add_typer(macro_app, name="macro")
tariff_app = typer.Typer(add_completion=False, help="Tariff regime")
labs_app.add_typer(tariff_app, name="tariff")
funding_app = typer.Typer(add_completion=False, help="Funding markets")
labs_app.add_typer(funding_app, name="funding")
usd_app = typer.Typer(add_completion=False, help="USD regime")
labs_app.add_typer(usd_app, name="usd")
monetary_app = typer.Typer(add_completion=False, help="Fed liquidity")
labs_app.add_typer(monetary_app, name="monetary")
rates_app = typer.Typer(add_completion=False, help="Rates regime")
labs_app.add_typer(rates_app, name="rates")
fiscal_app = typer.Typer(add_completion=False, help="Fiscal regime")
labs_app.add_typer(fiscal_app, name="fiscal")
vol_app = typer.Typer(add_completion=False, help="Volatility regime")
labs_app.add_typer(vol_app, name="volatility")
commod_app = typer.Typer(add_completion=False, help="Commodities")
labs_app.add_typer(commod_app, name="commodities")
crypto_app = typer.Typer(add_completion=False, help="Crypto")
labs_app.add_typer(crypto_app, name="crypto")
ticker_app = typer.Typer(add_completion=False, help="Ticker analysis")
labs_app.add_typer(ticker_app, name="ticker")
housing_app = typer.Typer(add_completion=False, help="Housing regime")
labs_app.add_typer(housing_app, name="housing")
household_app = typer.Typer(add_completion=False, help="Household wealth")
labs_app.add_typer(household_app, name="household")
news_app = typer.Typer(add_completion=False, help="News sentiment")
labs_app.add_typer(news_app, name="news")
solar_app = typer.Typer(add_completion=False, help="Solar regime")
labs_app.add_typer(solar_app, name="solar")
silver_app = typer.Typer(add_completion=False, help="Silver regime")
labs_app.add_typer(silver_app, name="silver")
track_app = typer.Typer(add_completion=False, help="Tracking")
labs_app.add_typer(track_app, name="track")

# Additional apps needed for registration
model_app = typer.Typer(add_completion=False, help="ML models")
app.add_typer(model_app, name="model")
live_app = typer.Typer(add_completion=False, help="Live monitoring")
app.add_typer(live_app, name="live")
weekly_app = typer.Typer(add_completion=False, help="Weekly reports")
app.add_typer(weekly_app, name="weekly")
autopilot_app = trade_app  # Alias for backward compat

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
    from ai_options_trader.cli_commands.regimes.news_cmd import register as register_news
    from ai_options_trader.cli_commands.regimes.solar_cmd import register as register_solar
    from ai_options_trader.cli_commands.regimes.silver_cmd import register as register_silver
    from ai_options_trader.cli_commands.regimes.regimes_cmd import register as register_regimes
    from ai_options_trader.cli_commands.regimes.fedfunds_cmd import register as register_fedfunds
    
    # Options commands
    from ai_options_trader.cli_commands.options.select_cmd import register as register_select
    from ai_options_trader.cli_commands.options.options_cmd import register as register_options
    from ai_options_trader.cli_commands.options.options_pick_cmd import register_pick
    from ai_options_trader.cli_commands.options.options_scanner_cmd import register_scanners
    from ai_options_trader.cli_commands.options.options_moonshot_cmd import register_moonshot
    
    # Analysis commands
    from ai_options_trader.cli_commands.analysis.scenarios_cmd import register as register_scenarios
    from ai_options_trader.cli_commands.analysis.scenarios_ml_cmd import register_ml as register_scenarios_ml
    from ai_options_trader.cli_commands.analysis.model_cmd import register_model
    from ai_options_trader.cli_commands.analysis.ticker_cmd import register as register_ticker
    from ai_options_trader.cli_commands.analysis.deep_cmd import register as register_deep
    from ai_options_trader.cli_commands.analysis.stress_cmd import register_stress
    from ai_options_trader.cli_commands.analysis.fundamentals_cmd import register as register_fundamentals
    
    # Ideas commands
    from ai_options_trader.cli_commands.ideas.ideas_cmd import register as register_ideas_legacy
    from ai_options_trader.cli_commands.ideas.ideas_clean import register_ideas as register_ideas_clean
    from ai_options_trader.cli_commands.ideas.hedges_cmd import register as register_hedges
    
    # Scanner commands
    from ai_options_trader.cli_commands.scanner.bubble_finder_cmd import register as register_bubble_finder
    
    # Other commands (remain at root)
    from ai_options_trader.cli_commands.track_cmd import register as register_track
    from ai_options_trader.cli_commands.autopilot_cmd import register as register_autopilot

    # Core commands (top-level for quick access)
    register_core(app)
    register_dashboard(app)  # Main dashboard command
    register_closed_trades(app)  # Closed trades P&L
    
    # Options: modular command registration
    register_options(options_app)       # scan, best, most-traded, high-oi, deep
    register_pick(options_app)          # pick
    register_scanners(options_app)      # sp500-under-budget, etf-under-budget
    register_moonshot(options_app)      # moonshot
    
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
    register_news(news_app)
    register_solar(solar_app)
    register_silver(silver_app)
    register_bubble_finder(labs_app)  # Bubble finder scanner
    register_fundamentals(labs_app)  # CFA-level financial modeling
    
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
