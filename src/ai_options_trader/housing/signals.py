from __future__ import annotations

from typing import Dict

import pandas as pd

from ai_options_trader.config import Settings
from ai_options_trader.data.fred import FredClient
from ai_options_trader.data.market import fetch_equity_daily_closes
from ai_options_trader.macro.transforms import merge_series_daily, zscore
from ai_options_trader.housing.models import HousingInputs, HousingState


HOUSING_FRED_SERIES: Dict[str, str] = {
    # 30-year fixed mortgage rate (weekly; FRED will return weekly points we ffill onto daily grid)
    "MORTGAGE_30Y": "MORTGAGE30US",
    # 10Y Treasury constant maturity
    "UST_10Y": "DGS10",
}


def _ret_pct(px: pd.Series, days: int) -> pd.Series:
    return (px / px.shift(int(days)) - 1.0) * 100.0


def build_housing_dataset(settings: Settings, start_date: str = "2011-01-01", refresh: bool = False) -> pd.DataFrame:
    """
    Housing / MBS regime dataset (best-effort).

    Features (MVP):
    - Mortgage spread: 30y mortgage rate - 10y UST, z-scored
    - Market proxies:
        - MBS relative performance (MBB vs IEF) over 60d, z-scored
        - Homebuilder relative performance (ITB vs SPY) over 60d, z-scored
        - REIT relative performance (VNQ vs SPY) over 60d, z-scored
    - Composite housing pressure score
    """
    if not settings.FRED_API_KEY:
        raise RuntimeError("Missing FRED_API_KEY in environment / .env")

    fred = FredClient(api_key=settings.FRED_API_KEY)
    frames: Dict[str, pd.DataFrame] = {}
    for name, sid in HOUSING_FRED_SERIES.items():
        df = fred.fetch_series(series_id=sid, start_date=start_date, refresh=refresh)
        if df is None or df.empty:
            raise RuntimeError(f"Failed to load housing series {name} ({sid})")
        frames[name] = df.sort_values("date").reset_index(drop=True)

    max_date = max(df["date"].max() for df in frames.values())
    base = pd.DataFrame({"date": pd.date_range(start=pd.to_datetime(start_date), end=pd.to_datetime(max_date), freq="D")})
    merged = merge_series_daily(base, frames, ffill=True)

    mort = pd.to_numeric(merged["MORTGAGE_30Y"], errors="coerce")
    ust10 = pd.to_numeric(merged["UST_10Y"], errors="coerce")
    merged["MORTGAGE_SPREAD"] = mort - ust10

    win = 252 * 3
    merged["Z_MORTGAGE_SPREAD"] = zscore(pd.to_numeric(merged["MORTGAGE_SPREAD"], errors="coerce"), window=win)

    # Market proxies (ETF closes)
    # NOTE: This uses the configured historical price source (FMP by default).
    px_syms = ["MBB", "IEF", "ITB", "SPY", "VNQ"]
    try:
        px = fetch_equity_daily_closes(settings=settings, symbols=px_syms, start=start_date, refresh=bool(refresh)).sort_index().ffill()
    except Exception:
        px = pd.DataFrame()

    if not px.empty:
        r60 = pd.DataFrame({s: _ret_pct(px[s], 60) for s in px.columns if s in px.columns})
        # Relative returns
        if "MBB" in r60.columns and "IEF" in r60.columns:
            merged["MBS_REL_RET_60D"] = r60["MBB"] - r60["IEF"]
            merged["Z_MBS_REL_RET_60D"] = zscore(pd.to_numeric(merged["MBS_REL_RET_60D"], errors="coerce"), window=win)
        if "ITB" in r60.columns and "SPY" in r60.columns:
            merged["HOMEBUILDER_REL_RET_60D"] = r60["ITB"] - r60["SPY"]
            merged["Z_HOMEBUILDER_REL_RET_60D"] = zscore(pd.to_numeric(merged["HOMEBUILDER_REL_RET_60D"], errors="coerce"), window=win)
        if "VNQ" in r60.columns and "SPY" in r60.columns:
            merged["REIT_REL_RET_60D"] = r60["VNQ"] - r60["SPY"]
            merged["Z_REIT_REL_RET_60D"] = zscore(pd.to_numeric(merged["REIT_REL_RET_60D"], errors="coerce"), window=win)

    # Composite score: higher mortgage spreads + weak housing/REIT/MBS relative performance => stress.
    z_spread = pd.to_numeric(merged.get("Z_MORTGAGE_SPREAD"), errors="coerce")
    z_mbs = pd.to_numeric(merged.get("Z_MBS_REL_RET_60D"), errors="coerce")
    z_itb = pd.to_numeric(merged.get("Z_HOMEBUILDER_REL_RET_60D"), errors="coerce")
    z_reit = pd.to_numeric(merged.get("Z_REIT_REL_RET_60D"), errors="coerce")

    merged["HOUSING_PRESSURE_SCORE"] = (0.55 * z_spread) - (0.20 * z_mbs) - (0.15 * z_itb) - (0.10 * z_reit)

    return merged


def build_housing_state(settings: Settings, start_date: str = "2011-01-01", refresh: bool = False) -> HousingState:
    df = build_housing_dataset(settings=settings, start_date=start_date, refresh=refresh)
    last = df.dropna(subset=["MORTGAGE_30Y", "UST_10Y"]).iloc[-1]
    win = 252 * 3

    def _f(k: str) -> float | None:
        try:
            v = last.get(k)
            return float(v) if v is not None and pd.notna(v) else None
        except Exception:
            return None

    inp = HousingInputs(
        mortgage_30y=_f("MORTGAGE_30Y"),
        ust_10y=_f("UST_10Y"),
        mortgage_spread=_f("MORTGAGE_SPREAD"),
        z_mortgage_spread=_f("Z_MORTGAGE_SPREAD"),
        z_mbs_rel_ret_60d=_f("Z_MBS_REL_RET_60D"),
        z_homebuilder_rel_ret_60d=_f("Z_HOMEBUILDER_REL_RET_60D"),
        z_reit_rel_ret_60d=_f("Z_REIT_REL_RET_60D"),
        housing_pressure_score=_f("HOUSING_PRESSURE_SCORE"),
        components={"window_days": float(win), "rel_ret_window_days": 60.0},
    )
    return HousingState(
        asof=str(pd.to_datetime(last["date"]).date()),
        start_date=start_date,
        inputs=inp,
        notes="Housing/MBS regime MVP: mortgage spread stress + market proxies (MBB vs IEF, ITB vs SPY, VNQ vs SPY).",
    )

