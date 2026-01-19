"""Idea generation for autopilot."""
from __future__ import annotations

import pandas as pd

from ai_options_trader.autopilot.utils import to_float


def generate_ideas(
    *,
    engine: str,
    prices,  # DataFrame
    regime_features,  # DataFrame
    symbols: list[str],
    asof,  # Timestamp
    require_positive_score: bool = True,
    feature_set: str = "fci",
    interaction_mode: str = "whitelist",
    whitelist_extra: str = "none",
) -> list[dict]:
    """
    Generate trade ideas using playbook, analog, or ML engine.
    
    Args:
        engine: "playbook", "analog", or "ml"
        prices: Price DataFrame
        regime_features: Regime feature DataFrame  
        symbols: List of tickers
        asof: As-of timestamp
        require_positive_score: Filter to positive scores only
        feature_set: "full" or "fci" (ML mode)
        interaction_mode: Interaction mode for ML
        whitelist_extra: Extra whitelist for ML
    
    Returns:
        List of candidate dicts sorted by score
    """
    mode = (engine or "analog").strip().lower()
    if mode not in {"playbook", "analog", "ml"}:
        mode = "analog"
    
    candidates: list[dict] = []
    
    if mode == "ml":
        candidates = _generate_ml_ideas(
            prices=prices,
            regime_features=regime_features,
            symbols=symbols,
            feature_set=feature_set,
            interaction_mode=interaction_mode,
            whitelist_extra=whitelist_extra,
        )
    else:
        candidates = _generate_playbook_ideas(
            prices=prices,
            regime_features=regime_features,
            symbols=symbols,
            asof=asof,
            use_analog=(mode == "analog"),
            require_positive_score=require_positive_score,
        )
    
    candidates.sort(key=lambda d: float(d.get("score") or -1e9), reverse=True)
    return candidates


def _generate_ml_ideas(
    *,
    prices,
    regime_features,
    symbols: list[str],
    feature_set: str,
    interaction_mode: str,
    whitelist_extra: str,
) -> list[dict]:
    """Generate ideas using ML panel model."""
    from ai_options_trader.regimes.fci import build_fci_feature_matrix
    from ai_options_trader.portfolio.panel import build_macro_panel_dataset
    from ai_options_trader.portfolio.panel_model import fit_latest_with_models
    
    X = regime_features
    fs = (feature_set or "fci").strip().lower()
    Xr = build_fci_feature_matrix(X) if fs == "fci" else X
    
    # Add extra features if requested
    extra = (whitelist_extra or "none").strip().lower()
    if fs == "fci" and extra in {"fiscal", "commod", "macro"}:
        cols = []
        if extra == "fiscal" and "fiscal_pressure_score" in X.columns:
            cols = ["fiscal_pressure_score"]
        elif extra == "commod" and "commod_pressure_score" in X.columns:
            cols = ["commod_pressure_score"]
        elif extra == "macro" and "macro_disconnect_score" in X.columns:
            cols = ["macro_disconnect_score"]
        if cols:
            Xr = Xr.join(X[cols], how="left")
    
    ds = build_macro_panel_dataset(
        regime_features=Xr,
        prices=prices,
        tickers=list(symbols),
        horizon_days=63,
        interaction_mode=(interaction_mode or "whitelist").strip().lower(),
        whitelist_extra=whitelist_extra,
    )
    
    preds, meta, _clf, _reg, _Xte = fit_latest_with_models(X=ds.X, y=ds.y)
    
    if meta.get("status") != "ok":
        return []
    
    candidates = []
    for p in preds:
        exp_ret = to_float(p.exp_return)
        if exp_ret is None:
            continue
        
        direction = "bullish" if exp_ret >= 0 else "bearish"
        prob_up = to_float(p.prob_up) or 0.5
        score = abs(exp_ret) * (0.5 + abs(prob_up - 0.5))
        
        candidates.append({
            "source": "ml",
            "ticker": p.ticker,
            "direction": direction,
            "horizon_days": 63,
            "exp_return_pred": exp_ret,
            "prob_up_pred": prob_up,
            "score": float(score),
        })
    
    return candidates


def _generate_playbook_ideas(
    *,
    prices,
    regime_features,
    symbols: list[str],
    asof,
    use_analog: bool,
    require_positive_score: bool,
) -> list[dict]:
    """Generate ideas using kNN playbook."""
    from ai_options_trader.ideas.macro_playbook import rank_macro_playbook
    
    X = regime_features
    Xm = X.copy() if use_analog else X
    
    # Add momentum features for analog mode
    if use_analog:
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
                Xm[f"{c}_mom{w}"] = (
                    pd.to_numeric(Xm[c], errors="coerce") - 
                    pd.to_numeric(Xm[c], errors="coerce").shift(int(w))
                )
    
    ideas = rank_macro_playbook(
        features=Xm,
        prices=prices,
        tickers=list(symbols),
        horizon_days=63,
        k=250,
        lookback_days=365 * 7,
        min_matches=60,
        asof=asof,
    )
    
    if require_positive_score:
        ideas = [i for i in ideas if i.score > 0]
    
    candidates = []
    for it in ideas:
        candidates.append({
            "source": "analog" if use_analog else "playbook",
            "ticker": it.ticker,
            "direction": it.direction,
            "horizon_days": it.horizon_days,
            "n_matches": it.n_matches,
            "exp_return": it.exp_return,
            "median_return": it.median_return,
            "hit_rate": it.hit_rate,
            "worst": it.worst,
            "best": it.best,
            "score": it.score,
            "notes": it.notes,
        })
    
    return candidates


def apply_thesis_reweighting(
    candidates: list[dict],
    thesis: str,
) -> list[dict]:
    """
    Reweight candidates based on macro thesis.
    
    Args:
        candidates: List of candidate dicts
        thesis: "none" or "inflation_fiscal"
    
    Returns:
        Reweighted candidates (sorted by new score)
    """
    thesis_s = (thesis or "none").strip().lower()
    if thesis_s == "none" or not candidates:
        return candidates
    
    for c in candidates:
        tkr = str(c.get("ticker") or "")
        tag, weight = _thesis_tag_weight(tkr, thesis_s)
        
        base = c.get("score")
        try:
            base_f = float(base) if base is not None else 0.0
        except Exception:
            base_f = 0.0
        
        c["score_raw"] = base_f
        c["thesis"] = thesis_s
        c["thesis_tag"] = tag
        c["thesis_weight"] = float(weight)
        c["score"] = float(base_f) * float(weight)
        
        # Thesis directional overrides
        if thesis_s == "inflation_fiscal" and tkr.upper() in {"HYG", "LQD"}:
            c["direction"] = "bearish"
            c["exposure"] = "bearish"
            c["thesis_override"] = "credit_bearish"
    
    candidates.sort(key=lambda d: float(d.get("score") or -1e9), reverse=True)
    return candidates


def _thesis_tag_weight(ticker: str, thesis: str) -> tuple[str, float]:
    """Get thesis tag and weight for a ticker."""
    t = (ticker or "").strip().upper()
    
    if thesis == "inflation_fiscal":
        # Inflation persistence (real assets + inflation-linked)
        inflation = {
            "GLDM", "GLD", "SLV", "GDX", "DBC", 
            "USO", "CPER", "XLE", "TIP",
        }
        # Fiscal wall / borrowing stress
        fiscal_wall = {
            "TBT", "TBF", "TMV", "SH", "PSQ", "SDS",
            "SQQQ", "SPXU", "SJB", "UUP", "VIXY", "KRE",
        }
        credit = {"HYG", "LQD"}
        
        if t in inflation:
            return "inflation", 1.35
        if t in credit:
            return "credit_stress", 1.25
        if t in fiscal_wall:
            return "fiscal_wall", 1.25
    
    return "neutral", 1.0
