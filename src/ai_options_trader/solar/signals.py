from __future__ import annotations

from typing import Iterable

import pandas as pd

from ai_options_trader.config import Settings
from ai_options_trader.data.market import fetch_equity_daily_closes
from ai_options_trader.macro.transforms import zscore
from ai_options_trader.solar.models import SolarInputs, SolarState


SOLAR_CORE_TICKERS: tuple[str, ...] = (
    # Module / cell manufacturers (silver cost sensitivity)
    "FSLR",  # First Solar
    "CSIQ",  # Canadian Solar
    "JKS",   # JinkoSolar
    "SPWR",  # SunPower
)

# Basket used for regime calc: emphasize core manufacturers + ETF proxy.
SOLAR_TICKERS: tuple[str, ...] = (
    "TAN",   # Solar ETF (market proxy)
    *SOLAR_CORE_TICKERS,
)


def _ret_pct(px: pd.Series, days: int) -> pd.Series:
    return (px / px.shift(int(days)) - 1.0) * 100.0


def _basket_index(px: pd.DataFrame, tickers: Iterable[str]) -> pd.Series:
    cols = [t for t in tickers if t in px.columns]
    if not cols:
        return pd.Series(dtype=float)
    base = px[cols].iloc[0].replace(0, pd.NA)
    norm = px[cols].div(base, axis=1) * 100.0
    return norm.mean(axis=1)


def build_solar_dataset(settings: Settings, start_date: str = "2011-01-01", refresh: bool = False) -> pd.DataFrame:
    """
    Solar regime dataset (MVP):
    - Solar basket 60d return (equal-weighted index)
    - Solar relative 60d return vs SPY
    - Silver 60d return (SLV proxy)
    - Z-scores + headwind score (silver up vs solar rel down)
    """
    symbols = sorted(set(SOLAR_TICKERS + ("SPY", "SLV")))
    px = fetch_equity_daily_closes(settings=settings, symbols=symbols, start=start_date, refresh=bool(refresh))
    px = px.sort_index().ffill().dropna(how="all")
    if px.empty:
        raise RuntimeError("No price data for solar basket.")

    solar_idx = _basket_index(px, SOLAR_TICKERS)
    if solar_idx.empty:
        raise RuntimeError("Solar basket missing price data.")

    spy = px["SPY"] if "SPY" in px.columns else None
    slv = px["SLV"] if "SLV" in px.columns else None
    if spy is None or slv is None:
        raise RuntimeError("Missing SPY or SLV price data for solar regime.")

    df = pd.DataFrame({"date": solar_idx.index})
    df["SOLAR_BASKET"] = solar_idx.values
    df["SOLAR_RET_60D"] = _ret_pct(solar_idx, 60).values
    df["SPY_RET_60D"] = _ret_pct(spy, 60).values
    df["SOLAR_REL_RET_60D"] = df["SOLAR_RET_60D"] - df["SPY_RET_60D"]
    df["SILVER_RET_60D"] = _ret_pct(slv, 60).values

    win = 252 * 3
    df["Z_SOLAR_REL_RET_60D"] = zscore(pd.to_numeric(df["SOLAR_REL_RET_60D"], errors="coerce"), window=win)
    df["Z_SILVER_RET_60D"] = zscore(pd.to_numeric(df["SILVER_RET_60D"], errors="coerce"), window=win)

    z_solar = pd.to_numeric(df["Z_SOLAR_REL_RET_60D"], errors="coerce")
    z_silver = pd.to_numeric(df["Z_SILVER_RET_60D"], errors="coerce")
    df["SOLAR_HEADWIND_SCORE"] = (0.60 * z_silver) - (0.40 * z_solar)

    return df


def build_solar_state(settings: Settings, start_date: str = "2011-01-01", refresh: bool = False) -> SolarState:
    df = build_solar_dataset(settings=settings, start_date=start_date, refresh=refresh)
    last = df.dropna(subset=["SOLAR_BASKET"]).iloc[-1]
    win = 252 * 3

    def _f(k: str) -> float | None:
        try:
            v = last.get(k)
            return float(v) if v is not None and pd.notna(v) else None
        except Exception:
            return None

    inp = SolarInputs(
        solar_ret_60d=_f("SOLAR_RET_60D"),
        solar_rel_ret_60d=_f("SOLAR_REL_RET_60D"),
        silver_ret_60d=_f("SILVER_RET_60D"),
        z_solar_rel_ret_60d=_f("Z_SOLAR_REL_RET_60D"),
        z_silver_ret_60d=_f("Z_SILVER_RET_60D"),
        solar_headwind_score=_f("SOLAR_HEADWIND_SCORE"),
        components={"window_days": float(win), "rel_ret_window_days": 60.0},
    )
    return SolarState(
        asof=str(pd.to_datetime(last["date"]).date()),
        start_date=start_date,
        inputs=inp,
        notes="Solar regime MVP: solar basket vs SPY relative return and silver (SLV) momentum.",
    )
