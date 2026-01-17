from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SolarInputs:
    solar_ret_60d: float | None = None
    solar_rel_ret_60d: float | None = None  # solar basket vs SPY
    silver_ret_60d: float | None = None  # SLV proxy
    z_solar_rel_ret_60d: float | None = None
    z_silver_ret_60d: float | None = None
    solar_headwind_score: float | None = None
    components: dict[str, Any] | None = None


@dataclass(frozen=True)
class SolarState:
    asof: str
    start_date: str
    inputs: SolarInputs
    notes: str = ""
