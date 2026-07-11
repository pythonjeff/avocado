"""
Quiver synthesis — turns the per-dataset readouts into a 3-line institutional
brief: REGIME, RISK, TRADE. Same shape as lox.funding.synthesis so the panel
header reads the way every other regime panel does.

Convergence is the key idea: when the same ticker shows up across two or more
of {congressional buys, gov contracts, insider buys, OTC short spikes}, that's
the high-conviction list. Single-source signals are listed too but ranked below.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from lox.quiver.congress import CongressReadout
from lox.quiver.contracts import ContractsReadout
from lox.quiver.flow import InsiderReadout, OtcShortReadout, WsbReadout


# ─────────────────────────────────────────────────────────────────────────────
# Dataclasses
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ConvergenceHit:
    ticker: str
    sources: list[str]   # which datasets flagged this name
    note: str            # one-line "why it's interesting"


@dataclass
class TradeIdea:
    expression: str
    rationale: str
    conviction: str = "moderate"   # "high" | "moderate" | "low"


@dataclass
class QuiverBrief:
    regime_line: str
    risk_line: str
    risk_lean: str        # "defensive" | "neutral-defensive" | "neutral" | "neutral-constructive" | "constructive"
    convergences: list[ConvergenceHit] = field(default_factory=list)
    trade_ideas: list[TradeIdea] = field(default_factory=list)
    context_notes: list[str] = field(default_factory=list)
    available_sources: list[str] = field(default_factory=list)
    missing_sources: list[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Builder
# ─────────────────────────────────────────────────────────────────────────────

def build_brief(
    *,
    congress: CongressReadout,
    contracts: ContractsReadout,
    insider: InsiderReadout,
    wsb: WsbReadout,
    otc_short: OtcShortReadout,
    available: list[str],
    missing: list[str],
) -> QuiverBrief:
    # Collect ticker → sources map
    ticker_sources: dict[str, set[str]] = {}

    if congress.have_data:
        # Cluster buys (≥2 lawmakers) are stronger than single disclosures
        for c in congress.cluster_buys:
            ticker_sources.setdefault(c.ticker, set()).add("congress-cluster")
        # Also flag the largest single buys as a weaker signal
        for t in congress.recent[:5]:
            if t.side == "Buy":
                ticker_sources.setdefault(t.ticker, set()).add("congress")

    if contracts.have_data:
        for agg in contracts.by_ticker[:5]:
            ticker_sources.setdefault(agg.ticker, set()).add("contracts")

    if insider.have_data:
        for cl in insider.clusters:
            ticker_sources.setdefault(cl.ticker, set()).add("insider-cluster")
        for b in insider.top_buys[:5]:
            ticker_sources.setdefault(b.ticker, set()).add("insider")

    if otc_short.have_data:
        # Only count the very top OTC short spikes (>55% share) as a signal.
        # NOTE: the "high share precedes squeezes" read is an unvalidated
        # hypothesis, not a documented fact. FINRA off-exchange short volume
        # is largely market-maker/internalizer legs offsetting retail
        # marketable *buy* orders, so a high share can coincide with retail
        # buying pressure rather than net-short positioning. Treat this as
        # confirmation-only (like WSB) until backtested on our own data.
        for r in otc_short.spikes[:5]:
            if r.short_share >= 0.55:
                ticker_sources.setdefault(r.ticker, set()).add("otc-short-spike")

    if wsb.have_data:
        for d in wsb.top_movers[:5]:
            # WSB on its own is noise; we only surface as confirmation
            ticker_sources.setdefault(d.ticker, set()).add("wsb")

    # Convergence hits: ticker appears in 2+ DISTINCT dataset families
    def _family(src: str) -> str:
        if src.startswith("congress"):
            return "congress"
        if src.startswith("insider"):
            return "insider"
        return src

    convergences: list[ConvergenceHit] = []
    for ticker, srcs in ticker_sources.items():
        families = {_family(s) for s in srcs}
        if len(families) >= 2:
            convergences.append(
                ConvergenceHit(
                    ticker=ticker,
                    sources=sorted(srcs),
                    note=_convergence_note(ticker, srcs, congress, contracts, insider),
                )
            )
    convergences.sort(key=lambda c: (-len(c.sources), c.ticker))

    # ── REGIME line — what was disclosed yesterday/recent ────────────────────
    regime_parts: list[str] = []
    if congress.have_data:
        n = congress.n_trades_recent
        regime_parts.append(f"{n} congressional disclosure{'s' if n != 1 else ''}")
    if contracts.have_data:
        regime_parts.append(f"{contracts.n_contracts_recent} gov contracts")
    if insider.have_data:
        regime_parts.append(f"{len(insider.top_buys)} insider buys")
    if not regime_parts:
        regime_line = "no Quiver data loaded yet — drop CSV exports into data/cache/quiver/"
    else:
        regime_line = " · ".join(regime_parts) + " in the recent window"

    # ── RISK line — where is the smart-money flow pointing ───────────────────
    risk_line, risk_lean = _build_risk_line(
        convergences=convergences,
        congress=congress,
        contracts=contracts,
        insider=insider,
        otc_short=otc_short,
    )

    # ── TRADE ideas ──────────────────────────────────────────────────────────
    trade_ideas: list[TradeIdea] = []
    # 1) Convergence names — highest conviction
    for hit in convergences[:3]:
        conviction = "high" if len(hit.sources) >= 3 else "moderate"
        trade_ideas.append(
            TradeIdea(
                expression=f"Long {hit.ticker} — confirmation across {', '.join(sorted({_family(s) for s in hit.sources}))}",
                rationale=hit.note,
                conviction=conviction,
            )
        )
    # 2) Standout congressional cluster buy if not already covered
    covered = {idea.expression.split()[1] for idea in trade_ideas if idea.expression.startswith("Long")}
    if congress.have_data and congress.cluster_buys:
        top_cluster = congress.cluster_buys[0]
        if top_cluster.ticker not in covered and top_cluster.buyer_count >= 3:
            trade_ideas.append(
                TradeIdea(
                    expression=f"Long {top_cluster.ticker}",
                    rationale=f"{top_cluster.buyer_count} lawmakers disclosed buys: {', '.join(top_cluster.lawmakers[:3])}",
                    conviction="moderate",
                )
            )
    # 3) Largest contract winner if not already covered
    if contracts.have_data and contracts.by_ticker:
        top_agg = contracts.by_ticker[0]
        if top_agg.ticker not in covered and top_agg.total_usd >= 100_000_000:
            trade_ideas.append(
                TradeIdea(
                    expression=f"Watch {top_agg.ticker}",
                    rationale=f"${top_agg.total_usd/1e6:.0f}M in fresh awards from {', '.join(top_agg.agencies[:2])}",
                    conviction="low",
                )
            )

    # ── Context notes ─────────────────────────────────────────────────────────
    context_notes: list[str] = []
    if missing:
        labels = ", ".join(_label_for(k) for k in missing)
        context_notes.append(f"datasets not loaded: {labels}")
    if congress.have_data and congress.top_buyers:
        tb = congress.top_buyers[0]
        context_notes.append(
            f"most active lawmaker this window: {tb.lawmaker} ({tb.n_trades} trades, ~${tb.total_mid_usd/1e3:.0f}K)"
        )

    return QuiverBrief(
        regime_line=regime_line,
        risk_line=risk_line,
        risk_lean=risk_lean,
        convergences=convergences[:8],
        trade_ideas=trade_ideas,
        context_notes=context_notes,
        available_sources=available,
        missing_sources=missing,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _build_risk_line(
    *,
    convergences: list[ConvergenceHit],
    congress: CongressReadout,
    contracts: ContractsReadout,
    insider: InsiderReadout,
    otc_short: OtcShortReadout,
) -> tuple[str, str]:
    """Lean is constructive when buying-side signals dominate; defensive when not."""
    buy_count = 0
    sell_count = 0
    if congress.have_data:
        for t in congress.recent:
            if t.side == "Buy":
                buy_count += 1
            elif t.side == "Sell":
                sell_count += 1
    if insider.have_data:
        buy_count += len(insider.top_buys)

    if not convergences and buy_count == 0 and sell_count == 0:
        return ("no convergence yet — load more Quiver datasets to surface confirmation signals", "neutral")

    if convergences and len(convergences) >= 3:
        return (
            f"{len(convergences)} names show cross-dataset confirmation — high-conviction watchlist forming",
            "constructive",
        )
    if convergences:
        names = ", ".join(c.ticker for c in convergences[:3])
        return (f"convergence on {names} — multi-source confirmation", "neutral-constructive")

    if buy_count > sell_count * 2:
        return (f"{buy_count} buy-side disclosures vs {sell_count} sells — single-source bullish skew", "neutral-constructive")
    if sell_count > buy_count * 2:
        return (f"{sell_count} sells vs {buy_count} buys — single-source distribution skew", "neutral-defensive")

    return ("disclosures balanced — wait for convergence before sizing", "neutral")


def _convergence_note(
    ticker: str,
    sources: set[str],
    congress: CongressReadout,
    contracts: ContractsReadout,
    insider: InsiderReadout,
) -> str:
    parts: list[str] = []
    if "congress-cluster" in sources or "congress" in sources:
        if congress.have_data:
            cb = next((c for c in congress.cluster_buys if c.ticker == ticker), None)
            if cb:
                parts.append(f"{cb.buyer_count} lawmakers")
            else:
                trades = [t for t in congress.recent if t.ticker == ticker and t.side == "Buy"]
                if trades:
                    parts.append(f"{trades[0].lawmaker} (Congress)")
    if "insider-cluster" in sources or "insider" in sources:
        if insider.have_data:
            cl = next((c for c in insider.clusters if c.ticker == ticker), None)
            if cl:
                parts.append(f"{cl.n_buyers} insiders bought")
            else:
                parts.append("insider buy filed")
    if "contracts" in sources and contracts.have_data:
        agg = next((a for a in contracts.by_ticker if a.ticker == ticker), None)
        if agg:
            parts.append(f"${agg.total_usd/1e6:.0f}M fresh awards")
    if "otc-short-spike" in sources:
        parts.append("OTC short-share spike")
    if "wsb" in sources:
        parts.append("WSB mention surge")
    return " · ".join(parts) if parts else ", ".join(sorted(sources))


_LABELS = {
    "congress": "Congressional Trading",
    "contracts": "Gov Contracts",
    "insider": "Insider (Form 4)",
    "wsb": "WSB Mentions",
    "otc_short": "OTC Short Volume",
}


def _label_for(key: str) -> str:
    return _LABELS.get(key, key)
