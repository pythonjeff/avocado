"""
Household Wealth Regime - Data Signals

Fetches household balance sheet and behavioral data from FRED.
Incorporates the sectoral balances framework to contextualize household wealth.
"""
from __future__ import annotations

from typing import Dict

import pandas as pd

from ai_options_trader.config import Settings
from ai_options_trader.data.fred import FredClient
from ai_options_trader.macro.transforms import merge_series_daily, zscore
from ai_options_trader.household.models import (
    HouseholdInputs,
    HouseholdState,
    SectoralBalances,
)


# =============================================================================
# FRED Series Definitions
# =============================================================================

HOUSEHOLD_FRED_SERIES: Dict[str, str] = {
    # -------------------------------------------------------------------------
    # Sectoral Balances Components (for MMT framework)
    # -------------------------------------------------------------------------
    # Government deficit (monthly, flow) - already used in fiscal module
    "GOVT_DEFICIT": "MTSDS133FMS",
    # Net exports (quarterly, billions SAAR)
    "NET_EXPORTS": "NETEXP",
    # Gross Private Domestic Investment (quarterly, billions SAAR)
    "INVESTMENT": "GPDI",
    # GDP (quarterly, billions SAAR) - for normalization
    "GDP": "GDP",
    
    # -------------------------------------------------------------------------
    # Wealth Metrics
    # -------------------------------------------------------------------------
    # Household Net Worth (quarterly, trillions)
    "NET_WORTH": "TNWBSHNO",
    # Household Checkable Deposits + Currency (quarterly, billions)
    "CHECKABLE_DEPOSITS": "BOGZ1FL153020005Q",
    # Retail Money Funds (weekly, billions)
    "MONEY_MARKET_FUNDS": "WRMFSL",
    
    # -------------------------------------------------------------------------
    # Debt Metrics
    # -------------------------------------------------------------------------
    # Household Debt Service Ratio (quarterly, %)
    "DEBT_SERVICE_RATIO": "TDSP",
    # Total Consumer Credit (monthly, billions)
    "CONSUMER_CREDIT": "TOTALSL",
    # Revolving Consumer Credit (monthly, billions) - credit cards
    "REVOLVING_CREDIT": "REVOLSL",
    # Mortgage Delinquency Rate (quarterly, %)
    "MORTGAGE_DELINQ": "DRSFRMACBS",
    
    # -------------------------------------------------------------------------
    # Behavioral Metrics
    # -------------------------------------------------------------------------
    # Personal Savings Rate (monthly, %)
    "SAVINGS_RATE": "PSAVERT",
    # Consumer Sentiment (monthly, index 1966=100)
    "CONSUMER_SENTIMENT": "UMCSENT",
    # M2 Money Velocity (quarterly)
    "M2_VELOCITY": "M2V",
    # Real Disposable Personal Income (monthly, billions chained 2017)
    "REAL_DPI": "DSPIC96",
    # Retail Sales ex Food Services (monthly, millions)
    "RETAIL_SALES": "RSXFS",
    
    # -------------------------------------------------------------------------
    # Inflation (for real adjustments)
    # -------------------------------------------------------------------------
    "CPI": "CPIAUCSL",
}

# Optional series that won't fail the build if unavailable
_OPTIONAL_SERIES = {
    "CHECKABLE_DEPOSITS",
    "MONEY_MARKET_FUNDS", 
    "MORTGAGE_DELINQ",
    "M2_VELOCITY",
    "INVESTMENT",
    "NET_EXPORTS",
}


def _fetch_optional(
    *, 
    fred: FredClient, 
    series_id: str, 
    start_date: str, 
    refresh: bool
) -> pd.DataFrame | None:
    """Fetch a series, returning None if unavailable."""
    try:
        df = fred.fetch_series(series_id=series_id, start_date=start_date, refresh=refresh)
        if df is None or df.empty:
            return None
        return df.sort_values("date").reset_index(drop=True)
    except Exception:
        return None


def _yoy_pct_change(series: pd.Series, periods: int = 12) -> pd.Series:
    """Year-over-year percent change (periods depends on frequency)."""
    return series.pct_change(periods) * 100.0


def _weighted_score(values: Dict[str, float | None], weights: Dict[str, float]) -> float | None:
    """Compute weighted average over available values."""
    num = 0.0
    denom = 0.0
    for key, weight in weights.items():
        val = values.get(key)
        if val is not None and pd.notna(val):
            num += float(weight) * float(val)
            denom += abs(float(weight))
    if denom <= 0:
        return None
    return num / denom


def build_sectoral_balances(
    settings: Settings,
    start_date: str = "2011-01-01",
    refresh: bool = False,
) -> SectoralBalances:
    """
    Build MMT sectoral balances snapshot.
    
    Identity: S = (G - T) + I + NX
    
    Where S is private sector financial balance.
    For households, (G-T) + NX is the key driver of net financial asset accumulation.
    """
    if not settings.FRED_API_KEY:
        return SectoralBalances(notes="Missing FRED_API_KEY")
    
    fred = FredClient(api_key=settings.FRED_API_KEY)
    
    # Fetch GDP for normalization
    gdp_df = _fetch_optional(
        fred=fred, 
        series_id=HOUSEHOLD_FRED_SERIES["GDP"],
        start_date=start_date,
        refresh=refresh,
    )
    
    # Fetch deficit (monthly flow - use rolling 12m)
    deficit_df = _fetch_optional(
        fred=fred,
        series_id=HOUSEHOLD_FRED_SERIES["GOVT_DEFICIT"],
        start_date=start_date,
        refresh=refresh,
    )
    
    # Fetch net exports (quarterly)
    netexp_df = _fetch_optional(
        fred=fred,
        series_id=HOUSEHOLD_FRED_SERIES["NET_EXPORTS"],
        start_date=start_date,
        refresh=refresh,
    )
    
    # Fetch investment (quarterly)
    inv_df = _fetch_optional(
        fred=fred,
        series_id=HOUSEHOLD_FRED_SERIES["INVESTMENT"],
        start_date=start_date,
        refresh=refresh,
    )
    
    if gdp_df is None or gdp_df.empty:
        return SectoralBalances(notes="GDP data unavailable")
    
    # Get latest GDP (billions SAAR)
    gdp_df["value"] = pd.to_numeric(gdp_df["value"], errors="coerce")
    gdp_latest = gdp_df.dropna(subset=["value"]).iloc[-1]
    gdp_bn = float(gdp_latest["value"])
    asof = str(pd.to_datetime(gdp_latest["date"]).date())
    
    # Calculate deficit as % GDP (rolling 12m deficit / GDP)
    govt_deficit_pct_gdp = None
    if deficit_df is not None and not deficit_df.empty:
        deficit_df["value"] = pd.to_numeric(deficit_df["value"], errors="coerce")
        deficit_df["deficit"] = -deficit_df["value"]  # Negative values are deficits
        deficit_12m = deficit_df["deficit"].rolling(12).sum()
        if not deficit_12m.dropna().empty:
            # MTSDS133FMS is in millions; GDP is in billions
            deficit_12m_bn = float(deficit_12m.dropna().iloc[-1]) / 1000.0
            govt_deficit_pct_gdp = 100.0 * deficit_12m_bn / gdp_bn
    
    # Net exports as % GDP
    net_exports_pct_gdp = None
    if netexp_df is not None and not netexp_df.empty:
        netexp_df["value"] = pd.to_numeric(netexp_df["value"], errors="coerce")
        netexp_latest = float(netexp_df.dropna(subset=["value"]).iloc[-1]["value"])
        net_exports_pct_gdp = 100.0 * netexp_latest / gdp_bn
    
    # Investment as % GDP
    inv_pct_gdp = None
    if inv_df is not None and not inv_df.empty:
        inv_df["value"] = pd.to_numeric(inv_df["value"], errors="coerce")
        inv_latest = float(inv_df.dropna(subset=["value"]).iloc[-1]["value"])
        inv_pct_gdp = 100.0 * inv_latest / gdp_bn
    
    # Private balance = (G-T) + NX (simplified; investment is separate)
    private_balance = None
    if govt_deficit_pct_gdp is not None and net_exports_pct_gdp is not None:
        private_balance = govt_deficit_pct_gdp + net_exports_pct_gdp
    
    return SectoralBalances(
        govt_deficit_pct_gdp=govt_deficit_pct_gdp,
        net_exports_pct_gdp=net_exports_pct_gdp,
        private_investment_pct_gdp=inv_pct_gdp,
        private_balance_pct_gdp=private_balance,
        asof=asof,
        notes="MMT sectoral balances: S = (G-T) + I + NX. Private balance = deficit + net exports.",
    )


def build_household_dataset(
    settings: Settings,
    start_date: str = "2011-01-01",
    refresh: bool = False,
) -> pd.DataFrame:
    """
    Build daily-grid household dataset with wealth, debt, and behavioral metrics.
    """
    if not settings.FRED_API_KEY:
        raise RuntimeError("Missing FRED_API_KEY in environment / .env")
    
    fred = FredClient(api_key=settings.FRED_API_KEY)
    
    # Fetch all series
    raw: Dict[str, pd.DataFrame] = {}
    for name, sid in HOUSEHOLD_FRED_SERIES.items():
        if name in _OPTIONAL_SERIES:
            df = _fetch_optional(fred=fred, series_id=sid, start_date=start_date, refresh=refresh)
            if df is None:
                continue
        else:
            try:
                df = fred.fetch_series(series_id=sid, start_date=start_date, refresh=refresh)
            except Exception:
                if name in _OPTIONAL_SERIES:
                    continue
                raise
        if df is not None and not df.empty:
            raw[name] = df.sort_values("date").reset_index(drop=True)
    
    # Require at least savings rate for minimal functionality
    if "SAVINGS_RATE" not in raw:
        raise RuntimeError("Failed to load personal savings rate (FRED PSAVERT)")
    
    # Build daily grid
    max_date = max(df["date"].max() for df in raw.values())
    base = pd.DataFrame({
        "date": pd.date_range(start=pd.to_datetime(start_date), end=pd.to_datetime(max_date), freq="D")
    })
    
    # Prepare frames for merging
    frames: Dict[str, pd.DataFrame] = {}
    for name, df in raw.items():
        tmp = df.rename(columns={"value": name})
        tmp[name] = pd.to_numeric(tmp[name], errors="coerce")
        frames[name] = tmp[["date", name]]
    
    # Merge all series onto daily grid with forward fill
    merged = base.copy()
    for name, df in frames.items():
        merged = merged.merge(df, on="date", how="left")
        merged[name] = merged[name].ffill()
    
    # Z-score window (3 years)
    win = 252 * 3
    
    # -------------------------------------------------------------------------
    # Derived metrics
    # -------------------------------------------------------------------------
    
    # Net worth YoY (quarterly data, ~4 observations per year)
    if "NET_WORTH" in merged.columns:
        merged["NET_WORTH_YOY_PCT"] = _yoy_pct_change(merged["NET_WORTH"], periods=4 * 252 // 252)
        # Approximate: forward filled quarterly data on daily grid
        nw_shifted = merged["NET_WORTH"].shift(252)  # ~1 year
        merged["NET_WORTH_YOY_PCT"] = ((merged["NET_WORTH"] / nw_shifted) - 1.0) * 100.0
        merged["Z_NET_WORTH_YOY"] = zscore(merged["NET_WORTH_YOY_PCT"], window=win)
        
        # Real net worth growth (adjust for CPI)
        if "CPI" in merged.columns:
            cpi_yoy = _yoy_pct_change(merged["CPI"], periods=252)
            merged["NET_WORTH_REAL_YOY_PCT"] = merged["NET_WORTH_YOY_PCT"] - cpi_yoy
    
    # Debt service ratio z-score
    if "DEBT_SERVICE_RATIO" in merged.columns:
        merged["Z_DEBT_SERVICE"] = zscore(merged["DEBT_SERVICE_RATIO"], window=win)
        merged["DEBT_SERVICE_YOY_CHG"] = merged["DEBT_SERVICE_RATIO"] - merged["DEBT_SERVICE_RATIO"].shift(252)
    
    # Consumer credit growth
    if "CONSUMER_CREDIT" in merged.columns:
        merged["CONSUMER_CREDIT_YOY_PCT"] = _yoy_pct_change(merged["CONSUMER_CREDIT"], periods=252)
        merged["Z_CONSUMER_CREDIT_YOY"] = zscore(merged["CONSUMER_CREDIT_YOY_PCT"], window=win)
    
    if "REVOLVING_CREDIT" in merged.columns:
        merged["REVOLVING_CREDIT_YOY_PCT"] = _yoy_pct_change(merged["REVOLVING_CREDIT"], periods=252)
    
    # Mortgage delinquency
    if "MORTGAGE_DELINQ" in merged.columns:
        merged["Z_MORTGAGE_DELINQ"] = zscore(merged["MORTGAGE_DELINQ"], window=win)
    
    # Savings rate z-score and 3m average
    if "SAVINGS_RATE" in merged.columns:
        merged["SAVINGS_RATE_3M_AVG"] = merged["SAVINGS_RATE"].rolling(63).mean()  # ~3 months
        merged["Z_SAVINGS_RATE"] = zscore(merged["SAVINGS_RATE"], window=win)
    
    # Consumer sentiment
    if "CONSUMER_SENTIMENT" in merged.columns:
        merged["CONSUMER_SENTIMENT_YOY_CHG"] = merged["CONSUMER_SENTIMENT"] - merged["CONSUMER_SENTIMENT"].shift(252)
        merged["Z_CONSUMER_SENTIMENT"] = zscore(merged["CONSUMER_SENTIMENT"], window=win)
    
    # M2 Velocity
    if "M2_VELOCITY" in merged.columns:
        merged["M2_VELOCITY_YOY_PCT"] = _yoy_pct_change(merged["M2_VELOCITY"], periods=252)
        merged["Z_M2_VELOCITY"] = zscore(merged["M2_VELOCITY"], window=win)
    
    # Real disposable income
    if "REAL_DPI" in merged.columns:
        merged["REAL_DPI_YOY_PCT"] = _yoy_pct_change(merged["REAL_DPI"], periods=252)
        merged["Z_REAL_DPI_YOY"] = zscore(merged["REAL_DPI_YOY_PCT"], window=win)
    
    # Retail sales
    if "RETAIL_SALES" in merged.columns:
        merged["RETAIL_SALES_YOY_PCT"] = _yoy_pct_change(merged["RETAIL_SALES"], periods=252)
        merged["Z_RETAIL_SALES_YOY"] = zscore(merged["RETAIL_SALES_YOY_PCT"], window=win)
    
    # -------------------------------------------------------------------------
    # Composite Scores
    # -------------------------------------------------------------------------
    
    # Wealth score: net worth growth + liquid assets (positive = good)
    def _wealth_score(row: pd.Series) -> float | None:
        weights = {
            "Z_NET_WORTH_YOY": 0.7,
            "Z_SAVINGS_RATE": 0.3,
        }
        return _weighted_score(
            {k: row.get(k) for k in weights},
            weights,
        )
    
    # Debt stress score: debt service + credit growth + delinquency (positive = stress)
    def _debt_stress_score(row: pd.Series) -> float | None:
        weights = {
            "Z_DEBT_SERVICE": 0.4,
            "Z_CONSUMER_CREDIT_YOY": 0.3,
            "Z_MORTGAGE_DELINQ": 0.3,
        }
        return _weighted_score(
            {k: row.get(k) for k in weights},
            weights,
        )
    
    # Behavioral score: sentiment + income + spending (positive = confident/risk-on)
    def _behavioral_score(row: pd.Series) -> float | None:
        weights = {
            "Z_CONSUMER_SENTIMENT": 0.3,
            "Z_REAL_DPI_YOY": 0.3,
            "Z_RETAIL_SALES_YOY": 0.2,
            "Z_M2_VELOCITY": 0.2,
        }
        return _weighted_score(
            {k: row.get(k) for k in weights},
            weights,
        )
    
    merged["WEALTH_SCORE"] = merged.apply(_wealth_score, axis=1)
    merged["DEBT_STRESS_SCORE"] = merged.apply(_debt_stress_score, axis=1)
    merged["BEHAVIORAL_SCORE"] = merged.apply(_behavioral_score, axis=1)
    
    # Overall household prosperity: wealth + behavior - debt stress
    def _prosperity_score(row: pd.Series) -> float | None:
        w = row.get("WEALTH_SCORE")
        b = row.get("BEHAVIORAL_SCORE")
        d = row.get("DEBT_STRESS_SCORE")
        
        components = []
        if w is not None and pd.notna(w):
            components.append(float(w) * 0.4)
        if b is not None and pd.notna(b):
            components.append(float(b) * 0.3)
        if d is not None and pd.notna(d):
            components.append(-float(d) * 0.3)  # Negative: stress hurts prosperity
        
        if not components:
            return None
        return sum(components) / (0.4 + 0.3 + 0.3)
    
    merged["HOUSEHOLD_PROSPERITY_SCORE"] = merged.apply(_prosperity_score, axis=1)
    
    return merged


def build_household_state(
    settings: Settings,
    start_date: str = "2011-01-01",
    refresh: bool = False,
) -> HouseholdState:
    """
    Build complete household regime state snapshot.
    """
    df = build_household_dataset(settings=settings, start_date=start_date, refresh=refresh)
    
    # Get sectoral balances context
    sectoral = build_sectoral_balances(settings=settings, start_date=start_date, refresh=refresh)
    
    # Get latest row with required data
    last = df.dropna(subset=["SAVINGS_RATE"]).iloc[-1]
    
    def _f(col: str) -> float | None:
        val = last.get(col)
        if val is None or pd.isna(val):
            return None
        return float(val)
    
    inputs = HouseholdInputs(
        sectoral=sectoral,
        # Wealth
        net_worth_tn=_f("NET_WORTH"),
        net_worth_yoy_pct=_f("NET_WORTH_YOY_PCT"),
        net_worth_real_yoy_pct=_f("NET_WORTH_REAL_YOY_PCT"),
        z_net_worth_yoy=_f("Z_NET_WORTH_YOY"),
        checkable_deposits_bn=_f("CHECKABLE_DEPOSITS"),
        money_market_funds_bn=_f("MONEY_MARKET_FUNDS"),
        # Debt
        debt_service_ratio=_f("DEBT_SERVICE_RATIO"),
        debt_service_yoy_chg=_f("DEBT_SERVICE_YOY_CHG"),
        z_debt_service=_f("Z_DEBT_SERVICE"),
        consumer_credit_yoy_pct=_f("CONSUMER_CREDIT_YOY_PCT"),
        revolving_credit_yoy_pct=_f("REVOLVING_CREDIT_YOY_PCT"),
        z_consumer_credit_yoy=_f("Z_CONSUMER_CREDIT_YOY"),
        mortgage_delinquency_rate=_f("MORTGAGE_DELINQ"),
        z_mortgage_delinquency=_f("Z_MORTGAGE_DELINQ"),
        # Behavior
        savings_rate=_f("SAVINGS_RATE"),
        savings_rate_3m_avg=_f("SAVINGS_RATE_3M_AVG"),
        z_savings_rate=_f("Z_SAVINGS_RATE"),
        consumer_sentiment=_f("CONSUMER_SENTIMENT"),
        consumer_sentiment_yoy_chg=_f("CONSUMER_SENTIMENT_YOY_CHG"),
        z_consumer_sentiment=_f("Z_CONSUMER_SENTIMENT"),
        m2_velocity=_f("M2_VELOCITY"),
        m2_velocity_yoy_pct=_f("M2_VELOCITY_YOY_PCT"),
        z_m2_velocity=_f("Z_M2_VELOCITY"),
        real_dpi_yoy_pct=_f("REAL_DPI_YOY_PCT"),
        z_real_dpi_yoy=_f("Z_REAL_DPI_YOY"),
        retail_sales_yoy_pct=_f("RETAIL_SALES_YOY_PCT"),
        z_retail_sales_yoy=_f("Z_RETAIL_SALES_YOY"),
        # Composites
        wealth_score=_f("WEALTH_SCORE"),
        debt_stress_score=_f("DEBT_STRESS_SCORE"),
        behavioral_score=_f("BEHAVIORAL_SCORE"),
        household_prosperity_score=_f("HOUSEHOLD_PROSPERITY_SCORE"),
        components={
            "wealth_weights": {"z_net_worth_yoy": 0.7, "z_savings_rate": 0.3},
            "debt_weights": {"z_debt_service": 0.4, "z_credit_yoy": 0.3, "z_delinq": 0.3},
            "behavior_weights": {"z_sentiment": 0.3, "z_dpi": 0.3, "z_retail": 0.2, "z_velocity": 0.2},
            "prosperity_weights": {"wealth": 0.4, "behavior": 0.3, "debt_stress": -0.3},
        },
    )
    
    return HouseholdState(
        asof=str(pd.to_datetime(last["date"]).date()),
        start_date=start_date,
        inputs=inputs,
        notes=(
            "Household wealth regime: tracks where deficit dollars flow (MMT sectoral balances) "
            "and resulting household behavior. Key insight: S = (G-T) + I + NX implies government "
            "deficits create private surpluses; the question is whether they accumulate as "
            "household wealth, service debt, or drive consumption."
        ),
    )
