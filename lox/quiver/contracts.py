"""
Government contracts reader.

Quiver's gov contracts export rolls federal contract awards (USAspending.gov)
keyed to public tickers. Yesterday's largest awards are the leading-edge view
since these post on T+1 from award date and can pre-announce revenue surprises.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

import pandas as pd

from lox.quiver.loader import load


@dataclass
class Contract:
    awarded: Optional[date]
    ticker: str
    agency: str
    amount_usd: float
    description: str


@dataclass
class TickerAggregate:
    ticker: str
    n_contracts: int
    total_usd: float
    agencies: list[str]


@dataclass
class ContractsReadout:
    have_data: bool
    asof: Optional[date]
    n_contracts_recent: int
    top_contracts: list[Contract]
    by_ticker: list[TickerAggregate]


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


def build_readout(window_days: int = 7, top_n: int = 12) -> ContractsReadout:
    df = load("contracts")
    if df is None:
        return ContractsReadout(False, None, 0, [], [])

    col_date = _pick(df, "date", "awarded", "award_date", "action_date")
    col_ticker = _pick(df, "ticker", "symbol")
    col_agency = _pick(df, "agency", "department", "awarding_agency")
    col_amount = _pick(df, "amount", "dollarsobligated", "obligated_amount", "value", "amount_usd")
    col_desc = _pick(df, "description", "transaction_description", "product")

    if col_ticker is None or col_amount is None:
        return ContractsReadout(False, None, 0, [], [])

    contracts: list[Contract] = []
    for _, row in df.iterrows():
        ticker = str(row.get(col_ticker, "")).strip().upper()
        if not ticker:
            continue
        contracts.append(
            Contract(
                awarded=_to_date(row.get(col_date)) if col_date else None,
                ticker=ticker,
                agency=str(row.get(col_agency, "")).strip() if col_agency else "",
                amount_usd=_to_float(row.get(col_amount)),
                description=str(row.get(col_desc, "")).strip()[:120] if col_desc else "",
            )
        )

    if not contracts:
        return ContractsReadout(False, None, 0, [], [])

    contracts.sort(key=lambda c: (c.awarded or date.min, c.amount_usd), reverse=True)
    asof = contracts[0].awarded

    cutoff = (asof or date.today()) - timedelta(days=window_days)
    recent = [c for c in contracts if c.awarded and c.awarded >= cutoff]

    top_contracts = sorted(recent, key=lambda c: c.amount_usd, reverse=True)[:top_n]

    # Per-ticker aggregation across the window
    by_ticker_map: dict[str, list[Contract]] = {}
    for c in recent:
        by_ticker_map.setdefault(c.ticker, []).append(c)
    aggregates = [
        TickerAggregate(
            ticker=t,
            n_contracts=len(cs),
            total_usd=sum(c.amount_usd for c in cs),
            agencies=sorted({c.agency for c in cs if c.agency})[:4],
        )
        for t, cs in by_ticker_map.items()
    ]
    aggregates.sort(key=lambda a: a.total_usd, reverse=True)

    return ContractsReadout(
        have_data=True,
        asof=asof,
        n_contracts_recent=len(recent),
        top_contracts=top_contracts,
        by_ticker=aggregates[:10],
    )
