"""
v3.5: Train correlations on actual historical market data.

Instead of hand-coded correlations, this learns from real data:
- Download historical VIX, SPX, rates, spreads
- Calculate actual correlations
- Regime-conditional (different in different regimes)
- Validate on holdout data
"""
from __future__ import annotations

import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Tuple

from ai_options_trader.config import Settings
from ai_options_trader.data.fred import FredClient


class CorrelationTrainer:
    """
    Train correlation matrices from historical data.
    
    This replaces hand-coded correlations with learned ones.
    """
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.fred = FredClient(api_key=settings.FRED_API_KEY)
    
    def fetch_training_data(
        self,
        start_date: str = "2010-01-01",
        end_date: str | None = None,
    ) -> pd.DataFrame:
        """
        Fetch historical data for all relevant variables.
        
        Returns daily DataFrame with columns:
        - vix, spx, ust_10y, ust_2y, hy_oas, cpi_yoy
        """
        if end_date is None:
            end_date = datetime.now().strftime("%Y-%m-%d")
        
        print(f"Fetching training data from {start_date} to {end_date}...")
        
        # Fetch all series
        series = {
            "VIX": "VIXCLS",
            "10Y": "DGS10",
            "2Y": "DGS2",
            "HY_OAS": "BAMLH0A0HYM2",
            "CPI": "CPIAUCSL",
        }
        
        dfs = {}
        for name, series_id in series.items():
            try:
                df = self.fred.fetch_series(series_id=series_id, start_date=start_date, refresh=False)
                df = df.rename(columns={"value": name})
                df = df.set_index("date")
                dfs[name] = df
            except Exception as e:
                print(f"Warning: Could not fetch {name}: {e}")
        
        # Merge all
        merged = pd.concat(dfs.values(), axis=1)
        merged = merged.sort_index()
        
        # Forward fill (CPI is monthly, others are daily)
        merged = merged.ffill()
        
        # Calculate returns/changes
        merged["vix_chg_pct"] = merged["VIX"].pct_change()
        merged["ust_10y_chg_bps"] = merged["10Y"].diff() * 100
        merged["ust_2y_chg_bps"] = merged["2Y"].diff() * 100
        merged["hy_oas_chg_bps"] = merged["HY_OAS"].diff()
        merged["cpi_yoy"] = merged["CPI"].pct_change(12) * 100
        
        # Drop NaN
        merged = merged.dropna()
        
        print(f"✓ Fetched {len(merged)} days of data")
        
        return merged
    
    def classify_regime(self, df: pd.DataFrame) -> pd.Series:
        """
        Classify each day into a regime based on macro conditions.
        
        Returns Series with regime labels:
        - "DISINFLATIONARY": CPI falling, growth positive
        - "INFLATIONARY": CPI rising, growth positive
        - "STAGFLATION": CPI high, growth negative
        - "GOLDILOCKS": CPI low, growth positive
        """
        regime = pd.Series("DISINFLATIONARY", index=df.index)
        
        # Simplified regime classification
        # In production, use your actual regime classifier
        high_inflation = df["cpi_yoy"] > 3.0
        rising_inflation = df["cpi_yoy"].diff(20) > 0  # Rising over last 20 days
        
        # Stagflation: high inflation
        regime[high_inflation & rising_inflation] = "STAGFLATION"
        
        # Inflationary: inflation rising but not yet high
        regime[~high_inflation & rising_inflation] = "INFLATIONARY"
        
        # Goldilocks: low and stable
        regime[(df["cpi_yoy"] < 2.5) & ~rising_inflation] = "GOLDILOCKS"
        
        return regime
    
    def calculate_correlation_matrix(
        self,
        df: pd.DataFrame,
        regime: str | None = None,
    ) -> Tuple[np.ndarray, Dict[str, int]]:
        """
        Calculate correlation matrix from historical data.
        
        Args:
            df: Historical data
            regime: If specified, filter to this regime only
        
        Returns:
            correlation_matrix: NxN correlation matrix
            variable_map: Dict mapping variable name to index
        """
        # Filter by regime if specified
        if regime:
            regime_series = self.classify_regime(df)
            df = df[regime_series == regime]
            print(f"  Regime '{regime}': {len(df)} days")
        
        # Select change variables
        change_vars = [
            "vix_chg_pct",
            "ust_10y_chg_bps",
            "ust_2y_chg_bps",
            "hy_oas_chg_bps",
        ]
        
        # Calculate correlation
        corr_df = df[change_vars].corr()
        corr_matrix = corr_df.values
        
        # Create variable map
        variable_map = {var: i for i, var in enumerate(change_vars)}
        
        return corr_matrix, variable_map
    
    def train_all_regimes(
        self,
        start_date: str = "2010-01-01",
    ) -> Dict[str, np.ndarray]:
        """
        Train correlation matrices for all regimes.
        
        Returns dict: regime_name -> correlation_matrix
        """
        print("\n=== Training Correlation Matrices from Historical Data ===\n")
        
        # Fetch data
        df = self.fetch_training_data(start_date=start_date)
        
        # Train for each regime
        regimes = ["ALL", "DISINFLATIONARY", "INFLATIONARY", "STAGFLATION", "GOLDILOCKS"]
        correlations = {}
        
        for regime in regimes:
            print(f"\nTraining {regime}...")
            if regime == "ALL":
                corr, var_map = self.calculate_correlation_matrix(df, regime=None)
            else:
                corr, var_map = self.calculate_correlation_matrix(df, regime=regime)
            
            # Check if we have enough data
            if np.isnan(corr).all():
                print(f"  ⚠️  Insufficient data for {regime} - skipping")
                print(f"     Will use ALL regime as fallback")
                continue
            
            correlations[regime] = corr
            
            # Print correlation matrix
            print(f"\nCorrelation Matrix ({regime}):")
            print("                VIX     10Y     2Y      HY_OAS")
            for i, var in enumerate(["vix_chg_pct", "ust_10y_chg_bps", "ust_2y_chg_bps", "hy_oas_chg_bps"]):
                row_str = f"{var:15s}"
                for j in range(4):
                    row_str += f" {corr[i, j]:7.2f}"
                print(row_str)
        
        # Save to cache
        self._save_correlations(correlations)
        
        print("\n✓ Training complete! Correlations saved.")
        
        return correlations
    
    def _save_correlations(self, correlations: Dict[str, np.ndarray]) -> None:
        """Save trained correlations to cache."""
        cache_dir = Path("data/cache/correlations")
        cache_dir.mkdir(parents=True, exist_ok=True)
        
        for regime, corr in correlations.items():
            np.save(cache_dir / f"{regime.lower()}.npy", corr)
    
    def load_correlations(self, regime: str = "ALL") -> np.ndarray | None:
        """Load trained correlations from cache."""
        cache_file = Path(f"data/cache/correlations/{regime.lower()}.npy")
        if cache_file.exists():
            return np.load(cache_file)
        return None


def validate_correlations(trainer: CorrelationTrainer, regime: str = "ALL") -> Dict[str, float]:
    """
    Validate correlation matrix on holdout data.
    
    Returns dict of validation metrics:
    - mse: Mean squared error
    - mae: Mean absolute error
    """
    print(f"\n=== Validating Correlations ({regime}) ===\n")
    
    # Fetch data and split into train/test
    df = trainer.fetch_training_data(start_date="2010-01-01")
    
    split_date = "2022-01-01"
    train_df = df[df.index < split_date]
    test_df = df[df.index >= split_date]
    
    print(f"Train: {len(train_df)} days (before {split_date})")
    print(f"Test:  {len(test_df)} days (after {split_date})")
    
    # Train on train set
    if regime == "ALL":
        train_corr, var_map = trainer.calculate_correlation_matrix(train_df, regime=None)
        test_corr, _ = trainer.calculate_correlation_matrix(test_df, regime=None)
    else:
        train_corr, var_map = trainer.calculate_correlation_matrix(train_df, regime=regime)
        test_corr, _ = trainer.calculate_correlation_matrix(test_df, regime=regime)
    
    # Calculate errors
    mse = np.mean((train_corr - test_corr) ** 2)
    mae = np.mean(np.abs(train_corr - test_corr))
    
    print(f"\nValidation Results:")
    print(f"  MSE: {mse:.4f}")
    print(f"  MAE: {mae:.4f}")
    
    if mae < 0.15:
        print(f"  ✓ Good: Correlations are stable across time")
    elif mae < 0.25:
        print(f"  ⚠️  Moderate: Some drift in correlations")
    else:
        print(f"  ⚠️  High: Correlations changing significantly (regime shift?)")
    
    return {"mse": mse, "mae": mae}
