from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal

import pandas as pd

InstrumentType = Literal["equity", "option"]
TradeFamily = Literal["probe", "expression", "moonshot"]


@dataclass(frozen=True)
class CandidateTrade:
    sleeve: str
    ticker: str
    action: str  # OPEN_OPTION|OPEN_SHARES|CLOSE|...
    instrument_type: InstrumentType
    direction: str  # bullish|bearish
    score: float
    expRet: float | None = None
    prob: float | None = None
    rationale: str | None = None
    expr: str | None = None  # option symbol or "qty=.."
    est_cost_usd: float | None = None
    risk_factors: tuple[str, ...] = ()
    trade_family: TradeFamily = "expression"
    probe: bool = False
    meta: dict[str, Any] | None = None


@dataclass(frozen=True)
class SleeveConfig:
    name: str
    aliases: tuple[str, ...] = ()
    risk_budget_pct: float = 0.33
    allowed_trade_families: tuple[TradeFamily, ...] = ("probe", "expression", "moonshot")
    allowed_instrument_types: tuple[InstrumentType, ...] = ("equity", "option")
    # Universe builder: basket name -> tickers.
    universe_fn: Callable[[str], list[str]] | None = None
    # Feature weighting: prefix -> multiplier (applied to shared regime matrix columns)
    feature_weights_by_prefix: dict[str, float] | None = None

    def all_names(self) -> set[str]:
        out = {self.name}
        out.update(self.aliases)
        return {x.strip().lower() for x in out if x and x.strip()}


def apply_feature_prefix_weights(X: pd.DataFrame, weights_by_prefix: dict[str, float] | None) -> pd.DataFrame:
    """
    Apply per-prefix multipliers to a shared regime matrix.
    This lets each sleeve emphasize different feature families while reusing the same pipeline.
    """
    if X is None or X.empty or not weights_by_prefix:
        return X
    w = {str(k): float(v) for k, v in weights_by_prefix.items() if k and v is not None}
    if not w:
        return X

    Xm = X.copy()
    for col in Xm.columns:
        mul = 1.0
        for pref, m in w.items():
            if str(col).startswith(pref) or str(col) == pref:
                mul = float(m)
                break
        if mul != 1.0:
            Xm[col] = pd.to_numeric(Xm[col], errors="coerce") * float(mul)
    return Xm


def infer_risk_factors(*, sleeve: str, ticker: str, direction: str) -> tuple[str, ...]:
    """
    MVP bucket inference. This is intentionally heuristic and can be refined later.
    """
    t = (ticker or "").strip().upper()
    s = (sleeve or "").strip().lower()
    d = (direction or "").strip().lower()

    fac: set[str] = set()

    # Vol sleeve: mostly "vol_up" expressions.
    if s in {"vol", "volatility"}:
        fac.add("vol_up")

    # Equity beta bucket
    if t in {"SPY", "QQQ", "QQQM", "IWM", "DIA"}:
        fac.add("equity_beta_up" if d.startswith("bull") else "equity_beta_down")

    # Inverse equity ETFs bucket
    if t in {"SH", "PSQ", "RWM", "DOG", "SDS", "QID", "TWM", "SPXU", "SQQQ", "TZA", "SDOW", "SOXS", "SRTY"}:
        fac.add("inverse_equity")
        fac.add("equity_beta_down")

    # Inverse real estate / REIT beta
    if t in {"REK", "SRS"}:
        fac.add("reit_beta_down")
        fac.add("inverse_real_estate")

    # Rates bucket
    if t in {"TLT", "IEF", "TIP", "TBT", "TBF"}:
        fac.add("rates_down" if t in {"TLT", "IEF"} and d.startswith("bull") else "rates_up")

    # Credit bucket
    if t in {"HYG", "LQD", "JNK", "SHY"}:
        fac.add("credit")
        if not d.startswith("bull"):
            fac.add("credit_stress")

    # AI bubble sleeve (tech duration / semis)
    if s in {"ai-bubble", "ai_bubble", "tech_duration"}:
        fac.add("tech_duration")
        if not d.startswith("bull"):
            fac.add("equity_beta_down")

    return tuple(sorted(fac))

