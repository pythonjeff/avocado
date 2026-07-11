"""CLI command for the broad-market bubble regime."""
from __future__ import annotations

from rich import print
from rich.table import Table
from rich.text import Text

from lox.bubble.history import (
    HISTORICAL_BUBBLES,
    compute_similarity,
    format_recover_months,
)
from lox.cli_commands.shared.regime_display import render_regime_panel
from lox.config import load_settings


def _fmt_pct(x: float | None, signed: bool = True) -> str:
    if x is None:
        return "n/a"
    return (f"{x:+.1f}%" if signed else f"{x:.1f}%")


# ── Context helpers ──────────────────────────────────────────────────────
def _val_ctx(p: float | None) -> str:
    if p is None:
        return "Buffett indicator percentile"
    if p >= 95:
        return "extreme — top 5% all-time"
    if p >= 85:
        return "very stretched"
    if p >= 70:
        return "elevated vs history"
    if p >= 40:
        return "near long-run average"
    return "cheap vs history"


def _top10_ctx(s: float | None) -> str:
    if s is None:
        return "top-10 weight share of SPY"
    if s >= 40:
        return "blow-off — index basically is 10 stocks"
    if s >= 35:
        return "extreme concentration"
    if s >= 30:
        return "narrow leadership"
    if s >= 24:
        return "elevated vs historical norm"
    return "broad — normal range"


def _conc_ctx(spread: float | None) -> str:
    if spread is None:
        return "SPY minus RSP YTD"
    if spread > 15:
        return "extreme cap-weight crowding"
    if spread > 8:
        return "narrow leadership — mega-caps doing the work"
    if spread > 3:
        return "modest cap-weight tilt"
    if spread > -3:
        return "broad participation"
    return "equal-weight winning — leadership rotating"


def _ai_ctx(excess: float | None, flag: bool) -> str:
    if excess is None:
        return "AI basket vs SPY YTD"
    if flag and excess > 35:
        return "AI is the bubble — basket smoking SPY"
    if flag:
        return "AI leadership — concentration tag fires"
    if excess > 0:
        return "AI modestly leading"
    return "AI not the leader"


def _margin_lvl_ctx(p: float | None) -> str:
    if p is None:
        return "margin debt level vs history"
    if p >= 90:
        return "near record borrowing"
    if p >= 70:
        return "elevated borrowing"
    if p >= 40:
        return "normal range"
    return "deleveraged"


def _margin_yoy_ctx(yoy: float | None) -> str:
    if yoy is None:
        return "margin debt YoY"
    if yoy > 30:
        return "explosive — classic late-cycle froth"
    if yoy > 15:
        return "rapid build-up"
    if yoy > 0:
        return "modest growth"
    if yoy > -10:
        return "flat — momentum faded"
    return "deleveraging — risk-off"


def _levered_aum_ctx(a: float | None) -> str:
    if a is None:
        return "TQQQ+SOXL+UPRO+FAS AUM"
    if a >= 60:
        return "blow-off levered-long AUM"
    if a >= 40:
        return "very elevated — late-cycle"
    if a >= 25:
        return "elevated speculation"
    if a >= 15:
        return "moderate"
    return "subdued speculation"


def _long_short_ctx(r: float | None) -> str:
    if r is None:
        return "long-to-short levered AUM ratio"
    if r >= 6:
        return "euphoric — shorts capitulated"
    if r >= 4:
        return "heavily skewed bullish"
    if r >= 2.5:
        return "moderately bullish skew"
    if r >= 1.5:
        return "balanced"
    return "skewed bearish — panic"


def _pcr_ctx(p: float | None) -> str:
    """SPY/index PCR — baseline ~1.5-2.0 from institutional hedging.
    Speculation shows up when PCR falls BELOW that baseline."""
    if p is None:
        return "put/call ratio"
    if p < 1.2:
        return "euphoric — retail calls overwhelming hedge book"
    if p < 1.5:
        return "frothy call buying"
    if p < 1.8:
        return "calls picking up vs hedging baseline"
    if p < 2.5:
        return "normal institutional hedging baseline"
    return "elevated hedging — fear premium in puts"


def _aaii_ctx(b: float | None) -> str:
    if b is None:
        return "AAII bullish %"
    if b >= 55:
        return "extreme bull — contrarian short"
    if b >= 45:
        return "elevated bullishness"
    if b >= 35:
        return "near historical avg (~38%)"
    if b >= 25:
        return "bearish lean"
    return "extreme bear — contrarian long"


def _gap_ctx(g: float | None) -> str:
    if g is None:
        return "VIX − 20d realized vol"
    if g <= -6:
        return "deeply complacent — vol mispriced"
    if g <= -3:
        return "complacent"
    if g <= 0:
        return "barely above realized"
    if g <= 5:
        return "normal premium"
    return "vol stressed — fear premium"


def bubble_snapshot(*, llm: bool = False, ticker: str = "", refresh: bool = False) -> None:
    """Entry point for `lox regime bubble`."""
    settings = load_settings()

    from lox.bubble.regime import classify_bubble
    from lox.bubble.signals import compute_bubble_signals

    sig = compute_bubble_signals(settings=settings, refresh=refresh)
    val = sig.valuation
    con = sig.concentration
    mar = sig.margin
    spec = sig.speculation
    sent = sig.sentiment

    result = classify_bubble(
        valuation_pct_full=val.percentile_full,
        top10_share_pct=con.top10_share_pct,
        spy_minus_rsp_ytd=con.spy_minus_rsp_ytd,
        spy_minus_rsp_1y=con.spy_minus_rsp_1y,
        ai_leadership_flag=con.ai_leadership_flag,
        ai_breadth_200d=con.ai_breadth_200d,
        margin_pct_full=mar.percentile_full,
        margin_yoy_pct=mar.yoy_pct,
        margin_rolling_over=mar.rolling_over,
        levered_long_aum_bn=spec.levered_long_aum_bn,
        long_to_short_ratio=spec.long_to_short_ratio,
        put_call_ratio=spec.put_call_ratio,
        aaii_bull_pct=sent.aaii_bull_pct,
        vix_minus_realized=sent.vix_minus_realized,
        complacency_flag=sent.complacency_flag,
    )

    top10_str = ", ".join(con.top10_names[:5]) if con.top10_names else ""

    metrics = [
        # ── Valuation ────────────────────────────────────────────────────
        {"name": "Buffett indicator",
         "value": f"{val.ratio_pct:.0f}%" if val.ratio_pct is not None else "n/a",
         "context": "corp equities mkt-cap / GDP"},
        {"name": "Valuation percentile",
         "value": f"{val.percentile_full:.0f}th" if val.percentile_full is not None else "n/a",
         "context": _val_ctx(val.percentile_full)},

        # ── Concentration ────────────────────────────────────────────────
        {"name": "Top-10 SPY share",
         "value": f"{con.top10_share_pct:.1f}%" if con.top10_share_pct is not None else "n/a",
         "context": _top10_ctx(con.top10_share_pct)},
        {"name": "Top-10 names",
         "value": top10_str or "n/a",
         "context": "from FMP SPY holdings"},
        {"name": "SPY YTD",
         "value": _fmt_pct(con.spy_ytd),
         "context": "cap-weighted S&P 500"},
        {"name": "RSP YTD",
         "value": _fmt_pct(con.rsp_ytd),
         "context": "equal-weighted S&P 500"},
        {"name": "SPY − RSP (YTD)",
         "value": (f"{con.spy_minus_rsp_ytd:+.1f}pp"
                   if con.spy_minus_rsp_ytd is not None else "n/a"),
         "context": _conc_ctx(con.spy_minus_rsp_ytd)},
        {"name": "AI basket vs SPY",
         "value": (f"{con.ai_basket_ytd_excess:+.1f}pp"
                   if con.ai_basket_ytd_excess is not None else "n/a"),
         "context": _ai_ctx(con.ai_basket_ytd_excess, con.ai_leadership_flag)},

        # ── Leverage / margin debt ───────────────────────────────────────
        {"name": "Margin debt",
         "value": f"${mar.level_bn:.0f}B" if mar.level_bn is not None else "n/a",
         "context": f"FRED {mar.series_id} (nominal)"},
        {"name": "Margin debt / GDP",
         "value": f"{mar.pct_of_gdp:.2f}%" if mar.pct_of_gdp is not None else "n/a",
         "context": "inflation-adjusted via GDP normalization"},
        {"name": "Margin debt percentile",
         "value": f"{mar.percentile_full:.0f}th" if mar.percentile_full is not None else "n/a",
         "context": _margin_lvl_ctx(mar.percentile_full)},
        {"name": "Margin debt YoY",
         "value": _fmt_pct(mar.yoy_pct),
         "context": _margin_yoy_ctx(mar.yoy_pct)},
        {"name": "Margin rolling over?",
         "value": "yes" if mar.rolling_over else "no",
         "context": "high level fading from peak = late-cycle"},

        # ── Speculation ──────────────────────────────────────────────────
        {"name": "Levered long AUM",
         "value": (f"${spec.levered_long_aum_bn:.1f}B"
                   if spec.levered_long_aum_bn is not None else "n/a"),
         "context": _levered_aum_ctx(spec.levered_long_aum_bn)},
        {"name": "Levered short AUM",
         "value": (f"${spec.levered_short_aum_bn:.1f}B"
                   if spec.levered_short_aum_bn is not None else "n/a"),
         "context": "TQQQ-class inverses"},
        {"name": "Long/Short ratio",
         "value": (f"{spec.long_to_short_ratio:.1f}x"
                   if spec.long_to_short_ratio is not None else "n/a"),
         "context": _long_short_ctx(spec.long_to_short_ratio)},
        {"name": "Put/Call (SPY)",
         "value": (f"{spec.put_call_ratio:.2f}"
                   if spec.put_call_ratio is not None else "n/a"),
         "context": _pcr_ctx(spec.put_call_ratio)},

        # ── Sentiment ────────────────────────────────────────────────────
        {"name": "AAII bull %",
         "value": _fmt_pct(sent.aaii_bull_pct, signed=False),
         "context": _aaii_ctx(sent.aaii_bull_pct)},
        {"name": "VIX",
         "value": f"{sent.vix:.1f}" if sent.vix is not None else "n/a",
         "context": "1m implied vol"},
        {"name": "SPY realized vol (20d)",
         "value": _fmt_pct(sent.spy_realized_vol_20d, signed=False),
         "context": "annualized realized"},
        {"name": "VIX − realized",
         "value": (f"{sent.vix_minus_realized:+.1f}pp"
                   if sent.vix_minus_realized is not None else "n/a"),
         "context": _gap_ctx(sent.vix_minus_realized)},
    ]

    sub_scores = [
        {"name": "Valuation",     "score": _safe_sub(result.metrics.get("Valuation sub")),     "weight": 0.15},
        {"name": "Concentration", "score": _safe_sub(result.metrics.get("Concentration sub")), "weight": 0.15},
        {"name": "Leverage",      "score": _safe_sub(result.metrics.get("Leverage sub")),      "weight": 0.25},
        {"name": "Speculation",   "score": _safe_sub(result.metrics.get("Speculation sub")),   "weight": 0.25},
        {"name": "Sentiment",     "score": _safe_sub(result.metrics.get("Sentiment sub")),     "weight": 0.20},
    ]

    from lox.regimes.trend import get_domain_trend
    trend = get_domain_trend("bubble", result.score, result.label)

    print(render_regime_panel(
        domain="Bubble",
        asof=sig.asof,
        regime_label=result.label,
        score=result.score,
        description=result.description,
        metrics=metrics,
        sub_scores=sub_scores,
        trend=trend,
    ))

    # ── Tag callouts ─────────────────────────────────────────────────────
    interesting = [t for t in result.tags
                   if t in {"valuation_stretched", "concentration_extreme",
                            "leverage_extreme", "speculation_hot",
                            "sentiment_euphoric", "ai_concentration",
                            "margin_rollover", "complacency",
                            "blowoff", "cracks"}]
    if interesting:
        print(Text(""))
        print(Text.from_markup(
            "[bold]Active flags[/bold]: "
            + ", ".join(f"[yellow]{t}[/yellow]" for t in interesting)
        ))

    # ── Historical comparison ────────────────────────────────────────────
    _print_historical_table(
        buffett_pct=val.ratio_pct,
        top10_share_pct=con.top10_share_pct,
        margin_to_gdp_pct=mar.pct_of_gdp,
    )

    if llm:
        from lox.cli_commands.shared.regime_display import print_llm_regime_analysis
        print_llm_regime_analysis(
            settings=settings,
            domain="bubble",
            snapshot={
                "valuation_pct": val.percentile_full,
                "buffett_ratio": val.ratio_pct,
                "top10_share": con.top10_share_pct,
                "spy_minus_rsp_ytd": con.spy_minus_rsp_ytd,
                "ai_excess_ytd": con.ai_basket_ytd_excess,
                "margin_pct": mar.percentile_full,
                "margin_yoy": mar.yoy_pct,
                "margin_rolling_over": mar.rolling_over,
                "levered_long_aum": spec.levered_long_aum_bn,
                "long_short_ratio": spec.long_to_short_ratio,
                "pcr": spec.put_call_ratio,
                "aaii_bull": sent.aaii_bull_pct,
                "vix_minus_realized": sent.vix_minus_realized,
            },
            regime_label=result.label,
            regime_description=result.description,
            ticker=ticker,
        )


def _safe_sub(v) -> float | None:
    if v is None:
        return None
    try:
        return float(str(v).rstrip("%"))
    except ValueError:
        return None


def _fmt_or_na(v: float | None, suffix: str = "", fmt: str = "{:.0f}") -> str:
    return (fmt.format(v) + suffix) if v is not None else "—"


def _hot_color(today: float | None, hist: float | None) -> str:
    """Return rich style: red if today exceeds the historical peak, yellow if within 10%."""
    if today is None or hist is None:
        return ""
    if today >= hist:
        return "bold red"
    if today >= hist * 0.9:
        return "yellow"
    return ""


def _print_historical_table(
    *,
    buffett_pct: float | None,
    top10_share_pct: float | None,
    margin_to_gdp_pct: float | None,
) -> None:
    """
    Render the bubble peak comparison: US + international, with CAPE,
    household-equity %, post-peak drawdown / recovery, plus a similarity
    ranking of today vs US peaks.
    """
    t = Table(
        title="Historical bubble comparison",
        show_header=True, header_style="bold dim",
        box=None, padding=(0, 1),
        title_style="bold",
        caption=(
            "Buffett indicator = corp-equities mkt value / GDP.  "
            "CAPE = Shiller cyclically-adjusted P/E at peak.  "
            "HHEq% = household equities as % of financial assets.  "
            "DD = peak-to-trough drawdown; Recov = months to nominal new high.  "
            "Red cells = today exceeds that peak."
        ),
        caption_style="dim",
    )
    t.add_column("Era",         style="bold", min_width=22)
    t.add_column("Rgn",         justify="center", style="dim", width=3)
    t.add_column("Buffett",     justify="right")
    t.add_column("CAPE",        justify="right")
    t.add_column("Top-10",      justify="right")
    t.add_column("Margin",      justify="right")
    t.add_column("HHEq%",       justify="right")
    t.add_column("DD",          justify="right")
    t.add_column("Recov",       justify="right")

    # Find max prior peak per metric for "today exceeded" highlighting.
    max_buffett = max((p.buffett_pct for p in HISTORICAL_BUBBLES if p.buffett_pct is not None), default=None)
    max_top10 = max((p.top10_share_pct for p in HISTORICAL_BUBBLES if p.top10_share_pct is not None), default=None)
    max_margin = max((p.margin_to_gdp_pct for p in HISTORICAL_BUBBLES if p.margin_to_gdp_pct is not None), default=None)
    max_cape = max((p.cape for p in HISTORICAL_BUBBLES if p.cape is not None), default=None)

    def _region_tag(region: str) -> str:
        # Two-letter codes — width-stable across terminals (emoji flags break
        # column widths in many terminals). Color codes the corridor.
        codes = {"US": "[cyan]US[/cyan]", "Japan": "[magenta]JP[/magenta]", "China": "[red]CN[/red]"}
        return codes.get(region, region)

    def _dd_cell(dd: float | None) -> str:
        if dd is None:
            return "—"
        # Worse drawdowns = redder
        if dd <= -70:
            return f"[bold red]{dd:.0f}%[/bold red]"
        if dd <= -45:
            return f"[red]{dd:.0f}%[/red]"
        if dd <= -25:
            return f"[yellow]{dd:.0f}%[/yellow]"
        return f"{dd:.0f}%"

    for peak in HISTORICAL_BUBBLES:
        # International peaks are italicized so the reader knows they're
        # cross-corridor context, not similarity candidates.
        name_cell = peak.name if peak.region == "US" else f"[italic]{peak.name}[/italic]"
        t.add_row(
            name_cell,
            _region_tag(peak.region),
            _fmt_or_na(peak.buffett_pct,       suffix="%",  fmt="{:.0f}"),
            _fmt_or_na(peak.cape,              suffix="",   fmt="{:.0f}"),
            _fmt_or_na(peak.top10_share_pct,   suffix="%",  fmt="{:.0f}"),
            _fmt_or_na(peak.margin_to_gdp_pct, suffix="%",  fmt="{:.1f}"),
            _fmt_or_na(peak.hh_equity_pct,     suffix="%",  fmt="{:.0f}"),
            _dd_cell(peak.drawdown_pct),
            format_recover_months(peak.recover_months),
        )

    def _marked(today: float | None, peak_max: float | None, suffix: str, fmt: str) -> str:
        if today is None:
            return "—"
        v = fmt.format(today) + suffix
        color = _hot_color(today, peak_max)
        return f"[{color}]{v}[/{color}]" if color else v

    today_row = [
        "[bold cyan]Today[/bold cyan]",
        _region_tag("US"),
        _marked(buffett_pct,       max_buffett, "%", "{:.0f}"),
        "—",  # CAPE — not yet computed live
        _marked(top10_share_pct,   max_top10,   "%", "{:.0f}"),
        _marked(margin_to_gdp_pct, max_margin,  "%", "{:.1f}"),
        "—",  # HHEq% — not yet computed live
        "—",  # No drawdown yet (we're not post-peak)
        "—",
    ]
    t.add_row(*[Text.from_markup(c) if isinstance(c, str) and "[" in c else c for c in today_row])

    print(Text(""))
    print(t)

    # ── Pattern legend (moved out of the table so it fits 80-col terminals) ──
    print(Text(""))
    print(Text.from_markup("[bold dim]Pattern[/bold dim]"))
    for peak in HISTORICAL_BUBBLES:
        # Compact two-line format: name → pattern. Italicize international.
        label = peak.name if peak.region == "US" else f"[italic]{peak.name}[/italic]"
        print(Text.from_markup(f"  [dim]·[/dim] {label}: [dim]{peak.note}[/dim]"))

    # ── Similarity ranking — which US peak does today most resemble? ─────
    _print_similarity_block(buffett_pct, top10_share_pct, margin_to_gdp_pct)


def _print_similarity_block(
    buffett_pct: float | None,
    top10_share_pct: float | None,
    margin_to_gdp_pct: float | None,
) -> None:
    """
    Print 'Today most resembles ...' ranking using the metrics we have live.

    Only the top 3 US peaks are surfaced — anything below that is noise.
    """
    today = {
        "buffett_pct": buffett_pct,
        "top10_share_pct": top10_share_pct,
        "margin_to_gdp_pct": margin_to_gdp_pct,
    }
    results = compute_similarity(today)
    if not results:
        return

    top = results[:3]

    print(Text(""))
    print(Text.from_markup(
        "[bold]Today most resembles[/bold]  [dim](US peaks only — scored across "
        "Buffett, top-10 share, margin/GDP)[/dim]"
    ))

    # Inline visual: similarity score as a small bar
    def _bar(sim: float, width: int = 16) -> str:
        filled = int(round(sim * width))
        filled = max(0, min(width, filled))
        return f"[green]{'█' * filled}[/green][dim]{'░' * (width - filled)}[/dim]"

    for i, r in enumerate(top):
        rank_marker = "▸▸" if i == 0 else "▸"
        sim_pct = r.similarity * 100
        print(Text.from_markup(
            f"  {rank_marker} {r.peak_name:<26}  {_bar(r.similarity)}  {sim_pct:.0f}%"
        ))

    # One-line interpretive cap based on the top match
    best = top[0]
    if best.similarity > 0.85:
        verdict = f"[bold]→ playbook: {best.peak_name.split('—')[1].strip() if '—' in best.peak_name else best.peak_name}[/bold]"
        print(Text.from_markup(f"  [dim]{verdict}[/dim]"))
