"""
Offshore USD funding stress — composite signal from FRED-available series.

True cross-currency basis (CCB) is Bloomberg-only; the liquid 3m EUR/USD and
USD/JPY basis swaps aren't published on FRED. This module builds the cleanest
composite that *is* available from public data:

  1. SWPT — Central Bank Liquidity Swaps (H.4.1 weekly).  Binary crisis signal.
     Near zero in normal times; spiked to $450B in March 2020.  When >$1B,
     the Fed is *actively bailing out offshore USD funding* — unambiguous.

  2. DTWEXBGS / DTWEXAFEGS / DTWEXEMEGS — broad / advanced-foreign-economy /
     EM-economy dollar indices.  Divergence reveals which corridor is bidding
     for dollars.  Broad >> AFE = EM-led USD demand (classic funding stress
     pattern: Turkey 2018, EM 2022).  AFE ≈ broad = balanced.

  3. Composite score (0-100, higher = more stress) with driver attribution.
     Folds both signals into a single readout for the synthesis brief.

Display-only by design — does NOT currently feed the funding regime score.
This matches the precedent set by the equity-transmission module.  If the
signal proves reliable, promotion to the score is a one-line change.

Caveat for the user: this composite captures *episodic* and *trend* offshore
stress.  It will miss the daily-frequency basis-swap moves that institutional
desks see in Bloomberg — the most you'll get from FRED is weekly H.4.1 plus
daily dollar-index momentum.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from lox.config import load_settings
from lox.data.fred import FredClient


# ─────────────────────────────────────────────────────────────────────────────
# Dataclass
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class OffshoreStress:
    """Snapshot of offshore USD funding stress signals."""
    asof: Optional[str] = None
    # Central bank swap lines — Fed bailout indicator
    swap_lines_usd_m: Optional[float] = None      # SWPT level in millions
    swap_lines_active: bool = False               # SWPT > $1B threshold
    swap_lines_max_4w_m: Optional[float] = None   # max in last 4 weeks
    # Dollar index divergence
    broad_dollar_z: Optional[float] = None        # DTWEXBGS Z-score vs 3y
    afe_dollar_z: Optional[float] = None
    eme_dollar_z: Optional[float] = None
    em_minus_afe_z: Optional[float] = None        # divergence signal
    # Composite
    composite_score: float = 0.0                  # 0-100, higher = more stress
    composite_label: str = "calm"                 # calm | watch | stress | crisis
    drivers: list[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _safe_z(series: pd.Series, window_days: int = 252 * 3) -> Optional[float]:
    """Z-score of the latest value vs trailing window. None if insufficient history."""
    s = pd.to_numeric(series, errors="coerce").dropna()
    if len(s) < 30:
        return None
    tail = s.tail(window_days)
    std = tail.std()
    if std == 0 or pd.isna(std):
        return None
    return float((s.iloc[-1] - tail.mean()) / std)


def _fetch_fred_series(fred: FredClient, series_id: str, *, refresh: bool) -> pd.DataFrame:
    """Fetch + normalize a FRED series. Empty DataFrame on any failure."""
    try:
        df = fred.fetch_series(series_id=series_id, start_date="2018-01-01", refresh=refresh)
    except Exception:
        return pd.DataFrame(columns=["date", "value"])
    if df is None or df.empty:
        return pd.DataFrame(columns=["date", "value"])
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df.dropna(subset=["date", "value"])[["date", "value"]]


# ─────────────────────────────────────────────────────────────────────────────
# Composite scoring
# ─────────────────────────────────────────────────────────────────────────────

def _score_offshore(
    swap_lines_m: Optional[float],
    swap_max_4w_m: Optional[float],
    broad_z: Optional[float],
    eme_afe_z: Optional[float],
) -> tuple[float, str, list[str]]:
    """
    Map raw signals to a 0-100 composite score with label and driver list.

    Calibration (informed by historical episodes):
      - SWPT > $1B is a hard crisis trigger (always rare; March 2020 was $450B).
      - Broad dollar Z > 2 = top 2.3% of moves = USD bid event.
      - EM-AFE divergence Z > 1.5 = EM-led USD demand (funding-stress pattern).
    """
    score = 0.0
    drivers: list[str] = []

    # ── Central bank swap lines (binary crisis signal) ───────────────────
    if isinstance(swap_lines_m, (int, float)):
        swap_b = swap_lines_m / 1000.0
        if swap_b > 50:
            score += 60.0
            drivers.append(f"swap lines active: ${swap_b:.0f}B drawn (crisis-level)")
        elif swap_b > 5:
            score += 40.0
            drivers.append(f"swap lines drawing: ${swap_b:.1f}B (elevated stress)")
        elif swap_b > 1:
            score += 20.0
            drivers.append(f"swap lines minimally active: ${swap_b:.1f}B")
    # 4-week max catches recent stress that's already unwound
    if isinstance(swap_max_4w_m, (int, float)) and swap_max_4w_m / 1000 > 1:
        if not any("swap lines" in d for d in drivers):
            drivers.append(f"swap lines recently active (max ${swap_max_4w_m / 1000:.1f}B in 4w)")
            score += 10.0

    # ── Broad dollar momentum ────────────────────────────────────────────
    if isinstance(broad_z, (int, float)):
        if broad_z > 2.0:
            score += 25.0
            drivers.append(f"broad dollar bid: Z {broad_z:+.1f}σ vs 3y")
        elif broad_z > 1.5:
            score += 15.0
            drivers.append(f"broad dollar bidding: Z {broad_z:+.1f}σ vs 3y")
        elif broad_z < -1.5:
            score -= 10.0  # dollar weakening = less offshore stress
            drivers.append(f"broad dollar offered: Z {broad_z:+.1f}σ (offshore-supportive)")

    # ── EM-AFE divergence (which corridor wants dollars?) ────────────────
    if isinstance(eme_afe_z, (int, float)):
        if eme_afe_z > 1.5:
            score += 15.0
            drivers.append(f"USD demand EM-led: EM dollar {eme_afe_z:+.1f}σ stronger than advanced")
        elif eme_afe_z > 1.0:
            score += 8.0
            drivers.append(f"USD demand tilting EM: divergence {eme_afe_z:+.1f}σ")
        elif eme_afe_z < -1.0:
            drivers.append(f"USD demand DM-led: divergence {eme_afe_z:+.1f}σ (less plumbing stress)")

    score = max(0.0, min(100.0, score))

    if score >= 70:
        label = "crisis"
    elif score >= 40:
        label = "stress"
    elif score >= 20:
        label = "watch"
    else:
        label = "calm"

    if not drivers:
        drivers.append("no offshore USD stress signals active")

    return score, label, drivers


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def compute_offshore_stress(*, refresh: bool = False) -> OffshoreStress:
    """
    Build the offshore USD stress composite from FRED.

    Returns an OffshoreStress dataclass; gracefully degrades on missing data
    (each FRED fetch is independent — partial data still produces a usable score).
    """
    out = OffshoreStress()
    settings = load_settings()
    if not settings.FRED_API_KEY:
        return out

    fred = FredClient(api_key=settings.FRED_API_KEY)

    # Central bank liquidity swaps (weekly, H.4.1)
    swpt = _fetch_fred_series(fred, "SWPT", refresh=refresh)
    if not swpt.empty:
        out.swap_lines_usd_m = float(swpt["value"].iloc[-1])
        # Threshold: >$1B (1000M) = unambiguously active. SWPT can sit at a few
        # tens of millions for residual lines that aren't "stress."
        out.swap_lines_active = out.swap_lines_usd_m > 1000
        # 4-week max — catches recent crisis that's already partially unwound
        if len(swpt) >= 4:
            out.swap_lines_max_4w_m = float(swpt["value"].tail(4).max())

    # Dollar indices — Z-scores vs 3-year history
    broad = _fetch_fred_series(fred, "DTWEXBGS", refresh=refresh)
    if not broad.empty:
        out.broad_dollar_z = _safe_z(broad["value"])

    afe = _fetch_fred_series(fred, "DTWEXAFEGS", refresh=refresh)
    if not afe.empty:
        out.afe_dollar_z = _safe_z(afe["value"])

    eme = _fetch_fred_series(fred, "DTWEXEMEGS", refresh=refresh)
    if not eme.empty:
        out.eme_dollar_z = _safe_z(eme["value"])

    # EM-AFE divergence: compute as Z-score of the *difference series*, which is
    # more meaningful than diff of two independent Z-scores.
    if not eme.empty and not afe.empty:
        # Align on date, compute spread, z-score it
        merged = eme.rename(columns={"value": "eme"}).merge(
            afe.rename(columns={"value": "afe"}), on="date", how="inner"
        )
        if not merged.empty:
            # Both indices are normalized — use difference of log levels for
            # comparability across the period.
            import numpy as np
            merged["spread"] = np.log(merged["eme"]) - np.log(merged["afe"])
            out.em_minus_afe_z = _safe_z(merged["spread"])

    # Determine asof from the most recent observation across all inputs
    last_dates = []
    for df in (swpt, broad, afe, eme):
        if not df.empty:
            last_dates.append(df["date"].max())
    if last_dates:
        out.asof = str(max(last_dates).date())

    # Composite score
    out.composite_score, out.composite_label, out.drivers = _score_offshore(
        swap_lines_m=out.swap_lines_usd_m,
        swap_max_4w_m=out.swap_lines_max_4w_m,
        broad_z=out.broad_dollar_z,
        eme_afe_z=out.em_minus_afe_z,
    )

    return out
