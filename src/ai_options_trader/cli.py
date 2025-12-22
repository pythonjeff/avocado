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

app = typer.Typer(add_completion=False, help="Lox — regime-aware options research & execution CLI")
macro_app = typer.Typer(add_completion=False, help="Macro signals and datasets")
app.add_typer(macro_app, name="macro")
tariff_app = typer.Typer(add_completion=False, help="Tariff / cost-push regime signals")
app.add_typer(tariff_app, name="tariff")
ideas_app = typer.Typer(add_completion=False, help="Trade idea generation from thesis + regimes")
app.add_typer(ideas_app, name="ideas")
track_app = typer.Typer(add_completion=False, help="Track recommendations, executions, and performance")
app.add_typer(track_app, name="track")



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


@app.command("ticker-outlook")
def ticker_outlook(
    ticker: str = typer.Option(..., "--ticker", "-t", help="Ticker, e.g. AAPL"),
    benchmark: str = typer.Option("SPY", "--benchmark", help="Benchmark ticker for relative strength (e.g. SPY, QQQ)"),
    price_start: str = typer.Option("2016-01-01", "--price-start", help="Start date for price history (YYYY-MM-DD)"),
    news_days: int = typer.Option(7, "--news-days", help="Lookback window for ticker news (days)"),
    fmp_pages: int = typer.Option(2, "--fmp-pages", help="Pages to fetch from FMP stock_news"),
    llm_model: str = typer.Option("", "--llm-model", help="Override OPENAI_MODEL (optional)"),
    llm_temperature: float = typer.Option(0.2, "--llm-temperature", help="LLM temperature"),
    options: bool = typer.Option(
        True,
        "--options/--no-options",
        help="Include high-level option structures aligned to the outlook (no exact strikes).",
    ),
    interactive: bool = typer.Option(
        False,
        "--interactive",
        help="Show suggested option legs and (optionally) submit paper orders after confirmation.",
    ),
    execute: bool = typer.Option(
        False,
        "--execute",
        help="When used with --interactive, allow submitting orders (still asks for confirmation).",
    ),
):
    """
    Single-ticker 3/6/12 month outlook combining:
    - quantitative ticker regime (trend/momentum/vol/relative strength)
    - macro regime (from FRED-based macro state)
    - recent ticker news (FMP stock_news)
    """
    from datetime import timedelta
    from typing import Any

    from rich.console import Console
    from rich.panel import Panel

    from ai_options_trader.data.market import fetch_equity_daily_closes
    from ai_options_trader.llm.ticker_news import fetch_fmp_stock_news, filter_items_since, utc_now as news_now
    from ai_options_trader.llm.ticker_outlook import (
        build_ticker_quant_snapshot,
        build_news_lookback_window,
        llm_ticker_full_outlook,
        llm_ticker_option_plan,
    )
    from ai_options_trader.macro.signals import build_macro_state
    from ai_options_trader.macro.regime import classify_macro_regime

    settings = load_settings()
    c = Console()

    t = ticker.strip().upper()
    b = benchmark.strip().upper()

    # --- Prices (Alpaca) ---
    try:
        px = fetch_equity_daily_closes(
            api_key=settings.alpaca_data_key or settings.alpaca_api_key,
            api_secret=settings.alpaca_data_secret or settings.alpaca_api_secret,
            symbols=sorted({t, b}),
            start=price_start,
        )
    except Exception as e:
        c.print(Panel(f"[red]Failed to fetch prices[/red]\n\n{e}", title="Error", expand=False))
        raise typer.Exit(code=1)

    try:
        quant = build_ticker_quant_snapshot(prices=px, ticker=t, benchmark=b)
    except Exception as e:
        c.print(Panel(f"[red]Failed to compute quant snapshot[/red]\n\n{e}", title="Error", expand=False))
        raise typer.Exit(code=1)

    # --- Macro regime (FRED) ---
    if not settings.fred_api_key:
        c.print(Panel("Missing FRED_API_KEY; cannot compute macro regime.", title="Error", expand=False))
        raise typer.Exit(code=1)
    macro_state = build_macro_state(settings=settings, start_date="2016-01-01", refresh=False)
    macro_regime = classify_macro_regime(
        inflation_momentum_minus_be=macro_state.inputs.inflation_momentum_minus_be5y or 0.0,
        real_yield=macro_state.inputs.real_yield_proxy_10y or 0.0,
    )

    # --- News (FMP) ---
    news_payload = []
    if settings.fmp_api_key:
        try:
            from_date, to_date = build_news_lookback_window(int(news_days))
            items = fetch_fmp_stock_news(
                settings=settings,
                tickers=[t],
                from_date=from_date,
                to_date=to_date,
                start_page=0,
                max_pages=int(fmp_pages),
            )
            # Tighten to the actual lookback window in hours based on published timestamps.
            since = news_now() - timedelta(days=int(news_days))
            items = filter_items_since(items, since)
            for i, it in enumerate(items[:50]):
                news_payload.append(
                    {
                        "i": i,
                        "published_at": it.published_at,
                        "title": it.title,
                        "source": it.source,
                        "url": it.url,
                        "snippet": (it.snippet[:500] if it.snippet else None),
                    }
                )
        except Exception as e:
            c.print(Panel(f"[yellow]FMP news fetch failed[/yellow]\n\n{e}", title="Warning", expand=False))
    else:
        c.print(Panel("FMP_API_KEY not set; proceeding without news items.", title="Info", expand=False))

    header = (
        f"Ticker: {t}\nBenchmark: {b}\n"
        f"Quant asof: {quant.get('asof')}\n"
        f"Macro regime: {getattr(macro_regime, 'name', '')} (asof={macro_state.asof})\n"
        f"News items: {len(news_payload)} (lookback={news_days}d)\n"
        f"Model: {llm_model.strip() or settings.openai_model}"
    )
    c.print(Panel(header, title="Ticker Outlook", expand=False))

    if not settings.openai_api_key:
        c.print(Panel("OPENAI_API_KEY is not set; cannot generate the outlook.", title="Error", expand=False))
        raise typer.Exit(code=1)

    # --- Option plan + concrete legs (optional, interactive) ---
    option_plan = []
    suggested_legs: list[dict[str, Any]] = []
    if interactive:
        if execute and not settings.alpaca_paper:
            c.print("[red]Refusing to submit orders because ALPACA_PAPER is false.[/red]")
            execute = False

        try:
            option_plan = llm_ticker_option_plan(
                settings=settings,
                quant=quant,
                macro_state=macro_state,
                macro_regime=macro_regime,
                news_items=news_payload,
                lookback_label=f"last {news_days} days",
                model=llm_model.strip() or None,
                temperature=float(llm_temperature),
            )
        except Exception as e:
            c.print(Panel(f"[yellow]Could not build option plan[/yellow]\n\n{e}", title="Warning", expand=False))
            option_plan = []

        if option_plan:
            from ai_options_trader.data.alpaca import make_clients, fetch_option_chain, to_candidates
            from ai_options_trader.strategy.selector import choose_best_option
            from ai_options_trader.config import StrategyConfig, RiskConfig

            trading, data_client = make_clients(settings)
            try:
                acct = trading.get_account()
                equity = float(acct.equity)
            except Exception:
                equity = 0.0

            try:
                chain = fetch_option_chain(data_client, t)
                candidates = list(to_candidates(chain, t))
            except Exception as e:
                c.print(Panel(f"[red]Failed to fetch option chain[/red]\n\n{e}", title="Error", expand=False))
                candidates = []

            for p in option_plan:
                want = None
                if p.bias.startswith("bull"):
                    want = "call"
                elif p.bias.startswith("bear"):
                    want = "put"
                else:
                    want = None

                if not want or not candidates:
                    suggested_legs.append(
                        {
                            "horizon_months": p.horizon_months,
                            "bias": p.bias,
                            "structure": p.structure,
                            "target_dte_days": p.target_dte_days,
                            "rationale": p.rationale,
                            "selected": None,
                            "note": "No directional leg selected (neutral bias or missing option chain).",
                        }
                    )
                    continue

                # DTE band: wide enough to find contracts around target.
                td = max(7, int(p.target_dte_days))
                strat = StrategyConfig(
                    target_dte_days=td,
                    dte_min=max(7, int(td * 0.6)),
                    dte_max=max(int(td * 1.4), int(td + 14)),
                )
                risk = RiskConfig()
                best = choose_best_option(
                    candidates,
                    t,
                    want=want,
                    equity_usd=equity if equity > 0 else 10000.0,
                    strat=strat,
                    risk=risk,
                )
                suggested_legs.append(
                    {
                        "horizon_months": p.horizon_months,
                        "bias": p.bias,
                        "structure": p.structure,
                        "target_dte_days": p.target_dte_days,
                        "rationale": p.rationale,
                        "selected": best,
                        "want": want,
                    }
                )

    try:
        report = llm_ticker_full_outlook(
            settings=settings,
            quant=quant,
            macro_state=macro_state,
            macro_regime=macro_regime,
            news_items=news_payload,
            lookback_label=f"last {news_days} days",
            model=llm_model.strip() or None,
            temperature=float(llm_temperature),
            include_options=bool(options),
        )
    except Exception as e:
        c.print(Panel(f"[red]LLM call failed[/red]\n\n{e}", title="Error", expand=False))
        raise typer.Exit(code=1)

    c.print(Panel(report or "(empty response)", title=f"{t} — 3/6/12m Outlook", expand=False))

    # Show selected concrete legs + optional execution flow
    if interactive and suggested_legs:
        from ai_options_trader.execution.alpaca import submit_option_order

        for leg in suggested_legs:
            sel = leg.get("selected")
            hm = leg.get("horizon_months")
            bias = leg.get("bias")
            structure = leg.get("structure")
            rationale = leg.get("rationale")

            if not sel:
                c.print(
                    Panel(
                        f"Horizon: {hm}m | Bias: {bias} | Structure: {structure}\n"
                        f"Rationale: {rationale}\n\n"
                        f"(No leg selected) {leg.get('note','')}",
                        title="Option leg",
                        expand=False,
                    )
                )
                continue

            # sel is an OptionCandidate-like dict from selector (already serializable in prior flows)
            symbol = sel.get("symbol") if isinstance(sel, dict) else getattr(sel, "symbol", None)
            mid = sel.get("mid") if isinstance(sel, dict) else getattr(sel, "mid", None)
            delta = sel.get("delta") if isinstance(sel, dict) else getattr(sel, "delta", None)
            dte = sel.get("dte_days") if isinstance(sel, dict) else getattr(sel, "dte_days", None)
            opt_type = sel.get("opt_type") if isinstance(sel, dict) else getattr(sel, "opt_type", None)
            contracts = None
            size = sel.get("size") if isinstance(sel, dict) else getattr(sel, "size", None)
            if isinstance(size, dict):
                contracts = size.get("max_contracts")
            else:
                contracts = getattr(size, "max_contracts", None) if size is not None else None

            body = (
                f"Horizon: {hm}m | Bias: {bias} | Structure: {structure}\n"
                f"Rationale: {rationale}\n\n"
                f"Selected leg: {symbol}\n"
                f"Type: {opt_type} | DTE: {dte} | Mid: {mid} | Δ: {delta}\n"
                f"Suggested qty: {contracts}\n"
            )
            c.print(Panel(body, title="Option leg (candidate)", expand=False))

            if execute and symbol:
                if not typer.confirm(f"Submit PAPER order for {symbol} now?", default=False):
                    continue
                qty = int(contracts or 1)
                if qty < 1:
                    qty = 1
                # Buy at mid by default if available, else market.
                limit_price = float(mid) if mid is not None else None
                try:
                    trading, _data = make_clients(settings)
                    resp = submit_option_order(
                        trading=trading,
                        symbol=str(symbol),
                        qty=qty,
                        side="buy",
                        limit_price=limit_price,
                        tif="day",
                    )
                    c.print(f"[green]Submitted[/green]: {resp}")
                except Exception as e:
                    c.print(Panel(f"[red]Submit failed[/red]\n\n{e}", title="Error", expand=False))


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
    from ai_options_trader.data.market import fetch_equity_daily_closes
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
    from ai_options_trader.data.market import fetch_equity_daily_closes
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


@app.command("regimes")
def regimes(
    start: str = typer.Option("2016-01-01", "--start", help="Start date YYYY-MM-DD"),
    refresh: bool = typer.Option(False, "--refresh", help="Force refresh FRED downloads"),
    benchmark: str = typer.Option("XLY", "--benchmark", help="Sector or market benchmark (e.g., XLY, SPY)"),
    baskets: str = typer.Option(
        "all",
        "--baskets",
        help="Comma-separated basket names, or 'all' (see: ai-options-trader tariff baskets)",
    ),
    llm: bool = typer.Option(False, "--llm", help="Ask an LLM to summarize regimes + follow-ups"),
    llm_model: str = typer.Option("", "--llm-model", help="Override OPENAI_MODEL (optional)"),
    llm_temperature: float = typer.Option(0.2, "--llm-temperature", help="LLM temperature (0..2)"),
):
    """
    Print the current macro regime and all tariff/cost-push regimes (by basket).
    """
    from ai_options_trader.data.fred import FredClient
    from ai_options_trader.data.market import fetch_equity_daily_closes
    from ai_options_trader.tariff.universe import BASKETS
    from ai_options_trader.tariff.proxies import DEFAULT_COST_PROXY_SERIES
    from ai_options_trader.tariff.signals import build_tariff_regime_state

    settings = load_settings()

    # --- Macro ---
    macro_state = build_macro_state(settings=settings, start_date=start, refresh=refresh)
    print(macro_state)
    macro_regime = classify_macro_regime(
        inflation_momentum_minus_be=macro_state.inputs.inflation_momentum_minus_be5y,
        real_yield=macro_state.inputs.real_yield_proxy_10y,
    )
    print("\nMACRO REGIME")
    print(macro_regime)

    # --- Tariff baskets selection ---
    if baskets.strip().lower() == "all":
        basket_names = list(BASKETS.keys())
    else:
        basket_names = [b.strip() for b in baskets.split(",") if b.strip()]

    unknown = [b for b in basket_names if b not in BASKETS]
    if unknown:
        raise typer.BadParameter(f"Unknown basket(s): {unknown}. Choose from: {list(BASKETS.keys())}")

    # --- Cost proxies (FRED) fetched once ---
    if not settings.FRED_API_KEY:
        raise RuntimeError("Missing FRED_API_KEY in environment / .env")
    fred = FredClient(api_key=settings.FRED_API_KEY)

    frames = []
    for col, sid in DEFAULT_COST_PROXY_SERIES.items():
        df = fred.fetch_series(sid, start_date=start, refresh=refresh)
        df = df.rename(columns={"value": col}).set_index("date")
        frames.append(df[[col]])
    cost_df = pd.concat(frames, axis=1).sort_index().resample("D").ffill()

    # --- Equities (Alpaca) fetched once ---
    all_universe = sorted({sym for b in basket_names for sym in BASKETS[b].tickers})
    symbols = sorted(set(all_universe + [benchmark.strip().upper()]))
    px = fetch_equity_daily_closes(
        api_key=settings.ALPACA_DATA_KEY or settings.ALPACA_API_KEY,
        api_secret=settings.ALPACA_DATA_SECRET or settings.ALPACA_API_SECRET,
        symbols=symbols,
        start=start,
    )
    px = px.sort_index().ffill().dropna(how="all")

    print("\nTARIFF / COST-PUSH REGIMES")
    tariff_results = []
    for b in basket_names:
        basket = BASKETS[b]
        print(f"\n[b]{basket.name}[/b] — {basket.description}")
        state = build_tariff_regime_state(
            cost_df=cost_df,
            equity_prices=px,
            universe=basket.tickers,
            benchmark=benchmark,
            basket_name=basket.name,
            start_date=start,
        )
        print(state)
        tariff_results.append(
            {
                "basket": basket.name,
                "description": basket.description,
                "benchmark": benchmark,
                "state": state,
            }
        )

    if llm:
        from ai_options_trader.llm.regime_summary import llm_regime_summary

        print("\nLLM SUMMARY")
        summary = llm_regime_summary(
            settings=settings,
            macro_state=macro_state,
            macro_regime=macro_regime,
            tariff_regimes=tariff_results,
            model=llm_model.strip() or None,
            temperature=float(llm_temperature),
        )
        print(summary)


@tariff_app.command("baskets")
def tariff_baskets():
    """List available tariff baskets."""
    from ai_options_trader.tariff.universe import BASKETS

    for name, b in BASKETS.items():
        print(f"- {name}: {b.description} (tickers={','.join(b.tickers)})")


@ideas_app.command("ai-bubble")
def ideas_ai_bubble(
    start: str = typer.Option("2016-01-01", "--start"),
    refresh: bool = typer.Option(False, "--refresh"),
    macro_window: int = typer.Option(252, "--macro-window", help="Rolling window (trading days) for sensitivity"),
    macro_benchmark: str = typer.Option("QQQ", "--macro-benchmark"),
    tariff_benchmark: str = typer.Option("XLY", "--tariff-benchmark"),
    tariff_baskets: str = typer.Option("all", "--tariff-baskets", help="Comma-separated or 'all'"),
    tech_tickers: str = typer.Option("", "--tech-tickers", help="Override AI/tech universe (comma-separated)"),
    top: int = typer.Option(12, "--top", help="Number of ideas to print"),
    with_legs: bool = typer.Option(False, "--with-legs", help="Fetch option chains and pick best leg per idea"),
    target_dte: int = typer.Option(30, "--target-dte", help="Target days-to-expiry for option selection"),
    interactive: bool = typer.Option(
        False,
        "--interactive",
        help="Show one idea at a time and (optionally) submit paper orders after confirmation",
    ),
    execute: bool = typer.Option(
        False,
        "--execute",
        help="When used with --interactive, allow submitting orders (still asks for confirmation)",
    ),
):
    """
    Generate option-trading ideas for the thesis:
    AI bubble + inflation underpriced in tech + tariffs underpriced in import-exposed stocks.
    """
    from rich.table import Table
    from rich.console import Console
    from rich.panel import Panel
    from rich.text import Text
    from ai_options_trader.ideas.ai_bubble import build_ai_bubble_ideas
    from ai_options_trader.tracking.store import TrackerStore, default_tracker_db_path

    settings = load_settings()
    tracker = TrackerStore(default_tracker_db_path())
    run_id = tracker.new_run_id()

    if tariff_baskets.strip().lower() == "all":
        basket_list = None
    else:
        basket_list = [b.strip() for b in tariff_baskets.split(",") if b.strip()]

    tech_list = [t.strip().upper() for t in tech_tickers.split(",") if t.strip()] or None

    try:
        _ctx, ideas = build_ai_bubble_ideas(
            settings=settings,
            start_date=start,
            refresh=refresh,
            macro_window=macro_window,
            macro_benchmark=macro_benchmark,
            tariff_benchmark=tariff_benchmark,
            tariff_baskets=basket_list,
            tech_tickers=tech_list,
        )
    except Exception as e:
        # Keep output readable; point to likely causes.
        Console().print(
            Panel(
                f"[red]Failed to build ideas.[/red]\n\n{e}\n\n"
                "Common fixes:\n"
                "- Re-run (FRED occasionally times out)\n"
                "- Try `--refresh` if your cache is stale\n"
                "- Ensure `FRED_API_KEY` is set\n",
                title="Error",
            )
        )
        raise typer.Exit(code=1)

    ideas = ideas[: max(1, int(top))]

    # Option legs (optional)
    if with_legs:
        trading, data = make_clients(settings)
        equity_usd = float(trading.get_account().equity)
        strat = StrategyConfig(target_dte_days=target_dte)
        risk = RiskConfig()

        for idea in ideas:
            want = "put" if idea.direction == "bearish" else "call"
            chain = fetch_option_chain(data, idea.ticker)
            candidates = list(to_candidates(chain, idea.ticker))
            best = choose_best_option(
                candidates,
                idea.ticker,
                want=want,
                equity_usd=equity_usd,
                strat=strat,
                risk=risk,
            )
            if best:
                idea.option_leg = {
                    "symbol": best.symbol,
                    "type": best.opt_type,
                    "expiry": str(best.expiry),
                    "strike": best.strike,
                    "dte_days": best.dte_days,
                    "mid": best.mid,
                    "delta": best.delta,
                    "gamma": best.gamma,
                    "theta": best.theta,
                    "vega": best.vega,
                    "iv": best.iv,
                    "contracts": best.size.max_contracts,
                    "budget_usd": best.size.budget_usd,
                }

    # Always log recommendations (one row per idea) so we can track later.
    reco_ids: dict[str, str] = {}
    for idea in ideas:
        reco_id = tracker.log_recommendation(
            run_id=run_id,
            ticker=idea.ticker,
            direction=idea.direction,
            score=float(idea.score),
            tags=list(idea.tags),
            thesis=idea.thesis,
            rationale=idea.rationale,
            why=dict(idea.why or {}),
            option_leg=dict(idea.option_leg) if idea.option_leg else None,
        )
        reco_ids[idea.ticker] = reco_id

    # Interactive: one idea at a time
    if interactive:
        console = Console()
        if execute:
            from ai_options_trader.execution.alpaca import submit_option_order

        for i, idea in enumerate(ideas, start=1):
            why = idea.why or {}
            macro = why.get("macro", {})
            tech = why.get("tech_sensitivity", {})
            tariff = why.get("tariff", {})
            comps = why.get("score_components", {})

            body = Text()
            body.append(f"Rank: {i}/{len(ideas)}\n", style="bold")
            body.append(f"Ticker: {idea.ticker} | Direction: {idea.direction} | Score: {idea.score:.2f}\n\n")
            body.append("WHY THIS IDEA\n", style="bold")
            if macro:
                body.append(
                    f"- Macro regime: {macro.get('regime')} (infl={macro.get('infl_trend')}, real={macro.get('real_yield_trend')})\n"
                )
                if macro.get("z_infl_mom_minus_be5y") is not None:
                    body.append(f"- z(infl mom - BE5y): {macro.get('z_infl_mom_minus_be5y'):.2f}\n")
            if tech:
                br = tech.get("beta_d_real")
                rp = tech.get("rank_pct")
                body.append(f"- Tech sensitivity: beta_d_real={br:.4f} | rank={rp:.0%}\n" if br is not None else "")
            if tariff and tariff.get("baskets"):
                bs = tariff.get("baskets", [])
                body.append("- Tariff exposure:\n")
                for b in bs:
                    body.append(
                        f"  - {b.get('basket')}: is_regime={b.get('is_tariff_regime')} score={b.get('tariff_regime_score')}\n"
                    )
            if comps:
                body.append("\nSCORE BREAKDOWN\n", style="bold")
                for k, v in comps.items():
                    body.append(f"- {k}: {float(v):.2f}\n")

            body.append("\nRECOMMENDED STRUCTURE\n", style="bold")
            body.append(
                "Put debit spread (starter workflow: select a liquid long put leg first)\n"
                if idea.direction == "bearish"
                else "Call (starter)\n"
            )

            leg = idea.option_leg
            body.append("\nOPTION LEG\n", style="bold")
            if leg:
                body.append(
                    f"- {leg['symbol']} exp={leg['expiry']} strike={leg['strike']} dte={leg['dte_days']} mid=${leg['mid']:.2f}\n"
                )
                body.append(
                    f"- Δ={leg.get('delta'):.3f} Γ={leg.get('gamma')} Θ={leg.get('theta')} ν={leg.get('vega')} IV={leg.get('iv')}\n"
                )
                body.append(f"- Suggested qty={leg['contracts']} (budget=${leg['budget_usd']:,.2f})\n")
            else:
                body.append("- (run with --with-legs to select an options leg)\n")

            console.print(Panel(body, title="Idea", expand=False))

            if execute and leg:
                if not settings.ALPACA_PAPER:
                    console.print("[red]Refusing to submit orders because ALPACA_PAPER is false.[/red]")
                else:
                    if typer.confirm("Submit this order to Alpaca PAPER now?", default=False):
                        qty = int(leg["contracts"]) if leg.get("contracts") else 1
                        if qty < 1:
                            qty = 1
                        # Use a limit at mid by default
                        resp = submit_option_order(
                            trading=trading,
                            symbol=str(leg["symbol"]),
                            qty=qty,
                            side="buy",
                            limit_price=float(leg["mid"]),
                            tif="day",
                        )
                        console.print(f"[green]Submitted[/green]: {resp}")
                        # Track execution by linking to the recommendation we just logged.
                        reco_id = reco_ids.get(idea.ticker)
                        if reco_id:
                            tracker.log_execution(
                                recommendation_id=reco_id,
                                alpaca_order_id=str(resp.id),
                                symbol=str(resp.symbol),
                                qty=int(qty),
                                side=str(resp.side),
                                order_type=str(resp.order_type),
                                limit_price=float(getattr(resp, "limit_price", None) or leg.get("mid")),
                                status=str(resp.status),
                                filled_qty=int(getattr(resp, "filled_qty", 0) or 0),
                                filled_avg_price=float(getattr(resp, "filled_avg_price", 0) or 0) or None,
                                filled_at=str(getattr(resp, "filled_at", None) or "") or None,
                                raw=resp.model_dump() if hasattr(resp, "model_dump") else str(resp),
                            )

            if i < len(ideas):
                if not typer.confirm("Next idea?", default=True):
                    break
        return

    # Print table
    tbl = Table(title="AI Bubble / Inflation / Tariff Thesis — Idea List")
    tbl.add_column("Ticker", style="bold")
    tbl.add_column("Direction")
    tbl.add_column("Score", justify="right")
    tbl.add_column("Tags")
    tbl.add_column("Why (short)")
    tbl.add_column("Structure")
    if with_legs:
        tbl.add_column("Leg (greeks)")

    for idea in ideas:
        structure = "Put debit spread" if idea.direction == "bearish" else "Call"
        why = idea.why or {}
        macro = why.get("macro", {})
        tech = why.get("tech_sensitivity", {})
        tariff = why.get("tariff", {})
        short_bits = []
        if macro.get("regime"):
            short_bits.append(f"macro={macro.get('regime')}")
        if tech.get("beta_d_real") is not None:
            short_bits.append(f"β_real={tech.get('beta_d_real'):.2f}")
        if tariff.get("baskets"):
            short_bits.append(f"tariff={len(tariff.get('baskets'))}b")
        why_short = " ".join(short_bits) if short_bits else "—"
        row = [
            idea.ticker,
            idea.direction,
            f"{idea.score:.2f}",
            ",".join(idea.tags),
            why_short,
            structure,
        ]
        if with_legs:
            leg = idea.option_leg
            if leg:
                row.append(f"{leg['symbol']} Δ={leg.get('delta'):.2f} mid=${leg.get('mid'):.2f}")
            else:
                row.append("—")
        tbl.add_row(*row)

    Console().print(tbl)
    print("\nNotes:")
    print("- These are research ideas, not advice. Use defined-risk spreads and size conservatively.")
    print("- Use `--with-legs` to pull current option chains and select a liquid leg per idea.")
    print("- Use `--interactive --with-legs --execute` for a one-by-one review + optional paper execution.")
    print(f"- This run logged to tracker DB: {default_tracker_db_path()} (run_id={run_id})")


@track_app.command("recent")
def track_recent(limit: int = typer.Option(20, "--limit")):
    """Show recent recommendations and executions from the local tracker DB."""
    from rich.table import Table
    from rich.console import Console
    from ai_options_trader.tracking.store import TrackerStore, default_tracker_db_path

    store = TrackerStore(default_tracker_db_path())
    recos = store.list_recent_recommendations(limit=limit)
    execs = store.list_recent_executions(limit=limit)

    t1 = Table(title="Recent recommendations")
    t1.add_column("created_at")
    t1.add_column("ticker")
    t1.add_column("dir")
    t1.add_column("score")
    t1.add_column("tags")
    for r in recos:
        t1.add_row(r.created_at[:19], r.ticker, r.direction, f"{r.score:.2f}", _json_short(r.tags_json))

    t2 = Table(title="Recent executions")
    t2.add_column("created_at")
    t2.add_column("symbol")
    t2.add_column("qty")
    t2.add_column("status")
    t2.add_column("order_id")
    for e in execs:
        t2.add_row(e.created_at[:19], e.symbol, str(e.qty), e.status, e.alpaca_order_id)

    c = Console()
    c.print(t1)
    c.print(t2)


def _json_short(s: str) -> str:
    import json

    try:
        obj = json.loads(s)
        if isinstance(obj, list):
            return ",".join(str(x) for x in obj)
        return str(obj)
    except Exception:
        return s


@track_app.command("sync")
def track_sync(limit: int = typer.Option(50, "--limit", help="Max executions to sync (most recent first)")):
    """
    Sync recent executions with Alpaca to update status/fills in the local tracker DB.
    """
    from rich.console import Console
    from ai_options_trader.tracking.store import TrackerStore, default_tracker_db_path

    settings = load_settings()
    trading, _data = make_clients(settings)

    store = TrackerStore(default_tracker_db_path())
    execs = store.list_recent_executions(limit=limit)

    c = Console()
    updated = 0
    for e in execs:
        try:
            o = trading.get_order_by_id(e.alpaca_order_id)
        except Exception as ex:
            c.print(f"[yellow]WARN[/yellow] could not fetch order {e.alpaca_order_id}: {ex}")
            continue

        store.update_execution_from_alpaca(
            alpaca_order_id=e.alpaca_order_id,
            status=str(getattr(o, "status", "")),
            filled_qty=int(getattr(o, "filled_qty", 0) or 0),
            filled_avg_price=float(getattr(o, "filled_avg_price", 0) or 0) or None,
            filled_at=str(getattr(o, "filled_at", None) or "") or None,
            raw=o.model_dump() if hasattr(o, "model_dump") else str(o),
        )
        updated += 1

    c.print(f"[green]Synced[/green] {updated} execution(s) into {default_tracker_db_path()}")


@track_app.command("report")
def track_report():
    """
    Show a quick performance snapshot for tracked option symbols using Alpaca positions.
    """
    from rich.table import Table
    from rich.console import Console
    from ai_options_trader.tracking.store import TrackerStore, default_tracker_db_path

    settings = load_settings()
    trading, _data = make_clients(settings)
    store = TrackerStore(default_tracker_db_path())

    # Pull current positions (includes unrealized P/L on Alpaca)
    try:
        positions = trading.get_all_positions()
    except Exception as e:
        raise RuntimeError(f"Failed to fetch Alpaca positions: {e}")

    pos_by_symbol = {p.symbol: p for p in positions}

    execs = store.list_recent_executions(limit=200)
    symbols = sorted({e.symbol for e in execs})

    tbl = Table(title="Tracked performance (current positions)")
    tbl.add_column("symbol", style="bold")
    tbl.add_column("qty", justify="right")
    tbl.add_column("avg_entry", justify="right")
    tbl.add_column("current", justify="right")
    tbl.add_column("uPL", justify="right")
    tbl.add_column("uPL%", justify="right")

    for sym in symbols:
        p = pos_by_symbol.get(sym)
        if not p:
            continue
        qty = getattr(p, "qty", "")
        avg = getattr(p, "avg_entry_price", None)
        cur = getattr(p, "current_price", None)
        upl = getattr(p, "unrealized_pl", None)
        uplpc = getattr(p, "unrealized_plpc", None)
        tbl.add_row(
            sym,
            str(qty),
            f"{float(avg):.2f}" if avg is not None else "—",
            f"{float(cur):.2f}" if cur is not None else "—",
            f"{float(upl):.2f}" if upl is not None else "—",
            f"{float(uplpc)*100:.1f}%" if uplpc is not None else "—",
        )

    Console().print(tbl)


@tariff_app.command("snapshot")
def tariff_snapshot(
    basket: str = typer.Option("import_retail_apparel", "--basket"),
    start: str = typer.Option("2016-01-01", "--start"),
    benchmark: str = typer.Option("XLY", "--benchmark", help="Sector or market benchmark (e.g., XLY, SPY)"),
    refresh: bool = typer.Option(False, "--refresh"),
):
    """
    Compute tariff/cost-push regime snapshot for an import-exposed basket.
    """
    from ai_options_trader.data.fred import FredClient
    from ai_options_trader.data.market import fetch_equity_daily_closes
    from ai_options_trader.tariff.universe import BASKETS
    from ai_options_trader.tariff.proxies import DEFAULT_COST_PROXY_SERIES
    from ai_options_trader.tariff.signals import build_tariff_regime_state

    settings = load_settings()

    if basket not in BASKETS:
        raise typer.BadParameter(f"Unknown basket: {basket}. Choose from: {list(BASKETS.keys())}")

    universe = BASKETS[basket].tickers

    # --- Cost proxies (FRED) ---
    fred = FredClient(api_key=settings.FRED_API_KEY)

    frames = []
    for col, sid in DEFAULT_COST_PROXY_SERIES.items():
        df = fred.fetch_series(sid, start_date=start, refresh=refresh)
        df = df.rename(columns={"value": col}).set_index("date")
        frames.append(df[[col]])

    cost_df = pd.concat(frames, axis=1).sort_index()

    # Align to daily for merging with equities
    cost_df = cost_df.resample("D").ffill()

    # --- Equities (Alpaca) ---
    symbols = sorted(set(universe + [benchmark]))
    px = fetch_equity_daily_closes(
        api_key=settings.ALPACA_DATA_KEY or settings.ALPACA_API_KEY,
        api_secret=settings.ALPACA_DATA_SECRET or settings.ALPACA_API_SECRET,
        symbols=symbols,
        start=start,
    )
    px = px.sort_index().ffill().dropna(how="all")

    state = build_tariff_regime_state(
        cost_df=cost_df,
        equity_prices=px,
        universe=universe,
        benchmark=benchmark,
        basket_name=basket,
        start_date=start,
    )

    print(state)


def main():
    app()


if __name__ == "__main__":
    main()
