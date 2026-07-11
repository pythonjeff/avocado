"""
Household equity allocation — % of household financial assets held in equities.

This is the indicator Buffett has cited as his single most predictive metric
(more than market cap / GDP).  Mechanically: when households are already
all-in on equities, marginal demand for stocks has nowhere to come from.

Numerator: `BOGZ1FL153064105Q` — Households and Nonprofit Organizations;
Corporate Equities; Asset, Level.  Quarterly Z.1 release, $ millions.

Denominator: `BOGZ1FL154090005Q` — Households and Nonprofit Organizations;
Total Financial Assets; Asset, Level.  Quarterly Z.1, $ millions.

Both series are quarterly (released ~75 days after quarter-end), so the
"asof" is whatever the latest Z.1 print covers.  We surface it explicitly on
the snapshot so the bubble panel can tell the user how fresh the reading is.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from lox.config import Settings
from lox.data.fred import FredClient


_EQUITY_SERIES = "BOGZ1FL153064105Q"     # HH corp equities, $M, quarterly
_FINASSETS_SERIES = "BOGZ1FL154090005Q"  # HH total financial assets, $M, quarterly


@dataclass
class HHEquitySnapshot:
    asof: Optional[str]                  # YYYY-MM-DD of latest Z.1 print
    equity_bn: Optional[float]           # HH corporate equities, $ billions
    total_finassets_bn: Optional[float]  # HH total financial assets, $ billions
    pct: Optional[float]                 # 100 * equity / total — the headline number


def fetch_hh_equity_share(*, settings: Settings, refresh: bool = False) -> HHEquitySnapshot:
    """
    Compute the household-equity-to-financial-assets percentage from Z.1.

    Returns an HHEquitySnapshot with all-None values on any fetch failure
    (no FRED key, network, missing series).  The bubble panel renders "—"
    when pct is None.
    """
    fred = FredClient(api_key=settings.FRED_API_KEY)

    try:
        eq = fred.fetch_series(_EQUITY_SERIES, start_date="1980-01-01", refresh=refresh)
    except Exception:
        eq = pd.DataFrame()

    try:
        fa = fred.fetch_series(_FINASSETS_SERIES, start_date="1980-01-01", refresh=refresh)
    except Exception:
        fa = pd.DataFrame()

    if eq.empty or fa.empty:
        return HHEquitySnapshot(asof=None, equity_bn=None, total_finassets_bn=None, pct=None)

    # Both series are quarterly; align on date intersection so we never divide
    # values from different reporting dates.
    eq_s = eq.set_index("date")["value"].sort_index() / 1000.0     # $M → $B
    fa_s = fa.set_index("date")["value"].sort_index() / 1000.0

    aligned = pd.DataFrame({"eq": eq_s, "fa": fa_s}).dropna()
    if aligned.empty:
        return HHEquitySnapshot(asof=None, equity_bn=None, total_finassets_bn=None, pct=None)

    aligned["pct"] = 100.0 * aligned["eq"] / aligned["fa"]

    last = aligned.iloc[-1]
    return HHEquitySnapshot(
        asof=str(aligned.index[-1].date()),
        equity_bn=float(last["eq"]),
        total_finassets_bn=float(last["fa"]),
        pct=float(last["pct"]),
    )
