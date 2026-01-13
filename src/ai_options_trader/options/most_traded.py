from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable, Literal, Sequence

from ai_options_trader.data.alpaca import OptionCandidate
from ai_options_trader.utils.occ import parse_occ_option_symbol


SortKey = Literal["volume", "open_interest", "delta", "abs_delta", "gamma", "theta", "vega", "iv", "hf"]
Want = Literal["call", "put", "both"]


@dataclass(frozen=True)
class TradedOption:
    symbol: str
    opt_type: str  # call|put
    expiry: date
    strike: float
    dte_days: int
    volume: int | None
    open_interest: int | None
    bid: float | None
    ask: float | None
    last: float | None
    delta: float | None
    gamma: float | None
    theta: float | None
    vega: float | None
    iv: float | None

    @property
    def mid(self) -> float | None:
        if self.bid is not None and self.ask is not None and self.bid > 0 and self.ask > 0:
            return (self.bid + self.ask) / 2.0
        return None

    @property
    def spread_pct(self) -> float | None:
        m = self.mid
        if m is None or m <= 0:
            return None
        if self.bid is None or self.ask is None:
            return None
        return float((float(self.ask) - float(self.bid)) / float(m))


def most_traded_options(
    candidates: Iterable[OptionCandidate],
    *,
    ticker: str,
    min_dte_days: int = 0,
    max_dte_days: int = 90,
    want: Want = "both",
    top: int = 25,
    sort: SortKey = "volume",
    volume_by_symbol: dict[str, int] | None = None,
    open_interest_by_symbol: dict[str, int] | None = None,
    today: date | None = None,
) -> Sequence[TradedOption]:
    """
    Rank option contracts by "most traded" in the next `max_dte_days`.

    Notes:
    - Uses snapshot fields (volume/open_interest) when present.
    - Treats missing volume/OI as 0 for ranking (so we still return something).
    """
    today = today or date.today()
    out: list[TradedOption] = []

    for c in candidates:
        try:
            expiry, opt_type, strike = parse_occ_option_symbol(c.symbol, ticker)
        except Exception:
            continue

        if want != "both" and opt_type != want:
            continue

        dte = (expiry - today).days
        if dte < int(min_dte_days) or dte > int(max_dte_days):
            continue

        vol_override = volume_by_symbol.get(c.symbol) if volume_by_symbol else None
        oi_override = open_interest_by_symbol.get(c.symbol) if open_interest_by_symbol else None

        out.append(
            TradedOption(
                symbol=c.symbol,
                opt_type=opt_type,
                expiry=expiry,
                strike=float(strike),
                dte_days=int(dte),
                volume=int(vol_override) if isinstance(vol_override, int) else (int(c.volume) if c.volume is not None else None),
                open_interest=int(oi_override) if isinstance(oi_override, int) else (int(c.oi) if c.oi is not None else None),
                bid=float(c.bid) if c.bid is not None else None,
                ask=float(c.ask) if c.ask is not None else None,
                last=float(c.last) if c.last is not None else None,
                delta=float(c.delta) if c.delta is not None else None,
                gamma=float(c.gamma) if getattr(c, "gamma", None) is not None else None,
                theta=float(c.theta) if getattr(c, "theta", None) is not None else None,
                vega=float(c.vega) if getattr(c, "vega", None) is not None else None,
                iv=float(c.iv) if c.iv is not None else None,
            )
        )

    def _key(x: TradedOption) -> tuple[int, int, int, float, int, int, int, int, int, int]:
        vol = x.volume or 0
        oi = x.open_interest or 0
        # Prefer nearer expiries slightly when primary values tie, and use strike as a stable tiebreaker.
        # NOTE: We don't know spot here, so strike isn't an "ATM" proxy; it's just deterministic.
        if sort == "open_interest":
            primary = oi
            secondary = vol
            return (primary, secondary, -x.dte_days, -x.strike, 0, 0, 0, 0, 0, 0)
        if sort == "volume":
            primary = vol
            secondary = oi
            return (primary, secondary, -x.dte_days, -x.strike, 0, 0, 0, 0, 0, 0)

        # Greeks/IV sorts: treat missing as very small so they naturally sink in descending sort.
        def _f(v: float | None) -> int:
            if v is None:
                return -10**12
            return int(round(float(v) * 1_000_000))

        if sort == "delta":
            return (_f(x.delta), vol, -x.dte_days, -x.strike, 0, 0, 0, 0, 0, 0)
        if sort == "abs_delta":
            return (_f(abs(x.delta) if x.delta is not None else None), vol, -x.dte_days, -x.strike, 0, 0, 0, 0, 0, 0)
        if sort == "gamma":
            return (_f(getattr(x, "gamma", None)), vol, -x.dte_days, -x.strike, 0, 0, 0, 0, 0, 0)
        if sort == "theta":
            return (_f(getattr(x, "theta", None)), vol, -x.dte_days, -x.strike, 0, 0, 0, 0, 0, 0)
        if sort == "vega":
            return (_f(getattr(x, "vega", None)), vol, -x.dte_days, -x.strike, 0, 0, 0, 0, 0, 0)
        if sort == "iv":
            return (_f(x.iv), vol, -x.dte_days, -x.strike, 0, 0, 0, 0, 0, 0)
        if sort == "hf":
            # Hedge-fund-ish ranking when OI/volume are missing:
            # - Tight, real quotes first (bid/ask/mid exist)
            # - Then prefer contracts that are responsive (|delta|), and have convexity/optionalities (gamma/vega)
            # - Prefer less-negative theta (carry) as a tertiary preference
            # - Prefer higher IV (more optionality; informational, not always "better")
            quote_ok = 1 if (x.mid is not None and x.bid is not None and x.ask is not None and x.bid > 0 and x.ask > 0) else 0
            sp = x.spread_pct
            sp_scaled = 0
            if sp is not None and sp == sp and sp >= 0:
                # smaller spread should rank higher; we negate it for reverse sort
                sp_scaled = int(round(-float(sp) * 1_000_000))
            absd = abs(float(x.delta)) if x.delta is not None else None
            absd_scaled = _f(absd)
            g = _f(getattr(x, "gamma", None))
            v = _f(getattr(x, "vega", None))
            th = _f(getattr(x, "theta", None))
            iv = _f(x.iv)
            # include vol/oi as weak tie-breakers when present
            return (quote_ok, sp_scaled, absd_scaled, g, v, th, iv, vol, oi, -x.dte_days)

        # Default fallback (shouldn't hit)
        return (vol, oi, -x.dte_days, -x.strike, 0, 0, 0, 0, 0, 0)

    out.sort(key=_key, reverse=True)
    return out[: max(1, int(top))]


