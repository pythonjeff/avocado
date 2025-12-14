from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd
import requests


@dataclass(frozen=True)
class FredSeries:
    series_id: str
    frequency: str  # "daily" or "monthly"


DEFAULT_SERIES = {
    # inflation "reality"
    "CPIAUCSL": FredSeries("CPIAUCSL", "monthly"),
    "CPILFESL": FredSeries("CPILFESL", "monthly"),
    # inflation "expectations"
    "T5YIE": FredSeries("T5YIE", "daily"),
    "T10YIE": FredSeries("T10YIE", "daily"),
    # rates
    "DFF": FredSeries("DFF", "daily"),
    "DGS2": FredSeries("DGS2", "daily"),
    "DGS10": FredSeries("DGS10", "daily"),
}


class FredClient:
    def __init__(self, api_key: str, cache_dir: str = "data/cache/fred"):
        self.api_key = api_key
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, series_id: str) -> Path:
        return self.cache_dir / f"{series_id}.csv"

    def fetch_series(
        self,
        series_id: str,
        start_date: str = "2016-01-01",
        refresh: bool = False,
    ) -> pd.DataFrame:
        """
        Returns DataFrame with columns: date (datetime64), value (float).
        """
        cache_path = self._cache_path(series_id)
        if cache_path.exists() and not refresh:
            df = pd.read_csv(cache_path)
            df["date"] = pd.to_datetime(df["date"])
            return df

        url = "https://api.stlouisfed.org/fred/series/observations"
        params = {
            "series_id": series_id,
            "api_key": self.api_key,
            "file_type": "json",
            "observation_start": start_date,
        }
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        js = r.json()

        obs = js.get("observations", [])
        rows = []
        for o in obs:
            v = o.get("value")
            if v is None or v == ".":
                continue
            try:
                rows.append({"date": o["date"], "value": float(v)})
            except Exception:
                continue

        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)

        df.to_csv(cache_path, index=False)
        return df
