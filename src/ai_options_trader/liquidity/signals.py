from __future__ import annotations

from typing import Dict

import pandas as pd

from ai_options_trader.config import Settings
from ai_options_trader.data.fred import FredClient
from ai_options_trader.liquidity.models import LiquidityInputs, LiquidityState
from ai_options_trader.macro.transforms import merge_series_daily, zscore


# FRED series IDs (widely used / liquid proxies for "liquidity" conditions)
LIQUIDITY_FRED_SERIES: Dict[str, str] = {
    # Government bond market
    "DGS10": "DGS10",  # 10-Year Treasury Constant Maturity Rate (%)
    "DGS2": "DGS2",  # 2-Year Treasury Constant Maturity Rate (%)
    # Policy + inflation (for real policy rate)
    "DFF": "DFF",  # Effective Federal Funds Rate (%)
    "CPIAUCSL": "CPIAUCSL",  # CPI (monthly) -> CPI YoY (%)
    # Corporate credit liquidity / stress
    "HY_OAS": "BAMLH0A0HYM2",  # ICE BofA US High Yield Index Option-Adjusted Spread (%)
    "IG_OAS": "BAMLC0A0CM",  # ICE BofA US Corporate Index Option-Adjusted Spread (%)
    # Spread-like yield measure
    "BAA10YM": "BAA10YM",  # Moody's Seasoned Baa Corporate Bond Yield Relative to 10Y Treasury (%)
    # Funding plumbing
    # Note: these may not be cached locally; we treat them as optional (see `_fetch_optional`).
    "TGA": "WTREGEN",  # Treasury General Account (weekly)
    "RRP": "RRPONTSYD",  # Overnight Reverse Repo usage (daily, $)
}

_OPTIONAL_SERIES = {"TGA", "RRP"}


def _fetch_optional(
    *,
    fred: FredClient,
    series_id: str,
    start_date: str,
    refresh: bool,
) -> pd.DataFrame | None:
    """
    Best-effort fetch for series that may not be available in cache in restricted environments.
    Returns None on failure instead of raising.
    """
    try:
        return fred.fetch_series(series_id=series_id, start_date=start_date, refresh=refresh)
    except Exception:
        return None


def _weighted_score(row: pd.Series, weights: Dict[str, float]) -> float | None:
    """
    Compute a weighted mean of available (non-NaN) components.
    We normalize by sum(abs(w_i)) over available components to keep scale comparable as series drop in/out.
    """
    num = 0.0
    denom = 0.0
    for col, w in weights.items():
        v = row.get(col, None)
        if v is None or (isinstance(v, float) and pd.isna(v)):
            continue
        if pd.isna(v):
            continue
        num += float(w) * float(v)
        denom += abs(float(w))
    if denom <= 0:
        return None
    return num / denom


def build_liquidity_dataset(settings: Settings, start_date: str = "2011-01-01", refresh: bool = False) -> pd.DataFrame:
    if not settings.FRED_API_KEY:
        raise RuntimeError("Missing FRED_API_KEY in environment / .env")

    fred = FredClient(api_key=settings.FRED_API_KEY)

    series_frames: Dict[str, pd.DataFrame] = {}
    for name, sid in LIQUIDITY_FRED_SERIES.items():
        if name in _OPTIONAL_SERIES:
            df = _fetch_optional(fred=fred, series_id=sid, start_date=start_date, refresh=refresh)
            if df is None or df.empty:
                continue
        else:
            df = fred.fetch_series(series_id=sid, start_date=start_date, refresh=refresh)
        df = df.rename(columns={"value": name}).sort_values("date")
        series_frames[name] = df

    # Build daily grid and forward-fill (FRED series can have missing weekends/holidays)
    
    max_date = max(df["date"].max() for df in series_frames.values())
    base = pd.DataFrame({"date": pd.date_range(start=pd.to_datetime(start_date), end=pd.to_datetime(max_date), freq="D")})
    merged = merge_series_daily(base, series_frames, ffill=True)

    # CPI YoY (monthly CPI ffilled to daily grid)
    if "CPIAUCSL" in merged.columns:
        merged["CPI_YOY"] = merged["CPIAUCSL"].pct_change(12) * 100.0

    # Real policy rate proxy (pct points)
    if "DFF" in merged.columns and "CPI_YOY" in merged.columns:
        merged["REAL_POLICY_RATE"] = merged["DFF"] - merged["CPI_YOY"]

    # 10Y yield dynamics (bps)
    merged["DGS10_CHG_20D_BPS"] = (merged["DGS10"] - merged["DGS10"].shift(20)) * 100.0
    merged["DGS10_CHG_60D_BPS"] = (merged["DGS10"] - merged["DGS10"].shift(60)) * 100.0

    # Term premium proxy: curve slope (10y - 2y), pct points
    if "DGS2" in merged.columns:
        merged["CURVE_10Y_2Y"] = merged["DGS10"] - merged["DGS2"]

    # Credit divergence: HY minus IG OAS (pct points)
    merged["HY_MINUS_IG_OAS"] = merged["HY_OAS"] - merged["IG_OAS"]

    # TGA and RRP dynamics (levels + changes). Units depend on series (FRED values).
    if "TGA" in merged.columns:
        merged["TGA_CHG_28D"] = merged["TGA"] - merged["TGA"].shift(28)
    if "RRP" in merged.columns:
        merged["RRP_CHG_20D"] = merged["RRP"] - merged["RRP"].shift(20)

    # Standardize key components
    merged["Z_HY_OAS"] = zscore(merged["HY_OAS"], window=252)
    merged["Z_IG_OAS"] = zscore(merged["IG_OAS"], window=252)
    merged["Z_DGS10_CHG_20D"] = zscore(merged["DGS10_CHG_20D_BPS"], window=252)
    merged["Z_HY_MINUS_IG_OAS"] = zscore(merged["HY_MINUS_IG_OAS"], window=252)
    if "CURVE_10Y_2Y" in merged.columns:
        merged["Z_CURVE_10Y_2Y"] = zscore(merged["CURVE_10Y_2Y"], window=252)
    if "REAL_POLICY_RATE" in merged.columns:
        merged["Z_REAL_POLICY_RATE"] = zscore(merged["REAL_POLICY_RATE"], window=252)
    if "TGA_CHG_28D" in merged.columns:
        merged["Z_TGA_CHG_28D"] = zscore(merged["TGA_CHG_28D"], window=252)
    if "RRP_CHG_20D" in merged.columns:
        merged["Z_RRP_CHG_20D"] = zscore(merged["RRP_CHG_20D"], window=252)

    # Composite tightness score (positive = tighter liquidity / tighter funding constraints)
    # Designed to be robust when optional components are missing: we normalize weights over available z-components.
    weights: Dict[str, float] = {
        "Z_HY_OAS": 0.25,
        "Z_IG_OAS": 0.15,
        "Z_HY_MINUS_IG_OAS": 0.10,
        "Z_DGS10_CHG_20D": 0.10,
        "Z_CURVE_10Y_2Y": 0.10,
        "Z_REAL_POLICY_RATE": 0.10,
        "Z_TGA_CHG_28D": 0.10,
        "Z_RRP_CHG_20D": 0.10,
    }
    merged["LIQ_TIGHTNESS_SCORE"] = merged.apply(lambda r: _weighted_score(r, weights), axis=1)

    return merged


def build_liquidity_state(settings: Settings, start_date: str = "2011-01-01", refresh: bool = False) -> LiquidityState:
    df = build_liquidity_dataset(settings=settings, start_date=start_date, refresh=refresh)
    last = df.dropna(subset=["DGS10", "HY_OAS", "IG_OAS"]).iloc[-1]

    score = float(last["LIQ_TIGHTNESS_SCORE"]) if pd.notna(last["LIQ_TIGHTNESS_SCORE"]) else None
    inputs = LiquidityInputs(
        ust_10y=float(last["DGS10"]) if pd.notna(last["DGS10"]) else None,
        ust_2y=float(last["DGS2"]) if "DGS2" in last and pd.notna(last["DGS2"]) else None,
        hy_oas=float(last["HY_OAS"]) if pd.notna(last["HY_OAS"]) else None,
        ig_oas=float(last["IG_OAS"]) if pd.notna(last["IG_OAS"]) else None,
        baa10ym=float(last["BAA10YM"]) if "BAA10YM" in last and pd.notna(last["BAA10YM"]) else None,
        fed_funds=float(last["DFF"]) if "DFF" in last and pd.notna(last["DFF"]) else None,
        cpi_yoy=float(last["CPI_YOY"]) if "CPI_YOY" in last and pd.notna(last["CPI_YOY"]) else None,
        real_policy_rate=float(last["REAL_POLICY_RATE"]) if "REAL_POLICY_RATE" in last and pd.notna(last["REAL_POLICY_RATE"]) else None,
        tga_level=float(last["TGA"]) if "TGA" in last and pd.notna(last["TGA"]) else None,
        tga_chg_28d=float(last["TGA_CHG_28D"]) if "TGA_CHG_28D" in last and pd.notna(last["TGA_CHG_28D"]) else None,
        rrp_level=float(last["RRP"]) if "RRP" in last and pd.notna(last["RRP"]) else None,
        rrp_chg_20d=float(last["RRP_CHG_20D"]) if "RRP_CHG_20D" in last and pd.notna(last["RRP_CHG_20D"]) else None,
        ust_10y_chg_20d_bps=float(last["DGS10_CHG_20D_BPS"]) if pd.notna(last["DGS10_CHG_20D_BPS"]) else None,
        ust_10y_chg_60d_bps=float(last["DGS10_CHG_60D_BPS"]) if pd.notna(last["DGS10_CHG_60D_BPS"]) else None,
        curve_10y_2y=float(last["CURVE_10Y_2Y"]) if "CURVE_10Y_2Y" in last and pd.notna(last["CURVE_10Y_2Y"]) else None,
        z_hy_oas=float(last["Z_HY_OAS"]) if pd.notna(last["Z_HY_OAS"]) else None,
        z_ig_oas=float(last["Z_IG_OAS"]) if pd.notna(last["Z_IG_OAS"]) else None,
        z_ust_10y_chg_20d=float(last["Z_DGS10_CHG_20D"]) if pd.notna(last["Z_DGS10_CHG_20D"]) else None,
        z_hy_minus_ig_oas=float(last["Z_HY_MINUS_IG_OAS"]) if pd.notna(last["Z_HY_MINUS_IG_OAS"]) else None,
        z_curve_10y_2y=float(last["Z_CURVE_10Y_2Y"]) if "Z_CURVE_10Y_2Y" in last and pd.notna(last["Z_CURVE_10Y_2Y"]) else None,
        z_real_policy_rate=float(last["Z_REAL_POLICY_RATE"]) if "Z_REAL_POLICY_RATE" in last and pd.notna(last["Z_REAL_POLICY_RATE"]) else None,
        z_tga_chg_28d=float(last["Z_TGA_CHG_28D"]) if "Z_TGA_CHG_28D" in last and pd.notna(last["Z_TGA_CHG_28D"]) else None,
        z_rrp_chg_20d=float(last["Z_RRP_CHG_20D"]) if "Z_RRP_CHG_20D" in last and pd.notna(last["Z_RRP_CHG_20D"]) else None,
        liquidity_tightness_score=score,
        is_liquidity_tight=bool(score is not None and score > 0.7),
        components={
            "w_z_hy_oas": 0.25,
            "w_z_ig_oas": 0.15,
            "w_z_hy_minus_ig_oas": 0.10,
            "w_z_ust_10y_chg_20d": 0.10,
            "w_z_curve_10y_2y": 0.10,
            "w_z_real_policy_rate": 0.10,
            "w_z_tga_chg_28d": 0.10,
            "w_z_rrp_chg_20d": 0.10,
        },
    )

    return LiquidityState(
        asof=str(pd.to_datetime(last["date"]).date()),
        start_date=start_date,
        inputs=inputs,
        notes=(
            "Liquidity & funding tightness: weighted z-score composite of credit spreads (HY/IG + divergence), "
            "rates/curve (10Y change + 10-2 slope), real policy rate, and funding plumbing (TGA, RRP). "
            "Positive = tighter constraints / worse liquidity."
        ),
    )


