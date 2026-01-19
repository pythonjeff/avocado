"""Display helpers for autopilot output."""
from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ai_options_trader.autopilot.utils import to_float, extract_underlying


def display_positions_table(
    console: Console,
    positions: list[dict],
    stop_candidates: list[dict],
    und_px_map: dict[str, float] | None = None,
) -> None:
    """Display positions table with moneyness for options."""
    tbl = Table(title="Lox Fund: open positions")
    tbl.add_column("symbol", style="bold")
    tbl.add_column("und vs K", justify="right")
    tbl.add_column("qty", justify="right")
    tbl.add_column("avg_entry", justify="right")
    tbl.add_column("current", justify="right")
    tbl.add_column("uPL", justify="right")
    tbl.add_column("uPL%", justify="right")

    und_px_map = und_px_map or {}

    for p in positions:
        uplpc = p.get("unrealized_plpc")
        style = "red" if p in stop_candidates else ""
        
        # Calculate moneyness for options
        und_vs_k = _calc_moneyness(p, und_px_map)
        
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


def _calc_moneyness(position: dict, und_px_map: dict[str, float]) -> str:
    """Calculate und vs strike for option positions."""
    try:
        sym = str(position.get("symbol") or "").strip().upper()
        und = extract_underlying(sym) or ""
        
        # Check if it's an option (has digits after letters)
        if not (und and sym != und and any(ch.isdigit() for ch in sym)):
            return "—"
        
        from ai_options_trader.utils.occ import parse_occ_option_symbol
        _exp, opt_type, strike = parse_occ_option_symbol(sym, und)
        
        und_px = und_px_map.get(und)
        if und_px is None or strike is None or float(strike) <= 0:
            return "—"
        
        k = float(strike)
        if str(opt_type) == "put":
            diff = k - float(und_px)
            itm = float(und_px) < k
        else:
            diff = float(und_px) - k
            itm = float(und_px) > k
        
        pct = (diff / k) * 100.0
        m = "ITM" if itm else "OTM"
        return f"${float(und_px):.2f} vs ${k:.2f} ({pct:+.0f}% {m})"
    except Exception:
        return "—"


def display_status_panel(
    console: Console,
    *,
    equity: float,
    cash: float,
    buying_power: float,
    stop_count: int,
    stop_loss_pct: float,
    budget_total: float,
    budget_mode: str,
    budget_plans: list[dict],
    min_trades: int,
    max_trades: int,
) -> None:
    """Display autopilot status panel."""
    lines = [
        f"Account: equity=${equity:,.2f} cash=${cash:,.2f} buying_power=${buying_power:,.2f}",
        f"Stop candidates (<= -{stop_loss_pct*100:.0f}%): {stop_count}",
        f"Trade budget (cash): ${budget_total:,.2f}",
    ]
    
    if budget_mode == "flex":
        lines.append(budget_plans[0]["note"])
    elif len(budget_plans) == 1:
        p = budget_plans[0]
        lines.append(
            f"{p['note']} (shares≈${float(p['budget_equity']):,.2f} "
            f"options≈${float(p['budget_options']):,.2f})"
        )
    else:
        for p in budget_plans:
            lines.append(
                f"- {p['name']}: {p['note']} "
                f"(shares≈${float(p['budget_equity']):,.2f} "
                f"options≈${float(p['budget_options']):,.2f})"
            )
    
    lines.append(f"Target new trades: {min_trades}..{max_trades}")
    console.print(Panel("\n".join(lines), title="Autopilot status", expand=False))


def display_proposals_table(
    console: Console,
    proposals: list[dict],
    plan_name: str,
    px=None,  # DataFrame for underlying prices
) -> None:
    """Display proposed trades table."""
    from ai_options_trader.options.targets import (
        required_underlying_move_for_profit_pct,
        format_required_move,
    )
    
    tbl = Table(title=f"Autopilot: recommended trades — plan={plan_name}")
    tbl.add_column("action", style="bold")
    tbl.add_column("ticker")
    tbl.add_column("score", justify="right")
    tbl.add_column("expRet", justify="right")
    tbl.add_column("hit/prob", justify="right")
    tbl.add_column("expr")
    tbl.add_column("und≈", justify="right")
    tbl.add_column("move@+5%", justify="right")
    tbl.add_column("profit if", justify="right")
    tbl.add_column("est_cost", justify="right")
    
    for p in proposals:
        it = p.get("idea", {})
        
        if p["kind"] == "OPEN_OPTION":
            leg = p.get("leg", {})
            expr = f"{leg.get('symbol', '?')} (${leg.get('premium_usd', 0):.0f} Δ={leg.get('delta')})"
            act = "BUY CALL" if leg.get("type") == "call" else "BUY PUT"
            
            # Get underlying price
            und_px = _get_underlying_price(p.get("ticker"), px)
            profit_if = _calc_profit_threshold(leg, p.get("ticker"))
            move5 = required_underlying_move_for_profit_pct(
                opt_entry_price=float(leg.get("price") or 0),
                delta=float(leg.get("delta")) if leg.get("delta") else None,
                profit_pct=0.05,
                underlying_px=und_px,
                opt_type=str(leg.get("type") or ""),
            )
        else:
            expr = f"qty={p.get('qty')} limit≈{p.get('limit', 0):.2f}"
            act = "BUY SHARES"
            und_px = float(p.get("limit") or 0) or None
            profit_if = "—"
            move5 = None
        
        score = it.get("score")
        exp_ret = it.get("exp_return") or it.get("exp_return_pred")
        hp = it.get("hit_rate") or it.get("prob_up_pred")
        
        tbl.add_row(
            act,
            p.get("ticker", ""),
            f"{float(score):.2f}" if score is not None else "—",
            f"{float(exp_ret):+.2f}%" if exp_ret is not None else "—",
            f"{float(hp):.0%}" if hp is not None else "—",
            expr,
            "—" if und_px is None else f"${und_px:.2f}",
            format_required_move(move5),
            profit_if,
            f"${float(p.get('est_cost_usd') or 0):.2f}",
        )
    
    console.print(tbl)


def _get_underlying_price(ticker: str, px) -> float | None:
    """Get underlying price from DataFrame."""
    if px is None or not ticker:
        return None
    try:
        if ticker in px.columns and not px[ticker].dropna().empty:
            return float(px[ticker].dropna().iloc[-1])
    except Exception:
        pass
    return None


def _calc_profit_threshold(leg: dict, ticker: str) -> str:
    """Calculate profit threshold for option at expiry."""
    try:
        from ai_options_trader.utils.occ import parse_occ_option_symbol
        
        symbol = leg.get("symbol", "")
        if not symbol or not ticker:
            return "—"
        
        _exp, opt_type, strike = parse_occ_option_symbol(symbol, ticker)
        prem_per_share = float(leg.get("price") or 0)
        
        if prem_per_share <= 0:
            return "—"
        
        if opt_type == "call":
            be = float(strike) + prem_per_share
            return f">{be:.2f}"
        else:
            be = float(strike) - prem_per_share
            return f"<{be:.2f}"
    except Exception:
        return "—"


def display_budget_summary(
    console: Console,
    budget_mode: str,
    budget_equity: float,
    budget_options: float,
    budget_total: float,
    remaining_equity: float,
    remaining_options: float,
    remaining_total: float,
) -> None:
    """Display budget summary panel."""
    if budget_mode == "strict":
        msg = (
            f"Budget summary:\n"
            f"- shares used=${budget_equity - remaining_equity:.2f}  "
            f"remaining=${remaining_equity:.2f}\n"
            f"- options used=${budget_options - remaining_options:.2f}  "
            f"remaining=${remaining_options:.2f}\n"
            f"- cash budget total=${budget_total:.2f}"
        )
    else:
        msg = (
            f"Budget summary (flex): used=${budget_total - remaining_total:.2f}  "
            f"remaining=${remaining_total:.2f}  cash=${budget_total:.2f}"
        )
    
    console.print(Panel(msg, title="Budget check", expand=False))
