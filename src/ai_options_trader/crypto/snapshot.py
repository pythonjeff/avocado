from __future__ import annotations

from typing import Any

import pandas as pd


def build_crypto_quant_snapshot(
    *,
    prices: pd.DataFrame,
    symbol: str,
    benchmark: str | None = None,
) -> dict[str, Any]:
    """
    Build a simple quantitative snapshot for a crypto pair from daily closes.

    Expects `prices` indexed by date with columns including `symbol` and optionally `benchmark`.
    Symbols should match Alpaca pair symbols, e.g. "BTC/USD".
    """
    s = symbol.upper()
    b = benchmark.upper() if benchmark else None

    if s not in prices.columns:
        raise ValueError(f"Missing {s} in price dataframe columns: {list(prices.columns)}")
    cols = [s] + ([b] if b else [])

    px = prices[cols].dropna(how="any").sort_index()
    if len(px) < 260:
        raise ValueError("Not enough history for a 12m snapshot (need ~260 trading days).")

    ret = px.pct_change().dropna()

    def trailing_return(col: str, days: int) -> float | None:
        if len(px) <= days:
            return None
        start = float(px[col].iloc[-days - 1])
        end = float(px[col].iloc[-1])
        if start <= 0:
            return None
        return (end / start - 1.0) * 100.0

    # Approx trading days
    r_3m = trailing_return(s, 63)
    r_6m = trailing_return(s, 126)
    r_12m = trailing_return(s, 252)

    br_3m = trailing_return(b, 63) if b else None
    br_6m = trailing_return(b, 126) if b else None
    br_12m = trailing_return(b, 252) if b else None

    # Trend + moving averages
    ma_50 = px[s].rolling(50).mean()
    ma_200 = px[s].rolling(200).mean()
    above_200 = bool(px[s].iloc[-1] > ma_200.iloc[-1]) if pd.notna(ma_200.iloc[-1]) else None
    cross_50_200 = (
        bool(ma_50.iloc[-1] > ma_200.iloc[-1]) if pd.notna(ma_50.iloc[-1]) and pd.notna(ma_200.iloc[-1]) else None
    )

    # Realized vol (annualized). Crypto trades 24/7, but we still use 252 as a pragmatic convention for now.
    vol_20 = ret[s].rolling(20).std(ddof=0).iloc[-1] * (252**0.5)
    vol_60 = ret[s].rolling(60).std(ddof=0).iloc[-1] * (252**0.5)

    # Relative strength vs benchmark (12m excess return)
    rel_12m = None
    if r_12m is not None and br_12m is not None:
        rel_12m = r_12m - br_12m

    # Simple "asset regime" label
    regime = "neutral"
    if above_200 is True and (r_6m is not None and r_6m > 0):
        regime = "bullish"
    elif above_200 is False and (r_6m is not None and r_6m < 0):
        regime = "bearish"

    return {
        "asof": str(px.index[-1].date()),
        "symbol": s,
        "benchmark": b,
        "regime": regime,
        "returns": {
            "asset_3m": r_3m,
            "asset_6m": r_6m,
            "asset_12m": r_12m,
            "benchmark_3m": br_3m,
            "benchmark_6m": br_6m,
            "benchmark_12m": br_12m,
            "excess_12m": rel_12m,
        },
        "trend": {
            "above_200dma": above_200,
            "ma50_gt_ma200": cross_50_200,
        },
        "volatility": {
            "realized_vol_20d_ann": float(vol_20) if pd.notna(vol_20) else None,
            "realized_vol_60d_ann": float(vol_60) if pd.notna(vol_60) else None,
        },
    }


