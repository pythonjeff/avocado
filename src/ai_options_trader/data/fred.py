from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class FredSeries:
    series_id: str
    frequency: str  # "daily" or "monthly"


DEFAULT_SERIES = {
    # inflation "reality"
    "CPIAUCSL": FredSeries("CPIAUCSL", "monthly"),
    "CPILFESL": FredSeries("CPILFESL", "monthly"),
    "MEDCPIM158SFRBCLE": FredSeries("MEDCPIM158SFRBCLE", "monthly"),  # Median CPI (Cleveland Fed)
    # labor market
    "PAYEMS": FredSeries("PAYEMS", "monthly"),  # Total Nonfarm Payrolls (level)
    "UNRATE": FredSeries("UNRATE", "monthly"),  # Unemployment rate
    "ICSA": FredSeries("ICSA", "weekly"),  # Initial jobless claims
    # inflation "expectations"
    "T5YIE": FredSeries("T5YIE", "daily"),  # 5Y breakeven
    "T10YIE": FredSeries("T10YIE", "daily"),  # 10Y breakeven
    "T5YIFR": FredSeries("T5YIFR", "daily"),  # 5y5y forward inflation expectation
    # rates
    "DFF": FredSeries("DFF", "daily"),
    "DGS2": FredSeries("DGS2", "daily"),
    "DGS10": FredSeries("DGS10", "daily"),
    # credit spreads (systemic stress)
    "BAMLH0A0HYM2": FredSeries("BAMLH0A0HYM2", "daily"),  # ICE BofA US High Yield OAS
    "BAMLC0A0CM": FredSeries("BAMLC0A0CM", "daily"),  # ICE BofA US Corporate OAS (IG)
    # volatility
    "VIXCLS": FredSeries("VIXCLS", "daily"),  # CBOE VIX (1-month implied vol)
    # VXMTCLS (VIX Mid-Term) removed due to persistent FRED API issues
    # dollar / FX
    "DTWEXBGS": FredSeries("DTWEXBGS", "daily"),  # Trade Weighted US Dollar Index: Broad, Goods and Services
    # commodities
    "DCOILWTICO": FredSeries("DCOILWTICO", "daily"),  # WTI Crude Oil Price
    # housing
    "MORTGAGE30US": FredSeries("MORTGAGE30US", "weekly"),  # 30-Year Fixed Rate Mortgage Average
    "CSUSHPISA": FredSeries("CSUSHPISA", "monthly"),  # S&P/Case-Shiller U.S. National Home Price Index
}

# Optional series that won't crash if unavailable
OPTIONAL_SERIES = {
    "DCOILWTICO",  # Oil (weekends/holidays)
    "VIXCLS",  # VIX (market hours only)
    # "VXMTCLS",  # VIX Mid-Term - Removed due to FRED API issues
    "BAMLH0A0HYM2",  # Credit spreads (sometimes delayed)
    "BAMLC0A0CM",
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
        start_date: str = "2011-01-01",
        refresh: bool = False,
    ) -> pd.DataFrame:
        """
        Returns DataFrame with columns: date (datetime64), value (float).
        """
        cache_path = self._cache_path(series_id)
        start_ts = pd.to_datetime(start_date)
        if cache_path.exists() and not refresh:
            df = pd.read_csv(cache_path)
            df["date"] = pd.to_datetime(df["date"])
            # Always prefer cache when available; filter to requested start.
            # This avoids unnecessary network calls (and common small "start_date" vs business-day gaps).
            if not df.empty:
                return df[df["date"] >= start_ts].reset_index(drop=True)

        # Lazy import so unit tests / restricted environments can import this module
        # without triggering SSL/cert initialization.
        import requests
        from requests.exceptions import RequestException

        url = "https://api.stlouisfed.org/fred/series/observations"
        params = {
            "series_id": series_id,
            "api_key": self.api_key,
            "file_type": "json",
            "observation_start": start_date,
        }
        last_err: Exception | None = None
        for _attempt in range(3):
            try:
                r = requests.get(url, params=params, timeout=30)
                r.raise_for_status()
                js = r.json()
                break
            except RequestException as e:
                # Some FRED series appear to intermittently reject `observation_start` with 400s.
                # Fall back to requesting the full history and filtering client-side.
                try:
                    status = getattr(getattr(e, "response", None), "status_code", None)
                except Exception:
                    status = None
                if status == 400 and "observation_start" in params:
                    params2 = dict(params)
                    params2.pop("observation_start", None)
                    try:
                        r2 = requests.get(url, params=params2, timeout=30)
                        r2.raise_for_status()
                        js = r2.json()
                        break
                    except RequestException as e2:
                        last_err = e2
                        continue
                last_err = e
        else:
            # Network failed; fall back to cache if available.
            if cache_path.exists():
                df = pd.read_csv(cache_path)
                df["date"] = pd.to_datetime(df["date"])
                return df[df["date"] >= start_ts].reset_index(drop=True)
            raise last_err  # type: ignore[misc]

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
        return df[df["date"] >= start_ts].reset_index(drop=True)