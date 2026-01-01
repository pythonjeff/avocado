from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
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
HORIZON_TO_DAYS: dict[Horizon, int] = {"3m": 63, "6m": 126, "12m": 252}


@dataclass(frozen=True)
class HorizonForecast:
    horizon: Horizon
    prob_up: float | None  # calibrated when available
    prob_up_raw: float | None
    exp_return: float | None
    auc_cv: float | None
    notes: str = ""


def _make_classifier() -> Pipeline:
    return Pipeline(
        steps=[
            ("scaler", StandardScaler()),
            ("clf", LogisticRegression(max_iter=2000, solver="lbfgs", random_state=42)),
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


def _purge_train_indices(train_idx: np.ndarray, test_idx: np.ndarray, purge_n: int) -> np.ndarray:
    """
    Purge the last `purge_n` rows of the training window to prevent overlap between
    train labels (which look forward) and the test window.

    This is a simplified "purged" time-series split (Lopez de Prado style).
    """
    if purge_n <= 0 or len(train_idx) == 0 or len(test_idx) == 0:
        return train_idx
    test_start = int(np.min(test_idx))
    cutoff = test_start - int(purge_n)
    return train_idx[train_idx < cutoff]


def _split_train_cal(train_idx: np.ndarray, cal_frac: float = 0.2, min_cal: int = 200) -> tuple[np.ndarray, np.ndarray]:
    """
    Chronologically split `train_idx` into (fit_idx, cal_idx) where cal_idx is the last chunk.
    """
    n = len(train_idx)
    if n <= min_cal + 50:
        return train_idx, np.array([], dtype=int)
    cal_n = max(int(n * cal_frac), int(min_cal))
    cal_n = min(cal_n, n // 2)  # don't let calibration dominate
    fit = train_idx[: n - cal_n]
    cal = train_idx[n - cal_n :]
    return fit, cal


def _safe_logloss(y_true: list[int], p: list[float]) -> float | None:
    try:
        return float(log_loss(y_true, p, labels=[0, 1]))
    except Exception:
        return None


def _safe_brier(y_true: list[int], p: list[float]) -> float | None:
    try:
        return float(brier_score_loss(y_true, p))
    except Exception:
        return None


def _calibrate_prefit(
    clf: Pipeline,
    X_cal: pd.DataFrame,
    y_cal: pd.Series,
    method: str = "sigmoid",
) -> Pipeline:
    """
    Calibrate a prefit classifier using a calibration set (time-series safe if caller purges properly).
    Returns a CalibratedClassifierCV wrapper.
    """
    cal = CalibratedClassifierCV(estimator=clf, method=method, cv="prefit")
    cal.fit(X_cal, y_cal)
    return cal  # type: ignore[return-value]


def _cv_auc_purged(
    X: pd.DataFrame,
    y: pd.Series,
    *,
    splits: int,
    purge_n: int,
) -> float | None:
    yb = (y > 0.0).astype(int)
    if yb.nunique() < 2 or len(yb) < 400:
        return None
    tscv = TimeSeriesSplit(n_splits=int(splits))
    aucs: list[float] = []
    for train_idx, test_idx in tscv.split(X):
        train_idx = _purge_train_indices(train_idx, test_idx, purge_n)
        if len(train_idx) < 200 or len(test_idx) < 50:
            continue
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

    # For diagnostic AUC, use a purged CV to avoid label overlap leakage.
    # We infer purge horizon from series name if possible; callers that care about horizon
    # should use `fit_and_forecast_for_horizon`.
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


def fit_and_forecast_for_horizon(
    *,
    X: pd.DataFrame,
    y: pd.Series,
    horizon: Horizon,
    calibrate: bool = True,
    calibration_method: str = "sigmoid",
    cal_frac: float = 0.2,
    min_cal: int = 200,
) -> tuple[float | None, float | None, float | None, float | None]:
    """
    Fit on all available *labeled* history for a given horizon, optionally calibrate probabilities,
    then predict for the latest feature row.

    Returns (prob_cal, prob_raw, exp_return, auc_cv_purged).
    """
    if X.empty or y.empty:
        return None, None, None, None

    idx = X.index.intersection(y.index)
    X2 = X.loc[idx].copy().replace([np.inf, -np.inf], np.nan)
    y2 = y.loc[idx].copy().replace([np.inf, -np.inf], np.nan)
    keep = X2.dropna().index.intersection(y2.dropna().index)
    X2 = X2.loc[keep]
    y2 = y2.loc[keep]
    if len(X2) < 400:
        return None, None, None, None

    purge_n = int(HORIZON_TO_DAYS[horizon])
    auc = _cv_auc_purged(X2, y2, splits=6, purge_n=purge_n)

    # Fit on labeled set, calibrate on tail chunk (still fully in-sample but time-respecting).
    yb = (y2 > 0.0).astype(int)
    n = len(X2)
    cal_n = max(int(n * float(cal_frac)), int(min_cal))
    cal_n = min(cal_n, n // 2)
    fit_end = max(0, n - cal_n)
    X_fit, y_fit = X2.iloc[:fit_end], yb.iloc[:fit_end]
    X_cal, y_cal = X2.iloc[fit_end:], yb.iloc[fit_end:]

    clf = _make_classifier()
    reg = _make_regressor()
    clf.fit(X2, yb)  # raw classifier fit on all labeled history
    reg.fit(X2, y2)

    # Predict current
    x_last = X.iloc[[-1]].replace([np.inf, -np.inf], np.nan)
    if x_last.isna().any(axis=1).iloc[0]:
        return None, None, None, auc

    prob_raw = float(clf.predict_proba(x_last)[:, 1][0])
    exp_ret = float(reg.predict(x_last)[0])

    prob_cal = None
    if calibrate and len(X_fit) > 200 and y_fit.nunique() == 2 and len(X_cal) > 50 and y_cal.nunique() == 2:
        # Calibrate a classifier fit only on the fit split, to avoid calibrating a model on data it was trained on.
        clf_fit = _make_classifier()
        clf_fit.fit(X_fit, y_fit)
        cal = _calibrate_prefit(clf_fit, X_cal, y_cal, method=calibration_method)
        prob_cal = float(cal.predict_proba(x_last)[:, 1][0])

    return prob_cal, prob_raw, exp_ret, auc


def build_forecasts(
    X: pd.DataFrame,
    y_df: pd.DataFrame,
    *,
    calibrate: bool = True,
    calibration_method: str = "sigmoid",
) -> list[HorizonForecast]:
    out: list[HorizonForecast] = []
    for h, col in [("3m", "fwd_ret_3m"), ("6m", "fwd_ret_6m"), ("12m", "fwd_ret_12m")]:
        p_cal, p_raw, r, auc = fit_and_forecast_for_horizon(
            X=X,
            y=y_df[col],
            horizon=h,  # type: ignore[arg-type]
            calibrate=calibrate,
            calibration_method=calibration_method,
        )
        out.append(
            HorizonForecast(
                horizon=h,  # type: ignore[arg-type]
                prob_up=(p_cal if p_cal is not None else p_raw),
                prob_up_raw=p_raw,
                exp_return=r,
                auc_cv=auc,
                notes=("calibrated" if p_cal is not None else "raw"),
            )
        )
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

    # Use purged CV for diagnostics to avoid label overlap leakage.
    # Default to 12m purge when unknown; this avoids the most severe leakage.
    auc = _cv_auc_purged(X2, y2, splits=6, purge_n=HORIZON_TO_DAYS["12m"])

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
    purge_n: int = 0,
    calibrate: bool = True,
    calibration_method: str = "sigmoid",
    cal_frac: float = 0.2,
    min_cal: int = 200,
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
    p_cal_all: list[float] = []
    p_base_all: list[float] = []
    yb_all: list[int] = []
    yhat_all: list[float] = []
    y_all: list[float] = []

    fold_aucs: list[float] = []
    fold_aucs_cal: list[float] = []
    valid_folds = 0

    for train_idx, test_idx in tscv.split(X2):
        train_idx = _purge_train_indices(train_idx, test_idx, int(purge_n))
        if len(train_idx) < 200 or len(test_idx) < 50:
            continue
        Xtr, Xte = X2.iloc[train_idx], X2.iloc[test_idx]
        ytr_b, yte_b = yb.iloc[train_idx], yb.iloc[test_idx]
        ytr, yte = y2.iloc[train_idx], y2.iloc[test_idx]

        # Need both classes in fold to compute AUC/logloss meaningfully
        if ytr_b.nunique() < 2 or yte_b.nunique() < 2:
            continue
        valid_folds += 1

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

        # Baseline: constant probability equal to train positive rate
        base_p = float(np.mean(ytr_b))
        p_base_all.extend([base_p for _ in range(len(test_idx))])

        # Calibrated probabilities (time-series safe):
        # calibrate using the tail of training window (still purged away from test).
        if calibrate:
            fit_idx, cal_idx = _split_train_cal(train_idx, cal_frac=float(cal_frac), min_cal=int(min_cal))
            if len(cal_idx) > 50:
                X_fit, y_fit = X2.iloc[fit_idx], yb.iloc[fit_idx]
                X_cal, y_cal = X2.iloc[cal_idx], yb.iloc[cal_idx]
                if y_fit.nunique() == 2 and y_cal.nunique() == 2:
                    clf_fit = _make_classifier()
                    clf_fit.fit(X_fit, y_fit)
                    cal = _calibrate_prefit(clf_fit, X_cal, y_cal, method=calibration_method)
                    p_cal = cal.predict_proba(Xte)[:, 1]
                    p_cal_all.extend([float(x) for x in p_cal])
                    try:
                        fold_aucs_cal.append(float(roc_auc_score(yte_b, p_cal)))
                    except Exception:
                        pass

        try:
            fold_aucs.append(float(roc_auc_score(yte_b, p)))
        except Exception:
            pass

    if not p_all:
        return {"status": "no_valid_folds", "n": int(len(X2))}

    # Classification metrics (raw)
    auc = float(roc_auc_score(yb_all, p_all)) if len(set(yb_all)) > 1 else None
    ll = _safe_logloss(yb_all, p_all)
    brier = _safe_brier(yb_all, p_all)

    # Classification metrics (baseline)
    auc_base = float(roc_auc_score(yb_all, p_base_all)) if len(set(yb_all)) > 1 else None
    ll_base = _safe_logloss(yb_all, p_base_all)
    brier_base = _safe_brier(yb_all, p_base_all)

    # Classification metrics (calibrated) – may be missing if calibration couldn't run on folds
    has_cal = len(p_cal_all) == len(p_all) and len(p_cal_all) > 0
    auc_cal = (float(roc_auc_score(yb_all, p_cal_all)) if has_cal and len(set(yb_all)) > 1 else None)
    ll_cal = (_safe_logloss(yb_all, p_cal_all) if has_cal else None)
    brier_cal = (_safe_brier(yb_all, p_cal_all) if has_cal else None)

    pred = [1 if p >= float(prob_threshold) else 0 for p in p_all]
    acc = float(accuracy_score(yb_all, pred))
    cm = confusion_matrix(yb_all, pred, labels=[0, 1]).tolist()

    pos_rate = float(np.mean(yb_all)) if yb_all else 0.0
    p_mean = float(np.mean(p_all)) if p_all else None
    p_std = float(np.std(p_all)) if p_all else None
    p_min = float(np.min(p_all)) if p_all else None
    p_max = float(np.max(p_all)) if p_all else None
    p_cal_mean = float(np.mean(p_cal_all)) if has_cal else None
    p_cal_std = float(np.std(p_cal_all)) if has_cal else None

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
        "purge_n": int(purge_n),
        "calibrated": bool(has_cal),
        "prob_threshold": float(prob_threshold),
        "classification": {
            "auc": auc,
            "auc_folds_mean": (float(np.mean(fold_aucs)) if fold_aucs else None),
            "auc_folds": fold_aucs,
            "auc_cal": auc_cal,
            "auc_cal_folds_mean": (float(np.mean(fold_aucs_cal)) if fold_aucs_cal else None),
            "auc_cal_folds": fold_aucs_cal,
            "valid_folds": int(valid_folds),
            "pos_rate": pos_rate,
            "prob_mean": p_mean,
            "prob_std": p_std,
            "prob_min": p_min,
            "prob_max": p_max,
            "prob_cal_mean": p_cal_mean,
            "prob_cal_std": p_cal_std,
            "logloss": ll,
            "brier": brier,
            "baseline_logloss": ll_base,
            "baseline_brier": brier_base,
            "baseline_auc": auc_base,
            "logloss_cal": ll_cal,
            "brier_cal": brier_cal,
            "accuracy": acc,
            "confusion_matrix": cm,  # [[tn, fp],[fn,tp]]
        },
        "regression": {
            "mae": mae,
            "rmse": rmse,
            "r2": r2,
        },
    }


