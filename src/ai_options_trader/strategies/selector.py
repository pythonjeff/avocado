from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable, Optional

from ai_options_trader.config import StrategyConfig, RiskConfig
from ai_options_trader.utils.occ import parse_occ_option_symbol
from ai_options_trader.data.alpaca import OptionCandidate
from ai_options_trader.strategies.risk import size_by_budget, SizeResult

@dataclass(frozen=True)
class ScoredOption:
    symbol: str
    opt_type: str
    expiry: date
    strike: float
    dte_days: int
    delta: float
    gamma: float | None
    theta: float | None
    vega: float | None
    iv: float | None
    mid: float
    spread_pct: float
    oi: int
    volume: int
    score: float
    size: SizeResult
    reasons: dict

@dataclass
class SelectionDiagnostics:
    total: int = 0
    occ_parsed: int = 0
    type_match: int = 0
    dte_match: int = 0
    has_delta: int = 0
    has_price: int = 0
    spread_ok: int = 0
    liquidity_ok: int = 0
    size_ok: int = 0
    selected: int = 0

def _spread_pct(bid: float | None, ask: float | None, mid: float | None) -> float:
    if bid is None or ask is None or mid is None or mid <= 0:
        return 1e9
    return (ask - bid) / mid

def choose_best_option(
    candidates: Iterable[OptionCandidate],
    ticker: str,
    want: str,  # 'call' or 'put'
    equity_usd: float,
    strat: StrategyConfig,
    risk: RiskConfig,
    today: date | None = None,
) -> Optional[ScoredOption]:
    today = today or date.today()
    budget = equity_usd * risk.max_equity_pct_per_trade
    best: ScoredOption | None = None

    for c in candidates:
        try:
            expiry, opt_type, strike = parse_occ_option_symbol(c.symbol, ticker)
        except Exception:
            continue

        if opt_type != want:
            continue

        dte_days = (expiry - today).days
        if dte_days < strat.dte_min or dte_days > strat.dte_max:
            continue

        if c.delta is None:
            continue
        delta = float(c.delta)
        if abs(delta) <= 0:
            continue

        mid = c.mid
        if mid is None:
            # fall back to last trade (less reliable)
            if c.last is None or c.last <= 0:
                continue
            mid = float(c.last)

        bid = c.bid
        ask = c.ask
        sp = _spread_pct(bid, ask, mid)
        if sp > strat.max_spread_pct:
            continue

        # Liquidity rule (global):
        # Only recommend contracts with tight spreads AND high liquidity.
        # Passes if (OI >= min_open_interest) OR (volume >= min_volume).
        # If both OI and volume are missing, treat as not tradable.
        oi_val = int(c.oi) if c.oi is not None else None
        vol_val = int(c.volume) if c.volume is not None else None
        oi_ok = (oi_val is not None) and (oi_val >= int(strat.min_open_interest))
        vol_ok = (vol_val is not None) and (vol_val >= int(strat.min_volume))
        if not (oi_ok or vol_ok):
            continue
        oi = int(oi_val or 0)
        vol = int(vol_val or 0)

        per_contract_cost = mid * 100.0
        size = size_by_budget(budget, per_contract_cost, risk)
        if size.max_contracts < 1:
            continue

        # scoring: minimize DTE distance and delta distance, penalize spread; reward liquidity
        dte_dist = abs(dte_days - strat.target_dte_days)
        delta_dist = abs(abs(delta) - strat.target_delta_abs)
        liquidity_bonus = -0.001 * (oi + 10 * vol)  # small bonus for more liquidity
        spread_penalty = 10.0 * sp

        score = (dte_dist * 1.0) + (delta_dist * 10.0) + spread_penalty + liquidity_bonus

        reasons = {
            "dte_dist": dte_dist,
            "delta_dist": delta_dist,
            "spread_pct": sp,
            "open_interest": oi,
            "volume": vol,
            "budget_usd": budget,
        }

        scored = ScoredOption(
            symbol=c.symbol,
            opt_type=opt_type,
            expiry=expiry,
            strike=strike,
            dte_days=dte_days,
            delta=delta,
            gamma=getattr(c, "gamma", None),
            theta=getattr(c, "theta", None),
            vega=getattr(c, "vega", None),
            iv=getattr(c, "iv", None),
            mid=mid,
            spread_pct=sp,
            oi=oi,
            volume=vol,
            score=score,
            size=size,
            reasons=reasons,
        )

        if best is None or scored.score < best.score:
            best = scored

    return best


def diagnose_selection(
    candidates: Iterable[OptionCandidate],
    ticker: str,
    want: str,
    equity_usd: float,
    strat: StrategyConfig,
    risk: RiskConfig,
    today: date | None = None,
) -> SelectionDiagnostics:
    """Run the same filter pipeline as choose_best_option, but only return counts.

    This is used by the CLI to explain why nothing was selected.
    """
    today = today or date.today()
    budget = equity_usd * risk.max_equity_pct_per_trade
    d = SelectionDiagnostics()

    for c in candidates:
        d.total += 1

        try:
            expiry, opt_type, _strike = parse_occ_option_symbol(c.symbol, ticker)
        except Exception:
            continue
        d.occ_parsed += 1

        if opt_type != want:
            continue
        d.type_match += 1

        dte_days = (expiry - today).days
        if dte_days < strat.dte_min or dte_days > strat.dte_max:
            continue
        d.dte_match += 1

        if c.delta is None or float(c.delta) == 0:
            continue
        d.has_delta += 1

        mid = c.mid
        if mid is None:
            if c.last is None or c.last <= 0:
                continue
            mid = float(c.last)
        d.has_price += 1

        sp = _spread_pct(c.bid, c.ask, mid)
        if sp > strat.max_spread_pct:
            continue
        d.spread_ok += 1

        oi_val = int(c.oi) if c.oi is not None else None
        vol_val = int(c.volume) if c.volume is not None else None
        oi_ok = (oi_val is not None) and (oi_val >= int(strat.min_open_interest))
        vol_ok = (vol_val is not None) and (vol_val >= int(strat.min_volume))
        if not (oi_ok or vol_ok):
            continue
        d.liquidity_ok += 1

        size = size_by_budget(budget, mid * 100.0, risk)
        if size.max_contracts < 1:
            continue
        d.size_ok += 1

        d.selected += 1

    return d
