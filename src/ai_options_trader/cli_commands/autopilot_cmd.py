"""
Autopilot CLI - streamlined trade automation.

Refactored to use modular components from ai_options_trader.autopilot.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ai_options_trader.autopilot import (
    to_float,
    extract_underlying,
    build_budget_plans,
    fetch_positions,
    stop_candidates,
    get_held_underlyings,
    get_option_underlyings,
    build_proposals,
    generate_ideas,
    apply_thesis_reweighting,
    attach_option_legs,
    display_positions_table,
    display_status_panel,
    display_proposals_table,
    display_budget_summary,
    INVERSE_PROXY,
)
from ai_options_trader.config import load_settings
from ai_options_trader.data.alpaca import make_clients
from ai_options_trader.data.market import fetch_equity_daily_closes
from ai_options_trader.execution.alpaca import submit_option_order, submit_equity_order
from ai_options_trader.options.targets import format_required_move, required_underlying_move_for_profit_pct
from ai_options_trader.regimes.feature_matrix import build_regime_feature_matrix
from ai_options_trader.strategies.sleeves import resolve_sleeves


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _normalize_inputs(
    budget_mode: str,
    allocation: str,
    flex_prefer: str,
    thesis: str,
    min_new_trades: int,
    max_new_trades: int,
) -> tuple[str, str, str, str, int, int]:
    """Normalize and validate input parameters."""
    mode = (budget_mode or "strict").strip().lower()
    if mode not in {"strict", "flex"}:
        mode = "strict"
    
    alloc = (allocation or "auto").strip().lower()
    if alloc not in {"auto", "equity100", "50_50", "70_30", "both"}:
        alloc = "auto"
    
    flex_p = (flex_prefer or "options").strip().lower()
    if flex_p not in {"options", "shares"}:
        flex_p = "options"
    
    thesis_s = (thesis or "none").strip().lower()
    if thesis_s not in {"none", "inflation_fiscal"}:
        thesis_s = "none"
    
    min_n = max(0, int(min_new_trades))
    max_n = max(int(max_new_trades), min_n if min_n > 0 else 0)
    
    return mode, alloc, flex_p, thesis_s, min_n, max_n


def _fetch_underlying_prices(
    positions: list[dict],
    settings,
) -> dict[str, float]:
    """Fetch current prices for option underlyings."""
    und_px_map: dict[str, float] = {}
    
    try:
        option_unds = get_option_underlyings(positions)
        if not option_unds:
            return und_px_map
        
        start_px = (datetime.now(timezone.utc) - timedelta(days=400)).date().isoformat()
        px_u = fetch_equity_daily_closes(
            settings=settings,
            symbols=sorted(option_unds),
            start=start_px,
            refresh=False,
        ).sort_index().ffill()
        
        if not px_u.empty:
            last = px_u.iloc[-1].to_dict()
            for k, v in (last or {}).items():
                try:
                    if v is not None:
                        und_px_map[str(k).strip().upper()] = float(v)
                except Exception:
                    continue
    except Exception:
        pass
    
    return und_px_map


def _get_universe_symbols(basket: str) -> list[str]:
    """Get universe symbols for the given basket."""
    try:
        from ai_options_trader.portfolio.universe import get_universe
    except Exception:
        from ai_options_trader.portfolio.universe import STARTER_UNIVERSE, DEFAULT_UNIVERSE
        def get_universe(name: str):
            n = (name or "starter").strip().lower()
            return DEFAULT_UNIVERSE if n.startswith("d") else STARTER_UNIVERSE
    
    uni = get_universe(basket)
    return sorted(set(uni.basket_equity))


def _ensure_live_confirmed(
    console: Console,
    live_ok: bool,
    live_confirmed: list,
) -> bool:
    """Ensure live mode is confirmed with extra friction."""
    if not live_ok or live_confirmed[0]:
        return True
    
    console.print(Panel(
        "[yellow]LIVE MODE ENABLED[/yellow]\n"
        "Orders will be submitted to your LIVE Alpaca account.",
        title="Safety", expand=False,
    ))
    
    if not typer.confirm("Confirm LIVE mode?", default=False):
        raise typer.Exit(code=0)
    if not typer.confirm("Second confirmation?", default=False):
        raise typer.Exit(code=0)
    
    live_confirmed[0] = True
    return True


def _convert_proposals_to_dicts(proposals) -> list[dict]:
    """Convert TradeProposal objects to dicts for display."""
    return [
        {
            "kind": p.kind,
            "ticker": p.ticker,
            "idea": p.idea,
            "est_cost_usd": p.est_cost_usd,
            "exposure": p.exposure,
            "leg": p.leg,
            "qty": p.qty,
            "limit": p.limit,
        }
        for p in proposals
    ]


# ---------------------------------------------------------------------------
# Command registration
# ---------------------------------------------------------------------------

def register(autopilot_app: typer.Typer) -> None:
    """Register autopilot commands."""

    @autopilot_app.command("run-once")
    def run_once(
        start: str = typer.Option("2012-01-01", "--start"),
        refresh: bool = typer.Option(False, "--refresh"),
        basket: str = typer.Option("starter", "--basket"),
        engine: str = typer.Option("analog", "--engine", help="playbook|analog|ml"),
        sleeves: str = typer.Option("", "--sleeves"),
        predictions: bool = typer.Option(False, "--predictions"),
        top_predictions: int = typer.Option(15, "--top-predictions"),
        feature_set: str = typer.Option("fci", "--feature-set"),
        interaction_mode: str = typer.Option("whitelist", "--interaction-mode"),
        whitelist_extra: str = typer.Option("none", "--whitelist-extra"),
        thesis: str = typer.Option("none", "--thesis"),
        stop_loss_pct: float = typer.Option(0.30, "--stop-loss"),
        review_positions: bool = typer.Option(True, "--review-positions/--no-review-positions"),
        execute: bool = typer.Option(False, "--execute"),
        live: bool = typer.Option(False, "--live"),
        budget_mode: str = typer.Option("strict", "--budget-mode"),
        allocation: str = typer.Option("auto", "--allocation"),
        max_new_trades: int = typer.Option(3, "--max-new-trades"),
        min_new_trades: int = typer.Option(2, "--min-new-trades"),
        flex_prefer: str = typer.Option("options", "--flex-prefer"),
        with_options: bool = typer.Option(True, "--with-options/--no-options"),
        max_premium_usd: float = typer.Option(100.0, "--max-premium"),
        min_days: int = typer.Option(30, "--min-days"),
        max_days: int = typer.Option(90, "--max-days"),
        target_abs_delta: float = typer.Option(0.30, "--target-abs-delta"),
        max_spread_pct: float = typer.Option(0.30, "--max-spread-pct"),
        shares_budget_usd: float = typer.Option(100.0, "--shares-budget"),
        require_positive_score: bool = typer.Option(True, "--require-positive-score/--allow-negative-score"),
        llm: bool = typer.Option(False, "--llm"),
        llm_model: str = typer.Option("", "--llm-model"),
        llm_temperature: float = typer.Option(0.2, "--llm-temperature"),
        llm_news: bool = typer.Option(True, "--llm-news/--no-llm-news"),
        llm_calendar_days: int = typer.Option(10, "--llm-calendar-days"),
        llm_calendar_max_items: int = typer.Option(18, "--llm-calendar-max-items"),
        llm_news_days: int = typer.Option(7, "--llm-news-days"),
        llm_news_max_items: int = typer.Option(18, "--llm-news-max-items"),
        llm_gate: bool = typer.Option(False, "--llm-gate"),
        llm_gate_override: bool = typer.Option(False, "--llm-gate-override"),
        llm_positions_outlook: bool = typer.Option(True, "--llm-positions-outlook/--no-llm-positions-outlook"),
        explain: bool = typer.Option(True, "--explain/--no-explain"),
        show_basket: bool = typer.Option(False, "--show-basket/--no-show-basket"),
    ):
        """Macro autopilot: fetch positions, generate ideas, propose trades."""
        console = Console()
        settings = load_settings()
        
        # Normalize inputs
        budget_mode_s, allocation_s, flex_prefer_s, thesis_s, min_n, max_n = _normalize_inputs(
            budget_mode, allocation, flex_prefer, thesis, min_new_trades, max_new_trades
        )
        
        # Connect to Alpaca
        trading, data = make_clients(settings)
        try:
            acct = trading.get_account()
        except Exception as e:
            mode = "PAPER" if settings.alpaca_paper else "LIVE"
            console.print(Panel(f"[red]Alpaca auth failed[/red] (mode={mode})\n{e}", title="Error", expand=False))
            raise typer.Exit(code=1)
        
        cash = to_float(getattr(acct, "cash", None)) or 0.0
        equity = to_float(getattr(acct, "equity", None)) or 0.0
        bp = to_float(getattr(acct, "buying_power", None)) or 0.0
        
        # Safety checks
        live_ok = bool(live) and not bool(settings.alpaca_paper)
        if execute and not settings.alpaca_paper and not live_ok:
            console.print(Panel("[red]Refusing to execute[/red]: ALPACA_PAPER is false.", title="Safety", expand=False))
            raise typer.Exit(code=1)
        
        # Build budget plans
        budget_total = max(0.0, cash)
        plans = build_budget_plans(cash=cash, mode=budget_mode_s, allocation=allocation_s, min_new_trades=min_n)
        active_plan = plans[0]
        budget_plans = [{"name": p.name, "budget_equity": p.budget_equity, "budget_options": p.budget_options, "note": p.note} for p in plans]
        
        # Fetch positions
        positions = fetch_positions(trading)
        held = get_held_underlyings(positions)
        stops = stop_candidates(positions, stop_loss_pct=stop_loss_pct)
        und_px_map = _fetch_underlying_prices(positions, settings)
        
        # Display
        display_positions_table(console, positions, stops, und_px_map)
        display_status_panel(console, equity=equity, cash=cash, buying_power=bp, stop_count=len(stops),
                            stop_loss_pct=stop_loss_pct, budget_total=budget_total, budget_mode=budget_mode_s,
                            budget_plans=budget_plans, min_trades=min_n, max_trades=max_n)
        
        live_confirmed = [False]
        
        # Position review
        if review_positions and positions:
            for p in positions:
                sym = str(p.get("symbol") or "")
                if not sym:
                    continue
                uplpc = p.get("unrealized_plpc")
                u_str = f"{float(uplpc)*100:.1f}%" if isinstance(uplpc, (int, float)) else "-"
                console.print(Panel(f"{sym} qty={p.get('qty')} uPL%={u_str}", title="Review", expand=False))
                if typer.confirm(f"Close {sym}?", default=False):
                    if execute:
                        if live_ok:
                            _ensure_live_confirmed(console, live_ok, live_confirmed)
                        try:
                            trading.close_position(sym)
                            console.print(f"[green]Closed[/green]: {sym}")
                        except Exception as e:
                            console.print(f"[red]Failed[/red]: {e}")
                    else:
                        console.print(f"[dim]DRY RUN[/dim]")
        
        # Get universe
        symbols = _get_universe_symbols(basket)
        if execute:
            tradable, skipped = [], []
            for s in symbols:
                try:
                    a = trading.get_asset(s)
                    (tradable if getattr(a, "tradable", True) else skipped).append(s)
                except Exception:
                    skipped.append(s)
            if skipped:
                console.print(Panel(f"Skipping {len(skipped)} non-tradable", title="Filter", expand=False))
            symbols = tradable
        
        # Data
        px = fetch_equity_daily_closes(settings=settings, symbols=symbols, start=start, refresh=refresh).sort_index().ffill()
        cache_dir = Path("data/cache/playbook")
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = cache_dir / f"regime_features_{start}.csv"
        if cache_path.exists() and not refresh:
            X = pd.read_csv(cache_path, parse_dates=["date"]).set_index("date")
        else:
            X = build_regime_feature_matrix(settings=settings, start_date=start, refresh_fred=refresh)
            X.reset_index().rename(columns={"index": "date"}).to_csv(cache_path, index=False)
        
        asof_ts = pd.to_datetime(X.index.max())
        
        # Ideas
        candidates = generate_ideas(engine=engine, prices=px, regime_features=X, symbols=symbols,
                                   asof=asof_ts, require_positive_score=require_positive_score,
                                   feature_set=feature_set, interaction_mode=interaction_mode, whitelist_extra=whitelist_extra)
        candidates = [c for c in candidates if c.get("ticker", "").upper() not in held]
        if thesis_s != "none":
            candidates = apply_thesis_reweighting(candidates, thesis_s)
        
        # Options
        with_options_effective = with_options and (budget_mode_s == "flex" or active_plan.budget_options > 0)
        legs = {}
        if with_options_effective and candidates:
            legs = attach_option_legs(candidates=candidates, data_client=data, settings=settings,
                                     max_premium_usd=max_premium_usd, min_days=min_days, max_days=max_days,
                                     target_abs_delta=target_abs_delta, max_spread_pct=max_spread_pct,
                                     budget_mode=budget_mode_s, budget_total=budget_total, max_candidates=max(10, max_n * 3))
        
        # Proposals
        result = build_proposals(candidates=candidates, legs=legs, prices=px, plan=active_plan, held_underlyings=held,
                                budget_mode=budget_mode_s, flex_prefer=flex_prefer_s, with_options=with_options_effective,
                                max_premium_usd=max_premium_usd, shares_budget_usd=shares_budget_usd,
                                max_new_trades=max_n, min_new_trades=min_n)
        
        proposed_dicts = _convert_proposals_to_dicts(result.proposals)
        if proposed_dicts:
            display_proposals_table(console, proposed_dicts, active_plan.name, px)
        else:
            console.print(Panel(f"No trades with cash=${budget_total:,.2f}", title="Warning", expand=False))
        
        display_budget_summary(console, budget_mode=budget_mode_s, budget_equity=active_plan.budget_equity,
                              budget_options=active_plan.budget_options, budget_total=budget_total,
                              remaining_equity=result.remaining_equity, remaining_options=result.remaining_options,
                              remaining_total=result.remaining_total)
        
        # Execute
        if execute and result.proposals:
            label = "LIVE" if live_ok else "PAPER"
            if not typer.confirm(f"Submit {len(result.proposals)} {label} trade(s)?", default=False):
                raise typer.Exit(code=0)
            if live_ok:
                _ensure_live_confirmed(console, live_ok, live_confirmed)
            for p in result.proposals:
                if p.kind == "OPEN_OPTION" and p.leg:
                    try:
                        submit_option_order(trading=trading, symbol=p.leg["symbol"], qty=1, side="buy", limit_price=float(p.leg["price"]), tif="day")
                        console.print(f"[green]Submitted[/green] option: {p.leg['symbol']}")
                    except Exception as e:
                        console.print(f"[red]Rejected[/red]: {e}")
                elif p.kind == "OPEN_SHARES":
                    try:
                        submit_equity_order(trading=trading, symbol=p.ticker, qty=p.qty, side="buy", limit_price=None, tif="day")
                        console.print(f"[green]Submitted[/green]: {p.qty}x {p.ticker}")
                    except Exception as e:
                        console.print(f"[red]Rejected[/red]: {e}")

    @autopilot_app.command("basic")
    def basic_run(
        sleeves: str = typer.Option("macro,vol,ai-bubble", "--sleeves"),
        basket: str = typer.Option("extended", "--basket"),
        engine: str = typer.Option("ml", "--engine"),
        allocation: str = typer.Option("70_30", "--allocation"),
        min_days: int = typer.Option(90, "--min-days"),
        max_days: int = typer.Option(120, "--max-days"),
        max_premium_usd: float = typer.Option(150.0, "--max-premium"),
        max_new_trades: int = typer.Option(8, "--max-new-trades"),
        min_new_trades: int = typer.Option(4, "--min-new-trades"),
        with_options: bool = typer.Option(True, "--with-options/--no-options"),
        llm: bool = typer.Option(False, "--llm"),
        llm_news: bool = typer.Option(True, "--llm-news/--no-llm-news"),
        show_basket: bool = typer.Option(False, "--show-basket/--no-show-basket"),
    ):
        """Professional basic run with sensible defaults."""
        run_once(start="2012-01-01", refresh=False, engine=str(engine), basket=str(basket),
                sleeves=str(sleeves), predictions=False, top_predictions=15, feature_set="fci",
                interaction_mode="whitelist", whitelist_extra="none", thesis="none", explain=True,
                stop_loss_pct=0.30, review_positions=True, execute=False, live=False,
                budget_mode="strict", allocation=str(allocation), max_new_trades=int(max_new_trades),
                min_new_trades=int(min_new_trades), flex_prefer="options", with_options=bool(with_options),
                max_premium_usd=float(max_premium_usd), min_days=int(min_days), max_days=int(max_days),
                target_abs_delta=0.30, max_spread_pct=0.30, shares_budget_usd=100.0,
                require_positive_score=True, llm=bool(llm), llm_model="", llm_temperature=0.2,
                llm_news=bool(llm_news), llm_calendar_days=10, llm_calendar_max_items=18,
                llm_news_days=7, llm_news_max_items=18, llm_gate=False, llm_gate_override=False,
                llm_positions_outlook=True, show_basket=bool(show_basket))
