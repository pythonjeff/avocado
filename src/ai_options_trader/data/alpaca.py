from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable

from alpaca.data.historical import OptionHistoricalDataClient
from alpaca.data.requests import OptionChainRequest
from alpaca.trading.client import TradingClient

from ai_options_trader.config import Settings

@dataclass(frozen=True)
class OptionCandidate:
    symbol: str
    opt_type: str
    expiry: date
    strike: float
    dte_days: int
    delta: float | None
    oi: int | None
    volume: int | None
    bid: float | None
    ask: float | None
    last: float | None

    @property
    def mid(self) -> float | None:
        if self.bid is not None and self.ask is not None and self.bid > 0 and self.ask > 0:
            return (self.bid + self.ask) / 2.0
        return None

def make_clients(settings: Settings) -> tuple[TradingClient, OptionHistoricalDataClient]:
    trading = TradingClient(settings.alpaca_api_key, settings.alpaca_api_secret, paper=settings.alpaca_paper)
    data_key = settings.alpaca_data_key or settings.alpaca_api_key
    data_secret = settings.alpaca_data_secret or settings.alpaca_api_secret
    data = OptionHistoricalDataClient(data_key, data_secret)
    return trading, data

def fetch_option_chain(data_client: OptionHistoricalDataClient, ticker: str) -> dict[str, Any]:
    req = OptionChainRequest(underlying_symbol=ticker)
    return data_client.get_option_chain(request_params=req)

def to_candidates(chain: dict[str, Any], ticker: str) -> Iterable[OptionCandidate]:
    # Alpaca returns mapping: symbol -> snapshot-like object.
    for sym, snap in chain.items():
        greeks = getattr(snap, "greeks", None)
        quote = getattr(snap, "latest_quote", None)
        trade = getattr(snap, "latest_trade", None)

        delta = getattr(greeks, "delta", None) if greeks else None
        bid = getattr(quote, "bid_price", None) if quote else None
        ask = getattr(quote, "ask_price", None) if quote else None
        last = getattr(trade, "price", None) if trade else None

        oi = getattr(snap, "open_interest", None)
        vol = getattr(snap, "volume", None)

        # leave expiry/strike/type to selector via OCC parsing
        yield OptionCandidate(
            symbol=sym,
            opt_type="",
            expiry=date(1970, 1, 1),
            strike=0.0,
            dte_days=0,
            delta=float(delta) if delta is not None else None,
            oi=int(oi) if oi is not None else None,
            volume=int(vol) if vol is not None else None,
            bid=float(bid) if bid is not None else None,
            ask=float(ask) if ask is not None else None,
            last=float(last) if last is not None else None,
        )
