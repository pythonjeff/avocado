from __future__ import annotations

from typing import Dict

import pandas as pd

from ai_options_trader.config import Settings
from ai_options_trader.data.fred import FredClient
from ai_options_trader.data.market import fetch_equity_daily_closes
from ai_options_trader.macro.transforms import merge_series_daily, zscore
from ai_options_trader.volatility.models import VolatilityInputs, VolatilityState


VOL_FRED_SERIES: Dict[str, str] = {
    # CBOE VIX (daily close)
    "VIX": "VIXCLS",
    # Optional term structure points (availability can vary by FRED behavior)
    "VIX9D": "VIX9D",
    "VIX3M": "VIX3M",
}


def build_volatility_dataset(settings: Settings, start_date: str = "2011-01-01", refresh: bool = False) -> pd.DataFrame:
    if not settings.FRED_API_KEY:
        raise RuntimeError("Missing FRED_API_KEY in environment / .env")

    fred = FredClient(api_key=settings.FRED_API_KEY)
    frames: Dict[str, pd.DataFrame] = {}

    for name, sid in VOL_FRED_SERIES.items():
        try:
            df = fred.fetch_series(series_id=sid, start_date=start_date, refresh=refresh)
        except Exception:
            if name in {"VIX9D", "VIX3M"}:
                continue
            raise
        if df is None or df.empty:
            if name in {"VIX9D", "VIX3M"}:
                continue
            raise RuntimeError(f"Failed to load vol series {name} ({sid})")
        frames[name] = df.sort_values("date").reset_index(drop=True)

    max_date = max(df["date"].max() for df in frames.values())
    base = pd.DataFrame({"date": pd.date_range(start=pd.to_datetime(start_date), end=pd.to_datetime(max_date), freq="D")})
    merged = merge_series_daily(base, frames, ffill=True)

    vix = pd.to_numeric(merged["VIX"], errors="coerce")
    merged["VIX_CHG_1D_PCT"] = (vix / vix.shift(1) - 1.0) * 100.0
    merged["VIX_CHG_5D_PCT"] = (vix / vix.shift(5) - 1.0) * 100.0

    # Term structure anchor:
    # Prefer FRED VIX3M when available; otherwise best-effort fallback to FMP VXV (3-month VIX index).
    term_source = None
    vix3m = pd.to_numeric(merged["VIX3M"], errors="coerce") if "VIX3M" in merged.columns else None
    if vix3m is not None and not vix3m.dropna().empty:
        term_source = "fred:VIX3M"
    else:
        # Best-effort: use FMP price history for VXV (and VIX as needed).
        if getattr(settings, "fmp_api_key", None):
            try:
                # Try common symbol spellings; FMP support can vary.
                px = None
                for pair in (("VIX", "VXV"), ("^VIX", "^VXV")):
                    try:
                        px0 = fetch_equity_daily_closes(settings=settings, symbols=[pair[0], pair[1]], start=start_date, refresh=bool(refresh))
                        if px0 is not None and (not px0.empty) and all(c in px0.columns for c in pair):
                            px = px0.rename(columns={pair[1]: "VXV_ANCHOR"})
                            break
                    except Exception:
                        continue
                if px is not None and (not px.empty) and "VXV_ANCHOR" in px.columns:
                    # Align by date.
                    dts = pd.to_datetime(merged["date"], errors="coerce")
                    m = merged.copy()
                    m["date"] = dts
                    m = m.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
                    # Join VXV anchor (ffill to daily grid).
                    vxv = pd.to_numeric(px["VXV_ANCHOR"], errors="coerce").sort_index()
                    vxv = vxv[~vxv.index.duplicated(keep="last")]
                    m_idx = m.set_index("date")
                    m_idx["VIX3M"] = m_idx.get("VIX3M")  # preserve if it existed
                    m_idx["VIX3M_FMP_VXV"] = vxv.reindex(m_idx.index).ffill()
                    # If VIX3M missing, use VXV proxy.
                    m_idx["VIX3M"] = pd.to_numeric(m_idx.get("VIX3M"), errors="coerce")
                    m_idx["VIX3M"] = m_idx["VIX3M"].where(m_idx["VIX3M"].notna(), m_idx["VIX3M_FMP_VXV"])
                    merged = m_idx.reset_index()
                    vix = pd.to_numeric(merged["VIX"], errors="coerce")
                    vix3m = pd.to_numeric(merged["VIX3M"], errors="coerce")
                    if not vix3m.dropna().empty:
                        term_source = "fmp:VXV"
            except Exception:
                term_source = None

    if vix3m is not None and "VIX3M" in merged.columns:
        merged["VIX_TERM_SPREAD"] = vix - pd.to_numeric(merged["VIX3M"], errors="coerce")
        merged["VIX_TERM_SOURCE"] = term_source

    win = 252 * 3
    merged["Z_VIX"] = zscore(vix, window=win)
    merged["Z_VIX_CHG_5D"] = zscore(pd.to_numeric(merged["VIX_CHG_5D_PCT"], errors="coerce"), window=win)
    if "VIX_TERM_SPREAD" in merged.columns:
        merged["Z_VIX_TERM"] = zscore(pd.to_numeric(merged["VIX_TERM_SPREAD"], errors="coerce"), window=win)

    # Spike and persistence (dynamic threshold)
    merged["SPIKE_20D_PCT"] = pd.to_numeric(merged["VIX_CHG_5D_PCT"], errors="coerce").rolling(20).max()
    baseline_med = vix.rolling(win).median()
    baseline_std = vix.rolling(win).std(ddof=0)
    merged["THRESH_VIX"] = baseline_med + 1.5 * baseline_std
    merged["PERSIST_20D"] = (vix > merged["THRESH_VIX"]).rolling(20).mean()

    # Composite pressure score (stable-ish)
    merged["VOL_PRESSURE_SCORE"] = 0.55 * merged["Z_VIX"] + 0.35 * merged["Z_VIX_CHG_5D"]
    if "Z_VIX_TERM" in merged.columns:
        merged["VOL_PRESSURE_SCORE"] = merged["VOL_PRESSURE_SCORE"] + 0.10 * merged["Z_VIX_TERM"]

    return merged


def build_volatility_state(settings: Settings, start_date: str = "2011-01-01", refresh: bool = False) -> VolatilityState:
    df = build_volatility_dataset(settings=settings, start_date=start_date, refresh=refresh)
    last = df.dropna(subset=["VIX"]).iloc[-1]
    win = 252 * 3

    inp = VolatilityInputs(
        vix=float(last["VIX"]) if pd.notna(last.get("VIX")) else None,
        vix9d=float(last["VIX9D"]) if "VIX9D" in last and pd.notna(last.get("VIX9D")) else None,
        vix3m=float(last["VIX3M"]) if "VIX3M" in last and pd.notna(last.get("VIX3M")) else None,
        vix_chg_1d_pct=float(last["VIX_CHG_1D_PCT"]) if pd.notna(last.get("VIX_CHG_1D_PCT")) else None,
        vix_chg_5d_pct=float(last["VIX_CHG_5D_PCT"]) if pd.notna(last.get("VIX_CHG_5D_PCT")) else None,
        vix_term_spread=float(last["VIX_TERM_SPREAD"])
        if "VIX_TERM_SPREAD" in last and pd.notna(last.get("VIX_TERM_SPREAD"))
        else None,
        vix_term_source=str(last.get("VIX_TERM_SOURCE") or "").strip() or None,
        z_vix=float(last["Z_VIX"]) if pd.notna(last.get("Z_VIX")) else None,
        z_vix_chg_5d=float(last["Z_VIX_CHG_5D"]) if pd.notna(last.get("Z_VIX_CHG_5D")) else None,
        z_vix_term=float(last["Z_VIX_TERM"]) if "Z_VIX_TERM" in last and pd.notna(last.get("Z_VIX_TERM")) else None,
        spike_20d_pct=float(last["SPIKE_20D_PCT"]) if pd.notna(last.get("SPIKE_20D_PCT")) else None,
        persist_20d=float(last["PERSIST_20D"]) if pd.notna(last.get("PERSIST_20D")) else None,
        threshold_vix=float(last["THRESH_VIX"]) if pd.notna(last.get("THRESH_VIX")) else None,
        vol_pressure_score=float(last["VOL_PRESSURE_SCORE"]) if pd.notna(last.get("VOL_PRESSURE_SCORE")) else None,
        components={"window_days": float(win), "persist_days": 20.0},
    )

    return VolatilityState(
        asof=str(pd.to_datetime(last["date"]).date()),
        start_date=start_date,
        inputs=inp,
        notes="Volatility regime MVP: VIX level + 5d momentum + optional term structure, standardized vs recent history.",
    )


