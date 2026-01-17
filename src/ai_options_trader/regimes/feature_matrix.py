from __future__ import annotations

import pandas as pd

from ai_options_trader.config import Settings
from ai_options_trader.commodities.signals import build_commodities_dataset
from ai_options_trader.fiscal.signals import build_fiscal_dataset
from ai_options_trader.funding.signals import build_funding_dataset
from ai_options_trader.macro.signals import build_macro_dataset
from ai_options_trader.rates.signals import build_rates_dataset
from ai_options_trader.usd.signals import build_usd_dataset
from ai_options_trader.volatility.signals import build_volatility_dataset
from ai_options_trader.housing.signals import build_housing_dataset
from ai_options_trader.solar.signals import build_solar_dataset


def build_regime_feature_matrix(
    *,
    settings: Settings,
    start_date: str = "2011-01-01",
    refresh_fred: bool = False,
) -> pd.DataFrame:
    """
    Build a daily regime feature matrix (no labels), intended for:
    - playbooks (regime-conditioned performance lookup)
    - downstream ML datasets

    Keep this lean and stable: only include relatively stable features (z-scores, scores).
    """
    macro_df = build_macro_dataset(settings=settings, start_date=start_date, refresh=refresh_fred)
    funding_df = build_funding_dataset(settings=settings, start_date=start_date, refresh=refresh_fred)
    usd_df = build_usd_dataset(settings=settings, start_date=start_date, refresh=refresh_fred)
    rates_df = build_rates_dataset(settings=settings, start_date=start_date, refresh=refresh_fred)
    vol_df = build_volatility_dataset(settings=settings, start_date=start_date, refresh=refresh_fred)
    commod_df = build_commodities_dataset(settings=settings, start_date=start_date, refresh=refresh_fred)
    fiscal_df = build_fiscal_dataset(settings=settings, start_date=start_date, refresh=refresh_fred)
    housing_df = build_housing_dataset(settings=settings, start_date=start_date, refresh=refresh_fred)
    solar_df = build_solar_dataset(settings=settings, start_date=start_date, refresh=refresh_fred)

    f = pd.DataFrame({"date": pd.to_datetime(macro_df["date"])})
    f["macro_disconnect_score"] = macro_df.get("DISCONNECT_SCORE")
    f["macro_z_infl_mom_minus_be5y"] = macro_df.get("Z_INFL_MOM_MINUS_BE5Y")
    f["macro_z_real_yield_proxy_10y"] = macro_df.get("Z_REAL_YIELD_PROXY_10Y")
    f["macro_cpi_yoy"] = macro_df.get("CPI_YOY")
    f["macro_payrolls_3m_ann"] = macro_df.get("PAYROLLS_3M_ANN")

    # Funding (schema-tolerant)
    liq_want = [
        "date",
        "LIQ_TIGHTNESS_SCORE",
        "CORRIDOR_SPREAD_BPS",
        "SPIKE_5D_BPS",
        "PERSIST_20D",
        "VOL_20D_BPS",
    ]
    liq_cols = [c for c in liq_want if c in funding_df.columns]
    if "date" not in liq_cols:
        liq_cols = ["date"]
    f = f.merge(funding_df[liq_cols].copy(), on="date", how="left")

    # USD (schema-tolerant)
    usd_cols = ["date", "USD_STRENGTH_SCORE"]
    if "Z_DTWEXBGS_MOM_60D" in usd_df.columns:
        usd_cols += ["Z_DTWEXBGS_MOM_60D", "Z_DTWEXBGS_VOL_60D_ANN"]
    else:
        usd_cols += ["Z_USD_LEVEL", "Z_USD_CHG_60D"]
    f = f.merge(usd_df[usd_cols].copy(), on="date", how="left")

    # Rates
    rates_cols = [
        "date",
        "Z_UST_10Y",
        "Z_UST_10Y_CHG_20D",
        "Z_CURVE_2S10S",
        "Z_CURVE_2S10S_CHG_20D",
    ]
    rates_cols = [c for c in rates_cols if c in rates_df.columns]
    if "date" not in rates_cols:
        rates_cols = ["date"]
    f = f.merge(rates_df[rates_cols].copy(), on="date", how="left")

    # Volatility (VIX): keep stable z-scores and score
    vol_cols = ["date", "Z_VIX", "Z_VIX_CHG_5D", "Z_VIX_TERM", "PERSIST_20D", "VOL_PRESSURE_SCORE"]
    vol_cols = [c for c in vol_cols if c in vol_df.columns]
    if "date" not in vol_cols:
        vol_cols = ["date"]
    f = f.merge(vol_df[vol_cols].copy(), on="date", how="left")

    # Commodities: keep stable score and z context
    commod_cols = [
        "date",
        "Z_WTI_RET_20D",
        "Z_GOLD_RET_20D",
        "Z_COPPER_RET_60D",
        "Z_BROAD_RET_60D",
        "COMMODITY_PRESSURE_SCORE",
        "ENERGY_SHOCK",
        "METALS_IMPULSE",
    ]
    commod_cols = [c for c in commod_cols if c in commod_df.columns]
    if "date" not in commod_cols:
        commod_cols = ["date"]
    f = f.merge(commod_df[commod_cols].copy(), on="date", how="left")

    # Fiscal: keep composite + stable z context (best-effort; some components may be NaN if upstream data is unavailable)
    fiscal_cols = [
        "date",
        "FISCAL_PRESSURE_SCORE",
        "Z_DEFICIT_12M",
        "Z_TGA_CHG_28D",
        "Z_LONG_DURATION_ISS_SHARE",
        "Z_AUCTION_TAIL_BPS",
        "Z_DEALER_TAKE_PCT",
    ]
    fiscal_cols = [c for c in fiscal_cols if c in fiscal_df.columns]
    if "date" not in fiscal_cols:
        fiscal_cols = ["date"]
    f = f.merge(fiscal_df[fiscal_cols].copy(), on="date", how="left")

    # Housing / MBS (best-effort): mortgage spread stress + market proxies.
    housing_cols = [
        "date",
        "Z_MORTGAGE_SPREAD",
        "Z_MBS_REL_RET_60D",
        "Z_HOMEBUILDER_REL_RET_60D",
        "Z_REIT_REL_RET_60D",
        "HOUSING_PRESSURE_SCORE",
    ]
    housing_cols = [c for c in housing_cols if c in housing_df.columns]
    if "date" not in housing_cols:
        housing_cols = ["date"]
    f = f.merge(housing_df[housing_cols].copy(), on="date", how="left")

    # Solar / Silver (best-effort): solar basket vs SPY + silver momentum.
    solar_cols = [
        "date",
        "Z_SOLAR_REL_RET_60D",
        "Z_SILVER_RET_60D",
        "SOLAR_HEADWIND_SCORE",
    ]
    solar_cols = [c for c in solar_cols if c in solar_df.columns]
    if "date" not in solar_cols:
        solar_cols = ["date"]
    f = f.merge(solar_df[solar_cols].copy(), on="date", how="left")

    f = f.sort_values("date").set_index("date")
    f = f.rename(
        columns={
            "LIQ_TIGHTNESS_SCORE": "funding_tightness_score",
            "CORRIDOR_SPREAD_BPS": "funding_corridor_spread_bps",
            "SPIKE_5D_BPS": "funding_spike_5d_bps",
            "PERSIST_20D": "funding_persist_20d",
            "VOL_20D_BPS": "funding_vol_20d_bps",
            "USD_STRENGTH_SCORE": "usd_strength_score",
            "Z_DTWEXBGS_MOM_60D": "usd_z_mom_60d",
            "Z_DTWEXBGS_VOL_60D_ANN": "usd_z_vol_60d",
            "Z_USD_LEVEL": "usd_z_level",
            "Z_USD_CHG_60D": "usd_z_chg_60d",
            "Z_UST_10Y": "rates_z_ust_10y",
            "Z_UST_10Y_CHG_20D": "rates_z_ust_10y_chg_20d",
            "Z_CURVE_2S10S": "rates_z_curve_2s10s",
            "Z_CURVE_2S10S_CHG_20D": "rates_z_curve_2s10s_chg_20d",
            "Z_VIX": "vol_z_vix",
            "Z_VIX_CHG_5D": "vol_z_vix_chg_5d",
            "Z_VIX_TERM": "vol_z_vix_term",
            "PERSIST_20D": "vol_persist_20d",
            "VOL_PRESSURE_SCORE": "vol_pressure_score",
            "Z_WTI_RET_20D": "commod_z_wti_ret_20d",
            "Z_GOLD_RET_20D": "commod_z_gold_ret_20d",
            "Z_COPPER_RET_60D": "commod_z_copper_ret_60d",
            "Z_BROAD_RET_60D": "commod_z_broad_ret_60d",
            "COMMODITY_PRESSURE_SCORE": "commod_pressure_score",
            "ENERGY_SHOCK": "commod_energy_shock",
            "METALS_IMPULSE": "commod_metals_impulse",
            "FISCAL_PRESSURE_SCORE": "fiscal_pressure_score",
            "Z_DEFICIT_12M": "fiscal_z_deficit_12m",
            "Z_TGA_CHG_28D": "fiscal_z_tga_chg_28d",
            "Z_LONG_DURATION_ISS_SHARE": "fiscal_z_long_duration_iss_share",
            "Z_AUCTION_TAIL_BPS": "fiscal_z_auction_tail_bps",
            "Z_DEALER_TAKE_PCT": "fiscal_z_dealer_take_pct",
            "Z_MORTGAGE_SPREAD": "housing_z_mortgage_spread",
            "Z_MBS_REL_RET_60D": "housing_z_mbs_rel_ret_60d",
            "Z_HOMEBUILDER_REL_RET_60D": "housing_z_homebuilder_rel_ret_60d",
            "Z_REIT_REL_RET_60D": "housing_z_reit_rel_ret_60d",
            "HOUSING_PRESSURE_SCORE": "housing_pressure_score",
            "Z_SOLAR_REL_RET_60D": "solar_z_rel_ret_60d",
            "Z_SILVER_RET_60D": "solar_z_silver_ret_60d",
            "SOLAR_HEADWIND_SCORE": "solar_headwind_score",
        }
    )
    return f


