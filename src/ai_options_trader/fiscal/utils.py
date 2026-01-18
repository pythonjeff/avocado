"""Utility functions for fiscal data processing."""

from __future__ import annotations

from typing import Tuple
import pandas as pd


def first_existing_col(df: pd.DataFrame, candidates: Tuple[str, ...]) -> str | None:
    """Return the first column name from candidates that exists in df."""
    for c in candidates:
        if c in df.columns:
            return c
    return None


def rolling_12m_sum_monthly(flow: pd.Series) -> pd.Series:
    """
    Compute rolling 12-month sum of a monthly flow series.
    
    Args:
        flow: Monthly series (e.g., monthly deficit)
        
    Returns:
        Rolling 12-month sum (e.g., trailing 12-month deficit)
    """
    return flow.rolling(12, min_periods=1).sum()


def yoy_pct_change(series: pd.Series, periods: int) -> pd.Series:
    """
    Compute year-over-year percent change.
    
    Args:
        series: Time series
        periods: Number of periods for YoY (12 for monthly data)
        
    Returns:
        Percent change (0-100 scale)
    """
    return series.pct_change(periods) * 100.0


def weighted_score(row: pd.Series, weights: dict[str, float]) -> float | None:
    """
    Compute a weighted score from multiple features.
    
    Args:
        row: pandas Series with feature values
        weights: Dict of feature names to weights
        
    Returns:
        Weighted sum, or None if all inputs are missing
    """
    total = 0.0
    total_weight = 0.0
    for feat, w in weights.items():
        val = row.get(feat)
        if pd.notna(val):
            total += float(val) * w
            total_weight += w
    if total_weight == 0:
        return None
    return total
