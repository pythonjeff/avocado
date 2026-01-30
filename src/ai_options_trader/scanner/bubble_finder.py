"""
Bubble Finder - Scans for extreme moves and analyzes reversion potential.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional, Literal
import numpy as np
import pandas as pd

from ai_options_trader.config import Settings


@dataclass
class BubbleCandidate:
    """A stock identified as having an extreme move."""
    
    ticker: str
    name: Optional[str] = None
    sector: Optional[str] = None
    
    # Current state
    price: float = 0
    market_cap: Optional[float] = None
    
    # Move metrics
    move_type: Literal["bubble", "crash"] = "bubble"  # bubble = run-up, crash = run-down
    ret_5d_pct: float = 0
    ret_20d_pct: float = 0
    ret_60d_pct: float = 0
    
    # Z-scores vs history
    zscore_20d: float = 0
    zscore_60d: float = 0
    
    # Technical state
    pct_from_50ma: float = 0
    pct_from_200ma: float = 0
    rsi_14: float = 50
    
    # Bubble metrics
    bubble_score: float = 0  # 0-100 for bubbles, negative for crashes
    extension_pct: float = 0  # Distance from fair value (200MA)
    
    # Reversion analysis
    reversion_score: float = 0  # 0-100 probability of reversion
    reversion_direction: Literal["down", "up", "neutral"] = "neutral"
    
    # Reason analysis
    has_recent_earnings: bool = False
    earnings_surprise_pct: Optional[float] = None
    has_recent_news: bool = False
    news_sentiment: Optional[str] = None  # "bullish", "bearish", "neutral"
    sector_move: bool = False  # Is sector also moving?
    
    # Trade idea
    trade_recommendation: Optional[str] = None
    confidence: float = 0  # 0-100


@dataclass
class BubbleScanResult:
    """Results from bubble scanning."""
    
    scan_date: date
    universe: str
    total_scanned: int
    
    bubbles: list[BubbleCandidate] = field(default_factory=list)  # Run-ups
    crashes: list[BubbleCandidate] = field(default_factory=list)  # Run-downs
    
    # Summary stats
    bubble_count: int = 0
    crash_count: int = 0
    avg_bubble_score: float = 0
    avg_crash_score: float = 0


def get_universe_tickers(universe: str, settings: Settings) -> list[str]:
    """Get list of tickers for a given universe."""
    
    if universe.lower() == "sp500":
        # Use S&P 500 from our universe module
        try:
            from ai_options_trader.universe.sp500 import get_sp500_tickers
            return get_sp500_tickers()
        except ImportError:
            # Fallback to a static list of major tickers
            return _get_fallback_sp500()
    
    elif universe.lower() == "etfs":
        return [
            # Major index ETFs
            "SPY", "QQQ", "IWM", "DIA",
            # Sector ETFs
            "XLF", "XLE", "XLK", "XLV", "XLI", "XLP", "XLU", "XLY", "XLB", "XLRE",
            # International
            "EEM", "EFA", "FXI", "EWZ", "EWJ",
            # Commodities
            "GLD", "SLV", "USO", "UNG", "DBC",
            # Bonds
            "TLT", "IEF", "HYG", "LQD",
            # Volatility
            "UVXY", "VXX",
            # Thematic
            "ARKK", "XBI", "SMH", "KWEB",
        ]
    
    elif universe.lower() == "mega":
        return [
            "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
            "JPM", "V", "JNJ", "UNH", "XOM", "PG", "MA", "HD", "CVX", "MRK",
            "ABBV", "PEP", "KO", "COST", "AVGO", "TMO", "WMT", "MCD", "CSCO",
            "ACN", "ABT", "DHR", "NEE", "LLY", "BMY", "UPS", "NKE", "PM",
        ]
    
    elif universe.lower() == "tech":
        return [
            "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "AVGO",
            "ORCL", "CRM", "AMD", "ADBE", "INTC", "CSCO", "QCOM", "TXN",
            "NOW", "IBM", "AMAT", "MU", "LRCX", "SNPS", "CDNS", "KLAC",
            "PANW", "CRWD", "ZS", "DDOG", "NET", "SNOW", "PLTR", "U",
        ]
    
    else:
        # Assume it's a comma-separated list
        return [t.strip().upper() for t in universe.split(",")]


def _get_fallback_sp500() -> list[str]:
    """Fallback S&P 500 list (top 100 by market cap)."""
    return [
        "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
        "JPM", "V", "JNJ", "UNH", "XOM", "PG", "MA", "HD", "CVX", "MRK",
        "ABBV", "PEP", "KO", "COST", "AVGO", "TMO", "WMT", "MCD", "CSCO",
        "ACN", "ABT", "DHR", "NEE", "LLY", "BMY", "UPS", "NKE", "PM",
        "CMCSA", "VZ", "T", "INTC", "DIS", "AMD", "CRM", "ADBE", "ORCL",
        "BA", "GE", "CAT", "DE", "RTX", "HON", "LMT", "GD", "NOC",
        "GS", "MS", "C", "BAC", "WFC", "AXP", "BLK", "SCHW", "USB",
        "PFE", "AMGN", "GILD", "BIIB", "REGN", "VRTX", "MRNA",
        "COP", "SLB", "EOG", "PSX", "VLO", "MPC", "OXY", "HAL",
        "F", "GM", "RIVN", "NIO",
        "PYPL", "SQ", "COIN", "HOOD", "SOFI", "AFRM",
        "SHOP", "MELI", "SE", "BABA", "JD", "PDD",
        "ROKU", "SPOT", "NFLX", "WBD", "PARA",
        "ZM", "DOCU", "OKTA", "TWLO", "TEAM",
    ]


def scan_for_bubbles(
    settings: Settings,
    universe: str = "sp500",
    min_bubble_score: float = 50,
    min_crash_score: float = -50,
    lookback_days: int = 252 * 3,
    include_news: bool = True,
    include_earnings: bool = True,
    top_n: int = 20,
) -> BubbleScanResult:
    """
    Scan a universe of stocks for bubble/crash candidates.
    
    Args:
        settings: App settings
        universe: "sp500", "etfs", "mega", "tech", or comma-separated tickers
        min_bubble_score: Minimum bubble score to include (0-100)
        min_crash_score: Minimum crash score to include (negative, e.g., -50)
        lookback_days: Days of history for z-score calculation
        include_news: Fetch recent news for context
        include_earnings: Check for recent earnings
        top_n: Return top N bubbles and crashes
    
    Returns:
        BubbleScanResult with bubble and crash candidates
    """
    from ai_options_trader.data.market import fetch_equity_daily_closes
    
    tickers = get_universe_tickers(universe, settings)
    
    # Fetch price data - batch in groups to handle API limits
    start_date = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    
    prices = None
    batch_size = 50
    
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i + batch_size]
        try:
            batch_prices = fetch_equity_daily_closes(
                settings=settings,
                symbols=batch,
                start=start_date,
                refresh=True,
            )
            if batch_prices is not None and not batch_prices.empty:
                if prices is None:
                    prices = batch_prices
                else:
                    # Merge batch with existing prices
                    prices = prices.join(batch_prices, how="outer", rsuffix="_dup")
                    # Remove duplicate columns
                    prices = prices.loc[:, ~prices.columns.str.endswith("_dup")]
        except Exception:
            # Skip failed batches
            continue
    
    if prices is None or prices.empty:
        raise RuntimeError("No price data returned")
    
    prices = prices.sort_index().ffill()
    
    candidates = []
    
    for ticker in tickers:
        if ticker not in prices.columns:
            continue
        
        px = pd.to_numeric(prices[ticker], errors="coerce").dropna()
        
        if len(px) < 60:  # Need at least 60 days
            continue
        
        try:
            candidate = _analyze_ticker(px, ticker, lookback_days)
            if candidate:
                candidates.append(candidate)
        except Exception:
            continue
    
    # Separate bubbles and crashes
    bubbles = [c for c in candidates if c.bubble_score >= min_bubble_score]
    crashes = [c for c in candidates if c.bubble_score <= min_crash_score]
    
    # Sort by score (most extreme first)
    bubbles = sorted(bubbles, key=lambda x: x.bubble_score, reverse=True)[:top_n]
    crashes = sorted(crashes, key=lambda x: x.bubble_score)[:top_n]
    
    # Enrich with news/earnings if requested
    if include_earnings:
        _enrich_with_earnings(settings, bubbles + crashes)
    
    if include_news:
        _enrich_with_news(settings, bubbles + crashes)
    
    # Generate trade recommendations
    for c in bubbles + crashes:
        _generate_recommendation(c)
    
    # Build result
    result = BubbleScanResult(
        scan_date=date.today(),
        universe=universe,
        total_scanned=len(tickers),
        bubbles=bubbles,
        crashes=crashes,
        bubble_count=len(bubbles),
        crash_count=len(crashes),
        avg_bubble_score=np.mean([b.bubble_score for b in bubbles]) if bubbles else 0,
        avg_crash_score=np.mean([c.bubble_score for c in crashes]) if crashes else 0,
    )
    
    return result


def _analyze_ticker(px: pd.Series, ticker: str, lookback_days: int) -> Optional[BubbleCandidate]:
    """Analyze a single ticker for bubble/crash characteristics."""
    
    current_price = px.iloc[-1]
    
    # Returns
    ret_5d = (px.iloc[-1] / px.iloc[-6] - 1) * 100 if len(px) > 5 else 0
    ret_20d = (px.iloc[-1] / px.iloc[-21] - 1) * 100 if len(px) > 20 else 0
    ret_60d = (px.iloc[-1] / px.iloc[-61] - 1) * 100 if len(px) > 60 else 0
    
    # Moving averages
    ma_50 = px.rolling(50, min_periods=30).mean().iloc[-1]
    ma_200 = px.rolling(200, min_periods=100).mean().iloc[-1] if len(px) > 100 else px.rolling(len(px), min_periods=30).mean().iloc[-1]
    
    pct_from_50ma = (current_price / ma_50 - 1) * 100 if ma_50 else 0
    pct_from_200ma = (current_price / ma_200 - 1) * 100 if ma_200 else 0
    
    # Z-scores
    ret_20d_series = px.pct_change(20) * 100
    ret_60d_series = px.pct_change(60) * 100
    
    window = min(len(px) - 1, lookback_days)
    
    zscore_20d = _compute_zscore(ret_20d_series, window)
    zscore_60d = _compute_zscore(ret_60d_series, window)
    
    # RSI
    rsi = _compute_rsi(px, 14)
    
    # Volatility
    daily_ret = px.pct_change()
    vol_20d = daily_ret.rolling(20, min_periods=10).std().iloc[-1] * np.sqrt(252) * 100
    
    # Bubble score calculation
    bubble_score = _compute_bubble_score(
        ret_20d=ret_20d,
        ret_60d=ret_60d,
        zscore_20d=zscore_20d,
        zscore_60d=zscore_60d,
        pct_from_200ma=pct_from_200ma,
        rsi=rsi,
        vol_20d=vol_20d,
    )
    
    # Skip if not extreme enough (between -30 and 30)
    if -30 < bubble_score < 30:
        return None
    
    # Reversion score
    reversion_score, reversion_direction = _compute_reversion_score(
        bubble_score=bubble_score,
        zscore_20d=zscore_20d,
        rsi=rsi,
        pct_from_200ma=pct_from_200ma,
    )
    
    move_type = "bubble" if bubble_score > 0 else "crash"
    
    return BubbleCandidate(
        ticker=ticker,
        price=round(current_price, 2),
        move_type=move_type,
        ret_5d_pct=round(ret_5d, 1),
        ret_20d_pct=round(ret_20d, 1),
        ret_60d_pct=round(ret_60d, 1),
        zscore_20d=round(zscore_20d, 2),
        zscore_60d=round(zscore_60d, 2),
        pct_from_50ma=round(pct_from_50ma, 1),
        pct_from_200ma=round(pct_from_200ma, 1),
        rsi_14=round(rsi, 1),
        bubble_score=round(bubble_score, 1),
        extension_pct=round(pct_from_200ma, 1),
        reversion_score=round(reversion_score, 1),
        reversion_direction=reversion_direction,
    )


def _compute_zscore(series: pd.Series, window: int) -> float:
    """Compute z-score of latest value vs rolling history."""
    if series.isna().all() or len(series) < window:
        return 0
    
    mean = series.rolling(window, min_periods=60).mean().iloc[-1]
    std = series.rolling(window, min_periods=60).std().iloc[-1]
    
    if pd.isna(mean) or pd.isna(std) or std == 0:
        return 0
    
    return (series.iloc[-1] - mean) / std


def _compute_rsi(prices: pd.Series, period: int = 14) -> float:
    """Compute RSI."""
    delta = prices.diff()
    gain = delta.where(delta > 0, 0).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    
    return rsi.iloc[-1] if not pd.isna(rsi.iloc[-1]) else 50


def _compute_bubble_score(
    ret_20d: float,
    ret_60d: float,
    zscore_20d: float,
    zscore_60d: float,
    pct_from_200ma: float,
    rsi: float,
    vol_20d: float,
) -> float:
    """
    Compute bubble score from -100 (crash) to +100 (bubble).
    """
    score = 0
    
    # Return z-score contribution (+/- 30)
    score += np.clip(zscore_20d, -3, 3) * 10
    
    # 60d z-score contribution (+/- 20)
    score += np.clip(zscore_60d, -2, 2) * 10
    
    # Distance from 200MA (+/- 25)
    score += np.clip(pct_from_200ma / 4, -25, 25)
    
    # RSI contribution (+/- 15)
    rsi_score = (rsi - 50) / 50 * 15
    score += rsi_score
    
    # Acceleration (5d momentum) (+/- 10)
    # If 20d is big but 5d is even more proportionally, accelerating
    # This is implicit in the z-scores
    
    return np.clip(score, -100, 100)


def _compute_reversion_score(
    bubble_score: float,
    zscore_20d: float,
    rsi: float,
    pct_from_200ma: float,
) -> tuple[float, Literal["down", "up", "neutral"]]:
    """
    Compute probability of mean reversion.
    
    Returns (score 0-100, direction)
    """
    score = 0
    
    # More extreme bubble = higher reversion probability
    extremity = abs(bubble_score)
    score += extremity * 0.4  # Up to 40 points
    
    # Extreme RSI
    if rsi > 80 or rsi < 20:
        score += 20
    elif rsi > 70 or rsi < 30:
        score += 10
    
    # Extreme z-score
    if abs(zscore_20d) > 3:
        score += 20
    elif abs(zscore_20d) > 2:
        score += 10
    
    # Far from 200MA
    if abs(pct_from_200ma) > 50:
        score += 20
    elif abs(pct_from_200ma) > 30:
        score += 10
    
    direction = "down" if bubble_score > 0 else "up" if bubble_score < 0 else "neutral"
    
    return min(100, score), direction


def _enrich_with_earnings(settings: Settings, candidates: list[BubbleCandidate]) -> None:
    """Add earnings context to candidates."""
    try:
        from ai_options_trader.altdata.earnings import fetch_earnings_surprises
        
        for c in candidates:
            try:
                surprises = fetch_earnings_surprises(settings=settings, ticker=c.ticker, limit=1)
                if surprises:
                    latest = surprises[0]
                    # Check if earnings were in last 30 days
                    try:
                        earn_date = datetime.strptime(latest.date, "%Y-%m-%d").date()
                        if (date.today() - earn_date).days <= 30:
                            c.has_recent_earnings = True
                            c.earnings_surprise_pct = latest.eps_surprise_pct
                    except Exception:
                        pass
            except Exception:
                continue
    except ImportError:
        pass


def _enrich_with_news(settings: Settings, candidates: list[BubbleCandidate]) -> None:
    """Add news context to candidates."""
    try:
        from ai_options_trader.llm.outlooks.ticker_news import fetch_fmp_stock_news
        
        for c in candidates[:10]:  # Limit to top 10 for API rate limits
            try:
                from_date = (date.today() - timedelta(days=7)).isoformat()
                news = fetch_fmp_stock_news(
                    settings=settings,
                    tickers=[c.ticker],
                    from_date=from_date,
                    to_date=date.today().isoformat(),
                    max_pages=1,
                )
                if news:
                    c.has_recent_news = True
                    # Simple sentiment from title keywords
                    titles = " ".join([n.get("title", "") for n in news[:5]]).lower()
                    if any(w in titles for w in ["surge", "soar", "jump", "rally", "beat", "record"]):
                        c.news_sentiment = "bullish"
                    elif any(w in titles for w in ["drop", "fall", "plunge", "miss", "cut", "warning"]):
                        c.news_sentiment = "bearish"
                    else:
                        c.news_sentiment = "neutral"
            except Exception:
                continue
    except ImportError:
        pass


def _generate_recommendation(c: BubbleCandidate) -> None:
    """Generate trade recommendation for a candidate."""
    
    confidence = c.reversion_score
    
    # Adjust confidence based on context
    if c.has_recent_earnings:
        # Earnings-driven moves may persist
        confidence -= 15
        if c.earnings_surprise_pct:
            # Big beat/miss explains the move
            if abs(c.earnings_surprise_pct) > 10:
                confidence -= 10
    
    if c.has_recent_news and c.news_sentiment:
        # News explains the move
        if (c.move_type == "bubble" and c.news_sentiment == "bullish") or \
           (c.move_type == "crash" and c.news_sentiment == "bearish"):
            confidence -= 10
    
    confidence = max(0, min(100, confidence))
    c.confidence = round(confidence, 1)
    
    # Generate recommendation
    if c.move_type == "bubble":
        if confidence >= 70:
            c.trade_recommendation = "STRONG PUT CANDIDATE - High reversion probability"
        elif confidence >= 50:
            c.trade_recommendation = "MODERATE PUT CANDIDATE - Wait for confirmation"
        else:
            c.trade_recommendation = "WATCH - Move may be justified"
    else:  # crash
        if confidence >= 70:
            c.trade_recommendation = "STRONG CALL CANDIDATE - Oversold bounce likely"
        elif confidence >= 50:
            c.trade_recommendation = "MODERATE CALL CANDIDATE - Wait for stabilization"
        else:
            c.trade_recommendation = "WATCH - Downtrend may continue"
