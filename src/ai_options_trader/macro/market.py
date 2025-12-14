from __future__ import annotations

import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame


def fetch_equity_daily_closes(
    api_key: str,
    api_secret: str,
    symbols: list[str],
    start: str,
) -> pd.DataFrame:
    """
    Returns a dataframe indexed by date with columns = symbols, values = close.
    """
    client = StockHistoricalDataClient(api_key, api_secret)
    req = StockBarsRequest(
        symbol_or_symbols=symbols,
        timeframe=TimeFrame.Day,
        start=pd.Timestamp(start, tz="UTC"),
    )
    bars = client.get_stock_bars(req).df  # multiindex: (symbol, timestamp)

    if bars is None or len(bars) == 0:
        raise RuntimeError("No stock bars returned from Alpaca.")

    # bars index is typically MultiIndex: (symbol, timestamp)
    bars = bars.reset_index()
    bars["timestamp"] = pd.to_datetime(bars["timestamp"]).dt.tz_convert(None)
    bars["date"] = bars["timestamp"].dt.date
    pivot = bars.pivot_table(index="date", columns="symbol", values="close", aggfunc="last").sort_index()
    pivot.index = pd.to_datetime(pivot.index)
    return pivot
