"""
LOX Capital CLI

Primary commands:
- lox pm                        Morning report
- lox research regimes/ticker/portfolio/scenario
- lox nav/account/status
- lox weekly report
"""
from __future__ import annotations

from datetime import date
import typer

app = typer.Typer(
    add_completion=False,
    help="""LOX Capital CLI — Research & Portfolio Management

\b
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RESEARCH
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  lox research regimes       Unified regime dashboard + LLM
  lox research ticker NVDA   Hedge fund level analysis
  lox research portfolio     Outlook on open positions
  lox research scenario SPY  Monte Carlo macro shock sim

\b
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PORTFOLIO
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  lox pm                     PM morning report + LLM
  lox status                 Portfolio health (NAV, P&L)
  lox risk                   Greeks dashboard
  lox scan -t NVDA           Options chain scanner

\b
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REGIME DRILL-DOWN
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  lox regime growth          Growth pillar
  lox regime inflation       Inflation pillar
  lox regime credit          Credit spreads
  lox regime vol             Volatility (VIX)
  lox regime rates           Interest rates
  lox regime funding         Liquidity / funding
  ... and more (lox regime --help)

\b
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ACCOUNTING
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  lox account                Alpaca account summary
  lox nav snapshot           NAV and investor ledger
  lox weekly report          Investor report

\b
Run 'lox <command> --help' for details.
"""
)


# ---------------------------------------------------------------------------
# TOP-LEVEL COMMANDS
# ---------------------------------------------------------------------------

@app.command("scan")
def scan_cmd(
    ticker: str = typer.Option(..., "--ticker", "-t", help="Ticker symbol"),
    want: str = typer.Option("put", "--want", "-w", help="call or put"),
    min_days: int = typer.Option(30, "--min-days", help="Min DTE"),
    max_days: int = typer.Option(365, "--max-days", help="Max DTE"),
    filter_delta: float = typer.Option(None, "--delta", "-d", help="Filter by delta"),
    max_iv: float = typer.Option(None, "--max-iv", help="Max IV"),
    min_iv: float = typer.Option(None, "--min-iv", help="Min IV"),
    show: int = typer.Option(30, "--show", "-n", help="Number of results"),
):
    """Options chain scanner."""
    from lox.config import load_settings
    from lox.data.alpaca import fetch_option_chain, make_clients
    from lox.utils.occ import parse_occ_option_symbol
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
            opt_delta = getattr(greeks, "delta", None) if greeks else None
            opt_theta = getattr(greeks, "theta", None) if greeks else None
            opt_iv = getattr(opt, "implied_volatility", None)
            
            quote = getattr(opt, "latest_quote", None)
            bid = getattr(quote, "bid_price", None) if quote else None
            ask = getattr(quote, "ask_price", None) if quote else None
            
            opts.append({
                "symbol": symbol, "strike": strike, "dte": dte,
                "delta": float(opt_delta) if opt_delta else None,
                "theta": float(opt_theta) if opt_theta else None,
                "iv": float(opt_iv) if opt_iv else None,
                "bid": float(bid) if bid else None,
                "ask": float(ask) if ask else None,
            })
        except Exception:
            continue
    
    if not opts:
        console.print(f"[yellow]No {w}s in {min_days}-{max_days} DTE[/yellow]")
        return
    
    # Apply filters
    if filter_delta is not None:
        target_delta = abs(filter_delta)
        opts = [o for o in opts if o["delta"] is not None and abs(abs(o["delta"]) - target_delta) <= 0.05]
    
    if min_iv is not None:
        opts = [o for o in opts if o["iv"] is not None and o["iv"] >= min_iv]
    
    if max_iv is not None:
        opts = [o for o in opts if o["iv"] is not None and o["iv"] <= max_iv]
    
    # Sort by strike
    opts.sort(key=lambda x: (x["strike"], x["dte"]))
    opts = opts[:show]
    
    table = Table(show_header=True, expand=False)
    table.add_column("Symbol", style="cyan")
    table.add_column("Strike", justify="right")
    table.add_column("DTE", justify="right")
    table.add_column("Delta", justify="right")
    table.add_column("IV", justify="right")
    table.add_column("Bid", justify="right")
    table.add_column("Ask", justify="right", style="yellow")
    
    for o in opts:
        table.add_row(
            o["symbol"],
            f"${o['strike']:.2f}",
            str(o["dte"]),
            f"{o['delta']:+.2f}" if o["delta"] else "—",
            f"{o['iv']:.0%}" if o["iv"] else "—",
            f"${o['bid']:.2f}" if o["bid"] else "—",
            f"${o['ask']:.2f}" if o["ask"] else "—",
        )
    console.print(table)


# ---------------------------------------------------------------------------
# SUBGROUPS
# ---------------------------------------------------------------------------

# NAV / Accounting
nav_app = typer.Typer(add_completion=False, help="NAV and fund accounting")
app.add_typer(nav_app, name="nav")

# Weekly reports
weekly_app = typer.Typer(add_completion=False, help="Weekly reports")
app.add_typer(weekly_app, name="weekly")

# Risk dashboard
@app.command("risk")
def risk_cmd(
    refresh: bool = typer.Option(False, "--refresh", help="Force refresh option chain data"),
    json_out: bool = typer.Option(False, "--json", help="Machine-readable JSON output"),
):
    """Portfolio Greeks risk dashboard — net delta, gamma, theta, vega."""
    from lox.cli_commands.core.risk_cmd import risk_dashboard
    risk_dashboard(refresh=refresh, json_out=json_out)


# Regimes (for drill-down)
regime_app = typer.Typer(add_completion=False, help="Regime analysis")
app.add_typer(regime_app, name="regime")

# Crypto perps
crypto_app = typer.Typer(add_completion=False, help="Crypto perps: data, research, trading")
app.add_typer(crypto_app, name="crypto")

# Quiver Quantitative — congressional / contracts / flow bundle
from lox.cli_commands.quiver_cmd import app as quiver_app
app.add_typer(quiver_app, name="quiver")
app.add_typer(quiver_app, name="q")


# ── Keep regimes ──────────────────────────────────────────────────────────
@regime_app.command("vol")
def regime_vol(
    llm: bool = typer.Option(False, "--llm", help="Chat with LLM analyst"),
    ticker: str = typer.Option("", "--ticker", "-t", help="Ticker for focused chat (used with --llm)"),
    refresh: bool = typer.Option(False, "--refresh", help="Force refresh data"),
    book: bool = typer.Option(False, "--book", "-b", help="Show impact on open positions"),
):
    """Volatility regime."""
    from lox.cli_commands.regimes.volatility_cmd import volatility_snapshot
    volatility_snapshot(llm=llm, ticker=ticker, refresh=refresh)
    if book:
        from lox.cli_commands.shared.book_impact import show_book_impact
        show_book_impact(domain="volatility")


@regime_app.command("gov")
def regime_gov(
    refresh: bool = typer.Option(False, "--refresh", help="Force refresh FRED / fiscaldata downloads"),
    llm: bool = typer.Option(False, "--llm", help="Chat with LLM analyst"),
    ticker: str = typer.Option("", "--ticker", "-t", help="Ticker for focused chat (used with --llm)"),
    features: bool = typer.Option(False, "--features", help="Export ML-ready feature vector"),
    json_out: bool = typer.Option(False, "--json", help="Machine-readable JSON output"),
    delta: str = typer.Option("", "--delta", help="Show changes vs N days ago (e.g., 7d, 1w, 1m)"),
    book: bool = typer.Option(False, "--book", "-b", help="Show impact on open positions"),
):
    """Government regime (fiscal flows + federal activity)."""
    from lox.cli_commands.regimes.gov_cmd import fiscal_snapshot
    fiscal_snapshot(refresh=refresh, llm=llm, ticker=ticker, features=features, json_out=json_out, delta=delta)
    if book:
        from lox.cli_commands.shared.book_impact import show_book_impact
        show_book_impact(domain="gov")


@regime_app.command("funding")
def regime_funding(
    refresh: bool = typer.Option(False, "--refresh", help="Force refresh FRED downloads"),
    llm: bool = typer.Option(False, "--llm", help="Chat with LLM analyst"),
    ticker: str = typer.Option("", "--ticker", "-t", help="Ticker for focused chat (used with --llm)"),
    features: bool = typer.Option(False, "--features", help="Export ML-ready feature vector"),
    json_out: bool = typer.Option(False, "--json", help="Machine-readable JSON output"),
    delta: str = typer.Option("", "--delta", help="Show changes vs N days ago (e.g., 7d, 1w, 1m)"),
    book: bool = typer.Option(False, "--book", "-b", help="Show impact on open positions"),
):
    """Funding regime."""
    from lox.cli_commands.regimes.funding_cmd import funding_snapshot
    funding_snapshot(refresh=refresh, llm=llm, ticker=ticker, features=features, json_out=json_out, delta=delta)
    if book:
        from lox.cli_commands.shared.book_impact import show_book_impact
        show_book_impact(domain="liquidity")


@regime_app.command("rates")
def regime_rates(
    llm: bool = typer.Option(False, "--llm", help="Chat with LLM analyst"),
    ticker: str = typer.Option("", "--ticker", "-t", help="Ticker for focused chat (used with --llm)"),
    refresh: bool = typer.Option(False, "--refresh", help="Force refresh data"),
    book: bool = typer.Option(False, "--book", "-b", help="Show impact on open positions"),
):
    """Rates regime."""
    from lox.cli_commands.regimes.rates_cmd import rates_snapshot
    rates_snapshot(llm=llm, ticker=ticker, refresh=refresh)
    if book:
        from lox.cli_commands.shared.book_impact import show_book_impact
        show_book_impact(domain="rates")


@regime_app.command("ai")
def regime_ai(
    llm: bool = typer.Option(False, "--llm", help="Chat with LLM analyst"),
    ticker: str = typer.Option("", "--ticker", "-t", help="Ticker for focused chat (used with --llm)"),
    refresh: bool = typer.Option(False, "--refresh", help="Force refresh price downloads"),
    book: bool = typer.Option(False, "--book", "-b", help="Show impact on open positions"),
):
    """AI bubble regime (v0 — basket equity signals)."""
    from lox.cli_commands.regimes.ai_cmd import ai_snapshot
    ai_snapshot(llm=llm, ticker=ticker, refresh=refresh)
    if book:
        from lox.cli_commands.shared.book_impact import show_book_impact
        show_book_impact(domain="ai")


@regime_app.command("bubble")
def regime_bubble(
    llm: bool = typer.Option(False, "--llm", help="Chat with LLM analyst"),
    ticker: str = typer.Option("", "--ticker", "-t", help="Ticker for focused chat (used with --llm)"),
    refresh: bool = typer.Option(False, "--refresh", help="Force refresh underlying data"),
    book: bool = typer.Option(False, "--book", "-b", help="Show impact on open positions"),
):
    """Broad-market bubble regime — valuation, concentration, margin debt."""
    from lox.cli_commands.regimes.bubble_cmd import bubble_snapshot
    bubble_snapshot(llm=llm, ticker=ticker, refresh=refresh)
    if book:
        from lox.cli_commands.shared.book_impact import show_book_impact
        show_book_impact(domain="bubble")


@regime_app.command("oil")
def regime_oil(
    llm: bool = typer.Option(False, "--llm", help="Chat with LLM analyst"),
    ticker: str = typer.Option("", "--ticker", "-t", help="Ticker for focused chat (used with --llm)"),
    refresh: bool = typer.Option(False, "--refresh", help="Force refresh data"),
    delta: str = typer.Option("", "--delta", help="Show changes vs N days ago (e.g., 1d, 7d, 1w)"),
    alert: bool = typer.Option(False, "--alert", help="Only output if disruption is severe (for cron/monitoring)"),
):
    """Oil prices & Strait of Hormuz shipping traffic."""
    from lox.cli_commands.regimes.oil_cmd import oil_snapshot
    oil_snapshot(llm=llm, ticker=ticker, refresh=refresh, delta=delta, alert=alert)



# ── Core regimes ─────────────────────────────────────────────────────────
@regime_app.command("growth")
def regime_growth(
    llm: bool = typer.Option(False, "--llm", help="Chat with LLM analyst"),
    ticker: str = typer.Option("", "--ticker", "-t", help="Ticker for focused chat (used with --llm)"),
    refresh: bool = typer.Option(False, "--refresh", help="Force refresh FRED downloads"),
    book: bool = typer.Option(False, "--book", "-b", help="Show impact on open positions"),
):
    """Growth regime."""
    from lox.cli_commands.regimes.growth_cmd import growth_snapshot
    growth_snapshot(llm=llm, ticker=ticker, refresh=refresh)
    if book:
        from lox.cli_commands.shared.book_impact import show_book_impact
        show_book_impact(domain="growth")


@regime_app.command("inflation")
def regime_inflation(
    llm: bool = typer.Option(False, "--llm", help="Chat with LLM analyst"),
    ticker: str = typer.Option("", "--ticker", "-t", help="Ticker for focused chat (used with --llm)"),
    refresh: bool = typer.Option(False, "--refresh", help="Force refresh FRED downloads"),
    book: bool = typer.Option(False, "--book", "-b", help="Show impact on open positions"),
):
    """Inflation regime."""
    from lox.cli_commands.regimes.inflation_cmd import inflation_snapshot
    inflation_snapshot(llm=llm, ticker=ticker, refresh=refresh)
    if book:
        from lox.cli_commands.shared.book_impact import show_book_impact
        show_book_impact(domain="inflation")


@regime_app.command("credit")
def regime_credit(
    llm: bool = typer.Option(False, "--llm", help="Chat with LLM analyst"),
    ticker: str = typer.Option("", "--ticker", "-t", help="Ticker for focused chat (used with --llm)"),
    refresh: bool = typer.Option(False, "--refresh", help="Force refresh FRED downloads"),
    book: bool = typer.Option(False, "--book", "-b", help="Show impact on open positions"),
    features: bool = typer.Option(False, "--features", help="Export ML-ready feature vector (JSON)"),
    json_out: bool = typer.Option(False, "--json", help="Machine-readable JSON output"),
    delta: str = typer.Option("", "--delta", help="Show changes vs N days ago (e.g., 7d, 1w, 1m)"),
    alert: bool = typer.Option(False, "--alert", help="Only output if regime is extreme (for cron/monitoring)"),
    calendar: bool = typer.Option(False, "--calendar", help="Show upcoming events that could shift this regime"),
    trades: bool = typer.Option(False, "--trades", help="Show quick trade expressions for current regime"),
):
    """Credit / spreads regime."""
    from lox.cli_commands.regimes.credit_cmd import credit_snapshot
    credit_snapshot(
        llm=llm, ticker=ticker, refresh=refresh,
        features=features, json_out=json_out, delta=delta,
        alert=alert, calendar=calendar, trades=trades,
    )
    if book:
        from lox.cli_commands.shared.book_impact import show_book_impact
        show_book_impact(domain="credit")


@regime_app.command("consumer")
def regime_consumer(
    llm: bool = typer.Option(False, "--llm", help="Chat with LLM analyst"),
    ticker: str = typer.Option("", "--ticker", "-t", help="Ticker for focused chat (used with --llm)"),
    refresh: bool = typer.Option(False, "--refresh", help="Force refresh FRED downloads"),
    book: bool = typer.Option(False, "--book", "-b", help="Show impact on open positions"),
):
    """Consumer health regime."""
    from lox.cli_commands.regimes.consumer_cmd import consumer_snapshot
    consumer_snapshot(llm=llm, ticker=ticker, refresh=refresh)
    if book:
        from lox.cli_commands.shared.book_impact import show_book_impact
        show_book_impact(domain="consumer")


@regime_app.command("earnings")
def regime_earnings(
    llm: bool = typer.Option(False, "--llm", help="Chat with LLM analyst"),
    ticker: str = typer.Option("", "--ticker", "-t", help="Ticker for focused chat (used with --llm)"),
    refresh: bool = typer.Option(False, "--refresh", help="Force refresh data downloads"),
    book: bool = typer.Option(False, "--book", "-b", help="Show impact on open positions"),
    delta: str = typer.Option("", "--delta", "-d", help="Show N-day delta (e.g. '7d', '30d')"),
    features: bool = typer.Option(False, "--features", help="Export ML-ready feature vector (JSON)"),
    json_out: bool = typer.Option(False, "--json", help="Machine-readable JSON output"),
    sector: str = typer.Option("", "--sector", "-s", help="Drill into sector basket (e.g. Technology, Healthcare)"),
):
    """S&P 500 earnings regime (beat rate, revisions, surprise magnitude)."""
    from lox.cli_commands.regimes.earnings_cmd import earnings_snapshot
    earnings_snapshot(
        llm=llm, ticker=ticker, refresh=refresh,
        features=features, json_out=json_out, delta=delta,
        sector=sector,
    )
    if book:
        from lox.cli_commands.shared.book_impact import show_book_impact
        show_book_impact(domain="earnings")


@regime_app.command("usd")
def regime_usd(
    llm: bool = typer.Option(False, "--llm", help="Chat with LLM analyst"),
    ticker: str = typer.Option("", "--ticker", "-t", help="Ticker for focused chat (used with --llm)"),
    refresh: bool = typer.Option(False, "--refresh", help="Force refresh FRED downloads"),
    book: bool = typer.Option(False, "--book", "-b", help="Show impact on open positions"),
    features: bool = typer.Option(False, "--features", help="Export ML-ready feature vector (JSON)"),
    json_out: bool = typer.Option(False, "--json", help="Machine-readable JSON output"),
    delta: str = typer.Option("", "--delta", help="Show changes vs N days ago (e.g., 7d, 1w, 1m)"),
    alert: bool = typer.Option(False, "--alert", help="Only output if regime is extreme (for cron/monitoring)"),
    calendar: bool = typer.Option(False, "--calendar", help="Show upcoming events that could shift this regime"),
    trades: bool = typer.Option(False, "--trades", help="Show quick trade expressions for current regime"),
):
    """USD strength regime (trade-weighted dollar, EM/commodity impact, tail risks)."""
    from lox.cli_commands.regimes.usd_cmd import usd_snapshot
    usd_snapshot(
        llm=llm, ticker=ticker, refresh=refresh,
        features=features, json_out=json_out, delta=delta,
        alert=alert, calendar=calendar, trades=trades,
    )
    if book:
        from lox.cli_commands.shared.book_impact import show_book_impact
        show_book_impact(domain="usd")


@regime_app.command("positioning")
def regime_positioning(
    llm: bool = typer.Option(False, "--llm", help="Chat with LLM analyst"),
    ticker: str = typer.Option("SPY", "--ticker", "-t", help="Ticker for GEX/options analysis (default SPY)"),
    refresh: bool = typer.Option(False, "--refresh", help="Force refresh data downloads"),
    book: bool = typer.Option(False, "--book", "-b", help="Show impact on open positions"),
    features: bool = typer.Option(False, "--features", help="Export ML-ready feature vector (JSON)"),
    json_out: bool = typer.Option(False, "--json", help="Machine-readable JSON output"),
    delta: str = typer.Option("", "--delta", help="Show changes vs N days ago (e.g., 7d, 1w, 1m)"),
    alert: bool = typer.Option(False, "--alert", help="Only output if regime is extreme (for cron/monitoring)"),
    calendar: bool = typer.Option(False, "--calendar", help="Show upcoming events that could shift this regime"),
    trades: bool = typer.Option(False, "--trades", help="Show quick trade expressions for current regime"),
):
    """Positioning & flow regime (COT, GEX, put/call, sentiment, short interest)."""
    from lox.cli_commands.regimes.positioning_cmd import positioning_snapshot
    positioning_snapshot(
        llm=llm, ticker=ticker, refresh=refresh,
        features=features, json_out=json_out, delta=delta,
        alert=alert, calendar=calendar, trades=trades,
    )
    if book:
        from lox.cli_commands.shared.book_impact import show_book_impact
        show_book_impact(domain="positioning")


@regime_app.command("spy")
def regime_spy(
    refresh: bool = typer.Option(False, "--refresh", help="Force refresh data"),
    json_out: bool = typer.Option(False, "--json", help="Machine-readable JSON output"),
    llm: bool = typer.Option(False, "--llm", help="Chat with LLM analyst"),
):
    """SPY options flow regime (GEX, put/call, skew) — single-fetch microstructure signal."""
    from lox.cli_commands.regimes.spy_cmd import spy_snapshot
    spy_snapshot(refresh=refresh, json_out=json_out, llm=llm)


@regime_app.command("ag")
def regime_agriculture(
    llm: bool = typer.Option(False, "--llm", help="Chat with LLM analyst"),
    ticker: str = typer.Option("", "--ticker", "-t", help="Ticker for analysis context"),
    refresh: bool = typer.Option(False, "--refresh", help="Force refresh data downloads"),
    json_out: bool = typer.Option(False, "--json", help="Machine-readable JSON output"),
    delta: str = typer.Option("", "--delta", help="Show changes vs N days ago (e.g., 7d, 1w, 1m)"),
    alert: bool = typer.Option(False, "--alert", help="Only output if regime is extreme (for cron/monitoring)"),
):
    """Agriculture & food inflation regime (crops, fertilizer, input costs)."""
    from lox.cli_commands.regimes.agriculture_cmd import agriculture_snapshot
    agriculture_snapshot(
        llm=llm, ticker=ticker, refresh=refresh,
        json_out=json_out, delta=delta, alert=alert,
    )


# Register unified / transitions directly on regime_app
from lox.cli_commands.regimes.regimes_cmd import register as _register_regimes
_register_regimes(regime_app)


# ---------------------------------------------------------------------------
# COMMAND REGISTRATION
# ---------------------------------------------------------------------------

_COMMANDS_REGISTERED = False


def _register_commands() -> None:
    global _COMMANDS_REGISTERED
    if _COMMANDS_REGISTERED:
        return
    
    # Research module (primary interface)
    from lox.cli_commands.research import register_research_commands
    register_research_commands(app)

    # Top-level `lox chat` alias (shortcut for `lox research chat`)
    from lox.cli_commands.research.chat_cmd import register as register_chat_alias
    register_chat_alias(app)
    
    # Core commands
    from lox.cli_commands.core.core_cmd import register_core
    from lox.cli_commands.core.pm_cmd import register_pm
    from lox.cli_commands.core.nav_cmd import register as register_nav
    from lox.cli_commands.core.account_cmd import register as register_account
    from lox.cli_commands.core.weekly_report_cmd import register as register_weekly_report
    from lox.cli_commands.core.investor_report_cmd import register as register_investor_report
    from lox.cli_commands.core.closed_trades_cmd import register as register_closed_trades
    from lox.cli_commands.core.suggest_cmd import register as register_suggest

    register_core(app)
    register_pm(app)
    register_suggest(app)
    register_closed_trades(app)
    register_nav(nav_app)
    register_account(app)
    register_weekly_report(weekly_app)
    register_investor_report(weekly_app)

    from lox.cli_commands.crypto.crypto_cmd import register as register_crypto
    register_crypto(crypto_app)

    _COMMANDS_REGISTERED = True


def main():
    _register_commands()
    app()


# Register on import
_register_commands()


if __name__ == "__main__":
    main()
