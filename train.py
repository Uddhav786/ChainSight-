"""Step 2: train the predictive models on a time based split and save them.

    python train.py
Models
  * delivery days: three quantile regressors (P10, P50, P90)
  * SLA breach: gradient boosted classifier + isotonic calibration on the validation period
Uses LightGBM when it installs on s390x, otherwise scikit-learn HistGradientBoosting (same idea).
"""
import json
import os
import time

import joblib
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import average_precision_score, brier_score_loss, mean_absolute_error, roc_auc_score

from config import ART_DIR, ORDERS_PKL, TRAIN_FRAC, VAL_FRAC
from features import CAT_COLS, FEATURES, build_matrix, fit_encoders

try:
    if os.getenv("FORCE_SKLEARN"):
        raise ImportError("forced")
    import lightgbm as lgb
    BACKEND = "lightgbm"
except Exception:  # noqa: BLE001
    lgb = None
    BACKEND = "sklearn"
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor

QUANTILES = [0.1, 0.5, 0.9]
CAT_MASK = [f in CAT_COLS for f in FEATURES]


def make_regressor(alpha):
    if BACKEND == "lightgbm":
        return lgb.LGBMRegressor(objective="quantile", alpha=alpha, n_estimators=300, learning_rate=0.05,
                                 num_leaves=31, min_child_samples=40, verbose=-1)
    return HistGradientBoostingRegressor(loss="quantile", quantile=alpha, max_iter=300, learning_rate=0.05,
                                         categorical_features=CAT_MASK)


def make_classifier():
    if BACKEND == "lightgbm":
        return lgb.LGBMClassifier(n_estimators=400, learning_rate=0.05, num_leaves=31, min_child_samples=40,
                                  verbose=-1)
    return HistGradientBoostingClassifier(max_iter=400, learning_rate=0.05, categorical_features=CAT_MASK)


def fit(model, X, y):
    if BACKEND == "lightgbm":
        return model.fit(X, y, categorical_feature=CAT_COLS)
    return model.fit(X, y)


def split(o: pd.DataFrame):
    n = len(o)
    a, b = int(n * TRAIN_FRAC), int(n * (TRAIN_FRAC + VAL_FRAC))
    return o.iloc[:a], o.iloc[a:b], o.iloc[b:]


def main():
    t0 = time.time()
    o = pd.read_pickle(ORDERS_PKL)
    tr, va, te = split(o)
    enc = fit_encoders(tr)
    d = {k: v[v.canceled == 0] for k, v in {"tr": tr, "va": va, "te": te}.items()}
    X = {k: build_matrix(v, enc) for k, v in d.items()}

    regs = {}
    for a in QUANTILES:
        regs[a] = fit(make_regressor(a), X["tr"], d["tr"]["real_days"])
    clf = fit(make_classifier(), X["tr"], d["tr"]["late"])
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(
        clf.predict_proba(X["va"])[:, 1], d["va"]["late"])

    # Test period evaluation
    q = np.sort(np.column_stack([regs[a].predict(X["te"]) for a in QUANTILES]), axis=1)
    y_days, y_late = d["te"]["real_days"].values, d["te"]["late"].values
    raw = clf.predict_proba(X["te"])[:, 1]
    cal = iso.predict(raw)
    metrics = {
        "backend": BACKEND,
        "n_train": int(len(X["tr"])), "n_val": int(len(X["va"])), "n_test": int(len(X["te"])),
        "test_period": [str(te.order_ts.min()), str(te.order_ts.max())],
        "eta_mae_days_model_p50": round(float(mean_absolute_error(y_days, q[:, 1])), 3),
        "eta_mae_days_baseline_scheduled": round(float(mean_absolute_error(y_days, d["te"]["scheduled_days"])), 3),
        "eta_p10_p90_coverage": round(float(np.mean((y_days >= q[:, 0]) & (y_days <= q[:, 2]))), 3),
        "breach_roc_auc": round(float(roc_auc_score(y_late, cal)), 3),
        "breach_pr_auc": round(float(average_precision_score(y_late, cal)), 3),
        "breach_pr_auc_baseline_rate": round(float(y_late.mean()), 3),
        "brier_raw": round(float(brier_score_loss(y_late, raw)), 4),
        "brier_calibrated": round(float(brier_score_loss(y_late, cal)), 4),
        "train_seconds": round(time.time() - t0, 1),
    }

    baseline = {}
    for c in FEATURES:
        col = X["tr"][c]
        baseline[c] = int(col.mode().iloc[0]) if c in CAT_COLS else float(col.median())
    mode_days = d["tr"].groupby("ship_mode")["real_days"].mean().round(2).to_dict()

    ART_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump({"backend": BACKEND, "enc": enc, "regs": regs, "clf": clf, "iso": iso,
                 "baseline": baseline, "mode_days": mode_days}, ART_DIR / "models.joblib")
    split_info = {"train_end": str(tr.order_ts.max()), "val_end": str(va.order_ts.max()),
                  "test_order_ids": te.order_id.astype(int).tolist()}
    (ART_DIR / "split.json").write_text(json.dumps(split_info))
    (ART_DIR / "metrics.json").write_text(json.dumps(metrics, indent=2))
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
