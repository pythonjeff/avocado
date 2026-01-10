from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

InteractionMode = str  # "none"|"whitelist"|"all"


@dataclass(frozen=True)
class MacroPanelDataset:
    """
    Panel dataset for cross-sectional forecasting:
      - rows: (date, ticker)
      - features: regime features (shared) + simple ticker state (momentum/vol)
      - label: forward return over horizon_days
    """

    X: pd.DataFrame  # columns = model features (numeric), index = MultiIndex(date,ticker)
    y: pd.Series  # forward return (%), aligned to X.index


def _forward_return(prices: pd.Series, days: int) -> pd.Series:
    return (prices.shift(-days) / prices - 1.0) * 100.0


def build_macro_panel_dataset(
    *,
    regime_features: pd.DataFrame,  # index=date, numeric columns
    prices: pd.DataFrame,  # index=date, columns=tickers
    tickers: list[str],
    horizon_days: int = 63,
    interaction_mode: InteractionMode = "none",
    whitelist_extra: str = "none",  # none|macro|funding|rates|vol|commod|fiscal (only used when interaction_mode=whitelist)
) -> MacroPanelDataset:
    px = prices.sort_index().ffill()
    Xr = regime_features.sort_index()

    idx = Xr.index.intersection(px.index)
    Xr = Xr.loc[idx].copy()
    # IMPORTANT: do NOT drop rows with any NaN across the entire regime matrix.
    # Some regime families (esp. fiscal / optional series) start later or are best-effort,
    # and a strict row-wise drop will often wipe out the entire dataset.
    #
    # Strategy:
    # - Drop regime columns with very low coverage (mostly-NaN)
    # - Forward-fill remaining regime columns (most are low-frequency series merged onto daily grid)
    # - Drop the remaining leading/trailing NaNs
    if not Xr.empty:
        # Keep columns that are present at least this fraction of days.
        min_col_coverage = 0.60
        keep_cols = [c for c in Xr.columns if float(Xr[c].notna().mean()) >= float(min_col_coverage)]
        if keep_cols:
            Xr = Xr[keep_cols]
        Xr = Xr.ffill().dropna(how="any")
    px = px.loc[idx]

    if Xr.empty:
        return MacroPanelDataset(X=pd.DataFrame(), y=pd.Series(dtype=float))

    # Simple ticker state features (kept light)
    ret_20d = (px / px.shift(20) - 1.0) * 100.0
    vol_20d = px.pct_change().rolling(20).std(ddof=0) * np.sqrt(252) * 100.0

    # Labels
    y_fwd = {}
    for t in tickers:
        if t in px.columns:
            y_fwd[t] = _forward_return(px[t], int(horizon_days))
    ydf = pd.DataFrame(y_fwd, index=px.index)

    # Build long panel (date x ticker)
    rows: list[dict] = []
    for d in Xr.index:
        rf = Xr.loc[d].to_dict()
        for t in tickers:
            if t not in ydf.columns:
                continue
            yv = ydf.at[d, t]
            if not np.isfinite(yv):
                continue
            rows.append(
                {
                    "date": d,
                    "ticker": t,
                    **rf,
                    "ticker_ret_20d": float(ret_20d.at[d, t]) if np.isfinite(ret_20d.at[d, t]) else np.nan,
                    "ticker_vol_20d_ann": float(vol_20d.at[d, t]) if np.isfinite(vol_20d.at[d, t]) else np.nan,
                    "y_fwd": float(yv),
                }
            )

    if not rows:
        return MacroPanelDataset(X=pd.DataFrame(), y=pd.Series(dtype=float))

    df = pd.DataFrame(rows).set_index(["date", "ticker"]).sort_index()

    y = pd.to_numeric(df["y_fwd"], errors="coerce").replace([np.inf, -np.inf], np.nan)
    X_base = df.drop(columns=["y_fwd"])

    # One-hot ticker (macro representations)
    ticker_oh = pd.get_dummies(X_base.reset_index()["ticker"], prefix="tkr")
    ticker_oh.index = X_base.index

    X = pd.concat([X_base, ticker_oh], axis=1).replace([np.inf, -np.inf], np.nan)

    mode = (interaction_mode or "none").strip().lower()
    if mode not in {"none", "whitelist", "all"}:
        mode = "none"

    def _add_interactions(regime_cols: list[str], tkr_cols: list[str]) -> pd.DataFrame:
        if not regime_cols or not tkr_cols:
            return X
        blocks = []
        R = X_base[regime_cols]
        for tcol in tkr_cols:
            s = ticker_oh[tcol]
            blk = R.mul(s, axis=0).rename(columns={rc: f"{rc}__x__{tcol}" for rc in regime_cols})
            blocks.append(blk)
        return pd.concat([X] + blocks, axis=1) if blocks else X

    # Regime×ticker interactions:
    # - "all" is very high dimensional and can overfit on small cross-sections.
    # - "whitelist" keeps only macro-economic interactions aligned to the thesis.
    if mode == "all":
        regime_cols = [c for c in X_base.columns if c.startswith(("macro_", "funding_", "usd_", "rates_", "vol_", "commod_"))]
        tkr_cols = [c for c in ticker_oh.columns if c.startswith("tkr_")]
        X = _add_interactions(regime_cols, tkr_cols)
    elif mode == "whitelist":
        # Intentionally minimal interaction set:
        # USD narrative only: USD strength × every ticker.
        # This lets the model learn "USD up helps UUP, USD up hurts QQQM" without exploding dimensionality.
        usd_feat = None
        if "usd_strength_score" in X_base.columns:
            usd_feat = "usd_strength_score"
        elif "usd_z_level" in X_base.columns:
            usd_feat = "usd_z_level"
        elif "fci_usd" in X_base.columns:
            # When using `--feature-set fci`, the USD component is exposed as fci_usd.
            usd_feat = "fci_usd"

        extra = (whitelist_extra or "none").strip().lower()
        if extra not in {"none", "macro", "funding", "rates", "vol", "commod", "fiscal"}:
            extra = "none"
        extra_feat = None
        if extra == "macro":
            # Macro narrative: "disconnect" is an explainable global signal already in the matrix.
            if "macro_disconnect_score" in X_base.columns:
                extra_feat = "macro_disconnect_score"
        elif extra == "funding":
            if "fci_funding" in X_base.columns:
                extra_feat = "fci_funding"
            elif "funding_tightness_score" in X_base.columns:
                extra_feat = "funding_tightness_score"
        elif extra == "rates":
            if "fci_rates" in X_base.columns:
                extra_feat = "fci_rates"
            elif "rates_z_ust_10y_chg_20d" in X_base.columns:
                extra_feat = "rates_z_ust_10y_chg_20d"
            elif "rates_z_ust_10y" in X_base.columns:
                extra_feat = "rates_z_ust_10y"
        elif extra == "vol":
            if "fci_vol" in X_base.columns:
                extra_feat = "fci_vol"
            elif "vol_pressure_score" in X_base.columns:
                extra_feat = "vol_pressure_score"
            elif "vol_z_vix" in X_base.columns:
                extra_feat = "vol_z_vix"
        elif extra == "commod":
            if "commod_pressure_score" in X_base.columns:
                extra_feat = "commod_pressure_score"
        elif extra == "fiscal":
            # Fiscal narrative: deficit/issuance/auction pressure. Prefer the composite score when available.
            if "fiscal_pressure_score" in X_base.columns:
                extra_feat = "fiscal_pressure_score"
            elif "fiscal_z_deficit_12m" in X_base.columns:
                extra_feat = "fiscal_z_deficit_12m"

        regime_cols = [c for c in [usd_feat, extra_feat] if c]
        tkr_cols = [c for c in ticker_oh.columns if c.startswith("tkr_")]
        X = _add_interactions(regime_cols, tkr_cols)

    keep = X.dropna().index.intersection(y.dropna().index)
    return MacroPanelDataset(X=X.loc[keep], y=y.loc[keep])


