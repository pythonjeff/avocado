from __future__ import annotations

import typer
from rich import print
from rich.panel import Panel
from rich.table import Table


def _run_volatility_snapshot(start: str = "2011-01-01", refresh: bool = False, llm: bool = False):
    """Shared implementation for volatility snapshot."""
    from ai_options_trader.config import load_settings
    from ai_options_trader.volatility.signals import build_volatility_state
    from ai_options_trader.volatility.regime import classify_volatility_regime

    settings = load_settings()
    state = build_volatility_state(settings=settings, start_date=start, refresh=refresh)
    regime = classify_volatility_regime(state.inputs)

    print(
        Panel(
            f"[b]Regime:[/b] {regime.label}\n"
            f"[b]VIX:[/b] {state.inputs.vix}\n"
            f"[b]5d chg%:[/b] {state.inputs.vix_chg_5d_pct}\n"
            f"[b]Term (VIX-3m proxy):[/b] {state.inputs.vix_term_spread}\n"
            f"[b]Term source:[/b] {state.inputs.vix_term_source}\n"
            f"[b]Z VIX:[/b] {state.inputs.z_vix}\n"
            f"[b]Z 5d chg:[/b] {state.inputs.z_vix_chg_5d}\n"
            f"[b]Persist 20d:[/b] {state.inputs.persist_20d}\n"
            f"[b]Pressure score:[/b] {state.inputs.vol_pressure_score}\n\n"
            f"[dim]{regime.description}[/dim]",
            title="Volatility (Full)",
            expand=False,
        )
    )

    if llm:
        from ai_options_trader.llm.core.analyst import llm_analyze_regime
        
        print("\n[bold cyan]Generating LLM analysis...[/bold cyan]\n")
        
        snapshot_data = {
            "vix": state.inputs.vix,
            "vix_chg_5d_pct": state.inputs.vix_chg_5d_pct,
            "vix_term_spread": state.inputs.vix_term_spread,
            "vix_term_source": state.inputs.vix_term_source,
            "z_vix": state.inputs.z_vix,
            "z_vix_chg_5d": state.inputs.z_vix_chg_5d,
            "persist_20d": state.inputs.persist_20d,
            "vol_pressure_score": state.inputs.vol_pressure_score,
        }
        
        analysis = llm_analyze_regime(
            settings=settings,
            domain="volatility",
            snapshot=snapshot_data,
            regime_label=regime.label,
            regime_description=regime.description,
        )
        
        from rich.markdown import Markdown
        print(Panel(Markdown(analysis), title="Analysis", expand=False))


def register(vol_app: typer.Typer) -> None:
    # Default callback so `lox labs volatility --llm` works without `snapshot`
    @vol_app.callback(invoke_without_command=True)
    def volatility_default(
        ctx: typer.Context,
        llm: bool = typer.Option(False, "--llm", help="Get PhD-level LLM analysis with real-time data"),
    ):
        """Volatility regime (VIX: level/momentum/term structure)"""
        if ctx.invoked_subcommand is None:
            _run_volatility_snapshot(llm=llm)

    @vol_app.command("snapshot")
    def snapshot(
        start: str = typer.Option("2011-01-01", "--start"),
        refresh: bool = typer.Option(False, "--refresh"),
        llm: bool = typer.Option(False, "--llm", help="Get PhD-level LLM analysis with real-time data"),
    ):
        """Volatility snapshot (VIX-based): level, momentum, term structure."""
        _run_volatility_snapshot(start=start, refresh=refresh, llm=llm)

    @vol_app.command("term-structure")
    def term_structure(
        ticker: str = typer.Option("VIXY", "--ticker", help="Vol proxy ETF to review (VIXY/VXX/UVXY/etc)."),
        start: str = typer.Option("2011-01-01", "--start"),
        refresh: bool = typer.Option(False, "--refresh"),
        lookback_days: int = typer.Option(252, "--lookback-days", help="Lookback window for recent stats/correlations."),
    ):
        """
        Review VIX term structure (proxy) and relate it to a vol ETF like VIXY.

        Notes:
        - VIXY is driven by short-dated VIX futures roll yield, so *true* contango/backwardation is about the VIX futures curve.
        - As an MVP proxy, we use VIX vs a 3m anchor:
          - FRED VIX3M when available
          - Otherwise best-effort FMP VXV (3-month VIX index)
        """
        import numpy as np
        import pandas as pd

        from ai_options_trader.config import load_settings
        from ai_options_trader.data.market import fetch_equity_daily_closes
        from ai_options_trader.volatility.signals import build_volatility_dataset

        settings = load_settings()
        sym = (ticker or "VIXY").strip().upper()

        vdf = build_volatility_dataset(settings=settings, start_date=start, refresh=refresh)
        if vdf is None or vdf.empty:
            raise typer.BadParameter("Volatility dataset is empty.")

        v = vdf.copy()
        v["date"] = pd.to_datetime(v["date"])
        v = v.set_index("date").sort_index()
        vix = pd.to_numeric(v.get("VIX"), errors="coerce")
        vix3m = pd.to_numeric(v.get("VIX3M"), errors="coerce") if "VIX3M" in v.columns else None
        spread = pd.to_numeric(v.get("VIX_TERM_SPREAD"), errors="coerce") if "VIX_TERM_SPREAD" in v.columns else None
        src = None
        try:
            if "VIX_TERM_SOURCE" in v.columns:
                src = str(v["VIX_TERM_SOURCE"].dropna().iloc[-1]) if not v["VIX_TERM_SOURCE"].dropna().empty else None
        except Exception:
            src = None

        if vix is None or vix.dropna().empty:
            raise typer.BadParameter("Missing VIX series (VIXCLS).")
        if vix3m is None or vix3m.dropna().empty or spread is None or spread.dropna().empty:
            print(
                Panel(
                    "Missing a usable 3m anchor for term structure.\n"
                    "Tried: FRED VIX3M and best-effort FMP VXV.\n"
                    "You can still use `lox labs volatility snapshot` for VIX level/momentum.\n"
                    "If you have an FMP key configured, ensure it has access to VXV history.",
                    title="VIX term structure (proxy) unavailable",
                    expand=False,
                )
            )
            raise typer.Exit(code=1)

        # Align on latest common date
        asof = min(vix.dropna().index.max(), vix3m.dropna().index.max(), spread.dropna().index.max())
        vix_last = float(vix.loc[asof])
        vix3m_last = float(vix3m.loc[asof])
        spr_last = float(spread.loc[asof])
        ratio_pct = (vix_last / vix3m_last - 1.0) * 100.0 if vix3m_last != 0 else float("nan")

        state = "backwardation-ish" if spr_last > 0 else "contango-ish"
        # "How far from backwardation" (if contango-ish): spread is negative, so distance is abs(spread).
        dist_to_backwardation = float(abs(min(spr_last, 0.0)))

        # Recent stats
        lb = int(max(20, lookback_days))
        spr_recent = spread.dropna().iloc[-lb:]
        pct_rank = float((spr_recent <= spr_last).mean() * 100.0) if not spr_recent.empty else float("nan")
        back_60 = float((spread.dropna().iloc[-60:] > 0).mean() * 100.0) if len(spread.dropna()) >= 60 else float("nan")

        # VIXY behavior
        px = fetch_equity_daily_closes(settings=settings, symbols=[sym], start=str(pd.to_datetime(start).date()), refresh=False).sort_index().ffill()
        pxs = px[sym] if (px is not None and not px.empty and sym in px.columns) else pd.Series(dtype=float)
        if pxs.dropna().empty:
            print(Panel(f"No prices for {sym}.", title="Market data", expand=False))
            raise typer.Exit(code=1)
        # Align with vol dates
        idx = pxs.index.intersection(v.index)
        pxs = pxs.loc[idx].dropna()
        spread_al = spread.loc[idx].ffill()
        vix_al = vix.loc[idx].ffill()

        def _ret(p: pd.Series, w: int) -> float | None:
            if len(p.dropna()) <= w:
                return None
            r = (p.iloc[-1] / p.iloc[-1 - w] - 1.0) * 100.0
            return float(r) if np.isfinite(r) else None

        def _delta(s: pd.Series, w: int) -> float | None:
            if len(s.dropna()) <= w:
                return None
            d = float(s.iloc[-1] - s.iloc[-1 - w])
            return d if np.isfinite(d) else None

        # Correlations over recent lookback
        corr_lb = min(lb, len(idx))
        r1d = pxs.pct_change().iloc[-corr_lb:].dropna()
        d_spr = spread_al.diff().iloc[-corr_lb:].dropna()
        d_vix = vix_al.diff().iloc[-corr_lb:].dropna()
        corr_spr = float(r1d.corr(d_spr)) if (not r1d.empty and not d_spr.empty) else float("nan")
        corr_vix = float(r1d.corr(d_vix)) if (not r1d.empty and not d_vix.empty) else float("nan")

        print(
            Panel(
                f"[b]asof:[/b] {str(pd.to_datetime(asof).date())}\n"
                f"[b]VIX:[/b] {vix_last:.2f}   [b]3m anchor:[/b] {vix3m_last:.2f}   [b]source:[/b] {src}\n"
                f"[b]Proxy spread (VIX-3M):[/b] {spr_last:+.2f}  ({state})\n"
                f"[b]Proxy ratio (VIX/VIX3M-1):[/b] {ratio_pct:+.2f}%\n"
                f"[b]Distance to backwardation (if contango):[/b] {dist_to_backwardation:.2f}\n"
                f"[b]Backwardation days (last 60):[/b] {'—' if not np.isfinite(back_60) else f'{back_60:.0f}%'}\n"
                f"[b]Spread percentile (last {corr_lb}d):[/b] {'—' if not np.isfinite(pct_rank) else f'{pct_rank:.0f}th'}\n"
                f"[b]{sym} 1d ret corr:[/b] Δspread={corr_spr:+.2f}  ΔVIX={corr_vix:+.2f}\n",
                title="VIX term structure (proxy) × vol ETF behavior",
                expand=False,
            )
        )

        tbl = Table(title=f"{sym} recent behavior (returns) vs term-structure changes")
        tbl.add_column("horizon", justify="right")
        tbl.add_column(f"{sym} ret", justify="right")
        tbl.add_column("Δ(VIX-3M)", justify="right")
        tbl.add_column("ΔVIX", justify="right")
        for w, name in [(5, "5d"), (20, "20d"), (60, "60d")]:
            rr = _ret(pxs, w)
            ds = _delta(spread_al, w)
            dv = _delta(vix_al, w)
            tbl.add_row(
                name,
                "—" if rr is None else f"{rr:+.2f}%",
                "—" if ds is None else f"{ds:+.2f}",
                "—" if dv is None else f"{dv:+.2f}",
            )
        print(tbl)

    @vol_app.command("front-end")
    def front_end(
        dt: str = typer.Option("", "--dt", help="Settlement date YYYY-MM-DD (defaults to latest available)."),
        refresh: bool = typer.Option(False, "--refresh", help="Refresh cached Cboe settlement CSV."),
        start: str = typer.Option("2011-01-01", "--start", help="Start date for spot VIX series (FRED)."),
        recent: int = typer.Option(30, "--recent", help="Also compute recent contango stats over N calendar days (best-effort)."),
    ):
        """
        Front-end VIX futures dashboard (best for VIXY/VXX roll logic).

        Pulls VX daily settlement prices from Cboe's free public CSV:
          /us/futures/market_statistics/settlement/csv/?dt=YYYY-MM-DD

        Computes:
        - M1 (front-month monthly VX)
        - M2 (second-month monthly VX)
        - Contango/backwardation % = (M2/M1 - 1) * 100
        - Spot VIX vs M1 basis (spot - future) using FRED VIXCLS (best-effort)
        """
        import numpy as np
        import pandas as pd

        from ai_options_trader.config import load_settings
        from ai_options_trader.volatility.signals import build_volatility_dataset
        from ai_options_trader.volatility.vx_front_end import (
            fetch_cboe_settlement_csv_text,
            iter_recent_dates,
            parse_vx_front_end_from_settlement_csv,
        )

        settings = load_settings()

        # Determine target date: default to "yesterday UTC" as Cboe settlement is for a session date.
        if dt.strip():
            d0 = pd.to_datetime(dt.strip(), errors="coerce")
            if pd.isna(d0):
                raise typer.BadParameter("--dt must be YYYY-MM-DD")
            target = d0.date()
        else:
            target = (pd.Timestamp.utcnow() - pd.Timedelta(days=1)).date()

        # Spot VIX as-of date (best-effort): use latest <= target from FRED series.
        spot_vix = None
        try:
            vdf = build_volatility_dataset(settings=settings, start_date=start, refresh=bool(refresh))
            vdf = vdf.copy()
            vdf["date"] = pd.to_datetime(vdf["date"])
            vdf = vdf.set_index("date").sort_index()
            vix = pd.to_numeric(vdf.get("VIX"), errors="coerce").dropna()
            if not vix.empty:
                vix_upto = vix.loc[vix.index <= pd.to_datetime(target)]
                if not vix_upto.empty:
                    spot_vix = float(vix_upto.iloc[-1])
        except Exception:
            spot_vix = None

        # Latest settlement for target date (best-effort; Cboe may not have it for weekends/holidays)
        front = None
        used_dt = None
        last_err = None
        for d in iter_recent_dates(lookback_days=10):
            if d > target:
                continue
            try:
                txt = fetch_cboe_settlement_csv_text(dt=d, refresh=bool(refresh))
                front = parse_vx_front_end_from_settlement_csv(dt=d, csv_text=txt, spot_vix=spot_vix)
                used_dt = d
                break
            except Exception as e:
                last_err = e
                continue
        if front is None or used_dt is None:
            raise typer.BadParameter(f"Failed to load/parse Cboe VX settlement CSV (last_err={last_err}).")

        state = "backwardation" if front.contango_pct < 0 else "contango"
        dist_to_backwardation = float(max(0.0, front.contango_pct)) if front.contango_pct >= 0 else 0.0

        spot_line = ""
        if front.spot_vix is not None and front.spot_minus_m1 is not None and front.spot_minus_m1_pct is not None:
            spot_line = (
                f"[b]Spot VIX:[/b] {front.spot_vix:.2f}  "
                f"[b]Spot−M1:[/b] {front.spot_minus_m1:+.2f}  ({front.spot_minus_m1_pct:+.2f}%)\n"
            )

        print(
            Panel(
                f"[b]asof settlement dt:[/b] {used_dt.isoformat()}\n"
                f"[b]M1:[/b] {front.m1_symbol} exp={front.m1_expiration.isoformat()} settle={front.m1_settle:.4f}\n"
                f"[b]M2:[/b] {front.m2_symbol} exp={front.m2_expiration.isoformat()} settle={front.m2_settle:.4f}\n"
                f"[b]Slope (M2/M1-1):[/b] {front.contango_pct:+.2f}%  ({state})\n"
                f"[b]Distance to backwardation:[/b] {dist_to_backwardation:.2f}%\n"
                f"{spot_line}"
                f"[dim]Source: Cboe daily settlement CSV + FRED VIXCLS (spot, best-effort)[/dim]",
                title="VX front-end vol (VIXY/VXX roll dashboard)",
                expand=False,
            )
        )

        # Recent behavior (best-effort)
        n = int(max(0, recent))
        if n > 0:
            obs = []
            for d in iter_recent_dates(lookback_days=max(7, n * 3)):
                try:
                    txt = fetch_cboe_settlement_csv_text(dt=d, refresh=False)
                    fe = parse_vx_front_end_from_settlement_csv(dt=d, csv_text=txt, spot_vix=None)
                    obs.append((d, fe.contango_pct))
                except Exception:
                    continue
                if len(obs) >= n:
                    break

            if obs:
                obs.sort(key=lambda x: x[0])
                vals = [v for _, v in obs if np.isfinite(v)]
                last = float(vals[-1]) if vals else float("nan")
                back_pct = float(sum(1 for v in vals if v < 0) / len(vals) * 100.0) if vals else float("nan")
                pct_rank = float(sum(1 for v in vals if v <= last) / len(vals) * 100.0) if vals else float("nan")
                tbl = Table(title=f"Recent VX contango (best-effort, last {len(vals)} settlement days)")
                tbl.add_column("metric")
                tbl.add_column("value", justify="right")
                tbl.add_row("current contango%", f"{last:+.2f}%")
                tbl.add_row("backwardation days", f"{back_pct:.0f}%")
                tbl.add_row("percentile of current", f"{pct_rank:.0f}th")
                print(tbl)


