from __future__ import annotations

import typer
from rich import print

from ai_options_trader.config import StrategyConfig, RiskConfig, load_settings
from ai_options_trader.data.alpaca import make_clients, fetch_option_chain, to_candidates
from ai_options_trader.strategies.selector import choose_best_option, diagnose_selection
from ai_options_trader.utils.logging import log_event


def register(app: typer.Typer) -> None:
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


