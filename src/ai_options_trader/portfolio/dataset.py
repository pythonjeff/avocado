from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ai_options_trader.config import Settings
from ai_options_trader.liquidity.signals import build_liquidity_dataset
from ai_options_trader.macro.signals import build_macro_dataset
from ai_options_trader.usd.signals import build_usd_dataset


@dataclass(frozen=True)
class PortfolioDataset:
    """
    Supervised dataset for forecasting forward basket returns using regime features.
    """

    X: pd.DataFrame  # index=date, columns=features
    y: pd.DataFrame  # index=date, columns=['fwd_ret_3m','fwd_ret_6m','fwd_ret_12m']
    meta: pd.DataFrame  # index=date, columns=['basket_level']


def _basket_index(prices: pd.DataFrame, tickers: list[str]) -> pd.Series:
    px = prices[tickers].dropna(how="any").sort_index()
    # Normalize to 1 at start for stability
    norm = px / px.iloc[0]
    return norm.mean(axis=1)


def _forward_return(series: pd.Series, days: int) -> pd.Series:
    # Forward % return: (t+days / t - 1) * 100
    return (series.shift(-days) / series - 1.0) * 100.0


def build_portfolio_dataset(
    *,
    settings: Settings,
    equity_prices: pd.DataFrame,
    basket_tickers: list[str],
    start_date: str = "2011-01-01",
    refresh_fred: bool = False,
) -> PortfolioDataset:
    """
    Build merged daily regime features + basket forward returns (3/6/12m).

    Notes:
    - Regime features are computed from FRED-based datasets (macro/liquidity/USD).
    - Equity basket uses Alpaca daily closes passed in as `equity_prices`.
    - We use a daily intersection to avoid look-ahead; labels use forward shifting.
    """
    # --- Features (daily, with 'date' column) ---
    macro_df = build_macro_dataset(settings=settings, start_date=start_date, refresh=refresh_fred)
    liq_df = build_liquidity_dataset(settings=settings, start_date=start_date, refresh=refresh_fred)
    usd_df = build_usd_dataset(settings=settings, start_date=start_date, refresh=refresh_fred)

    # Select stable feature columns (avoid raw levels where possible)
    f = pd.DataFrame({"date": pd.to_datetime(macro_df["date"])})
    f["macro_disconnect_score"] = macro_df.get("DISCONNECT_SCORE")
    f["macro_z_infl_mom_minus_be5y"] = macro_df.get("Z_INFL_MOM_MINUS_BE5Y")
    f["macro_z_real_yield_proxy_10y"] = macro_df.get("Z_REAL_YIELD_PROXY_10Y")
    f["macro_cpi_yoy"] = macro_df.get("CPI_YOY")
    f["macro_payrolls_3m_ann"] = macro_df.get("PAYROLLS_3M_ANN")
    f = f.merge(
        liq_df[
            [
                "date",
                "LIQ_TIGHTNESS_SCORE",
                "Z_HY_OAS",
                "Z_IG_OAS",
                "Z_HY_MINUS_IG_OAS",
                "Z_DGS10_CHG_20D",
                "Z_CURVE_10Y_2Y",
                "Z_REAL_POLICY_RATE",
                "Z_TGA_CHG_28D",
                "Z_RRP_CHG_20D",
            ]
        ].copy(),
        on="date",
        how="left",
    )
    # USD dataset schema has evolved; support both:
    # - newer: Z_DTWEXBGS_MOM_60D / Z_DTWEXBGS_VOL_60D_ANN
    # - current repo: Z_USD_LEVEL / Z_USD_CHG_60D
    usd_cols = ["date", "USD_STRENGTH_SCORE"]
    if "Z_DTWEXBGS_MOM_60D" in usd_df.columns:
        usd_cols += ["Z_DTWEXBGS_MOM_60D", "Z_DTWEXBGS_VOL_60D_ANN"]
    else:
        usd_cols += ["Z_USD_LEVEL", "Z_USD_CHG_60D"]

    f = f.merge(usd_df[usd_cols].copy(), on="date", how="left")

    f = f.sort_values("date").set_index("date")
    f = f.rename(
        columns={
            "LIQ_TIGHTNESS_SCORE": "liq_tightness_score",
            "Z_HY_OAS": "liq_z_hy_oas",
            "Z_IG_OAS": "liq_z_ig_oas",
            "Z_HY_MINUS_IG_OAS": "liq_z_hy_minus_ig_oas",
            "Z_DGS10_CHG_20D": "liq_z_ust10y_chg_20d",
            "Z_CURVE_10Y_2Y": "liq_z_curve_10y_2y",
            "Z_REAL_POLICY_RATE": "liq_z_real_policy_rate",
            "Z_TGA_CHG_28D": "liq_z_tga_chg_28d",
            "Z_RRP_CHG_20D": "liq_z_rrp_chg_20d",
            "USD_STRENGTH_SCORE": "usd_strength_score",
            # Newer schema
            "Z_DTWEXBGS_MOM_60D": "usd_z_mom_60d",
            "Z_DTWEXBGS_VOL_60D_ANN": "usd_z_vol_60d",
            # Current repo schema
            "Z_USD_LEVEL": "usd_z_level",
            "Z_USD_CHG_60D": "usd_z_chg_60d",
        }
    )

    # --- Labels (basket forward returns) ---
    px = equity_prices.copy().sort_index()
    basket = _basket_index(px, basket_tickers)
    y = pd.DataFrame(
        {
            "fwd_ret_3m": _forward_return(basket, 63),
            "fwd_ret_6m": _forward_return(basket, 126),
            "fwd_ret_12m": _forward_return(basket, 252),
        },
        index=basket.index,
    )
    meta = pd.DataFrame({"basket_level": basket}, index=basket.index)

    # Align + drop rows where we can't train/predict
    idx = f.index.intersection(y.index)
    f2 = f.loc[idx].copy()
    y2 = y.loc[idx].copy()
    meta2 = meta.loc[idx].copy()

    # Drop rows with missing features (after z-score warmups etc.)
    f2 = f2.replace([np.inf, -np.inf], np.nan)
    y2 = y2.replace([np.inf, -np.inf], np.nan)

    # Need features + at least 12m label for training; prediction can use last row without label.
    keep = f2.dropna().index
    f2 = f2.loc[keep]
    y2 = y2.loc[keep]
    meta2 = meta2.loc[keep]

    return PortfolioDataset(X=f2, y=y2, meta=meta2)


