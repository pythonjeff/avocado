from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from ai_options_trader.altdata.cache import cache_path, read_cache, write_cache
from ai_options_trader.config import Settings


FMP_BASE_URL = "https://financialmodelingprep.com/api"


def fetch_realtime_quotes(
    *,
    settings: Settings,
    tickers: list[str],
    cache_max_age: timedelta = timedelta(minutes=5),
) -> dict[str, float]:
    """
    Fetch real-time stock/ETF prices from FMP.
    
    Endpoint: /api/v3/quote/{symbols}
    
    Returns:
        dict mapping ticker -> price (e.g., {"SPY": 585.23, "HYG": 77.45})
    """
    if not settings.fmp_api_key or not tickers:
        return {}
    
    # Clean tickers
    clean_tickers = [t.strip().upper() for t in tickers if t.strip()]
    if not clean_tickers:
        return {}
    
    symbols_str = ",".join(clean_tickers)
    key = f"fmp_quotes_{symbols_str}"
    p = cache_path(key)
    cached = read_cache(p, max_age=cache_max_age)
    if isinstance(cached, dict):
        return cached
    
    url = f"{FMP_BASE_URL}/v3/quote/{symbols_str}"
    import requests
    
    try:
        resp = requests.get(
            url,
            params={"apikey": settings.fmp_api_key},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        
        result = {}
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    ticker = item.get("symbol", "").strip().upper()
                    price = item.get("price")
                    if ticker and price is not None:
                        try:
                            result[ticker] = float(price)
                        except (ValueError, TypeError):
                            pass
        
        if result:
            write_cache(p, result)
        return result
    except Exception:
        return {}


def _parse_iso_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).strip().replace("Z", "+00:00")).date()
    except Exception:
        try:
            return datetime.strptime(str(s).strip()[0:10], "%Y-%m-%d").date()
        except Exception:
            return None


@dataclass(frozen=True)
class CompanyProfile:
    ticker: str
    company_name: str | None = None
    exchange: str | None = None
    industry: str | None = None
    sector: str | None = None
    website: str | None = None
    description: str | None = None
    market_cap: float | None = None


@dataclass(frozen=True)
class EarningsEvent:
    ticker: str
    date: date
    time: str | None = None
    eps: float | None = None
    eps_estimated: float | None = None
    revenue: float | None = None
    revenue_estimated: float | None = None


def fetch_earnings_history(
    *,
    settings: Settings,
    ticker: str,
    limit: int = 12,
    cache_max_age: timedelta = timedelta(hours=12),
) -> list[dict[str, Any]]:
    """
    Fetch historical earnings rows for a ticker (best-effort).

    FMP has used multiple endpoint spellings historically, so we try a few:
    - /api/v3/earnings-surprises/{ticker}
    - /api/v3/earnings_surprises/{ticker}
    - /api/v3/historical/earning_calendar/{ticker}

    Returns raw JSON rows (list[dict]) or [].
    """
    if not settings.fmp_api_key:
        return []
    t = (ticker or "").strip().upper()
    if not t:
        return []

    key = f"fmp_earnings_history_{t}_limit{int(limit)}"
    p = cache_path(key)
    cached = read_cache(p, max_age=cache_max_age)
    if isinstance(cached, list):
        return cached

    import requests

    params = {"apikey": settings.fmp_api_key, "limit": int(limit)}
    endpoints = (
        f"{FMP_BASE_URL}/v3/earnings-surprises/{t}",
        f"{FMP_BASE_URL}/v3/earnings_surprises/{t}",
        f"{FMP_BASE_URL}/v3/historical/earning_calendar/{t}",
    )
    for url in endpoints:
        try:
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                rows = [r for r in data if isinstance(r, dict)]
                if rows:
                    write_cache(p, rows[: max(0, int(limit))])
                    return rows[: max(0, int(limit))]
        except Exception:
            continue
    return []


def fetch_stock_news(
    *,
    settings: Settings,
    ticker: str,
    limit: int = 25,
    cache_max_age: timedelta = timedelta(minutes=30),
) -> list[dict[str, Any]]:
    """
    Fetch recent news headlines for a ticker (best-effort).

    Endpoint (typical): /api/v3/stock_news?tickers=AAPL&limit=50
    Returns raw JSON rows (list[dict]) or [].
    """
    if not settings.fmp_api_key:
        return []
    t = (ticker or "").strip().upper()
    if not t:
        return []

    key = f"fmp_stock_news_{t}_limit{int(limit)}"
    p = cache_path(key)
    cached = read_cache(p, max_age=cache_max_age)
    if isinstance(cached, list):
        return cached

    url = f"{FMP_BASE_URL}/v3/stock_news"
    import requests

    try:
        resp = requests.get(
            url,
            params={"tickers": t, "limit": int(limit), "apikey": settings.fmp_api_key},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            rows = [r for r in data if isinstance(r, dict)]
            write_cache(p, rows[: max(0, int(limit))])
            return rows[: max(0, int(limit))]
    except Exception:
        return []
    return []


def fetch_profile(
    *,
    settings: Settings,
    ticker: str,
    cache_max_age: timedelta = timedelta(days=7),
) -> CompanyProfile | None:
    """
    Fetch company profile (best-effort).

    Endpoint is typically: /api/v3/profile/{ticker}
    """
    if not settings.fmp_api_key:
        return None
    t = (ticker or "").strip().upper()
    if not t:
        return None

    key = f"fmp_profile_{t}"
    p = cache_path(key)
    cached = read_cache(p, max_age=cache_max_age)
    if isinstance(cached, list) and cached:
        row = cached[0] if isinstance(cached[0], dict) else None
        if isinstance(row, dict):
            return _profile_from_row(t, row)

    url = f"{FMP_BASE_URL}/v3/profile/{t}"
    import requests
    resp = requests.get(url, params={"apikey": settings.fmp_api_key}, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, list):
        write_cache(p, data)
        if data and isinstance(data[0], dict):
            return _profile_from_row(t, data[0])
    return None


def _profile_from_row(ticker: str, row: dict[str, Any]) -> CompanyProfile:
    def _f(x):
        try:
            return float(x) if x is not None and x != "" else None
        except Exception:
            return None

    return CompanyProfile(
        ticker=ticker,
        company_name=(str(row.get("companyName") or row.get("companyName") or "").strip() or None),
        exchange=(str(row.get("exchangeShortName") or row.get("exchange") or "").strip() or None),
        industry=(str(row.get("industry") or "").strip() or None),
        sector=(str(row.get("sector") or "").strip() or None),
        website=(str(row.get("website") or "").strip() or None),
        description=(str(row.get("description") or "").strip() or None),
        market_cap=_f(row.get("mktCap") or row.get("marketCap")),
    )


def fetch_earnings_calendar(
    *,
    settings: Settings,
    tickers: list[str],
    from_date: str,
    to_date: str,
    cache_max_age: timedelta = timedelta(hours=6),
) -> list[dict[str, Any]]:
    """
    Fetch earnings calendar rows for tickers between from/to dates (best-effort).

    FMP has used multiple endpoint spellings historically, so we try a couple:
    - /api/v3/earning_calendar
    - /api/v3/earnings_calendar
    """
    if not settings.fmp_api_key:
        return []
    syms = [t.strip().upper() for t in tickers if t and t.strip()]
    if not syms:
        return []
    key = f"fmp_earnings_calendar_{','.join(sorted(syms))}_{from_date}_{to_date}"
    p = cache_path(key)
    cached = read_cache(p, max_age=cache_max_age)
    if isinstance(cached, list):
        return cached

    params = {"from": str(from_date), "to": str(to_date), "apikey": settings.fmp_api_key}

    last_err: Exception | None = None
    for ep in ("earning_calendar", "earnings_calendar"):
        try:
            url = f"{FMP_BASE_URL}/v3/{ep}"
            import requests
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                # Filter to requested symbols; some endpoints ignore tickers param.
                rows = [r for r in data if isinstance(r, dict) and str(r.get("symbol") or "").strip().upper() in set(syms)]
                write_cache(p, rows)
                return rows
        except Exception as e:
            last_err = e
            continue
    if last_err:
        # Best-effort: if both endpoints fail, return empty.
        return []
    return []


def normalize_earnings_calendar(rows: list[dict[str, Any]]) -> list[EarningsEvent]:
    out: list[EarningsEvent] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        sym = str(r.get("symbol") or "").strip().upper()
        dt = _parse_iso_date(str(r.get("date") or r.get("fillingDate") or r.get("earningDate") or ""))
        if not sym or dt is None:
            continue

        def _f(x):
            try:
                return float(x) if x is not None and x != "" else None
            except Exception:
                return None

        out.append(
            EarningsEvent(
                ticker=sym,
                date=dt,
                time=(str(r.get("time") or r.get("hour") or "").strip() or None),
                eps=_f(r.get("eps")),
                eps_estimated=_f(r.get("epsEstimated") or r.get("epsEstimate")),
                revenue=_f(r.get("revenue")),
                revenue_estimated=_f(r.get("revenueEstimated") or r.get("revenueEstimate")),
            )
        )
    out.sort(key=lambda x: x.date)
    return out


def build_ticker_dossier(
    *,
    settings: Settings,
    ticker: str,
    days_ahead: int = 180,
) -> dict[str, Any]:
    """
    Minimal alt-data dossier for one ticker.
    Start slow:
    - company profile (static-ish)
    - next earnings event (if any in next N days)
    """
    t = (ticker or "").strip().upper()
    if not t:
        return {}

    prof = fetch_profile(settings=settings, ticker=t)

    now = datetime.now(timezone.utc).date()
    end = now + timedelta(days=int(days_ahead))
    rows = fetch_earnings_calendar(settings=settings, tickers=[t], from_date=now.isoformat(), to_date=end.isoformat())
    ev = normalize_earnings_calendar(rows)
    next_ev = next((e for e in ev if e.date >= now), None)

    return {
        "ticker": t,
        "asof": datetime.now(timezone.utc).date().isoformat(),
        "profile": (prof.__dict__ if prof else None),
        "next_earnings": (next_ev.__dict__ if next_ev else None),
        "earnings_history": fetch_earnings_history(settings=settings, ticker=t, limit=12),
        "news": fetch_stock_news(settings=settings, ticker=t, limit=25),
    }

