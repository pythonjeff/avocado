from __future__ import annotations

from typing import Dict
import pandas as pd

from ai_options_trader.config import Settings
from ai_options_trader.data.fred import FredClient, DEFAULT_SERIES
from ai_options_trader.macro.transforms import (
    to_daily_index,
    merge_series_daily,
    yoy_from_index_level,
    annualized_rate_from_levels,
    zscore,
)
from ai_options_trader.macro.models import MacroState, MacroInputs


def build_macro_dataset(settings: Settings, start_date: str = "2011-01-01", refresh: bool = False) -> pd.DataFrame:
    if not settings.FRED_API_KEY:
        raise RuntimeError("Missing FRED_API_KEY in environment / .env")

    fred = FredClient(api_key=settings.FRED_API_KEY)
    
    from ai_options_trader.data.fred import OPTIONAL_SERIES

    series_frames: Dict[str, pd.DataFrame] = {}
    for sid in DEFAULT_SERIES.keys():
        try:
            series_frames[sid] = fred.fetch_series(series_id=sid, start_date=start_date, refresh=refresh)
        except Exception as e:
            # Allow optional series to fail gracefully
            if sid in OPTIONAL_SERIES:
                print(f"Warning: Optional series {sid} unavailable: {e}")
                continue
            else:
                raise
    
    # Fetch GLDM (gold proxy) from FMP if available
    # GLDM tracks 1/10 oz of gold, so multiply by ~10 for spot equivalent
    if settings.FMP_API_KEY:
        try:
            import requests
            url = f"https://financialmodelingprep.com/api/v3/quote/GLDM"
            params = {"apikey": settings.FMP_API_KEY}
            resp = requests.get(url, params=params, timeout=10)
            if resp.ok:
                data = resp.json()
                if data and len(data) > 0:
                    gldm_price = data[0].get("price")
                    if gldm_price:
                        # Convert GLDM to gold spot equivalent (GLDM ≈ 1/10 oz)
                        gold_spot_proxy = float(gldm_price) * 10.0
                        # Create a synthetic series with current value
                        today = pd.Timestamp.now().floor('D')
                        gold_df = pd.DataFrame({
                            "date": [today],
                            "value": [gold_spot_proxy]
                        })
                        series_frames["GLDM_GOLD_PROXY"] = gold_df
        except Exception as e:
            print(f"Warning: Could not fetch GLDM for gold proxy: {e}")

    # Compute CPI-derived metrics on the *monthly* CPI observations, then ffill them
    # onto the daily grid. If we compute these after forward-filling CPI to daily,
    # the "3m" window may land entirely in a flat (no-new-CPI) region and show 0.0.
    if "CPIAUCSL" in series_frames:
        cpi = series_frames["CPIAUCSL"].copy().sort_values("date")
        cpi["CPI_YOY"] = cpi["value"].pct_change(12) * 100.0
        cpi["CPI_3M_ANN"] = ((cpi["value"] / cpi["value"].shift(3)) ** (12.0 / 3.0) - 1.0) * 100.0
        cpi["CPI_6M_ANN"] = ((cpi["value"] / cpi["value"].shift(6)) ** (12.0 / 6.0) - 1.0) * 100.0
        series_frames["CPIAUCSL"] = cpi

    if "CPILFESL" in series_frames:
        core = series_frames["CPILFESL"].copy().sort_values("date")
        core["CORE_CPI_YOY"] = core["value"].pct_change(12) * 100.0
        series_frames["CPILFESL"] = core
    
    # Median CPI (stickiness proxy)
    if "MEDCPIM158SFRBCLE" in series_frames:
        median = series_frames["MEDCPIM158SFRBCLE"].copy().sort_values("date")
        median["MEDIAN_CPI_YOY"] = median["value"].pct_change(12) * 100.0
        series_frames["MEDCPIM158SFRBCLE"] = median

    # Compute payroll-derived metrics on the *monthly* payroll observations, then ffill onto daily grid.
    # PAYEMS is a level series (thousands of employees).
    if "PAYEMS" in series_frames:
        p = series_frames["PAYEMS"].copy().sort_values("date")
        p["PAYROLLS_YOY"] = p["value"].pct_change(12) * 100.0
        p["PAYROLLS_MOM"] = p["value"].pct_change(1) * 100.0
        p["PAYROLLS_3M_ANN"] = ((p["value"] / p["value"].shift(3)) ** (12.0 / 3.0) - 1.0) * 100.0
        series_frames["PAYEMS"] = p
    
    # Initial claims 4-week average
    if "ICSA" in series_frames:
        claims = series_frames["ICSA"].copy().sort_values("date")
        claims["ICSA_4W"] = claims["value"].rolling(4).mean()
        series_frames["ICSA"] = claims
    
    # Home prices YoY
    if "CSUSHPISA" in series_frames:
        home = series_frames["CSUSHPISA"].copy().sort_values("date")
        home["HOME_PRICES_YOY"] = home["value"].pct_change(12) * 100.0
        series_frames["CSUSHPISA"] = home

    # Create daily index and merge (monthly series will be forward-filled)
    # Use the max date across all series
    max_date = max(df["date"].max() for df in series_frames.values())
    base = pd.DataFrame({"date": pd.date_range(start=pd.to_datetime(start_date), end=pd.to_datetime(max_date), freq="D")})
    merged = merge_series_daily(base, series_frames, ffill=True)

    # Rates/expectations derived
    merged["CURVE_2S10S"] = merged["DGS10"] - merged["DGS2"]
    merged["REAL_YIELD_PROXY_10Y"] = merged["DGS10"] - merged["T10YIE"]
    merged["INFL_MOM_MINUS_BE5Y"] = merged["CPI_6M_ANN"] - merged["T5YIE"]
    
    # VIX term structure (removed due to VXMTCLS FRED API issues)
    # Negative = contango (VIX < VIXM, normal market)
    # Positive = backwardation (VIX > VIXM, near-term stress)
    # if "VIXCLS" in merged.columns and "VXMTCLS" in merged.columns:
    #     merged["VIX_TERM_STRUCTURE"] = merged["VIXCLS"] - merged["VXMTCLS"]
    
    # Credit spreads
    if "BAMLH0A0HYM2" in merged.columns and "BAMLC0A0CM" in merged.columns:
        merged["HY_IG_SPREAD"] = merged["BAMLH0A0HYM2"] - merged["BAMLC0A0CM"]
    
    # Housing
    if "MORTGAGE30US" in merged.columns and "DGS10" in merged.columns:
        merged["MORTGAGE_SPREAD"] = (merged["MORTGAGE30US"] - merged["DGS10"]) * 100.0  # Convert to bps
    
    # Gold proxy from GLDM (if available)
    if "GLDM_GOLD_PROXY" in merged.columns:
        merged["GOLD_PRICE"] = merged["GLDM_GOLD_PROXY"]

    # Composite disconnect score: z-scored components (you can tune weights)
    merged["Z_INFL_MOM_MINUS_BE5Y"] = zscore(merged["INFL_MOM_MINUS_BE5Y"], window=252)
    merged["Z_REAL_YIELD_PROXY_10Y"] = zscore(merged["REAL_YIELD_PROXY_10Y"], window=252)

    merged["DISCONNECT_SCORE"] = 0.6 * merged["Z_INFL_MOM_MINUS_BE5Y"] + 0.4 * merged["Z_REAL_YIELD_PROXY_10Y"]

    return merged


def build_macro_state(settings: Settings, start_date: str = "2011-01-01", refresh: bool = False) -> MacroState:
    return build_macro_state_at(
        settings=settings,
        start_date=start_date,
        refresh=refresh,
        asof=None,
    )


def build_macro_state_at(
    settings: Settings,
    start_date: str = "2011-01-01",
    refresh: bool = False,
    asof: str | None = None,
) -> MacroState:
    """
    Build a MacroState as-of a given date (inclusive).

    If asof is None, uses the latest available observation.
    """
    df = build_macro_dataset(settings=settings, start_date=start_date, refresh=refresh)
    if asof:
        asof_ts = pd.to_datetime(asof)
        df = df[df["date"] <= asof_ts]
        if df.empty:
            raise ValueError(f"No macro data available on or before asof={asof} (start_date={start_date}).")

    last = df.dropna(subset=["CPIAUCSL", "DGS10", "T5YIE"]).iloc[-1]

    inputs = MacroInputs(
        cpi_yoy=float(last["CPI_YOY"]) if pd.notna(last["CPI_YOY"]) else None,
        core_cpi_yoy=float(last["CORE_CPI_YOY"]) if pd.notna(last["CORE_CPI_YOY"]) else None,
        median_cpi_yoy=float(last["MEDIAN_CPI_YOY"]) if "MEDIAN_CPI_YOY" in last and pd.notna(last["MEDIAN_CPI_YOY"]) else None,
        cpi_3m_annualized=float(last["CPI_3M_ANN"]) if pd.notna(last["CPI_3M_ANN"]) else None,
        cpi_6m_annualized=float(last["CPI_6M_ANN"]) if pd.notna(last["CPI_6M_ANN"]) else None,
        breakeven_5y=float(last["T5YIE"]) if pd.notna(last["T5YIE"]) else None,
        breakeven_10y=float(last["T10YIE"]) if pd.notna(last["T10YIE"]) else None,
        breakeven_5y5y=float(last["T5YIFR"]) if "T5YIFR" in last and pd.notna(last["T5YIFR"]) else None,
        payrolls_yoy=float(last["PAYROLLS_YOY"]) if "PAYROLLS_YOY" in last and pd.notna(last["PAYROLLS_YOY"]) else None,
        payrolls_3m_annualized=float(last["PAYROLLS_3M_ANN"]) if "PAYROLLS_3M_ANN" in last and pd.notna(last["PAYROLLS_3M_ANN"]) else None,
        payrolls_mom=float(last["PAYROLLS_MOM"]) if "PAYROLLS_MOM" in last and pd.notna(last["PAYROLLS_MOM"]) else None,
        unemployment_rate=float(last["UNRATE"]) if "UNRATE" in last and pd.notna(last["UNRATE"]) else None,
        initial_claims_4w=float(last["ICSA_4W"]) if "ICSA_4W" in last and pd.notna(last["ICSA_4W"]) else None,
        eff_fed_funds=float(last["DFF"]) if pd.notna(last["DFF"]) else None,
        ust_2y=float(last["DGS2"]) if pd.notna(last["DGS2"]) else None,
        ust_10y=float(last["DGS10"]) if pd.notna(last["DGS10"]) else None,
        curve_2s10s=float(last["CURVE_2S10S"]) if pd.notna(last["CURVE_2S10S"]) else None,
        real_yield_proxy_10y=float(last["REAL_YIELD_PROXY_10Y"]) if pd.notna(last["REAL_YIELD_PROXY_10Y"]) else None,
        inflation_momentum_minus_be5y=float(last["INFL_MOM_MINUS_BE5Y"]) if pd.notna(last["INFL_MOM_MINUS_BE5Y"]) else None,
        # Credit spreads
        hy_oas=float(last["BAMLH0A0HYM2"]) if "BAMLH0A0HYM2" in last and pd.notna(last["BAMLH0A0HYM2"]) else None,
        ig_oas=float(last["BAMLC0A0CM"]) if "BAMLC0A0CM" in last and pd.notna(last["BAMLC0A0CM"]) else None,
        hy_ig_spread=float(last["HY_IG_SPREAD"]) if "HY_IG_SPREAD" in last and pd.notna(last["HY_IG_SPREAD"]) else None,
        # Volatility
        vix=float(last["VIXCLS"]) if "VIXCLS" in last and pd.notna(last["VIXCLS"]) else None,
        vixm=None,  # VXMTCLS removed due to FRED API issues
        vix_term_structure=None,  # Cannot calculate without VXMTCLS
        move=None,  # MOVE not available on FRED, would need Bloomberg/other source
        # Dollar / FX
        dxy=float(last["DTWEXBGS"]) if "DTWEXBGS" in last and pd.notna(last["DTWEXBGS"]) else None,
        # Commodities (oil + gold from GLDM)
        gold_price=float(last["GOLD_PRICE"]) if "GOLD_PRICE" in last and pd.notna(last["GOLD_PRICE"]) else None,
        oil_price=float(last["DCOILWTICO"]) if "DCOILWTICO" in last and pd.notna(last["DCOILWTICO"]) else None,
        gold_oil_ratio=None,  # Could calculate if both available
        # Housing
        mortgage_30y=float(last["MORTGAGE30US"]) if "MORTGAGE30US" in last and pd.notna(last["MORTGAGE30US"]) else None,
        mortgage_spread=float(last["MORTGAGE_SPREAD"]) if "MORTGAGE_SPREAD" in last and pd.notna(last["MORTGAGE_SPREAD"]) else None,
        home_prices_yoy=float(last["HOME_PRICES_YOY"]) if "HOME_PRICES_YOY" in last and pd.notna(last["HOME_PRICES_YOY"]) else None,
        disconnect_score=float(last["DISCONNECT_SCORE"]) if pd.notna(last["DISCONNECT_SCORE"]) else None,
        components={
            "z_infl_mom_minus_be5y": float(last["Z_INFL_MOM_MINUS_BE5Y"]) if pd.notna(last["Z_INFL_MOM_MINUS_BE5Y"]) else None,
            "z_real_yield_proxy_10y": float(last["Z_REAL_YIELD_PROXY_10Y"]) if pd.notna(last["Z_REAL_YIELD_PROXY_10Y"]) else None,
        },
    )

    return MacroState(
        asof=str(pd.to_datetime(last["date"]).date()),
        start_date=start_date,
        inputs=inputs,
        notes="Disconnect score combines inflation momentum vs breakevens and a real-yield proxy (z-scored).",
    )
