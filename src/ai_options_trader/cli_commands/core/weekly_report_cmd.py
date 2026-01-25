from __future__ import annotations

from datetime import datetime, timezone, timedelta
import os
import pandas as pd
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.columns import Columns
from rich.text import Text
from rich import box

from ai_options_trader.config import load_settings
from ai_options_trader.data.alpaca import fetch_option_chain, to_candidates
from ai_options_trader.data.alpaca import make_clients
from ai_options_trader.data.market import fetch_equity_daily_closes
from ai_options_trader.utils.occ import parse_occ_option_symbol
from ai_options_trader.utils.settings import safe_load_settings


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _generate_report(console: Console, period: str = "week") -> None:
    """Generate report for use by core commands."""
    # For now, delegate to the main weekly report
    # In future, can differentiate by period
    pass  # The actual report is in the register function


def _pretty_ts(ts: str | None) -> str:
    if not ts:
        return "DATA NOT PROVIDED"
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return dt.strftime("%b %d, %Y %H:%M UTC")
    except Exception:
        return str(ts)


def _fmt_value(v) -> str:
    if v is None or str(v).strip() == "":
        return "DATA NOT PROVIDED"
    return str(v)


def _fmt_pct(v: float | None) -> str:
    if v is None:
        return "DATA NOT PROVIDED"
    return f"{v * 100.0:.2f}%"


def _parse_occ_auto(symbol: str):
    try:
        import re

        sym = (symbol or "").upper()
        m = re.match(r"^([A-Z]+)(\d{6}[CP]\d{8})$", sym)
        if not m:
            return None
        underlying = m.group(1)
        exp, opt_type, strike = parse_occ_option_symbol(sym, underlying)
        return {"underlying": underlying, "expiry": exp, "opt_type": opt_type, "strike": strike}
    except Exception:
        return None


def _get_latest_nav() -> dict | None:
    try:
        from ai_options_trader.nav.store import read_nav_sheet
        from ai_options_trader.nav.investors import read_investor_flows

        rows = read_nav_sheet()
        if not rows:
            return None
        last = rows[-1]
        flows = read_investor_flows()
        # Original capital = sum of positive investor contributions.
        original_capital = sum(float(f.amount) for f in flows if float(f.amount) > 0)
        return {
            "ts": last.ts,
            "original_capital": original_capital,
            "equity": last.equity,
            "cash": last.cash,
            "buying_power": last.buying_power,
            "pnl_since_prev": last.pnl_since_prev,
            "twr_since_prev": last.twr_since_prev,
            "twr_cum": last.twr_cum,
        }
    except Exception:
        return None


def _weekly_ust10y_change() -> tuple[str, str]:
    """
    Best-effort weekly change in 10Y yield (DGS10, FRED).
    Returns (level, weekly_change) as strings, or DATA NOT PROVIDED.
    """
    settings = safe_load_settings()
    if not settings or not settings.FRED_API_KEY:
        return "DATA NOT PROVIDED", "DATA NOT PROVIDED"
    try:
        from ai_options_trader.data.fred import FredClient

        fred = FredClient(api_key=settings.FRED_API_KEY)
        df = fred.fetch_series(series_id="DGS10", start_date="2018-01-01", refresh=False)
        if df is None or df.empty:
            return "DATA NOT PROVIDED", "DATA NOT PROVIDED"
        df = df.sort_values("date")
        df = df[df["value"].notna()]
        if df.shape[0] < 2:
            return "DATA NOT PROVIDED", "DATA NOT PROVIDED"
        last = df.iloc[-1]
        # 5 business days back (best-effort)
        prev = df.iloc[-6] if df.shape[0] >= 6 else df.iloc[0]
        level = float(last["value"])
        prev_val = float(prev["value"])
        return f"{level:.2f}%", f"{((level - prev_val) * 100.0):+.0f} bps"
    except Exception:
        return "DATA NOT PROVIDED", "DATA NOT PROVIDED"


def _ust10y_live_yield() -> tuple[str, str, str]:
    """
    Best-effort intraday 10Y yield using FMP ^TNX quote as a proxy.
    Returns (yield, asof, note).
    """
    settings = safe_load_settings()
    if not settings or not settings.FMP_API_KEY:
        return "DATA NOT PROVIDED", "DATA NOT PROVIDED", "FMP_API_KEY missing"
    try:
        import requests

        url = "https://financialmodelingprep.com/api/v3/quote/%5ETNX"
        resp = requests.get(url, params={"apikey": settings.FMP_API_KEY}, timeout=20)
        resp.raise_for_status()
        js = resp.json()
        if not isinstance(js, list) or not js:
            return "DATA NOT PROVIDED", "DATA NOT PROVIDED", "empty response"
        row = js[0] if isinstance(js[0], dict) else {}
        price = row.get("price")
        ts = row.get("timestamp")
        if price is None:
            return "DATA NOT PROVIDED", "DATA NOT PROVIDED", "missing price"
        px = float(price)
        # ^TNX is commonly 10x the yield (e.g., 418 -> 4.18%)
        yield_pct = px / 100.0 if px > 20 else px
        asof = "DATA NOT PROVIDED"
        if ts:
            try:
                asof = datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%b %d, %Y %H:%M UTC")
            except Exception:
                asof = "DATA NOT PROVIDED"
        return f"{yield_pct:.2f}%", asof, ""
    except Exception as e:
        return "DATA NOT PROVIDED", "DATA NOT PROVIDED", f"FMP error: {e}"


def _fred_latest_and_change(series_id: str, lookback: int = 5) -> tuple[str, str, str, str]:
    """
    Returns (latest, change, asof, note) for a FRED series. Change is vs ~1 week.
    """
    settings = safe_load_settings()
    if not settings or not settings.FRED_API_KEY:
        return "DATA NOT PROVIDED", "DATA NOT PROVIDED", "DATA NOT PROVIDED", "FRED_API_KEY missing"
    try:
        from ai_options_trader.data.fred import FredClient

        fred = FredClient(api_key=settings.FRED_API_KEY)
        df = fred.fetch_series(series_id=series_id, start_date="2018-01-01", refresh=False)
        if df is None or df.empty:
            return "DATA NOT PROVIDED", "DATA NOT PROVIDED", "DATA NOT PROVIDED", "series empty"
        df = df.sort_values("date")
        df = df[df["value"].notna()]
        if df.shape[0] < 2:
            return "DATA NOT PROVIDED", "DATA NOT PROVIDED", "DATA NOT PROVIDED", "insufficient history"
        series = pd.Series(df["value"].values, index=pd.to_datetime(df["date"]))
        last = float(series.iloc[-1])
        prev = float(series.iloc[-(lookback + 1)]) if series.shape[0] > lookback else float(series.iloc[0])
        chg = last - prev
        asof = str(series.index[-1].date())
        return f"{last:.2f}", f"{chg:+.2f}", asof, ""
    except Exception as e:
        return "DATA NOT PROVIDED", "DATA NOT PROVIDED", "DATA NOT PROVIDED", f"FRED error: {e}"


def _fred_latest_and_change_days(
    series_id: str, days: int
) -> tuple[str, str, str, str, float | None, float | None]:
    """
    Returns (latest, change, asof, note, change_num) for a FRED series using day-based lookback.
    """
    settings = safe_load_settings()
    if not settings or not settings.FRED_API_KEY:
        return "DATA NOT PROVIDED", "DATA NOT PROVIDED", "DATA NOT PROVIDED", "FRED_API_KEY missing", None, None
    try:
        from ai_options_trader.data.fred import FredClient

        fred = FredClient(api_key=settings.FRED_API_KEY)
        df = fred.fetch_series(series_id=series_id, start_date="2010-01-01", refresh=False)
        if df is None or df.empty:
            return "DATA NOT PROVIDED", "DATA NOT PROVIDED", "DATA NOT PROVIDED", "series empty", None, None
        df = df.sort_values("date")
        df = df[df["value"].notna()]
        if df.shape[0] < 2:
            return "DATA NOT PROVIDED", "DATA NOT PROVIDED", "DATA NOT PROVIDED", "insufficient history", None, None
        series = pd.Series(df["value"].values, index=pd.to_datetime(df["date"]))
        asof_dt = series.index[-1]
        last = float(series.iloc[-1])
        target_dt = asof_dt - pd.Timedelta(days=int(days))
        prior = series.loc[:target_dt]
        if prior.empty:
            prior_val = float(series.iloc[0])
        else:
            prior_val = float(prior.iloc[-1])
        chg = last - prior_val
        asof = str(asof_dt.date())
        return f"{last:.2f}", f"{chg:+.2f}", asof, "", float(chg), float(last)
    except Exception as e:
        return "DATA NOT PROVIDED", "DATA NOT PROVIDED", "DATA NOT PROVIDED", f"FRED error: {e}", None, None


def _fred_yoy_and_change_days(
    series_id: str, days: int
) -> tuple[str, str, str, str, float | None, float | None]:
    """
    Returns YoY (%) for a level series (e.g., CPIAUCSL), plus change in YoY vs lookback days.
    """
    settings = safe_load_settings()
    if not settings or not settings.FRED_API_KEY:
        return "DATA NOT PROVIDED", "DATA NOT PROVIDED", "DATA NOT PROVIDED", "FRED_API_KEY missing", None, None
    try:
        from ai_options_trader.data.fred import FredClient

        fred = FredClient(api_key=settings.FRED_API_KEY)
        df = fred.fetch_series(series_id=series_id, start_date="2010-01-01", refresh=False)
        if df is None or df.empty:
            return "DATA NOT PROVIDED", "DATA NOT PROVIDED", "DATA NOT PROVIDED", "series empty", None, None
        df = df.sort_values("date")
        df = df[df["value"].notna()]
        if df.shape[0] < 24:
            return "DATA NOT PROVIDED", "DATA NOT PROVIDED", "DATA NOT PROVIDED", "insufficient history", None, None
        series = pd.Series(df["value"].values, index=pd.to_datetime(df["date"]))
        asof_dt = series.index[-1]
        last = float(series.iloc[-1])
        # YoY from 12 months prior
        prior_12m = series.loc[: (asof_dt - pd.Timedelta(days=365))]
        if prior_12m.empty:
            return "DATA NOT PROVIDED", "DATA NOT PROVIDED", "DATA NOT PROVIDED", "insufficient history", None, None
        base = float(prior_12m.iloc[-1])
        yoy = (last / base - 1.0) * 100.0

        target_dt = asof_dt - pd.Timedelta(days=int(days))
        prior_win = series.loc[:target_dt]
        if prior_win.empty:
            return "DATA NOT PROVIDED", "DATA NOT PROVIDED", "DATA NOT PROVIDED", "insufficient history", None, None
        prior_last = float(prior_win.iloc[-1])
        prior_12m_win = series.loc[: (target_dt - pd.Timedelta(days=365))]
        if prior_12m_win.empty:
            return "DATA NOT PROVIDED", "DATA NOT PROVIDED", "DATA NOT PROVIDED", "insufficient history", None, None
        prior_base = float(prior_12m_win.iloc[-1])
        yoy_prior = (prior_last / prior_base - 1.0) * 100.0
        chg = yoy - yoy_prior
        asof = str(asof_dt.date())
        return f"{yoy:.2f}", f"{chg:+.2f}", asof, "", float(chg), float(yoy)
    except Exception as e:
        return "DATA NOT PROVIDED", "DATA NOT PROVIDED", "DATA NOT PROVIDED", f"FRED error: {e}", None, None


def _fred_latest(series_id: str) -> tuple[str, str, str]:
    """
    Returns (latest, asof, note) for a FRED series.
    """
    settings = safe_load_settings()
    if not settings or not settings.FRED_API_KEY:
        return "DATA NOT PROVIDED", "DATA NOT PROVIDED", "FRED_API_KEY missing"
    try:
        from ai_options_trader.data.fred import FredClient

        fred = FredClient(api_key=settings.FRED_API_KEY)
        df = fred.fetch_series(series_id=series_id, start_date="2018-01-01", refresh=False)
        if df is None or df.empty:
            return "DATA NOT PROVIDED", "DATA NOT PROVIDED", "series empty"
        df = df.sort_values("date")
        df = df[df["value"].notna()]
        if df.shape[0] < 1:
            return "DATA NOT PROVIDED", "DATA NOT PROVIDED", "insufficient history"
        last = float(df["value"].iloc[-1])
        asof = str(pd.to_datetime(df["date"].iloc[-1]).date())
        return f"{last:.2f}", asof, ""
    except Exception as e:
        return "DATA NOT PROVIDED", "DATA NOT PROVIDED", f"FRED error: {e}"


def _ust10y_change_1m_3m() -> tuple[str, str, str, str]:
    """
    Returns (asof, change_1m, change_3m, note).
    """
    settings = safe_load_settings()
    if not settings or not settings.FRED_API_KEY:
        return "DATA NOT PROVIDED", "DATA NOT PROVIDED", "DATA NOT PROVIDED", "FRED_API_KEY missing"
    try:
        from ai_options_trader.data.fred import FredClient

        fred = FredClient(api_key=settings.FRED_API_KEY)
        df = fred.fetch_series(series_id="DGS10", start_date="2018-01-01", refresh=False)
        if df is None or df.empty:
            return "DATA NOT PROVIDED", "DATA NOT PROVIDED", "DATA NOT PROVIDED", "series empty"
        df = df.sort_values("date")
        df = df[df["value"].notna()]
        if df.shape[0] < 2:
            return "DATA NOT PROVIDED", "DATA NOT PROVIDED", "DATA NOT PROVIDED", "insufficient history"
        series = pd.Series(df["value"].values, index=pd.to_datetime(df["date"]))
        d_1m = 21
        d_3m = 63
        last = float(series.iloc[-1])
        prev_1m = float(series.iloc[-(d_1m + 1)]) if series.shape[0] > d_1m else float(series.iloc[0])
        prev_3m = float(series.iloc[-(d_3m + 1)]) if series.shape[0] > d_3m else float(series.iloc[0])
        chg_1m = last - prev_1m
        chg_3m = last - prev_3m
        asof = str(series.index[-1].date())
        return asof, f"{chg_1m:+.2f}pp", f"{chg_3m:+.2f}pp", ""
    except Exception as e:
        return "DATA NOT PROVIDED", "DATA NOT PROVIDED", "DATA NOT PROVIDED", f"FRED error: {e}"


def _hy_oas_metrics() -> tuple[str, str, str, str, float | None]:
    """
    Returns (asof, latest_bps, change_bps) for HY OAS, or DATA NOT PROVIDED.
    """
    settings = safe_load_settings()
    if not settings:
        return "DATA NOT PROVIDED", "DATA NOT PROVIDED", "DATA NOT PROVIDED", "settings unavailable", None
    if not settings.FRED_API_KEY:
        return "DATA NOT PROVIDED", "DATA NOT PROVIDED", "DATA NOT PROVIDED", "FRED_API_KEY missing", None
    try:
        from ai_options_trader.data.fred import FredClient

        fred = FredClient(api_key=settings.FRED_API_KEY)
        df = fred.fetch_series(series_id="BAMLH0A0HYM2", start_date="2018-01-01", refresh=False)
        if df is None or df.empty:
            return "DATA NOT PROVIDED", "DATA NOT PROVIDED", "DATA NOT PROVIDED", "series empty", None
        df = df.sort_values("date")
        df = df[df["value"].notna()]
        if df.shape[0] < 2:
            return "DATA NOT PROVIDED", "DATA NOT PROVIDED", "DATA NOT PROVIDED", "insufficient history", None
        series = pd.Series(df["value"].values, index=pd.to_datetime(df["date"]))
        # 3-month proxy ~ 63 trading days
        lookback = 63
        last = float(series.iloc[-1])
        prev = float(series.iloc[-(lookback + 1)]) if series.shape[0] > lookback else float(series.iloc[0])
        # FRED series is percent; convert to bps.
        last_bps = last * 100.0
        chg_bps = (last - prev) * 100.0
        asof = str(series.index[-1].date())
        return asof, f"{last_bps:.0f} bps", f"{chg_bps:+.0f} bps", "", float(chg_bps)
    except Exception as e:
        return "DATA NOT PROVIDED", "DATA NOT PROVIDED", "DATA NOT PROVIDED", f"FRED error: {e}", None


def _rel_return_vs(symbol: str, benchmark: str, lookback: int = 63) -> tuple[str, str, str, float | None]:
    """
    Returns (asof, rel_return_pct) for symbol vs benchmark, or DATA NOT PROVIDED.
    """
    settings = safe_load_settings()
    if not settings:
        return "DATA NOT PROVIDED", "DATA NOT PROVIDED", "settings unavailable", None
    try:
        px = fetch_equity_daily_closes(settings=settings, symbols=[symbol, benchmark], start="2018-01-01")
    except Exception as e:
        return "DATA NOT PROVIDED", "DATA NOT PROVIDED", f"price data error: {e}", None
    if px is None or px.empty:
        return "DATA NOT PROVIDED", "DATA NOT PROVIDED", "price data empty", None
    df = px[[symbol, benchmark]].dropna()
    if df.shape[0] <= lookback:
        return "DATA NOT PROVIDED", "DATA NOT PROVIDED", "insufficient history", None
    win = df.iloc[-(lookback + 1) :]
    ret_sym = (float(win[symbol].iloc[-1]) / float(win[symbol].iloc[0]) - 1.0) * 100.0
    ret_b = (float(win[benchmark].iloc[-1]) / float(win[benchmark].iloc[0]) - 1.0) * 100.0
    rel = ret_sym - ret_b
    asof = str(win.index[-1].date())
    return asof, f"{rel:+.2f}%", "", float(rel)


def _ratio_change(numerator: str, denominator: str, lookback: int = 63) -> tuple[str, str, str, str, float | None]:
    """
    Returns (asof, latest_ratio, change_pct) for numerator/denominator ratio.
    """
    settings = safe_load_settings()
    if not settings:
        return "DATA NOT PROVIDED", "DATA NOT PROVIDED", "DATA NOT PROVIDED", "settings unavailable", None
    try:
        px = fetch_equity_daily_closes(settings=settings, symbols=[numerator, denominator], start="2018-01-01")
    except Exception as e:
        return "DATA NOT PROVIDED", "DATA NOT PROVIDED", "DATA NOT PROVIDED", f"price data error: {e}", None
    if px is None or px.empty:
        return "DATA NOT PROVIDED", "DATA NOT PROVIDED", "DATA NOT PROVIDED", "price data empty", None
    df = px[[numerator, denominator]].dropna()
    if df.shape[0] <= lookback:
        return "DATA NOT PROVIDED", "DATA NOT PROVIDED", "DATA NOT PROVIDED", "insufficient history", None
    ratio = df[numerator] / df[denominator]
    win = ratio.iloc[-(lookback + 1) :]
    latest = float(win.iloc[-1])
    chg = (float(win.iloc[-1]) / float(win.iloc[0]) - 1.0) * 100.0
    asof = str(win.index[-1].date())
    return asof, f"{latest:.3f}", f"{chg:+.2f}%", "", float(chg)


THEMES = [
    "Base intent: tail-risk and drawdown protection with small premium.",
    "What you need: shift toward risk-off conditions (credit widening and/or AI de-rating).",
    "Rates leg: duration convexity benefits if rates are stable to lower.",
]


def _fetch_upcoming_events(days: int = 7, max_items: int = 15) -> list[dict]:
    """Fetch upcoming economic events from FMP calendar."""
    settings = safe_load_settings()
    if not settings or not settings.FMP_API_KEY:
        return []
    
    import requests
    
    try:
        url = "https://financialmodelingprep.com/api/v3/economic_calendar"
        resp = requests.get(url, params={"apikey": settings.FMP_API_KEY}, timeout=15)
        resp.raise_for_status()
        events = resp.json()
        
        if not isinstance(events, list):
            return []
        
        now = datetime.now(timezone.utc)
        cutoff = now + timedelta(days=days)
        
        # High-impact keywords for portfolio
        high_impact = ["FOMC", "CPI", "PCE", "GDP", "NFP", "Jobless", "Fed", "Auction", "Employment", "Payroll"]
        
        relevant = []
        for e in events:
            if not isinstance(e, dict):
                continue
            
            event_date_str = e.get("date", "")
            try:
                event_date = datetime.fromisoformat(event_date_str.replace(" ", "T").replace("Z", "+00:00"))
                if event_date.tzinfo is None:
                    event_date = event_date.replace(tzinfo=timezone.utc)
            except:
                continue
            
            if event_date < now or event_date > cutoff:
                continue
            
            country = e.get("country", "").upper()
            if country and country != "US":
                continue
            
            event_name = e.get("event", "")
            is_high_impact = any(kw.lower() in event_name.lower() for kw in high_impact)
            
            relevant.append({
                "date": event_date,
                "event": event_name,
                "estimate": e.get("estimate"),
                "previous": e.get("previous"),
                "high_impact": is_high_impact,
            })
        
        # Sort by date, prioritize high impact
        relevant.sort(key=lambda x: (x["date"], not x["high_impact"]))
        return relevant[:max_items]
        
    except Exception:
        return []


def _get_regime_snapshot() -> dict:
    """Get current regime readings from pillars."""
    regimes = {}
    settings = safe_load_settings()
    if not settings:
        return regimes
    
    try:
        from ai_options_trader.regimes.pillars import VolatilityPillar
        pillar = VolatilityPillar()
        pillar.compute(settings)
        vix = next((m.value for m in pillar.metrics if m.name == "VIX"), None)
        regimes["volatility"] = {
            "regime": pillar.regime,
            "vix": vix,
            "term_structure": pillar.term_structure_status(),
        }
    except:
        pass
    
    try:
        from ai_options_trader.rates.signals import build_rates_state
        from ai_options_trader.rates.regime import classify_rates_regime
        state = build_rates_state(settings=settings)
        regime = classify_rates_regime(state.inputs)
        regimes["rates"] = {
            "regime": regime.label or regime.name,
            "ust_10y": state.inputs.ust_10y,
            "curve_2s10s": state.inputs.curve_2s10s,
        }
    except:
        pass
    
    try:
        from ai_options_trader.funding.signals import build_funding_state
        from ai_options_trader.funding.regime import classify_funding_regime
        from ai_options_trader.funding.models import FundingInputs
        state = build_funding_state(settings=settings)
        fi = state.inputs
        regime = classify_funding_regime(FundingInputs(
            spread_corridor_bps=fi.spread_corridor_bps,
            spike_5d_bps=fi.spike_5d_bps,
            persistence_20d=fi.persistence_20d,
            vol_20d_bps=fi.vol_20d_bps,
            tight_threshold_bps=fi.tight_threshold_bps,
            stress_threshold_bps=fi.stress_threshold_bps,
            persistence_tight=fi.persistence_tight,
            persistence_stress=fi.persistence_stress,
            vol_tight_bps=fi.vol_tight_bps,
            vol_stress_bps=fi.vol_stress_bps,
        ))
        regimes["funding"] = {
            "regime": regime.label or regime.name,
            "sofr": fi.sofr,
            "spread_bps": fi.spread_corridor_bps,
        }
    except:
        pass
    
    return regimes


def _format_event_time(dt: datetime) -> str:
    """Format event datetime for display."""
    now = datetime.now(timezone.utc)
    if dt.date() == now.date():
        return f"TODAY {dt.strftime('%H:%M')}"
    elif dt.date() == (now + timedelta(days=1)).date():
        return f"Tomorrow {dt.strftime('%H:%M')}"
    else:
        return dt.strftime("%a %b %d %H:%M")


def _intent_for_symbol(symbol: str) -> str:
    sym = (symbol or "").upper()
    if sym.startswith("HYG"):
        return "Credit hedge (HY spreads)"
    if sym.startswith("NVDA"):
        return "AI downside hedge"
    if sym.startswith("TAN"):
        return "Solar downside hedge"
    if sym.startswith("TLT"):
        return "Duration convexity hedge"
    if sym.startswith("VIX") or sym == "VIXM":
        return "Volatility hedge"
    if sym.startswith("GLD") or sym.startswith("GLDM"):
        return "Defensive diversifier (gold)"
    if sym.startswith("BTC"):
        return "Diversifier (crypto)"
    return "Portfolio hedge / diversifier"


def _safe_float(x) -> float | None:
    try:
        if x is None:
            return None
        return float(x)
    except Exception:
        return None


def _generate_shareable_report(now: datetime) -> None:
    """Generate a clean, investor-grade shareable report."""
    lines = []
    
    # Header
    lines.append(f"WEEKLY UPDATE | {now.strftime('%b %d, %Y')}")
    lines.append("=" * 40)
    lines.append("")
    
    # NAV
    nav = _get_latest_nav()
    if nav:
        eq = float(nav.get("equity") or 0.0)
        orig = float(nav.get("original_capital") or 0.0)
        pnl = eq - orig
        weekly_ret = _safe_float(nav.get("twr_since_prev"))
        since_ret = _safe_float(nav.get("twr_cum"))
        
        lines.append("PERFORMANCE")
        lines.append(f"  NAV: ${eq:,.0f} (P&L: ${pnl:+,.0f})")
        if weekly_ret is not None:
            lines.append(f"  Week: {weekly_ret*100:+.2f}%")
        if since_ret is not None:
            lines.append(f"  Since inception: {since_ret*100:+.1f}%")
        lines.append("")
    
    # Regimes
    regimes = _get_regime_snapshot()
    if regimes:
        lines.append("MARKET ENVIRONMENT")
        if "volatility" in regimes:
            vol = regimes["volatility"]
            vix = vol.get("vix")
            vix_str = f" at {vix:.0f}" if vix else ""
            lines.append(f"  Volatility: {vol.get('regime', 'N/A')}{vix_str}")
        if "rates" in regimes:
            r = regimes["rates"]
            y10 = r.get("ust_10y")
            y10_str = f" (10Y: {y10:.2f}%)" if y10 else ""
            lines.append(f"  Rates: {r.get('regime', 'N/A')}{y10_str}")
        lines.append("")
    
    # Week ahead events
    events = _fetch_upcoming_events(days=7, max_items=8)
    if events:
        high_impact = [e for e in events if e["high_impact"]][:5]
        if high_impact:
            lines.append("WEEK AHEAD")
            for e in high_impact:
                day = e["date"].strftime("%a %d")
                lines.append(f"  {day}: {e['event'][:45]}")
            lines.append("")
    
    # Key triggers
    hy_asof, hy_level, hy_chg, hy_note, hy_chg_num = _hy_oas_metrics()
    nvda_asof, nvda_rel, nvda_note, nvda_rel_num = _rel_return_vs("NVDA", "SPY")
    ratio_asof, ratio_level, ratio_chg, ratio_note, ratio_chg_num = _ratio_change("SLV", "TAN")
    
    lines.append("POSITIONING & TRIGGERS")
    lines.append("  Strategy: Tail-risk hedges via puts on credit (HYG),")
    lines.append("  AI (NVDA), and solar (TAN), plus duration convexity (TLT).")
    lines.append("")
    lines.append("  For our hedges to pay off, we need:")
    lines.append(f"  - Credit stress: HY spreads at {hy_level}, need >325bp")
    lines.append(f"  - AI de-rating: NVDA vs SPY {nvda_rel} over 3m")
    lines.append(f"  - Solar weakness: SLV/TAN ratio at {ratio_level}")
    lines.append("")
    
    # Bottom line
    lines.append("BOTTOM LINE")
    lines.append("  Markets remain risk-on. Our hedges are cheap insurance.")
    lines.append("  Watching for credit or tech cracks to validate the thesis.")
    
    # Print as plain text
    print("\n".join(lines))


def register(weekly_app: typer.Typer) -> None:
    @weekly_app.command("report")
    def weekly_report(
        share: bool = typer.Option(False, "--share", "-s", help="Chat-friendly format for sharing"),
    ):
        """
        Institutional-grade weekly report with regime context and forward calendar.
        
        Use --share for a compact format you can copy/paste into chats.
        """
        c = Console()
        now = datetime.now(timezone.utc)
        
        if share:
            _generate_shareable_report(now)
            return
        
        # ════════════════════════════════════════════════════════════════════════
        # HEADER
        # ════════════════════════════════════════════════════════════════════════
        c.print()
        c.print(Panel(
            f"[bold white]WEEKLY PORTFOLIO REVIEW[/bold white]\n"
            f"[dim]{now.strftime('%A, %B %d, %Y')} • {now.strftime('%H:%M')} UTC[/dim]",
            style="cyan",
            expand=False,
        ))
        c.print()
        
        # ════════════════════════════════════════════════════════════════════════
        # NAV & PERFORMANCE (Side by side)
        # ════════════════════════════════════════════════════════════════════════
        nav = _get_latest_nav()
        
        if nav:
            orig = float(nav.get("original_capital") or 0.0)
            eq = float(nav.get("equity") or 0.0)
            cash = float(nav.get("cash") or 0.0)
            net_ret = eq - orig
            weekly_ret = _safe_float(nav.get("twr_since_prev"))
            since_ret = _safe_float(nav.get("twr_cum"))
            
            ret_color = "green" if net_ret >= 0 else "red"
            wk_color = "green" if (weekly_ret or 0) >= 0 else "red"
            
            nav_lines = [
                f"[bold]Equity:[/bold] ${eq:,.2f}",
                f"[bold]Cash:[/bold] ${cash:,.2f} ({cash/eq*100:.1f}%)" if eq > 0 else f"Cash: ${cash:,.2f}",
                f"[bold]Cost Basis:[/bold] ${orig:,.2f}",
                f"[bold]P&L:[/bold] [{ret_color}]${net_ret:+,.2f}[/{ret_color}]",
            ]
            
            perf_lines = [
                f"[bold]Week:[/bold] [{wk_color}]{_fmt_pct(weekly_ret)}[/{wk_color}]" if weekly_ret is not None else "Week: —",
                f"[bold]Inception:[/bold] {_fmt_pct(since_ret)}" if since_ret is not None else "Inception: —",
                f"[dim]As of {_pretty_ts(str(nav.get('ts') or ''))}[/dim]",
            ]
            
            nav_panel = Panel("\n".join(nav_lines), title="[bold]Portfolio[/bold]", border_style="green", expand=True)
            perf_panel = Panel("\n".join(perf_lines), title="[bold]Returns[/bold]", border_style="blue", expand=True)
            c.print(Columns([nav_panel, perf_panel], equal=True))
        else:
            c.print("[yellow]NAV data not available[/yellow]")
        
        c.print()

        # ════════════════════════════════════════════════════════════════════════
        # REGIME CONTEXT (Market Environment)
        # ════════════════════════════════════════════════════════════════════════
        regimes = _get_regime_snapshot()
        if regimes:
            regime_lines = []
            
            if "volatility" in regimes:
                vol = regimes["volatility"]
                vix_val = vol.get("vix")
                vix_str = f"VIX {vix_val:.1f}" if vix_val else "VIX —"
                regime_lines.append(f"[bold]Vol:[/bold] {vol.get('regime', '—')} ({vix_str}, {vol.get('term_structure', '—')})")
            
            if "rates" in regimes:
                r = regimes["rates"]
                y10 = r.get("ust_10y")
                curve = r.get("curve_2s10s")
                y10_str = f"10Y {y10:.2f}%" if y10 else "10Y —"
                curve_str = f"2s10s {curve*100:+.0f}bp" if curve else ""
                regime_lines.append(f"[bold]Rates:[/bold] {r.get('regime', '—')} ({y10_str}{', ' + curve_str if curve_str else ''})")
            
            if "funding" in regimes:
                f = regimes["funding"]
                sofr = f.get("sofr")
                spread = f.get("spread_bps")
                sofr_str = f"SOFR {sofr:.2f}%" if sofr else ""
                regime_lines.append(f"[bold]Funding:[/bold] {f.get('regime', '—')}" + (f" ({sofr_str})" if sofr_str else ""))
            
            if regime_lines:
                c.print(Panel("\n".join(regime_lines), title="[bold]Market Regime[/bold]", border_style="magenta", expand=False))
                c.print()
        
        # ════════════════════════════════════════════════════════════════════════
        # DAY & WEEK AHEAD (Economic Calendar)
        # ════════════════════════════════════════════════════════════════════════
        events = _fetch_upcoming_events(days=7, max_items=12)
        if events:
            # Split into today vs rest of week
            today_events = [e for e in events if e["date"].date() == now.date()]
            week_events = [e for e in events if e["date"].date() != now.date()][:8]
            
            cal_table = Table(title="Economic Calendar", box=box.ROUNDED, expand=False, show_edge=True)
            cal_table.add_column("When", style="cyan", width=18)
            cal_table.add_column("Event", style="bold", width=35)
            cal_table.add_column("Est", justify="right", width=8)
            cal_table.add_column("Prev", justify="right", style="dim", width=8)
            
            for e in today_events:
                est = str(e["estimate"]) if e["estimate"] is not None else "—"
                prev = str(e["previous"]) if e["previous"] is not None else "—"
                style = "bold yellow" if e["high_impact"] else ""
                cal_table.add_row(
                    _format_event_time(e["date"]),
                    e["event"][:35],
                    est,
                    prev,
                    style=style,
                )
            
            if today_events and week_events:
                cal_table.add_row("─" * 15, "─" * 30, "─" * 6, "─" * 6, style="dim")
            
            for e in week_events:
                est = str(e["estimate"]) if e["estimate"] is not None else "—"
                prev = str(e["previous"]) if e["previous"] is not None else "—"
                style = "bold" if e["high_impact"] else "dim"
                cal_table.add_row(
                    _format_event_time(e["date"]),
                    e["event"][:35],
                    est,
                    prev,
                    style=style,
                )
            
            c.print(cal_table)
            c.print()
        else:
            c.print("[dim]No economic events loaded[/dim]")
            c.print()
        
        # ════════════════════════════════════════════════════════════════════════
        # POSITIONS
        # ════════════════════════════════════════════════════════════════════════
        try:
            trading, data_client = make_clients(load_settings())
            positions = trading.get_all_positions()
        except Exception:
            positions = []
            data_client = None

        # Build position table
        total_prem = 0.0
        nearest_exp: tuple[str, int, str] | None = None
        largest_prem: tuple[str, float] | None = None
        
        if positions:
            pos_table = Table(title="Holdings", box=box.ROUNDED, expand=False)
            pos_table.add_column("Position", style="bold", width=22)
            pos_table.add_column("Type", width=12)
            pos_table.add_column("Size", justify="right", width=10)
            pos_table.add_column("Value", justify="right", width=10)
            pos_table.add_column("Expiry", justify="right", style="dim", width=12)
            
            for p in positions:
                sym = str(getattr(p, "symbol", "") or "")
                qty = _safe_float(getattr(p, "qty", None)) or 0.0
                mv = _safe_float(getattr(p, "market_value", None))
                opt = _parse_occ_auto(sym)
                
                if opt:
                    pos_type = _intent_for_symbol(opt["underlying"])
                    exp = opt["expiry"]
                    dte = max(0, (exp - datetime.utcnow().date()).days)
                    expiry_str = f"{dte} DTE"
                    prem = _safe_float(getattr(p, "avg_entry_price", None))
                    if prem is None or prem <= 0:
                        prem = _safe_float(getattr(p, "current_price", None))
                    if prem is not None:
                        prem_usd = abs(qty) * float(prem) * 100.0
                        total_prem += prem_usd
                        if largest_prem is None or prem_usd > largest_prem[1]:
                            largest_prem = (sym, prem_usd)
                        if nearest_exp is None or dte < nearest_exp[1]:
                            nearest_exp = (sym, dte, str(exp))
                else:
                    pos_type = _intent_for_symbol(sym)
                    expiry_str = "—"
                
                mv_str = f"${abs(mv):,.0f}" if mv is not None else "—"
                qty_str = f"{qty:+.0f}" if qty != int(qty) == qty else f"{int(qty):+d}"
                
                pos_table.add_row(sym[:22], pos_type[:12], qty_str, mv_str, expiry_str)
            
            c.print(pos_table)
            
            # Risk summary
            if total_prem > 0 and nav:
                eqv = _safe_float(nav.get("equity")) or 0.0
                prem_pct = (total_prem / eqv * 100.0) if eqv > 0 else 0
                risk_lines = [
                    f"[bold]Premium at Risk:[/bold] ${total_prem:,.0f} ({prem_pct:.0f}% of equity)",
                ]
                if nearest_exp:
                    risk_lines.append(f"[bold]Nearest Expiry:[/bold] {nearest_exp[0][:15]} ({nearest_exp[1]} DTE)")
                if largest_prem:
                    risk_lines.append(f"[bold]Largest Position:[/bold] {largest_prem[0][:15]} (${largest_prem[1]:,.0f})")
                
                c.print(Panel("\n".join(risk_lines), title="[bold]Risk Summary[/bold]", border_style="red", expand=False))
        else:
            c.print("[dim]No positions loaded[/dim]")
        
        c.print()
        
        # ════════════════════════════════════════════════════════════════════════
        # KEY INDICATORS & TRIGGERS
        # ════════════════════════════════════════════════════════════════════════
        hy_asof, hy_level, hy_chg, hy_note, hy_chg_num = _hy_oas_metrics()
        nvda_asof, nvda_rel, nvda_note, nvda_rel_num = _rel_return_vs("NVDA", "SPY")
        ratio_asof, ratio_level, ratio_chg, ratio_note, ratio_chg_num = _ratio_change("SLV", "TAN")
        rates_asof, rates_1m, rates_3m, rates_note = _ust10y_change_1m_3m()
        
        ind_table = Table(title="Triggers & Watchlist", box=box.ROUNDED, expand=False)
        ind_table.add_column("Signal", style="bold", width=18)
        ind_table.add_column("Current", width=20)
        ind_table.add_column("Trigger Level", width=22, style="yellow")
        ind_table.add_column("Implication", width=25, style="dim")
        
        # Credit stress
        hy_status = "⚠️" if hy_chg_num and hy_chg_num > 15 else "✓"
        ind_table.add_row(
            f"{hy_status} HY OAS",
            f"{hy_level} (Δ3m: {hy_chg})",
            ">325bp or +25bp/1m",
            "Credit stress → HYG puts pay",
        )
        
        # NVDA relative
        nvda_status = "⚠️" if nvda_rel_num and nvda_rel_num < -5 else "✓"
        ind_table.add_row(
            f"{nvda_status} NVDA vs SPY",
            f"{nvda_rel} (3m)",
            "Underperf + weak breadth",
            "AI de-rating → NVDA puts pay",
        )
        
        # SLV/TAN ratio
        ratio_status = "⚠️" if ratio_chg_num and ratio_chg_num > 20 else "✓"
        ind_table.add_row(
            f"{ratio_status} SLV/TAN Ratio",
            f"{ratio_level} (Δ3m: {ratio_chg})",
            "Persistence >30d",
            "Solar stress → TAN puts pay",
        )
        
        # Rates
        ind_table.add_row(
            "✓ 10Y Yield",
            f"Δ1m: {rates_1m}, Δ3m: {rates_3m}",
            "Bull flatten / <4.0%",
            "Rates rally → TLT calls pay",
        )
        
        c.print(ind_table)
        c.print()
        
        # ════════════════════════════════════════════════════════════════════════
        # MACRO CONTEXT
        # ════════════════════════════════════════════════════════════════════════
        level, chg = _weekly_ust10y_change()
        live_level, live_asof, _ = _ust10y_live_yield()
        cpi_u, cpi_u_3m, cpi_u_asof, _, _, _ = _fred_yoy_and_change_days("CPIAUCSL", 90)
        fivey5y, fivey5y_asof, _ = _fred_latest("T5YIFR")
        _, _, _, sofr_note, _, sofr_num = _fred_latest_and_change_days("SOFR", 30)
        _, _, _, iorb_note, _, iorb_num = _fred_latest_and_change_days("IORB", 30)
        
        spread_str = "—"
        if sofr_num and iorb_num and not sofr_note and not iorb_note:
            spread_str = f"{(sofr_num - iorb_num) * 100.0:+.0f}bp"
        
        macro_lines = [
            f"[bold]10Y Yield:[/bold] {live_level} (wk {chg})",
            f"[bold]CPI YoY:[/bold] {cpi_u}% (Δ3m: {cpi_u_3m})",
            f"[bold]5y5y Breakeven:[/bold] {fivey5y}%",
            f"[bold]SOFR-IORB:[/bold] {spread_str}",
        ]
        c.print(Panel("\n".join(macro_lines), title="[bold]Macro Snapshot[/bold]", border_style="cyan", expand=False))
        c.print()
        
        # ════════════════════════════════════════════════════════════════════════
        # THESIS & ACTION ITEMS
        # ════════════════════════════════════════════════════════════════════════
        thesis_lines = [
            "[bold]Thesis:[/bold] Tail-risk hedges across credit/AI/solar + duration convexity",
            "[bold]Win Condition:[/bold] Risk-off regime (credit widening, AI de-rating, or rates rally)",
            "",
            "[bold cyan]This Week's Focus:[/bold cyan]",
            "  • Monitor HY OAS for signs of credit stress (>325bp)",
            "  • Watch NVDA relative strength vs SPY for AI weakness",
            "  • Track PCE release for inflation trajectory",
        ]
        
        if events:
            # Highlight today's key events
            today_high_impact = [e for e in events if e["date"].date() == now.date() and e["high_impact"]]
            if today_high_impact:
                thesis_lines.append("")
                thesis_lines.append("[bold yellow]Today's Key Events:[/bold yellow]")
                for e in today_high_impact[:3]:
                    thesis_lines.append(f"  • {e['date'].strftime('%H:%M')} — {e['event']}")
        
        c.print(Panel("\n".join(thesis_lines), title="[bold]Investment Thesis[/bold]", border_style="green", expand=False))
        c.print()
