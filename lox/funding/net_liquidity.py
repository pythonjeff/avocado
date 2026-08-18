"""
Net liquidity composite: Fed balance sheet − TGA − ON RRP.

The Howell/Bianco definition — WALCL minus TGA minus ON RRP — not bank
reserves (WRESBAL) minus TGA minus RRP. Reserves already net out most of
TGA/RRP's balance-sheet impact (WRESBAL = WALCL − TGA − RRP − currency −
other Fed liabilities, roughly), so "reserves − TGA − RRP" double-subtracts
those two legs and produces a series that: (a) reads ~$4T below the commonly
quoted net-liquidity level, and (b) has ~zero historical correlation to the
standard WALCL-based series it's meant to approximate. Use WALCL here so this
composite is the same "net liquidity" figure the Howell/Bianco literature
(and lox.funding.correlations' equity-transmission pairs) refers to.

Lives in the funding regime because two of three legs (Fed balance sheet,
RRP) are Fed balance-sheet primitives. TGA is imported from lox.gov.dts since
the Treasury General Account is a fiscal-authority lever — the dependency
runs one-way (funding ← gov), mirroring the Fed/Treasury institutional
separation.

Pure ΔTGA in isolation can be noisy. The net-liquidity series captures the
*net* reserve impact of all three plumbing flows:

    rising TGA      → reserves drain (bearish liquidity)
    rising ON RRP   → reserves drain (bearish liquidity)
    rising WALCL    → reserves add (bullish liquidity)

Sources:
    TGA     — DTS daily (lox.gov.dts.fetch_tga_daily) in $B
    ON RRP  — FRED RRPONTSYD, daily, $B
    WALCL   — FRED WALCL, weekly (Wed close), $M (we convert to $B)

The series are aligned on a daily business-day index; weekly WALCL is
forward-filled to the latest TGA/RRP date so the composite isn't gated by
the slowest series.

Public API:
    fetch_net_liquidity_components(refresh=False) -> pd.DataFrame
        columns: date, tga_b, rrp_b, walcl_b, net_liq_t

    compute_net_liquidity_metrics(refresh=False) -> dict
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from lox.config import load_settings
from lox.data.fred import FredClient
from lox.gov.dts import fetch_tga_daily


_RRP_SERIES = "RRPONTSYD"  # daily, billions of $
_WALCL_SERIES = "WALCL"    # weekly, millions of $


def fetch_net_liquidity_components(
    *,
    refresh: bool = False,
    start_date: str = "2018-01-01",
) -> pd.DataFrame:
    """
    Daily-aligned series of (TGA, RRP, WALCL) and net liquidity in $T.

    Returns empty DataFrame if any source fetch fails outright; the gov panel
    code degrades gracefully on empty.
    """
    settings = load_settings()
    if not settings.FRED_API_KEY:
        return pd.DataFrame(columns=["date", "tga_b", "rrp_b", "walcl_b", "net_liq_t"])

    fred = FredClient(api_key=settings.FRED_API_KEY)

    try:
        tga = fetch_tga_daily(refresh=refresh, lookback_days=400)
    except Exception:
        tga = pd.DataFrame(columns=["date", "tga_close_b"])

    try:
        rrp = fred.fetch_series(series_id=_RRP_SERIES, start_date=start_date, refresh=refresh)
    except Exception:
        rrp = pd.DataFrame(columns=["date", "value"])

    try:
        walcl = fred.fetch_series(series_id=_WALCL_SERIES, start_date=start_date, refresh=refresh)
    except Exception:
        walcl = pd.DataFrame(columns=["date", "value"])

    if tga.empty and rrp.empty and walcl.empty:
        return pd.DataFrame(columns=["date", "tga_b", "rrp_b", "walcl_b", "net_liq_t"])

    frames = []
    if not tga.empty:
        t = tga.copy()
        t["date"] = pd.to_datetime(t["date"])
        frames.append(t.rename(columns={"tga_close_b": "tga_b"})[["date", "tga_b"]])
    if not rrp.empty:
        r = rrp.copy()
        r["date"] = pd.to_datetime(r["date"])
        frames.append(r.rename(columns={"value": "rrp_b"})[["date", "rrp_b"]])
    if not walcl.empty:
        w = walcl.copy()
        w["date"] = pd.to_datetime(w["date"])
        w["walcl_b"] = pd.to_numeric(w["value"], errors="coerce") / 1000.0
        frames.append(w[["date", "walcl_b"]])

    merged = frames[0]
    for f in frames[1:]:
        merged = merged.merge(f, on="date", how="outer")
    merged = merged.sort_values("date").reset_index(drop=True)

    # Build a business-day index spanning the union, forward-fill weekly
    # WALCL so the composite isn't lagged by it. Don't ffill TGA/RRP
    # past their last observation — if today is Saturday and TGA last printed
    # Friday, we want today's row dropped, not stale.
    bidx = pd.bdate_range(start=merged["date"].min(), end=merged["date"].max())
    merged = merged.set_index("date").reindex(bidx)
    merged.index.name = "date"

    if "walcl_b" in merged.columns:
        merged["walcl_b"] = merged["walcl_b"].ffill()

    merged = merged.dropna(subset=["tga_b", "rrp_b", "walcl_b"])
    if merged.empty:
        return pd.DataFrame(columns=["date", "tga_b", "rrp_b", "walcl_b", "net_liq_t"])

    merged["net_liq_t"] = (merged["walcl_b"] - merged["tga_b"] - merged["rrp_b"]) / 1000.0
    out = merged.reset_index()
    out["date"] = out["date"].dt.date
    return out[["date", "tga_b", "rrp_b", "walcl_b", "net_liq_t"]]


def compute_net_liquidity_metrics(*, refresh: bool = False) -> dict:
    """
    Net-liquidity composite metrics for the gov panel.

    Deltas are reported in $B (more legible at panel scale than $T). The level
    is in $T because it sits in the $5T range.
    """
    empty = {
        "asof": None,
        "level_t": None,
        "delta_1d_b": None,
        "delta_5d_b": None,
        "delta_30d_b": None,
        "components_b": None,
    }
    try:
        df = fetch_net_liquidity_components(refresh=refresh)
    except Exception:
        return empty

    if df.empty:
        return empty

    last = df.iloc[-1]
    level_t = float(last["net_liq_t"])

    def _delta_b(n: int) -> Optional[float]:
        if len(df) <= n:
            return None
        prior_t = float(df.iloc[-1 - n]["net_liq_t"])
        return (level_t - prior_t) * 1000.0  # $T → $B

    series_30d_t = [float(v) for v in df["net_liq_t"].tail(30).tolist()]

    return {
        "asof": str(last["date"]),
        "level_t": level_t,
        "delta_1d_b": _delta_b(1),
        "delta_5d_b": _delta_b(5),
        "delta_30d_b": _delta_b(21),  # ~1 trading month
        "series_30d_t": series_30d_t,
        "components_b": {
            "tga_b": float(last["tga_b"]),
            "rrp_b": float(last["rrp_b"]),
            "walcl_b": float(last["walcl_b"]),
        },
    }
