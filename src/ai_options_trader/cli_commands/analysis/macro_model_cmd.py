from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table


def register(ideas_app: typer.Typer) -> None:
    def _augment_feature_set_with_whitelist_extra(
        *,
        fs: str,
        Xr: "pd.DataFrame",
        Xr_full: "pd.DataFrame",
        whitelist_extra: str,
    ) -> "pd.DataFrame":
        """
        When using --feature-set fci, we sometimes want to A/B a single extra regime feature
        that isn't part of the FCI matrix (e.g., fiscal/commod/macro). This keeps the core FCI
        narrative but allows a controlled extra interaction family.
        """
        extra = (whitelist_extra or "none").strip().lower()
        if fs != "fci" or extra in {"none", "rates", "funding", "vol"}:
            # rates/funding/vol are already present in FCI as fci_rates/fci_funding/fci_vol
            return Xr
        want_cols: list[str] = []
        if extra == "fiscal":
            want_cols = ["fiscal_pressure_score"]
        elif extra == "commod":
            want_cols = ["commod_pressure_score"]
        elif extra == "macro":
            want_cols = ["macro_disconnect_score"]
        cols = [c for c in want_cols if c in Xr_full.columns]
        return Xr.join(Xr_full[cols], how="left") if cols else Xr

    @ideas_app.command("macro-model")
    def macro_model(
        start: str = typer.Option("2012-01-01", "--start", help="Start date YYYY-MM-DD"),
        refresh: bool = typer.Option(False, "--refresh", help="Force refresh FRED downloads (regimes)"),
        top: int = typer.Option(12, "--top", help="How many tickers to print"),
        basket: str = typer.Option("starter", "--basket", help="starter|extended (universe for training/prediction)"),
        feature_set: str = typer.Option("full", "--feature-set", help="full|fci (FCI = financial-conditions narrative)"),
        with_options: bool = typer.Option(False, "--with-options/--no-options", help="Attach <=$100 call/put leg when possible"),
        max_premium_usd: float = typer.Option(100.0, "--max-premium", help="Max premium per option contract (USD)"),
        min_days: int = typer.Option(30, "--min-days", help="Min option DTE (calendar days)"),
        max_days: int = typer.Option(90, "--max-days", help="Max option DTE (calendar days)"),
        target_abs_delta: float = typer.Option(0.30, "--target-abs-delta", help="Target |delta| for option leg"),
        max_spread_pct: float = typer.Option(0.30, "--max-spread-pct", help="Prefer spreads <= this"),
        interaction_mode: str = typer.Option(
            "whitelist",
            "--interaction-mode",
            help="none|whitelist|all (whitelist = USD×ticker only; uses fci_usd when --feature-set fci)",
        ),
        whitelist_extra: str = typer.Option(
            "none",
            "--whitelist-extra",
            help="none|macro|funding|rates|vol|commod|fiscal (A/B: add a second whitelist interaction family; use with --interaction-mode whitelist)",
        ),
        explain: bool = typer.Option(False, "--explain", help="Explain which regime features are driving each ticker forecast"),
        explain_top: int = typer.Option(8, "--explain-top", help="Top +/- features to show per ticker"),
        explain_tickers: int = typer.Option(5, "--explain-tickers", help="How many top-ranked tickers to explain (keep output readable)"),
    ):
        """
        Cross-sectional ML model (MVP): predict 63-trading-day forward returns per macro representation ticker.

        Uses:
        - regime feature matrix (macro/funding/usd/rates/vol/commodities)
        - simple ticker state (20d return + 20d realized vol)
        - ticker one-hot to let the model learn persistent differences across instruments
        """
        import pandas as pd

        from ai_options_trader.config import load_settings
        from ai_options_trader.data.market import fetch_equity_daily_closes
        try:
            from ai_options_trader.portfolio.universe import get_universe
        except Exception:  # pragma: no cover
            # Back-compat for environments that haven't picked up the extended universe helper yet.
            from ai_options_trader.portfolio.universe import STARTER_UNIVERSE, DEFAULT_UNIVERSE

            def get_universe(name: str):
                n = (name or "starter").strip().lower()
                if n.startswith("d"):
                    return DEFAULT_UNIVERSE
                return STARTER_UNIVERSE
        from ai_options_trader.regimes.feature_matrix import build_regime_feature_matrix
        from ai_options_trader.regimes.fci import build_fci_feature_matrix
        from ai_options_trader.portfolio.panel import build_macro_panel_dataset
        from ai_options_trader.portfolio.panel_model import fit_latest_with_models
        from ai_options_trader.portfolio.explain import explain_linear_pipeline
        from ai_options_trader.data.alpaca import make_clients, fetch_option_chain, to_candidates
        from ai_options_trader.options.budget_scan import affordable_options_for_ticker, pick_best_affordable

        settings = load_settings()
        console = Console()

        uni = get_universe(basket)
        tickers = list(uni.basket_equity)
        px = fetch_equity_daily_closes(settings=settings, symbols=sorted(set(uni.tradable)), start=start, refresh=bool(refresh)).sort_index().ffill()

        Xr_full = build_regime_feature_matrix(settings=settings, start_date=start, refresh_fred=refresh)
        fs = (feature_set or "full").strip().lower()
        Xr = build_fci_feature_matrix(Xr_full) if fs == "fci" else Xr_full
        Xr = _augment_feature_set_with_whitelist_extra(fs=fs, Xr=Xr, Xr_full=Xr_full, whitelist_extra=whitelist_extra)
        ds = build_macro_panel_dataset(
            regime_features=Xr,
            prices=px,
            tickers=tickers,
            horizon_days=63,
            interaction_mode=interaction_mode,
            whitelist_extra=whitelist_extra,
        )

        preds_all, meta, clf, reg, Xte = fit_latest_with_models(X=ds.X, y=ds.y)
        if meta.get("status") != "ok":
            console.print(Panel(f"Model status: {meta}", title="macro-model", expand=False))
            raise typer.Exit(code=1)

        preds = preds_all[: max(1, int(top))]

        legs: dict[str, dict] = {}
        if with_options and preds:
            _trading, data = make_clients(settings)
            for p in preds:
                want = "call" if (p.exp_return is not None and p.exp_return >= 0) else "put"
                try:
                    chain = fetch_option_chain(data, p.ticker, feed=settings.alpaca_options_feed)
                    candidates = list(to_candidates(chain, p.ticker))
                    opts = affordable_options_for_ticker(
                        candidates,
                        ticker=p.ticker,
                        max_premium_usd=float(max_premium_usd),
                        min_dte_days=int(min_days),
                        max_dte_days=int(max_days),
                        want=want,  # type: ignore[arg-type]
                        price_basis="ask",  # type: ignore[arg-type]
                        min_price=0.05,
                        max_spread_pct=float(max_spread_pct),
                        require_delta=True,
                    )
                    best = pick_best_affordable(opts, target_abs_delta=float(target_abs_delta), max_spread_pct=float(max_spread_pct))
                    if best:
                        legs[p.ticker] = {
                            "symbol": best.symbol,
                            "type": best.opt_type,
                            "expiry": str(best.expiry),
                            "dte_days": int(best.dte_days),
                            "strike": float(best.strike),
                            "premium_usd": float(best.premium_usd),
                            "delta": float(best.delta) if best.delta is not None else None,
                            "iv": float(best.iv) if best.iv is not None else None,
                            "spread_pct": float(best.spread_pct) if best.spread_pct is not None else None,
                        }
                except Exception:
                    continue

        tbl = Table(title="Macro model (63d) — ranked")
        tbl.add_column("Ticker", style="bold")
        tbl.add_column("ProbUp", justify="right")
        tbl.add_column("ExpRet", justify="right")
        tbl.add_column("Expression")

        for p in preds:
            leg = legs.get(p.ticker)
            if leg:
                expr = f"{leg['symbol']} (${leg['premium_usd']:.0f} Δ={leg.get('delta')})"
            else:
                expr = "BUY SHARES" if (p.exp_return is not None and p.exp_return >= 0) else "BUY PUT (n/a under $100)"
            tbl.add_row(
                p.ticker,
                f"{p.prob_up:.3f}" if p.prob_up is not None else "—",
                f"{p.exp_return:+.2f}%" if p.exp_return is not None else "—",
                expr,
            )

        console.print(tbl)
        console.print(Panel(f"Train rows: {meta.get('train_rows')}  Latest cross-section rows: {meta.get('test_rows')}", title="Fit info", expand=False))

        if explain and clf is not None and reg is not None and Xte is not None:
            # Explain the top-N tickers (by predicted exp_return) for readability.
            n_show = max(1, int(explain_tickers))
            to_explain = preds_all[:n_show]

            def _group(feature: str) -> str:
                # Handle interaction columns like "usd_strength_score__x__tkr_UUP"
                if "__x__" in feature:
                    feature = feature.split("__x__", 1)[0]
                for pref, name in [
                    ("fci_", "fci"),
                    ("macro_", "macro"),
                    ("funding_", "funding"),
                    ("usd_", "usd"),
                    ("rates_", "rates"),
                    ("vol_", "vol"),
                    ("commod_", "commod"),
                    ("ticker_", "ticker_state"),
                    ("tkr_", "ticker_id"),
                ]:
                    if feature.startswith(pref):
                        return name
                return "other"

            def _full_contrib(pipe, xrow):
                import numpy as np
                import pandas as pd

                scaler = pipe.named_steps.get("scaler")
                model = pipe.named_steps.get("clf") or pipe.named_steps.get("reg")
                if scaler is None or model is None:
                    return {}
                feature_names = list(xrow.index)
                X1 = pd.DataFrame([xrow.values], columns=feature_names)
                Xs = scaler.transform(X1).reshape(-1)
                coef = getattr(model, "coef_", None)
                if coef is None:
                    return {}
                c = np.array(coef).reshape(-1)
                if len(c) != len(feature_names):
                    return {}
                return {feature_names[i]: float(c[i] * Xs[i]) for i in range(len(feature_names))}

            # Group contribution summary (regressor only; units = predicted return contribution in model space)
            gt = Table(title="Explain (group contributions, Δ vs cross-section mean) — Ridge exp_return drivers", show_lines=True)
            gt.add_column("Ticker", style="bold")
            for g in ("fci", "macro", "funding", "usd", "rates", "vol", "commod", "ticker_state", "ticker_id", "other"):
                gt.add_column(g, justify="right")

            # Compute cross-section mean contribution by group (latest date)
            all_tickers = sorted(set(Xte.index.get_level_values(1)))
            group_sum_mean = {k: 0.0 for k in ("fci", "macro", "funding", "usd", "rates", "vol", "commod", "ticker_state", "ticker_id", "other")}
            if all_tickers:
                tmp = []
                for t in all_tickers:
                    xrow_all = Xte.xs(t, level=1).iloc[0]
                    full_all = _full_contrib(reg, xrow_all)
                    gs = {k: 0.0 for k in group_sum_mean.keys()}
                    for f, c in full_all.items():
                        key = _group(str(f))
                        if key not in gs:
                            key = "other"
                        gs[key] += float(c)
                    tmp.append(gs)
                if tmp:
                    for k in group_sum_mean.keys():
                        group_sum_mean[k] = float(sum(d.get(k, 0.0) for d in tmp) / max(1, len(tmp)))

            detail_panels = []
            for p in to_explain:
                xrow = Xte.xs(p.ticker, level=1).iloc[0]
                exp_reg = explain_linear_pipeline(pipe=reg, x=xrow, top_n=int(explain_top))
                exp_clf = explain_linear_pipeline(pipe=clf, x=xrow, top_n=int(explain_top))

                # Group sums
                group_sum = {k: 0.0 for k in ("fci", "macro", "funding", "usd", "rates", "vol", "commod", "ticker_state", "ticker_id", "other")}
                full = _full_contrib(reg, xrow)
                for f, c in full.items():
                    key = _group(str(f))
                    if key not in group_sum:
                        key = "other"
                    group_sum[key] += float(c)

                # Deltas vs cross-section mean highlight what differs across tickers.
                group_delta = {k: float(group_sum[k] - group_sum_mean.get(k, 0.0)) for k in group_sum.keys()}

                gt.add_row(
                    p.ticker,
                    f"{group_delta['fci']:+.2f}",
                    f"{group_delta['macro']:+.2f}",
                    f"{group_delta['funding']:+.2f}",
                    f"{group_delta['usd']:+.2f}",
                    f"{group_delta['rates']:+.2f}",
                    f"{group_delta['vol']:+.2f}",
                    f"{group_delta['commod']:+.2f}",
                    f"{group_delta['ticker_state']:+.2f}",
                    f"{group_delta['ticker_id']:+.2f}",
                    f"{group_delta['other']:+.2f}",
                )

                # Detailed panels: top features
                def _fmt(lst):
                    lines = []
                    for it in lst or []:
                        lines.append(f"- {it['feature']}: contrib={it['contribution']:+.3f} (x={it['value']})")
                    return "\n".join(lines) if lines else "- (none)"

                detail_panels.append(
                    Panel(
                        f"[b]Regressor (exp_return) top +[/b]\n{_fmt(exp_reg.get('top_positive'))}\n\n"
                        f"[b]Regressor (exp_return) top -[/b]\n{_fmt(exp_reg.get('top_negative'))}\n\n"
                        f"[b]Classifier (logit P(up)) top +[/b]\n{_fmt(exp_clf.get('top_positive'))}\n\n"
                        f"[b]Classifier (logit P(up)) top -[/b]\n{_fmt(exp_clf.get('top_negative'))}\n",
                        title=f"Explain: {p.ticker} (exp_ret={p.exp_return:+.2f}%, prob_up={p.prob_up:.3f})",
                        expand=False,
                    )
                )

            console.print(gt)
            console.print(
                Panel(
                    "Note: regime features (macro/funding/usd/rates/vol/commod) are global on the asof date, so their *absolute* contributions are identical across tickers.\n"
                    "This table shows Δ vs cross-section mean so you can see what actually differentiates tickers (mostly ticker_state + ticker_id, unless you add regime×ticker interactions).\n"
                    "When using --feature-set fci, those features appear under the 'fci' bucket.",
                    title="Interpretation",
                    expand=False,
                )
            )
            for pan in detail_panels:
                console.print(pan)

    @ideas_app.command("macro-model-eval")
    def macro_model_eval(
        start: str = typer.Option("2012-01-01", "--start", help="Start date YYYY-MM-DD"),
        refresh: bool = typer.Option(False, "--refresh", help="Force refresh FRED downloads (regimes)"),
        horizon_days: int = typer.Option(63, "--horizon-days", help="Forward horizon in trading days for the label (prediction target)"),
        purge_days: int = typer.Option(63, "--purge-days", help="Purge window in trading days to prevent label overlap (leakage guard)"),
        step_days: int = typer.Option(5, "--step-days", help="Evaluate every N trading days (keep it fast)"),
        top_k: int = typer.Option(3, "--top-k", help="Top/bottom K for spread metric"),
        basket: str = typer.Option("starter", "--basket", help="starter|extended (universe for evaluation)"),
        sleeve: str = typer.Option("", "--sleeve", help="Optional: evaluate only tickers in a sleeve (macro|vol|ai-bubble|housing)"),
        feature_set: str = typer.Option("full", "--feature-set", help="full|fci (FCI = financial-conditions narrative)"),
        interaction_mode: str = typer.Option(
            "whitelist",
            "--interaction-mode",
            help="none|whitelist|all (whitelist = USD×ticker only; uses fci_usd when --feature-set fci)",
        ),
        whitelist_extra: str = typer.Option(
            "none",
            "--whitelist-extra",
            help="none|macro|funding|rates|vol|commod|fiscal (A/B: add a second whitelist interaction family; use with --interaction-mode whitelist)",
        ),
        book: str = typer.Option("longshort", "--book", help="longshort|longonly (longonly is more realistic for most accounts)"),
        tc_bps: float = typer.Option(5.0, "--tc-bps", help="Transaction cost per side (bps) applied to turnover"),
        nan_report: bool = typer.Option(True, "--nan-report/--no-nan-report", help="Print missingness diagnostics (inputs + dataset)"),
    ):
        """
        Walk-forward evaluation (leak-resistant) for the macro panel model.

        Metrics are cross-sectional and out-of-sample:
        - Spearman(rank(pred_exp_ret), rank(realized_fwd_ret))
        - Hit-rate of sign(pred) vs sign(realized)
        - Top-bottom spread in realized returns
        """
        import pandas as pd

        from ai_options_trader.config import load_settings
        from ai_options_trader.data.market import fetch_equity_daily_closes
        try:
            from ai_options_trader.portfolio.universe import get_universe
        except Exception:  # pragma: no cover
            from ai_options_trader.portfolio.universe import STARTER_UNIVERSE, DEFAULT_UNIVERSE

            def get_universe(name: str):
                n = (name or "starter").strip().lower()
                if n.startswith("d"):
                    return DEFAULT_UNIVERSE
                return STARTER_UNIVERSE
        from ai_options_trader.regimes.feature_matrix import build_regime_feature_matrix
        from ai_options_trader.regimes.fci import build_fci_feature_matrix
        from ai_options_trader.portfolio.panel import build_macro_panel_dataset
        from ai_options_trader.portfolio.panel_eval import walk_forward_panel_eval, walk_forward_panel_portfolio

        settings = load_settings()
        console = Console()

        # Universe: basket (default) or sleeve override.
        uni = get_universe(basket)
        tickers = list(uni.basket_equity)
        if (sleeve or "").strip():
            from ai_options_trader.strategies.sleeves import resolve_sleeves

            cfgs = resolve_sleeves([(sleeve or "").strip()])
            cfg = cfgs[0]
            tickers = list(cfg.universe_fn(basket) if cfg.universe_fn else [])  # type: ignore[misc]
            tickers = [t.strip().upper() for t in tickers if t and t.strip()]
        # Fetch prices for the tickers under evaluation (not the entire basket tradables).
        px = (
            fetch_equity_daily_closes(settings=settings, symbols=sorted(set(tickers)), start=start, refresh=bool(refresh))
            .sort_index()
            .ffill()
        )

        Xr_full = build_regime_feature_matrix(settings=settings, start_date=start, refresh_fred=refresh)
        fs = (feature_set or "full").strip().lower()
        Xr = build_fci_feature_matrix(Xr_full) if fs == "fci" else Xr_full
        Xr = _augment_feature_set_with_whitelist_extra(fs=fs, Xr=Xr, Xr_full=Xr_full, whitelist_extra=whitelist_extra)

        # Missingness diagnostics BEFORE dataset alignment/dropna.
        if bool(nan_report):
            try:
                import numpy as np

                msg = []
                if Xr is None or Xr.empty:
                    msg.append("regimes: empty")
                else:
                    cov = Xr.notna().mean().sort_values()
                    worst = cov.head(10)
                    msg.append(f"regimes: rows={len(Xr):,} cols={len(Xr.columns):,} (worst coverage: {dict(worst.round(3))})")
                if px is None or px.empty:
                    msg.append("prices: empty")
                else:
                    pcov = px.notna().mean().sort_values()
                    worstp = pcov.head(min(10, len(pcov)))
                    msg.append(f"prices: rows={len(px):,} cols={len(px.columns):,} (worst coverage: {dict(worstp.round(3))})")
                console.print(Panel("\n".join(msg), title="NaN coverage (inputs)", expand=False))
            except Exception:
                pass

        ds = build_macro_panel_dataset(
            regime_features=Xr,
            prices=px,
            tickers=tickers,
            horizon_days=int(horizon_days),
            interaction_mode=interaction_mode,
            whitelist_extra=whitelist_extra,
        )

        if bool(nan_report):
            try:
                n_nan_X = int(ds.X.isna().sum().sum()) if not ds.X.empty else 0
                n_nan_y = int(ds.y.isna().sum()) if getattr(ds, "y", None) is not None else 0
                n_rows = int(ds.X.shape[0]) if not ds.X.empty else 0
                n_cols = int(ds.X.shape[1]) if not ds.X.empty else 0
                msg = f"dataset: rows={n_rows:,} cols={n_cols:,} nan_X={n_nan_X:,} nan_y={n_nan_y:,}"
                console.print(Panel(msg, title="NaN coverage (dataset)", expand=False))
            except Exception:
                pass

        # Hard safety: no NaNs should survive in the dataset used for eval.
        if (not ds.X.empty) and bool(ds.X.isna().any().any()):
            raise RuntimeError("Dataset contains NaNs in X after build_macro_panel_dataset (unexpected).")
        if getattr(ds, "y", None) is not None and bool(ds.y.isna().any()):
            raise RuntimeError("Dataset contains NaNs in y after build_macro_panel_dataset (unexpected).")

        # Dataset coverage (helps diagnose "why doesn't --start change anything?")
        ds_date_start = None
        ds_date_end = None
        ds_unique_dates = 0
        ds_unique_tickers = 0
        if not ds.X.empty:
            dates = ds.X.index.get_level_values(0)
            syms = ds.X.index.get_level_values(1)
            ds_unique_dates = int(len(set(dates)))
            ds_unique_tickers = int(len(set(syms)))
            ds_date_start = str(pd.to_datetime(dates.min()).date()) if len(dates) else None
            ds_date_end = str(pd.to_datetime(dates.max()).date()) if len(dates) else None

        res = walk_forward_panel_eval(X=ds.X, y=ds.y, horizon_days=int(purge_days), step_days=int(step_days), top_k=int(top_k))
        port = walk_forward_panel_portfolio(
            X=ds.X,
            y=ds.y,
            horizon_days=int(purge_days),
            step_days=int(step_days),
            top_k=int(top_k),
            tc_bps=float(tc_bps),
            book=book,
        )
        # Stability breakdowns
        book_s = (book or "longshort").strip().lower()
        ret_col = "long_ret_net" if book_s == "longonly" else "ls_ret_net"
        turn_col = "long_turnover" if book_s == "longonly" else "turnover"
        by_decade = port.groupby("decade")[ret_col].mean().to_dict() if not port.empty else {}
        by_stress = port.groupby("stress")[ret_col].mean().to_dict() if not port.empty else {}
        console.print(
            Panel(
                f"status={res.status}\n"
                f"dates_evaluated={res.n_dates}\n"
                f"predictions_scored={res.n_preds}\n"
                f"spearman_mean={res.spearman_mean}\n"
                f"hit_rate_mean={res.hit_rate_mean}\n"
                f"top_bottom_spread_mean={res.top_bottom_spread_mean}\n"
                f"dataset_date_start={ds_date_start}\n"
                f"dataset_date_end={ds_date_end}\n"
                f"dataset_unique_dates={ds_unique_dates}\n"
                f"dataset_unique_tickers={ds_unique_tickers}\n"
                f"sleeve={(sleeve.strip() or None)}\n"
                f"book={book_s}\n"
                f"book_ret_net_mean={float(port[ret_col].mean()) if not port.empty else None}\n"
                f"turnover_mean={float(port[turn_col].mean()) if not port.empty else None}\n"
                f"by_decade_mean_ls_ret_net={by_decade}\n"
                f"by_stress_mean_ls_ret_net={by_stress}\n"
                f"notes={res.notes} horizon={int(horizon_days)}bd",
                title="macro-model-eval (walk-forward, purged)",
                expand=False,
            )
        )

    @ideas_app.command("macro-model-eval-ab")
    def macro_model_eval_ab(
        start: str = typer.Option("2012-01-01", "--start", help="Start date YYYY-MM-DD"),
        refresh: bool = typer.Option(False, "--refresh", help="Force refresh FRED downloads (regimes)"),
        horizon_days: int = typer.Option(63, "--horizon-days", help="Forward horizon in trading days for the label (prediction target)"),
        purge_days: int = typer.Option(63, "--purge-days", help="Purge window in trading days to prevent label overlap (leakage guard)"),
        step_days: int = typer.Option(5, "--step-days", help="Evaluate every N trading days (keep it fast)"),
        top_k: int = typer.Option(3, "--top-k", help="Top/bottom K for spread metric"),
        basket: str = typer.Option("starter", "--basket", help="starter|extended (universe for evaluation)"),
        feature_set: str = typer.Option("fci", "--feature-set", help="full|fci"),
        interaction_mode: str = typer.Option("whitelist", "--interaction-mode", help="Recommended: whitelist (USD×ticker + optional extra)"),
        book: str = typer.Option("longshort", "--book", help="longshort|longonly"),
        tc_bps: float = typer.Option(5.0, "--tc-bps", help="Transaction cost per side (bps) applied to turnover"),
    ):
        """Run macro-model-eval across all whitelist extras and print a comparison table."""
        import pandas as pd
        from ai_options_trader.config import load_settings
        from ai_options_trader.data.market import fetch_equity_daily_closes
        try:
            from ai_options_trader.portfolio.universe import get_universe
        except Exception:  # pragma: no cover
            from ai_options_trader.portfolio.universe import STARTER_UNIVERSE, DEFAULT_UNIVERSE

            def get_universe(name: str):
                n = (name or "starter").strip().lower()
                if n.startswith("d"):
                    return DEFAULT_UNIVERSE
                return STARTER_UNIVERSE
        from ai_options_trader.regimes.feature_matrix import build_regime_feature_matrix
        from ai_options_trader.regimes.fci import build_fci_feature_matrix
        from ai_options_trader.portfolio.panel import build_macro_panel_dataset
        from ai_options_trader.portfolio.panel_eval import walk_forward_panel_eval, walk_forward_panel_portfolio

        settings = load_settings()
        console = Console()

        fs = (feature_set or "fci").strip().lower()
        mode = (interaction_mode or "whitelist").strip().lower()
        if mode != "whitelist":
            console.print(Panel("A/B is intended for --interaction-mode whitelist. Proceeding anyway.", title="Note", expand=False))

        uni = get_universe(basket)
        tickers = list(uni.basket_equity)
        px = fetch_equity_daily_closes(settings=settings, symbols=sorted(set(uni.tradable)), start=start, refresh=bool(refresh)).sort_index().ffill()

        Xr_full = build_regime_feature_matrix(settings=settings, start_date=start, refresh_fred=refresh)
        Xbase = build_fci_feature_matrix(Xr_full) if fs == "fci" else Xr_full

        extras = ["none", "macro", "funding", "rates", "vol", "commod", "fiscal"]
        rows = []
        book_s = (book or "longshort").strip().lower()
        ret_col = "long_ret_net" if book_s == "longonly" else "ls_ret_net"
        turn_col = "long_turnover" if book_s == "longonly" else "turnover"
        for extra in extras:
            Xr = _augment_feature_set_with_whitelist_extra(fs=fs, Xr=Xbase, Xr_full=Xr_full, whitelist_extra=extra)
            ds = build_macro_panel_dataset(
                regime_features=Xr,
                prices=px,
                tickers=tickers,
                horizon_days=int(horizon_days),
                interaction_mode=mode,
                whitelist_extra=extra,
            )
            res = walk_forward_panel_eval(X=ds.X, y=ds.y, horizon_days=int(purge_days), step_days=int(step_days), top_k=int(top_k))
            port = walk_forward_panel_portfolio(
                X=ds.X,
                y=ds.y,
                horizon_days=int(purge_days),
                step_days=int(step_days),
                top_k=int(top_k),
                tc_bps=float(tc_bps),
                book=book_s,
            )
            rows.append(
                {
                    "whitelist_extra": extra,
                    "status": res.status,
                    "dates": res.n_dates,
                    "spearman_mean": res.spearman_mean,
                    "hit_rate_mean": res.hit_rate_mean,
                    "top_bottom_spread_mean": res.top_bottom_spread_mean,
                    "book": book_s,
                    "book_ret_net_mean": float(port[ret_col].mean()) if not port.empty else None,
                    "turnover_mean": float(port[turn_col].mean()) if not port.empty else None,
                }
            )

        df = pd.DataFrame(rows)
        if not df.empty:
            df = df.sort_values(["book_ret_net_mean", "spearman_mean"], ascending=[False, False])
        console.print(Panel(df.to_string(index=False), title="macro-model-eval-ab (whitelist extras)", expand=False))

    @ideas_app.command("macro-model-dataset")
    def macro_model_dataset(
        start: str = typer.Option("2012-01-01", "--start", help="Start date YYYY-MM-DD"),
        refresh: bool = typer.Option(False, "--refresh", help="Force refresh FRED downloads (regimes)"),
        horizon_days: int = typer.Option(63, "--horizon-days", help="Forward horizon in trading days for the label"),
        limit: int = typer.Option(30, "--limit", help="How many rows to print (head)"),
        tail: bool = typer.Option(False, "--tail", help="Print tail rows instead of head"),
        export_csv: str = typer.Option("", "--export-csv", help="Write full dataset (features+label) to this CSV path"),
        export_parquet: str = typer.Option("", "--export-parquet", help="Write full dataset to this parquet path"),
        basket: str = typer.Option("starter", "--basket", help="starter|extended (universe for dataset build)"),
        sleeve: str = typer.Option("", "--sleeve", help="Optional: build dataset only for a sleeve (macro|vol|ai-bubble|housing)"),
        feature_set: str = typer.Option("full", "--feature-set", help="full|fci (FCI = financial-conditions narrative)"),
        interaction_mode: str = typer.Option(
            "whitelist",
            "--interaction-mode",
            help="none|whitelist|all (whitelist = USD×ticker only; uses fci_usd when --feature-set fci)",
        ),
        whitelist_extra: str = typer.Option(
            "none",
            "--whitelist-extra",
            help="none|macro|funding|rates|vol|commod|fiscal (A/B: add a second whitelist interaction family; use with --interaction-mode whitelist)",
        ),
    ):
        """
        Build and inspect the training dataset used by `lox ideas macro-model`.

        Dataset is a panel:
        - rows: (date, ticker)
        - columns: regime features + ticker state + ticker one-hot
        - label: 63-trading-day forward return (%)
        """
        import pandas as pd

        from ai_options_trader.config import load_settings
        from ai_options_trader.data.market import fetch_equity_daily_closes
        try:
            from ai_options_trader.portfolio.universe import get_universe
        except Exception:  # pragma: no cover
            from ai_options_trader.portfolio.universe import STARTER_UNIVERSE, DEFAULT_UNIVERSE

            def get_universe(name: str):
                n = (name or "starter").strip().lower()
                if n.startswith("d"):
                    return DEFAULT_UNIVERSE
                return STARTER_UNIVERSE
        from ai_options_trader.regimes.feature_matrix import build_regime_feature_matrix
        from ai_options_trader.regimes.fci import build_fci_feature_matrix
        from ai_options_trader.portfolio.panel import build_macro_panel_dataset

        settings = load_settings()
        console = Console()

        uni = get_universe(basket)
        tickers = list(uni.basket_equity)
        if (sleeve or "").strip():
            from ai_options_trader.strategies.sleeves import resolve_sleeves

            cfgs = resolve_sleeves([(sleeve or "").strip()])
            cfg = cfgs[0]
            tickers = list(cfg.universe_fn(basket) if cfg.universe_fn else [])  # type: ignore[misc]
            tickers = [t.strip().upper() for t in tickers if t and t.strip()]
        px = (
            fetch_equity_daily_closes(settings=settings, symbols=sorted(set(tickers)), start=start, refresh=bool(refresh))
            .sort_index()
            .ffill()
        )

        Xr_full = build_regime_feature_matrix(settings=settings, start_date=start, refresh_fred=refresh)
        fs = (feature_set or "full").strip().lower()
        Xr = build_fci_feature_matrix(Xr_full) if fs == "fci" else Xr_full
        Xr = _augment_feature_set_with_whitelist_extra(fs=fs, Xr=Xr, Xr_full=Xr_full, whitelist_extra=whitelist_extra)
        ds = build_macro_panel_dataset(
            regime_features=Xr,
            prices=px,
            tickers=tickers,
            horizon_days=int(horizon_days),
            interaction_mode=interaction_mode,
            whitelist_extra=whitelist_extra,
        )

        if ds.X.empty:
            console.print(Panel("Dataset is empty (no rows after alignment/dropna).", title="macro-model-dataset", expand=False))
            raise typer.Exit(code=1)

        # Join label onto feature frame for export/inspection
        Xdf = ds.X.copy()
        y = ds.y.rename("y_fwd_ret").copy()
        joined = Xdf.join(y, how="inner")

        # Summary
        dates = joined.index.get_level_values(0)
        syms = joined.index.get_level_values(1)
        summary = {
            "rows": int(joined.shape[0]),
            "feature_cols": int(ds.X.shape[1]),
            "tickers": int(len(set(syms))),
            "date_start": str(pd.to_datetime(dates.min()).date()) if len(dates) else None,
            "date_end": str(pd.to_datetime(dates.max()).date()) if len(dates) else None,
            "horizon_days": int(horizon_days),
            "basket_equity": tickers,
            "sleeve": (sleeve.strip() or None),
        }
        console.print(Panel(str(summary), title="Dataset summary", expand=False))

        # Print sample rows
        sample = joined.reset_index().rename(columns={"level_0": "date", "level_1": "ticker"})
        sample = sample.sort_values(["date", "ticker"])
        view = sample.tail(int(limit)) if tail else sample.head(int(limit))
        console.print(Panel(view.to_string(index=False), title=("Dataset tail" if tail else "Dataset head"), expand=False))

        # Exports
        if export_csv.strip():
            path = export_csv.strip()
            joined.reset_index().rename(columns={"level_0": "date", "level_1": "ticker"}).to_csv(path, index=False)
            console.print(Panel(f"Wrote CSV: {path}", title="Export", expand=False))
        if export_parquet.strip():
            path = export_parquet.strip()
            joined.reset_index().rename(columns={"level_0": "date", "level_1": "ticker"}).to_parquet(path, index=False)
            console.print(Panel(f"Wrote parquet: {path}", title="Export", expand=False))


