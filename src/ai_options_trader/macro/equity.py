from __future__ import annotations

import numpy as np
import pandas as pd


def returns(df_prices: pd.DataFrame) -> pd.DataFrame:
    return df_prices.pct_change().dropna(how="all")


def delta(series: pd.Series) -> pd.Series:
    return series.diff()


def rolling_corr(x: pd.Series, y: pd.Series, window: int) -> pd.Series:
    return x.rolling(window).corr(y)


def rolling_beta(y: pd.Series, x: pd.Series, window: int) -> pd.Series:
    """
    Rolling OLS beta of y on x with intercept, using covariance/variance.
    """
    cov = y.rolling(window).cov(x)
    var = x.rolling(window).var()
    return cov / var


def latest_sensitivity_table(
    rets: pd.DataFrame,
    d_real: pd.Series,
    d_10y: pd.Series,
    d_be5y: pd.Series,
    window: int,
) -> pd.DataFrame:
    rows = []
    for sym in rets.columns:
        y = rets[sym].dropna()
        common = pd.concat([y, d_real, d_10y, d_be5y], axis=1, join="inner").dropna()
        if len(common) < window + 5:
            continue

        y2 = common.iloc[:, 0]
        real = common.iloc[:, 1]
        ten = common.iloc[:, 2]
        be5 = common.iloc[:, 3]

        corr_real = rolling_corr(y2, real, window).iloc[-1]
        beta_real = rolling_beta(y2, real, window).iloc[-1]
        corr_10y = rolling_corr(y2, ten, window).iloc[-1]
        beta_10y = rolling_beta(y2, ten, window).iloc[-1]
        corr_be5 = rolling_corr(y2, be5, window).iloc[-1]
        beta_be5 = rolling_beta(y2, be5, window).iloc[-1]

        rows.append(
            {
                "symbol": sym,
                "corr_d_real": float(corr_real) if pd.notna(corr_real) else np.nan,
                "beta_d_real": float(beta_real) if pd.notna(beta_real) else np.nan,
                "corr_d_10y": float(corr_10y) if pd.notna(corr_10y) else np.nan,
                "beta_d_10y": float(beta_10y) if pd.notna(beta_10y) else np.nan,
                "corr_d_be5y": float(corr_be5) if pd.notna(corr_be5) else np.nan,
                "beta_d_be5y": float(beta_be5) if pd.notna(beta_be5) else np.nan,
            }
        )

    out = pd.DataFrame(rows).set_index("symbol").sort_values(by="beta_d_real")
    return out
