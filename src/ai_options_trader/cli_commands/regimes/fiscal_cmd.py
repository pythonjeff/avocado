from __future__ import annotations

import typer
from rich import print
from rich.panel import Panel

from ai_options_trader.config import load_settings
from ai_options_trader.fiscal.regime import classify_fiscal_regime, classify_fiscal_regime_skeleton
from ai_options_trader.fiscal.signals import build_fiscal_deficit_page_data, build_fiscal_state
from ai_options_trader.utils.formatting import fmt_usd_from_millions


# ─────────────────────────────────────────────────────────────────────────────
# Helper functions (module-level for reuse)
# ─────────────────────────────────────────────────────────────────────────────

def _band(
    x: float | None,
    *,
    low: float,
    high: float,
    low_label: str,
    mid_label: str,
    high_label: str,
    fmt: str = "{:.2f}",
    units: str = "",
) -> str:
    if not isinstance(x, (int, float)):
        return "n/a"
    v = float(x)
    label = mid_label
    if v <= low:
        label = low_label
    elif v >= high:
        label = high_label
    u = f" {units}".rstrip()
    return f"{fmt.format(v)}{u} → {label}"


def _deficit_level_ctx(deficit_pct_gdp: float | None) -> str:
    return _band(
        deficit_pct_gdp,
        low=3.0,
        high=6.0,
        low_label="Low funding pressure",
        mid_label="Moderate funding pressure",
        high_label="High funding pressure (stress watch)",
        fmt="{:.1f}",
        units="% GDP",
    )


def _deficit_impulse_ctx(impulse_pct_gdp: float | None) -> str:
    return _band(
        impulse_pct_gdp,
        low=-0.75,
        high=0.75,
        low_label="Improving (less thrust)",
        mid_label="Neutral-ish",
        high_label="Deteriorating (more thrust) → stress watch",
        fmt="{:+.2f}",
        units="% GDP",
    )


def _duration_share_ctx(long_share: float | None) -> str:
    if not isinstance(long_share, (int, float)):
        return "n/a"
    pct = 100.0 * float(long_share)
    label = "Balanced"
    if pct >= 40.0:
        label = "Long-tilted → stress watch"
    elif pct <= 25.0:
        label = "Bill/coupon-tilted (less duration risk)"
    return f"{pct:.1f}% → {label}"


def _tga_z_ctx(z: float | None) -> str:
    if not isinstance(z, (int, float)):
        return "n/a"
    v = float(z)
    if abs(v) < 0.75:
        label = "Neutral / normal"
    elif v < 0:
        label = "Liquidity easing (TGA down fast)"
    else:
        label = "Liquidity tightening (TGA up fast) → stress watch"
    return f"{v:+.2f} → {label}"


def _tga_level_ctx(z_level: float | None) -> str:
    if not isinstance(z_level, (int, float)):
        return "n/a"
    v = float(z_level)
    if v <= -0.75:
        label = "Low vs recent history"
    elif v >= 0.75:
        label = "High vs recent history"
    else:
        label = "Normal vs recent history"
    return f"{v:+.2f} → {label}"


def _auction_tail_ctx(tail_bps: float | None) -> str:
    if not isinstance(tail_bps, (int, float)):
        return "n/a"
    v = float(tail_bps)
    if v < 2.0:
        label = "Strong demand"
    elif v < 5.0:
        label = "Mixed / watch"
    else:
        label = "Weak demand → stress watch"
    return f"{v:.1f}bp → {label}"


def _dealer_take_ctx(pct: float | None) -> str:
    if not isinstance(pct, (int, float)):
        return "n/a"
    v = float(pct)
    if v < 15.0:
        label = "Strong real-money demand"
    elif v < 35.0:
        label = "Mixed / watch"
    else:
        label = "Dealers absorbing supply → stress watch"
    return f"{v:.1f}% → {label}"


# ─────────────────────────────────────────────────────────────────────────────
# Core implementation (callable directly)
# ─────────────────────────────────────────────────────────────────────────────

def _run_fiscal_snapshot(
    lookback_years: int = 5,
    refresh: bool = False,
    full: bool = False,
    llm: bool = False,
    features: bool = False,
    json_out: bool = False,
    delta: str = "",
    alert: bool = False,
    calendar: bool = False,
    trades: bool = False,
):
    """Shared implementation for fiscal snapshot."""
    from rich.console import Console
    from ai_options_trader.cli_commands.shared.labs_utils import (
        handle_output_flags, parse_delta_period, show_delta_summary,
        show_alert_output, show_calendar_output, show_trades_output,
    )
    
    console = Console()
    settings = load_settings()

    if full:
        # Full snapshot path - raw dataclass output for debugging
        state = build_fiscal_state(settings=settings, start_date="2011-01-01", refresh=refresh)
        print(state)
        regime = classify_fiscal_regime(state.inputs)
        print("\nFISCAL REGIME")
        print(regime)
        return

    # Standard Panel output
    d = build_fiscal_deficit_page_data(settings=settings, lookback_years=lookback_years, refresh=refresh)

    deficit_12m = float(d["deficit_12m"])
    # Format into $B/$T for readability
    dollars = deficit_12m * 1_000_000.0
    if abs(dollars) >= 1_000_000_000_000:
        disp = f"${dollars/1_000_000_000_000:,.2f}T"
    elif abs(dollars) >= 1_000_000_000:
        disp = f"${dollars/1_000_000_000:,.0f}B"
    else:
        disp = f"${dollars/1_000_000:,.0f}M"

    gdp = d.get("gdp") if isinstance(d.get("gdp"), dict) else None
    gdp_millions = gdp.get("gdp_millions") if gdp else None

    d30 = d.get("deficit_12m_30d_ago") if isinstance(d.get("deficit_12m_30d_ago"), dict) else None
    d1y = d.get("deficit_12m_1y_ago") if isinstance(d.get("deficit_12m_1y_ago"), dict) else None
    d30_val = fmt_usd_from_millions(d30.get("deficit_12m") if d30 else None)
    d30_asof = d30.get("asof") if d30 else None
    d1y_val = fmt_usd_from_millions(d1y.get("deficit_12m") if d1y else None)
    d1y_asof = d1y.get("asof") if d1y else None
    d_yoy = fmt_usd_from_millions(d.get("deficit_12m_delta_yoy"))
    impulse = d.get("deficit_impulse_pct_gdp")
    impulse_disp = f"{float(impulse):+.2f}%" if isinstance(impulse, (int, float)) else "n/a"
    gdp_asof = gdp.get("asof") if gdp else None
    deficit_pct_gdp = d.get("deficit_pct_gdp")
    deficit_pct_gdp_disp = f"{float(deficit_pct_gdp):.1f}%" if isinstance(deficit_pct_gdp, (int, float)) else "n/a"

    # Net issuance from MSPD
    net = d.get("net_issuance") if isinstance(d.get("net_issuance"), dict) else None
    bills = fmt_usd_from_millions(net.get("bills") if net else None)
    coupons = fmt_usd_from_millions(net.get("coupons") if net else None)
    long = fmt_usd_from_millions(net.get("long") if net else None)
    long_share = net.get("long_duration_share") if net else None
    long_share_disp = f"{100.0*float(long_share):.1f}%" if isinstance(long_share, (int, float)) else "n/a"
    net_total_m = None
    if net and all(isinstance(net.get(k), (int, float)) for k in ("bills", "coupons", "long")):
        net_total_m = float(net.get("bills")) + float(net.get("coupons")) + float(net.get("long"))  # type: ignore[arg-type]
    net_total_disp = fmt_usd_from_millions(net_total_m)

    # TGA behavior
    tga = d.get("tga") if isinstance(d.get("tga"), dict) else None
    tga_asof = tga.get("tga_asof") if tga else None
    tga_level = fmt_usd_from_millions(tga.get("tga_level") if tga else None)
    tga_z_level = tga.get("tga_z_level") if tga else None
    tga_z_level_disp = f"{float(tga_z_level):.2f}" if isinstance(tga_z_level, (int, float)) else "n/a"
    tga_d_4w = fmt_usd_from_millions(tga.get("tga_d_4w") if tga else None)
    tga_d_13w = fmt_usd_from_millions(tga.get("tga_d_13w") if tga else None)
    tga_z = tga.get("tga_z_d_4w") if tga else None
    tga_z_disp = f"{float(tga_z):.2f}" if isinstance(tga_z, (int, float)) else "n/a"

    # Auctions
    auctions = d.get("auctions") if isinstance(d.get("auctions"), dict) else None
    auction_asof = auctions.get("asof") if auctions else None
    tail_bps = auctions.get("tail_bps") if auctions else None
    dealer_take = auctions.get("dealer_take_pct") if auctions else None
    tail_disp = f"{float(tail_bps):.1f}bp" if isinstance(tail_bps, (int, float)) else "n/a"
    dealer_disp = f"{float(dealer_take):.1f}%" if isinstance(dealer_take, (int, float)) else "n/a"

    # TGA interpretation
    tga_interp = "n/a"
    if isinstance(tga_z, (int, float)) and isinstance(tga.get("tga_d_4w") if tga else None, (int, float)):
        d4 = float(tga.get("tga_d_4w"))  # type: ignore[arg-type]
        z4 = float(tga_z)
        if abs(z4) < 0.75:
            tga_interp = "Neutral / normal range (TGA changes not extreme)."
        elif d4 < 0:
            tga_interp = "Stealth liquidity injection (TGA down sharply)."
        else:
            tga_interp = "Stealth tightening / liquidity drain (TGA up sharply)."

    regime = classify_fiscal_regime_skeleton(
        deficit_12m=deficit_12m,
        gdp_millions=float(gdp_millions) if isinstance(gdp_millions, (int, float)) else None,
        deficit_impulse_pct_gdp=float(d["deficit_impulse_pct_gdp"])
        if isinstance(d.get("deficit_impulse_pct_gdp"), (int, float))
        else None,
        long_duration_issuance_share=float(net.get("long_duration_share"))
        if net and isinstance(net.get("long_duration_share"), (int, float))
        else None,
        tga_z_d_4w=float(tga.get("tga_z_d_4w")) if tga and isinstance(tga.get("tga_z_d_4w"), (int, float)) else None,
        auction_tail_bps=float(tail_bps) if isinstance(tail_bps, (int, float)) else None,
        dealer_take_pct=float(dealer_take) if isinstance(dealer_take, (int, float)) else None,
    )

    series_used = d.get("series_used") if isinstance(d.get("series_used"), dict) else {}
    fred_series = series_used.get("fred") if isinstance(series_used.get("fred"), list) else []
    fiscaldata_series = series_used.get("fiscaldata") if isinstance(series_used.get("fiscaldata"), list) else []
    fred_disp = ", ".join(str(x) for x in fred_series) if fred_series else "n/a"
    fiscaldata_disp = ", ".join(str(x) for x in fiscaldata_series) if fiscaldata_series else "n/a"

    # Build snapshot and features for output flags
    snapshot_data = {
        "deficit_12m": d.get("deficit_12m"),
        "deficit_pct_gdp": deficit_pct_gdp,
        "deficit_impulse_pct_gdp": impulse,
        "net_issuance_bills": net.get("bills") if net else None,
        "net_issuance_coupons": net.get("coupons") if net else None,
        "net_issuance_long": net.get("long") if net else None,
        "long_duration_share": long_share,
        "tga_level": tga.get("tga_level") if tga else None,
        "tga_z_d_4w": tga_z,
        "auction_tail_bps": tail_bps,
        "dealer_take_pct": dealer_take,
        "regime": regime.label or regime.name,
    }

    feature_dict = {
        "deficit_12m_millions": d.get("deficit_12m"),
        "deficit_pct_gdp": deficit_pct_gdp,
        "deficit_impulse_pct_gdp": impulse,
        "long_duration_share": long_share,
        "tga_z_d_4w": tga_z,
        "auction_tail_bps": tail_bps,
        "dealer_take_pct": dealer_take,
    }

    # Handle --features and --json flags
    if handle_output_flags(
        domain="fiscal",
        snapshot=snapshot_data,
        features=feature_dict,
        regime=regime.label or regime.name,
        regime_description=regime.description,
        asof=d.get("asof"),
        output_json=json_out,
        output_features=features,
    ):
        return

    # Handle --alert flag (silent unless extreme)
    if alert:
        show_alert_output("fiscal", regime.label or regime.name, snapshot_data, regime.description)
        return

    # Handle --calendar flag
    if calendar:
        print(Panel.fit(f"[b]Regime:[/b] {regime.label or regime.name}", title="US Fiscal", border_style="cyan"))
        show_calendar_output("fiscal")
        return

    # Handle --trades flag
    if trades:
        print(Panel.fit(f"[b]Regime:[/b] {regime.label or regime.name}", title="US Fiscal", border_style="cyan"))
        show_trades_output("fiscal", regime.label or regime.name)
        return

    # Handle --delta flag
    if delta:
        from ai_options_trader.cli_commands.shared.labs_utils import get_delta_metrics
        
        delta_days = parse_delta_period(delta)
        
        # Define metrics to track: "Display Name:snapshot_key:unit"
        metric_keys = [
            "Deficit % GDP:deficit_pct_gdp:%",
            "Deficit Impulse:deficit_impulse_pct_gdp:%",
            "Long Duration Share:long_duration_share:",
            "TGA z(Δ4w):tga_z_d_4w:",
            "Auction Tail:auction_tail_bps:bp",
            "Dealer Take:dealer_take_pct:%",
        ]
        
        metrics_for_delta, prev_regime = get_delta_metrics("fiscal", snapshot_data, metric_keys, delta_days)
        show_delta_summary("fiscal", regime.label or regime.name, prev_regime, metrics_for_delta, delta_days)
        
        if prev_regime is None:
            console.print(f"\n[dim]No cached data from {delta_days}d ago. Run `lox labs fiscal` daily to build history.[/dim]")
        return

    body = "\n".join(
        [
            f"As of: [bold]{d['asof']}[/bold]",
            f"Rolling 12m deficit: [bold]{disp}[/bold]  (positive = larger deficit)",
            f"Rolling 12m deficit ~30d ago: [bold]{d30_val}[/bold]  (as of {d30_asof or 'n/a'})",
            f"Rolling 12m deficit 1y ago: [bold]{d1y_val}[/bold]  (as of {d1y_asof or 'n/a'})",
            f"Δ rolling 12m deficit (YoY): [bold]{d_yoy}[/bold]",
            f"Deficit level (% GDP): [bold]{deficit_pct_gdp_disp}[/bold]  [dim]({_deficit_level_ctx(float(deficit_pct_gdp)) if isinstance(deficit_pct_gdp, (int, float)) else 'n/a'})[/dim]",
            f"Deficit impulse (% GDP): [bold]{impulse_disp}[/bold]  (GDP as of {gdp_asof or 'n/a'})",
            f"[dim]Context: {_deficit_impulse_ctx(float(impulse)) if isinstance(impulse, (int, float)) else 'n/a'}[/dim]",
            "Net issuance (true, Δ outstanding; MSPD):",
            f"  Bills: [bold]{bills}[/bold]",
            f"  Coupons: [bold]{coupons}[/bold]",
            f"  Long: [bold]{long}[/bold]",
            f"  Long-duration share: [bold]{long_share_disp}[/bold]",
            f"  [dim]Context: {_duration_share_ctx(float(long_share)) if isinstance(long_share, (int, float)) else 'n/a'} | Total net: {net_total_disp}[/dim]",
            "TGA behavior (WTREGEN):",
            f"  Level: [bold]{tga_level}[/bold]  (as of {tga_asof or 'n/a'})  [dim](z-level={tga_z_level_disp}; {_tga_level_ctx(float(tga_z_level)) if isinstance(tga_z_level, (int, float)) else 'n/a'})[/dim]",
            f"  Δ 4-week: [bold]{tga_d_4w}[/bold]",
            f"  Δ 13-week: [bold]{tga_d_13w}[/bold]",
            f"  Z(Δ 4-week): [bold]{tga_z_disp}[/bold]",
            f"  Interpretation: [bold]{tga_interp}[/bold]  [dim]({_tga_z_ctx(float(tga_z)) if isinstance(tga_z, (int, float)) else 'n/a'})[/dim]",
            "Auction absorption (Treasury auctions):",
            f"  Tail (proxy): [bold]{tail_disp}[/bold]  (as of {auction_asof or 'n/a'})  [dim]({_auction_tail_ctx(float(tail_bps)) if isinstance(tail_bps, (int, float)) else 'n/a'})[/dim]",
            f"  Dealer take: [bold]{dealer_disp}[/bold]  [dim]({_dealer_take_ctx(float(dealer_take)) if isinstance(dealer_take, (int, float)) else 'n/a'})[/dim]",
            f"Regime: [bold]{regime.label or regime.name}[/bold]",
            f"Answer: {regime.description}",
            f"History loaded: {d.get('lookback_years', lookback_years)}y",
            f"Series (FRED): [dim]{fred_disp}[/dim]",
            f"Series (FiscalData): [dim]{fiscaldata_disp}[/dim]",
        ]
    )
    print(Panel.fit(body, title="US Fiscal", border_style="cyan"))

    if llm:
        from ai_options_trader.llm.core.analyst import llm_analyze_regime
        from rich.markdown import Markdown

        print("\n[bold cyan]Generating LLM analysis...[/bold cyan]\n")

        snapshot_data = {
            "deficit_12m": d.get("deficit_12m"),
            "deficit_pct_gdp": deficit_pct_gdp,
            "deficit_impulse_pct_gdp": impulse,
            "net_issuance_bills": net.get("bills") if net else None,
            "net_issuance_coupons": net.get("coupons") if net else None,
            "net_issuance_long": net.get("long") if net else None,
            "long_duration_share": long_share,
            "tga_level": tga.get("tga_level") if tga else None,
            "tga_z_d_4w": tga_z,
            "tga_d_4w": tga.get("tga_d_4w") if tga else None,
            "auction_tail_bps": tail_bps,
            "dealer_take_pct": dealer_take,
        }

        analysis = llm_analyze_regime(
            settings=settings,
            domain="fiscal",
            snapshot=snapshot_data,
            regime_label=regime.label or regime.name,
            regime_description=regime.description,
        )

        print(Panel(Markdown(analysis), title="Analysis", expand=False))


# ─────────────────────────────────────────────────────────────────────────────
# CLI Registration
# ─────────────────────────────────────────────────────────────────────────────

def register(fiscal_app: typer.Typer) -> None:
    @fiscal_app.callback(invoke_without_command=True)
    def fiscal_default(
        ctx: typer.Context,
        llm: bool = typer.Option(False, "--llm", help="Get PhD-level LLM analysis with real-time data"),
        features: bool = typer.Option(False, "--features", help="Export ML-ready feature vector (JSON)"),
        json_out: bool = typer.Option(False, "--json", help="Machine-readable JSON output"),
        delta: str = typer.Option("", "--delta", help="Show changes vs N days ago (e.g., 7d, 1w, 1m)"),
        alert: bool = typer.Option(False, "--alert", help="Only output if regime is extreme (for cron/monitoring)"),
        calendar: bool = typer.Option(False, "--calendar", help="Show upcoming events that could shift this regime"),
        trades: bool = typer.Option(False, "--trades", help="Show quick trade expressions for current regime"),
    ):
        """US fiscal regime (deficits, issuance mix, auctions, TGA)"""
        if ctx.invoked_subcommand is None:
            _run_fiscal_snapshot(llm=llm, features=features, json_out=json_out, delta=delta, alert=alert, calendar=calendar, trades=trades)

    @fiscal_app.command("snapshot")
    def fiscal_snapshot(
        lookback_years: int = typer.Option(
            5,
            "--lookback-years",
            help="How many years of history to load (enough for rolling 12m deficit).",
        ),
        refresh: bool = typer.Option(False, "--refresh", help="Force refresh FRED downloads"),
        full: bool = typer.Option(
            False,
            "--full",
            help="Print the full fiscal state (TGA/interest placeholders) and the richer regime classifier.",
        ),
        llm: bool = typer.Option(False, "--llm", help="Get PhD-level LLM analysis with real-time data"),
        features: bool = typer.Option(False, "--features", help="Export ML-ready feature vector (JSON)"),
        json_out: bool = typer.Option(False, "--json", help="Machine-readable JSON output"),
        delta: str = typer.Option("", "--delta", help="Show changes vs N days ago (e.g., 7d, 1w, 1m)"),
        alert: bool = typer.Option(False, "--alert", help="Only output if regime is extreme (for cron/monitoring)"),
        calendar: bool = typer.Option(False, "--calendar", help="Show upcoming events that could shift this regime"),
        trades: bool = typer.Option(False, "--trades", help="Show quick trade expressions for current regime"),
    ):
        """
        Print fiscal regime snapshot.

        Default behavior is intentionally simple and uniform with other regimes:
        it prints the rolling 12m deficit plus a skeleton regime label.
        Use --full for the richer snapshot + classifier.
        """
        _run_fiscal_snapshot(lookback_years=lookback_years, refresh=refresh, full=full, llm=llm, features=features, json_out=json_out, delta=delta, alert=alert, calendar=calendar, trades=trades)

    @fiscal_app.command("outlook")
    def fiscal_outlook(
        lookback_years: int = typer.Option(5, "--lookback-years", help="How many years of history to load."),
        refresh: bool = typer.Option(False, "--refresh", help="Force refresh downloads"),
        llm_model: str = typer.Option("", "--llm-model", help="Override OPENAI_MODEL (optional)"),
        llm_temperature: float = typer.Option(0.2, "--llm-temperature", help="LLM temperature (0..2)"),
    ):
        """
        Ask an LLM to summarize the current fiscal snapshot and implications for trading.
        Grounded in the same quantitative snapshot used by `fiscal snapshot`.
        """
        settings = load_settings()
        d = build_fiscal_deficit_page_data(settings=settings, lookback_years=lookback_years, refresh=refresh)

        gdp = d.get("gdp") if isinstance(d.get("gdp"), dict) else None
        gdp_millions = gdp.get("gdp_millions") if gdp else None
        net = d.get("net_issuance") if isinstance(d.get("net_issuance"), dict) else None
        tga = d.get("tga") if isinstance(d.get("tga"), dict) else None
        auctions = d.get("auctions") if isinstance(d.get("auctions"), dict) else None

        deficit_12m = float(d["deficit_12m"]) if isinstance(d.get("deficit_12m"), (int, float)) else None
        regime = classify_fiscal_regime_skeleton(
            deficit_12m=deficit_12m,
            gdp_millions=float(gdp_millions) if isinstance(gdp_millions, (int, float)) else None,
            deficit_impulse_pct_gdp=float(d["deficit_impulse_pct_gdp"])
            if isinstance(d.get("deficit_impulse_pct_gdp"), (int, float))
            else None,
            long_duration_issuance_share=float(net.get("long_duration_share"))
            if net and isinstance(net.get("long_duration_share"), (int, float))
            else None,
            tga_z_d_4w=float(tga.get("tga_z_d_4w")) if tga and isinstance(tga.get("tga_z_d_4w"), (int, float)) else None,
            auction_tail_bps=float(auctions.get("tail_bps"))
            if auctions and isinstance(auctions.get("tail_bps"), (int, float))
            else None,
            dealer_take_pct=float(auctions.get("dealer_take_pct"))
            if auctions and isinstance(auctions.get("dealer_take_pct"), (int, float))
            else None,
        )

        from ai_options_trader.llm.outlooks.fiscal_outlook import llm_fiscal_outlook

        text = llm_fiscal_outlook(
            settings=settings,
            fiscal_snapshot=d,
            fiscal_regime=regime,
            model=llm_model.strip() or None,
            temperature=float(llm_temperature),
        )
        print(text)
