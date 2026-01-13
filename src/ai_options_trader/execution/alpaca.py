from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import LimitOrderRequest, MarketOrderRequest


@dataclass(frozen=True)
class OrderPreview:
    symbol: str
    qty: int
    side: str  # "buy"|"sell"
    order_type: str  # "market"|"limit"
    limit_price: Optional[float] = None
    tif: str = "day"


@dataclass(frozen=True)
class CryptoOrderPreview:
    symbol: str
    side: str  # "buy"|"sell"
    order_type: str  # "market"|"limit"
    notional: Optional[float] = None
    qty: Optional[float] = None
    limit_price: Optional[float] = None
    tif: str = "day"


def submit_option_order(
    *,
    trading: TradingClient,
    symbol: str,
    qty: int,
    side: str,
    limit_price: float | None = None,
    tif: str = "day",
):
    """
    Submit an options order to Alpaca.

    Note: For safety, call this only after explicit user confirmation.
    """
    side_enum = OrderSide.BUY if side.lower().startswith("b") else OrderSide.SELL
    tif_enum = TimeInForce.DAY if tif.lower() == "day" else TimeInForce.GTC

    if limit_price is None:
        req = MarketOrderRequest(symbol=symbol, qty=qty, side=side_enum, time_in_force=tif_enum)
    else:
        req = LimitOrderRequest(
            symbol=symbol,
            qty=qty,
            side=side_enum,
            time_in_force=tif_enum,
            limit_price=round(float(limit_price), 2),
        )

    return trading.submit_order(order_data=req)


def submit_equity_order(
    *,
    trading: TradingClient,
    symbol: str,
    qty: int,
    side: str,
    limit_price: float | None = None,
    tif: str = "day",
):
    """
    Submit an equity/ETF order to Alpaca.

    Note: For safety, call this only after explicit user confirmation.
    """
    side_enum = OrderSide.BUY if side.lower().startswith("b") else OrderSide.SELL
    tif_enum = TimeInForce.DAY if tif.lower() == "day" else TimeInForce.GTC

    if limit_price is None:
        req = MarketOrderRequest(symbol=symbol, qty=qty, side=side_enum, time_in_force=tif_enum)
    else:
        req = LimitOrderRequest(
            symbol=symbol,
            qty=qty,
            side=side_enum,
            time_in_force=tif_enum,
            limit_price=round(float(limit_price), 2),
        )

    return trading.submit_order(order_data=req)


def submit_equity_notional_order(
    *,
    trading: TradingClient,
    symbol: str,
    notional: float,
    side: str,
    tif: str = "day",
):
    """
    Submit an equity/ETF notional market order (spend $X).

    Notes:
    - Alpaca supports fractional shares for eligible equities/ETFs via notional.
    - Some SDK versions may not accept `notional` on MarketOrderRequest; callers should catch TypeError.
    """
    side_enum = OrderSide.BUY if side.lower().startswith("b") else OrderSide.SELL
    tif_enum = TimeInForce.DAY if tif.lower() == "day" else TimeInForce.GTC
    req = MarketOrderRequest(symbol=symbol, notional=round(float(notional), 2), side=side_enum, time_in_force=tif_enum)
    return trading.submit_order(order_data=req)


def submit_crypto_order(
    *,
    trading: TradingClient,
    symbol: str,
    side: str,
    notional: float | None = None,
    qty: float | None = None,
    limit_price: float | None = None,
    tif: str = "day",
):
    """
    Submit a crypto order to Alpaca.

    Notes:
    - Prefer NOTIONAL for "spend $X" buys when supported.
    - For closes, prefer QTY to sell the entire position.
    - Some Alpaca SDK versions may not support `notional` on MarketOrderRequest; in that case, pass `qty`.
    """
    side_enum = OrderSide.BUY if side.lower().startswith("b") else OrderSide.SELL
    tif_enum = TimeInForce.DAY if tif.lower() == "day" else TimeInForce.GTC

    if limit_price is not None:
        # Crypto limit orders: rely on standard LimitOrderRequest.
        req = LimitOrderRequest(
            symbol=symbol,
            qty=qty,
            side=side_enum,
            time_in_force=tif_enum,
            limit_price=round(float(limit_price), 8),
        )
        return trading.submit_order(order_data=req)

    # Market order
    if notional is not None:
        try:
            # Alpaca expects notional to be in USD with 2 decimal places.
            req = MarketOrderRequest(
                symbol=symbol,
                notional=round(float(notional), 2),
                side=side_enum,
                time_in_force=tif_enum,
            )
            return trading.submit_order(order_data=req)
        except TypeError:
            # SDK doesn't accept notional here; fall back to qty if provided.
            if qty is None:
                raise

    if qty is None:
        raise ValueError("submit_crypto_order requires either notional or qty")

    req = MarketOrderRequest(symbol=symbol, qty=float(qty), side=side_enum, time_in_force=tif_enum)
    return trading.submit_order(order_data=req)



