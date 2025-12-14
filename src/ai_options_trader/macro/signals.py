from __future__ import annotations

from typing import Dict
import pandas as pd

from ai_options_trader.config import Settings
from ai_options_trader.macro.fred import FredClient, DEFAULT_SERIES
from ai_options_trader.macro.transforms import (
    to_daily_index,
    merge_series_daily,
    yoy_from_index_level,
    annualized_rate_from_levels,
    zscore,
)
from ai_options_trader.macro.models import MacroState, MacroInputs


def build_macro_dataset(settings: Settings, start_date: str = "2016-01-01", refresh: bool = False) -> pd.DataFrame:
    if not settings.FRED_API_KEY:
        raise RuntimeError("Missing FRED_API_KEY in environment / .env")

    fred = FredClient(api_key=settings.FRED_API_KEY)

    series_frames: Dict[str, pd.DataFrame] = {}
    for sid in DEFAULT_SERIES.keys():
        series_frames[sid] = fred.fetch_series(series_id=sid, start_date=start_date, refresh=refresh)

    # Compute CPI-derived metrics on the *monthly* CPI observations, then ffill them
    # onto the daily grid. If we compute these after forward-filling CPI to daily,
    # the "3m" window may land entirely in a flat (no-new-CPI) region and show 0.0.
    if "CPIAUCSL" in series_frames:
        cpi = series_frames["CPIAUCSL"].copy().sort_values("date")
        cpi["CPI_YOY"] = cpi["value"].pct_change(12) * 100.0
        cpi["CPI_3M_ANN"] = ((cpi["value"] / cpi["value"].shift(3)) ** (12.0 / 3.0) - 1.0) * 100.0
        cpi["CPI_6M_ANN"] = ((cpi["value"] / cpi["value"].shift(6)) ** (12.0 / 6.0) - 1.0) * 100.0
        series_frames["CPIAUCSL"] = cpi

    if "CPILFESL" in series_frames:
        core = series_frames["CPILFESL"].copy().sort_values("date")
        core["CORE_CPI_YOY"] = core["value"].pct_change(12) * 100.0
        series_frames["CPILFESL"] = core

    # Create daily index and merge (monthly series will be forward-filled)
    # Use the max date across all series
    max_date = max(df["date"].max() for df in series_frames.values())
    base = pd.DataFrame({"date": pd.date_range(start=pd.to_datetime(start_date), end=pd.to_datetime(max_date), freq="D")})
    merged = merge_series_daily(base, series_frames, ffill=True)

    # Rates/expectations derived
    merged["CURVE_2S10S"] = merged["DGS10"] - merged["DGS2"]
    merged["REAL_YIELD_PROXY_10Y"] = merged["DGS10"] - merged["T10YIE"]
    merged["INFL_MOM_MINUS_BE5Y"] = merged["CPI_6M_ANN"] - merged["T5YIE"]

    # Composite disconnect score: z-scored components (you can tune weights)
    merged["Z_INFL_MOM_MINUS_BE5Y"] = zscore(merged["INFL_MOM_MINUS_BE5Y"], window=252)
    merged["Z_REAL_YIELD_PROXY_10Y"] = zscore(merged["REAL_YIELD_PROXY_10Y"], window=252)

    merged["DISCONNECT_SCORE"] = 0.6 * merged["Z_INFL_MOM_MINUS_BE5Y"] + 0.4 * merged["Z_REAL_YIELD_PROXY_10Y"]

    return merged


def build_macro_state(settings: Settings, start_date: str = "2016-01-01", refresh: bool = False) -> MacroState:
    df = build_macro_dataset(settings=settings, start_date=start_date, refresh=refresh)
    last = df.dropna(subset=["CPIAUCSL", "DGS10", "T5YIE"]).iloc[-1]

    inputs = MacroInputs(
        cpi_yoy=float(last["CPI_YOY"]) if pd.notna(last["CPI_YOY"]) else None,
        core_cpi_yoy=float(last["CORE_CPI_YOY"]) if pd.notna(last["CORE_CPI_YOY"]) else None,
        cpi_3m_annualized=float(last["CPI_3M_ANN"]) if pd.notna(last["CPI_3M_ANN"]) else None,
        cpi_6m_annualized=float(last["CPI_6M_ANN"]) if pd.notna(last["CPI_6M_ANN"]) else None,
        breakeven_5y=float(last["T5YIE"]) if pd.notna(last["T5YIE"]) else None,
        breakeven_10y=float(last["T10YIE"]) if pd.notna(last["T10YIE"]) else None,
        eff_fed_funds=float(last["DFF"]) if pd.notna(last["DFF"]) else None,
        ust_2y=float(last["DGS2"]) if pd.notna(last["DGS2"]) else None,
        ust_10y=float(last["DGS10"]) if pd.notna(last["DGS10"]) else None,
        curve_2s10s=float(last["CURVE_2S10S"]) if pd.notna(last["CURVE_2S10S"]) else None,
        real_yield_proxy_10y=float(last["REAL_YIELD_PROXY_10Y"]) if pd.notna(last["REAL_YIELD_PROXY_10Y"]) else None,
        inflation_momentum_minus_be5y=float(last["INFL_MOM_MINUS_BE5Y"]) if pd.notna(last["INFL_MOM_MINUS_BE5Y"]) else None,
        disconnect_score=float(last["DISCONNECT_SCORE"]) if pd.notna(last["DISCONNECT_SCORE"]) else None,
        components={
            "z_infl_mom_minus_be5y": float(last["Z_INFL_MOM_MINUS_BE5Y"]) if pd.notna(last["Z_INFL_MOM_MINUS_BE5Y"]) else None,
            "z_real_yield_proxy_10y": float(last["Z_REAL_YIELD_PROXY_10Y"]) if pd.notna(last["Z_REAL_YIELD_PROXY_10Y"]) else None,
        },
    )

    return MacroState(
        asof=str(pd.to_datetime(last["date"]).date()),
        start_date=start_date,
        inputs=inputs,
        notes="Disconnect score combines inflation momentum vs breakevens and a real-yield proxy (z-scored).",
    )
