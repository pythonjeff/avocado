from __future__ import annotations

import pandas as pd
import numpy as np


def to_daily_index(df: pd.DataFrame, start_date: str) -> pd.DataFrame:
    """Create a daily date index starting at start_date through df max date."""
    start = pd.to_datetime(start_date)
    end = pd.to_datetime(df["date"].max())
    idx = pd.date_range(start=start, end=end, freq="D")
    return pd.DataFrame({"date": idx})


def merge_series_daily(daily_index: pd.DataFrame, series_map: dict[str, pd.DataFrame], ffill: bool = True) -> pd.DataFrame:
    out = daily_index.copy()
    for sid, sdf in series_map.items():
        tmp = sdf.copy()
        tmp = tmp.rename(columns={"value": sid})
        before_cols = set(out.columns)
        out = out.merge(tmp, on="date", how="left")
        if ffill:
            # Forward-fill all newly merged columns (not just the primary series),
            # so derived monthly metrics (e.g., CPI_YOY) remain valid on the daily grid.
            new_cols = [c for c in out.columns if c not in before_cols and c != "date"]
            for c in new_cols:
                out[c] = out[c].ffill()
    return out


def yoy_from_index_level(level: pd.Series) -> pd.Series:
    """YoY percent change for index levels like CPI.

    Note: In this project we forward-fill monthly CPI onto a daily grid, so the
    series is effectively daily. Using pct_change(12) would mean "12 days".
    We therefore compute YoY as ~365 days.
    """
    return level.pct_change(365) * 100.0


def annualized_rate_from_levels(level: pd.Series, months: int) -> pd.Series:
    """
    Annualized inflation rate from index levels over 'months'.
    Example: 6-month annualized = ((CPI_t / CPI_{t-6})^(12/6) - 1) * 100
    """
    # Same note as yoy_from_index_level: after forward-fill onto a daily grid,
    # treat "months" as an approximate number of days.
    days = int(round(365.0 / 12.0 * months))
    ratio = level / level.shift(days)
    ann = (ratio ** (365.0 / days) - 1.0) * 100.0
    return ann


def zscore(series: pd.Series, window: int = 252) -> pd.Series:
    mu = series.rolling(window).mean()
    sd = series.rolling(window).std(ddof=0)
    return (series - mu) / sd
