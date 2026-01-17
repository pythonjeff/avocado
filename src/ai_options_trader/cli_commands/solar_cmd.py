from __future__ import annotations

import typer
from rich.table import Table
from rich import print
from rich.panel import Panel


def register(solar_app: typer.Typer) -> None:
    @solar_app.command("snapshot")
    def snapshot(
        start: str = typer.Option("2011-01-01", "--start"),
        refresh: bool = typer.Option(False, "--refresh"),
        execute: bool = typer.Option(False, "--execute", help="If set, can submit the order after confirmation (paper by default; use --live for live)."),
        live: bool = typer.Option(False, "--live", help="Allow LIVE execution when ALPACA_PAPER is false (guarded with extra confirmations)."),
        budgeted: bool = typer.Option(True, "--budgeted/--no-budgeted", help="If enabled, constrain options by available cash. Default: budgeted."),
        max_trades: int = typer.Option(5, "--max-trades", help="Max number of option ideas to list from the solar basket."),
        pair_trade: bool = typer.Option(True, "--pair-trade/--no-pair-trade", help="Use 70% options short TAN + 30% equity long SLV."),
    ):
        """
        Solar basket + silver headwind snapshot.
        """
        from ai_options_trader.config import load_settings
        from ai_options_trader.data.alpaca import make_clients, fetch_option_chain, to_candidates
        from ai_options_trader.execution.alpaca import submit_equity_notional_order, submit_option_order
        from ai_options_trader.options.budget_scan import affordable_options_for_ticker, pick_best_delta_theta
        from ai_options_trader.solar.signals import build_solar_state
        from ai_options_trader.solar.regime import classify_solar_regime

        settings = load_settings()
        state = build_solar_state(settings=settings, start_date=start, refresh=refresh)
        regime = classify_solar_regime(state.inputs)

        print(
            Panel(
                f"[b]Regime:[/b] {regime.label}\n"
                f"[b]Solar 60d ret:[/b] {state.inputs.solar_ret_60d}\n"
                f"[b]Solar rel 60d (vs SPY):[/b] {state.inputs.solar_rel_ret_60d}\n"
                f"[b]Silver 60d (SLV):[/b] {state.inputs.silver_ret_60d}\n"
                f"[b]Z solar rel 60d:[/b] {state.inputs.z_solar_rel_ret_60d}\n"
                f"[b]Z silver 60d:[/b] {state.inputs.z_silver_ret_60d}\n"
                f"[b]Solar headwind score:[/b] {state.inputs.solar_headwind_score}\n\n"
                f"[dim]{regime.description}[/dim]\n"
                f"[dim]{state.notes}[/dim]",
                title="Solar / Silver snapshot",
                expand=False,
            )
        )

        # Recommend a list of options across the solar basket (core manufacturers).
        from ai_options_trader.solar.signals import SOLAR_CORE_TICKERS
        basket = list(SOLAR_CORE_TICKERS)
        want = "put" if regime.label == "silver_headwind" else "call" if regime.label == "silver_tailwind" else "both"
        try:
            trading, data = make_clients(settings)
            acct = trading.get_account()
            cash = float(getattr(acct, "cash", 0.0) or 0.0)
        except Exception:
            trading, data = None, None
            cash = 0.0

        if cash <= 0:
            print(Panel("No available cash detected for options budget.", title="Option recommendation", expand=False))
            return

        # Budget control: 70% options / 30% equity (pair trade).
        if pair_trade:
            # Force the 70/30 split for the TAN short + SLV long pair.
            budgeted = True
        opt_budget = max(0.0, min(0.70 * cash, cash * 0.99)) if budgeted else 1e9
        eq_budget = max(0.0, min(0.30 * cash, cash * 0.99)) if budgeted else 0.0
        afford_budget = opt_budget if budgeted else cash

        def _chain_for(sym: str):
            try:
                chain = fetch_option_chain(data, sym, feed=getattr(settings, "alpaca_options_feed", None))
                return list(to_candidates(chain, sym))
            except Exception:
                return []

        def _pick(candidates, sym: str, require_delta: bool):
            def _score(o):
                oi = float(o.oi) if getattr(o, "oi", None) is not None else -1.0
                delta_dist = abs(abs(float(o.delta)) - 0.30) if o.delta is not None else 1e9
                return (-oi, delta_dist, float(o.premium_usd))

            # 6+ months DTE constraint (allow wide max).
            for price_basis in ("last", "mid", "ask"):
                opts = affordable_options_for_ticker(
                    candidates,
                    ticker=sym,
                    max_premium_usd=float(afford_budget),
                    min_dte_days=180,
                    max_dte_days=720,
                    want=want,
                    price_basis=price_basis,
                    min_price=0.01,
                    require_delta=require_delta,
                    max_spread_pct=0.30,
                    min_open_interest=0,
                    min_volume=0,
                    require_liquidity=False,
                )
                if opts:
                    best = sorted(opts, key=_score)[0]
                    return best, _score(best)

            return None

        if pair_trade:
            # Force TAN put selection as "short solar" leg.
            tan_candidates = _chain_for("TAN")
            tan_pick = _pick(tan_candidates, "TAN", require_delta=True)
            if tan_pick is None:
                tan_pick = _pick(tan_candidates, "TAN", require_delta=False)
            if tan_pick is None:
                print(
                    Panel(
                        f"No TAN option matched the affordability filters (budget=${afford_budget:.2f}).",
                        title="Option recommendation",
                        expand=False,
                    )
                )
                return
            best = tan_pick[0]
            print(
                Panel(
                    f"[b]Short solar leg:[/b] TAN {('PUT' if best.opt_type == 'put' else 'CALL')}\n"
                    f"[b]Contract:[/b] {best.symbol}\n"
                    f"[b]DTE:[/b] {best.dte_days}  [b]Strike:[/b] {best.strike}\n"
                    f"[b]Premium:[/b] ${best.premium_usd:.2f} (budget={'off' if not budgeted else f'${afford_budget:.2f}'})\n"
                    f"[b]Delta:[/b] {best.delta}  [b]Gamma:[/b] {best.gamma}  [b]Theta:[/b] {best.theta}  [b]IV:[/b] {best.iv}",
                    title="Option recommendation",
                    expand=False,
                )
            )

            # 1) List affordable TAN options
            tan_opts = affordable_options_for_ticker(
                tan_candidates,
                ticker="TAN",
                max_premium_usd=float(afford_budget),
                min_dte_days=180,
                max_dte_days=720,
                want=want,
                price_basis="last",
                min_price=0.01,
                require_delta=True,
                max_spread_pct=1.0,
                min_open_interest=0,
                min_volume=0,
                require_liquidity=False,
            )
            if tan_opts:
                t_aff = Table(title="Affordable TAN options (>=6m DTE)")
                t_aff.add_column("symbol", style="bold")
                t_aff.add_column("dte", justify="right")
                t_aff.add_column("strike", justify="right")
                t_aff.add_column("premium", justify="right")
                t_aff.add_column("oi", justify="right")
                t_aff.add_column("delta", justify="right")
                for o in sorted(tan_opts, key=lambda x: x.premium_usd)[:10]:
                    t_aff.add_row(
                        str(o.symbol),
                        str(o.dte_days),
                        f"{o.strike:.2f}",
                        f"${o.premium_usd:.2f}",
                        "—" if o.oi is None else str(o.oi),
                        "—" if o.delta is None else f"{o.delta:.2f}",
                    )
                print(t_aff)

                # 2) Cheapest with favorable greeks (delta present + gamma/theta present)
                favorable = [
                    o
                    for o in tan_opts
                    if o.delta is not None
                    and 0.15 <= abs(float(o.delta)) <= 0.45
                    and o.gamma is not None
                    and o.theta is not None
                ]
                if favorable:
                    fav = sorted(favorable, key=lambda x: x.premium_usd)[0]
                    print(
                        Panel(
                            f"[b]Cheapest favorable greeks:[/b] {fav.symbol}\n"
                            f"DTE={fav.dte_days}  strike={fav.strike}  premium=${fav.premium_usd:.2f}",
                            title="TAN pick (cheapest favorable)",
                            expand=False,
                        )
                    )

                # 3) Near cash (+/-5%)
                near = [o for o in tan_opts if o.premium_usd >= 0.95 * afford_budget]
                if near:
                    near_pick = sorted(near, key=lambda x: abs(x.premium_usd - afford_budget))[:3]
                    t_near = Table(title="TAN options near cash (±5%)")
                    t_near.add_column("symbol", style="bold")
                    t_near.add_column("premium", justify="right")
                    t_near.add_column("oi", justify="right")
                    t_near.add_column("delta", justify="right")
                    for o in near_pick:
                        t_near.add_row(
                            str(o.symbol),
                            f"${o.premium_usd:.2f}",
                            "—" if o.oi is None else str(o.oi),
                            "—" if o.delta is None else f"{o.delta:.2f}",
                        )
                    print(t_near)

                # 4) Adjacent securities (same thesis, more affordable)
                alt_syms = ["FSLR", "CSIQ", "JKS", "SPWR"]
                alt_rows = []
                for s in alt_syms:
                    alt_candidates = _chain_for(s)
                    if not alt_candidates:
                        continue
                    alt_pick = _pick(alt_candidates, s, require_delta=True)
                    if alt_pick is None:
                        continue
                    alt_rows.append(alt_pick[0])

                if alt_rows:
                    t_alt = Table(title="Adjacent solar shorts (affordable)")
                    t_alt.add_column("ticker", style="bold")
                    t_alt.add_column("symbol")
                    t_alt.add_column("premium", justify="right")
                    t_alt.add_column("oi", justify="right")
                    t_alt.add_column("delta", justify="right")
                    for o in alt_rows[:10]:
                        t_alt.add_row(
                            str(o.ticker),
                            str(o.symbol),
                            f"${o.premium_usd:.2f}",
                            "—" if o.oi is None else str(o.oi),
                            "—" if o.delta is None else f"{o.delta:.2f}",
                        )
                    print(t_alt)

            # Long silver equity leg
            print(
                Panel(
                    f"[b]Long silver leg:[/b] SLV equity\n"
                    f"[b]Notional:[/b] ${eq_budget:.2f} (budget={'off' if not budgeted else '30% cash'})\n"
                    f"[b]Allocation:[/b] TAN options 70% / SLV equity 30%",
                    title="Equity recommendation",
                    expand=False,
                )
            )
        else:
            picks: list[tuple[float, object]] = []
            for sym in basket:
                candidates = _chain_for(sym)
                if not candidates:
                    continue
                picked = _pick(candidates, sym, require_delta=True)
                if picked is None:
                    picked = _pick(candidates, sym, require_delta=False)
                if picked is None:
                    continue
                best_opt, score = picked
                picks.append((score, best_opt))

            if not picks:
                print(
                    Panel(
                        "No options matched filters across the solar basket. Try loosening liquidity or DTE.",
                        title="Option recommendations",
                        expand=False,
                    )
                )
                return

            picks = sorted(picks, key=lambda x: x[0])[: max(1, int(max_trades))]
            t = Table(title="Solar basket option ideas (module makers)")
            t.add_column("ticker", style="bold")
            t.add_column("type")
            t.add_column("symbol")
            t.add_column("dte", justify="right")
            t.add_column("strike", justify="right")
            t.add_column("premium", justify="right")
            t.add_column("delta", justify="right")
            t.add_column("gamma", justify="right")
            t.add_column("theta", justify="right")

            for _score, opt in picks:
                t.add_row(
                    str(opt.ticker),
                    "PUT" if opt.opt_type == "put" else "CALL",
                    str(opt.symbol),
                    str(opt.dte_days),
                    f"{opt.strike:.2f}",
                    f"${opt.premium_usd:.2f}",
                    "—" if opt.delta is None else f"{opt.delta:.2f}",
                    "—" if opt.gamma is None else f"{opt.gamma:.4f}",
                    "—" if opt.theta is None else f"{opt.theta:.4f}",
                )
            print(t)

            best = picks[0][1]
            side = "PUT" if best.opt_type == "put" else "CALL"
            print(
                Panel(
                    f"[b]Top pick:[/b] {best.symbol} ({side})\n"
                    f"[b]Budget:[/b] {'off' if not budgeted else f'${opt_budget:.2f}'}",
                    title="Option recommendation",
                    expand=False,
                )
            )

        # Pair leg: long silver to isolate the relative move (optional but default-on for headwind regime).
        if regime.label == "silver_headwind":
            slv_candidates = _chain_for("SLV")
            if slv_candidates:
                slv_pick = _pick(slv_candidates, "SLV", require_delta=True)
                if slv_pick is None:
                    slv_pick = _pick(slv_candidates, "SLV", require_delta=False)
                if slv_pick is not None:
                    slv_best, _ = slv_pick
                    print(
                        Panel(
                            f"[b]Pair leg (long silver):[/b] {slv_best.symbol} (CALL)\n"
                            f"[b]DTE:[/b] {slv_best.dte_days}  [b]Strike:[/b] {slv_best.strike}\n"
                            f"[b]Premium:[/b] ${slv_best.premium_usd:.2f}",
                            title="Pair trade leg",
                            expand=False,
                        )
                    )

        # Ask to execute
        if not typer.confirm("Submit the recommended orders now?", default=False):
            return

        live_ok = bool(live) and (not bool(settings.alpaca_paper))
        if execute and (not settings.alpaca_paper) and (not live_ok):
            print(Panel("[red]Refusing to execute[/red] because ALPACA_PAPER is false.\nUse --live --execute for live.", title="Safety", expand=False))
            return
        if execute and live_ok:
            print(
                Panel(
                    "[yellow]LIVE MODE ENABLED[/yellow]\n"
                    "Orders will be submitted to your LIVE Alpaca account.\n"
                    "You will be asked to confirm again before submission.",
                    title="Safety",
                    expand=False,
                )
            )
            if not typer.confirm("Confirm LIVE mode (ALPACA_PAPER=false) and proceed?", default=False):
                return
            if not typer.confirm("Second confirmation: proceed with LIVE trading now?", default=False):
                return

        if not execute:
            print("[dim]DRY RUN[/dim]: re-run with --execute to submit this order.")
            return

        try:
            submit_option_order(
                trading=trading,
                symbol=best.symbol,
                qty=1,
                side="buy",
                limit_price=float(best.price),
                tif="day",
            )
            print(f"[green]Submitted[/green] option: {best.symbol}")
        except Exception as e:
            print(Panel(f"Option order rejected: {e}", title="Order", expand=False))

        if pair_trade and eq_budget > 0:
            try:
                submit_equity_notional_order(
                    trading=trading,
                    symbol="SLV",
                    notional=float(eq_budget),
                    side="buy",
                    tif="day",
                )
                print(f"[green]Submitted[/green] equity: SLV notional ${eq_budget:.2f}")
            except Exception as e:
                print(Panel(f"Equity order rejected: {e}", title="Order", expand=False))
