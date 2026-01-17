from __future__ import annotations

from typing import Dict

import pandas as pd

from ai_options_trader.config import Settings
from ai_options_trader.data.fred import FredClient
from ai_options_trader.funding.models import FundingInputs, FundingState
from ai_options_trader.funding.nyfed import fetch_nyfed_secured_rate
from ai_options_trader.macro.transforms import merge_series_daily


FUNDING_FRED_SERIES: Dict[str, str] = {
    "EFFR": "DFF",
    "SOFR": "SOFR",
    "TGCR": "TGCR",
    "BGCR": "BGCR",
    # Optional cross-checks
    "OBFR": "OBFR",
}

# Treat TGCR/BGCR as best-effort: some environments see intermittent FRED 400s for these series.
# The regime can still run using SOFR vs IORB/EFFR even if collateral segmentation is unavailable.
_OPTIONAL_SERIES = {"OBFR", "TGCR", "BGCR"}

# IORB naming depends on vintage; try in order.
_IORB_CANDIDATES = ("IORB", "IOER")


def _fetch_optional(*, fred: FredClient, series_id: str, start_date: str, refresh: bool) -> pd.DataFrame | None:
    try:
        return fred.fetch_series(series_id=series_id, start_date=start_date, refresh=refresh)
    except Exception:
        return None


def _as_bps(x: pd.Series) -> pd.Series:
    """Percent -> basis points."""
    return pd.to_numeric(x, errors="coerce") * 100.0


def _recent_baseline(series: pd.Series, window: int) -> tuple[float | None, float | None]:
    s = pd.to_numeric(series, errors="coerce").dropna()
    if s.empty:
        return None, None
    tail = s.iloc[-window:] if s.shape[0] >= window else s
    if tail.empty:
        return None, None
    return float(tail.median()), float(tail.std(ddof=0))


def build_funding_dataset(settings: Settings, start_date: str = "2011-01-01", refresh: bool = False) -> pd.DataFrame:
    if not settings.FRED_API_KEY:
        raise RuntimeError("Missing FRED_API_KEY in environment / .env")

    fred = FredClient(api_key=settings.FRED_API_KEY)

    frames: Dict[str, pd.DataFrame] = {}
    for name, sid in FUNDING_FRED_SERIES.items():
        if name in _OPTIONAL_SERIES:
            df = _fetch_optional(fred=fred, series_id=sid, start_date=start_date, refresh=refresh)
            if df is None or df.empty:
                # Fallback: TGCR/BGCR are published by NY Fed; use their public API when FRED is flaky/missing.
                if name in {"TGCR", "BGCR"}:
                    try:
                        r = fetch_nyfed_secured_rate(
                            rate=("tgcr" if name == "TGCR" else "bgcr"),
                            start_date=start_date,
                            refresh=bool(refresh),
                        )
                        if r.df is not None and not r.df.empty:
                            df2 = r.df.rename(columns={"value": name}).copy()
                            df2 = df2[["date", name]]
                            frames[name] = df2.sort_values("date").reset_index(drop=True)
                            continue
                    except Exception:
                        pass
                continue
        else:
            df = fred.fetch_series(series_id=sid, start_date=start_date, refresh=refresh)
        if df is not None and not df.empty:
            frames[name] = df.sort_values("date").reset_index(drop=True)

    # IORB (optional) with fallbacks
    iorb_df = None
    iorb_sid = None
    for sid in _IORB_CANDIDATES:
        iorb_df = _fetch_optional(fred=fred, series_id=sid, start_date=start_date, refresh=refresh)
        if iorb_df is not None and not iorb_df.empty:
            iorb_sid = sid
            break
    if iorb_df is not None and not iorb_df.empty:
        frames["IORB"] = iorb_df.sort_values("date").reset_index(drop=True)

    # Use business-day grid (funding spreads are trading-day concepts)
    max_date = max(df["date"].max() for df in frames.values())
    base = pd.DataFrame({"date": pd.date_range(start=pd.to_datetime(start_date), end=pd.to_datetime(max_date), freq="B")})
    merged = merge_series_daily(base, frames, ffill=True)

    # Ensure stable columns exist even when best-effort series are unavailable.
    for c in ("TGCR", "BGCR", "OBFR", "IORB"):
        if c not in merged.columns:
            merged[c] = pd.NA

    # Spreads (bps)
    merged["SOFR_EFFR_BPS"] = _as_bps(merged["SOFR"] - merged["EFFR"])
    merged["BGCR_TGCR_BPS"] = pd.NA
    if "BGCR" in merged.columns and "TGCR" in merged.columns:
        merged["BGCR_TGCR_BPS"] = _as_bps(merged["BGCR"] - merged["TGCR"])
    if "IORB" in merged.columns:
        # Only prefer IORB if it actually has numeric values.
        if pd.to_numeric(merged["IORB"], errors="coerce").dropna().shape[0] > 0:
            merged["SOFR_IORB_BPS"] = _as_bps(merged["SOFR"] - merged["IORB"])
            merged["CORRIDOR_SPREAD_BPS"] = merged["SOFR_IORB_BPS"]
            merged["CORRIDOR_NAME"] = "SOFR-IORB"
            merged["IORB_SID"] = iorb_sid or ""
        else:
            merged["CORRIDOR_SPREAD_BPS"] = merged["SOFR_EFFR_BPS"]
            merged["CORRIDOR_NAME"] = "SOFR-EFFR"
            merged["IORB_SID"] = ""
    else:
        merged["CORRIDOR_SPREAD_BPS"] = merged["SOFR_EFFR_BPS"]
        merged["CORRIDOR_NAME"] = "SOFR-EFFR"
        merged["IORB_SID"] = ""

    # Baseline calibration (distributional, last ~3y by default)
    win_hist = 252 * 3
    base_med, base_sd = _recent_baseline(merged["CORRIDOR_SPREAD_BPS"], window=win_hist)

    # Start with a simple multiplier in the recommended range; tune after eyeballing distributions.
    k_stress = 1.75
    k_tight = 1.0
    tight_thr = (base_med + k_tight * base_sd) if (base_med is not None and base_sd is not None) else None
    stress_thr = (base_med + k_stress * base_sd) if (base_med is not None and base_sd is not None) else None

    # Spike / persistence / volatility indicators
    merged["SPIKE_5D_BPS"] = pd.to_numeric(merged["CORRIDOR_SPREAD_BPS"], errors="coerce").rolling(5).max()
    merged["VOL_20D_BPS"] = pd.to_numeric(merged["CORRIDOR_SPREAD_BPS"], errors="coerce").rolling(20).std(ddof=0)
    if stress_thr is not None:
        above = (pd.to_numeric(merged["CORRIDOR_SPREAD_BPS"], errors="coerce") > float(stress_thr)).astype(float)
        merged["PERSIST_20D"] = above.rolling(20).mean()
    else:
        merged["PERSIST_20D"] = pd.NA

    # Distributional baselines for persistence + vol (avoid fixed 0.1/0.3 cutoffs).
    p_base, p_sd = _recent_baseline(merged["PERSIST_20D"], window=win_hist)
    vol_base, vol_sd = _recent_baseline(merged["VOL_20D_BPS"], window=win_hist)

    merged["BASELINE_MED_BPS"] = base_med
    merged["BASELINE_SD_BPS"] = base_sd
    merged["TIGHT_THR_BPS"] = tight_thr
    merged["STRESS_THR_BPS"] = stress_thr
    merged["P_BASE"] = p_base
    merged["P_TIGHT"] = (p_base + 1.0 * p_sd) if (p_base is not None and p_sd is not None) else None
    merged["P_STRESS"] = (p_base + 2.0 * p_sd) if (p_base is not None and p_sd is not None) else None
    merged["VOL_BASE"] = vol_base
    merged["VOL_TIGHT"] = (vol_base + 1.0 * vol_sd) if (vol_base is not None and vol_sd is not None) else None
    merged["VOL_STRESS"] = (vol_base + 2.0 * vol_sd) if (vol_base is not None and vol_sd is not None) else None
    merged["K_STRESS"] = float(k_stress)

    return merged


def build_funding_state(settings: Settings, start_date: str = "2011-01-01", refresh: bool = False) -> FundingState:
    df = build_funding_dataset(settings=settings, start_date=start_date, refresh=refresh)
    # Only require the corridor core; TGCR/BGCR are best-effort.
    last = df.dropna(subset=["EFFR", "SOFR", "CORRIDOR_SPREAD_BPS"]).iloc[-1]

    inp = FundingInputs(
        effr=float(last["EFFR"]) if pd.notna(last["EFFR"]) else None,
        sofr=float(last["SOFR"]) if pd.notna(last["SOFR"]) else None,
        tgcr=float(last["TGCR"]) if pd.notna(last["TGCR"]) else None,
        bgcr=float(last["BGCR"]) if pd.notna(last["BGCR"]) else None,
        obfr=float(last["OBFR"]) if "OBFR" in last and pd.notna(last["OBFR"]) else None,
        iorb=float(last["IORB"]) if "IORB" in last and pd.notna(last["IORB"]) else None,
        spread_corridor_bps=float(last["CORRIDOR_SPREAD_BPS"]) if pd.notna(last["CORRIDOR_SPREAD_BPS"]) else None,
        spread_corridor_name=str(last.get("CORRIDOR_NAME") or "") or None,
        spread_sofr_effr_bps=float(last["SOFR_EFFR_BPS"]) if pd.notna(last.get("SOFR_EFFR_BPS")) else None,
        spread_bgcr_tgcr_bps=float(last["BGCR_TGCR_BPS"]) if pd.notna(last.get("BGCR_TGCR_BPS")) else None,
        spike_5d_bps=float(last["SPIKE_5D_BPS"]) if pd.notna(last.get("SPIKE_5D_BPS")) else None,
        persistence_20d=float(last["PERSIST_20D"]) if pd.notna(last.get("PERSIST_20D")) else None,
        vol_20d_bps=float(last["VOL_20D_BPS"]) if pd.notna(last.get("VOL_20D_BPS")) else None,
        baseline_median_bps=float(last["BASELINE_MED_BPS"]) if pd.notna(last.get("BASELINE_MED_BPS")) else None,
        baseline_std_bps=float(last["BASELINE_SD_BPS"]) if pd.notna(last.get("BASELINE_SD_BPS")) else None,
        tight_threshold_bps=float(last["TIGHT_THR_BPS"]) if pd.notna(last.get("TIGHT_THR_BPS")) else None,
        stress_threshold_bps=float(last["STRESS_THR_BPS"]) if pd.notna(last.get("STRESS_THR_BPS")) else None,
        persistence_baseline=float(last["P_BASE"]) if pd.notna(last.get("P_BASE")) else None,
        persistence_tight=float(last["P_TIGHT"]) if pd.notna(last.get("P_TIGHT")) else None,
        persistence_stress=float(last["P_STRESS"]) if pd.notna(last.get("P_STRESS")) else None,
        vol_baseline_bps=float(last["VOL_BASE"]) if pd.notna(last.get("VOL_BASE")) else None,
        vol_tight_bps=float(last["VOL_TIGHT"]) if pd.notna(last.get("VOL_TIGHT")) else None,
        vol_stress_bps=float(last["VOL_STRESS"]) if pd.notna(last.get("VOL_STRESS")) else None,
        components={
            "baseline_window_days": float(252 * 3),
            "k_stress": float(last.get("K_STRESS")) if pd.notna(last.get("K_STRESS")) else 1.75,
        },
    )

    return FundingState(
        asof=str(pd.to_datetime(last["date"]).date()),
        start_date=start_date,
        inputs=inp,
        notes=(
            "Funding regime (secured rates): corridor dislocations (SOFR vs IORB/EFFR), "
            "collateral segmentation (BGCR vs TGCR), and spike/persistence/volatility indicators."
        ),
    )


