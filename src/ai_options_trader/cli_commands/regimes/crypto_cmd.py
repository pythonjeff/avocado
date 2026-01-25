from __future__ import annotations

import typer
from rich import print
from rich.console import Console
from rich.panel import Panel

from ai_options_trader.config import load_settings
from ai_options_trader.data.market import fetch_crypto_daily_closes
from ai_options_trader.funding.signals import build_funding_state
from ai_options_trader.macro.regime import classify_macro_regime_from_state
from ai_options_trader.macro.signals import build_macro_state
from ai_options_trader.usd.signals import build_usd_state


def run_crypto_snapshot(
    *,
    symbol: str = "BTC/USD",
    benchmark: str = "",
    start: str = "2017-01-01",
    features: bool = False,
    json_out: bool = False,
    llm: bool = False,
) -> None:
    """Shared implementation for crypto snapshot."""
    from ai_options_trader.cli_commands.shared.labs_utils import handle_output_flags
    from ai_options_trader.crypto.snapshot import build_crypto_quant_snapshot
    from ai_options_trader.crypto.models import CryptoQuantSnapshot

    settings = load_settings()
    console = Console()

    if not settings.alpaca_api_key:
        console.print(Panel("[red]Missing Alpaca API keys[/red]", title="Error", expand=False))
        raise typer.Exit(code=1)

    try:
        px = fetch_crypto_daily_closes(
            api_key=settings.alpaca_data_key or settings.alpaca_api_key,
            api_secret=settings.alpaca_data_secret or settings.alpaca_api_secret,
            symbols=[symbol.upper()] + ([benchmark.upper()] if benchmark.strip() else []),
            start=start,
        )
        snap_dict = build_crypto_quant_snapshot(
            prices=px,
            symbol=symbol,
            benchmark=(benchmark.strip() or None),
        )
        snap = CryptoQuantSnapshot(**snap_dict)
    except Exception as e:
        console.print(Panel(f"[red]Failed to build crypto snapshot[/red]\n\n{e}", title="Error", expand=False))
        raise typer.Exit(code=1)

    # Build snapshot data
    snapshot_data = {
        "symbol": snap.symbol,
        "price": snap.price,
        "ret_1d": snap.ret_1d,
        "ret_7d": snap.ret_7d,
        "ret_30d": snap.ret_30d,
        "vol_30d": snap.vol_30d,
        "trend_60d": snap.trend_60d,
    }

    feature_dict = {
        "price": snap.price,
        "ret_1d": snap.ret_1d,
        "ret_7d": snap.ret_7d,
        "ret_30d": snap.ret_30d,
        "vol_30d": snap.vol_30d,
        "trend_60d": snap.trend_60d,
    }

    # Handle --features and --json flags
    if handle_output_flags(
        domain="crypto",
        snapshot=snapshot_data,
        features=feature_dict,
        regime=f"{symbol} trend: {snap.trend_60d}",
        regime_description=f"30d volatility: {snap.vol_30d:.1%}",
        asof=snap.asof,
        output_json=json_out,
        output_features=features,
    ):
        return

    # Standard output
    print(snap)

    if llm:
        from ai_options_trader.llm.core.analyst import llm_analyze_regime
        from rich.markdown import Markdown

        print("\n[bold cyan]Generating LLM analysis...[/bold cyan]\n")

        analysis = llm_analyze_regime(
            settings=settings,
            domain="crypto",
            snapshot=snapshot_data,
            regime_label=f"{symbol} trend: {snap.trend_60d}",
            regime_description=f"30d volatility: {snap.vol_30d:.1%}",
        )

        print(Panel(Markdown(analysis), title="Analysis", expand=False))


def register(crypto_app: typer.Typer) -> None:
    # Default callback so `lox labs crypto --llm` works without `snapshot`
    @crypto_app.callback(invoke_without_command=True)
    def crypto_default(
        ctx: typer.Context,
        symbol: str = typer.Option("BTC/USD", "--symbol", help='Crypto pair symbol, e.g. "BTC/USD"'),
        llm: bool = typer.Option(False, "--llm", help="Get LLM analysis with real-time data"),
        features: bool = typer.Option(False, "--features", help="Export ML-ready feature vector (JSON)"),
        json_out: bool = typer.Option(False, "--json", help="Machine-readable JSON output"),
    ):
        """Crypto snapshots and LLM outlooks"""
        if ctx.invoked_subcommand is None:
            run_crypto_snapshot(symbol=symbol, llm=llm, features=features, json_out=json_out)

    @crypto_app.command("snapshot")
    def crypto_snapshot(
        symbol: str = typer.Option("BTC/USD", "--symbol", help='Crypto pair symbol, e.g. "BTC/USD"'),
        benchmark: str = typer.Option("", "--benchmark", help='Optional benchmark pair, e.g. "ETH/USD"'),
        start: str = typer.Option("2017-01-01", "--start", help="Start date YYYY-MM-DD for price data"),
        features: bool = typer.Option(False, "--features", help="Export ML-ready feature vector (JSON)"),
        json_out: bool = typer.Option(False, "--json", help="Machine-readable JSON output"),
        llm: bool = typer.Option(False, "--llm", help="Get LLM analysis with real-time data"),
    ):
        """Compute and print a quantitative snapshot for a crypto pair (returns, trend, volatility)."""
        run_crypto_snapshot(
            symbol=symbol, benchmark=benchmark, start=start,
            features=features, json_out=json_out, llm=llm,
        )

    @crypto_app.command("outlook")
    def crypto_outlook(
        symbol: str = typer.Option("BTC/USD", "--symbol", help='Crypto pair symbol, e.g. "BTC/USD"'),
        benchmark: str = typer.Option("", "--benchmark", help='Optional benchmark pair, e.g. "ETH/USD"'),
        start: str = typer.Option("2017-01-01", "--start", help="Start date YYYY-MM-DD for data"),
        refresh: bool = typer.Option(False, "--refresh", help="Force refresh FRED downloads (regimes only)"),
        year: int = typer.Option(2026, "--year", help="Target year for outlook (e.g., 2026)"),
        llm_model: str = typer.Option("", "--llm-model", help="Override OPENAI_MODEL (optional)"),
        llm_temperature: float = typer.Option(0.2, "--llm-temperature", help="LLM temperature (0..2)"),
        cpi_target: float = typer.Option(3.0, "--cpi-target", help="Inflation stage threshold for CPI YoY (percent)"),
        infl_thresh: float = typer.Option(0.0, "--infl-thresh", help="Inflation threshold (z units if default mode; raw units if --raw)"),
        real_thresh: float = typer.Option(0.0, "--real-thresh", help="Real-yield threshold (z units if default mode; raw units if --raw)"),
    ):
        """
        Generate a 2026-focused crypto outlook combining:
        - crypto quant snapshot (Alpaca)
        - macro regime (FRED)
        - liquidity regime (FRED)
        - USD regime (FRED)
        """
        settings = load_settings()
        console = Console()

        if not settings.alpaca_api_key:
            console.print(Panel("[red]Missing Alpaca API keys[/red]", title="Error", expand=False))
            raise typer.Exit(code=1)
        if not settings.fred_api_key:
            console.print(Panel("[red]Missing FRED_API_KEY[/red]", title="Error", expand=False))
            raise typer.Exit(code=1)
        if not settings.openai_api_key:
            console.print(Panel("[red]Missing OPENAI_API_KEY[/red]", title="Error", expand=False))
            raise typer.Exit(code=1)

        # --- Crypto quant snapshot ---
        try:
            from ai_options_trader.crypto.snapshot import build_crypto_quant_snapshot

            px = fetch_crypto_daily_closes(
                api_key=settings.alpaca_data_key or settings.alpaca_api_key,
                api_secret=settings.alpaca_data_secret or settings.alpaca_api_secret,
                symbols=[symbol.upper()] + ([benchmark.upper()] if benchmark.strip() else []),
                start=start,
            )
            quant = build_crypto_quant_snapshot(prices=px, symbol=symbol, benchmark=(benchmark.strip() or None))
        except Exception as e:
            console.print(Panel(f"[red]Failed to build crypto quant snapshot[/red]\n\n{e}", title="Error", expand=False))
            raise typer.Exit(code=1)

        # --- Regimes ---
        macro_state = build_macro_state(settings=settings, start_date="2011-01-01", refresh=refresh)
        macro_regime = classify_macro_regime_from_state(
            cpi_yoy=macro_state.inputs.cpi_yoy,
            payrolls_3m_annualized=macro_state.inputs.payrolls_3m_annualized,
            inflation_momentum_minus_be5y=macro_state.inputs.inflation_momentum_minus_be5y,
            real_yield_proxy_10y=macro_state.inputs.real_yield_proxy_10y,
            z_inflation_momentum_minus_be5y=macro_state.inputs.components.get("z_infl_mom_minus_be5y") if macro_state.inputs.components else None,
            z_real_yield_proxy_10y=macro_state.inputs.components.get("z_real_yield_proxy_10y") if macro_state.inputs.components else None,
            use_zscores=True,
            cpi_target=cpi_target,
            infl_thresh=infl_thresh,
            real_thresh=real_thresh,
        )
        liquidity_state = build_funding_state(settings=settings, start_date="2011-01-01", refresh=refresh)
        usd_state = build_usd_state(settings=settings, start_date="2011-01-01", refresh=refresh)

        header = (
            f"Symbol: {symbol}\n"
            f"Quant asof: {quant.get('asof')}\n"
            f"Macro regime: {getattr(macro_regime, 'name', '')} (asof={macro_state.asof})\n"
            f"Liquidity score: {liquidity_state.inputs.liquidity_tightness_score} (asof={liquidity_state.asof})\n"
            f"USD score: {usd_state.inputs.usd_strength_score} (asof={usd_state.asof})\n"
            f"Model: {llm_model.strip() or settings.openai_model}"
        )
        console.print(Panel(header, title="Crypto Outlook", expand=False))

        try:
            from ai_options_trader.llm.outlooks.crypto_outlook import llm_crypto_outlook

            report = llm_crypto_outlook(
                settings=settings,
                symbol=symbol,
                quant_snapshot=quant,
                macro_state=macro_state,
                macro_regime=macro_regime,
                liquidity_state=liquidity_state,
                usd_state=usd_state,
                year=year,
                model=llm_model.strip() or None,
                temperature=float(llm_temperature),
            )
            console.print(Panel(report, title=f"{symbol} — Outlook into {year}", expand=False))
        except Exception as e:
            console.print(Panel(f"[red]LLM call failed[/red]\n\n{e}", title="Error", expand=False))
            raise typer.Exit(code=1)


