"""
Flow bundle reader — three retail/dark-pool surfaces:

  - insider: open-market Form 4 buys, cluster buys are the high-signal cut
  - wsb: r/WallStreetBets ticker mentions with day-over-day delta
  - otc_short: off-exchange short-volume share spikes

These three are bundled because the v0 brief blends them into a single
"flow regime" — when insider buying, WSB attention, and OTC shorting all
converge on the same name, that's the readout the brief surfaces.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

import pandas as pd

from lox.quiver.loader import load


# ─────────────────────────────────────────────────────────────────────────────
# Insider buys
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class InsiderBuy:
    filed: Optional[date]
    ticker: str
    insider: str
    title: str
    shares: float
    price: float
    value_usd: float


@dataclass
class InsiderCluster:
    ticker: str
    n_buyers: int
    total_value_usd: float
    insiders: list[str]


@dataclass
class InsiderReadout:
    have_data: bool
    asof: Optional[date]
    top_buys: list[InsiderBuy]
    clusters: list[InsiderCluster]


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


def _to_float(x) -> float:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return 0.0
    try:
        return float(str(x).replace(",", "").replace("$", ""))
    except (TypeError, ValueError):
        return 0.0


def build_insider_readout(window_days: int = 7, top_n: int = 10) -> InsiderReadout:
    df = load("insider")
    if df is None:
        return InsiderReadout(False, None, [], [])

    col_date = _pick(df, "filed", "filing_date", "date", "transaction_date")
    col_ticker = _pick(df, "ticker", "symbol")
    col_insider = _pick(df, "insider", "name", "reporting_name")
    col_title = _pick(df, "title", "position", "relationship")
    col_shares = _pick(df, "shares", "shares_traded", "amount")
    col_price = _pick(df, "price", "share_price")
    col_value = _pick(df, "value", "transaction_value", "value_usd", "transaction_amount")
    col_side = _pick(df, "transaction", "side", "type", "transaction_type", "acquired_disposed")

    if col_ticker is None or col_insider is None:
        return InsiderReadout(False, None, [], [])

    buys: list[InsiderBuy] = []
    for _, row in df.iterrows():
        # Only count open-market buys when a side column exists
        if col_side is not None:
            side = str(row.get(col_side, "")).lower()
            if not ("buy" in side or "purchase" in side or side.strip() == "a"):
                continue
        ticker = str(row.get(col_ticker, "")).strip().upper()
        insider = str(row.get(col_insider, "")).strip()
        if not ticker or not insider:
            continue
        shares = _to_float(row.get(col_shares)) if col_shares else 0.0
        price = _to_float(row.get(col_price)) if col_price else 0.0
        value = _to_float(row.get(col_value)) if col_value else (shares * price)
        buys.append(
            InsiderBuy(
                filed=_to_date(row.get(col_date)) if col_date else None,
                ticker=ticker,
                insider=insider,
                title=str(row.get(col_title, "")).strip()[:40] if col_title else "",
                shares=shares,
                price=price,
                value_usd=value,
            )
        )

    if not buys:
        return InsiderReadout(False, None, [], [])

    buys.sort(key=lambda b: (b.filed or date.min, b.value_usd), reverse=True)
    asof = buys[0].filed

    cutoff = (asof or date.today()) - timedelta(days=window_days)
    recent = [b for b in buys if b.filed and b.filed >= cutoff]

    top_buys = sorted(recent, key=lambda b: b.value_usd, reverse=True)[:top_n]

    cluster_map: dict[str, list[InsiderBuy]] = {}
    for b in recent:
        cluster_map.setdefault(b.ticker, []).append(b)
    clusters = []
    for t, bs in cluster_map.items():
        insiders = sorted({b.insider for b in bs})
        if len(insiders) >= 2:
            clusters.append(
                InsiderCluster(
                    ticker=t,
                    n_buyers=len(insiders),
                    total_value_usd=sum(b.value_usd for b in bs),
                    insiders=insiders,
                )
            )
    clusters.sort(key=lambda c: (c.n_buyers, c.total_value_usd), reverse=True)

    return InsiderReadout(
        have_data=True,
        asof=asof,
        top_buys=top_buys,
        clusters=clusters[:8],
    )


# ─────────────────────────────────────────────────────────────────────────────
# WSB mentions
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class WsbRow:
    asof: Optional[date]
    ticker: str
    mentions: float
    sentiment: float


@dataclass
class WsbDelta:
    ticker: str
    mentions_today: float
    mentions_prev: float
    delta_pct: float
    sentiment: float


@dataclass
class WsbReadout:
    have_data: bool
    asof: Optional[date]
    top_movers: list[WsbDelta]


def build_wsb_readout(top_n: int = 10) -> WsbReadout:
    df = load("wsb")
    if df is None:
        return WsbReadout(False, None, [])

    col_date = _pick(df, "date", "asof", "day")
    col_ticker = _pick(df, "ticker", "symbol")
    col_mentions = _pick(df, "mentions", "count", "n_mentions")
    col_sentiment = _pick(df, "sentiment", "score")

    if col_ticker is None or col_mentions is None:
        return WsbReadout(False, None, [])

    rows: list[WsbRow] = []
    for _, row in df.iterrows():
        ticker = str(row.get(col_ticker, "")).strip().upper()
        if not ticker:
            continue
        rows.append(
            WsbRow(
                asof=_to_date(row.get(col_date)) if col_date else None,
                ticker=ticker,
                mentions=_to_float(row.get(col_mentions)),
                sentiment=_to_float(row.get(col_sentiment)) if col_sentiment else 0.0,
            )
        )

    if not rows:
        return WsbReadout(False, None, [])

    rows.sort(key=lambda r: r.asof or date.min, reverse=True)
    asof = rows[0].asof

    today_rows = [r for r in rows if r.asof == asof]
    # Previous-day baseline: the next distinct date
    prior_dates = sorted({r.asof for r in rows if r.asof and r.asof != asof}, reverse=True)
    prev_date = prior_dates[0] if prior_dates else None
    prev_map = {r.ticker: r.mentions for r in rows if r.asof == prev_date} if prev_date else {}

    deltas: list[WsbDelta] = []
    for r in today_rows:
        prev = prev_map.get(r.ticker, 0.0)
        if r.mentions < 5:  # ignore noise
            continue
        delta_pct = ((r.mentions - prev) / prev * 100.0) if prev > 0 else (float("inf") if r.mentions > 0 else 0.0)
        deltas.append(
            WsbDelta(
                ticker=r.ticker,
                mentions_today=r.mentions,
                mentions_prev=prev,
                delta_pct=delta_pct,
                sentiment=r.sentiment,
            )
        )

    deltas.sort(key=lambda d: (d.delta_pct if d.delta_pct != float("inf") else 1e9, d.mentions_today), reverse=True)

    return WsbReadout(
        have_data=True,
        asof=asof,
        top_movers=deltas[:top_n],
    )


# ─────────────────────────────────────────────────────────────────────────────
# Off-exchange short volume
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class OtcShortRow:
    asof: Optional[date]
    ticker: str
    short_volume: float
    total_volume: float
    short_share: float


@dataclass
class OtcShortReadout:
    have_data: bool
    asof: Optional[date]
    spikes: list[OtcShortRow]  # rows with the highest short-share that day


def build_otc_short_readout(top_n: int = 10, min_volume: float = 500_000) -> OtcShortReadout:
    df = load("otc_short")
    if df is None:
        return OtcShortReadout(False, None, [])

    col_date = _pick(df, "date", "asof", "day")
    col_ticker = _pick(df, "ticker", "symbol")
    col_short = _pick(df, "short_volume", "shortvolume", "shorts")
    col_total = _pick(df, "total_volume", "totalvolume", "volume")
    col_share = _pick(df, "short_share", "short_ratio", "share_short")

    if col_ticker is None or (col_short is None and col_share is None):
        return OtcShortReadout(False, None, [])

    rows: list[OtcShortRow] = []
    for _, row in df.iterrows():
        ticker = str(row.get(col_ticker, "")).strip().upper()
        if not ticker:
            continue
        short = _to_float(row.get(col_short)) if col_short else 0.0
        total = _to_float(row.get(col_total)) if col_total else 0.0
        share = _to_float(row.get(col_share)) if col_share else (short / total if total > 0 else 0.0)
        if total > 0 and total < min_volume:
            continue
        rows.append(
            OtcShortRow(
                asof=_to_date(row.get(col_date)) if col_date else None,
                ticker=ticker,
                short_volume=short,
                total_volume=total,
                short_share=share,
            )
        )

    if not rows:
        return OtcShortReadout(False, None, [])

    rows.sort(key=lambda r: r.asof or date.min, reverse=True)
    asof = rows[0].asof
    same_day = [r for r in rows if r.asof == asof]
    same_day.sort(key=lambda r: r.short_share, reverse=True)

    return OtcShortReadout(
        have_data=True,
        asof=asof,
        spikes=same_day[:top_n],
    )
