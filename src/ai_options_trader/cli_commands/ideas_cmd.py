from __future__ import annotations

import typer
from rich import print

from ai_options_trader.config import StrategyConfig, RiskConfig, load_settings
from ai_options_trader.data.alpaca import make_clients, fetch_option_chain, to_candidates
from ai_options_trader.strategy.selector import choose_best_option
from ai_options_trader.options.targets import required_underlying_move_for_profit_pct, format_required_move
from ai_options_trader.data.quotes import fetch_stock_last_prices


def register(ideas_app: typer.Typer) -> None:
    @ideas_app.command("event")
    def ideas_event(
        url: str = typer.Option("", "--url", help="News/article URL (lox will fetch and extract text)"),
        text: str = typer.Option("", "--text", help="Paste event text directly (skips fetching URL)"),
        thesis: str = typer.Option(
            "",
            "--thesis",
            help="Your context in plain English (e.g., 'tariff refund ruling could force extra Treasury borrowing')",
        ),
        basket: str = typer.Option("starter", "--basket", help="starter|extended (universe for idea generation)"),
        focus: str = typer.Option("treasuries", "--focus", help="treasuries|equities|usd|vol (prompt hint)"),
        direction: str = typer.Option("short", "--direction", help="short|hedge (prompt hint)"),
        max_trades: int = typer.Option(3, "--max-trades", help="Max ideas to propose"),
        max_premium_usd: float = typer.Option(150.0, "--max-premium", help="Max option premium per contract (USD)"),
        execute: bool = typer.Option(False, "--execute", help="If set, ask to submit recommended trades to Alpaca (paper by default; use --live for live)"),
        live: bool = typer.Option(False, "--live", help="Allow LIVE execution when ALPACA_PAPER is false (guarded with extra confirmations)"),
        llm_model: str = typer.Option("", "--llm-model", help="Override OPENAI_MODEL (optional)"),
        llm_temperature: float = typer.Option(0.2, "--llm-temperature", help="LLM temperature (0..2)"),
    ):
        """
        Turn a news/event link (or pasted text) into short/hedge trade ideas.

        Example:
          lox ideas event --url "<link>" --thesis "court ruling could force Treasury to refund tariffs -> more borrowing"
        """
        from rich.console import Console
        from rich.panel import Panel
        from rich.table import Table
        from ai_options_trader.config import load_settings
        try:
            from ai_options_trader.portfolio.universe import get_universe
        except Exception:  # pragma: no cover
            # Back-compat for environments that haven't picked up the extended universe helper yet.
            from ai_options_trader.portfolio.universe import STARTER_UNIVERSE, DEFAULT_UNIVERSE

            def get_universe(name: str):
                n = (name or "starter").strip().lower()
                if n.startswith("d"):
                    return DEFAULT_UNIVERSE
                return STARTER_UNIVERSE
        from ai_options_trader.llm.url_tools import fetch_url_text
        from ai_options_trader.llm.event_trade_ideas import llm_event_trade_ideas_json
        from ai_options_trader.data.alpaca import make_clients, fetch_option_chain, to_candidates
        from ai_options_trader.strategy.selector import choose_best_option
        from ai_options_trader.config import StrategyConfig, RiskConfig

        settings = load_settings()
        c = Console()

        if not thesis.strip():
            thesis_use = "Generate short/hedge trade ideas consistent with the event."
        else:
            thesis_use = thesis.strip()

        if text.strip():
            event_text = text.strip()
            event_url = url.strip() or None
        elif url.strip():
            event_url = url.strip()
            try:
                event_text = fetch_url_text(event_url)
            except Exception as e:
                raise RuntimeError(f"Failed to fetch/parse URL: {e}")
        else:
            raise typer.BadParameter("Provide --url or --text")

        uni = get_universe(basket)
        universe = list(uni.basket_equity)

        obj = llm_event_trade_ideas_json(
            settings=settings,
            event_text=event_text,
            event_url=event_url,
            user_thesis=thesis_use,
            focus=focus,
            direction=direction,
            universe=universe,
            max_trades=int(max_trades),
            max_premium_usd=float(max_premium_usd),
            model=llm_model.strip() or None,
            temperature=float(llm_temperature),
        )

        c.print(Panel(f"Universe: {basket} ({len(universe)} tickers)\nFocus: {focus}  Direction: {direction}", title="Event context", expand=False))
        # Print structured summary + trade table
        summary = obj.get("event_summary") or []
        assumptions = obj.get("assumptions") or []
        trades = obj.get("trades") or []
        body = ""
        if summary:
            body += "Event summary:\n- " + "\n- ".join(str(x) for x in summary[:6]) + "\n\n"
        if assumptions:
            body += "Assumptions:\n- " + "\n- ".join(str(x) for x in assumptions[:10]) + "\n"
        if body.strip():
            c.print(Panel(body.strip(), title="LLM brief (structured)", expand=False))

        tbl = Table(title="Event trade ideas (proposed)")
        tbl.add_column("priority", justify="right")
        tbl.add_column("underlying", style="bold")
        tbl.add_column("action")
        tbl.add_column("target_dte", justify="right")
        tbl.add_column("max_premium", justify="right")
        tbl.add_column("rationale")
        for t in trades[: int(max_trades)]:
            tbl.add_row(
                str(t.get("priority") or ""),
                str(t.get("underlying") or ""),
                str(t.get("action") or ""),
                str(t.get("target_dte_days") or "—"),
                f"${float(t.get('max_premium_usd') or max_premium_usd):.0f}",
                str(t.get("rationale") or "")[:80],
            )
        c.print(tbl)

        if not execute:
            return

        # --- Execution guardrails (paper vs live) ---
        trading, data = make_clients(settings)
        acct = trading.get_account()
        equity = float(getattr(acct, "equity", 0.0) or 0.0)
        cash = float(getattr(acct, "cash", 0.0) or 0.0)
        bp = float(getattr(acct, "buying_power", 0.0) or 0.0)

        live_ok = bool(live) and (not bool(settings.alpaca_paper))
        if execute and (not settings.alpaca_paper) and (not live_ok):
            c.print(
                Panel(
                    "[red]Refusing to execute[/red] because ALPACA_PAPER is false.\n"
                    "If you intend LIVE trading, re-run with [b]--live --execute[/b].",
                    title="Safety",
                    expand=False,
                )
            )
            raise typer.Exit(code=1)

        label = "LIVE" if live_ok else "PAPER"
        c.print(Panel(f"Mode: {label}\nEquity=${equity:,.2f} Cash=${cash:,.2f} BuyingPower=${bp:,.2f}", title="Account", expand=False))

        if execute and live_ok:
            c.print(
                Panel(
                    "[yellow]LIVE MODE ENABLED[/yellow]\n"
                    "Orders will be submitted to your LIVE Alpaca account.\n"
                    "You will be asked to confirm each action.",
                    title="Safety",
                    expand=False,
                )
            )
            if not typer.confirm("Confirm LIVE mode (ALPACA_PAPER=false) and proceed?", default=False):
                raise typer.Exit(code=0)
            if not typer.confirm("Second confirmation: proceed with LIVE trading actions in this run?", default=False):
                raise typer.Exit(code=0)

        from ai_options_trader.execution.alpaca import submit_option_order, submit_equity_order
        from ai_options_trader.data.market import fetch_equity_daily_closes

        for t in trades[: int(max_trades)]:
            underlying = str(t.get("underlying") or "").strip().upper()
            action = str(t.get("action") or "").strip().upper()
            if not underlying or underlying not in set(universe):
                c.print(f"[yellow]Skip[/yellow] invalid underlying: {underlying!r}")
                continue

            # Risk sizing knobs
            target_dte = int(t.get("target_dte_days") or 60)
            prem_cap = float(t.get("max_premium_usd") or max_premium_usd)
            strat = StrategyConfig(target_dte_days=int(target_dte))
            risk = RiskConfig(max_premium_per_contract=float(prem_cap) / 100.0)

            # Underlying "current" price (best-effort: latest daily close).
            und_px = None
            try:
                px = fetch_equity_daily_closes(settings=settings, symbols=[underlying], start="2025-01-01")
                if underlying in px.columns and not px[underlying].dropna().empty:
                    und_px = float(px[underlying].dropna().iloc[-1])
            except Exception:
                und_px = None

            if action in {"BUY_PUT", "BUY_CALL"}:
                want = "put" if action == "BUY_PUT" else "call"
                try:
                    chain = fetch_option_chain(data, underlying, feed=settings.alpaca_options_feed)
                    candidates = list(to_candidates(chain, underlying))
                except Exception as e:
                    c.print(f"[red]Failed to fetch option chain[/red] for {underlying}: {e}")
                    continue

                best = choose_best_option(candidates, underlying, want=want, equity_usd=float(equity), strat=strat, risk=risk)
                if not best:
                    c.print(f"[yellow]No option matched filters[/yellow] for {underlying} ({want}); try adjusting --max-premium/--llm-thesis.")
                    continue

                qty = 1  # conservative default; user can re-run or manually size
                # Breakeven at expiry (best-effort, for single long call/put):
                profit_if = "—"
                try:
                    if best.opt_type == "call":
                        be = float(best.strike) + float(best.mid)
                        profit_if = f"profit if und > ${be:.2f} @ expiry"
                    elif best.opt_type == "put":
                        be = float(best.strike) - float(best.mid)
                        profit_if = f"profit if und < ${be:.2f} @ expiry"
                except Exception:
                    profit_if = "—"

                # Required underlying move for +5% option profit (delta-only approximation)
                und_live = None
                try:
                    last_px, _asof_map, _src = fetch_stock_last_prices(settings=settings, symbols=[underlying], max_symbols_for_live=5)
                    und_live = last_px.get(underlying)
                except Exception:
                    und_live = None
                und_for_calc = und_live if und_live is not None else und_px
                move5 = required_underlying_move_for_profit_pct(
                    opt_entry_price=float(best.mid),
                    delta=float(best.delta),
                    profit_pct=0.05,
                    underlying_px=und_for_calc,
                    opt_type=str(best.opt_type),
                )
                c.print(
                    Panel(
                        f"{underlying}: {action}\n"
                        f"Selected: {best.symbol} dte={best.dte_days} mid=${best.mid:.2f} Δ={best.delta:.3f}\n"
                        f"Underlying≈{('—' if und_for_calc is None else f'${und_for_calc:.2f}')}  "
                        f"Move for +5% option P&L≈{format_required_move(move5)}; {profit_if}\n"
                        f"Max contracts by risk sizing: {best.size.max_contracts} (budget≈${best.size.budget_usd:,.2f})",
                        title="Order preview",
                        expand=False,
                    )
                )
                if not typer.confirm(f"Submit {label} option order: BUY {qty} {best.symbol}?", default=False):
                    continue
                resp = submit_option_order(trading=trading, symbol=best.symbol, qty=int(qty), side="buy", limit_price=float(best.mid), tif="day")
                c.print(f"[green]Submitted[/green]: {resp}")

            elif action == "BUY_SHARES":
                qty = 1
                c.print(
                    Panel(
                        f"{underlying}: BUY_SHARES qty={qty} (market)\nUnderlying≈{('—' if und_px is None else f'${und_px:.2f}')}",
                        title="Order preview",
                        expand=False,
                    )
                )
                if not typer.confirm(f"Submit {label} equity order: BUY {qty} {underlying}?", default=False):
                    continue
                resp = submit_equity_order(trading=trading, symbol=underlying, qty=int(qty), side="buy", limit_price=None, tif="day")
                c.print(f"[green]Submitted[/green]: {resp}")
            else:
                c.print(f"[yellow]Skip[/yellow] unsupported action: {action}")
                continue

    @ideas_app.command("macro-playbook")
    def ideas_macro_playbook(
        start: str = typer.Option("2012-01-01", "--start", help="Start date YYYY-MM-DD"),
        refresh: bool = typer.Option(False, "--refresh", help="Force refresh FRED downloads (regimes)"),
        horizon_days: int = typer.Option(63, "--horizon-days", help="Forward horizon in trading days (~63=3m)"),
        neighbors: int = typer.Option(250, "--neighbors", help="k nearest historical regime days"),
        lookback_years: int = typer.Option(7, "--lookback-years", help="How many years to search for analogs"),
        top: int = typer.Option(12, "--top", help="How many ideas to print"),
        with_options: bool = typer.Option(False, "--with-options/--no-options", help="Attach <=$100 call/put leg when possible"),
        max_premium_usd: float = typer.Option(100.0, "--max-premium", help="Max premium per option contract (USD)"),
        min_days: int = typer.Option(30, "--min-days", help="Min option DTE (calendar days)"),
        max_days: int = typer.Option(90, "--max-days", help="Max option DTE (calendar days)"),
        target_abs_delta: float = typer.Option(0.30, "--target-abs-delta", help="Target |delta| for option leg"),
        max_spread_pct: float = typer.Option(0.30, "--max-spread-pct", help="Prefer spreads <= this"),
        price_basis: str = typer.Option("ask", "--price-basis", help="ask|mid|last (budget basis)"),
        cache: bool = typer.Option(True, "--cache/--no-cache", help="Cache regime feature matrix locally for speed"),
        refresh_cache: bool = typer.Option(False, "--refresh-cache", help="Rebuild cached regime features"),
        llm: bool = typer.Option(False, "--llm", help="Ask an LLM to summarize + propose actions"),
        llm_model: str = typer.Option("", "--llm-model", help="Override OPENAI_MODEL (optional)"),
        llm_temperature: float = typer.Option(0.2, "--llm-temperature", help="LLM temperature (0..2)"),
        include_positions: bool = typer.Option(True, "--positions/--no-positions", help="Include Alpaca positions in LLM payload"),
    ):
        """
        Macro playbook (30–90d horizon):
        - Find historical days with similar regime features (kNN in feature space)
        - Rank ETF trades by forward performance in those analog regimes
        - Output simple expressions: buy call / buy put (<= $100) and/or buy shares for bullish ideas
        """
        from rich.table import Table
        from rich.console import Console
        from rich.panel import Panel

        import pandas as pd
        from pathlib import Path

        from ai_options_trader.config import load_settings
        from ai_options_trader.data.market import fetch_equity_daily_closes
        from ai_options_trader.portfolio.universe import STARTER_UNIVERSE
        from ai_options_trader.ideas.macro_playbook import rank_macro_playbook
        from ai_options_trader.regimes.feature_matrix import build_regime_feature_matrix
        from ai_options_trader.options.budget_scan import affordable_options_for_ticker, pick_best_affordable
        from ai_options_trader.data.alpaca import fetch_option_chain, make_clients, to_candidates
        from ai_options_trader.llm.macro_playbook_review import llm_macro_playbook_review

        settings = load_settings()
        console = Console()

        # --- Prices for starter basket only (keep it lean) ---
        symbols = sorted(set(STARTER_UNIVERSE.basket_equity))
        px = fetch_equity_daily_closes(settings=settings, symbols=symbols, start=start, refresh=bool(refresh)).sort_index().ffill()

        # --- Regime feature matrix (cacheable, no labels) ---
        cache_dir = Path("data/cache/playbook")
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = cache_dir / f"regime_features_{start}.csv"

        X: pd.DataFrame
        if cache and cache_path.exists() and not refresh_cache and not refresh:
            X = pd.read_csv(cache_path, parse_dates=["date"]).set_index("date")
        else:
            X = build_regime_feature_matrix(settings=settings, start_date=start, refresh_fred=refresh)
            if cache:
                X.reset_index().rename(columns={"index": "date"}).to_csv(cache_path, index=False)

        ideas = rank_macro_playbook(
            features=X,
            prices=px,
            tickers=list(STARTER_UNIVERSE.basket_equity),
            horizon_days=int(horizon_days),
            k=int(neighbors),
            lookback_days=int(365 * int(lookback_years)),
            min_matches=60,
            asof=pd.to_datetime(X.index.max()),
        )

        ideas = ideas[: max(1, int(top))]

        # Option legs (optional): strict <=$100 premium, delta required
        legs: dict[str, dict] = {}
        if with_options and ideas:
            _trading, data = make_clients(settings)
            pb = price_basis.strip().lower()
            if pb not in {"ask", "mid", "last"}:
                pb = "ask"

            for idea in ideas:
                want = "call" if idea.direction == "bullish" else "put"
                try:
                    chain = fetch_option_chain(data, idea.ticker, feed=settings.alpaca_options_feed)
                    candidates = list(to_candidates(chain, idea.ticker))
                    opts = affordable_options_for_ticker(
                        candidates,
                        ticker=idea.ticker,
                        max_premium_usd=float(max_premium_usd),
                        min_dte_days=int(min_days),
                        max_dte_days=int(max_days),
                        want=want,  # type: ignore[arg-type]
                        price_basis=pb,  # type: ignore[arg-type]
                        min_price=0.05,
                        max_spread_pct=float(max_spread_pct),
                        require_delta=True,
                    )
                    best = pick_best_affordable(opts, target_abs_delta=float(target_abs_delta), max_spread_pct=float(max_spread_pct))
                    if best:
                        legs[idea.ticker] = {
                            "symbol": best.symbol,
                            "type": best.opt_type,
                            "expiry": str(best.expiry),
                            "dte_days": int(best.dte_days),
                            "strike": float(best.strike),
                            "price": float(best.price),
                            "premium_usd": float(best.premium_usd),
                            "delta": float(best.delta) if best.delta is not None else None,
                            "iv": float(best.iv) if best.iv is not None else None,
                            "spread_pct": float(best.spread_pct) if best.spread_pct is not None else None,
                        }
                except Exception:
                    continue

        # Print
        tbl = Table(title=f"Macro Playbook Ideas (horizon≈{int(horizon_days)}d, analogs k={int(neighbors)})")
        tbl.add_column("Ticker", style="bold")
        tbl.add_column("Dir")
        tbl.add_column("Score", justify="right")
        tbl.add_column("ExpRet", justify="right")
        tbl.add_column("Hit", justify="right")
        tbl.add_column("Worst", justify="right")
        tbl.add_column("Matches", justify="right")
        tbl.add_column("Expression")

        for it in ideas:
            leg = legs.get(it.ticker)
            if leg:
                expr = f"{leg['symbol']} (${leg['premium_usd']:.0f} Δ={leg.get('delta')})"
            else:
                expr = "BUY SHARES" if it.direction == "bullish" else "PUT (n/a under $100)"
            tbl.add_row(
                it.ticker,
                "UP" if it.direction == "bullish" else "DOWN",
                f"{it.score:.2f}",
                f"{it.exp_return:+.2f}%",
                f"{it.hit_rate:.0%}",
                f"{it.worst:+.2f}%",
                str(it.n_matches),
                expr,
            )

        console.print(tbl)
        console.print(
            Panel(
                "Notes:\n"
                "- These are research ideas, not advice.\n"
                "- 'ExpRet/Hit/Worst' are conditional forward returns computed over similar historical regime days.\n"
                "- Options legs are filtered to premium <= $100, delta required, and DTE 30..90.",
                title="Macro Playbook (MVP)",
                expand=False,
            )
        )

        if llm:
            # LLM payload: use current feature row + the idea rows (+ optional positions)
            asof = str(pd.to_datetime(X.index.max()).date())
            feat_row = X.loc[pd.to_datetime(X.index.max())].to_dict()
            ideas_payload = []
            for it in ideas:
                leg = legs.get(it.ticker)
                ideas_payload.append(
                    {
                        "ticker": it.ticker,
                        "direction": it.direction,
                        "horizon_days": it.horizon_days,
                        "n_matches": it.n_matches,
                        "exp_return": it.exp_return,
                        "median_return": it.median_return,
                        "hit_rate": it.hit_rate,
                        "worst": it.worst,
                        "best": it.best,
                        "score": it.score,
                        "option_leg": leg,
                    }
                )

            account_payload = None
            positions_payload = None
            if include_positions:
                trading, _data = make_clients(settings)
                try:
                    acct = trading.get_account()
                    account_payload = {
                        "equity": float(getattr(acct, "equity", 0.0) or 0.0),
                        "cash": float(getattr(acct, "cash", 0.0) or 0.0),
                        "buying_power": float(getattr(acct, "buying_power", 0.0) or 0.0),
                    }
                except Exception:
                    account_payload = None
                try:
                    pos = trading.get_all_positions()
                    positions_payload = []
                    for p in pos:
                        positions_payload.append(
                            {
                                "symbol": getattr(p, "symbol", ""),
                                "qty": float(getattr(p, "qty", 0.0) or 0.0),
                                "avg_entry_price": float(getattr(p, "avg_entry_price", 0.0) or 0.0)
                                if getattr(p, "avg_entry_price", None) is not None
                                else None,
                                "current_price": float(getattr(p, "current_price", 0.0) or 0.0)
                                if getattr(p, "current_price", None) is not None
                                else None,
                                "unrealized_pl": float(getattr(p, "unrealized_pl", 0.0) or 0.0)
                                if getattr(p, "unrealized_pl", None) is not None
                                else None,
                                "unrealized_plpc": float(getattr(p, "unrealized_plpc", 0.0) or 0.0)
                                if getattr(p, "unrealized_plpc", None) is not None
                                else None,
                            }
                        )
                except Exception:
                    positions_payload = None

            text = llm_macro_playbook_review(
                settings=settings,
                asof=asof,
                regime_features=feat_row,
                playbook_ideas=ideas_payload,
                positions=positions_payload,
                account=account_payload,
                model=llm_model.strip() or None,
                temperature=float(llm_temperature),
            )
            print("\nLLM REVIEW")
            print(text)

    @ideas_app.command("ai-bubble")
    def ideas_ai_bubble(
        start: str = typer.Option("2011-01-01", "--start"),
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


