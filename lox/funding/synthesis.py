"""
Funding regime synthesis — turns the panel's data sections into a 3-line
institutional-style brief: regime, risk implication, trade lean.

Why this module exists: the funding panel computes a lot — corridor stress,
plumbing levels, cross-correlations, lead-lag, cross-regime scores. A buy-side
researcher's morning note never opens with that data; it opens with a brief
that crunches it into actionable readout, with the data below as support.

Design: pure deterministic rules over already-computed inputs. No LLM, no
fetches. The output is a dataclass that the CLI renders. Trade ideas reference
the *specific active signal* that justifies them so the user can verify.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# Dataclasses
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ActiveSignal:
    name: str
    detail: str   # e.g. "+0.51 corr, 25-day lead"
    tradeable: bool


@dataclass
class TradeIdea:
    expression: str       # the trade itself
    rationale: str        # which signal justifies it (so user can verify)
    conviction: str = "moderate"  # "high" | "moderate" | "low"


@dataclass
class FundingBrief:
    regime_line: str
    risk_line: str
    risk_lean: str        # "defensive" | "neutral-defensive" | "neutral" | "neutral-constructive" | "constructive"
    active_signals: list[ActiveSignal] = field(default_factory=list)
    broken_couplings: list[str] = field(default_factory=list)
    trade_ideas: list[TradeIdea] = field(default_factory=list)
    context_notes: list[str] = field(default_factory=list)
    # Offshore USD stress block — populated only when score >= 20 (watch).
    # Calm offshore status is summarized as a one-liner in context_notes instead.
    offshore_label: Optional[str] = None     # "watch" | "stress" | "crisis" when shown
    offshore_drivers: list[str] = field(default_factory=list)
    offshore_score: Optional[float] = None


# ─────────────────────────────────────────────────────────────────────────────
# Regime-line construction
# ─────────────────────────────────────────────────────────────────────────────

def _net_liq_phrase(nl: dict | None) -> str:
    """Plain-English net-liquidity trend phrase."""
    if not nl:
        return ""
    d30 = nl.get("delta_30d_b")
    level_t = nl.get("level_t")
    if d30 is None or level_t is None:
        return ""
    if d30 < -100:
        return f"net liquidity draining hard (-${abs(d30):.0f}B/30d)"
    if d30 < -30:
        return f"net liquidity drifting lower (-${abs(d30):.0f}B/30d)"
    if d30 > 100:
        return f"net liquidity expanding (+${d30:.0f}B/30d)"
    if d30 > 30:
        return f"net liquidity drifting higher (+${d30:.0f}B/30d)"
    return "net liquidity ~flat"


def _reserves_phrase(reserves_m: float | None) -> str:
    if not isinstance(reserves_m, (int, float)):
        return ""
    t = reserves_m / 1_000_000.0
    if t < 3.0:
        return f"reserves scarce (${t:.2f}T, below LCLoR)"
    if t < 3.2:
        return f"reserves approaching scarcity (${t:.2f}T)"
    if t < 3.5:
        return f"reserves comfortable (${t:.2f}T)"
    return f"reserves abundant (${t:.2f}T)"


def _rrp_phrase(rrp_m: float | None) -> str:
    if not isinstance(rrp_m, (int, float)):
        return ""
    bn = rrp_m / 1000.0
    if bn < 50:
        return "RRP cushion essentially gone"
    if bn < 200:
        return f"RRP thin (${bn:.0f}B)"
    if bn > 500:
        return f"RRP ample (${bn / 1000:.1f}T)"
    return f"RRP moderate (${bn:.0f}B)"


def _build_regime_line(
    fi,
    regime,
    corr_rep: dict,
    nl: dict | None,
) -> str:
    """One-line plain-English regime call."""
    plumbing_regime = corr_rep.get("regime")
    epairs = corr_rep.get("equity_pairs") or []
    broken_count = sum(1 for p in epairs if p.get("status") in ("broken", "flipped"))
    total_eq = len(epairs)

    parts: list[str] = []

    # Lead with the plumbing-decoupled framing if it's the dominant story
    if total_eq >= 3 and broken_count == total_eq:
        parts.append("Plumbing-decoupled. Equities trading on flow/sentiment, not Fed.")
    elif plumbing_regime == "RESERVE-CONSTRAINED":
        parts.append("Reserve-constrained. Reserves are the binding driver of corridor stress.")
    elif plumbing_regime == "RRP-CUSHIONED":
        parts.append("RRP-cushioned. MMF cash is absorbing the funding pressure.")
    elif plumbing_regime == "NET-LIQUIDITY-DRIVEN":
        parts.append("Net-liquidity driven. Composite liquidity is the primary corridor lever.")
    elif plumbing_regime == "DECOUPLED":
        parts.append("Decoupled funding. Corridor moving on idiosyncratic stress, not plumbing.")
    else:
        # Fallback to the funding-regime label
        parts.append(f"{regime.label or regime.name}.")

    # Append plumbing-level snapshot
    levels = [
        _net_liq_phrase(nl),
        _reserves_phrase(fi.bank_reserves_usd_bn),
        _rrp_phrase(fi.on_rrp_usd_bn),
    ]
    levels = [l for l in levels if l]
    if levels:
        # Capitalize the first phrase so the sentence flows correctly when
        # concatenated to the regime-call sentence.
        levels[0] = levels[0][0].upper() + levels[0][1:]
        parts.append(", ".join(levels) + ".")

    return " ".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# Risk-line construction
# ─────────────────────────────────────────────────────────────────────────────

def _build_risk_assessment(
    regime,
    corr_rep: dict,
    cross_scores: dict | None,
) -> tuple[str, str]:
    """Return (risk_line, lean) where lean is the categorical lean."""
    score = regime.score
    epairs = corr_rep.get("equity_pairs") or []
    broken_count = sum(1 for p in epairs if p.get("status") in ("broken", "flipped"))
    total_eq = len(epairs)
    all_broken = total_eq >= 3 and broken_count == total_eq

    # Cross-regime late-cycle detector
    cs = cross_scores or {}
    credit_score = cs.get("credit", {}).get("score")
    rates_score = cs.get("rates", {}).get("score")
    vol_score = cs.get("volatility", {}).get("score")
    late_cycle = (
        isinstance(credit_score, (int, float)) and credit_score < 30
        and isinstance(rates_score, (int, float)) and rates_score > 60
    )

    # Determine lean
    if score >= 70:
        lean = "defensive"
    elif score >= 60:
        lean = "neutral-defensive"
    elif score >= 45:
        lean = "neutral"
    elif score >= 30:
        lean = "neutral-constructive"
    else:
        lean = "constructive"

    # Build the line — explain WHY this lean
    if all_broken:
        line = (
            f"All {total_eq} Fed→equity coupling channels are broken — rare regime. "
            f"Plumbing thesis won't drive equities this week; "
            f"historically snaps back hard when reserves cross $3.2T."
        )
        if score < 55:
            lean = "neutral"
    elif score >= 70:
        line = "Funding stress active. Reduce risk, watch for spillover into credit and vol."
    elif score >= 60:
        line = "Funding tightening. Defensive bias on plumbing — but coupling intact, so moves graduated."
    elif score >= 45:
        line = "Funding normal. Risk drivers elsewhere (earnings, fiscal, positioning)."
    else:
        line = "Funding flush. Liquidity supportive of risk — watch for complacency, not stress."

    if late_cycle:
        line += " Late-cycle backdrop (credit euphoric + curve flattening) — size down beta."

    return line, lean


# ─────────────────────────────────────────────────────────────────────────────
# Active signals + broken couplings
# ─────────────────────────────────────────────────────────────────────────────

def _collect_active_signals(corr_rep: dict) -> list[ActiveSignal]:
    """All tradeable leads from both plumbing and equity lead-lag."""
    sigs: list[ActiveSignal] = []
    for src in (corr_rep.get("lags") or [], corr_rep.get("equity_lags") or []):
        for l in src:
            if not l.get("tradeable"):
                continue
            sign = "+" if l["best_corr"] > 0 else "−"
            mag = abs(l["best_corr"])
            sigs.append(ActiveSignal(
                name=l["name"],
                detail=f"corr {sign}{mag:.2f}, {l['best_lag']}-day lead",
                tradeable=True,
            ))
    return sigs


def _collect_broken_couplings(corr_rep: dict, *, min_delta: float = 0.20) -> list[str]:
    """Surface broken/flipped equity couplings with meaningful baseline drift."""
    out: list[str] = []
    for p in corr_rep.get("equity_pairs") or []:
        if p.get("status") not in ("broken", "flipped"):
            continue
        cur, base = p.get("current"), p.get("baseline")
        if not isinstance(cur, (int, float)) or not isinstance(base, (int, float)):
            continue
        if abs(cur - base) < min_delta:
            continue
        out.append(f"{p['name']}: was {base:+.2f}, now {cur:+.2f}")
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Trade ideas — rule table mapping active signals → expressions
# ─────────────────────────────────────────────────────────────────────────────

def _build_trade_ideas(
    fi,
    regime,
    corr_rep: dict,
    cross_scores: dict | None,
    active: list[ActiveSignal],
    all_eq_broken: bool,
) -> list[TradeIdea]:
    """Deterministic mapping: active signals × plumbing state → trade expressions."""
    ideas: list[TradeIdea] = []
    active_names = {s.name for s in active}

    # SOFR-IORB → VIX tradeable → long vol expression
    if "SOFR-IORB → VIX" in active_names:
        ideas.append(TradeIdea(
            expression="Long MOVE or VIX call spread, funded by short 1-2m SPX put skew",
            rationale="SOFR-IORB → VIX active lead — funding stress reliably precedes vol expansion",
            conviction="high",
        ))

    # ΔWALCL → ΔSPX tradeable → directional bias on Fed BS pace
    if "ΔWALCL → ΔSPX" in active_names:
        # Direction depends on WALCL trend — read from fi if available
        fa_chg = getattr(fi, "fed_assets_chg_13w", None)
        if isinstance(fa_chg, (int, float)) and fa_chg < -20_000:
            ideas.append(TradeIdea(
                expression="WALCL drift bearish equities at 25-day horizon — fade strength in QQQ/SPX",
                rationale="ΔWALCL → ΔSPX active positive lead; balance sheet still shrinking",
                conviction="moderate",
            ))
        elif isinstance(fa_chg, (int, float)) and fa_chg > 20_000:
            ideas.append(TradeIdea(
                expression="WALCL drift constructive equities at 25-day horizon — buy dips in beta",
                rationale="ΔWALCL → ΔSPX active positive lead; balance sheet expanding",
                conviction="moderate",
            ))

    # ΔTGA → SOFR-IORB tradeable → position for corridor widening
    if "ΔTGA → SOFR-IORB" in active_names:
        ideas.append(TradeIdea(
            expression="Position for corridor widening into refunding settlements (short SOFR/FRA spreads)",
            rationale="ΔTGA → SOFR-IORB active lead — TGA buildup mechanically widens corridor",
            conviction="moderate",
        ))

    # Reserve scarcity setup → bank stress / Fed forced to ease
    reserves_t = (fi.bank_reserves_usd_bn or 0) / 1_000_000
    rrp_bn = (fi.on_rrp_usd_bn or 0) / 1000
    if reserves_t < 3.2 and rrp_bn < 100:
        ideas.append(TradeIdea(
            expression="Short KRE (regional banks) — reserve scarcity hits regionals first",
            rationale=f"Reserves ${reserves_t:.2f}T + RRP ${rrp_bn:.0f}B = scarcity zone, no buffer",
            conviction="high",
        ))
        ideas.append(TradeIdea(
            expression="Receive front-end (2y, 5y) — Fed forced to ease/halt QT if stress accelerates",
            rationale="Plumbing at LCLoR with no cushion left — historical Fed response is pivot",
            conviction="moderate",
        ))

    # All-coupling-broken regime → explicitly DO NOT chase equity beta on Fed thesis
    if all_eq_broken:
        ideas.append(TradeIdea(
            expression="DO NOT lean equity beta on Fed-liquidity thesis — channel is broken",
            rationale="All Fed→equity correlations decoupled; equities running on flow/earnings",
            conviction="high",
        ))

    # Late-cycle cross-regime → size discipline
    cs = cross_scores or {}
    credit_score = cs.get("credit", {}).get("score")
    rates_score = cs.get("rates", {}).get("score")
    if (isinstance(credit_score, (int, float)) and credit_score < 30
        and isinstance(rates_score, (int, float)) and rates_score > 60):
        ideas.append(TradeIdea(
            expression="Reduce gross — credit-euphoria + bear-flatten is late-cycle setup",
            rationale=f"Credit score {credit_score:.0f} (euphoric) + Rates {rates_score:.0f} (bear flatten)",
            conviction="moderate",
        ))

    return ideas


# ─────────────────────────────────────────────────────────────────────────────
# Context notes — small one-liners for the bottom of the brief
# ─────────────────────────────────────────────────────────────────────────────

def _build_context_notes(corr_rep: dict, cross_scores: dict | None) -> list[str]:
    notes: list[str] = []

    # Plumbing-correlation regime summary
    pregime = corr_rep.get("regime")
    rationale = corr_rep.get("rationale")
    if pregime and pregime != "BALANCED":
        notes.append(f"Plumbing correlation regime: {pregime} — {rationale}")

    # Calendar/cadence hint — TGA prints daily, refresh on Tuesday is meaningful
    notes.append("Next TGA print: tomorrow's DTS release (signals refunding flow)")

    return notes


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def build_funding_brief(
    fi,
    regime,
    corr_rep: dict,
    cross_scores: dict | None = None,
    nl_metrics: dict | None = None,
    offshore=None,  # OffshoreStress | None — avoid hard import for test ergonomics
) -> FundingBrief:
    """
    Build the 3-line synthesis brief from already-computed inputs.

    Inputs are not re-fetched; this is a pure rule engine over:
        - FundingInputs (levels)
        - FundingRegime (score, label)
        - correlation report (pairs, lags, equity_pairs, equity_lags)
        - cross-regime scores (credit, vol, rates, growth)
        - net liquidity metrics (level_t, delta_30d_b)
        - offshore stress composite (OffshoreStress; optional)
    """
    regime_line = _build_regime_line(fi, regime, corr_rep, nl_metrics)
    risk_line, lean = _build_risk_assessment(regime, corr_rep, cross_scores)

    active = _collect_active_signals(corr_rep)
    broken = _collect_broken_couplings(corr_rep)

    # Total broken-equity check for the "all broken" trade rule
    epairs = corr_rep.get("equity_pairs") or []
    broken_count = sum(1 for p in epairs if p.get("status") in ("broken", "flipped"))
    all_eq_broken = len(epairs) >= 3 and broken_count == len(epairs)

    ideas = _build_trade_ideas(fi, regime, corr_rep, cross_scores, active, all_eq_broken)
    notes = _build_context_notes(corr_rep, cross_scores)

    # Offshore USD stress — fold into the brief.
    offshore_label = None
    offshore_drivers: list[str] = []
    offshore_score = None
    if offshore is not None:
        offshore_score = getattr(offshore, "composite_score", 0.0)
        label = getattr(offshore, "composite_label", "calm")
        drivers = list(getattr(offshore, "drivers", []) or [])

        # Promote to ACTIVE signal when SWPT line is actually drawing — that's
        # the strongest single offshore stress reading we can get from FRED.
        if getattr(offshore, "swap_lines_active", False):
            swap_b = (offshore.swap_lines_usd_m or 0) / 1000.0
            active.insert(0, ActiveSignal(
                name="Fed swap lines drawing",
                detail=f"${swap_b:.1f}B active — offshore USD funding stress",
                tradeable=True,
            ))
            ideas.insert(0, TradeIdea(
                expression="Long DXY / short EM FX — offshore USD bid, Fed bailing out funding",
                rationale=f"SWPT ${swap_b:.1f}B active — historical pattern is sustained USD strength",
                conviction="high",
            ))

        # Stress / crisis level → show full block
        if offshore_score is not None and offshore_score >= 20:
            offshore_label = label
            offshore_drivers = drivers
            # Add USD-bid trade if broad dollar is bidding meaningfully
            broad_z = getattr(offshore, "broad_dollar_z", None)
            if isinstance(broad_z, (int, float)) and broad_z > 1.5 and not getattr(offshore, "swap_lines_active", False):
                ideas.append(TradeIdea(
                    expression="Long DXY call spread — broad-dollar momentum + offshore funding pressure",
                    rationale=f"Broad-$ Z {broad_z:+.1f}σ, offshore composite at {label} level",
                    conviction="moderate",
                ))
        else:
            # Calm offshore → single context line summarizing the state
            broad_z = getattr(offshore, "broad_dollar_z", None)
            swap_m = offshore.swap_lines_usd_m
            bits = []
            if isinstance(broad_z, (int, float)):
                bits.append(f"broad $ Z {broad_z:+.1f}σ")
            if isinstance(swap_m, (int, float)):
                bits.append(f"swap lines ${swap_m / 1000:.2f}B")
            if bits:
                notes.append(f"Offshore USD: calm ({', '.join(bits)})")

    return FundingBrief(
        regime_line=regime_line,
        risk_line=risk_line,
        risk_lean=lean,
        active_signals=active,
        broken_couplings=broken,
        trade_ideas=ideas,
        context_notes=notes,
        offshore_label=offshore_label,
        offshore_drivers=offshore_drivers,
        offshore_score=offshore_score,
    )
