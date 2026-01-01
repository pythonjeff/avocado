from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class CryptoQuantReturns(BaseModel):
    asset_3m: Optional[float] = None
    asset_6m: Optional[float] = None
    asset_12m: Optional[float] = None
    benchmark_3m: Optional[float] = None
    benchmark_6m: Optional[float] = None
    benchmark_12m: Optional[float] = None
    excess_12m: Optional[float] = None


class CryptoQuantTrend(BaseModel):
    above_200dma: Optional[bool] = None
    ma50_gt_ma200: Optional[bool] = None


class CryptoQuantVolatility(BaseModel):
    realized_vol_20d_ann: Optional[float] = None
    realized_vol_60d_ann: Optional[float] = None


class CryptoQuantSnapshot(BaseModel):
    asof: str
    symbol: str
    benchmark: Optional[str] = None
    regime: str  # "bullish" | "bearish" | "neutral"
    returns: CryptoQuantReturns
    trend: CryptoQuantTrend
    volatility: CryptoQuantVolatility


