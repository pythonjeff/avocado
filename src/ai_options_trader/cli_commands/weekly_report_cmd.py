from __future__ import annotations

from datetime import datetime, timezone
import os
import pandas as pd
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ai_options_trader.config import Settings, load_settings
from ai_options_trader.data.alpaca import fetch_option_chain, to_candidates
from ai_options_trader.data.alpaca import make_clients
from ai_options_trader.data.market import fetch_equity_daily_closes
from ai_options_trader.utils.occ import parse_occ_option_symbol


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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
    settings = _safe_settings()
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
    settings = _safe_settings()
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
    settings = _safe_settings()
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
    settings = _safe_settings()
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
    settings = _safe_settings()
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
    settings = _safe_settings()
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
    settings = _safe_settings()
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
def _safe_settings():
    try:
        return load_settings()
    except Exception:
        try:
            # Fallback: ignore .env if it is unreadable, rely on environment vars.
            return Settings.model_construct(
                AOT_PRICE_SOURCE=os.getenv("AOT_PRICE_SOURCE", "fmp"),
                ALPACA_API_KEY=os.getenv("ALPACA_API_KEY", ""),
                ALPACA_API_SECRET=os.getenv("ALPACA_API_SECRET", ""),
                ALPACA_PAPER=str(os.getenv("ALPACA_PAPER", "true")).lower() not in {"0", "false", "no"},
                ALPACA_DATA_KEY=os.getenv("ALPACA_DATA_KEY"),
                ALPACA_DATA_SECRET=os.getenv("ALPACA_DATA_SECRET"),
                ALPACA_OPTIONS_FEED=os.getenv("ALPACA_OPTIONS_FEED"),
                OPENAI_API_KEY=os.getenv("OPENAI_API_KEY"),
                OPENAI_MODEL=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                FRED_API_KEY=os.getenv("FRED_API_KEY"),
                FMP_API_KEY=os.getenv("FMP_API_KEY"),
            )
        except Exception:
            return None


def _hy_oas_metrics() -> tuple[str, str, str, str, float | None]:
    """
    Returns (asof, latest_bps, change_bps) for HY OAS, or DATA NOT PROVIDED.
    """
    settings = _safe_settings()
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
    settings = _safe_settings()
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
    settings = _safe_settings()
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


def register(weekly_app: typer.Typer) -> None:
    @weekly_app.command("report")
    def weekly_report():
        """
        Basic weekly report: NAV, current trades + short thesis, and 10Y weekly performance.
        """
        c = Console()
        c.print("# Weekly Report — Lox")
        c.print("")
        c.print(f"asof: {_pretty_ts(_now_utc_iso())}")
        c.print("")

        # NAV
        nav = _get_latest_nav()
        if nav:
            orig = float(nav.get("original_capital") or 0.0)
            eq = float(nav.get("equity") or 0.0)
            net_ret = eq - orig
            net_color = "green" if net_ret >= 0 else "red"
            nav_txt = (
                f"[b]As of:[/b] {_pretty_ts(str(nav.get('ts') or ''))}\n"
                f"[b]Original capital:[/b] ${orig:,.2f}\n"
                f"[b]Net return:[/b] [{net_color}]${net_ret:,.2f}[/{net_color}]\n"
                f"[b]Equity:[/b] ${eq:,.2f}\n"
                f"[b]Cash:[/b] ${float(nav.get('cash') or 0.0):,.2f}\n"
                f"[b]Buying power:[/b] ${float(nav.get('buying_power') or 0.0):,.2f}"
            )
            c.print("## NAV Snapshot")
            c.print(Panel(nav_txt, title="NAV", expand=False))
        else:
            c.print("## NAV Snapshot")
            c.print("DATA NOT PROVIDED (no NAV snapshots found)")
        c.print("")

        # Load positions once for summary + tables
        try:
            trading, data_client = make_clients(load_settings())
            positions = trading.get_all_positions()
        except Exception:
            positions = []
            data_client = None

        # Weekly investor update (compact)
        c.print("\n## Weekly Investor Update")
        # Cash / exposure summary
        cash_pct = "DATA NOT PROVIDED"
        gross = "DATA NOT PROVIDED"
        net = "DATA NOT PROVIDED"
        opt_mv = "DATA NOT PROVIDED"
        if positions:
            try:
                mvs = [float(getattr(p, "market_value", 0.0) or 0.0) for p in positions]
                gross_v = sum(abs(v) for v in mvs)
                net_v = sum(mvs)
                gross = f"${gross_v:,.2f}"
                net = f"${net_v:,.2f}"
                opt_mv_v = 0.0
                # Use bid/ask mid if available for options; fallback to position market_value.
                mid_by_symbol: dict[str, float] = {}
                if data_client is not None:
                    try:
                        settings = _safe_settings()
                        underlyings = sorted(
                            {
                                opt["underlying"]
                                for p in positions
                                if (opt := _parse_occ_auto(str(getattr(p, "symbol", "") or "")))
                            }
                        )
                        for und in underlyings:
                            chain = fetch_option_chain(
                                data_client,
                                und,
                                feed=getattr(settings, "alpaca_options_feed", None) if settings else None,
                            )
                            for cand in to_candidates(chain, und):
                                mid = cand.mid
                                if mid is not None:
                                    mid_by_symbol[str(cand.symbol)] = float(mid)
                    except Exception:
                        mid_by_symbol = {}
                for p in positions:
                    sym = str(getattr(p, "symbol", "") or "")
                    opt = _parse_occ_auto(sym)
                    if opt:
                        qty = float(getattr(p, "qty", 0.0) or 0.0)
                        mid = mid_by_symbol.get(sym)
                        if mid is None:
                            bid = getattr(p, "bid_price", None) or getattr(p, "bid", None)
                            ask = getattr(p, "ask_price", None) or getattr(p, "ask", None)
                            if bid is not None and ask is not None and float(bid) > 0 and float(ask) > 0:
                                mid = (float(bid) + float(ask)) / 2.0
                        if mid is None:
                            cur = getattr(p, "current_price", None)
                            if cur is not None and float(cur) > 0:
                                mid = float(cur)
                        if mid is not None:
                            opt_mv_v += abs(qty) * float(mid) * 100.0
                        else:
                            opt_mv_v += float(getattr(p, "market_value", 0.0) or 0.0)
                opt_mv = f"${opt_mv_v:,.2f}"
            except Exception:
                pass
        if nav:
            try:
                eqv = float(nav.get("equity") or 0.0)
                cashv = float(nav.get("cash") or 0.0)
                if eqv > 0:
                    cash_pct = f"{(cashv / eqv) * 100.0:.1f}%"
            except Exception:
                pass

        c.print(f"- Cash % of equity: {cash_pct}")
        c.print(f"- Gross / net exposure: {gross} / {net}")
        c.print(f"- Options market value: {opt_mv}")

        # Performance (investor-facing)
        c.print("\n## Performance")
        if nav:
            weekly_ret = _safe_float(nav.get("twr_since_prev"))
            since_ret = _safe_float(nav.get("twr_cum"))
            c.print(f"- Equity: ${eq:,.2f}")
            if weekly_ret is not None:
                c.print(f"- Weekly return (last NAV interval): {_fmt_pct(weekly_ret)}")
            if since_ret is not None:
                c.print(f"- Since inception return: {_fmt_pct(since_ret)}")
        else:
            c.print("- DATA NOT PROVIDED")

        # Portfolio purpose (one line)
        c.print("\n## Portfolio Purpose")
        c.print("Small-premium risk hedges across credit/AI/solar plus duration convexity.")

        # Performance drivers (plain English)
        c.print("\n## Performance Drivers (this week)")
        c.print("• Credit hedges detracted (HYG puts down) as spreads remained tight.")
        c.print("• Solar downside hedge detracted (TAN puts down) despite SLV/TAN improving; timing/vol mattered.")
        c.print("• NVDA put roughly flat; volatility and time decay offset small underlying moves.")
        c.print("• Defensive diversifiers (GLDM) helped modestly.")

        # Key risks + management (compact)
        c.print("\n## Key Risks & Management")
        c.print("• Credit spreads stay tight → HYG downside takes longer; size kept small vs equity.")
        c.print("• AI remains bid / rates fall → NVDA put decay risk; manage via time and premium limits.")
        c.print("• Silver rolls over while solar stabilizes → TAN put edge fades; monitored vs SLV/TAN.")

        # Current positioning (simplified)
        c.print("\n## Current Positioning")
        if positions:
            t = Table(title="Current positioning")
            t.add_column("instrument", style="bold")
            t.add_column("intent")
            t.add_column("max loss")
            t.add_column("time horizon", justify="right")

            total_prem = 0.0
            nearest_exp: tuple[str, int, str] | None = None
            largest_prem: tuple[str, float] | None = None
            short_option_present = False

            for p in positions:
                sym = str(getattr(p, "symbol", "") or "")
                qty = _safe_float(getattr(p, "qty", None)) or 0.0
                mv = _safe_float(getattr(p, "market_value", None))
                opt = _parse_occ_auto(sym)
                intent = _intent_for_symbol(sym if not opt else opt["underlying"])
                max_loss = "DATA NOT PROVIDED"
                horizon = "DATA NOT PROVIDED"

                if opt:
                    exp = opt["expiry"]
                    dte = max(0, (exp - datetime.utcnow().date()).days)
                    horizon = f"{exp} ({dte} DTE)"
                    prem = _safe_float(getattr(p, "avg_entry_price", None))
                    if prem is None or prem <= 0:
                        prem = _safe_float(getattr(p, "current_price", None))
                    if prem is not None:
                        prem_usd = abs(qty) * float(prem) * 100.0
                        max_loss = f"${prem_usd:,.2f}"
                        if qty < 0:
                            short_option_present = True
                        total_prem += prem_usd
                        if largest_prem is None or prem_usd > largest_prem[1]:
                            largest_prem = (sym, prem_usd)
                        if nearest_exp is None or dte < nearest_exp[1]:
                            nearest_exp = (sym, dte, str(exp))
                else:
                    if qty < 0:
                        max_loss = "Short (unbounded)"
                    elif mv is not None:
                        max_loss = f"${abs(mv):,.2f}"
                    horizon = "Open-ended"

                t.add_row(sym, intent, max_loss, horizon)

            c.print(t)

            # Risk & runway block
            c.print("\n## Risk & Runway")
            if total_prem > 0 and nav:
                eqv = _safe_float(nav.get("equity")) or 0.0
                prem_pct = (total_prem / eqv * 100.0) if eqv > 0 else None
                c.print(
                    f"- Total option premium at risk: ${total_prem:,.2f}"
                    + (f" ({prem_pct:.1f}% of equity)" if prem_pct is not None else "")
                )
            else:
                c.print("- Total option premium at risk: DATA NOT PROVIDED")
            if nearest_exp:
                c.print(f"- Nearest expiry: {nearest_exp[0]} ({nearest_exp[1]} DTE)")
            else:
                c.print("- Nearest expiry: DATA NOT PROVIDED")
            if largest_prem:
                c.print(f"- Largest option position by premium: {largest_prem[0]} (${largest_prem[1]:,.2f})")
            else:
                c.print("- Largest option position by premium: DATA NOT PROVIDED")
            if short_option_present:
                c.print("- Note: Short option positions detected; max loss is not bounded.")
        else:
            c.print("DATA NOT PROVIDED (no open positions)")

        # Market thesis (macro conditions required to win)
        c.print("\n## Market Thesis (What must happen to win)")
        thesis_t = Table(show_header=False, box=None, pad_edge=False)
        thesis_t.add_column("thesis")
        for tline in THEMES:
            thesis_t.add_row(f"• {tline}")
        c.print(thesis_t)

        # Leading indicators (top 3)
        c.print("\n## Leading Indicators (with triggers)")
        hy_asof, hy_level, hy_chg, hy_note, hy_chg_num = _hy_oas_metrics()
        nvda_asof, nvda_rel, nvda_note, nvda_rel_num = _rel_return_vs("NVDA", "SPY")
        ratio_asof, ratio_level, ratio_chg, ratio_note, ratio_chg_num = _ratio_change("SLV", "TAN")
        rates_asof, rates_1m, rates_3m, rates_note = _ust10y_change_1m_3m()

        if hy_note:
            hy_level = f"{hy_level} ({hy_note})"
        if nvda_note:
            nvda_rel = f"{nvda_rel} ({nvda_note})"
        if ratio_note:
            ratio_level = f"{ratio_level} ({ratio_note})"
        if rates_note:
            rates_1m = f"{rates_1m} ({rates_note})"

        ind_t = Table(title="Leading Indicators", show_header=True)
        ind_t.add_column("Indicator", style="bold")
        ind_t.add_column("Latest (asof)", overflow="fold")
        ind_t.add_column("Watch / trigger", overflow="fold")

        ind_t.add_row(
            "Credit stress (HY OAS)",
            f"latest={hy_level}; 3m change={hy_chg}; asof={hy_asof}",
            "watch: >325 bps or +25 bps in 1m = confirmation",
        )
        ind_t.add_row(
            "AI de-rating (NVDA vs SPY)",
            f"rel return (3m)={nvda_rel}; asof={nvda_asof}",
            "watch: continued underperformance + breadth deterioration",
        )
        ind_t.add_row(
            "Solar relative (SLV/TAN)",
            f"ratio={ratio_level}; 3m change={ratio_chg}; asof={ratio_asof}",
            "watch: persistence + solar earnings revisions",
        )
        ind_t.add_row(
            "Rates leg (TLT call)",
            f"10Y yield change 1m={rates_1m}; 3m={rates_3m}; asof={rates_asof}",
            "watch: yields lower / curve bull-flattening",
        )
        c.print(ind_t)

        # Weekly 10Y
        level, chg = _weekly_ust10y_change()
        live_level, live_asof, live_note = _ust10y_live_yield()
        if live_note:
            live_level = f"{live_level} ({live_note})"

        # Inflation + liquidity metrics (best-effort)
        cpi_u, cpi_u_3m, cpi_u_asof, cpi_u_note, cpi_u_3m_num, cpi_u_num = _fred_yoy_and_change_days(
            "CPIAUCSL", 90
        )
        _, cpi_u_6m, _cpi_u_asof2, _cpi_u_note2, cpi_u_6m_num, _cpi_u_num2 = _fred_yoy_and_change_days(
            "CPIAUCSL", 180
        )
        if cpi_u_note:
            cpi_u = f"{cpi_u} ({cpi_u_note})"

        med_cpi, med_cpi_3m, med_cpi_asof, med_cpi_note, med_cpi_3m_num, med_cpi_num = _fred_latest_and_change_days(
            "MEDCPIM158SFRBCLE", 90
        )
        _, med_cpi_6m, _asof2, _note2, _num2, _num3 = _fred_latest_and_change_days("MEDCPIM158SFRBCLE", 180)
        if med_cpi_note:
            med_cpi = f"{med_cpi} ({med_cpi_note})"

        fivey5y, fivey5y_asof, fivey5y_note = _fred_latest("T5YIFR")
        if fivey5y_note:
            fivey5y = f"{fivey5y} ({fivey5y_note})"
        _sofr, _sofr_chg, _sofr_asof, sofr_note, _sofr_chg_num, sofr_num = _fred_latest_and_change_days(
            "SOFR", 30
        )
        _iorb, _iorb_chg, _iorb_asof, iorb_note, _iorb_chg_num, iorb_num = _fred_latest_and_change_days(
            "IORB", 30
        )
        if sofr_note:
            sofr_num = None
        if iorb_note:
            iorb_num = None

        infl_vs_be = "DATA NOT PROVIDED"
        try:
            if med_cpi_num is not None and fivey5y_note == "":
                infl_vs_be = f"{(med_cpi_num - float(fivey5y)):+.2f}pp"
        except Exception:
            infl_vs_be = "DATA NOT PROVIDED"

        spread_bps = "DATA NOT PROVIDED"
        try:
            if sofr_num is not None and iorb_num is not None:
                spread_bps = f"{(sofr_num - iorb_num) * 100.0:+.0f} bps"
        except Exception:
            spread_bps = "DATA NOT PROVIDED"

        liq_line = "Liquidity/funding: Overnight funding conditions remain orderly."
        if spread_bps != "DATA NOT PROVIDED":
            liq_line = f"Liquidity/funding: Overnight funding conditions remain orderly; SOFR–IORB ~ {spread_bps}."
        regime_read = "Policy easing in progress; inflation signals mixed; funding conditions orderly."

        c.print(
            Panel(
                "Rates:\n"
                f"  10Y: {level} (wk {chg}); Live {live_level} (asof {live_asof})\n"
                "\nInflation:\n"
                f"  Headline CPI YoY: {cpi_u} (3m {cpi_u_3m}, 6m {cpi_u_6m}; asof {cpi_u_asof})\n"
                f"  Median CPI YoY: {med_cpi} (3m {med_cpi_3m}, 6m {med_cpi_6m}; asof {med_cpi_asof})\n"
                f"  5y5y breakeven: {fivey5y} (asof {fivey5y_asof})\n"
                f"  Dislocation (Median CPI − 5y5y): {infl_vs_be}\n"
                "\nLiquidity:\n"
                f"  {liq_line}\n"
                f"\nRegime read: {regime_read}",
                title="Macro Weekly Performance",
                expand=False,
            )
        )

        # Positioning changes / next actions
        c.print("\n## Positioning Changes / Next Actions")
        c.print("• Trades / changes this week: DATA NOT PROVIDED.")
        c.print("• Planned actions (conditional): If HY OAS widens materially, we may take partial profits on HYG puts; "
                "if vol spikes, we may reduce VIX exposure.")

        # Next-week watchlist
        c.print("\n## Next Week Watchlist")
        c.print("• HY OAS +25 bps in 1m would validate credit stress.")
        c.print("• Median CPI YoY re-accelerates > +0.3pp in 3m.")
        c.print("• NVDA underperforms SPY further on weaker breadth.")
