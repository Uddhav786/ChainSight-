"""Live state that updates as events arrive: supplier scores and price references."""
import numpy as np
import pandas as pd

from config import PRIOR_K


class SupplierBook:
    """Bayesian shrunk supplier scores.

    on_time_rate = (on_time + K * prior) / (orders + K)
    A newcomer with a few perfect orders stays near the prior, so it cannot outrank a proven supplier.
    """

    def __init__(self, history: pd.DataFrame):
        self.prior_on_time = 1 - history.loc[history.canceled == 0, "late"].mean()
        self.prior_quality = 1 - history["canceled"].mean()
        self.meta = history.groupby("supplier_id").agg(name=("supplier_name", "first"),
                                                       department=("department", "first")).to_dict("index")
        delivered = history[history.canceled == 0]
        self.n = delivered.groupby("supplier_id").size().to_dict()
        self.on_time = delivered.groupby("supplier_id")["late"].apply(lambda s: int((1 - s).sum())).to_dict()
        self.total = history.groupby("supplier_id").size().to_dict()
        self.quality_ok = history.groupby("supplier_id")["canceled"].apply(lambda s: (1 - s).sum()).to_dict()

    def ensure(self, sid, name="", department=""):
        if sid not in self.meta:
            self.meta[sid] = {"name": name, "department": department}

    def on_time_rate(self, sid) -> float:
        n, ok = self.n.get(sid, 0), self.on_time.get(sid, 0)
        return (ok + PRIOR_K * self.prior_on_time) / (n + PRIOR_K)

    def late_rate(self, sid) -> float:
        return 1 - self.on_time_rate(sid)

    def quality_rate(self, sid) -> float:
        n, ok = self.total.get(sid, 0), self.quality_ok.get(sid, 0)
        return (ok + PRIOR_K * self.prior_quality) / (n + PRIOR_K)

    def score(self, sid) -> float:
        return round(100 * (0.7 * self.on_time_rate(sid) + 0.3 * self.quality_rate(sid)), 1)

    def n_orders(self, sid) -> int:
        return int(self.n.get(sid, 0))

    def update(self, sid, delivered: bool, on_time: bool, quality_ok: bool):
        self.total[sid] = self.total.get(sid, 0) + 1
        self.quality_ok[sid] = self.quality_ok.get(sid, 0) + int(quality_ok)
        if delivered:
            self.n[sid] = self.n.get(sid, 0) + 1
            self.on_time[sid] = self.on_time.get(sid, 0) + int(on_time)

    def best_in_department(self, department, exclude=None):
        cands = [s for s, m in self.meta.items() if m["department"] == department and s != exclude]
        return max(cands, key=self.score) if cands else None

    def table(self) -> pd.DataFrame:
        rows = [{"supplier_id": s, "name": m["name"], "department": m["department"],
                 "n_orders": self.n_orders(s), "on_time_rate": round(self.on_time_rate(s), 3),
                 "quality_rate": round(self.quality_rate(s), 3), "score": self.score(s)}
                for s, m in self.meta.items()]
        return pd.DataFrame(rows).sort_values("score", ascending=False)


class PriceBook:
    """Robust z score on unit price per product (median and MAD), with a relative fallback when MAD is 0."""

    def __init__(self, history: pd.DataFrame, z_limit=3.5, rel_limit=0.25):
        g = history.groupby("product_id")["unit_price"]
        self.median = g.median().to_dict()
        self.mad = g.apply(lambda s: float(np.median(np.abs(s - s.median())))).to_dict()
        self.z_limit, self.rel_limit = z_limit, rel_limit

    def check(self, product_id, price):
        med = self.median.get(product_id)
        if med is None or med <= 0:
            return None
        mad = self.mad.get(product_id, 0.0)
        rel = (price - med) / med
        z = 0.6745 * (price - med) / mad if mad > 0 else None
        if (z is not None and abs(z) > self.z_limit) or abs(rel) > self.rel_limit:
            ztxt = f"robust z {z:.1f}, " if z is not None else ""
            return f"unit price {price:.2f} vs median {med:.2f} ({ztxt}{rel:+.0%})"
        return None


def check_quantity(ordered, shipped, tol=0.0):
    if shipped < ordered * (1 - tol) or shipped > ordered * (1 + tol):
        return f"shipped {shipped} vs ordered {ordered}"
    return None
