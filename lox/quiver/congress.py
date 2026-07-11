"""
Congressional trading reader.

Quiver exports of congressional Periodic Transaction Reports (PTRs) vary in
column naming. This module normalizes the common shapes (House Stock Watcher,
Senate Stock Watcher, Quiver-unified) and produces three readouts:

  - recent: yesterday + last N days of disclosures, ranked by size
  - cluster_buys: same ticker bought by 2+ distinct lawmakers in a window
  - top_buyers: lawmakers most active in the window (for tracking habitual flow)

PTR sizes on the disclosure form are buckets ("$1,001 - $15,000" etc.). We
estimate the midpoint of the bucket when ranking. That's noisy but it's what
every PTR-tracker does because the actual amount isn't disclosed.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

import pandas as pd

from lox.quiver.loader import load


# ─────────────────────────────────────────────────────────────────────────────
# Dataclasses surfaced to the CLI
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CongressTrade:
    traded: Optional[date]
    disclosed: Optional[date]
    lawmaker: str
    chamber: str           # "House" | "Senate" | ""
    party: str             # "D" | "R" | "I" | ""
    ticker: str
    side: str              # "Buy" | "Sell" | "Exchange" | ""
    amount_mid_usd: float  # midpoint estimate of the disclosed range
    raw_amount: str        # original bucket label for display


@dataclass
class ClusterBuy:
    ticker: str
    buyer_count: int
    total_mid_usd: float
    lawmakers: list[str]


@dataclass
class TopBuyer:
    lawmaker: str
    chamber: str
    n_trades: int
    total_mid_usd: float


@dataclass
class CongressReadout:
    have_data: bool
    asof: Optional[date]
    n_trades_recent: int
    recent: list[CongressTrade]
    cluster_buys: list[ClusterBuy]
    top_buyers: list[TopBuyer]


# ─────────────────────────────────────────────────────────────────────────────
# Amount bucket parsing
# ─────────────────────────────────────────────────────────────────────────────

# PTR amount ranges roughly follow these brackets. Map to midpoints (USD).
_AMOUNT_MIDPOINTS: dict[str, float] = {
    "$1,001 - $15,000": 8_000,
    "$15,001 - $50,000": 32_500,
    "$15,000 - $50,000": 32_500,
    "$50,001 - $100,000": 75_000,
    "$100,001 - $250,000": 175_000,
    "$250,001 - $500,000": 375_000,
    "$500,001 - $1,000,000": 750_000,
    "$1,000,001 - $5,000,000": 3_000_000,
    "$5,000,001 - $25,000,000": 15_000_000,
    "$25,000,001 - $50,000,000": 37_500_000,
    "$50,000,001 -": 75_000_000,
}


def _parse_amount_mid(raw: object) -> float:
    """Best-effort midpoint of a Quiver amount bucket."""
    if raw is None:
        return 0.0
    s = str(raw).strip()
    if not s or s.lower() in ("nan", "none"):
        return 0.0
    # Direct hit on a known bucket
    if s in _AMOUNT_MIDPOINTS:
        return _AMOUNT_MIDPOINTS[s]
    # Numeric column case (some exports give an actual dollar number)
    try:
        v = float(s.replace(",", "").replace("$", ""))
        if v > 0:
            return v
    except ValueError:
        pass
    # Generic "$X - $Y" → midpoint
    if "-" in s:
        parts = [p.strip().lstrip("$").replace(",", "") for p in s.split("-")]
        try:
            lo = float(parts[0]) if parts[0] else 0.0
            hi = float(parts[1]) if len(parts) > 1 and parts[1] else lo
            if hi <= 0:
                return lo
            return (lo + hi) / 2.0
        except ValueError:
            return 0.0
    return 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Column resolution
# ─────────────────────────────────────────────────────────────────────────────

def _pick(df: pd.DataFrame, *candidates: str) -> Optional[str]:
    for c in candidates:
        if c in df.columns:
            return c
    return None


def _to_date(x) -> Optional[date]:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return None
    try:
        return pd.to_datetime(x, errors="coerce").date()
    except Exception:
        return None


def _infer_chamber(lawmaker: str, raw_chamber: str) -> str:
    if raw_chamber:
        rc = raw_chamber.lower()
        if "house" in rc or rc.startswith("rep"):
            return "House"
        if "sen" in rc:
            return "Senate"
    return ""


def _classify_side(raw: object) -> str:
    if raw is None:
        return ""
    s = str(raw).strip().lower()
    if not s:
        return ""
    if "purchase" in s or s == "buy" or "acquisition" in s:
        return "Buy"
    if "sale" in s or s == "sell" or "disposition" in s:
        return "Sell"
    if "exchange" in s:
        return "Exchange"
    return s.title()


# ─────────────────────────────────────────────────────────────────────────────
# Main entry
# ─────────────────────────────────────────────────────────────────────────────

def build_readout(
    window_days: int = 7,
    top_n: int = 12,
    df: Optional[pd.DataFrame] = None,
) -> CongressReadout:
    """Build the congress panel readout from a DataFrame or the cached CSV."""
    if df is None:
        df = load("congress")
    if df is None:
        return CongressReadout(False, None, 0, [], [], [])

    col_law = _pick(df, "representative", "senator", "lawmaker", "name", "member")
    col_ticker = _pick(df, "ticker", "symbol")
    col_side = _pick(df, "transaction", "type", "transaction_type", "side")
    col_amount = _pick(df, "amount", "range", "trade_size_usd", "transaction_amount")
    col_bucket = _pick(df, "range") or col_amount  # API has "range" for label, "amount" for numeric
    col_traded = _pick(df, "traded", "transaction_date", "transactiondate", "date")
    col_disclosed = _pick(df, "disclosed", "filing_date", "report_date", "reportdate", "disclosure_date", "date")
    col_chamber = _pick(df, "chamber", "house")
    col_party = _pick(df, "party")

    if col_law is None or col_ticker is None:
        # Schema we don't recognize — bail with a have_data=False so the
        # CLI shows the "check the CSV" guide.
        return CongressReadout(False, None, 0, [], [], [])

    # Build CongressTrade rows
    trades: list[CongressTrade] = []
    for _, row in df.iterrows():
        traded = _to_date(row.get(col_traded)) if col_traded else None
        disclosed = _to_date(row.get(col_disclosed)) if col_disclosed else None
        raw_amount = str(row.get(col_bucket, "")) if col_bucket else ""
        raw_chamber = str(row.get(col_chamber, "")) if col_chamber else ""
        lawmaker = str(row.get(col_law, "")).strip()
        ticker = str(row.get(col_ticker, "")).strip().upper()
        if not lawmaker or not ticker:
            continue
        trades.append(
            CongressTrade(
                traded=traded,
                disclosed=disclosed,
                lawmaker=lawmaker,
                chamber=_infer_chamber(lawmaker, raw_chamber),
                party=str(row.get(col_party, "")).strip()[:1] if col_party else "",
                ticker=ticker,
                side=_classify_side(row.get(col_side)) if col_side else "",
                amount_mid_usd=_parse_amount_mid(row.get(col_amount)) if col_amount else 0.0,
                raw_amount=raw_amount,
            )
        )

    if not trades:
        return CongressReadout(False, None, 0, [], [], [])

    # Sort by disclosed date desc (with traded as tiebreaker) to find recency
    def _sort_key(t: CongressTrade) -> tuple:
        return (
            t.disclosed or date.min,
            t.traded or date.min,
            t.amount_mid_usd,
        )

    trades.sort(key=_sort_key, reverse=True)
    asof = trades[0].disclosed or trades[0].traded

    # Recent window
    cutoff = (asof or date.today()) - timedelta(days=window_days)
    recent_window = [
        t for t in trades
        if (t.disclosed and t.disclosed >= cutoff) or (t.traded and t.traded >= cutoff)
    ]

    # Top N recent disclosures by amount
    recent_sorted = sorted(recent_window, key=lambda t: t.amount_mid_usd, reverse=True)[:top_n]

    # Cluster buys — same ticker bought by 2+ distinct lawmakers in window
    buys = [t for t in recent_window if t.side == "Buy"]
    by_ticker: dict[str, list[CongressTrade]] = {}
    for t in buys:
        by_ticker.setdefault(t.ticker, []).append(t)
    clusters: list[ClusterBuy] = []
    for ticker, ts in by_ticker.items():
        lawmakers = sorted({t.lawmaker for t in ts})
        if len(lawmakers) >= 2:
            clusters.append(
                ClusterBuy(
                    ticker=ticker,
                    buyer_count=len(lawmakers),
                    total_mid_usd=sum(t.amount_mid_usd for t in ts),
                    lawmakers=lawmakers,
                )
            )
    clusters.sort(key=lambda c: (c.buyer_count, c.total_mid_usd), reverse=True)

    # Top buyers in window
    by_law: dict[tuple[str, str], list[CongressTrade]] = {}
    for t in recent_window:
        by_law.setdefault((t.lawmaker, t.chamber), []).append(t)
    top_buyers = [
        TopBuyer(
            lawmaker=law,
            chamber=cham,
            n_trades=len(ts),
            total_mid_usd=sum(t.amount_mid_usd for t in ts),
        )
        for (law, cham), ts in by_law.items()
    ]
    top_buyers.sort(key=lambda b: b.total_mid_usd, reverse=True)
    top_buyers = top_buyers[:8]

    return CongressReadout(
        have_data=True,
        asof=asof,
        n_trades_recent=len(recent_window),
        recent=recent_sorted,
        cluster_buys=clusters[:8],
        top_buyers=top_buyers,
    )
