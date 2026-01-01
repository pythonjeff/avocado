from __future__ import annotations

from typing import Dict, Optional

from pydantic import BaseModel, Field


class LiquidityInputs(BaseModel):
    # Core levels
    ust_10y: Optional[float] = None
    ust_2y: Optional[float] = None
    hy_oas: Optional[float] = None
    ig_oas: Optional[float] = None
    baa10ym: Optional[float] = None  # Baa corporate yield - 10Y treasury (if available)
    fed_funds: Optional[float] = None
    cpi_yoy: Optional[float] = None
    real_policy_rate: Optional[float] = None  # Fed funds - CPI YoY (pct points)

    # Funding plumbing
    tga_level: Optional[float] = None  # Treasury General Account (level)
    tga_chg_28d: Optional[float] = None  # 28d change in TGA level
    rrp_level: Optional[float] = None  # Overnight RRP usage (level)
    rrp_chg_20d: Optional[float] = None  # 20d change in RRP level

    # Dynamics
    ust_10y_chg_20d_bps: Optional[float] = None
    ust_10y_chg_60d_bps: Optional[float] = None
    curve_10y_2y: Optional[float] = None  # DGS10 - DGS2 (pct points)

    # Standardized readings
    z_hy_oas: Optional[float] = None
    z_ig_oas: Optional[float] = None
    z_ust_10y_chg_20d: Optional[float] = None
    z_hy_minus_ig_oas: Optional[float] = None
    z_curve_10y_2y: Optional[float] = None
    z_real_policy_rate: Optional[float] = None
    z_tga_chg_28d: Optional[float] = None
    z_rrp_chg_20d: Optional[float] = None

    # Composite
    liquidity_tightness_score: Optional[float] = None
    is_liquidity_tight: Optional[bool] = None

    # Debug / transparency
    components: Dict[str, Optional[float]] = Field(default_factory=dict)


class LiquidityState(BaseModel):
    asof: str
    start_date: str
    inputs: LiquidityInputs
    notes: str = ""


