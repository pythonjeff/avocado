"""Options moonshot command - high-variance extreme-move scanner."""
from __future__ import annotations

from datetime import date

import pandas as pd
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ai_options_trader.altdata.fmp import build_ticker_dossier
from ai_options_trader.config import load_settings
from ai_options_trader.data.alpaca import fetch_option_chain, make_clients, to_candidates
from ai_options_trader.data.market import fetch_equity_daily_closes
from ai_options_trader.data.quotes import fetch_stock_last_prices
from ai_options_trader.execution.alpaca import submit_option_order
from ai_options_trader.llm.moonshot_theory import llm_moonshot_theory
from ai_options_trader.options.budget_scan import affordable_options_for_ticker, pick_best_affordable
from ai_options_trader.options.moonshot import rank_moonshots, rank_moonshots_unconditional
from ai_options_trader.options.targets import format_required_move, required_underlying_move_for_profit_pct
from ai_options_trader.regimes.feature_matrix import build_regime_feature_matrix
from ai_options_trader.strategies.sleeves import resolve_sleeves
from ai_options_trader.universe.sp500 import load_sp500_universe


def register_moonshot(options_app: typer.Typer) -> None:
    """Register the moonshot command."""

    @options_app.command("moonshot")
    def options_moonshot(
        basket: str = typer.Option("starter", "--basket"),
        ticker: str = typer.Option("", "--ticker", "-t"),
        tickers: str = typer.Option("", "--tickers"),
        sleeves: str = typer.Option("", "--sleeves"),
        catalyst_mode: bool = typer.Option(False, "--catalyst-mode"),
        require_sp500: bool = typer.Option(False, "--require-sp500/--no-require-sp500"),
        start_date: str = typer.Option("2012-01-01", "--start-date"),
        horizon_days: int = typer.Option(63, "--horizon-days"),
        k_analogs: int = typer.Option(250, "--k-analogs"),
        min_abs_extreme: float = typer.Option(0.15, "--min-abs-extreme"),
        min_samples: int = typer.Option(40, "--min-samples"),
        direction: str = typer.Option("both", "--direction"),
        vol_lookback_days: int = typer.Option(14, "--vol-lookback-days"),
        vol_top_pct: float = typer.Option(0.35, "--vol-top-pct"),
        vol_min_ann: float = typer.Option(0.0, "--vol-min-ann"),
        min_days: int = typer.Option(14, "--min-days"),
        max_days: int = typer.Option(60, "--max-days"),
        price_basis: str = typer.Option("ask", "--price-basis"),
        min_price: float = typer.Option(0.05, "--min-price"),
        target_abs_delta: float = typer.Option(0.12, "--target-abs-delta"),
        max_spread_pct: float = typer.Option(0.60, "--max-spread-pct"),
        top: int = typer.Option(10, "--top"),
        cash_usd: float = typer.Option(0.0, "--cash"),
        all_in_threshold_usd: float = typer.Option(50.0, "--all-in-threshold"),
        max_premium_usd: float = typer.Option(0.0, "--max-premium"),
        review: bool = typer.Option(True, "--review/--no-review"),
        review_limit: int = typer.Option(25, "--review-limit"),
        with_theory: bool = typer.Option(True, "--theory/--no-theory"),
        theory_model: str = typer.Option("", "--theory-model"),
        theory_temperature: float = typer.Option(0.2, "--theory-temperature"),
        execute: bool = typer.Option(False, "--execute"),
        live: bool = typer.Option(False, "--live"),
    ):
        """
        Find extreme-move analogs and recommend OTM options (high-variance scanner).
        """
        console = Console()
        pb = price_basis.strip().lower()
        if pb not in {"ask", "mid", "last"}:
            pb = "ask"

        settings = load_settings()
        trading, data = make_clients(settings)

        # Auto catalyst mode for single ticker
        if ticker.strip() and not tickers.strip() and not catalyst_mode:
            catalyst_mode = True

        # S&P 500 guardrail
        if require_sp500:
            uni = load_sp500_universe(refresh=False, fmp_api_key=settings.fmp_api_key)
            allow = {t.strip().upper() for t in uni.tickers}
            check = []
            if tickers.strip():
                check = [t.strip().upper() for t in tickers.split(",") if t.strip()]
            elif ticker.strip():
                check = [ticker.strip().upper()]
            for t in check:
                if t not in allow:
                    console.print(Panel(f"[red]{t}[/red] not in S&P 500", title="Universe", expand=False))
                    raise typer.Exit(code=2)

        # Safety checks
        live_ok = bool(live) and not bool(settings.alpaca_paper)
        if execute and not settings.alpaca_paper and not live_ok:
            console.print(Panel("[red]Refusing[/red]: ALPACA_PAPER=false", title="Safety", expand=False))
            raise typer.Exit(code=1)
        if execute and live_ok:
            console.print(Panel("[yellow]LIVE MODE[/yellow]", title="Safety", expand=False))
            if not typer.confirm("Confirm LIVE?", default=False):
                raise typer.Exit(code=0)
            if not typer.confirm("Second confirmation?", default=False):
                raise typer.Exit(code=0)

        # Budget
        cash_live = 0.0
        prem_cap = float(max_premium_usd) if max_premium_usd > 0 else 0.0
        if not catalyst_mode:
            if cash_usd > 0:
                cash_live = float(cash_usd)
            else:
                try:
                    acct = trading.get_account()
                    cash_live = float(getattr(acct, "cash", 0.0) or 0.0)
                except Exception:
                    pass
            if max_premium_usd > 0:
                prem_cap = float(max_premium_usd)
            else:
                prem_cap = cash_live if cash_live <= all_in_threshold_usd else min(100.0, 0.35 * cash_live)
            prem_cap = max(0.0, prem_cap)

        # Universe
        try:
            from ai_options_trader.portfolio.universe import get_universe
        except Exception:
            from ai_options_trader.portfolio.universe import STARTER_UNIVERSE, DEFAULT_UNIVERSE
            def get_universe(name: str):
                return DEFAULT_UNIVERSE if name.startswith("d") else STARTER_UNIVERSE

        symbols: list[str]
        sleeve_names = [x.strip() for x in (sleeves or "").replace(",", " ").split() if x.strip()]
        if sleeve_names:
            cfgs = resolve_sleeves(sleeve_names)
            all_syms = []
            for s in cfgs:
                uni_syms = s.universe_fn(basket) if s.universe_fn else []
                all_syms.extend([t.strip().upper() for t in (uni_syms or []) if t])
            symbols = sorted(set(all_syms))
        elif tickers.strip():
            symbols = [t.strip().upper() for t in tickers.split(",") if t.strip()]
        elif ticker.strip():
            symbols = [ticker.strip().upper()]
        else:
            uni = get_universe(basket)
            symbols = sorted(set(uni.basket_equity))

        # Data
        X = build_regime_feature_matrix(settings=settings, start_date=str(start_date), refresh_fred=False)
        px = fetch_equity_daily_closes(settings=settings, symbols=symbols, start=str(start_date), refresh=False).sort_index().ffill()

        asof = min(pd.to_datetime(X.index.max()), pd.to_datetime(px.index.max()))
        asof_str = str(pd.to_datetime(asof).date())
        feat_row = {}
        try:
            feat_row = X.loc[pd.to_datetime(asof)].to_dict()
        except Exception:
            pass

        # Realized vol
        rv_ann = None
        try:
            r = px.pct_change().replace([float("inf"), float("-inf")], pd.NA)
            rv = r.rolling(max(5, int(vol_lookback_days))).std() * (252.0 ** 0.5)
            rv_ann = rv.loc[pd.to_datetime(asof)] if pd.to_datetime(asof) in rv.index else rv.iloc[-1]
        except Exception:
            pass

        # Rank moonshots
        ranked = rank_moonshots(
            px=px, regimes=X, asof=asof,
            horizon_days=int(horizon_days), k_analogs=int(k_analogs),
            min_abs_extreme=float(min_abs_extreme), min_samples=int(min_samples),
            direction=str(direction),
        )

        # Fallback
        if not ranked:
            console.print(Panel("No candidates, falling back...", title="Fallback", expand=False))
            for mae, ms in [(min_abs_extreme*0.75, max(25, min_samples)), 
                           (min_abs_extreme*0.50, max(20, min_samples//2)),
                           (max(0.05, min_abs_extreme*0.33), max(15, min_samples//3))]:
                ranked = rank_moonshots(
                    px=px, regimes=X, asof=asof,
                    horizon_days=int(horizon_days), k_analogs=int(k_analogs),
                    min_abs_extreme=float(mae), min_samples=int(ms),
                    direction=str(direction),
                )
                if ranked:
                    break
            if not ranked:
                ranked = rank_moonshots_unconditional(
                    px=px, asof=asof, horizon_days=int(horizon_days),
                    min_samples=max(60, int(min_samples)), direction=str(direction),
                )
            if not ranked:
                print("[yellow]No candidates available[/yellow]")
                raise typer.Exit(code=0)

        # Vol filter
        if rv_ann is not None and len(symbols) > 1:
            try:
                v = pd.to_numeric(rv_ann, errors="coerce").dropna()
                if not v.empty:
                    keep = set(v.index)
                    if vol_min_ann > 0:
                        keep = {t for t in keep if float(v.get(t, 0) or 0) >= vol_min_ann}
                    if 0 < vol_top_pct < 1:
                        thr = float(v.quantile(max(0, min(1, 1-vol_top_pct))))
                        keep = {t for t in keep if float(v.get(t, 0) or 0) >= thr}
                    filtered = [r for r in ranked if r.ticker.upper() in keep]
                    if filtered:
                        ranked = filtered
            except Exception:
                pass

        # Display
        cash_lbl = f"cash≈${cash_live:,.2f}" if not catalyst_mode else "cash=ignored"
        tbl = Table(title=f"Moonshot ({asof.date()} | {horizon_days}d | {cash_lbl})")
        tbl.add_column("Rank", justify="right")
        tbl.add_column("Ticker", style="bold")
        tbl.add_column("Dir")
        tbl.add_column("rv", justify="right")
        tbl.add_column("Score", justify="right")
        tbl.add_column("q95", justify="right")
        tbl.add_column("q05", justify="right")
        tbl.add_column("extreme", justify="right")
        tbl.add_column("n", justify="right")

        shown = ranked[:max(1, int(top))]
        for i, r in enumerate(shown, start=1):
            ex = "—"
            if r.extreme_date and r.extreme_return:
                ex = f"{pd.to_datetime(r.extreme_date).date()} {100*r.extreme_return:+.1f}%"
            rv_s = "—"
            try:
                if rv_ann is not None:
                    vv = float(pd.to_numeric(rv_ann.get(r.ticker.upper()), errors="coerce"))
                    if vv == vv:
                        rv_s = f"{100*vv:.0f}%"
            except Exception:
                pass
            tbl.add_row(
                str(i), str(r.ticker),
                "CALL" if r.direction == "bullish" else "PUT",
                rv_s, f"{r.score:.3f}",
                f"{100*r.q95:+.1f}%" if r.q95 else "—",
                f"{100*r.q05:+.1f}%" if r.q05 else "—",
                ex, str(int(r.samples)),
            )
        console.print(tbl)

        # Contract picker helper
        def _pick_contract(tkr: str, want: str, target_dt: date | None):
            chain = fetch_option_chain(data, tkr, feed=settings.alpaca_options_feed)
            cands = list(to_candidates(chain, tkr))
            cap = 1e12
            
            if target_dt:
                today = pd.Timestamp(asof).date()
                for mind, maxd in [(0, 120), (0, 180)]:
                    opts = affordable_options_for_ticker(
                        cands, ticker=tkr, max_premium_usd=cap,
                        min_dte_days=mind, max_dte_days=maxd,
                        want=want, price_basis=pb, min_price=float(min_price),
                        max_spread_pct=float(max_spread_pct), require_delta=True, today=today,
                    )
                    opts2 = [o for o in opts if o.expiry >= target_dt]
                    best = pick_best_affordable(opts2, target_abs_delta=float(target_abs_delta), max_spread_pct=float(max_spread_pct))
                    if best:
                        return best
            
            opts = affordable_options_for_ticker(
                cands, ticker=tkr, max_premium_usd=cap,
                min_dte_days=int(min_days), max_dte_days=int(max_days),
                want=want, price_basis=pb, min_price=float(min_price),
                max_spread_pct=float(max_spread_pct), require_delta=True,
                today=pd.Timestamp(asof).date(),
            )
            return pick_best_affordable(opts, target_abs_delta=float(target_abs_delta), max_spread_pct=float(max_spread_pct))

        def _next_earnings(tkr: str) -> date | None:
            try:
                d = build_ticker_dossier(settings=settings, ticker=tkr, days_ahead=180)
                ne = d.get("next_earnings") if isinstance(d, dict) else None
                if isinstance(ne, dict) and ne.get("date"):
                    return pd.to_datetime(ne.get("date")).date()
            except Exception:
                pass
            return None

        # Interactive review
        remaining_cash = cash_live
        all_in = 0 < remaining_cash <= all_in_threshold_usd
        if all_in:
            prem_cap = remaining_cash
            console.print(Panel(f"[red]ALL-IN[/red]: ${remaining_cash:,.2f}", title="Moonshot", expand=False))

        if review:
            label = "LIVE" if live_ok else "PAPER"
            n_review = min(int(review_limit), len(ranked))

            for i, r in enumerate(ranked[:n_review], start=1):
                if remaining_cash <= 0 and cash_live > 0:
                    console.print(Panel("No cash remaining", title="Budget", expand=False))
                    break

                try:
                    want = "call" if r.direction == "bullish" else "put"
                    target_dt = _next_earnings(r.ticker) if catalyst_mode else None
                    best = _pick_contract(r.ticker, want, target_dt)
                except Exception as e:
                    console.print(f"[dim]{i}/{n_review} {r.ticker}: skip ({type(e).__name__})[/dim]")
                    continue

                if best is None:
                    console.print(f"[dim]{i}/{n_review} {r.ticker}: no contract[/dim]")
                    continue

                ex = "—"
                if r.extreme_date and r.extreme_return:
                    ex = f"{pd.to_datetime(r.extreme_date).date()} {100*r.extreme_return:+.1f}%"

                console.print(Panel(
                    f"{i}/{n_review}  {r.ticker}  {'CALL' if r.direction=='bullish' else 'PUT'}  "
                    f"score={r.score:.3f}  extreme={ex}",
                    title="Candidate", expand=False,
                ))

                if with_theory:
                    try:
                        dossier = build_ticker_dossier(settings=settings, ticker=r.ticker, days_ahead=180) if catalyst_mode else {}
                        theory = llm_moonshot_theory(
                            settings=settings, asof=asof_str, ticker=r.ticker,
                            direction=r.direction, horizon_days=int(horizon_days),
                            regime_features=feat_row,
                            analog_stats={
                                "samples": r.samples, "q05": r.q05, "q50": r.q50,
                                "q95": r.q95, "best": r.best, "worst": r.worst,
                                "extreme_date": r.extreme_date, "extreme_return": r.extreme_return,
                            },
                            dossier=dossier,
                            model=theory_model.strip() or None,
                            temperature=float(theory_temperature),
                        )
                        console.print(Panel(theory, title="Theory", expand=False))
                    except Exception as e:
                        console.print(f"[dim]Theory unavailable: {e}[/dim]")

                # Contract table
                und_px = None
                try:
                    if len(symbols) <= 5:
                        last_px, _, _ = fetch_stock_last_prices(settings=settings, symbols=[best.ticker])
                        und_px = last_px.get(best.ticker.upper())
                    if und_px is None and best.ticker in px.columns:
                        col = px[best.ticker].dropna()
                        if not col.empty:
                            und_px = float(col.iloc[-1])
                except Exception:
                    pass

                move = required_underlying_move_for_profit_pct(
                    opt_entry_price=float(best.price),
                    delta=float(best.delta) if best.delta else None,
                    profit_pct=0.05, underlying_px=und_px, opt_type=str(best.opt_type),
                )

                tbl2 = Table(title="Contract")
                tbl2.add_column("Und")
                tbl2.add_column("Type")
                tbl2.add_column("Contract")
                tbl2.add_column("Exp")
                tbl2.add_column("Strike", justify="right")
                tbl2.add_column("Price", justify="right")
                tbl2.add_column("Move@5%", justify="right")
                tbl2.add_column("Premium", justify="right")
                tbl2.add_row(
                    best.ticker, "CALL" if best.opt_type == "call" else "PUT",
                    best.symbol, best.expiry.isoformat(),
                    f"${best.strike:.2f}", f"${best.price:.2f}",
                    format_required_move(move), f"${best.premium_usd:,.0f}",
                )
                console.print(tbl2)

                qty = 1
                if not catalyst_mode and remaining_cash > 0 and best.premium_usd > 0:
                    qty = max(1, int(remaining_cash // best.premium_usd)) if all_in else 1
                est = qty * best.premium_usd

                if not typer.confirm(f"BUY {qty}x {best.symbol}? [{label}]", default=False):
                    if typer.confirm("Stop reviewing?", default=False):
                        break
                    continue

                if not catalyst_mode:
                    remaining_cash = max(0, remaining_cash - est)
                    console.print(Panel(f"Reserved ${est:,.2f}, remaining ${remaining_cash:,.2f}", title="Budget", expand=False))

                if not execute:
                    print("[dim]DRY RUN[/dim]: add --execute")
                    continue

                try:
                    resp = submit_option_order(
                        trading=trading, symbol=best.symbol, qty=qty,
                        side="buy", limit_price=float(best.price), tif="day",
                    )
                    print(f"[green]Submitted {label}[/green]: {resp}")
                except Exception as e:
                    print(f"[red]Failed[/red]: {e}")
                    raise typer.Exit(code=2)

            raise typer.Exit(code=0)
