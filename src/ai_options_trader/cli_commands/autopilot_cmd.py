from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ai_options_trader.config import load_settings
from ai_options_trader.data.alpaca import make_clients
from ai_options_trader.options.targets import required_underlying_move_for_profit_pct, format_required_move
from ai_options_trader.strategies.sleeves import resolve_sleeves


def _to_float(x) -> float | None:
    try:
        return float(x) if x is not None else None
    except Exception:
        return None


def _stop_candidates(positions: list[dict], *, stop_loss_pct: float) -> list[dict]:
    out = []
    for p in positions:
        uplpc = p.get("unrealized_plpc")
        if isinstance(uplpc, (int, float)) and uplpc <= -abs(float(stop_loss_pct)):
            out.append(p)
    return out


def register(autopilot_app: typer.Typer) -> None:
    @autopilot_app.command("run-once")
    def run_once(
        start: str = typer.Option("2012-01-01", "--start", help="Start date YYYY-MM-DD for regime feature matrix"),
        refresh: bool = typer.Option(False, "--refresh", help="Force refresh FRED downloads (regimes)"),
        engine: str = typer.Option(
            "analog",
            "--engine",
            help="playbook|analog|ml (analog adds factor-momentum features to regime similarity; ml uses panel model forecast)",
        ),
        basket: str = typer.Option("starter", "--basket", help="starter|extended (universe for idea generation)"),
        sleeves: str = typer.Option(
            "",
            "--sleeves",
            help="Optional: multi-sleeve mode (comma/space-separated): macro, vol, ai-bubble. If omitted, uses legacy macro-only pipeline.",
        ),
        predictions: bool = typer.Option(
            False,
            "--predictions",
            help="Predictions-only mode: output predicted direction/ranks for the basket(s) (no budgeting, no aggregator, no trade selection, no execution).",
        ),
        top_predictions: int = typer.Option(
            15,
            "--top-predictions",
            help="(predictions mode) How many tickers per sleeve to print.",
        ),
        feature_set: str = typer.Option("fci", "--feature-set", help="full|fci (used when --engine ml)"),
        interaction_mode: str = typer.Option("whitelist", "--interaction-mode", help="none|whitelist|all (used when --engine ml)"),
        whitelist_extra: str = typer.Option(
            "none",
            "--whitelist-extra",
            help="none|macro|funding|rates|vol|commod|fiscal (A/B: add a second whitelist interaction family; use with --interaction-mode whitelist)",
        ),
        thesis: str = typer.Option(
            "none",
            "--thesis",
            help="none|inflation_fiscal. If set, reweights rankings toward the thesis (still hedged + budget-aware).",
        ),
        explain: bool = typer.Option(True, "--explain/--no-explain", help="Print WHY THESE TRADES (drivers + event focus)"),
        stop_loss_pct: float = typer.Option(0.30, "--stop-loss", help="Close candidates when unrealized P/L% <= -X"),
        review_positions: bool = typer.Option(True, "--review-positions/--no-review-positions", help="Interactively review open positions (close/keep)"),
        execute: bool = typer.Option(False, "--execute", help="If set, can submit orders after confirmation (paper by default; use --live for live)"),
        live: bool = typer.Option(False, "--live", help="Allow LIVE execution when ALPACA_PAPER is false (guarded with extra confirmations)"),
        budget_mode: str = typer.Option(
            "strict",
            "--budget-mode",
            help="strict|flex. strict enforces max-premium and equity/options split. flex allocates full cash across >=min trades (still stays within cash).",
        ),
        allocation: str = typer.Option(
            "auto",
            "--allocation",
            help="auto|equity100|50_50|both (applies to --budget-mode strict only). 'both' prints both plans and lets you pick one to execute.",
        ),
        max_new_trades: int = typer.Option(3, "--max-new-trades", help="Max new trades to open in one run"),
        min_new_trades: int = typer.Option(2, "--min-new-trades", help="Try to produce at least this many new trades (if feasible)"),
        flex_prefer: str = typer.Option(
            "options",
            "--flex-prefer",
            help="options|shares (only used when --budget-mode flex). Defaults to options (convex bias).",
        ),
        with_options: bool = typer.Option(True, "--with-options/--no-options", help="Prefer <=$100 calls/puts when possible"),
        max_premium_usd: float = typer.Option(100.0, "--max-premium", help="Max premium per option contract (USD)"),
        min_days: int = typer.Option(30, "--min-days", help="Min option DTE (calendar days)"),
        max_days: int = typer.Option(90, "--max-days", help="Max option DTE (calendar days)"),
        target_abs_delta: float = typer.Option(0.30, "--target-abs-delta", help="Target |delta| for option leg"),
        max_spread_pct: float = typer.Option(0.30, "--max-spread-pct", help="Prefer spreads <= this"),
        shares_budget_usd: float = typer.Option(100.0, "--shares-budget", help="Approx $ budget for share buys per idea"),
        require_positive_score: bool = typer.Option(True, "--require-positive-score/--allow-negative-score", help="Only propose ideas with score > 0"),
        llm: bool = typer.Option(False, "--llm", help="Ask LLM to summarize + propose actions (no auto execution)"),
        llm_model: str = typer.Option("", "--llm-model", help="Override OPENAI_MODEL (optional)"),
        llm_temperature: float = typer.Option(0.2, "--llm-temperature", help="LLM temperature (0..2)"),
        llm_news: bool = typer.Option(True, "--llm-news/--no-llm-news", help="Include concrete risk overlay inputs (calendar + headlines + sentiment) in LLM review"),
        llm_calendar_days: int = typer.Option(10, "--llm-calendar-days", help="Days ahead to include economic calendar events (LLM overlay)"),
        llm_calendar_max_items: int = typer.Option(18, "--llm-calendar-max-items", help="Max econ calendar events to include (LLM overlay)"),
        llm_news_days: int = typer.Option(7, "--llm-news-days", help="News lookback window (days) (LLM overlay)"),
        llm_news_max_items: int = typer.Option(18, "--llm-news-max-items", help="Max news items to include (LLM overlay)"),
        llm_gate: bool = typer.Option(False, "--llm-gate", help="Require LLM DECISION=GO before allowing execution (risk overlay gate)"),
        llm_gate_override: bool = typer.Option(False, "--llm-gate-override", help="Ignore LLM gate and allow execution anyway"),
        llm_positions_outlook: bool = typer.Option(True, "--llm-positions-outlook/--no-llm-positions-outlook", help="Have the LLM give an outlook per current position before recommending new trades"),
    ):
        """
        Macro autopilot (MVP): run once.

        Steps:
        - Pull current Alpaca positions and flag stop-loss candidates (<= -stop_loss_pct).
        - Optionally prompt to close those positions (paper-first).
        - Run the macro playbook and print ideas (use `lox ideas macro-playbook` for details/options legs).
        - Optionally generate an LLM decision memo.

        Safety:
        - Never executes unless `--execute` is set AND ALPACA_PAPER is true AND you confirm.
        """
        settings = load_settings()
        console = Console()

        trading, _data = make_clients(settings)
        try:
            acct = trading.get_account()
        except Exception as e:
            # Alpaca uses different API keys for paper vs live.
            # If ALPACA_PAPER=false but keys are paper (or otherwise invalid), Alpaca returns 401 unauthorized.
            mode = "PAPER" if bool(settings.alpaca_paper) else "LIVE"
            hint = (
                f"Alpaca authorization failed while requesting /v2/account (mode={mode}).\n"
                "Most common causes:\n"
                "- ALPACA_PAPER=false but you're still using PAPER API keys (live requires live keys)\n"
                "- API key/secret are missing or incorrect\n"
                "- The Alpaca account is not enabled/approved for trading\n\n"
                "Fix:\n"
                "- If you want paper trading: set ALPACA_PAPER=true\n"
                "- If you want live trading: create LIVE API keys in Alpaca and set ALPACA_API_KEY/ALPACA_API_SECRET\n"
            )
            raise RuntimeError(hint) from e
        cash = _to_float(getattr(acct, "cash", None)) or 0.0
        equity = _to_float(getattr(acct, "equity", None)) or 0.0
        bp = _to_float(getattr(acct, "buying_power", None)) or 0.0

        budget_mode_s = (budget_mode or "strict").strip().lower()
        if budget_mode_s not in {"strict", "flex"}:
            budget_mode_s = "strict"
        allocation_s = (allocation or "auto").strip().lower()
        if allocation_s not in {"auto", "equity100", "50_50", "both"}:
            allocation_s = "auto"
        flex_prefer_s = (flex_prefer or "options").strip().lower()
        if flex_prefer_s not in {"options", "shares"}:
            flex_prefer_s = "options"
        thesis_s = (thesis or "none").strip().lower()
        if thesis_s not in {"none", "inflation_fiscal"}:
            thesis_s = "none"
        min_new_trades_n = max(0, int(min_new_trades))
        max_new_trades_n = max(int(max_new_trades), min_new_trades_n if min_new_trades_n > 0 else 0)

        # -------------------------------------------------------------------
        # Predictions-only mode: run the shared sleeve pipeline in "predict" mode and exit.
        # This intentionally ignores budgeting and does NOT propose trades.
        # -------------------------------------------------------------------
        if bool(predictions):
            # Lazy import so test collection doesn't require Alpaca SDK.
            from ai_options_trader.strategies.pipeline import run_sleeves_pipeline

            sleeve_names: list[str] = []
            if str(sleeves or "").strip():
                sleeve_names = [x.strip() for x in str(sleeves).replace(",", " ").split() if x.strip()]
            if not sleeve_names:
                sleeve_names = ["macro"]
            cfgs = resolve_sleeves(sleeve_names)

            runs, meta = run_sleeves_pipeline(
                settings=settings,
                sleeves=cfgs,
                basket=str(basket),
                engine=str(engine),
                start=str(start),
                refresh=bool(refresh),
                # Predictions should always print something; don't filter out negative scores here.
                require_positive_score=False,
                with_options=False,
                max_premium_usd=float(max_premium_usd),
                min_days=int(min_days),
                max_days=int(max_days),
                target_abs_delta=float(target_abs_delta),
                max_spread_pct=float(max_spread_pct),
                shares_budget_usd=float(shares_budget_usd),
                predictions_only=True,
                max_candidates_per_sleeve=max(1, int(top_predictions)),
                data_client=None,
            )
            if meta.get("status") != "ok":
                console.print(Panel(f"Predictions pipeline status: {meta}", title="Predictions", expand=False))
                raise typer.Exit(code=1)

            t = Table(title=f"Predictions (no trades) — engine={meta.get('engine')} asof={meta.get('asof')} basket={meta.get('basket')}")
            t.add_column("sleeve", style="bold")
            t.add_column("ticker", style="bold")
            t.add_column("dir", style="bold")
            t.add_column("score", justify="right")
            t.add_column("expRet", justify="right")
            t.add_column("prob", justify="right")
            t.add_column("expX", justify="right")
            t.add_column("probX", justify="right")
            t.add_column("risk_factors")
            for r in runs:
                shown = r.candidates[: max(1, int(top_predictions))]
                for c in shown:
                    expx = None
                    probx = None
                    try:
                        m = c.meta if isinstance(c.meta, dict) else {}
                        # The sleeve pipeline stores the full PlaybookIdea-derived values only in the object fields,
                        # but we can access them via attached notes when present.
                        # For MVP, we reconstruct from the standardized fields when available.
                        # (expRet/prob already printed; excess values are provided when benchmark is enabled.)
                        # NOTE: expRet/prob refer to absolute stats; expX/probX refer to excess vs benchmark.
                        expx = m.get("exp_return_excess")  # may be missing
                        probx = m.get("hit_rate_excess")
                    except Exception:
                        expx = None
                        probx = None
                    t.add_row(
                        c.sleeve,
                        c.ticker,
                        ("UP" if str(c.direction).lower().startswith("bull") else "DOWN"),
                        f"{float(c.score):.2f}",
                        (f"{float(c.expRet):+.2f}%" if c.expRet is not None else "—"),
                        (f"{float(c.prob):.0%}" if c.prob is not None else "—"),
                        (f"{float(expx):+.2f}%" if isinstance(expx, (int, float)) else "—"),
                        (f"{float(probx):.0%}" if isinstance(probx, (int, float)) else "—"),
                        ", ".join(c.risk_factors or ()),
                    )
            console.print(t)
            raise typer.Exit(code=0)

        # -------------------------------------------------------------------
        # Multi-sleeve mode (MVP): shared sleeve pipeline + portfolio aggregator.
        # Triggered only when more than one sleeve is specified, or when a non-macro sleeve is specified.
        # Backward compatible: `--sleeves macro` (or empty) runs the legacy path below.
        # -------------------------------------------------------------------
        sleeve_names: list[str] = []
        if str(sleeves or "").strip():
            sleeve_names = [x.strip() for x in str(sleeves).replace(",", " ").split() if x.strip()]
        want_multi = False
        if sleeve_names:
            low = [x.lower() for x in sleeve_names]
            want_multi = (len(low) > 1) or (len(low) == 1 and low[0] not in {"macro", "core"})

        if want_multi:
            # Lazy imports here so test collection doesn't require the Alpaca SDK.
            from ai_options_trader.strategies.pipeline import run_sleeves_pipeline
            from ai_options_trader.strategies.aggregator import PortfolioAggregator

            # Safety checks (mirror the existing guard rails)
            live_ok = bool(live) and (not bool(settings.alpaca_paper))
            if execute and (not settings.alpaca_paper) and (not live_ok):
                console.print(
                    Panel(
                        "[red]Refusing to execute[/red] because ALPACA_PAPER is false.\n"
                        "If you intend LIVE trading, re-run with [b]--live --execute[/b].",
                        title="Safety",
                        expand=False,
                    )
                )
                raise typer.Exit(code=1)
            if execute and live_ok:
                console.print(
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

            cfgs = resolve_sleeves(sleeve_names)
            runs, meta = run_sleeves_pipeline(
                settings=settings,
                sleeves=cfgs,
                basket=str(basket),
                engine=str(engine),
                start=str(start),
                refresh=bool(refresh),
                require_positive_score=bool(require_positive_score),
                with_options=bool(with_options),
                max_premium_usd=float(max_premium_usd),
                min_days=int(min_days),
                max_days=int(max_days),
                target_abs_delta=float(target_abs_delta),
                max_spread_pct=float(max_spread_pct),
                shares_budget_usd=float(shares_budget_usd),
                max_candidates_per_sleeve=max(8, int(max_new_trades_n) * 4),
                data_client=_data,
            )
            if meta.get("status") != "ok":
                console.print(Panel(f"Multi-sleeve pipeline status: {meta}", title="Sleeves", expand=False))
                raise typer.Exit(code=1)

            # Aggregate with sleeve budgets
            all_cands = [c for r in runs for c in r.candidates]
            sleeve_budget_pct = {c.name: float(c.risk_budget_pct) for c in cfgs}
            agg = PortfolioAggregator(factor_cap=1)
            res = agg.aggregate(candidates=all_cands, total_budget_usd=float(max(0.0, cash)), sleeve_budgets_pct=sleeve_budget_pct)

            # Print combined table (compare sleeves side-by-side)
            t = Table(title=f"Autopilot (multi-sleeve) — engine={meta.get('engine')} asof={meta.get('asof')} cash≈${cash:,.2f}")
            t.add_column("sleeve", style="bold")
            t.add_column("action", style="bold")
            t.add_column("ticker", style="bold")
            t.add_column("score", justify="right")
            t.add_column("expRet", justify="right")
            t.add_column("prob", justify="right")
            t.add_column("expr")
            t.add_column("risk_factors")
            t.add_column("est_cost", justify="right")
            for c in res.selected[: max(1, int(max_new_trades_n))]:
                t.add_row(
                    c.sleeve,
                    c.action,
                    c.ticker,
                    f"{float(c.score):.2f}",
                    (f"{float(c.expRet):+.2f}%" if c.expRet is not None else "—"),
                    (f"{float(c.prob):.0%}" if c.prob is not None else "—"),
                    str(c.expr or "—"),
                    ", ".join(c.risk_factors or ()),
                    (f"${float(c.est_cost_usd):,.2f}" if c.est_cost_usd is not None else "—"),
                )
            console.print(t)

            if res.dropped:
                console.print(Panel(f"Dropped {len(res.dropped)} candidate(s) due to caps/budgets.", title="Aggregator", expand=False))

            # Optional LLM overlay (post-aggregation; MVP keeps one overlay call)
            if bool(llm):
                try:
                    from ai_options_trader.llm.macro_recommendation import llm_macro_recommendation

                    memo = llm_macro_recommendation(
                        settings=settings,
                        asof=str(meta.get("asof") or ""),
                        regime_features=dict(meta.get("regime_features") or {}),
                        candidates=[c.__dict__ for c in all_cands],
                        budgeted_recommendations=[c.__dict__ for c in res.selected[: max(1, int(max_new_trades_n))]],
                        account={"cash": cash, "equity": equity, "buying_power": bp},
                        positions=None,
                        risk_watch=None,
                        news=None,
                        require_decision_line=bool(llm_gate),
                        model=(llm_model.strip() or None),
                        temperature=float(llm_temperature),
                    )
                    console.print(Panel(memo, title="LLM memo (post-aggregation)", expand=False))
                except Exception as e:
                    console.print(Panel(f"[yellow]LLM unavailable[/yellow]\n{type(e).__name__}: {e}", title="LLM", expand=False))

            # Optional execution (confirmation-gated). MVP: OPEN_OPTION qty=1, OPEN_SHARES qty from meta.
            if bool(execute):
                from ai_options_trader.execution.alpaca import submit_option_order, submit_equity_order

                label = "LIVE" if live_ok else "PAPER"
                for c in res.selected[: max(1, int(max_new_trades_n))]:
                    if c.action == "OPEN_OPTION" and c.expr:
                        sym = str(c.expr)
                        limit_px = None
                        try:
                            leg = (c.meta or {}).get("option_leg") if isinstance(c.meta, dict) else None
                            limit_px = float(leg.get("price")) if isinstance(leg, dict) and leg.get("price") else None
                        except Exception:
                            limit_px = None
                        if limit_px is None:
                            console.print(f"[yellow]Skip[/yellow] {sym}: missing limit price (option snapshot incomplete).")
                            continue
                        if not typer.confirm(f"Submit {label} option order: BUY 1 {sym} (limit≈{limit_px:.2f})?", default=False):
                            continue
                        resp = submit_option_order(trading=trading, symbol=sym, qty=1, side="buy", limit_price=float(limit_px), tif="day")
                        console.print(f"[green]Submitted[/green]: {resp}")
                    elif c.action == "OPEN_SHARES":
                        qty = 1
                        limit_px = None
                        try:
                            qty = int((c.meta or {}).get("qty") or 1)
                            limit_px = (c.meta or {}).get("limit")
                            limit_px = float(limit_px) if limit_px is not None else None
                        except Exception:
                            qty = 1
                            limit_px = None
                        if not typer.confirm(f"Submit {label} equity order: BUY {qty} {c.ticker} (limit≈{limit_px if limit_px else 'mkt'})?", default=False):
                            continue
                        resp = submit_equity_order(trading=trading, symbol=str(c.ticker), qty=int(qty), side="buy", limit_price=limit_px, tif="day")
                        console.print(f"[green]Submitted[/green]: {resp}")
                    else:
                        console.print(f"[dim]Skip unsupported action in MVP: {c.action}[/dim]")

            raise typer.Exit(code=0)

        # Budgeting: stay within available cash.
        budget_total = float(max(0.0, cash))
        budget_plans: list[dict] = []
        if budget_mode_s == "flex":
            budget_plans = [
                {
                    "name": "flex",
                    "budget_equity": budget_total,
                    "budget_options": budget_total,
                    "note": f"Budget mode: FLEX (allocate across >= {min_new_trades_n} trade(s); max-premium is a hint, not a cap)",
                }
            ]
        else:
            def _strict_plan(kind: str) -> dict:
                k = (kind or "auto").strip().lower()
                if k == "equity100":
                    return {"name": "equity100", "budget_equity": budget_total, "budget_options": 0.0, "note": "Allocation: 100% equities"}
                if k == "50_50":
                    return {"name": "50_50", "budget_equity": 0.50 * budget_total, "budget_options": 0.50 * budget_total, "note": "Allocation: 50% equities / 50% options"}
                # auto (legacy behavior)
                # New drawdown-aware default:
                # - If cash >= $500: 70% equities / 30% options
                # - If cash < $500: 100% equities
                if budget_total >= 500.0:
                    return {
                        "name": "auto",
                        "budget_equity": 0.70 * budget_total,
                        "budget_options": 0.30 * budget_total,
                        "note": "Allocation: 70% equities / 30% options (auto since cash >= $500)",
                    }
                return {"name": "auto", "budget_equity": budget_total, "budget_options": 0.0, "note": "Allocation: 100% equities (auto since cash < $500)"}

            if allocation_s == "both":
                budget_plans = [_strict_plan("equity100"), _strict_plan("50_50")]
            else:
                budget_plans = [_strict_plan(allocation_s)]

        # Choose the active plan for the remainder of the run.
        # (If allocation=both, we still need a concrete plan for sizing/execution.)
        active_plan = budget_plans[0] if budget_plans else {"name": "auto", "budget_equity": budget_total, "budget_options": 0.0, "note": ""}
        budget_equity = float(active_plan.get("budget_equity") or 0.0)
        budget_options = float(active_plan.get("budget_options") or 0.0)
        budget_note = str(active_plan.get("note") or "").strip()

        # --- Positions ---
        try:
            raw_positions = trading.get_all_positions()
        except Exception as e:
            raise RuntimeError(f"Failed to fetch Alpaca positions: {e}")

        positions: list[dict] = []
        for p in raw_positions:
            positions.append(
                {
                    "symbol": getattr(p, "symbol", ""),
                    "qty": _to_float(getattr(p, "qty", None)),
                    "avg_entry_price": _to_float(getattr(p, "avg_entry_price", None)),
                    "current_price": _to_float(getattr(p, "current_price", None)),
                    "unrealized_pl": _to_float(getattr(p, "unrealized_pl", None)),
                    "unrealized_plpc": _to_float(getattr(p, "unrealized_plpc", None)),
                }
            )

        def _extract_underlying_from_symbol(sym: str) -> str | None:
            """
            Best-effort underlying extraction for option symbols like:
            - VIXY260220C00028000 -> VIXY
            - IEF260227P00095500  -> IEF
            Falls back to the raw symbol for equities.
            """
            s = (sym or "").strip().upper()
            if not s:
                return None
            m = re.match(r"^([A-Z]+)", s)
            if not m:
                return s
            return str(m.group(1))

        # Portfolio-awareness: treat both equity tickers and option underlyings as "already held".
        held_underlyings_initial: set[str] = set()
        for p in positions:
            sym = str(p.get("symbol") or "").strip().upper()
            if not sym:
                continue
            held_underlyings_initial.add(sym)
            und = _extract_underlying_from_symbol(sym)
            if und:
                held_underlyings_initial.add(und)

        stop = _stop_candidates(positions, stop_loss_pct=float(stop_loss_pct))

        # Report
        tbl = Table(title="Lox Fund: open positions")
        tbl.add_column("symbol", style="bold")
        tbl.add_column("und vs K", justify="right")
        tbl.add_column("qty", justify="right")
        tbl.add_column("avg_entry", justify="right")
        tbl.add_column("current", justify="right")
        tbl.add_column("uPL", justify="right")
        tbl.add_column("uPL%", justify="right")

        # Best-effort: show option underlyings vs strikes (quick visual moneyness).
        und_px_map: dict[str, float] = {}
        try:
            from ai_options_trader.data.market import fetch_equity_daily_closes

            option_unds: set[str] = set()
            for p0 in positions:
                sym0 = str(p0.get("symbol") or "").strip().upper()
                und0 = _extract_underlying_from_symbol(sym0)
                if not und0:
                    continue
                # Heuristic: option symbols include digits after the underlying prefix.
                if sym0 != und0 and any(ch.isdigit() for ch in sym0):
                    option_unds.add(und0)
            if option_unds:
                start_px = (datetime.now(timezone.utc) - timedelta(days=400)).date().isoformat()
                px_u = fetch_equity_daily_closes(settings=settings, symbols=sorted(option_unds), start=start_px, refresh=False).sort_index().ffill()
                if not px_u.empty:
                    last = px_u.iloc[-1].to_dict()
                    for k, v in (last or {}).items():
                        try:
                            if v is None:
                                continue
                            und_px_map[str(k).strip().upper()] = float(v)
                        except Exception:
                            continue
        except Exception:
            und_px_map = {}

        for p in positions:
            uplpc = p.get("unrealized_plpc")
            style = "red" if p in stop else ""
            # Und vs strike (options only)
            und_vs_k = "—"
            try:
                sym = str(p.get("symbol") or "").strip().upper()
                und = _extract_underlying_from_symbol(sym) or ""
                if und and sym != und and any(ch.isdigit() for ch in sym):
                    from ai_options_trader.utils.occ import parse_occ_option_symbol

                    _exp, opt_type, strike = parse_occ_option_symbol(sym, und)
                    und_px = und_px_map.get(und)
                    if und_px is not None and strike is not None and float(strike) > 0:
                        k = float(strike)
                        if str(opt_type) == "put":
                            diff = k - float(und_px)
                            itm = float(und_px) < k
                        else:
                            diff = float(und_px) - k
                            itm = float(und_px) > k
                        pct = (diff / k) * 100.0
                        m = "ITM" if itm else "OTM"
                        und_vs_k = f"${float(und_px):.2f} vs ${k:.2f} ({pct:+.0f}% {m})"
            except Exception:
                und_vs_k = "—"
            tbl.add_row(
                str(p.get("symbol") or ""),
                und_vs_k,
                f"{p.get('qty'):.2f}" if isinstance(p.get("qty"), (int, float)) else "—",
                f"{p.get('avg_entry_price'):.2f}" if isinstance(p.get("avg_entry_price"), (int, float)) else "—",
                f"{p.get('current_price'):.2f}" if isinstance(p.get("current_price"), (int, float)) else "—",
                f"{p.get('unrealized_pl'):.2f}" if isinstance(p.get("unrealized_pl"), (int, float)) else "—",
                f"{float(uplpc)*100:.1f}%" if isinstance(uplpc, (int, float)) else "—",
                style=style,
            )
        console.print(tbl)

        status_body = (
            f"Account: equity=${equity:,.2f} cash=${cash:,.2f} buying_power=${bp:,.2f}\n"
            f"Stop candidates (<= -{float(stop_loss_pct)*100:.0f}%): {len(stop)}\n"
        )
        status_body += f"Trade budget (cash): ${budget_total:,.2f}\n"
        if budget_mode_s == "flex":
            status_body += f"{budget_plans[0]['note']}\n"
        else:
            if len(budget_plans) == 1:
                p = budget_plans[0]
                status_body += f"{p['note']} (shares≈${float(p['budget_equity']):,.2f} options≈${float(p['budget_options']):,.2f})\n"
            else:
                for p in budget_plans:
                    status_body += f"- {p['name']}: {p['note']} (shares≈${float(p['budget_equity']):,.2f} options≈${float(p['budget_options']):,.2f})\n"
        status_body += f"Target new trades: {min_new_trades_n}..{max_new_trades_n}"

        console.print(Panel(status_body, title="Autopilot status", expand=False))

        # Execution guardrails
        live_ok = bool(live) and (not bool(settings.alpaca_paper))
        live_confirmed = False

        def _ensure_live_confirmed() -> None:
            """
            Extra friction for live mode. We deliberately call this as late as possible so the LLM
            can review positions first, but before ANY live execution (closes or opens).
            """
            nonlocal live_confirmed
            if (not live_ok) or live_confirmed:
                return
            console.print(
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
            live_confirmed = True

        if execute and (not settings.alpaca_paper) and (not live_ok):
            console.print(
                Panel(
                    "[red]Refusing to execute[/red] because ALPACA_PAPER is false.\n"
                    "If you intend LIVE trading, re-run with [b]--live --execute[/b].",
                    title="Safety",
                    expand=False,
                )
            )
            raise typer.Exit(code=1)

        # LLM overlay context (built once; reused for per-position deck + later memo).
        asof_now = datetime.now(timezone.utc).date().isoformat()
        feat_row: dict = {}
        risk_watch: dict = {"trackers_asof": None, "trackers": {}, "events": []}
        news_payload: dict = {}

        # LLM-first position outlook (smarter macro trader overlay) BEFORE any interactive close prompts.
        # This gives an "opinion on the outlook for the trade" while grounding on trackers/events/headlines.
        if llm and (llm_positions_outlook or llm_gate) and positions:
            try:
                from ai_options_trader.regimes.feature_matrix import build_regime_feature_matrix
                from ai_options_trader.data.econ_release import fetch_fmp_economic_calendar, normalize_fmp_economic_calendar

                # Trackers from latest regime feature row.
                try:
                    X_now = build_regime_feature_matrix(settings=settings, start_date=str(start), refresh_fred=bool(refresh))
                    if not X_now.empty:
                        feat_row = X_now.iloc[-1].to_dict()
                        risk_watch["trackers_asof"] = str(X_now.index[-1].date())
                        keys = [
                            "macro_disconnect_score",
                            "usd_strength_score",
                            "rates_z_ust_10y",
                            "rates_z_curve_2s10s",
                            "vol_pressure_score",
                            "commod_pressure_score",
                            "fiscal_pressure_score",
                            "funding_tightness_score",
                        ]
                        risk_watch["trackers"] = {k: feat_row.get(k) for k in keys if k in feat_row}
                except Exception:
                    feat_row = {}

                # Calendar events (best-effort; requires FMP key)
                if getattr(settings, "fmp_api_key", None):
                    try:
                        # Use shared overlay helper so we consistently filter to US/USD events.
                        from ai_options_trader.overlay.context import fetch_calendar_events

                        risk_watch["events"] = fetch_calendar_events(
                            settings=settings,
                            days_ahead=int(llm_calendar_days),
                            max_items=int(llm_calendar_max_items),
                            us_only=True,
                        )
                    except Exception:
                        pass

                # News for held underlyings (best-effort; requires FMP key)
                if llm_news and getattr(settings, "fmp_api_key", None):
                    try:
                        from ai_options_trader.llm.ticker_news import fetch_fmp_stock_news
                        from ai_options_trader.llm.sentiment import rule_based_sentiment

                        held = set()
                        for p0 in positions:
                            sym0 = str(p0.get("symbol") or "")
                            m = re.match(r"^([A-Z]+)", sym0.strip().upper())
                            if m:
                                held.add(str(m.group(1)))
                        now = datetime.now(timezone.utc)
                        from_date = (now - timedelta(days=int(llm_news_days))).date().isoformat()
                        to_date = now.date().isoformat()
                        items = fetch_fmp_stock_news(settings=settings, tickers=sorted(held), from_date=from_date, to_date=to_date, max_pages=3)
                        items = sorted(items, key=lambda x: x.published_at, reverse=True)[: max(0, int(llm_news_max_items))]
                        items_by_ticker: dict[str, list[dict]] = {}
                        for it in items:
                            tk = str(getattr(it, "ticker", "") or "").strip().upper()
                            if not tk:
                                continue
                            items_by_ticker.setdefault(tk, []).append(
                                {
                                    "ticker": tk,
                                    "title": getattr(it, "title", None),
                                    "url": getattr(it, "url", None),
                                    "published_at": getattr(it, "published_at", None),
                                    "source": getattr(it, "source", None),
                                    "snippet": getattr(it, "snippet", None),
                                }
                            )
                        blob = "\n".join([f"{i.ticker}: {i.title} — {i.snippet or ''}" for i in items])[:8000]
                        sent = rule_based_sentiment(blob)
                        news_payload = {
                            "lookback_days": int(llm_news_days),
                            "tickers": sorted(held),
                            "sentiment": {"label": sent.label, "confidence": float(sent.confidence)},
                            "items_by_ticker": items_by_ticker,
                            "items": [
                                {"ticker": i.ticker, "title": i.title, "url": i.url, "published_at": i.published_at, "source": i.source}
                                for i in items
                            ],
                        }
                    except Exception:
                        news_payload = {}
            except Exception as e:
                console.print(Panel(f"[dim]LLM overlay context unavailable[/dim]: {type(e).__name__}: {e}", title="LLM overlay", expand=False))

        # Interactive position review (trade-by-trade)
        if review_positions and positions:
            for p in positions:
                sym = str(p.get("symbol") or "")
                if not sym:
                    continue

                # One-position LLM deck: show trade-metric-specific outlook BEFORE asking to close.
                if llm and llm_positions_outlook:
                    try:
                        from ai_options_trader.llm.positions_outlook import llm_position_outlook_one
                        from ai_options_trader.utils.occ import parse_occ_option_symbol

                        def _und_from_symbol(s0: str) -> str | None:
                            m0 = re.match(r"^([A-Z]+)", (s0 or "").strip().upper())
                            return str(m0.group(1)) if m0 else None

                        und = _und_from_symbol(sym) or sym.strip().upper()
                        qty = float(p.get("qty") or 0.0)
                        entry = _to_float(p.get("avg_entry_price")) or 0.0
                        cur = _to_float(p.get("current_price")) or 0.0
                        upl = _to_float(p.get("unrealized_pl")) or 0.0
                        uplpc = _to_float(p.get("unrealized_plpc"))
                        uplpc_pct = (float(uplpc) * 100.0) if isinstance(uplpc, (int, float)) else None

                        # Option metadata (if OCC-style symbol)
                        is_option = False
                        opt_meta = None
                        mult = 1.0
                        try:
                            exp, ot, st = parse_occ_option_symbol(sym, und)
                            is_option = True
                            mult = 100.0
                            dte = int((exp - datetime.now(timezone.utc).date()).days)
                            be = (float(st) + float(entry)) if ot == "call" else (float(st) - float(entry))
                            opt_meta = {
                                "expiry": exp.isoformat(),
                                "dte": dte,
                                "type": ot,
                                "strike": float(st),
                                "breakeven": float(be),
                                "multiplier": 100,
                            }
                        except Exception:
                            is_option = False

                        metrics = {
                            "underlying": und,
                            "is_option": bool(is_option),
                            "qty": qty,
                            "entry_price": float(entry),
                            "current_price": float(cur),
                            "pnl_usd": float(upl),
                            "pnl_pct": float(uplpc_pct) if uplpc_pct is not None else None,
                            "invested_usd": (float(abs(qty) * entry * mult) if entry else None),
                            "notional_usd": (float(abs(qty) * cur * mult) if cur else None),
                            "option": opt_meta,
                        }

                        # Trackers: focus subset by underlying heuristic.
                        tkr_u = und.strip().upper()
                        if tkr_u in {"GLDM", "GLD", "SLV", "GDX", "DBC", "USO", "CPER"}:
                            focus = ["commod_pressure_score", "usd_strength_score", "rates_z_ust_10y", "vol_pressure_score", "macro_disconnect_score"]
                        elif tkr_u in {"TBF", "TBT", "TMV", "SHY", "IEF", "TLT"}:
                            focus = ["rates_z_ust_10y", "rates_z_curve_2s10s", "macro_disconnect_score", "usd_strength_score", "vol_pressure_score"]
                        elif tkr_u in {"VIXY"}:
                            focus = ["vol_pressure_score", "rates_z_ust_10y", "usd_strength_score", "macro_disconnect_score"]
                        elif tkr_u in {"SQQQ", "PSQ", "SH", "SPXU", "TZA", "QID"}:
                            focus = ["vol_pressure_score", "rates_z_ust_10y", "usd_strength_score", "macro_disconnect_score"]
                        elif tkr_u in {"IBIT"}:
                            focus = ["usd_strength_score", "rates_z_ust_10y", "funding_tightness_score", "vol_pressure_score"]
                        else:
                            focus = ["macro_disconnect_score", "usd_strength_score", "rates_z_ust_10y", "vol_pressure_score"]

                        trackers = {k: feat_row.get(k) for k in focus if k in feat_row} if feat_row else (risk_watch.get("trackers") or {})

                        # Events: filter upcoming calendar by relevant keywords.
                        kw = []
                        if tkr_u in {"TBF", "TBT", "TMV", "IEF", "TLT", "SHY"}:
                            kw = ["cpi", "pce", "fomc", "auction", "treasury", "jobs", "payroll", "unemployment"]
                        elif tkr_u in {"GLDM", "GLD", "SLV", "GDX"}:
                            kw = ["cpi", "pce", "fomc", "jobs", "payroll", "unemployment"]
                        elif tkr_u in {"USO", "DBC", "CPER"}:
                            kw = ["cpi", "pce", "inventory", "jobs", "payroll"]
                        else:
                            kw = ["cpi", "pce", "fomc", "jobs", "payroll"]

                        evs = []
                        for e0 in (risk_watch.get("events") or []):
                            name = str(e0.get("event") or "").lower()
                            cat = str(e0.get("category") or "").lower()
                            ctry = str(e0.get("country") or "").lower()
                            curcat = str(e0.get("category") or "").lower()
                            # Avoid irrelevant global events for US-traded instruments.
                            # Keep only US/USD items unless the provider omitted country.
                            is_us = ("united states" in ctry) or (ctry == "us") or ("usd" in curcat)
                            if (not ctry) or is_us:
                                if any(k in name or k in cat for k in kw):
                                    evs.append(e0)
                            if len(evs) >= 6:
                                break

                        # Headlines: ticker-specific only (no global list).
                        headlines = []
                        try:
                            by_t = news_payload.get("items_by_ticker") or {}
                            headlines = list(by_t.get(tkr_u) or [])[:6]
                        except Exception:
                            headlines = []

                        # Add curated expert-watch links (link-only sources where appropriate).
                        try:
                            from ai_options_trader.overlay.expert_links import expert_links_for_ticker

                            for ln in expert_links_for_ticker(tkr_u):
                                headlines.append(
                                    {
                                        "ticker": tkr_u,
                                        "title": ln.name,
                                        "url": ln.url,
                                        "published_at": None,
                                        "source": "expert_link",
                                        "snippet": ln.notes,
                                    }
                                )
                            # Keep list tight
                            headlines = headlines[:6]
                        except Exception:
                            pass

                        # Crypto special-case: IBIT is a spot BTC ETF.
                        # Supplement with general-market crypto headlines when ticker-tagged news is sparse.
                        if tkr_u == "IBIT" and len(headlines) < 2 and getattr(settings, "fmp_api_key", None):
                            try:
                                from ai_options_trader.overlay.context import fetch_general_news_items, filter_news_items_by_keywords

                                g = fetch_general_news_items(settings=settings, max_pages=2, max_items=40)
                                extra = filter_news_items_by_keywords(
                                    g,
                                    keywords=["bitcoin", "btc", "crypto", "spot etf", "etf flows", "blackrock"],
                                    max_items=6,
                                )
                                for it in extra:
                                    headlines.append(
                                        {
                                            "ticker": "BTC",
                                            "title": it.get("title"),
                                            "url": it.get("url"),
                                            "published_at": it.get("published_at"),
                                            "source": it.get("source"),
                                            "snippet": it.get("snippet"),
                                        }
                                    )
                                headlines = headlines[:6]
                            except Exception:
                                pass

                        txt = llm_position_outlook_one(
                            settings=settings,
                            asof=asof_now,
                            position=p,
                            metrics=metrics,
                            trackers=trackers,
                            events=evs,
                            headlines=headlines,
                            model=llm_model.strip() or None,
                            temperature=float(llm_temperature),
                        )
                        console.print(Panel(txt, title="LLM trade outlook (1 position)", expand=False))
                    except Exception as e:
                        console.print(Panel(f"[dim]LLM trade outlook unavailable[/dim]: {type(e).__name__}: {e}", title="LLM overlay", expand=False))

                uplpc = p.get("unrealized_plpc")
                u_str = f"{float(uplpc)*100:.1f}%" if isinstance(uplpc, (int, float)) else "—"
                line = (
                    f"{sym}  qty={p.get('qty') if p.get('qty') is not None else '—'}  "
                    f"avg={p.get('avg_entry_price') if p.get('avg_entry_price') is not None else '—'}  "
                    f"px={p.get('current_price') if p.get('current_price') is not None else '—'}  "
                    f"uPL={p.get('unrealized_pl') if p.get('unrealized_pl') is not None else '—'}  "
                    f"uPL%={u_str}"
                )
                console.print(Panel(line, title="Position review", expand=False))
                if typer.confirm(f"Close {sym} now?", default=False):
                    if execute:
                        if live_ok:
                            _ensure_live_confirmed()
                        try:
                            trading.close_position(sym)
                            console.print(f"[green]Submitted close[/green]: {sym}")
                        except Exception as e:
                            console.print(f"[red]Failed to close {sym}[/red]: {e}")
                    else:
                        console.print(f"[dim]DRY RUN close[/dim]: {sym}")

        # --- Ideas / forecasts (playbook OR ML) ---
        from pathlib import Path
        import pandas as pd
        from ai_options_trader.data.market import fetch_equity_daily_closes
        try:
            from ai_options_trader.portfolio.universe import get_universe
        except Exception:  # pragma: no cover
            from ai_options_trader.portfolio.universe import STARTER_UNIVERSE, DEFAULT_UNIVERSE

            def get_universe(name: str):
                n = (name or "starter").strip().lower()
                if n.startswith("d"):
                    return DEFAULT_UNIVERSE
                return STARTER_UNIVERSE
        from ai_options_trader.regimes.feature_matrix import build_regime_feature_matrix
        from ai_options_trader.ideas.macro_playbook import rank_macro_playbook
        from ai_options_trader.options.budget_scan import affordable_options_for_ticker, pick_best_affordable
        from ai_options_trader.data.alpaca import fetch_option_chain, to_candidates

        uni = get_universe(basket)
        symbols = sorted(set(uni.basket_equity))

        # If we intend to execute, pre-filter to symbols Alpaca considers tradable (prevents mid-run crashes).
        if execute:
            tradable_ok: list[str] = []
            skipped: list[str] = []
            for s in symbols:
                try:
                    a = trading.get_asset(str(s))
                    if getattr(a, "tradable", True):
                        tradable_ok.append(str(s))
                    else:
                        skipped.append(str(s))
                except Exception:
                    skipped.append(str(s))
            if skipped:
                console.print(Panel(f"Skipping {len(skipped)} non-tradable/unavailable symbol(s): {', '.join(skipped[:20])}", title="Universe filter", expand=False))
            symbols = tradable_ok

        px = fetch_equity_daily_closes(settings=settings, symbols=symbols, start=start, refresh=bool(refresh)).sort_index().ffill()

        cache_dir = Path("data/cache/playbook")
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = cache_dir / f"regime_features_{start}.csv"
        if cache_path.exists() and not refresh:
            X = pd.read_csv(cache_path, parse_dates=["date"]).set_index("date")
        else:
            X = build_regime_feature_matrix(settings=settings, start_date=start, refresh_fred=refresh)
            X.reset_index().rename(columns={"index": "date"}).to_csv(cache_path, index=False)

        mode = (engine or "playbook").strip().lower()
        if mode not in {"playbook", "analog", "ml"}:
            mode = "playbook"

        # Standardized candidate schema to feed both the trade proposer and the LLM.
        candidates: list[dict] = []
        asof_ts = pd.to_datetime(X.index.max())

        if mode == "ml":
            from ai_options_trader.regimes.fci import build_fci_feature_matrix
            from ai_options_trader.portfolio.panel import build_macro_panel_dataset
            from ai_options_trader.portfolio.panel_model import fit_latest_with_models

            fs = (feature_set or "fci").strip().lower()
            Xr = build_fci_feature_matrix(X) if fs == "fci" else X
            extra = (whitelist_extra or "none").strip().lower()
            if fs == "fci" and extra in {"fiscal", "commod", "macro"}:
                cols = []
                if extra == "fiscal" and "fiscal_pressure_score" in X.columns:
                    cols = ["fiscal_pressure_score"]
                elif extra == "commod" and "commod_pressure_score" in X.columns:
                    cols = ["commod_pressure_score"]
                elif extra == "macro" and "macro_disconnect_score" in X.columns:
                    cols = ["macro_disconnect_score"]
                if cols:
                    Xr = Xr.join(X[cols], how="left")
            ds = build_macro_panel_dataset(
                regime_features=Xr,
                prices=px,
                tickers=list(symbols),
                horizon_days=63,
                interaction_mode=(interaction_mode or "whitelist").strip().lower(),
                whitelist_extra=whitelist_extra,
            )
            preds, meta, _clf, _reg, _Xte = fit_latest_with_models(X=ds.X, y=ds.y)
            if meta.get("status") != "ok":
                console.print(Panel(f"ML model status: {meta}", title="Autopilot ML", expand=False))
                preds = []
            for p in preds:
                exp_ret = float(p.exp_return) if p.exp_return is not None else None
                prob_up = float(p.prob_up) if p.prob_up is not None else None
                if exp_ret is None:
                    continue
                direction = "bullish" if exp_ret >= 0 else "bearish"
                score = abs(exp_ret) * (0.5 + (abs((prob_up or 0.5) - 0.5)))
                candidates.append(
                    {
                        "source": "ml",
                        "ticker": p.ticker,
                        "direction": direction,
                        "horizon_days": 63,
                        "exp_return_pred": exp_ret,
                        "prob_up_pred": prob_up,
                        "score": float(score),
                    }
                )
            candidates.sort(key=lambda d: float(d.get("score") or -1e9), reverse=True)
        else:
            # "analog": same playbook machinery (kNN in regime feature space) but with explicit
            # factor-momentum features so the similarity search respects *direction of travel*.
            Xm = X
            if mode == "analog":
                Xm = X.copy()
                mom_cols = [
                    "commod_pressure_score",
                    "fiscal_pressure_score",
                    "rates_z_ust_10y",
                    "rates_z_curve_2s10s",
                    "usd_strength_score",
                    "vol_pressure_score",
                    "funding_tightness_score",
                    "macro_disconnect_score",
                ]
                mom_cols = [c for c in mom_cols if c in Xm.columns]
                for w in (20, 60, 120):
                    for c in mom_cols:
                        Xm[f"{c}_mom{w}"] = pd.to_numeric(Xm[c], errors="coerce") - pd.to_numeric(Xm[c], errors="coerce").shift(int(w))

            ideas = rank_macro_playbook(
                features=Xm,
                prices=px,
                tickers=list(symbols),
                horizon_days=63,
                k=250,
                lookback_days=365 * 7,
                min_matches=60,
                asof=asof_ts,
            )
            if require_positive_score:
                ideas = [i for i in ideas if i.score > 0]
            for it in ideas:
                candidates.append(
                    {
                        "source": "analog" if mode == "analog" else "playbook",
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
                        "notes": it.notes,
                    }
                )

        # Portfolio-awareness: avoid recommending openings in symbols you already hold.
        if held_underlyings_initial:
            candidates = [c for c in candidates if str(c.get("ticker") or "").strip().upper() not in held_underlyings_initial]

        # Thesis reweighting: bias the ranking toward the chosen macro thesis without hard-filtering.
        # This is intentionally simple/transparent so the operator understands why items rise/fall.
        def _thesis_tag_weight(tkr: str) -> tuple[str, float]:
            t = (tkr or "").strip().upper()
            if thesis_s == "inflation_fiscal":
                # Inflation persistence (real assets + inflation-linked)
                inflation = {
                    "GLDM",
                    "GLD",
                    "SLV",
                    "GDX",
                    "DBC",
                    "USO",
                    "CPER",
                    "XLE",
                    "TIP",
                }
                # Fiscal wall / borrowing stress (rates up + hedges)
                fiscal_wall = {
                    "TBT",
                    "TBF",
                    "TMV",
                    "SH",
                    "PSQ",
                    "SDS",
                    "SQQQ",
                    "SPXU",
                    "SJB",
                    "UUP",
                    "VIXY",
                    "KRE",
                }
                credit = {"HYG", "LQD"}
                if t in inflation:
                    return "inflation", 1.35
                if t in credit:
                    # Credit is a fiscal-wall stress *channel*, but we will generally express it as a hedge (bearish).
                    return "credit_stress", 1.25
                if t in fiscal_wall:
                    return "fiscal_wall", 1.25
                # Neutral weight for broad beta sleeves
                return "neutral", 1.0
            return "neutral", 1.0

        if thesis_s != "none" and candidates:
            for c in candidates:
                tkr = str(c.get("ticker") or "")
                tag, w = _thesis_tag_weight(tkr)
                base = c.get("score")
                try:
                    base_f = float(base) if base is not None else 0.0
                except Exception:
                    base_f = 0.0
                c["score_raw"] = base_f
                c["thesis"] = thesis_s
                c["thesis_tag"] = tag
                c["thesis_weight"] = float(w)
                c["score"] = float(base_f) * float(w)

                # Thesis directional overrides (keep explicit and narrow).
                # Under inflation_fiscal, we generally treat corporate credit as a stress point → hedge, not long.
                if thesis_s == "inflation_fiscal" and tkr.strip().upper() in {"HYG", "LQD"}:
                    c["direction"] = "bearish"
                    c["exposure"] = "bearish"
                    c["thesis_override"] = "credit_bearish"
            candidates.sort(key=lambda d: float(d.get("score") or -1e9), reverse=True)

        # Attach option legs when enabled
        legs: dict[str, dict] = {}
        # If we're under the drawdown threshold (strict plan has options=$0), force equities-only.
        with_options_effective = bool(with_options) and (budget_mode_s == "flex" or float(budget_options) > 0.0)
        if (not with_options_effective) and bool(with_options) and budget_mode_s == "strict" and float(budget_options) <= 0.0:
            console.print(Panel("Options disabled for this run because allocation is equities-only (cash < $500).", title="Allocator", expand=False))

        if with_options_effective and candidates:
            pb = "ask"
            precompute_max_premium = float(budget_total) if budget_mode_s == "flex" else float(max_premium_usd)
            for it in candidates[: max(10, int(max_new_trades_n) * 3)]:
                want = "call" if it.get("direction") == "bullish" else "put"
                try:
                    tkr = str(it.get("ticker") or "")
                    if not tkr:
                        continue
                    chain = fetch_option_chain(_data, tkr, feed=settings.alpaca_options_feed)
                    cands = list(to_candidates(chain, tkr))
                    opts = affordable_options_for_ticker(
                        cands,
                        ticker=tkr,
                        max_premium_usd=float(precompute_max_premium),
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
                        legs[tkr] = {
                            "symbol": best.symbol,
                            "type": best.opt_type,
                            "premium_usd": float(best.premium_usd),
                            "price": float(best.price),
                            "delta": float(best.delta) if best.delta is not None else None,
                        }
                except Exception:
                    continue

        # Propose actions (budget-aware). Support multiple strict plans (allocation=both).
        def _build_proposed_for_budgets(*, beq: float, bop: float) -> tuple[list[dict], float, float, float]:
            remaining_total = float(max(0.0, budget_total))
            remaining_equity = float(max(0.0, beq)) if budget_mode_s == "strict" else 0.0
            remaining_options = float(max(0.0, bop)) if budget_mode_s == "strict" else 0.0
            proposed: list[dict] = []
            opened: set[str] = set()
            n_bullish = 0
            n_bearish = 0

            inverse_proxy: dict[str, str] = {
                # Equity indices
                "SPLG": "SH",
                "SPY": "SH",
                "QQQM": "PSQ",
                "QQQ": "PSQ",
                "IWM": "RWM",
                "DIA": "DOG",
                # Rates / credit
                "TLT": "TBF",
                "HYG": "SJB",
            }

            # Tickers that are hedge-like even if the model's predicted direction is "bullish"
            # (because the instrument itself is inverse/vol/short-credit).
            hedge_like_tickers: set[str] = {
                # Long vol
                "VIXY",
                # Inverse equity ETFs
                "SH",
                "SDS",
                "SPXU",
                "PSQ",
                "QID",
                "SQQQ",
                "RWM",
                "TWM",
                "TZA",
                "DOG",
                "DXD",
                # Rates / credit inverse/short
                "TBF",
                "TMV",
                "TBT",
                "SJB",
            }

            # Strong guardrail: avoid stacking multiple *leveraged* inverse equity ETFs.
            # These are highly correlated in stress and decay via daily reset.
            levered_inverse_equity: set[str] = {
                "SQQQ",
                "SPXU",
                "TZA",
                "SDS",
                "QID",
                "TWM",
                "DXD",
            }

            def _has_hedge_exposure() -> bool:
                return any(str(p.get("exposure") or "").strip().lower() == "bearish" for p in proposed)

            def _has_levered_inverse_equity() -> bool:
                return any(
                    str(p.get("kind") or "") == "OPEN_SHARES"
                    and str(p.get("ticker") or "").strip().upper() in levered_inverse_equity
                    for p in proposed
                )

            def _inverse_for(tkr: str) -> str | None:
                t = (tkr or "").strip().upper()
                return inverse_proxy.get(t)

            def _maybe_add_option(tkr: str, it: dict) -> bool:
                nonlocal remaining_total, remaining_options, proposed, n_bullish, n_bearish
                leg = legs.get(tkr)
                if not leg:
                    return False
                prem = float(leg.get("premium_usd") or 0.0)
                if prem <= 0:
                    return False
                if len(proposed) >= int(max_new_trades_n):
                    return False

                if budget_mode_s == "flex":
                    remaining_needed = max(1, int(min_new_trades_n) - len(proposed)) if int(min_new_trades_n) > 0 else 1
                    per_trade_cap = float(remaining_total) / float(max(1, remaining_needed))
                    if prem > remaining_total + 1e-9:
                        return False
                    # If we're still trying to reach min trades, keep any single leg from consuming too much.
                    if len(proposed) < int(min_new_trades_n) and prem > per_trade_cap + 1e-9:
                        return False
                    proposed.append({"kind": "OPEN_OPTION", "ticker": tkr, "leg": leg, "idea": it, "est_cost_usd": prem, "exposure": str(it.get("direction") or "")})
                    remaining_total -= prem
                    if str(it.get("direction") or "") == "bearish":
                        n_bearish += 1
                    else:
                        n_bullish += 1
                    return True
                else:
                    if prem > float(max_premium_usd) or prem > remaining_options:
                        return False
                    proposed.append({"kind": "OPEN_OPTION", "ticker": tkr, "leg": leg, "idea": it, "est_cost_usd": prem, "exposure": str(it.get("direction") or "")})
                    remaining_options -= prem
                    if str(it.get("direction") or "") == "bearish":
                        n_bearish += 1
                    else:
                        n_bullish += 1
                    return True

            def _maybe_add_shares(tkr: str, it: dict) -> bool:
                nonlocal remaining_total, remaining_equity, proposed, n_bullish, n_bearish
                last_px = _to_float(px[tkr].dropna().iloc[-1]) if tkr in px.columns else None
                if not last_px or last_px <= 0:
                    return False
                if len(proposed) >= int(max_new_trades_n):
                    return False
                if str(tkr).strip().upper() in opened:
                    return False

                if budget_mode_s == "flex":
                    if remaining_total <= 0:
                        return False
                    remaining_needed = max(1, int(min_new_trades_n) - len(proposed)) if int(min_new_trades_n) > 0 else 1
                    per_trade_cap = float(remaining_total) / float(max(1, remaining_needed))
                    alloc = float(per_trade_cap)
                    qty = int(alloc // float(last_px))
                    if qty <= 0:
                        return False
                    cost = float(qty) * float(last_px)
                    if cost > remaining_total + 1e-9:
                        return False
                    proposed.append({"kind": "OPEN_SHARES", "ticker": tkr, "qty": qty, "limit": float(last_px), "idea": it, "est_cost_usd": cost, "exposure": str(it.get("exposure") or it.get("direction") or "")})
                    opened.add(str(tkr).strip().upper())
                    remaining_total -= cost
                    if str(it.get("exposure") or it.get("direction") or "") == "bearish":
                        n_bearish += 1
                    else:
                        n_bullish += 1
                    return True
                else:
                    if remaining_equity <= 0:
                        return False
                    # Allocate up to shares_budget_usd per idea, but never exceed remaining equity budget.
                    alloc = float(min(float(shares_budget_usd), remaining_equity))
                    qty = int(alloc // float(last_px))
                    if qty <= 0:
                        return False
                    cost = float(qty) * float(last_px)
                    if cost > remaining_equity + 1e-9:
                        return False
                    proposed.append({"kind": "OPEN_SHARES", "ticker": tkr, "qty": qty, "limit": float(last_px), "idea": it, "est_cost_usd": cost, "exposure": str(it.get("exposure") or it.get("direction") or "")})
                    opened.add(str(tkr).strip().upper())
                    remaining_equity -= cost
                    if str(it.get("exposure") or it.get("direction") or "") == "bearish":
                        n_bearish += 1
                    else:
                        n_bullish += 1
                    return True

            # Simple allocator:
            # - strict: uses the earlier split and hard max-premium.
            # - flex: uses total cash and tries to reach >=min trades without micro-leg constraints.
            for it in candidates:
                if len(proposed) >= int(max_new_trades_n):
                    break
                tkr = str(it.get("ticker") or "")
                if not tkr:
                    continue
                direction = str(it.get("direction") or "")
                if tkr.strip().upper() in held_underlyings_initial:
                    continue

                # If the ticker itself is an inverse/hedge instrument, treat it as bearish exposure
                # for portfolio mix purposes (even if the predicted direction is "bullish").
                if tkr.strip().upper() in hedge_like_tickers:
                    # Avoid building a "one idea x3" basket by stacking multiple hedge instruments,
                    # especially leveraged inverse equity ETFs.
                    if _has_hedge_exposure():
                        continue
                    if tkr.strip().upper() in levered_inverse_equity and _has_levered_inverse_equity():
                        continue
                    it2 = dict(it)
                    it2["direction"] = "bullish"
                    it2["exposure"] = "bearish"
                    if _maybe_add_shares(tkr, it2):
                        continue

                # FLEX preference control (options-biased by default).
                if budget_mode_s == "flex" and flex_prefer_s == "shares":
                    if direction == "bullish" and _maybe_add_shares(tkr, it):
                        continue

                # Prefer options when enabled and available.
                if with_options_effective and legs.get(tkr):
                    if direction == "bullish" and legs.get(tkr, {}).get("type") == "call" and _maybe_add_option(tkr, it):
                        continue
                    if direction == "bearish" and legs.get(tkr, {}).get("type") == "put" and _maybe_add_option(tkr, it):
                        continue

                # Otherwise shares for bullish ideas, within equity budget.
                if direction == "bullish":
                    if _maybe_add_shares(tkr, it):
                        continue

                # If we want bearish exposure but we're in equities-only mode, try an inverse ETF proxy.
                if (not with_options_effective) and direction == "bearish":
                    inv = _inverse_for(tkr)
                    if inv and inv in px.columns and inv.strip().upper() not in held_underlyings_initial:
                        it2 = dict(it)
                        it2["ticker"] = inv
                        it2["direction"] = "bullish"  # trade direction for the inverse
                        it2["exposure"] = "bearish"   # portfolio exposure intent
                        it2["notes"] = f"inverse_proxy_for={tkr}"
                        _maybe_add_shares(inv, it2)

            # Hedging sanity: try to ensure we have at least one bullish AND one bearish exposure.
            # This keeps the basket "two-sided" instead of ending up all risk-on.
            if (n_bullish == 0 or n_bearish == 0) and len(proposed) < int(max_new_trades_n):
                # Prefer adding the missing side from the best remaining candidate.
                need = "bearish" if n_bearish == 0 else "bullish"
                for it in candidates:
                    if len(proposed) >= int(max_new_trades_n):
                        break
                    tkr = str(it.get("ticker") or "")
                    if not tkr:
                        continue
                    if tkr.strip().upper() in held_underlyings_initial:
                        continue
                    direction = str(it.get("direction") or "")
                    if direction != need:
                        continue
                    # Use options for hedges when possible; otherwise fall back to inverse ETFs (bearish) or shares (bullish).
                    if need == "bearish":
                        if with_options_effective and legs.get(tkr, {}).get("type") == "put":
                            if _maybe_add_option(tkr, it):
                                break
                        inv = _inverse_for(tkr)
                        if inv and inv in px.columns and inv.strip().upper() not in held_underlyings_initial:
                            it2 = dict(it)
                            it2["ticker"] = inv
                            it2["direction"] = "bullish"
                            it2["exposure"] = "bearish"
                            it2["notes"] = f"inverse_proxy_for={tkr}"
                            if _maybe_add_shares(inv, it2):
                                break
                    else:
                        # bullish
                        if with_options_effective and legs.get(tkr, {}).get("type") == "call":
                            if _maybe_add_option(tkr, it):
                                break
                        if _maybe_add_shares(tkr, it):
                            break

            # Enforce min_new_trades (best-effort):
            # - In flex mode, try to fill missing slots with more option legs first (options bias),
            #   then fall back to bullish shares if needed.
            if len(proposed) < int(min_new_trades_n):
                if budget_mode_s == "flex" and with_options_effective:
                    for it in candidates:
                        if len(proposed) >= int(min_new_trades_n) or len(proposed) >= int(max_new_trades_n):
                            break
                        tkr = str(it.get("ticker") or "")
                        if not tkr:
                            continue
                        direction = str(it.get("direction") or "")
                        if not legs.get(tkr):
                            continue
                        if direction == "bullish" and legs.get(tkr, {}).get("type") == "call":
                            _maybe_add_option(tkr, it)
                        elif direction == "bearish" and legs.get(tkr, {}).get("type") == "put":
                            _maybe_add_option(tkr, it)

                for it in candidates:
                    if len(proposed) >= int(min_new_trades_n) or len(proposed) >= int(max_new_trades_n):
                        break
                    tkr = str(it.get("ticker") or "")
                    if not tkr:
                        continue
                    if str(it.get("direction") or "") != "bullish":
                        continue
                    _maybe_add_shares(tkr, it)

            return proposed, remaining_equity, remaining_options, remaining_total

        proposed_by_plan: dict[str, tuple[list[dict], float, float, float]] = {}
        if budget_mode_s == "strict" and allocation_s == "both":
            for p in budget_plans:
                nm = str(p.get("name") or "")
                proposed_by_plan[nm] = _build_proposed_for_budgets(beq=float(p.get("budget_equity") or 0.0), bop=float(p.get("budget_options") or 0.0))
        else:
            proposed_by_plan[str(active_plan.get("name") or "auto")] = _build_proposed_for_budgets(beq=float(budget_equity), bop=float(budget_options))

        # Active plan for execution + LLM
        plan_name_active = str(active_plan.get("name") or "auto")
        proposed, remaining_equity, remaining_options, remaining_total = proposed_by_plan.get(plan_name_active, ([], 0.0, 0.0, float(max(0.0, budget_total))))

        if len(proposed) < int(min_new_trades_n):
            console.print(
                Panel(
                    f"Could only construct {len(proposed)} trade(s) with current cash=${budget_total:,.2f}.\n"
                    "Try increasing cash, lowering --min-new-trades, or disabling options (--no-options).",
                    title="Allocator warning",
                    expand=False,
                )
            )

        def _print_plan_table(plan_name: str, plan_proposed: list[dict]) -> None:
            t2 = Table(title=f"Autopilot: recommended trades — plan={plan_name}")
            t2.add_column("action", style="bold")
            t2.add_column("ticker")
            t2.add_column("score", justify="right")
            t2.add_column("expRet", justify="right")
            t2.add_column("hit/prob", justify="right")
            t2.add_column("expr")
            t2.add_column("und≈", justify="right")
            t2.add_column("move@+5%", justify="right")
            t2.add_column("profit if", justify="right")
            t2.add_column("est_cost", justify="right")
            for p in plan_proposed:
                it = p["idea"]
                if p["kind"] == "OPEN_OPTION":
                    leg = p["leg"]
                    expr = f"{leg['symbol']} (${leg['premium_usd']:.0f} Δ={leg.get('delta')})"
                    act = "BUY CALL" if leg.get("type") == "call" else "BUY PUT"
                    # Underlying price (best-effort: latest close from our price panel)
                    und_px = None
                    try:
                        tkr0 = str(p.get("ticker") or "")
                        if tkr0 in px.columns and not px[tkr0].dropna().empty:
                            und_px = float(px[tkr0].dropna().iloc[-1])
                    except Exception:
                        und_px = None
                    # Breakeven / profit threshold at expiry (best-effort)
                    profit_if = "—"
                    try:
                        from ai_options_trader.utils.occ import parse_occ_option_symbol

                        _exp, opt_type, strike = parse_occ_option_symbol(str(leg["symbol"]), str(p["ticker"]))
                        prem_per_share = float(leg.get("price") or 0.0)
                        if prem_per_share > 0:
                            if opt_type == "call":
                                be = float(strike) + prem_per_share
                                profit_if = f">{be:.2f}"
                            else:
                                be = float(strike) - prem_per_share
                                profit_if = f"<{be:.2f}"
                    except Exception:
                        profit_if = "—"
                    move5 = required_underlying_move_for_profit_pct(
                        opt_entry_price=float(leg.get("price") or 0.0),
                        delta=(float(leg.get("delta")) if leg.get("delta") is not None else None),
                        profit_pct=0.05,
                        underlying_px=und_px,
                        opt_type=str(leg.get("type") or ""),
                    )
                else:
                    expr = f"qty={p['qty']} limit≈{p['limit']:.2f}"
                    act = "BUY SHARES"
                    und_px = float(p.get("limit") or 0.0) or None
                    profit_if = "—"
                    move5 = None
                score = it.get("score")
                exp_ret = it.get("exp_return")
                if exp_ret is None:
                    exp_ret = it.get("exp_return_pred")
                hp = it.get("hit_rate")
                if hp is None:
                    hp = it.get("prob_up_pred")
                t2.add_row(
                    act,
                    p["ticker"],
                    f"{float(score):.2f}" if score is not None else "—",
                    f"{float(exp_ret):+.2f}%" if exp_ret is not None else "—",
                    f"{float(hp):.0%}" if hp is not None else "—",
                    expr,
                    "—" if und_px is None else f"${und_px:.2f}",
                    format_required_move(move5),
                    profit_if,
                    f"${float(p.get('est_cost_usd') or 0.0):.2f}",
                )
            console.print(t2)

        if budget_mode_s == "strict" and allocation_s == "both":
            for nm, (pp, _re, _ro, _rt) in proposed_by_plan.items():
                _print_plan_table(nm, pp)
        else:
            _print_plan_table(plan_name_active, proposed)

        # Explainability: make the selection legible (especially under a thesis mode).
        if bool(explain):
            try:
                feat_row_explain = X.loc[asof_ts].to_dict()
            except Exception:
                feat_row_explain = {}

            driver_keys = [
                "commod_pressure_score",
                "fiscal_pressure_score",
                "rates_z_ust_10y",
                "rates_z_curve_2s10s",
                "usd_strength_score",
                "vol_pressure_score",
                "funding_tightness_score",
                "macro_disconnect_score",
            ]
            drivers = {k: feat_row_explain.get(k) for k in driver_keys if k in feat_row_explain}

            # Event focus (best-effort): FMP econ calendar + cached Treasury auctions.
            events_all: list[dict] = []
            try:
                from ai_options_trader.overlay.context import fetch_calendar_events, fetch_treasury_auction_events

                events_all.extend(
                    fetch_calendar_events(
                        settings=settings,
                        days_ahead=int(llm_calendar_days),
                        max_items=max(60, int(llm_calendar_max_items)),
                    )
                )
                events_all.extend(fetch_treasury_auction_events(days_ahead=max(21, int(llm_calendar_days)), max_items=30))
            except Exception:
                events_all = []

            def _filter_events(evs: list[dict], keywords: list[str], *, max_items: int = 8) -> list[dict]:
                kw = [k.strip().lower() for k in (keywords or []) if k and k.strip()]
                out: list[dict] = []
                for e0 in (evs or []):
                    name = str(e0.get("event") or "").lower()
                    cat = str(e0.get("category") or "").lower()
                    if (not kw) or any(k in name or k in cat for k in kw):
                        out.append(e0)
                    if len(out) >= int(max_items):
                        break
                return out

            thesis_kw = ["cpi", "pce", "fomc", "jobs", "payroll"]
            if thesis_s == "inflation_fiscal":
                thesis_kw = [
                    "cpi",
                    "pce",
                    "ppi",
                    "inflation",
                    "fomc",
                    "fed",
                    "auction",
                    "treasury",
                    "jobs",
                    "payroll",
                    "unemployment",
                    "wage",
                ]
            events_focus = _filter_events(events_all, thesis_kw, max_items=8)

            if drivers:
                console.print(
                    Panel(
                        f"thesis={thesis_s}\n" + "\n".join([f"- {k}={drivers.get(k)}" for k in drivers.keys()]),
                        title="WHY THESE TRADES — thesis drivers (latest)",
                        expand=False,
                    )
                )
            else:
                console.print(Panel(f"thesis={thesis_s}\n- (no tracker row available)", title="WHY THESE TRADES", expand=False))

            if events_focus:
                lines = []
                for e0 in events_focus:
                    dt = str(e0.get("datetime_utc") or "")[:10]
                    lines.append(f"- {dt} — {e0.get('event')} ({e0.get('category')})")
                console.print(Panel("\n".join(lines), title="WHY THESE TRADES — upcoming focus events", expand=False))

            if proposed:
                twhy = Table(title="WHY THESE TRADES — per-trade rationale (compact)")
                twhy.add_column("ticker", style="bold")
                twhy.add_column("action")
                twhy.add_column("bucket")
                twhy.add_column("score_raw", justify="right")
                twhy.add_column("score", justify="right")
                twhy.add_column("dir")
                for p0 in proposed:
                    it0 = dict(p0.get("idea") or {})
                    tkr0 = str(p0.get("ticker") or "")
                    act0 = "OPTION" if str(p0.get("kind") or "") == "OPEN_OPTION" else "SHARES"
                    bucket = str(it0.get("thesis_tag") or "neutral")
                    sraw = it0.get("score_raw")
                    sw = it0.get("score")
                    direction = str(it0.get("direction") or "")
                    twhy.add_row(
                        tkr0,
                        act0,
                        bucket,
                        f"{float(sraw):.3f}" if isinstance(sraw, (int, float)) else "—",
                        f"{float(sw):.3f}" if isinstance(sw, (int, float)) else "—",
                        direction,
                    )
                console.print(twhy)
        console.print(
            Panel(
                (
                    f"Budget summary:\n"
                    f"- shares used=${(budget_equity - remaining_equity):.2f}  remaining=${remaining_equity:.2f}\n"
                    f"- options used=${(budget_options - remaining_options):.2f}  remaining=${remaining_options:.2f}\n"
                    f"- cash budget total=${budget_total:.2f}"
                    if budget_mode_s == "strict"
                    else f"Budget summary (flex): used=${(budget_total - remaining_total):.2f}  remaining=${remaining_total:.2f}  cash=${budget_total:.2f}"
                ),
                title="Budget check",
                expand=False,
            )
        )

        if llm:
            from ai_options_trader.llm.macro_recommendation import llm_macro_recommendation

            asof = str(asof_ts.date())
            feat_row = X.loc[asof_ts].to_dict()
            cand_payload = []
            for it in candidates[:10]:
                tkr = str(it.get("ticker") or "")
                d = dict(it)
                d["option_leg"] = legs.get(tkr)
                cand_payload.append(d)

            # What the CLI table shows: budgeted, executable recommendations.
            budgeted_payload: list[dict] = []
            for p in proposed:
                it = dict(p.get("idea") or {})
                rec = {
                    "kind": p.get("kind"),
                    "ticker": p.get("ticker"),
                    "est_cost_usd": p.get("est_cost_usd"),
                    "score": it.get("score"),
                    "direction": it.get("direction"),
                    "exp_return": it.get("exp_return") if it.get("exp_return") is not None else it.get("exp_return_pred"),
                    "prob_up": it.get("prob_up_pred") if it.get("prob_up_pred") is not None else it.get("hit_rate"),
                    "option_leg": p.get("leg"),
                    "shares_qty": p.get("qty"),
                    "shares_limit": p.get("limit"),
                }
                budgeted_payload.append(rec)

            # Risk overlay payload: reuse earlier context (trackers/events/news) and extend with proposed tickers.
            risk_watch_llm: dict = risk_watch if isinstance(risk_watch, dict) else {}
            news_llm: dict = news_payload if isinstance(news_payload, dict) else {}
            if llm_news:
                try:
                    from ai_options_trader.overlay.context import extract_underlyings, fetch_calendar_events, fetch_news_payload, merge_news_payload

                    # Ensure we have upcoming events.
                    if isinstance(risk_watch_llm, dict) and not list(risk_watch_llm.get("events") or []):
                        risk_watch_llm = dict(risk_watch_llm)
                        risk_watch_llm["events"] = fetch_calendar_events(
                            settings=settings,
                            days_ahead=int(llm_calendar_days),
                            max_items=int(llm_calendar_max_items),
                        )

                    # Ensure we have headlines for held + proposed tickers.
                    want_tickers = set()
                    want_tickers |= extract_underlyings([str(p0.get("symbol") or "") for p0 in positions])
                    want_tickers |= {str(r0.get("ticker") or "").strip().upper() for r0 in budgeted_payload if str(r0.get("ticker") or "").strip()}
                    existing = set(str(t).strip().upper() for t in (news_llm.get("tickers") or [])) if isinstance(news_llm, dict) else set()
                    missing = sorted(t for t in want_tickers if t and t not in existing)
                    if missing:
                        extra = fetch_news_payload(
                            settings=settings,
                            tickers=missing,
                            lookback_days=int(llm_news_days),
                            max_items=int(llm_news_max_items),
                        )
                        news_llm = merge_news_payload(news_llm, extra)
                except Exception as e:
                    console.print(Panel(f"[dim]LLM overlay (events/news) unavailable[/dim]: {type(e).__name__}: {e}", title="LLM overlay", expand=False))

            text = llm_macro_recommendation(
                settings=settings,
                asof=asof,
                regime_features=feat_row,
                candidates=cand_payload,
                budgeted_recommendations=budgeted_payload,
                positions=positions,
                account={
                    "equity": equity,
                    "cash": cash,
                    "buying_power": bp,
                    "budget_total": budget_total,
                    "budget_equity": budget_equity,
                    "budget_options": budget_options,
                    "budget_mode": budget_mode_s,
                    "flex_prefer": flex_prefer_s,
                    "min_new_trades": min_new_trades_n,
                    "max_new_trades": max_new_trades_n,
                },
                risk_watch=risk_watch_llm,
                news=news_llm,
                require_decision_line=bool(llm_gate),
                model=llm_model.strip() or None,
                temperature=float(llm_temperature),
            )
            console.print("\nLLM REVIEW")
            console.print(text)

            # LLM gate: if enabled, parse DECISION and refuse execution unless GO (or override).
            if llm_gate and execute and (not llm_gate_override):
                decision = None
                for line in (text or "").splitlines():
                    s = line.strip()
                    if s.upper().startswith("DECISION:"):
                        decision = s.split(":", 1)[1].strip().upper()
                        break
                if decision and decision != "GO":
                    console.print(
                        Panel(
                            f"LLM gate blocked execution.\nDECISION: {decision}\n\n"
                            "If you want to proceed anyway, re-run with `--llm-gate-override`.",
                            title="LLM gate",
                            expand=False,
                        )
                    )
                    raise typer.Exit(code=0)
        else:
            # If the user asked for gating, we must run the LLM to get a decision line.
            if llm_gate and execute and (not llm_gate_override):
                console.print(Panel("`--llm-gate` requires `--llm` so the LLM can produce DECISION.", title="LLM gate", expand=False))
                raise typer.Exit(code=2)

        # Execute proposed trades (paper-only, explicit confirm)
        if execute and (proposed or (allocation_s == "both" and proposed_by_plan)):
            label = "LIVE" if live_ok else "PAPER"
            if budget_mode_s == "strict" and allocation_s == "both":
                # Select which plan to execute
                choice = typer.prompt("Select allocation plan to execute (equity100|50_50)", default="equity100")
                choice = (choice or "equity100").strip()
                if choice not in proposed_by_plan:
                    console.print(f"[yellow]Unknown plan[/yellow] {choice!r}; defaulting to equity100")
                    choice = "equity100"
                proposed, remaining_equity, remaining_options, remaining_total = proposed_by_plan.get(choice, ([], 0.0, 0.0, remaining_total))
                plan_name_active = choice
            if not typer.confirm(f"Proceed to submit {len(proposed)} {label} trade(s) now?", default=False):
                raise typer.Exit(code=0)
            if live_ok:
                _ensure_live_confirmed()

            from ai_options_trader.execution.alpaca import submit_option_order, submit_equity_order

            for p in proposed:
                if p["kind"] == "OPEN_OPTION":
                    leg = p["leg"]
                    sym = str(leg["symbol"])
                    # Show underlying + profit threshold at expiry (breakeven) to keep decisions grounded.
                    ctx = ""
                    try:
                        from ai_options_trader.utils.occ import parse_occ_option_symbol

                        _exp, opt_type, strike = parse_occ_option_symbol(sym, str(p["ticker"]))
                        prem_per_share = float(leg.get("price") or 0.0)
                        und_px = None
                        tkr0 = str(p.get("ticker") or "")
                        if tkr0 in px.columns and not px[tkr0].dropna().empty:
                            und_px = float(px[tkr0].dropna().iloc[-1])
                        if prem_per_share > 0:
                            if opt_type == "call":
                                be = float(strike) + prem_per_share
                                thresh = f"profit if >${be:.2f}"
                            else:
                                be = float(strike) - prem_per_share
                                thresh = f"profit if <${be:.2f}"
                        else:
                            thresh = "profit if —"
                        ctx = f" (und≈{('—' if und_px is None else f'${und_px:.2f}')}; {thresh} @ expiry)"
                    except Exception:
                        ctx = ""

                    if not typer.confirm(f"Submit {label} option order: BUY 1 {sym}?{ctx}", default=False):
                        continue
                    try:
                        submit_option_order(
                            trading=trading,
                            symbol=sym,
                            qty=1,
                            side="buy",
                            limit_price=float(leg.get("price") or 0.0) or None,
                            tif="day",
                        )
                        console.print(f"[green]Submitted[/green] option: {sym}")
                    except Exception as e:
                        msg = str(e)
                        # Don't crash the whole session for one rejected trade.
                        console.print(f"[red]Option order rejected[/red] {sym}: {msg}")
                        continue
                else:
                    sym = str(p["ticker"])
                    qty = int(p["qty"])
                    limit_px = float(p["limit"])
                    if not typer.confirm(f"Submit {label} equity order: BUY {qty} {sym} MKT (last≈{limit_px:.2f})?", default=False):
                        continue
                    # Pre-flight: some symbols in our universe may not be tradable on Alpaca.
                    try:
                        asset = trading.get_asset(sym)
                        if not getattr(asset, "tradable", True):
                            console.print(f"[yellow]Skipping[/yellow] {sym}: asset not tradable on Alpaca")
                            continue
                    except Exception as e:
                        msg = str(e)
                        console.print(f"[yellow]Skipping[/yellow] {sym}: could not fetch asset metadata ({msg})")
                        continue

                    try:
                        # Market order: pass limit_price=None.
                        submit_equity_order(
                            trading=trading,
                            symbol=sym,
                            qty=qty,
                            side="buy",
                            limit_price=None,
                            tif="day",
                        )
                        console.print(f"[green]Submitted[/green] equity: {qty} {sym} (MKT)")
                    except Exception as e:
                        msg = str(e)
                        # Common Alpaca rejection: {"code":42210000,"message":"asset \"XYZ\" not found"}
                        if "asset" in msg.lower() and "not found" in msg.lower():
                            console.print(f"[yellow]Skipping[/yellow] {sym}: {msg}")
                            continue
                        console.print(f"[red]Equity order rejected[/red] {qty} {sym}: {msg}")
                        continue


