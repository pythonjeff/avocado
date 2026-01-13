from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from ai_options_trader.config import Settings


def _to_f(x) -> float | None:
    try:
        if x is None:
            return None
        f = float(x)
        if f == f and f > 0:
            return f
    except Exception:
        return None
    return None


def fetch_stock_last_prices(
    *,
    settings: Settings,
    symbols: list[str],
    max_symbols_for_live: int = 10,
) -> tuple[dict[str, float], dict[str, str], str]:
    """
    Best-effort "current-ish" underlying prices for equities.

    Primary: latest trade endpoint (SDK-dependent).
    Fallback: last 1-minute bar close (last ~10 minutes).
    Final fallback: empty (caller can use daily close).

    Returns: (prices, asof, source)
    """
    syms = [s.strip().upper() for s in symbols if s and s.strip()]
    syms = list(dict.fromkeys(syms))  # stable unique
    if not syms:
        return {}, {}, "none"
    if len(syms) > int(max_symbols_for_live):
        return {}, {}, "skipped_many_symbols"

    # Lazy import so tests can import without alpaca installed.
    try:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.timeframe import TimeFrame
    except Exception:
        return {}, {}, "alpaca_sdk_missing"

    api_key = settings.alpaca_data_key or settings.alpaca_api_key
    api_secret = settings.alpaca_data_secret or settings.alpaca_api_secret
    client = StockHistoricalDataClient(api_key, api_secret)

    out: dict[str, float] = {}
    out_asof: dict[str, str] = {}

    # Attempt latest trade request first (SDK-dependent).
    try:
        from alpaca.data.requests import StockLatestTradeRequest

        try:
            req = StockLatestTradeRequest(symbol_or_symbols=syms)
            latest = client.get_stock_latest_trade(req)
        except TypeError:
            latest = client.get_stock_latest_trade(symbol_or_symbols=syms)

        if isinstance(latest, dict):
            for sym, trade in latest.items():
                px = getattr(trade, "price", None)
                ts = getattr(trade, "timestamp", None) or getattr(trade, "t", None)
                fpx = _to_f(px)
                if fpx is not None:
                    out[str(sym).upper()] = fpx
                    if ts is not None:
                        out_asof[str(sym).upper()] = str(ts)
    except Exception:
        pass

    missing = [s for s in syms if s.upper() not in out]
    if not missing:
        return out, out_asof, "latest_trade"

    # Fallback: last 1m bar close in the last ~10 minutes.
    try:
        from alpaca.data.requests import StockBarsRequest

        start = pd.Timestamp(datetime.now(timezone.utc) - timedelta(minutes=10))
        req = StockBarsRequest(symbol_or_symbols=[s.upper() for s in missing], timeframe=TimeFrame.Minute, start=start)
        bars = client.get_stock_bars(req).df
        if bars is not None and len(bars) > 0:
            b = bars.reset_index()
            for sym in missing:
                df_sym = b[b["symbol"].astype(str).str.upper() == sym.upper()]
                if df_sym.empty:
                    continue
                row = df_sym.sort_values("timestamp").iloc[-1]
                last_close = row.get("close")
                last_ts = row.get("timestamp")
                fpx = _to_f(last_close)
                if fpx is not None:
                    out[sym.upper()] = fpx
                    if last_ts is not None:
                        out_asof[sym.upper()] = str(last_ts)
    except Exception:
        pass

    return out, out_asof, ("bars_1m" if out else "none")

