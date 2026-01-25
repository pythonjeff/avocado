"""
News and calendar fetching utilities for the LOX FUND Dashboard.
Handles economic calendar, earnings, and market news.
"""
import requests
from datetime import datetime, timezone, timedelta


def fetch_economic_calendar(settings, days_back=3, days_ahead=7):
    """Fetch recent and upcoming economic events from FMP."""
    try:
        if not settings or not getattr(settings, 'FMP_API_KEY', None):
            return [], []
        
        url = "https://financialmodelingprep.com/api/v3/economic_calendar"
        resp = requests.get(url, params={"apikey": settings.FMP_API_KEY}, timeout=15)
        resp.raise_for_status()
        events = resp.json()
        
        if not isinstance(events, list):
            return [], []
        
        now = datetime.now(timezone.utc)
        past_cutoff = now - timedelta(days=days_back)
        future_cutoff = now + timedelta(days=days_ahead)
        
        recent_releases = []
        upcoming_events = []
        
        for event in events:
            if not isinstance(event, dict):
                continue
            
            event_date = _parse_event_date(event.get("date", ""))
            if not event_date:
                continue
            
            # Only US events
            country = event.get("country", "").upper()
            if country and country != "US":
                continue
            
            event_name = event.get("event", "")
            actual = event.get("actual")
            estimate = event.get("estimate")
            previous = event.get("previous")
            
            # Recent releases (with actual values)
            if past_cutoff <= event_date <= now and actual is not None:
                surprise = _calc_surprise(actual, estimate)
                recent_releases.append({
                    "date": event_date.strftime("%Y-%m-%d"),
                    "event": event_name,
                    "actual": actual,
                    "estimate": estimate,
                    "previous": previous,
                    "surprise": surprise,
                })
            # Upcoming events
            elif now < event_date <= future_cutoff:
                upcoming_events.append({
                    "date": event_date.strftime("%Y-%m-%d %H:%M"),
                    "event": event_name,
                    "estimate": estimate,
                    "previous": previous,
                })
        
        recent_releases.sort(key=lambda x: x["date"], reverse=True)
        upcoming_events.sort(key=lambda x: x["date"])
        
        return recent_releases[:10], upcoming_events[:8]
    
    except Exception as e:
        print(f"Economic calendar fetch error: {e}")
        return [], []


def fetch_earnings_history(symbol, api_key, num_quarters=4):
    """Fetch historical earnings surprises for a ticker from FMP."""
    try:
        url = f"https://financialmodelingprep.com/api/v3/earnings-surprises/{symbol}"
        resp = requests.get(url, params={"apikey": api_key}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        
        if not isinstance(data, list) or not data:
            return None
        
        recent = data[:num_quarters]
        beats, misses, meets = 0, 0, 0
        
        for q in recent:
            actual = q.get("actualEarningResult")
            estimate = q.get("estimatedEarning")
            if actual is not None and estimate is not None:
                try:
                    diff = float(actual) - float(estimate)
                    if diff > 0.01:
                        beats += 1
                    elif diff < -0.01:
                        misses += 1
                    else:
                        meets += 1
                except:
                    pass
        
        total = beats + misses + meets
        if total == 0:
            return None
        
        return {
            "beats": beats,
            "misses": misses,
            "meets": meets,
            "total": total,
            "beat_rate": round(beats / total * 100),
            "miss_rate": round(misses / total * 100),
        }
    except Exception as e:
        print(f"Earnings history fetch error for {symbol}: {e}")
        return None


def fetch_earnings_calendar(settings, tickers, days_ahead=14):
    """Fetch upcoming earnings for specified tickers with historical beat/miss data."""
    try:
        if not settings or not getattr(settings, 'FMP_API_KEY', None):
            return []
        
        # ETF holdings mapping
        etf_holdings = {
            "TAN": ["ENPH", "SEDG", "FSLR", "RUN", "CSIQ", "JKS"],
            "HYG": [], "TLT": [], "VIXM": [], "GLDM": [],
        }
        
        # Expand tickers to include ETF holdings
        all_tickers = set()
        for ticker in tickers:
            base_ticker = ticker.split()[0] if ' ' in ticker else ticker
            base_ticker = ''.join([c for c in base_ticker if not c.isdigit()]).strip()
            
            if base_ticker in etf_holdings:
                all_tickers.update(etf_holdings[base_ticker])
            else:
                all_tickers.add(base_ticker)
        
        if not all_tickers:
            return []
        
        now = datetime.now(timezone.utc)
        from_date = now.strftime("%Y-%m-%d")
        to_date = (now + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
        
        url = "https://financialmodelingprep.com/api/v3/earning_calendar"
        resp = requests.get(url, params={
            "apikey": settings.FMP_API_KEY,
            "from": from_date,
            "to": to_date,
        }, timeout=15)
        resp.raise_for_status()
        earnings = resp.json()
        
        if not isinstance(earnings, list):
            return []
        
        relevant_earnings = []
        for e in earnings:
            symbol = e.get("symbol", "").upper()
            if symbol in [t.upper() for t in all_tickers]:
                history = fetch_earnings_history(symbol, settings.FMP_API_KEY, num_quarters=4)
                relevant_earnings.append({
                    "date": e.get("date", ""),
                    "symbol": symbol,
                    "time": e.get("time", ""),
                    "eps_estimate": e.get("epsEstimated"),
                    "revenue_estimate": e.get("revenueEstimated"),
                    "history": history,
                })
        
        relevant_earnings.sort(key=lambda x: x["date"])
        return relevant_earnings
    
    except Exception as e:
        print(f"Earnings calendar fetch error: {e}")
        return []


def fetch_macro_headlines(settings, portfolio_tickers=None, limit=3):
    """Fetch headlines ONLY for portfolio tickers - top 3 most relevant."""
    headlines = []
    
    try:
        if not portfolio_tickers or not settings:
            return headlines
        
        # Filter to clean underlying tickers only
        clean_tickers = list(set([
            t.upper() for t in portfolio_tickers 
            if t and len(t) <= 5 and t.isalpha() and t.upper() not in ['C', 'P']
        ]))
        
        if not clean_tickers:
            return headlines
        
        api_key = getattr(settings, 'fmp_api_key', None) or getattr(settings, 'FMP_API_KEY', None)
        if not api_key:
            return headlines
        
        tickers_str = ",".join(clean_tickers[:8])
        url = f"https://financialmodelingprep.com/api/v3/stock_news?tickers={tickers_str}&limit={limit * 3}&apikey={api_key}"
        
        resp = requests.get(url, timeout=10)
        data = resp.json()
        
        if isinstance(data, list):
            now = datetime.now(timezone.utc)
            for item in data:
                title = item.get("title", "") or ""
                if not title:
                    continue
                
                time_str = _format_relative_time(item.get("publishedDate", ""), now)
                
                headlines.append({
                    "headline": title[:100],
                    "source": (item.get("site", "") or "News")[:15],
                    "time": time_str,
                    "ticker": item.get("symbol", "") or "",
                    "url": item.get("url", "") or "",
                })
        
        # Dedupe by headline
        seen = set()
        unique_headlines = []
        for h in headlines:
            key = h["headline"][:50].lower()
            if key not in seen:
                seen.add(key)
                unique_headlines.append(h)
        
        return unique_headlines[:limit]
        
    except Exception as e:
        print(f"[Headlines] Error: {e}")
    
    return headlines


def get_event_source_url(event_name: str) -> str:
    """Map economic event names to authoritative source URLs."""
    event_lower = event_name.lower()
    
    # Federal Reserve / FOMC
    if any(kw in event_lower for kw in ['fomc', 'fed ', 'federal reserve', 'powell', 'rate decision']):
        return "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
    
    # Treasury / Auctions
    if any(kw in event_lower for kw in ['treasury', 'auction', 't-bill', 't-bond', 't-note']):
        return "https://www.treasurydirect.gov/auctions/upcoming/"
    
    # Employment / Jobs (BLS)
    if any(kw in event_lower for kw in ['payroll', 'employment', 'unemployment', 'jobless', 'nonfarm', 'jobs']):
        return "https://www.bls.gov/news.release/empsit.toc.htm"
    
    # Inflation - CPI (BLS)
    if 'cpi' in event_lower or 'consumer price' in event_lower:
        return "https://www.bls.gov/cpi/"
    
    # Inflation - PCE (BEA)
    if 'pce' in event_lower or 'personal consumption' in event_lower:
        return "https://www.bea.gov/data/personal-consumption-expenditures-price-index"
    
    # GDP (BEA)
    if 'gdp' in event_lower or 'gross domestic' in event_lower:
        return "https://www.bea.gov/data/gdp/gross-domestic-product"
    
    # Retail Sales (Census)
    if 'retail' in event_lower:
        return "https://www.census.gov/retail/index.html"
    
    # Housing (Census)
    if any(kw in event_lower for kw in ['housing', 'home sales', 'building permits', 'housing starts']):
        return "https://www.census.gov/construction/nrc/index.html"
    
    # ISM / PMI
    if any(kw in event_lower for kw in ['ism', 'pmi', 'manufacturing index', 'services index']):
        return "https://www.ismworld.org/supply-management-news-and-reports/reports/ism-report-on-business/"
    
    # Durable Goods (Census)
    if 'durable' in event_lower:
        return "https://www.census.gov/manufacturing/m3/index.html"
    
    # Consumer Confidence (Conference Board)
    if 'consumer confidence' in event_lower or 'consumer sentiment' in event_lower:
        return "https://www.conference-board.org/topics/consumer-confidence"
    
    # Default: Trading Economics calendar
    return "https://tradingeconomics.com/united-states/calendar"


def _parse_event_date(date_str: str):
    """Parse event date string to datetime."""
    if not date_str:
        return None
    
    date_str = date_str.replace(" ", "T")
    try:
        return datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
    except:
        try:
            return datetime.strptime(date_str.split("T")[0], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except:
            return None


def _calc_surprise(actual, estimate):
    """Calculate earnings/economic surprise."""
    if estimate is None or actual is None:
        return None
    try:
        return float(actual) - float(estimate)
    except:
        return None


def _format_relative_time(published: str, now: datetime) -> str:
    """Format published time as relative string (e.g., '2h ago')."""
    if not published:
        return ""
    try:
        dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
        diff = now - dt
        hours = diff.total_seconds() / 3600
        if hours < 1:
            return f"{int(diff.total_seconds() / 60)}m ago"
        elif hours < 24:
            return f"{int(hours)}h ago"
        else:
            return dt.strftime("%b %d")
    except:
        return ""
