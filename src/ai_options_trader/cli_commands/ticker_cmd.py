from __future__ import annotations

import typer
from rich import print
from rich.console import Console
from rich.panel import Panel
from rich.pretty import Pretty

from ai_options_trader.config import load_settings


def register(ticker_app: typer.Typer) -> None:
    @ticker_app.command("snapshot")
    def ticker_snapshot(
        ticker: str = typer.Option(..., "--ticker", "-t", help="Ticker symbol (e.g., AAPL)"),
        benchmark: str = typer.Option("SPY", "--benchmark", help="Benchmark symbol for relative strength (default SPY)"),
        start: str = typer.Option("2011-01-01", "--start", help="Start date YYYY-MM-DD"),
    ):
        """Print a quantitative snapshot for a ticker (returns, vol, drawdown, rel strength)."""
        settings = load_settings()
        from ai_options_trader.ticker.snapshot import build_ticker_snapshot

        snap = build_ticker_snapshot(settings=settings, ticker=ticker, benchmark=benchmark, start=start)
        print(snap)

    @ticker_app.command("outlook")
    def ticker_outlook(
        ticker: str = typer.Option(..., "--ticker", "-t", help="Ticker symbol (e.g., AAPL)"),
        benchmark: str = typer.Option("SPY", "--benchmark", help="Benchmark symbol for relative strength (default SPY)"),
        year: int = typer.Option(2026, "--year", help="Focus year for the outlook (e.g., 2026)"),
        start: str = typer.Option("2011-01-01", "--start", help="Start date YYYY-MM-DD"),
        refresh: bool = typer.Option(False, "--refresh", help="Force refresh FRED downloads (for regimes)"),
        llm_model: str = typer.Option("", "--llm-model", help="Override OPENAI_MODEL (optional)"),
        llm_temperature: float = typer.Option(0.2, "--llm-temperature", help="LLM temperature (0..2)"),
    ):
        """
        Ask an LLM for a 3/6/12 month outlook for a ticker, grounded in:
        - ticker quantitative snapshot (Alpaca daily closes)
        - current regimes (macro/liquidity/usd + optional tariff summary)
        """
        settings = load_settings()

        # --- Ticker snapshot ---
        from ai_options_trader.ticker.snapshot import build_ticker_snapshot

        snap = build_ticker_snapshot(settings=settings, ticker=ticker, benchmark=benchmark, start=start)

        # --- Regime context (keep it lightweight / non-leaky) ---
        from ai_options_trader.macro.signals import build_macro_state
        from ai_options_trader.macro.regime import classify_macro_regime_from_state
        from ai_options_trader.funding.signals import build_funding_state
        from ai_options_trader.usd.signals import build_usd_state

        macro_state = build_macro_state(settings=settings, start_date=start, refresh=refresh)
        macro_regime = classify_macro_regime_from_state(
            cpi_yoy=macro_state.inputs.cpi_yoy,
            payrolls_3m_annualized=macro_state.inputs.payrolls_3m_annualized,
            inflation_momentum_minus_be5y=macro_state.inputs.inflation_momentum_minus_be5y,
            real_yield_proxy_10y=macro_state.inputs.real_yield_proxy_10y,
            z_inflation_momentum_minus_be5y=macro_state.inputs.components.get("z_infl_mom_minus_be5y") if macro_state.inputs.components else None,
            z_real_yield_proxy_10y=macro_state.inputs.components.get("z_real_yield_proxy_10y") if macro_state.inputs.components else None,
            use_zscores=True,
            cpi_target=3.0,
            infl_thresh=0.0,
            real_thresh=0.0,
        )
        liq_state = build_funding_state(settings=settings, start_date=start, refresh=refresh)
        usd_state = build_usd_state(settings=settings, start_date=start, refresh=refresh)

        regimes = {
            "macro": {"state": macro_state.model_dump(), "regime": macro_regime.__dict__},
            "liquidity": liq_state.model_dump(),
            "usd": usd_state.model_dump(),
        }

        # --- LLM ---
        from ai_options_trader.llm.ticker_outlook import llm_ticker_outlook

        text = llm_ticker_outlook(
            settings=settings,
            ticker_snapshot=snap,
            regimes=regimes,
            year=int(year),
            model=llm_model.strip() or None,
            temperature=float(llm_temperature),
        )
        print(text)

    @ticker_app.command("dossier")
    def ticker_dossier(
        ticker: str = typer.Option(..., "--ticker", "-t", help="Ticker symbol (e.g., AAPL)"),
        days_ahead: int = typer.Option(180, "--days-ahead", help="How far ahead to look for next earnings (days)"),
    ):
        """
        Build a minimal alternative-data dossier for a ticker (start slow):
        - company profile (sector/industry/market cap)
        - next earnings date (if available)
        """
        settings = load_settings()
        from ai_options_trader.altdata.fmp import build_ticker_dossier

        d = build_ticker_dossier(settings=settings, ticker=ticker, days_ahead=int(days_ahead))
        Console().print(Panel(Pretty(d, expand_all=True), title=f"Dossier: {ticker.upper()}", expand=False))


