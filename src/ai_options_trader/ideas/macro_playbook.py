from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class PlaybookIdea:
    ticker: str
    direction: str  # bullish|bearish
    horizon_days: int
    n_matches: int
    exp_return: float  # mean fwd return (%)
    median_return: float
    hit_rate: float  # P(fwd_ret > 0)
    worst: float  # min fwd return (%)
    best: float  # max fwd return (%)
    score: float  # ranking scalar
    notes: dict
    # Optional benchmark-relative stats to reduce "everything drifts up" bias.
    benchmark: str | None = None
    exp_return_excess: float | None = None  # mean fwd (ticker - benchmark) (%)
    hit_rate_excess: float | None = None  # P(fwd_excess > 0)


def _zscore_frame(X: pd.DataFrame) -> pd.DataFrame:
    mu = X.mean(axis=0)
    sd = X.std(axis=0, ddof=0).replace(0, np.nan)
    return (X - mu) / sd


def _forward_return(series: pd.Series, days: int) -> pd.Series:
    return (series.shift(-days) / series - 1.0) * 100.0


def build_forward_returns(prices: pd.DataFrame, horizon_days: int) -> pd.DataFrame:
    px = prices.sort_index().ffill()
    out = {}
    for c in px.columns:
        out[c] = _forward_return(px[c], int(horizon_days))
    return pd.DataFrame(out, index=px.index)


def _nearest_neighbors(
    X: pd.DataFrame,
    asof: pd.Timestamp,
    *,
    k: int = 250,
    lookback_days: int = 252 * 7,
) -> pd.DatetimeIndex:
    """
    Pick k nearest historical dates to `asof` in feature space.

    Notes:
    - Uses z-scored features for distance.
    - Restricts to a trailing lookback window for stability.
    """
    X = X.sort_index()
    if asof not in X.index:
        # choose last available
        asof = X.index.max()

    start = asof - pd.Timedelta(days=int(lookback_days))
    hist = X.loc[(X.index < asof) & (X.index >= start)].dropna(how="any")
    if hist.empty:
        return pd.DatetimeIndex([])

    x0 = X.loc[[asof]].dropna(axis=1, how="any")
    cols = [c for c in x0.columns if c in hist.columns]
    hist2 = hist[cols].dropna(how="any")
    if hist2.empty or not cols:
        return pd.DatetimeIndex([])

    # z-score using historical window stats (numpy path for speed)
    mu = hist2.mean(axis=0).to_numpy(dtype=float)
    sd = hist2.std(axis=0, ddof=0).replace(0, np.nan).to_numpy(dtype=float)
    H = hist2.to_numpy(dtype=float)
    x = x0[cols].iloc[0].to_numpy(dtype=float)

    # handle NaNs / zero std
    sd = np.where(np.isfinite(sd), sd, 1.0)
    mu = np.where(np.isfinite(mu), mu, 0.0)
    H = np.where(np.isfinite(H), H, mu)
    x = np.where(np.isfinite(x), x, mu)

    Hz = (H - mu) / sd
    xz = (x - mu) / sd
    # Euclidean distances
    d = np.sqrt(((Hz - xz) ** 2).sum(axis=1))
    take = min(max(10, int(k)), d.shape[0])
    idx_sorted = np.argsort(d)[:take]
    return pd.DatetimeIndex(hist2.index[idx_sorted])


def rank_macro_playbook(
    *,
    features: pd.DataFrame,
    prices: pd.DataFrame,
    tickers: Iterable[str],
    horizon_days: int = 63,  # ~3 months
    k: int = 250,
    lookback_days: int = 252 * 7,
    min_matches: int = 60,
    benchmark: str | None = None,
    asof: pd.Timestamp | None = None,
) -> list[PlaybookIdea]:
    """
    Regime-conditioned playbook:
    - Find historical dates with similar regime feature vectors (kNN)
    - For each ticker, look at forward returns over the horizon from those dates
    - Rank ideas by a simple quality score
    """
    X = features.sort_index()
    px = prices.sort_index().ffill()
    idx = X.index.intersection(px.index)
    X = X.loc[idx].dropna(how="any")
    px = px.loc[idx]
    if X.empty:
        return []

    asof = asof or X.index.max()
    nbrs = _nearest_neighbors(X, asof, k=k, lookback_days=lookback_days)
    if len(nbrs) < int(min_matches):
        return []

    fwd = build_forward_returns(px, horizon_days=int(horizon_days))
    ideas: list[PlaybookIdea] = []
    bench = (benchmark or "").strip().upper() or None
    if bench is not None and bench not in fwd.columns:
        bench = None

    for t in tickers:
        if t not in fwd.columns:
            continue
        s = pd.to_numeric(fwd.loc[nbrs, t], errors="coerce").dropna()
        if s.shape[0] < int(min_matches):
            continue

        exp_ret = float(s.mean())
        med = float(s.median())
        hit = float((s > 0).mean())
        worst = float(s.min())
        best = float(s.max())
        exp_ex = None
        hit_ex = None
        direction_basis = exp_ret
        if bench is not None and bench != t:
            sb = pd.to_numeric(fwd.loc[nbrs, bench], errors="coerce").dropna()
            # Align on common analog dates
            common = s.index.intersection(sb.index)
            if len(common) >= int(min_matches):
                ex = (s.loc[common] - sb.loc[common]).dropna()
                if len(ex) >= int(min_matches):
                    exp_ex = float(ex.mean())
                    hit_ex = float((ex > 0).mean())
                    direction_basis = exp_ex

        direction = "bullish" if float(direction_basis) >= 0 else "bearish"

        # Score: reward magnitude + consistency, penalize ugly tails a bit.
        h_use = hit_ex if hit_ex is not None else hit
        r_use = exp_ex if exp_ex is not None else exp_ret
        score = (abs(float(r_use)) * (0.5 + float(h_use))) - 0.05 * abs(worst)

        ideas.append(
            PlaybookIdea(
                ticker=t,
                direction=direction,
                horizon_days=int(horizon_days),
                n_matches=int(s.shape[0]),
                exp_return=exp_ret,
                median_return=med,
                hit_rate=hit,
                benchmark=bench,
                exp_return_excess=exp_ex,
                hit_rate_excess=hit_ex,
                worst=worst,
                best=best,
                score=float(score),
                notes={
                    "asof": str(asof.date()),
                    "neighbors_start": str(nbrs.min().date()),
                    "neighbors_end": str(nbrs.max().date()),
                    "benchmark": bench,
                },
            )
        )

    ideas.sort(key=lambda x: x.score, reverse=True)
    return ideas


