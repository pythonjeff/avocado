from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import roc_auc_score
from sklearn.metrics import (
    accuracy_score,
    brier_score_loss,
    confusion_matrix,
    log_loss,
    mean_absolute_error,
    mean_squared_error,
    r2_score,
)
from sklearn.model_selection import TimeSeriesSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


Horizon = Literal["3m", "6m", "12m"]


@dataclass(frozen=True)
class HorizonForecast:
    horizon: Horizon
    prob_up: float | None
    exp_return: float | None
    auc_cv: float | None


def _make_classifier() -> Pipeline:
    return Pipeline(
        steps=[
            ("scaler", StandardScaler()),
            ("clf", LogisticRegression(max_iter=2000, solver="lbfgs")),
        ]
    )


def _make_regressor() -> Pipeline:
    return Pipeline(
        steps=[
            ("scaler", StandardScaler()),
            ("reg", Ridge(alpha=5.0)),
        ]
    )


def _cv_auc(model: Pipeline, X: pd.DataFrame, y: pd.Series, splits: int = 5) -> float | None:
    yb = (y > 0.0).astype(int)
    # Need both classes present
    if yb.nunique() < 2 or len(yb) < 200:
        return None
    tscv = TimeSeriesSplit(n_splits=splits)
    aucs: list[float] = []
    for train_idx, test_idx in tscv.split(X):
        Xtr, Xte = X.iloc[train_idx], X.iloc[test_idx]
        ytr, yte = yb.iloc[train_idx], yb.iloc[test_idx]
        if ytr.nunique() < 2 or yte.nunique() < 2:
            continue
        m = _make_classifier()
        m.fit(Xtr, ytr)
        p = m.predict_proba(Xte)[:, 1]
        try:
            aucs.append(float(roc_auc_score(yte, p)))
        except Exception:
            continue
    if not aucs:
        return None
    return float(np.mean(aucs))


def fit_and_forecast(
    *,
    X: pd.DataFrame,
    y: pd.Series,
) -> tuple[float | None, float | None, float | None]:
    """
    Fit on all available history and predict for the latest feature row.
    Returns (prob_up, exp_return, auc_cv).
    """
    if X.empty or y.empty:
        return None, None, None

    # Align and drop NaNs
    idx = X.index.intersection(y.index)
    X2 = X.loc[idx].copy()
    y2 = y.loc[idx].copy()
    X2 = X2.replace([np.inf, -np.inf], np.nan)
    y2 = y2.replace([np.inf, -np.inf], np.nan)
    keep = X2.dropna().index.intersection(y2.dropna().index)
    X2 = X2.loc[keep]
    y2 = y2.loc[keep]
    if len(X2) < 250:
        return None, None, None

    auc = _cv_auc(_make_classifier(), X2, y2)

    # Final fit
    yb = (y2 > 0.0).astype(int)
    clf = _make_classifier()
    reg = _make_regressor()
    clf.fit(X2, yb)
    reg.fit(X2, y2)

    x_last = X.iloc[[-1]]
    x_last = x_last.replace([np.inf, -np.inf], np.nan)
    if x_last.isna().any(axis=1).iloc[0]:
        return None, None, auc

    prob_up = float(clf.predict_proba(x_last)[:, 1][0])
    exp_ret = float(reg.predict(x_last)[0])
    return prob_up, exp_ret, auc


def build_forecasts(X: pd.DataFrame, y_df: pd.DataFrame) -> list[HorizonForecast]:
    out: list[HorizonForecast] = []
    for h, col in [("3m", "fwd_ret_3m"), ("6m", "fwd_ret_6m"), ("12m", "fwd_ret_12m")]:
        p, r, auc = fit_and_forecast(X=X, y=y_df[col])
        out.append(HorizonForecast(horizon=h, prob_up=p, exp_return=r, auc_cv=auc))
    return out


def _extract_linear_coefs(pipe: Pipeline, feature_names: list[str]) -> dict[str, float] | None:
    """
    Extract coefficients from a linear model inside a pipeline. Returns mapping feature->coef.
    Coefs are in the standardized feature space (after StandardScaler).
    """
    try:
        model = pipe.named_steps.get("clf") or pipe.named_steps.get("reg")
        coef = getattr(model, "coef_", None)
        if coef is None:
            return None
        arr = np.array(coef).reshape(-1)
        if len(arr) != len(feature_names):
            return None
        return {feature_names[i]: float(arr[i]) for i in range(len(feature_names))}
    except Exception:
        return None


def fit_models_for_debug(
    *,
    X: pd.DataFrame,
    y: pd.Series,
) -> tuple[Pipeline | None, Pipeline | None, float | None]:
    """
    Fit classifier/regressor on all available history (aligned) and return fitted models + auc_cv.
    """
    if X.empty or y.empty:
        return None, None, None

    idx = X.index.intersection(y.index)
    X2 = X.loc[idx].copy()
    y2 = y.loc[idx].copy()
    X2 = X2.replace([np.inf, -np.inf], np.nan)
    y2 = y2.replace([np.inf, -np.inf], np.nan)
    keep = X2.dropna().index.intersection(y2.dropna().index)
    X2 = X2.loc[keep]
    y2 = y2.loc[keep]
    if len(X2) < 250:
        return None, None, None

    auc = _cv_auc(_make_classifier(), X2, y2)

    yb = (y2 > 0.0).astype(int)
    clf = _make_classifier()
    reg = _make_regressor()
    clf.fit(X2, yb)
    reg.fit(X2, y2)
    return clf, reg, auc


def model_debug_report(
    *,
    X: pd.DataFrame,
    y_df: pd.DataFrame,
    top_n: int = 12,
) -> dict[str, dict[str, object]]:
    """
    Return per-horizon debug info:
    - auc_cv (classifier)
    - top positive/negative coefficients for classifier and regressor
    """
    feature_names = list(X.columns)
    out: dict[str, dict[str, object]] = {}

    for h, col in [("3m", "fwd_ret_3m"), ("6m", "fwd_ret_6m"), ("12m", "fwd_ret_12m")]:
        clf, reg, auc = fit_models_for_debug(X=X, y=y_df[col])
        if clf is None or reg is None:
            out[h] = {"auc_cv": auc, "status": "insufficient_data"}
            continue

        clf_coefs = _extract_linear_coefs(clf, feature_names) or {}
        reg_coefs = _extract_linear_coefs(reg, feature_names) or {}

        def top_pairs(d: dict[str, float]) -> dict[str, list[tuple[str, float]]]:
            items = sorted(d.items(), key=lambda kv: kv[1])
            neg = items[:top_n]
            pos = items[-top_n:][::-1]
            return {"top_positive": pos, "top_negative": neg}

        out[h] = {
            "auc_cv": auc,
            "classifier": top_pairs(clf_coefs),
            "regressor": top_pairs(reg_coefs),
            "status": "ok",
        }

    return out


def walk_forward_evaluation(
    *,
    X: pd.DataFrame,
    y: pd.Series,
    splits: int = 6,
    prob_threshold: float = 0.50,
) -> dict[str, object]:
    """
    Walk-forward evaluation for one horizon.

    Outputs:
    - classification: AUC, logloss, brier, accuracy, confusion matrix
    - regression: MAE, RMSE, R2

    IMPORTANT:
    - This evaluates out-of-sample folds (time-series split).
    - Labels are forward returns; folds contain overlapping horizons, so treat metrics as directional/diagnostic.
    """
    if X.empty or y.empty:
        return {"status": "empty"}

    idx = X.index.intersection(y.index)
    X2 = X.loc[idx].copy().replace([np.inf, -np.inf], np.nan)
    y2 = y.loc[idx].copy().replace([np.inf, -np.inf], np.nan)
    keep = X2.dropna().index.intersection(y2.dropna().index)
    X2 = X2.loc[keep]
    y2 = y2.loc[keep]

    if len(X2) < 400:
        return {"status": "insufficient_data", "n": int(len(X2))}

    yb = (y2 > 0.0).astype(int)
    if yb.nunique() < 2:
        return {"status": "single_class", "n": int(len(X2))}

    tscv = TimeSeriesSplit(n_splits=int(splits))

    p_all: list[float] = []
    yb_all: list[int] = []
    yhat_all: list[float] = []
    y_all: list[float] = []

    fold_aucs: list[float] = []

    for train_idx, test_idx in tscv.split(X2):
        Xtr, Xte = X2.iloc[train_idx], X2.iloc[test_idx]
        ytr_b, yte_b = yb.iloc[train_idx], yb.iloc[test_idx]
        ytr, yte = y2.iloc[train_idx], y2.iloc[test_idx]

        # Need both classes in fold to compute AUC/logloss meaningfully
        if ytr_b.nunique() < 2 or yte_b.nunique() < 2:
            continue

        clf = _make_classifier()
        reg = _make_regressor()
        clf.fit(Xtr, ytr_b)
        reg.fit(Xtr, ytr)

        p = clf.predict_proba(Xte)[:, 1]
        yhat = reg.predict(Xte)

        p_all.extend([float(x) for x in p])
        yb_all.extend([int(x) for x in yte_b.values])
        yhat_all.extend([float(x) for x in yhat])
        y_all.extend([float(x) for x in yte.values])

        try:
            fold_aucs.append(float(roc_auc_score(yte_b, p)))
        except Exception:
            pass

    if not p_all:
        return {"status": "no_valid_folds", "n": int(len(X2))}

    # Classification metrics
    auc = float(roc_auc_score(yb_all, p_all)) if len(set(yb_all)) > 1 else None
    try:
        ll = float(log_loss(yb_all, p_all, labels=[0, 1]))
    except Exception:
        ll = None
    try:
        brier = float(brier_score_loss(yb_all, p_all))
    except Exception:
        brier = None

    pred = [1 if p >= float(prob_threshold) else 0 for p in p_all]
    acc = float(accuracy_score(yb_all, pred))
    cm = confusion_matrix(yb_all, pred, labels=[0, 1]).tolist()

    # Regression metrics
    mae = float(mean_absolute_error(y_all, yhat_all))
    # Some sklearn versions don't support squared=... in mean_squared_error.
    # Compute RMSE portably: sqrt(MSE).
    rmse = float(np.sqrt(mean_squared_error(y_all, yhat_all)))
    r2 = float(r2_score(y_all, yhat_all))

    return {
        "status": "ok",
        "n": int(len(X2)),
        "splits": int(splits),
        "prob_threshold": float(prob_threshold),
        "classification": {
            "auc": auc,
            "auc_folds_mean": (float(np.mean(fold_aucs)) if fold_aucs else None),
            "auc_folds": fold_aucs,
            "logloss": ll,
            "brier": brier,
            "accuracy": acc,
            "confusion_matrix": cm,  # [[tn, fp],[fn,tp]]
        },
        "regression": {
            "mae": mae,
            "rmse": rmse,
            "r2": r2,
        },
    }


