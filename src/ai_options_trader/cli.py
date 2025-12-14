from __future__ import annotations
import pandas as pd
import typer
from rich import print
from ai_options_trader.config import load_settings, Settings, StrategyConfig, RiskConfig
from ai_options_trader.data.alpaca import make_clients, fetch_option_chain, to_candidates
from ai_options_trader.strategy.selector import choose_best_option, diagnose_selection
from ai_options_trader.utils.logging import log_event
from ai_options_trader.macro.regime import classify_macro_regime

from ai_options_trader.macro.signals import build_macro_state

app = typer.Typer(add_completion=False, help="AI Options Trader CLI")
macro_app = typer.Typer(add_completion=False, help="Macro signals and datasets")
app.add_typer(macro_app, name="macro")


@app.command()
def select(
    ticker: str = typer.Option(..., "--ticker", "-t", help="Underlying ticker, e.g. NVDA"),
    sentiment: str = typer.Option("positive", "--sentiment", help="positive|negative"),
    target_dte: int = typer.Option(30, "--target-dte", help="Target days-to-expiry"),
    debug: bool = typer.Option(False, "--debug", help="Print filter diagnostics"),
):
    """Select an option contract based on sentiment + constraints."""
    settings = load_settings()
    trading, data = make_clients(settings)

    acct = trading.get_account()
    equity = float(acct.equity)

    chain = fetch_option_chain(data, ticker)
    if debug:
        print(f"[dim]Fetched option chain snapshots: {len(chain)}[/dim]")
    candidates = list(to_candidates(chain, ticker))
    if debug:
        print(f"[dim]Option candidates: {len(candidates)}[/dim]")
        oi_missing = sum(1 for c in candidates if c.oi is None)
        vol_missing = sum(1 for c in candidates if c.volume is None)
        if oi_missing or vol_missing:
            print(
                "[dim]"
                f"Snapshot fields missing: open_interest={oi_missing}/{len(candidates)} "
                f"volume={vol_missing}/{len(candidates)} "
                "(these thresholds are only enforced when present)"
                "[/dim]"
            )

    strat = StrategyConfig(target_dte_days=target_dte)
    risk = RiskConfig()
    want = "call" if sentiment.lower().startswith("pos") else "put"

    best = choose_best_option(candidates, ticker, want=want, equity_usd=equity, strat=strat, risk=risk)
    if not best:
        diag = diagnose_selection(candidates, ticker, want=want, equity_usd=equity, strat=strat, risk=risk)
        print("[red]No option matched filters.[/red]")
        print(
            "[dim]"
            f"Diagnostics: total={diag.total} occ_parsed={diag.occ_parsed} type_match={diag.type_match} "
            f"dte_match={diag.dte_match} has_delta={diag.has_delta} has_price={diag.has_price} "
            f"spread_ok={diag.spread_ok} liquidity_ok={diag.liquidity_ok} size_ok={diag.size_ok}"
            "[/dim]"
        )
        raise typer.Exit(code=1)

    log_event(
        "SELECTION",
        {
            "ticker": ticker,
            "want": want,
            "equity_usd": equity,
            "selected": best,
        },
    )

    print(
        f"\nSelected: {best.symbol} ({best.opt_type}) strike={best.strike} exp={best.expiry} "
        f"dte={best.dte_days} mid=${best.mid:.2f} Δ={best.delta:.3f}"
    )
    print(f"Contracts: {best.size.max_contracts} (budget=${best.size.budget_usd:,.2f})")


@macro_app.command("snapshot")
def macro_snapshot(
    start: str = typer.Option("2016-01-01", "--start", help="Start date YYYY-MM-DD"),
    refresh: bool = typer.Option(False, "--refresh", help="Force refresh FRED downloads"),
):
    """Print current macro state (inflation + rates + expectations)."""
    settings = load_settings()
    state = build_macro_state(settings=settings, start_date=start, refresh=refresh)
    print(state)
    regime = classify_macro_regime(
    inflation_momentum_minus_be=state.inputs.inflation_momentum_minus_be5y,
    real_yield=state.inputs.real_yield_proxy_10y,
)

    print("\nMACRO REGIME")
    print(regime)


@macro_app.command("equity-sensitivity")
def macro_equity_sensitivity(
    start: str = typer.Option("2016-01-01", "--start", help="Start date YYYY-MM-DD"),
    window: int = typer.Option(252, "--window", help="Rolling window (trading days)"),
    tickers: str = typer.Option("NVDA,AMD,MSFT,GOOGL", "--tickers", help="Comma-separated tickers"),
    benchmark: str = typer.Option("QQQ", "--benchmark", help="Benchmark ticker"),
    refresh: bool = typer.Option(False, "--refresh", help="Force refresh FRED downloads"),
):
    """
    Quantify how equities move with rates/inflation expectations.
    """
    from ai_options_trader.macro.signals import build_macro_dataset
    from ai_options_trader.macro.market import fetch_equity_daily_closes
    from ai_options_trader.macro.equity import returns, delta, latest_sensitivity_table

    settings = load_settings()

    # Macro dataset for rates/breakevens (daily)
    m = build_macro_dataset(settings=settings, start_date=start, refresh=refresh).set_index("date")

    # Build explanatory daily changes
    d_10y = delta(m["DGS10"]).rename("d_10y")
    d_real = delta(m["REAL_YIELD_PROXY_10Y"]).rename("d_real")
    d_be5 = delta(m["T5YIE"]).rename("d_be5")

    syms = [s.strip().upper() for s in tickers.split(",") if s.strip()]
    syms_all = sorted(set(syms + [benchmark.strip().upper()]))

    px = fetch_equity_daily_closes(
        api_key=settings.alpaca_data_key or settings.alpaca_api_key,
        api_secret=settings.alpaca_data_secret or settings.alpaca_api_secret,
        symbols=syms_all,
        start=start,
    )
    r = returns(px)

    # Build table
    tbl = latest_sensitivity_table(
        rets=r,
        d_real=d_real,
        d_10y=d_10y,
        d_be5y=d_be5,
        window=window,
    )

    print(tbl)

@macro_app.command("beta-adjusted-sensitivity")
def macro_beta_adjusted_sensitivity(
    start: str = typer.Option("2016-01-01", "--start"),
    window: int = typer.Option(252, "--window"),
    tickers: str = typer.Option("NVDA,AMD,MSFT,GOOGL", "--tickers"),
    benchmark: str = typer.Option("QQQ", "--benchmark"),
    refresh: bool = typer.Option(False, "--refresh"),
):
    """
    Compute beta-adjusted macro sensitivity for single-name equities.
    """
    from ai_options_trader.config import Settings
    from ai_options_trader.macro.signals import build_macro_dataset
    from ai_options_trader.macro.market import fetch_equity_daily_closes
    from ai_options_trader.macro.equity import returns, delta
    from ai_options_trader.macro.equity_beta_adjusted import (
        strip_market_beta,
        macro_sensitivity_on_residuals,
    )

    settings = Settings()

    # --- Macro data ---
    macro = build_macro_dataset(
        settings=settings,
        start_date=start,
        refresh=refresh,
    ).set_index("date")

    d_real = delta(macro["REAL_YIELD_PROXY_10Y"])
    d_nominal = delta(macro["DGS10"])
    d_be = delta(macro["T5YIE"])

    macro_changes = (
        pd.concat([d_real, d_nominal, d_be], axis=1)
        .rename(
            columns={
                "REAL_YIELD_PROXY_10Y": "real",
                "DGS10": "nominal",
                "T5YIE": "breakeven",
            }
        )
        .dropna()
    )

    # --- Equity data ---
    syms = [s.strip().upper() for s in tickers.split(",")]
    syms_all = sorted(set(syms + [benchmark]))

    px = fetch_equity_daily_closes(
        api_key=settings.ALPACA_API_KEY,
        api_secret=settings.ALPACA_API_SECRET,
        symbols=syms_all,
        start=start,
    )

    r = returns(px)

    tables = []

    for sym in syms:
        resid = strip_market_beta(
            stock_returns=r[sym],
            market_returns=r[benchmark],
            window=window,
        )

        sens = macro_sensitivity_on_residuals(
            residuals=resid.rename(sym),
            macro_changes=macro_changes,
            window=window,
        )

        latest = sens.iloc[-1].to_frame(name=sym)
        tables.append(latest)

    result = pd.concat(tables, axis=1).T
    print(result)



def main():
    app()


if __name__ == "__main__":
    main()
