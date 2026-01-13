from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd

from ai_options_trader.config import Settings
from ai_options_trader.strategies.base import CandidateTrade, SleeveConfig, apply_feature_prefix_weights, infer_risk_factors


@dataclass(frozen=True)
class SleeveRun:
    sleeve: SleeveConfig
    candidates: list[CandidateTrade]


def _parse_engine(engine: str) -> str:
    e = (engine or "analog").strip().lower()
    if e not in {"playbook", "analog", "ml"}:
        return "analog"
    return e


def _add_momentum_features(X: pd.DataFrame) -> pd.DataFrame:
    """
    Mirror the existing autopilot analog engine: add factor-momentum deltas for key drivers.
    """
    Xm = X.copy()
    mom_cols = [
        "commod_pressure_score",
        "fiscal_pressure_score",
        "rates_z_ust_10y",
        "rates_z_curve_2s10s",
        "usd_strength_score",
        "vol_pressure_score",
        "funding_tightness_score",
        "macro_disconnect_score",
    ]
    mom_cols = [c for c in mom_cols if c in Xm.columns]
    for w in (20, 60, 120):
        for c in mom_cols:
            Xm[f"{c}_mom{w}"] = pd.to_numeric(Xm[c], errors="coerce") - pd.to_numeric(Xm[c], errors="coerce").shift(int(w))
    return Xm


def run_sleeves_pipeline(
    *,
    settings: Settings,
    sleeves: list[SleeveConfig],
    basket: str,
    engine: str,
    start: str,
    refresh: bool,
    require_positive_score: bool,
    with_options: bool,
    max_premium_usd: float,
    min_days: int,
    max_days: int,
    target_abs_delta: float,
    max_spread_pct: float,
    shares_budget_usd: float,
    predictions_only: bool = False,
    max_candidates_per_sleeve: int = 12,
    data_client: Any | None = None,
) -> tuple[list[SleeveRun], dict[str, Any]]:
    """
    Shared multi-sleeve pipeline:
    - builds regimes + prices once
    - scores per sleeve (playbook/analog)
    - attaches option legs when enabled
    - returns standardized CandidateTrade lists
    """
    e = _parse_engine(engine)

    # 1) Build shared regimes once
    from ai_options_trader.regimes.feature_matrix import build_regime_feature_matrix

    X = build_regime_feature_matrix(settings=settings, start_date=start, refresh_fred=bool(refresh))
    if X is None or X.empty:
        return [], {"status": "empty_regimes"}

    # 2) Resolve per-sleeve universes + union
    sleeve_tickers: dict[str, list[str]] = {}
    all_syms: set[str] = set()
    for s in sleeves:
        uni = s.universe_fn(basket) if s.universe_fn else []
        uni = [t.strip().upper() for t in (uni or []) if t and t.strip()]
        sleeve_tickers[s.name] = uni
        all_syms.update(uni)

    if not all_syms:
        return [], {"status": "empty_universe"}

    # 3) Shared price panel once
    from ai_options_trader.data.market import fetch_equity_daily_closes

    px = fetch_equity_daily_closes(settings=settings, symbols=sorted(all_syms), start=str(start), refresh=False).sort_index().ffill()
    if px is None or px.empty:
        return [], {"status": "empty_prices"}

    asof = min(pd.to_datetime(X.index.max()), pd.to_datetime(px.index.max()))
    asof_ts = pd.to_datetime(asof)
    asof_str = str(asof_ts.date())
    try:
        feat_row = X.loc[asof_ts].to_dict()
    except Exception:
        feat_row = {}

    # Engine transforms
    X_base = X
    if e == "analog":
        X_base = _add_momentum_features(X_base)

    # 4) Per-sleeve scoring (MVP uses shared playbook mechanics; ML integration can be added later)
    out_runs: list[SleeveRun] = []
    today = date.today()
    for s in sleeves:
        tickers = sleeve_tickers.get(s.name, [])
        if not tickers:
            out_runs.append(SleeveRun(sleeve=s, candidates=[]))
            continue

        Xm = apply_feature_prefix_weights(X_base, s.feature_weights_by_prefix)
        # Important: avoid empty outputs due to sparse/missing regime rows.
        # Use forward-fill only (no lookahead). Remaining NaNs become 0.0.
        try:
            Xm = Xm.sort_index()
            for c in Xm.columns:
                Xm[c] = pd.to_numeric(Xm[c], errors="coerce")
            Xm = Xm.ffill().fillna(0.0)
        except Exception:
            pass

        from ai_options_trader.ideas.macro_playbook import rank_macro_playbook

        # Predictions should "always show something" when possible; relax thresholds.
        min_matches = 20 if bool(predictions_only) else 60
        ideas = rank_macro_playbook(
            features=Xm,
            prices=px,
            tickers=list(tickers),
            horizon_days=63,
            k=250,
            lookback_days=365 * 7,
            min_matches=int(min_matches),
            benchmark=("SPY" if bool(predictions_only) else None),
            asof=asof_ts,
        )
        if require_positive_score and (not bool(predictions_only)):
            ideas = [i for i in ideas if i.score > 0]
        ideas = ideas[: max(1, int(max_candidates_per_sleeve))]

        # Attach option legs (best-effort; data entitlement may limit OI/vol)
        legs: dict[str, dict] = {}
        if (not bool(predictions_only)) and with_options and data_client is not None:
            from ai_options_trader.data.alpaca import fetch_option_chain, to_candidates
            from ai_options_trader.options.budget_scan import affordable_options_for_ticker, pick_best_affordable

            for it in ideas[: max(3, int(max_candidates_per_sleeve))]:
                want = "call" if it.direction == "bullish" else "put"
                try:
                    chain = fetch_option_chain(data_client, it.ticker, feed=settings.alpaca_options_feed)
                    cands = list(to_candidates(chain, it.ticker))
                    opts = affordable_options_for_ticker(
                        cands,
                        ticker=it.ticker,
                        max_premium_usd=float(max_premium_usd),
                        min_dte_days=int(min_days),
                        max_dte_days=int(max_days),
                        want=want,  # type: ignore[arg-type]
                        price_basis="ask",  # type: ignore[arg-type]
                        min_price=0.05,
                        max_spread_pct=float(max_spread_pct),
                        require_delta=True,
                        today=today,
                    )
                    best = pick_best_affordable(opts, target_abs_delta=float(target_abs_delta), max_spread_pct=float(max_spread_pct))
                    if best:
                        legs[it.ticker] = {
                            "symbol": best.symbol,
                            "type": best.opt_type,
                            "price": float(best.price),
                            "premium_usd": float(best.premium_usd),
                            "delta": float(best.delta) if best.delta is not None else None,
                        }
                except Exception:
                    continue

        # Standardize as CandidateTrade
        cands_out: list[CandidateTrade] = []
        for it in ideas:
            leg = legs.get(it.ticker)
            und_px = None
            try:
                if it.ticker in px.columns and not px[it.ticker].dropna().empty:
                    und_px = float(px[it.ticker].dropna().iloc[-1])
            except Exception:
                und_px = None

            if bool(predictions_only):
                cands_out.append(
                    CandidateTrade(
                        sleeve=s.name,
                        ticker=it.ticker,
                        action="PREDICT",
                        instrument_type="equity",
                        direction=it.direction,
                        score=float(it.score),
                        expRet=(float(it.exp_return) if it.exp_return is not None else None),
                        prob=(float(it.hit_rate) if it.hit_rate is not None else None),
                        rationale=str(it.notes or "") if it.notes else None,
                        expr=None,
                        est_cost_usd=None,
                        risk_factors=infer_risk_factors(sleeve=s.name, ticker=it.ticker, direction=it.direction),
                        trade_family="expression",
                        probe=False,
                        meta={
                            "asof": asof_str,
                            "regime_features": feat_row,
                            "benchmark": getattr(it, "benchmark", None),
                            "exp_return_excess": getattr(it, "exp_return_excess", None),
                            "hit_rate_excess": getattr(it, "hit_rate_excess", None),
                            "n_matches": getattr(it, "n_matches", None),
                        },
                    )
                )
                continue

            if leg and ("option" in s.allowed_instrument_types):
                cands_out.append(
                    CandidateTrade(
                        sleeve=s.name,
                        ticker=it.ticker,
                        action="OPEN_OPTION",
                        instrument_type="option",
                        direction=it.direction,
                        score=float(it.score),
                        expRet=(float(it.exp_return) if it.exp_return is not None else None),
                        prob=(float(it.hit_rate) if it.hit_rate is not None else None),
                        rationale=str(it.notes or "") if it.notes else None,
                        expr=str(leg["symbol"]),
                        est_cost_usd=float(leg["premium_usd"]),
                        risk_factors=infer_risk_factors(sleeve=s.name, ticker=it.ticker, direction=it.direction),
                        trade_family="expression",
                        probe=False,
                        meta={"asof": asof_str, "regime_features": feat_row, "option_leg": dict(leg)},
                    )
                )
                continue

            # Shares fallback: 1-3 shares depending on shares_budget
            qty = 1
            est = None
            if und_px is not None and und_px > 0:
                qty = max(1, int(float(shares_budget_usd) // float(und_px)))
                est = float(qty) * float(und_px)
            cands_out.append(
                CandidateTrade(
                    sleeve=s.name,
                    ticker=it.ticker,
                    action="OPEN_SHARES",
                    instrument_type="equity",
                    direction=it.direction,
                    score=float(it.score),
                    expRet=(float(it.exp_return) if it.exp_return is not None else None),
                    prob=(float(it.hit_rate) if it.hit_rate is not None else None),
                    rationale=str(it.notes or "") if it.notes else None,
                    expr=f"qty={qty}" + (f" limit≈{und_px:.2f}" if und_px is not None else ""),
                    est_cost_usd=est,
                    risk_factors=infer_risk_factors(sleeve=s.name, ticker=it.ticker, direction=it.direction),
                    trade_family="expression",
                    probe=False,
                    meta={"asof": asof_str, "regime_features": feat_row, "qty": qty, "limit": und_px},
                )
            )

        out_runs.append(SleeveRun(sleeve=s, candidates=cands_out))

    meta = {
        "status": "ok",
        "asof": asof_str,
        "asof_ts": asof_ts,
        "regime_features": feat_row,
        "engine": e,
        "basket": basket,
        "symbols_union": sorted(all_syms),
        "sleeves": [s.name for s in sleeves],
    }
    return out_runs, meta

