from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

import pandas as pd


SecuredRate = Literal["sofr", "tgcr", "bgcr", "obfr"]


@dataclass(frozen=True)
class NyFedRateFetchResult:
    rate: str
    df: pd.DataFrame  # columns: date, value
    source: str = "nyfed:markets_api"


def _cache_path(rate: str) -> Path:
    p = Path("data/cache/nyfed") / f"{rate.lower()}.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def fetch_nyfed_secured_rate(
    *,
    rate: SecuredRate,
    start_date: str = "2011-01-01",
    refresh: bool = False,
    cache_max_age: timedelta = timedelta(hours=12),
) -> NyFedRateFetchResult:
    """
    Fetch NY Fed reference rates (secured) as daily time series.

    Endpoint pattern (public):
      https://markets.newyorkfed.org/api/rates/secured/{rate}.json

    We cache the full CSV locally and filter to `start_date` on read.
    """
    rate_l = (rate or "").strip().lower()
    if rate_l not in {"sofr", "tgcr", "bgcr", "obfr"}:
        raise ValueError(f"Unknown rate: {rate!r}")

    p = _cache_path(rate_l)
    start_ts = pd.to_datetime(start_date)
    if p.exists() and not refresh:
        try:
            age = datetime.now(timezone.utc) - datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
            if age <= cache_max_age:
                dfc = pd.read_csv(p)
                dfc["date"] = pd.to_datetime(dfc["date"])
                dfc["value"] = pd.to_numeric(dfc["value"], errors="coerce")
                dfc = dfc.dropna(subset=["date", "value"]).sort_values("date").reset_index(drop=True)
                return NyFedRateFetchResult(rate=rate_l, df=dfc[dfc["date"] >= start_ts].reset_index(drop=True))
        except Exception:
            pass

    import requests

    url = f"https://markets.newyorkfed.org/api/rates/secured/{rate_l}.json"
    # Some environments (notably certain macOS Python builds) can throw odd SSL PermissionErrors.
    # Try verified HTTPS first; if the SSL stack is broken, fall back to verify=False (best-effort).
    source = "nyfed:markets_api"
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        resp.raise_for_status()
        js = resp.json()
    except Exception:
        # Best-effort fallback. We keep it contained to this NY Fed public data pull.
        source = "nyfed:markets_api_insecure"
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30, verify=False)
        resp.raise_for_status()
        js = resp.json()

    # JSON shape: { "refRates": [ { "effectiveDate": "YYYY-MM-DD", "percentRate": "3.64", ... }, ... ] }
    rows = []
    ref = js.get("refRates") if isinstance(js, dict) else None
    if isinstance(ref, list):
        for r in ref:
            if not isinstance(r, dict):
                continue
            d = r.get("effectiveDate") or r.get("effective_date") or r.get("date")
            v = r.get("percentRate") or r.get("percent_rate") or r.get("rate") or r.get("value")
            if d is None or v is None:
                continue
            try:
                rows.append({"date": str(d)[:10], "value": float(str(v))})
            except Exception:
                continue

    df = pd.DataFrame(rows)
    if df.empty:
        # Best-effort: return empty df for caller to handle.
        return NyFedRateFetchResult(rate=rate_l, df=pd.DataFrame(columns=["date", "value"]), source=source)

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["date", "value"]).sort_values("date").reset_index(drop=True)

    # Cache full series to disk
    try:
        df2 = df.copy()
        df2["date"] = df2["date"].dt.strftime("%Y-%m-%d")
        df2.to_csv(p, index=False)
    except Exception:
        pass

    return NyFedRateFetchResult(rate=rate_l, df=df[df["date"] >= start_ts].reset_index(drop=True), source=source)

