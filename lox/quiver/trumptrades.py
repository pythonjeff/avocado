"""
Trump stock trades reader.

Reads from the Quiver /bulk/trumpstocktrades endpoint. Fields:
  Ticker, Company, Transaction, Amount (bucket), Filed, Traded, ExcessReturn
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

import pandas as pd

from lox.quiver.congress import _parse_amount_mid, _classify_side, _to_date


@dataclass
class TrumpTrade:
    filed: Optional[date]
    traded: Optional[date]
    ticker: Optional[str]
    company: str
    side: str
    amount_mid_usd: float
    raw_amount: str
    excess_return: Optional[float]


@dataclass
class TickerSummary:
    ticker: str
    company: str
    n_trades: int
    total_mid_usd: float
    last_side: str
    last_traded: Optional[date]
    avg_excess_return: Optional[float]


@dataclass
class TrumpReadout:
    have_data: bool
    asof: Optional[date]
    trades: list[TrumpTrade]
    by_ticker: list[TickerSummary]


def build_readout(df: pd.DataFrame, top_n: int = 30) -> TrumpReadout:
    if df is None or df.empty:
        return TrumpReadout(False, None, [], [])

    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]

    trades: list[TrumpTrade] = []
    for _, row in df.iterrows():
        ticker_raw = row.get("ticker")
        ticker = str(ticker_raw).strip().upper() if ticker_raw and str(ticker_raw) not in ("nan", "None", "") else None
        company = str(row.get("company", "")).strip()
        raw_amount = str(row.get("amount", ""))
        er_raw = row.get("excessreturn")
        try:
            excess_return = float(er_raw) if er_raw is not None and str(er_raw) not in ("nan", "None") else None
        except (ValueError, TypeError):
            excess_return = None

        trades.append(TrumpTrade(
            filed=_to_date(row.get("filed")),
            traded=_to_date(row.get("traded")),
            ticker=ticker,
            company=company,
            side=_classify_side(row.get("transaction")),
            amount_mid_usd=_parse_amount_mid(row.get("amount")),
            raw_amount=raw_amount,
            excess_return=excess_return,
        ))

    trades.sort(key=lambda t: (t.traded or date.min, t.amount_mid_usd), reverse=True)
    asof = next((t.traded for t in trades if t.traded), None)

    # Aggregate by ticker (skip null-ticker rows for the summary)
    by_ticker_map: dict[str, list[TrumpTrade]] = {}
    for t in trades:
        key = t.ticker or f"_{t.company[:20]}"
        by_ticker_map.setdefault(key, []).append(t)

    summaries: list[TickerSummary] = []
    for key, ts in by_ticker_map.items():
        er_vals = [t.excess_return for t in ts if t.excess_return is not None]
        summaries.append(TickerSummary(
            ticker=ts[0].ticker or "—",
            company=ts[0].company,
            n_trades=len(ts),
            total_mid_usd=sum(t.amount_mid_usd for t in ts),
            last_side=ts[0].side,
            last_traded=ts[0].traded,
            avg_excess_return=sum(er_vals) / len(er_vals) if er_vals else None,
        ))
    summaries.sort(key=lambda s: s.total_mid_usd, reverse=True)

    return TrumpReadout(
        have_data=True,
        asof=asof,
        trades=trades[:top_n],
        by_ticker=summaries[:20],
    )
