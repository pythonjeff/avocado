"""
CLI command for `lox quiver` — v0 morning brief from Quiver Quantitative
exports. Reads CSVs from data/cache/quiver/, synthesizes a 3-line brief, and
renders per-dataset panels with the top yesterday/recent disclosures.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

import typer
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from lox.quiver import congress as q_congress
from lox.quiver import contracts as q_contracts
from lox.quiver import flow as q_flow
from lox.quiver import trumptrades as q_trump
from lox.quiver.loader import CATALOG, available_keys, fetch_congress_live, fetch_trump_live, get_api_key, missing_keys, quiver_dir
from lox.quiver.signal import QuiverSignal, build_signals
from lox.quiver.signal_email import send_signal_email
from lox.quiver.synthesis import QuiverBrief, build_brief


app = typer.Typer(add_completion=False, help="Quiver Quantitative — congressional / contracts / flow")
congress_app = typer.Typer(add_completion=False, help="Congressional trading data")
app.add_typer(congress_app, name="congress")
djt_app = typer.Typer(add_completion=False, help="Trump stock trades")
app.add_typer(djt_app, name="djt")


# ─────────────────────────────────────────────────────────────────────────────
# Styling
# ─────────────────────────────────────────────────────────────────────────────

_LEAN_COLOR = {
    "defensive": "red",
    "neutral-defensive": "yellow",
    "neutral": "white",
    "neutral-constructive": "green",
    "constructive": "bold green",
}

_LEAN_GLYPH = {
    "defensive": "▼",
    "neutral-defensive": "◆",
    "neutral": "◇",
    "neutral-constructive": "◆",
    "constructive": "▲",
}

_CONVICTION_GLYPH = {
    "high": "▸▸",
    "moderate": "▸",
    "low": "·",
}


def _fmt_usd(v: float) -> str:
    if v >= 1_000_000_000:
        return f"${v/1e9:.2f}B"
    if v >= 1_000_000:
        return f"${v/1e6:.1f}M"
    if v >= 1_000:
        return f"${v/1e3:.0f}K"
    return f"${v:.0f}"


def _fmt_date(d: Optional[date]) -> str:
    return d.isoformat() if d else "—"


# ─────────────────────────────────────────────────────────────────────────────
# Brief renderer (mirrors funding_cmd._show_funding_brief)
# ─────────────────────────────────────────────────────────────────────────────

def _render_brief(console: Console, brief: QuiverBrief, asof_label: str) -> None:
    lean_color = _LEAN_COLOR.get(brief.risk_lean, "white")
    lean_glyph = _LEAN_GLYPH.get(brief.risk_lean, "◇")

    lines: list = []
    lines.append(Text.from_markup(f"[bold]REGIME[/bold]   {brief.regime_line}"))
    lines.append(Text(""))
    lines.append(Text.from_markup(
        f"[bold]RISK[/bold]     [{lean_color}]{lean_glyph} {brief.risk_lean.upper()}[/{lean_color}]"
    ))
    lines.append(Text.from_markup(f"         {brief.risk_line}"))

    if brief.convergences:
        lines.append(Text(""))
        lines.append(Text.from_markup("[bold]CONVERGENCE[/bold]"))
        for hit in brief.convergences:
            lines.append(Text.from_markup(
                f"  [cyan]▸[/cyan] [bold]{hit.ticker}[/bold]  [dim]{hit.note}[/dim]"
            ))

    if brief.trade_ideas:
        lines.append(Text(""))
        lines.append(Text.from_markup("[bold]TRADE[/bold]"))
        for idea in brief.trade_ideas:
            glyph = _CONVICTION_GLYPH.get(idea.conviction, "▸")
            color = "green" if idea.conviction == "high" else ("white" if idea.conviction == "moderate" else "dim")
            lines.append(Text.from_markup(f"  [{color}]{glyph}[/{color}] {idea.expression}"))
            lines.append(Text.from_markup(f"     [dim italic]↳ {idea.rationale}[/dim italic]"))

    if brief.context_notes:
        lines.append(Text(""))
        for note in brief.context_notes:
            lines.append(Text.from_markup(f"  [dim]· {note}[/dim]"))

    panel = Panel(
        Group(*lines),
        title=f"[bold]Quiver — Brief[/bold]  [dim]asof {asof_label}[/dim]",
        title_align="left",
        border_style="bold cyan",
        padding=(1, 2),
    )
    console.print(panel)


# ─────────────────────────────────────────────────────────────────────────────
# Catalog panel — shown when no CSVs are present yet
# ─────────────────────────────────────────────────────────────────────────────

def _render_catalog(console: Console) -> None:
    """Show the user what to download and where to drop it."""
    path = quiver_dir()
    lines: list = []
    lines.append(Text.from_markup(
        "[bold]No Quiver CSVs found yet.[/bold] Drop dataset exports here, then re-run [cyan]lox quiver[/cyan]:"
    ))
    lines.append(Text.from_markup(f"  [dim]{path}/[/dim]"))
    lines.append(Text(""))

    t = Table(show_header=True, header_style="bold cyan", box=None, pad_edge=False)
    t.add_column("Dataset")
    t.add_column("Filename")
    t.add_column("Source URL", overflow="fold")
    t.add_column("Why we pull it", overflow="fold")
    for d in CATALOG:
        t.add_column
        t.add_row(d.label, f"[dim]{d.filename}[/dim]", d.url, d.insight)
    lines.append(t)

    lines.append(Text(""))
    lines.append(Text.from_markup(
        "[dim]Tip — log into quiverquant.com, open each dataset page, and use the CSV download "
        "button. Premium ($10/mo) is required for full CSV exports and the API.[/dim]"
    ))

    console.print(Panel(
        Group(*lines),
        title="[bold]Quiver — Setup[/bold]",
        title_align="left",
        border_style="bold yellow",
        padding=(1, 2),
    ))


def _render_access_check(console: Console) -> None:
    """Always-on note telling the user how to confirm their tier."""
    body = Text.from_markup(
        "[bold]Confirm your Quiver access:[/bold]\n"
        "  · Log into [cyan]quiverquant.com[/cyan] → click your username (top-right).\n"
        "  · [bold]API tab[/bold]: if you see a token, you have Premium API. Set [cyan]QUIVER_API_KEY[/cyan] in .env.\n"
        "  · [bold]Subscription tab[/bold]: Premium ($10/mo) unlocks CSV downloads on every dataset page.\n"
        "  · Free tier shows website tables only — limited use for daily pulls."
    )
    console.print(Panel(body, title="[bold]Access check[/bold]", border_style="dim", padding=(1, 2)))


# ─────────────────────────────────────────────────────────────────────────────
# Per-dataset panels
# ─────────────────────────────────────────────────────────────────────────────

def _render_congress(console: Console, r: q_congress.CongressReadout) -> None:
    if not r.have_data:
        return

    # Recent disclosures
    t = Table(show_header=True, header_style="bold cyan", title=None, box=None)
    t.add_column("Disclosed")
    t.add_column("Lawmaker")
    t.add_column("Cham")
    t.add_column("Ticker")
    t.add_column("Side")
    t.add_column("Amount (mid)")
    t.add_column("Bucket", overflow="fold")
    for x in r.recent:
        side_style = "green" if x.side == "Buy" else ("red" if x.side == "Sell" else "white")
        t.add_row(
            _fmt_date(x.disclosed),
            x.lawmaker,
            x.chamber or "—",
            f"[bold]{x.ticker}[/bold]",
            f"[{side_style}]{x.side or '—'}[/{side_style}]",
            _fmt_usd(x.amount_mid_usd),
            x.raw_amount or "—",
        )

    blocks: list = [Text.from_markup("[bold]Recent disclosures[/bold]"), t]

    # Cluster buys
    if r.cluster_buys:
        cb = Table(show_header=True, header_style="bold cyan", box=None)
        cb.add_column("Ticker")
        cb.add_column("Buyers")
        cb.add_column("Total (mid)")
        cb.add_column("Lawmakers", overflow="fold")
        for c in r.cluster_buys:
            cb.add_row(
                f"[bold]{c.ticker}[/bold]",
                str(c.buyer_count),
                _fmt_usd(c.total_mid_usd),
                ", ".join(c.lawmakers),
            )
        blocks.append(Text(""))
        blocks.append(Text.from_markup("[bold]Cluster buys[/bold]  [dim](same ticker, ≥2 lawmakers in window)[/dim]"))
        blocks.append(cb)

    # Top buyers
    if r.top_buyers:
        tb = Table(show_header=True, header_style="bold cyan", box=None)
        tb.add_column("Lawmaker")
        tb.add_column("Cham")
        tb.add_column("Trades")
        tb.add_column("Total (mid)")
        for b in r.top_buyers:
            tb.add_row(b.lawmaker, b.chamber or "—", str(b.n_trades), _fmt_usd(b.total_mid_usd))
        blocks.append(Text(""))
        blocks.append(Text.from_markup("[bold]Most active lawmakers[/bold]"))
        blocks.append(tb)

    console.print(Panel(
        Group(*blocks),
        title=f"[bold]Congressional Trading[/bold]  [dim]asof {_fmt_date(r.asof)} · n={r.n_trades_recent}[/dim]",
        title_align="left",
        border_style="cyan",
        padding=(1, 2),
    ))


def _render_contracts(console: Console, r: q_contracts.ContractsReadout) -> None:
    if not r.have_data:
        return
    t = Table(show_header=True, header_style="bold cyan", box=None)
    t.add_column("Awarded")
    t.add_column("Ticker")
    t.add_column("Agency", overflow="fold")
    t.add_column("Amount")
    t.add_column("Description", overflow="fold")
    for c in r.top_contracts:
        t.add_row(
            _fmt_date(c.awarded),
            f"[bold]{c.ticker}[/bold]",
            c.agency or "—",
            _fmt_usd(c.amount_usd),
            c.description or "—",
        )

    blocks: list = [Text.from_markup("[bold]Top recent awards[/bold]"), t]

    if r.by_ticker:
        agg = Table(show_header=True, header_style="bold cyan", box=None)
        agg.add_column("Ticker")
        agg.add_column("# Contracts")
        agg.add_column("Total $")
        agg.add_column("Agencies", overflow="fold")
        for a in r.by_ticker:
            agg.add_row(f"[bold]{a.ticker}[/bold]", str(a.n_contracts), _fmt_usd(a.total_usd), ", ".join(a.agencies))
        blocks.append(Text(""))
        blocks.append(Text.from_markup("[bold]By ticker[/bold]"))
        blocks.append(agg)

    console.print(Panel(
        Group(*blocks),
        title=f"[bold]Government Contracts[/bold]  [dim]asof {_fmt_date(r.asof)} · n={r.n_contracts_recent}[/dim]",
        title_align="left",
        border_style="cyan",
        padding=(1, 2),
    ))


def _render_insider(console: Console, r: q_flow.InsiderReadout) -> None:
    if not r.have_data:
        return
    t = Table(show_header=True, header_style="bold cyan", box=None)
    t.add_column("Filed")
    t.add_column("Ticker")
    t.add_column("Insider", overflow="fold")
    t.add_column("Title")
    t.add_column("Shares")
    t.add_column("Value")
    for b in r.top_buys:
        t.add_row(
            _fmt_date(b.filed),
            f"[bold]{b.ticker}[/bold]",
            b.insider,
            b.title or "—",
            f"{b.shares:,.0f}" if b.shares else "—",
            _fmt_usd(b.value_usd),
        )
    blocks: list = [Text.from_markup("[bold]Top insider buys[/bold]"), t]

    if r.clusters:
        cl = Table(show_header=True, header_style="bold cyan", box=None)
        cl.add_column("Ticker")
        cl.add_column("# Insiders")
        cl.add_column("Total Value")
        cl.add_column("Insiders", overflow="fold")
        for c in r.clusters:
            cl.add_row(f"[bold]{c.ticker}[/bold]", str(c.n_buyers), _fmt_usd(c.total_value_usd), ", ".join(c.insiders))
        blocks.append(Text(""))
        blocks.append(Text.from_markup("[bold]Insider cluster buys[/bold]  [dim](≥2 distinct insiders)[/dim]"))
        blocks.append(cl)

    console.print(Panel(
        Group(*blocks),
        title=f"[bold]Insider Trading[/bold]  [dim]asof {_fmt_date(r.asof)}[/dim]",
        title_align="left",
        border_style="cyan",
        padding=(1, 2),
    ))


def _render_wsb(console: Console, r: q_flow.WsbReadout) -> None:
    if not r.have_data or not r.top_movers:
        return
    t = Table(show_header=True, header_style="bold cyan", box=None)
    t.add_column("Ticker")
    t.add_column("Today")
    t.add_column("Prev")
    t.add_column("Δ %")
    t.add_column("Sentiment")
    for d in r.top_movers:
        delta = "+∞%" if d.delta_pct == float("inf") else f"{d.delta_pct:+.0f}%"
        t.add_row(
            f"[bold]{d.ticker}[/bold]",
            f"{d.mentions_today:,.0f}",
            f"{d.mentions_prev:,.0f}",
            delta,
            f"{d.sentiment:+.2f}" if d.sentiment else "—",
        )
    console.print(Panel(
        t,
        title=f"[bold]r/WSB Mention Movers[/bold]  [dim]asof {_fmt_date(r.asof)}[/dim]",
        title_align="left",
        border_style="cyan",
        padding=(1, 2),
    ))


def _render_otc_short(console: Console, r: q_flow.OtcShortReadout) -> None:
    if not r.have_data or not r.spikes:
        return
    t = Table(show_header=True, header_style="bold cyan", box=None)
    t.add_column("Ticker")
    t.add_column("Short Vol")
    t.add_column("Total Vol")
    t.add_column("Short Share")
    for s in r.spikes:
        share_style = "red" if s.short_share >= 0.6 else ("yellow" if s.short_share >= 0.5 else "white")
        t.add_row(
            f"[bold]{s.ticker}[/bold]",
            f"{s.short_volume:,.0f}",
            f"{s.total_volume:,.0f}",
            f"[{share_style}]{s.short_share*100:.1f}%[/{share_style}]",
        )
    console.print(Panel(
        t,
        title=f"[bold]Off-Exchange Short-Share Spikes[/bold]  [dim]asof {_fmt_date(r.asof)}[/dim]",
        title_align="left",
        border_style="cyan",
        padding=(1, 2),
    ))


# ─────────────────────────────────────────────────────────────────────────────
# Main command
# ─────────────────────────────────────────────────────────────────────────────

@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    window: int = typer.Option(7, "--window", "-w", help="Recent-window length in days."),
) -> None:
    """Quiver morning brief — congressional / contracts / insider / WSB / OTC short."""
    if ctx.invoked_subcommand is not None:
        return

    console = Console()

    available = available_keys()
    missing = missing_keys()

    # If we have no data at all, show the catalog + access check and exit.
    if not available:
        _render_access_check(console)
        _render_catalog(console)
        return

    # Build readouts
    congress = q_congress.build_readout(window_days=window)
    contracts = q_contracts.build_readout(window_days=window)
    insider = q_flow.build_insider_readout(window_days=window)
    wsb = q_flow.build_wsb_readout()
    otc_short = q_flow.build_otc_short_readout()

    # Pick the asof — the most recent of any dataset's asof
    asof_candidates = [
        d for d in (congress.asof, contracts.asof, insider.asof, wsb.asof, otc_short.asof) if d
    ]
    asof_label = max(asof_candidates).isoformat() if asof_candidates else "—"

    brief = build_brief(
        congress=congress,
        contracts=contracts,
        insider=insider,
        wsb=wsb,
        otc_short=otc_short,
        available=available,
        missing=missing,
    )

    _render_brief(console, brief, asof_label)
    _render_congress(console, congress)
    _render_contracts(console, contracts)
    _render_insider(console, insider)
    _render_wsb(console, wsb)
    _render_otc_short(console, otc_short)


@app.command("catalog")
def catalog_cmd() -> None:
    """Show the dataset catalog (what to download and where to drop it)."""
    console = Console()
    _render_access_check(console)
    _render_catalog(console)


# ─────────────────────────────────────────────────────────────────────────────
# lox quiver congress trades  (live API)
# ─────────────────────────────────────────────────────────────────────────────

@congress_app.command("trades")
def congress_trades_cmd(
    window: int = typer.Option(7, "--window", "-w", help="Look-back window in days."),
    top: int = typer.Option(20, "--top", "-n", help="Max recent trades to show."),
) -> None:
    """Pull live congressional trades from the Quiver API and display them."""
    console = Console()

    api_key = get_api_key()
    if not api_key:
        console.print(
            "[bold red]QUIVER_API_KEY not set.[/bold red] "
            "Add it to your .env file and re-run."
        )
        raise typer.Exit(1)

    with console.status("[cyan]Fetching congressional trades from Quiver API…[/cyan]"):
        try:
            df = fetch_congress_live(api_key)
        except RuntimeError as exc:
            console.print(f"[bold red]Error:[/bold red] {exc}")
            raise typer.Exit(1)

    if df is None or df.empty:
        console.print("[yellow]API returned no data.[/yellow]")
        raise typer.Exit(0)

    readout = q_congress.build_readout(window_days=window, top_n=top, df=df)
    if not readout.have_data:
        console.print("[yellow]Could not parse API response — unexpected column shape.[/yellow]")
        raise typer.Exit(1)

    _render_congress(console, readout)


# ─────────────────────────────────────────────────────────────────────────────
# lox quiver djt trade  (live API)
# ─────────────────────────────────────────────────────────────────────────────

def _render_trump(console: Console, r: q_trump.TrumpReadout) -> None:
    # Recent trades table
    t = Table(show_header=True, header_style="bold cyan", box=None)
    t.add_column("Traded")
    t.add_column("Filed")
    t.add_column("Ticker")
    t.add_column("Company", overflow="fold")
    t.add_column("Side")
    t.add_column("Amount")
    t.add_column("α vs SPY", justify="right")
    for x in r.trades:
        side_style = "green" if x.side == "Buy" else ("red" if x.side == "Sell" else "white")
        er = f"{x.excess_return:+.1f}%" if x.excess_return is not None else "—"
        er_style = "green" if (x.excess_return or 0) > 0 else ("red" if (x.excess_return or 0) < 0 else "dim")
        t.add_row(
            _fmt_date(x.traded),
            _fmt_date(x.filed),
            f"[bold]{x.ticker or '—'}[/bold]",
            x.company or "—",
            f"[{side_style}]{x.side or '—'}[/{side_style}]",
            x.raw_amount or "—",
            f"[{er_style}]{er}[/{er_style}]",
        )

    blocks: list = [Text.from_markup("[bold]Trades[/bold]  [dim](sorted by date → amount)[/dim]"), t]

    # By-ticker summary
    if r.by_ticker:
        st = Table(show_header=True, header_style="bold cyan", box=None)
        st.add_column("Ticker")
        st.add_column("Company", overflow="fold")
        st.add_column("# Trades")
        st.add_column("Total (mid)")
        st.add_column("Last")
        st.add_column("Avg α vs SPY", justify="right")
        for s in r.by_ticker:
            er = f"{s.avg_excess_return:+.1f}%" if s.avg_excess_return is not None else "—"
            er_style = "green" if (s.avg_excess_return or 0) > 0 else ("red" if (s.avg_excess_return or 0) < 0 else "dim")
            last_style = "green" if s.last_side == "Buy" else ("red" if s.last_side == "Sell" else "white")
            st.add_row(
                f"[bold]{s.ticker}[/bold]",
                s.company,
                str(s.n_trades),
                _fmt_usd(s.total_mid_usd),
                f"[{last_style}]{s.last_side}[/{last_style}]",
                f"[{er_style}]{er}[/{er_style}]",
            )
        blocks.append(Text(""))
        blocks.append(Text.from_markup("[bold]By ticker[/bold]  [dim](ranked by total size)[/dim]"))
        blocks.append(st)

    console.print(Panel(
        Group(*blocks),
        title=f"[bold]Trump Stock Trades[/bold]  [dim]asof {_fmt_date(r.asof)} · n={len(r.trades)}[/dim]",
        title_align="left",
        border_style="bold red",
        padding=(1, 2),
    ))


@djt_app.command("trade")
def djt_trade_cmd(
    top: int = typer.Option(30, "--top", "-n", help="Max trades to show."),
) -> None:
    """Pull Trump stock trades from the Quiver API and display them."""
    console = Console()

    api_key = get_api_key()
    if not api_key:
        console.print("[bold red]QUIVER_API_KEY not set.[/bold red] Add it to your .env file and re-run.")
        raise typer.Exit(1)

    with console.status("[cyan]Fetching Trump stock trades from Quiver API…[/cyan]"):
        try:
            df = fetch_trump_live(api_key)
        except RuntimeError as exc:
            console.print(f"[bold red]Error:[/bold red] {exc}")
            raise typer.Exit(1)

    if df is None or df.empty:
        console.print("[yellow]API returned no data.[/yellow]")
        raise typer.Exit(0)

    readout = q_trump.build_readout(df=df, top_n=top)
    if not readout.have_data:
        console.print("[yellow]No data to display.[/yellow]")
        raise typer.Exit(1)

    _render_trump(console, readout)


# ─────────────────────────────────────────────────────────────────────────────
# lox quiver signal  — cross-source signal scanner
# ─────────────────────────────────────────────────────────────────────────────

_SCORE_GLYPHS = {5: "▸▸▸", 4: "▸▸", 3: "▸", 2: "·", 1: "·"}


def _render_signals(console: Console, signals: list[QuiverSignal]) -> None:
    from rich.text import Text as RText

    lines: list = []
    for s in signals:
        side_style = "green" if s.side == "Buy" else "red"
        play = "call" if s.side == "Buy" else "put "

        filled = round(s.score * 5)
        sig_str = "▸" * filled + "·" * (5 - filled)

        alpha_str = f"{s.alpha_vs_spy:+.1f}%" if s.alpha_vs_spy is not None else "  —  "
        if s.alpha_vs_spy is not None:
            alpha_ok = (s.side == "Buy" and s.alpha_vs_spy <= 2) or (s.side == "Sell" and s.alpha_vs_spy >= -2)
            alpha_style = "green" if alpha_ok else "yellow"
        else:
            alpha_style = "dim"

        def _last(name: str) -> str:
            return name.split()[-1] if name != "Trump" else "Trump"
        names = [_last(o) for o in s.officials[:2]]
        officials_str = ", ".join(names) + (f" +{len(s.officials)-2}" if len(s.officials) > 2 else "")

        line = RText()
        line.append(f"{s.avg_lag_days:2.0f}d  ", style="dim")
        line.append(f"{s.ticker:<6}", style="bold white")
        line.append(f"{s.side:<5}", style=side_style)
        line.append(f"[{play} ATM 45d]  ", style="cyan")
        line.append(f"{alpha_str:>7}  ", style=alpha_style)
        line.append(f"{_fmt_usd(s.total_usd):>6}  ", style="dim")
        line.append("▸" * filled, style="yellow")
        line.append("·" * (5 - filled) + "  ", style="dim")
        line.append(officials_str, style="dim")
        lines.append(line)

    console.print(Panel(
        Group(*lines),
        title=f"[bold]Quiver Signals[/bold]  [dim]{len(signals)} signals · sorted by lag[/dim]",
        title_align="left",
        border_style="bold yellow",
        padding=(1, 2),
    ))


@app.command("signal")
def signal_cmd(
    lag: int = typer.Option(14, "--lag", "-l", help="Max disclosure lag in days to consider."),
    min_score: float = typer.Option(0.55, "--min-score", "-s", help="Minimum signal score to display (0-1)."),
    email: bool = typer.Option(False, "--email", "-e", help="Send digest to your email."),
    to: str = typer.Option("jeffreyblarson00@gmail.com", "--to", help="Recipient address."),
) -> None:
    """Score congress + trump trades and surface actionable options signals."""
    console = Console()

    api_key = get_api_key()
    if not api_key:
        console.print("[bold red]QUIVER_API_KEY not set.[/bold red]")
        raise typer.Exit(1)

    with console.status("[cyan]Fetching congress and Trump trades…[/cyan]"):
        try:
            congress_df = fetch_congress_live(api_key)
            trump_df = fetch_trump_live(api_key)
        except RuntimeError as exc:
            console.print(f"[bold red]API error:[/bold red] {exc}")
            raise typer.Exit(1)

    signals = build_signals(congress_df, trump_df, max_lag_days=lag, min_score=min_score)

    if not signals:
        console.print(f"[yellow]No notable signals within {lag}d lag / score ≥ {min_score}.[/yellow]")
        raise typer.Exit(0)

    _render_signals(console, signals)

    if email:
        # Email uses a tighter floor — only send the highest-conviction names
        email_signals = [s for s in signals if s.score >= max(min_score, 0.60)]
        if not email_signals:
            console.print("[dim]No signals above email threshold (0.60) — skipping send.[/dim]")
        else:
            with console.status(f"[cyan]Sending {len(email_signals)} signals to {to}…[/cyan]"):
                try:
                    send_signal_email(email_signals, to_email=to, asof=date.today())
                    console.print(f"[green]✓ Email sent to {to} ({len(email_signals)} signals)[/green]")
                except RuntimeError as exc:
                    console.print(f"[bold red]Email failed:[/bold red] {exc}")
                    raise typer.Exit(1)
