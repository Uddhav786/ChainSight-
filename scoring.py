"""Scores one shipment: delivery date band, calibrated breach probability, top drivers.
Also used for counterfactuals (same shipment with a different ship mode or supplier)."""
import time

import joblib
import numpy as np
import pandas as pd

from config import ART_DIR
from features import CAT_COLS, FEATURES, build_matrix, decode

QUANTILES = [0.1, 0.5, 0.9]

FRIENDLY = {
    "ship_mode": "shipping mode", "market": "market", "order_region": "destination region",
    "department": "department", "category": "product category", "customer_segment": "customer segment",
    "supplier_id": "supplier", "scheduled_days": "promised days", "total_qty": "order quantity",
    "total_sales": "order value", "unit_price": "unit price", "order_dow": "order weekday",
    "order_month": "order month", "order_hour": "order hour", "sup_late_rate": "supplier late rate",
    "sup_n_orders": "supplier order history",
}


class Scorer:
    def __init__(self, art_dir=ART_DIR):
        m = joblib.load(art_dir / "models.joblib")
        self.backend, self.enc, self.regs = m["backend"], m["enc"], m["regs"]
        self.clf, self.iso, self.baseline, self.mode_days = m["clf"], m["iso"], m["baseline"], m["mode_days"]

    def matrix(self, record: dict) -> pd.DataFrame:
        return build_matrix(pd.DataFrame([record]), self.enc)

    def predict(self, X: pd.DataFrame):
        q = np.sort(np.column_stack([self.regs[a].predict(X) for a in QUANTILES]), axis=1)
        q = np.clip(q, 0, None)
        p = self.iso.predict(self.clf.predict_proba(X)[:, 1])
        return q, p

    def explain(self, X: pd.DataFrame, top=4):
        """TreeSHAP contributions from LightGBM when available, else a baseline swap attribution."""
        if self.backend == "lightgbm":
            contrib = self.clf.predict(X, pred_contrib=True)[0][:-1]
            unit = "log odds"
        else:
            p0 = self.clf.predict_proba(X)[:, 1][0]
            Xs = pd.concat([X] * len(FEATURES), ignore_index=True)
            for i, f in enumerate(FEATURES):
                Xs.loc[i, f] = self.baseline[f]
            contrib = p0 - self.clf.predict_proba(Xs)[:, 1]
            unit = "probability"
        order = np.argsort(-np.abs(contrib))[:top]
        out = []
        for i in order:
            f = FEATURES[i]
            raw = X.iloc[0][f]
            val = decode(self.enc, f, raw) if f in CAT_COLS else round(float(raw), 3)
            out.append({"feature": f, "label": FRIENDLY[f], "value": val,
                        "contribution": round(float(contrib[i]), 4), "unit": unit})
        return out

    def score(self, record: dict, explain=True):
        t = time.perf_counter()
        X = self.matrix(record)
        q, p = self.predict(X)
        res = {"eta_p10": float(q[0, 0]), "eta_p50": float(q[0, 1]), "eta_p90": float(q[0, 2]),
               "breach_prob": float(p[0])}
        if explain:
            res["drivers"] = self.explain(X)
        res["score_ms"] = round((time.perf_counter() - t) * 1000, 2)
        return res
