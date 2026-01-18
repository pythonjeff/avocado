from __future__ import annotations

from typing import Dict, Optional

from pydantic import BaseModel, Field


class FundingInputs(BaseModel):
    # Core levels (%)
    effr: Optional[float] = None  # DFF
    sofr: Optional[float] = None  # SOFR
    tgcr: Optional[float] = None  # TGCR
    bgcr: Optional[float] = None  # BGCR
    obfr: Optional[float] = None  # OBFR (optional)
    iorb: Optional[float] = None  # IORB or IOER (optional)

    # MVP spreads / features (bps unless stated)
    spread_corridor_bps: Optional[float] = None  # SOFR - IORB (preferred) else SOFR - EFFR
    spread_corridor_name: Optional[str] = None  # "SOFR-IORB" or "SOFR-EFFR"
    spread_sofr_effr_bps: Optional[float] = None
    spread_bgcr_tgcr_bps: Optional[float] = None

    spike_5d_bps: Optional[float] = None  # rolling max 5d of corridor spread
    persistence_20d: Optional[float] = None  # % of last 20d above stress threshold (0..1)
    vol_20d_bps: Optional[float] = None  # rolling std 20d of corridor spread

    # Baselines (computed from recent history; regime-grade, not hard-coded)
    baseline_median_bps: Optional[float] = None
    baseline_std_bps: Optional[float] = None
    tight_threshold_bps: Optional[float] = None
    stress_threshold_bps: Optional[float] = None

    persistence_baseline: Optional[float] = None
    persistence_tight: Optional[float] = None
    persistence_stress: Optional[float] = None

    vol_baseline_bps: Optional[float] = None
    vol_tight_bps: Optional[float] = None
    vol_stress_bps: Optional[float] = None

    # ON RRP (critical liquidity buffer)
    on_rrp_usd_bn: Optional[float] = None  # already in billions (stored as millions, displayed /1000)
    on_rrp_chg_13w: Optional[float] = None  # 13-week change (millions)
    z_on_rrp: Optional[float] = None  # z-score vs 3y history
    
    # Bank reserves (critical liquidity level)
    bank_reserves_usd_bn: Optional[float] = None  # millions in storage
    bank_reserves_chg_13w: Optional[float] = None
    z_bank_reserves: Optional[float] = None
    
    # TGA (Treasury General Account - inverse driver of RRP/reserves)
    tga_usd_bn: Optional[float] = None  # millions in storage
    tga_chg_4w: Optional[float] = None
    z_tga_chg_4w: Optional[float] = None
    
    # Fed balance sheet (QT pace)
    fed_assets_usd_bn: Optional[float] = None  # millions in storage
    fed_assets_chg_13w: Optional[float] = None

    # Debug / transparency
    components: Dict[str, Optional[float]] = Field(default_factory=dict)


class FundingState(BaseModel):
    asof: str
    start_date: str
    inputs: FundingInputs
    notes: str = ""


