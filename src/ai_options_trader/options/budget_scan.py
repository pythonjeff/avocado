from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable, Literal, Sequence

from ai_options_trader.data.alpaca import OptionCandidate
from ai_options_trader.utils.occ import parse_occ_option_symbol


Want = Literal["call", "put", "both"]
PriceBasis = Literal["ask", "mid", "last"]


@dataclass(frozen=True)
class AffordableOption:
    ticker: str
    symbol: str
    opt_type: str
    expiry: date
    dte_days: int
    strike: float
    price: float
    premium_usd: float
    spread_pct: float | None
    delta: float | None
    gamma: float | None
    theta: float | None
    vega: float | None
    iv: float | None
    oi: int | None = None  # Open interest
    volume: int | None = None  # Daily volume


def _spread_pct(bid: float | None, ask: float | None, mid: float | None) -> float | None:
    if bid is None or ask is None or mid is None or mid <= 0:
        return None
    return float((ask - bid) / mid)


def affordable_options_for_ticker(
    candidates: Iterable[OptionCandidate],
    *,
    ticker: str,
    max_premium_usd: float = 100.0,
    min_dte_days: int = 7,
    max_dte_days: int = 45,
    want: Want = "both",
    price_basis: PriceBasis = "ask",
    min_price: float = 0.05,
    require_delta: bool = True,
    # Liquidity guardrails
    max_spread_pct: float = 0.30,
    min_open_interest: int = 10,  # Lowered for illiquid underlyings (ETFs, etc.)
    min_volume: int = 10,  # Lowered for illiquid underlyings
    require_liquidity: bool = True,
    today: date | None = None,
) -> Sequence[AffordableOption]:
    """
    Return all option contracts within DTE window whose premium is <= max_premium_usd.

    Premium is computed as `price * 100` where `price` is chosen based on `price_basis`.
    """
    today = today or date.today()
    out: list[AffordableOption] = []

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

        mid = c.mid
        ask = c.ask
        last = c.last

        if price_basis == "mid":
            px = mid
        elif price_basis == "last":
            px = last
        else:
            px = ask

        if px is None or px <= 0:
            continue
        px = float(px)
        if px < float(min_price):
            continue

        prem = px * 100.0
        if prem > float(max_premium_usd):
            continue

        if require_delta and c.delta is None:
            continue

        sp = _spread_pct(c.bid, c.ask, mid)
        # Tight spread requirement: if we can compute spread, enforce max.
        # If spread is not computable, treat as not tradable (we can't evaluate the bid/ask).
        if sp is None or float(sp) > float(max_spread_pct):
            continue

        if bool(require_liquidity):
            # Passes if (OI >= min_open_interest) OR (volume >= min_volume).
            # If both missing, treat as not tradable.
            oi_val = int(c.oi) if c.oi is not None else None
            vol_val = int(c.volume) if c.volume is not None else None
            oi_ok = (oi_val is not None) and (oi_val >= int(min_open_interest))
            vol_ok = (vol_val is not None) and (vol_val >= int(min_volume))
            if not (oi_ok or vol_ok):
                continue

        out.append(
            AffordableOption(
                ticker=ticker,
                symbol=c.symbol,
                opt_type=opt_type,
                expiry=expiry,
                dte_days=int(dte),
                strike=float(strike),
                price=px,
                premium_usd=prem,
                spread_pct=sp,
                delta=float(c.delta) if c.delta is not None else None,
                gamma=float(c.gamma) if c.gamma is not None else None,
                theta=float(c.theta) if c.theta is not None else None,
                vega=float(c.vega) if c.vega is not None else None,
                iv=float(c.iv) if c.iv is not None else None,
                oi=int(c.oi) if c.oi is not None else None,
                volume=int(c.volume) if c.volume is not None else None,
            )
        )

    return out


def pick_best_affordable(
    opts: Sequence[AffordableOption],
    *,
    target_abs_delta: float = 0.30,
    max_spread_pct: float = 0.30,
) -> AffordableOption | None:
    """
    Choose a single "best" affordable contract.

    Heuristic (regime-grade but simple):
    - Prefer contracts with a computable spread_pct and spread <= max_spread_pct
    - Prefer contracts with delta present, and abs(delta) near target_abs_delta
    - Prefer lower premium (cheaper) as a final tiebreaker
    """
    if not opts:
        return None

    def _key(o: AffordableOption) -> tuple[int, float, float, float]:
        sp_ok = 1 if (o.spread_pct is not None and o.spread_pct <= float(max_spread_pct)) else 0
        has_delta = 1 if o.delta is not None else 0
        delta_dist = abs(abs(o.delta) - float(target_abs_delta)) if o.delta is not None else 1e9
        spread = float(o.spread_pct) if o.spread_pct is not None else 1e9
        return (-sp_ok, -has_delta, delta_dist, o.premium_usd + 10.0 * spread)

    return sorted(opts, key=_key)[0]


def score_delta_theta(
    opt: AffordableOption,
    *,
    target_abs_delta: float = 0.30,
    delta_weight: float = 1.0,
    theta_weight: float = 1.0,
) -> float:
    """
    Score a single option by delta/theta quality (higher is better).
    
    Used for display/ranking purposes.
    """
    # Delta score: how close to target (0-1 scale, 1 is perfect)
    if opt.delta is not None:
        delta_diff = abs(abs(float(opt.delta)) - float(target_abs_delta))
        delta_score = max(0.0, 1.0 - delta_diff * 2.0)  # Perfect at target, 0 at ±0.5 away
    else:
        delta_score = 0.0
    
    # Theta score: smaller magnitude is better (0-1 scale)
    if opt.theta is not None:
        theta_mag = abs(float(opt.theta))
        theta_score = max(0.0, 1.0 - theta_mag * 10.0)  # Penalize high theta decay
    else:
        theta_score = 0.0
    
    # Weighted combination
    total_weight = float(delta_weight) + float(theta_weight)
    if total_weight <= 0:
        return 0.0
    
    return (float(delta_weight) * delta_score + float(theta_weight) * theta_score) / total_weight


def score_delta_oi(
    opt: AffordableOption,
    *,
    target_abs_delta: float = 0.30,
    delta_weight: float = 1.0,
    oi_weight: float = 1.0,
    theta_weight: float = 0.3,  # Still factor in theta but lower weight
    oi_baseline: int = 1000,  # OI above this gets full score
) -> float:
    """
    Score an option by delta (proximity to target) and open interest (liquidity).
    
    Higher score is better.
    
    - Delta: Score 1.0 when |delta| == target_abs_delta, decays toward 0 as delta deviates
    - OI: Score 1.0 when OI >= oi_baseline, scales linearly below
    - Theta: Small bonus for lower time decay (closer to 0)
    """
    # Delta score: 1.0 at target, decaying as deviation increases
    if opt.delta is not None:
        abs_delta = abs(float(opt.delta))
        delta_diff = abs(abs_delta - float(target_abs_delta))
        # Max deviation is ~0.30 (from 0 or 0.60 to 0.30), so we scale
        delta_score = max(0.0, 1.0 - delta_diff / 0.30)
    else:
        delta_score = 0.0
    
    # OI score: 1.0 at baseline, linear scale below
    if opt.oi is not None and opt.oi > 0:
        oi_score = min(1.0, float(opt.oi) / float(oi_baseline))
    else:
        oi_score = 0.0  # No OI = low liquidity signal
    
    # Theta score: prefer closer to 0 (less decay)
    # Theta is typically negative for long options; we want small magnitude
    if opt.theta is not None:
        theta_mag = abs(float(opt.theta))
        # Typical theta might range 0.01 to 0.50; normalize
        theta_score = max(0.0, 1.0 - theta_mag / 0.50)
    else:
        theta_score = 0.5  # Neutral if missing
    
    # Weighted combination
    total_weight = float(delta_weight) + float(oi_weight) + float(theta_weight)
    if total_weight <= 0:
        return 0.0
    
    return (
        float(delta_weight) * delta_score +
        float(oi_weight) * oi_score +
        float(theta_weight) * theta_score
    ) / total_weight


def pick_best_delta_theta(
    opts: Sequence[AffordableOption],
    *,
    target_abs_delta: float = 0.30,
    delta_weight: float = 1.0,
    theta_weight: float = 1.0,
) -> AffordableOption | None:
    """
    Pick a single contract optimized for delta + theta (best-effort).

    Interpretation for long options:
    - Prefer |delta| close to target_abs_delta (responsiveness / moneyness control)
    - Prefer theta closer to 0 (lower time decay; theta is typically negative for long options)

    This assumes spread filtering has already happened upstream.
    """
    if not opts:
        return None

    def _theta_penalty(th: float | None) -> float:
        # Theta is usually negative; we want small magnitude (closer to 0).
        if th is None:
            return 1e9
        return abs(float(th))

    def _key(o: AffordableOption) -> tuple[float, float]:
        dd = abs(abs(float(o.delta)) - float(target_abs_delta)) if o.delta is not None else 1e9
        tp = _theta_penalty(o.theta)
        score = float(delta_weight) * dd + float(theta_weight) * tp
        # Secondary tiebreaker: cheaper premium
        return (score, float(o.premium_usd))

    return sorted(opts, key=_key)[0]
