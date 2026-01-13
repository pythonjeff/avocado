from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class HousingInputs:
    mortgage_30y: float | None = None
    ust_10y: float | None = None
    mortgage_spread: float | None = None  # mortgage_30y - ust_10y
    z_mortgage_spread: float | None = None

    # Market-based proxies (best-effort; derived from ETF closes)
    z_mbs_rel_ret_60d: float | None = None  # MBB vs IEF
    z_homebuilder_rel_ret_60d: float | None = None  # ITB vs SPY
    z_reit_rel_ret_60d: float | None = None  # VNQ vs SPY

    housing_pressure_score: float | None = None
    components: dict[str, Any] | None = None


@dataclass(frozen=True)
class HousingState:
    asof: str
    start_date: str
    inputs: HousingInputs
    notes: str = ""

