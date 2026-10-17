"""Step 3: replay test period shipments as a live event stream and score every event.

    python replay.py --n 1500 --speed 20000 --reset
--speed is simulated seconds per real second (20000 means one simulated day takes about 4 seconds).
Writes everything to SQLite (chainsight.db) for the dashboard. Safe to stop with Ctrl+C.
"""
import argparse
import warnings
import json
import platform
import sqlite3
import time

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=DeprecationWarning)

from books import PriceBook, SupplierBook, check_quantity
from config import ART_DIR, BREACH_THRESHOLD, DB_PATH, DELAY_EVENT_LIFT, LLM_MAX_CALLS, LLM_MIN_PRIORITY, ORDERS_PKL
from decision import needs_approval, options, priority_breakdown
from reasoner import evidence_packet, review
from scoring import Scorer
import scenarios as scn

SCHEMA = """
CREATE TABLE IF NOT EXISTS shipments(shipment_id INTEGER PRIMARY KEY, order_ts TEXT, promised_ts TEXT, ship_mode TEXT,
  market TEXT, region TEXT, department TEXT, category TEXT, product_name TEXT, essential_goods_type TEXT,
  supplier_id TEXT, supplier_name TEXT, criticality INT,
  total_sales REAL, total_qty INT, eta_p10 REAL, eta_p50 REAL, eta_p90 REAL, breach_prob REAL, priority REAL,
  status TEXT, drivers TEXT, last_event TEXT, updated_ts TEXT, inventory_cover REAL, actual_late INT, alerted INT DEFAULT 0,
  scenario TEXT, goods_tier INT, priority_detail TEXT);
CREATE TABLE IF NOT EXISTS scenarios(id TEXT PRIMARY KEY, name TEXT, story TEXT, expected TEXT, shipments TEXT);
CREATE TABLE IF NOT EXISTS events(event_id TEXT PRIMARY KEY, shipment_id INT, type TEXT, sim_ts TEXT, payload TEXT, score_ms REAL);
CREATE TABLE IF NOT EXISTS alerts(alert_id TEXT PRIMARY KEY, shipment_id INT, created_ts TEXT, breach_prob REAL, priority REAL,
  verdict TEXT, root_cause TEXT, recommended_action TEXT, justification TEXT, citations TEXT, options TEXT, evidence TEXT,
  draft_email TEXT, requires_approval INT, status TEXT, source TEXT, llm_ms REAL, promised_ts TEXT, actual_late INT);
CREATE TABLE IF NOT EXISTS anomalies(id INTEGER PRIMARY KEY AUTOINCREMENT, shipment_id INT, event_id TEXT, kind TEXT, detail TEXT, sim_ts TEXT);
CREATE TABLE IF NOT EXISTS suppliers(supplier_id TEXT PRIMARY KEY, name TEXT, department TEXT, n_orders INT, on_time_rate REAL,
  quality_rate REAL, score REAL, updated_ts TEXT);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
"""


def build_events(orders: pd.DataFrame, seed=11):
    """Turn each order into a realistic event sequence. Delay signals and anomalies are simulated and labeled."""
    rng = np.random.default_rng(seed)
    evs = []
    for r in orders.itertuples():
        t0, sid = r.order_ts, int(r.order_id)
        evs.append((t0, sid, "ORDER_PLACED", {}))
        price = r.unit_price * (rng.uniform(1.4, 2.0) if rng.random() < 0.03 else 1.0)
        evs.append((t0 + pd.Timedelta(minutes=30), sid, "INVOICE", {"unit_price": round(float(price), 2)}))
        if r.canceled:
            evs.append((t0 + pd.Timedelta(days=1), sid, "CANCELED", {}))
            continue
        shipped = int(r.total_qty)
        if rng.random() < 0.03:
            shipped = max(0, shipped - int(rng.integers(1, 3)))
        evs.append((t0 + pd.Timedelta(hours=int(rng.integers(2, 20))), sid, "DISPATCHED", {"shipped_qty": shipped}))
        horizon = min(r.scheduled_days, r.real_days)
        if horizon > 0 and ((r.late and rng.random() < 0.7) or (not r.late and rng.random() < 0.05)):
            delay = float(max(r.real_days - r.scheduled_days, 1))
            evs.append((t0 + pd.Timedelta(days=0.5 * horizon), sid, "DELAYED", {"delay_days": delay, "reason": "carrier exception"}))
        evs.append((t0 + pd.Timedelta(days=float(r.real_days), hours=int(rng.integers(1, 8))), sid, "DELIVERED", {}))
    evs.sort(key=lambda e: e[0])
    return [{"event_id": f"E{i:06d}", "sim_ts": e[0], "shipment_id": e[1], "type": e[2], "payload": e[3]} for i, e in enumerate(evs)]


class Engine:
    def __init__(self, n, seed=11, with_scenarios=True):
        o = pd.read_pickle(ORDERS_PKL)
        split = json.loads((ART_DIR / "split.json").read_text())
        hist = o[o.order_ts <= pd.Timestamp(split["val_end"])]
        test_all = o[o.order_id.isin(split["test_order_ids"])].sort_values("order_ts")
        test = test_all.head(n)
        self.scorer = Scorer()
        self.book = SupplierBook(hist)
        self.prices = PriceBook(hist)
        self.orders = {int(r["order_id"]): r for r in test.to_dict("records")}
        rng = np.random.default_rng(seed)
        # Demo estimate only: no real inventory feed exists in the source dataset.
        # Use reproducible cover values and a lower-cover scenario for explicitly
        # classified essential goods, rather than silently implying live stock data.
        self.cover = {
            sid: float(rng.uniform(1, 3) if r.get("essential_goods_type", "other") != "other"
                       else rng.uniform(5, 20))
            for sid, r in self.orders.items()
        }
        self.events = build_events(test, seed)
        self.scenario_rows = []
        if with_scenarios:
            ok = test_all[(test_all.canceled == 0)]
            base = (ok[ok.ship_mode == "Standard Class"] if (ok.ship_mode == "Standard Class").any() else ok).iloc[0].to_dict()
            counts = (test if len(test) else test_all).order_region.value_counts()
            others = [r for r in counts.index if r != base["order_region"]]
            storm = others[0] if others else None  # busiest other region, so real shipments are hit too
            sc_events, self.scenario_rows = scn.inject(self, test_all.order_ts.iloc[0], base, storm)
            self.events = sorted(self.events + sc_events, key=lambda e: e["sim_ts"])
        self.state, self.trail, self.anoms = {}, {}, {}
        self.llm_calls = 0

    # ---------- database ----------
    def open_db(self, reset):
        if reset and DB_PATH.exists():
            DB_PATH.unlink()
        self.db = sqlite3.connect(DB_PATH)
        self.db.executescript(SCHEMA)
        self.meta("platform", f"{platform.machine()} | {platform.platform()} | Python {platform.python_version()}")
        self.meta("backend", self.scorer.backend)
        self.write_suppliers("start")
        self.db.executemany("INSERT OR REPLACE INTO scenarios VALUES(?,?,?,?,?)",
                            [(r["id"], r["name"], r["story"], r["expected"], r["shipments"]) for r in self.scenario_rows])

    def meta(self, k, v):
        self.db.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (k, str(v)))

    def write_suppliers(self, ts):
        rows = [(r.supplier_id, r.name, r.department, int(r.n_orders), r.on_time_rate, r.quality_rate, r.score, str(ts))
                for r in self.book.table().itertuples()]
        self.db.executemany("INSERT OR REPLACE INTO suppliers VALUES(?,?,?,?,?,?,?,?)", rows)

    def save_shipment(self, sid, now):
        o, s = self.orders[sid], self.state[sid]
        self.db.execute("INSERT OR REPLACE INTO shipments VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            sid, str(o["order_ts"]), str(o["promised_ts"]), o["ship_mode"], o["market"], o["order_region"], o["department"],
            o["category"], o.get("product_name", "Unknown product"), o.get("essential_goods_type", "other"),
            o["supplier_id"], o["supplier_name"], int(o["criticality"]), float(o["total_sales"]),
            int(o["total_qty"]), s["eta_p10"], s["eta_p50"], s["eta_p90"], s["breach_prob"], s["priority"], s["status"],
            json.dumps(s["drivers"]), s["last_event"], str(now), self.cover[sid], int(o["late"]), int(s["alerted"]),
            o.get("scenario"), scn.GOODS_TIER.get(o.get("essential_goods_type", "other"), 4), json.dumps(s.get("priority_detail", {}))))

    # ---------- event handling ----------
    def record(self, sid):
        o = dict(self.orders[sid])
        o["sup_late_rate"] = self.book.late_rate(o["supplier_id"])
        o["sup_n_orders"] = self.book.n_orders(o["supplier_id"])
        return o

    def refresh_priority(self, sid, now):
        o, s = self.orders[sid], self.state[sid]
        elapsed = (now - o["order_ts"]).total_seconds() / 86400
        to_promise = (o["promised_ts"] - now).total_seconds() / 86400
        detail = priority_breakdown(s["breach_prob"], o["criticality"], max(s["eta_p50"] - elapsed, 0.1),
                                    self.cover[sid], to_promise, self.book.score(o["supplier_id"]))
        s["priority"], s["priority_detail"] = detail["priority"], detail

    def handle(self, ev):
        sid, now, kind, p = ev["shipment_id"], ev["sim_ts"], ev["type"], ev["payload"]
        t = time.perf_counter()
        note = ""
        if kind == "REGION_DISRUPTION":
            self.region_disruption(ev)
            return
        self.book.ensure(self.orders[sid]["supplier_id"], self.orders[sid]["supplier_name"], self.orders[sid]["department"])
        if kind == "ORDER_PLACED":
            res = self.scorer.score(self.record(sid))
            self.state[sid] = {**res, "status": "OPEN", "last_event": kind, "alerted": 0}
            self.refresh_priority(sid, now)
        elif sid not in self.state:
            return
        s = self.state[sid]
        if kind == "INVOICE":
            msg = self.prices.check(self.orders[sid]["product_id"], p["unit_price"])
            if msg:
                self.add_anomaly(sid, ev, "price_jump", msg)
                note = "price anomaly"
        elif kind == "DISPATCHED":
            msg = check_quantity(int(self.orders[sid]["total_qty"]), p["shipped_qty"])
            if msg:
                self.add_anomaly(sid, ev, "quantity_mismatch", msg)
                note = "quantity anomaly"
            s["status"] = "IN_TRANSIT"
        elif kind == "DELAYED":
            # Event update rule: a carrier delay removes most of the remaining chance of arriving on time
            s["breach_prob"] = 1 - (1 - s["breach_prob"]) * (1 - DELAY_EVENT_LIFT)
            for k in ("eta_p10", "eta_p50", "eta_p90"):
                s[k] += p["delay_days"]
            note = f"delay {p['delay_days']:.0f} day(s)" + (f", {p['reason']}" if p.get("reason") else "")
            self.refresh_priority(sid, now)
        elif kind == "TEMP_EXCURSION":
            # Event rule: goods outside their temperature range cannot be used, so the order will miss its date
            msg = f"logged {p['temp_c']} C for {p.get('minutes', '?')} min, allowed {p.get('limit', '2 to 8 C')}"
            self.add_anomaly(sid, ev, "temperature_excursion", msg)
            s["breach_prob"] = max(s["breach_prob"], 0.95)
            note = "cold chain break"
            self.refresh_priority(sid, now)
        elif kind in ("DELIVERED", "CANCELED"):
            o = self.orders[sid]
            delivered = kind == "DELIVERED"
            self.book.update(o["supplier_id"], delivered, on_time=not o["late"], quality_ok=delivered and sid not in self.anoms)
            s["status"] = kind
            s["breach_prob"] = float(o["late"]) if delivered else s["breach_prob"]
            self.db.execute("UPDATE alerts SET status = CASE WHEN status='OPEN' THEN 'CLOSED' ELSE status END WHERE shipment_id=?", (sid,))
        s["last_event"] = kind
        ev["note"] = note
        self.trail.setdefault(sid, []).append({"event_id": ev["event_id"], "type": kind, "sim_ts": str(now), "note": note})
        if kind in ("ORDER_PLACED", "DELAYED", "INVOICE", "DISPATCHED", "TEMP_EXCURSION"):
            self.maybe_alert(sid, now, kind)
        ms = round((time.perf_counter() - t) * 1000, 2)
        self.db.execute("INSERT OR REPLACE INTO events VALUES(?,?,?,?,?,?)",
                        (ev["event_id"], sid, kind, str(now), json.dumps(p), ms))
        self.save_shipment(sid, now)
        if kind in ("DELIVERED", "CANCELED"):
            o = self.orders[sid]
            b = self.book
            sup = o["supplier_id"]
            self.db.execute("INSERT OR REPLACE INTO suppliers VALUES(?,?,?,?,?,?,?,?)",
                            (sup, b.meta[sup]["name"], b.meta[sup]["department"], b.n_orders(sup),
                             round(b.on_time_rate(sup), 3), round(b.quality_rate(sup), 3), b.score(sup), str(now)))

    def region_disruption(self, ev):
        """Broadcast event: every open shipment in the region gets a carrier delay at once."""
        p = ev["payload"]
        hit = [sid for sid, s in self.state.items()
               if s["status"] in ("OPEN", "IN_TRANSIT") and self.orders[sid]["order_region"] == p["region"]]
        for sid in hit:
            self.handle({"event_id": f"{ev['event_id']}_{sid}", "sim_ts": ev["sim_ts"], "shipment_id": sid, "type": "DELAYED",
                         "payload": {"delay_days": p["delay_days"], "reason": f"regional disruption: {p['reason']}"}})
        self.db.execute("INSERT OR REPLACE INTO events VALUES(?,?,?,?,?,?)",
                        (ev["event_id"], 0, ev["type"], str(ev["sim_ts"]), json.dumps(dict(p, affected=len(hit))), 0.0))
        self.meta("last_disruption", json.dumps({"region": p["region"], "affected": len(hit), "at": str(ev["sim_ts"])}))

    def add_anomaly(self, sid, ev, kind, msg):
        self.anoms.setdefault(sid, []).append({"event_id": ev["event_id"], "kind": kind, "detail": msg})
        self.db.execute("INSERT INTO anomalies(shipment_id,event_id,kind,detail,sim_ts) VALUES(?,?,?,?,?)",
                        (sid, ev["event_id"], kind, msg, str(ev["sim_ts"])))

    def maybe_alert(self, sid, now, kind):
        s, o = self.state[sid], self.orders[sid]
        prev = self.db.execute("SELECT verdict FROM alerts WHERE alert_id=?", (f"A{sid}",)).fetchone()
        new_signal = kind in ("DELAYED", "TEMP_EXCURSION") or (kind in ("INVOICE", "DISPATCHED") and sid in self.anoms and prev is None)
        if s["breach_prob"] < BREACH_THRESHOLD and not (sid in self.anoms and prev is None):
            return
        if prev is not None and not (prev[0] == "DISMISS" and new_signal):
            return
        rec = self.record(sid)
        opts = options(self.scorer, self.book, rec, s, [a["kind"] for a in self.anoms.get(sid, [])])
        sup = {"name": o["supplier_name"], "score": self.book.score(o["supplier_id"]), "n_orders": self.book.n_orders(o["supplier_id"])}
        packet = evidence_packet({"shipment_id": sid, "criticality": int(o["criticality"]), "ship_mode": o["ship_mode"],
                                  "scheduled_days": float(o["scheduled_days"])},
                                 s, s["drivers"], self.trail.get(sid, []), opts, sup, self.cover[sid], self.anoms.get(sid, []))
        # Scenario shipments always get the LLM review so the demo stories are complete
        use_llm = bool(o.get("scenario")) or (self.llm_calls < LLM_MAX_CALLS and s["priority"] >= LLM_MIN_PRIORITY)
        ans = review(packet, opts, use_llm=use_llm)
        if use_llm:
            self.llm_calls += 1
        s["alerted"] = 1
        self.db.execute("INSERT OR REPLACE INTO alerts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            f"A{sid}", sid, str(now), s["breach_prob"], s["priority"], ans["verdict"], ans["root_cause"],
            ans["recommended_action"], ans["justification"], json.dumps(ans["citations"]), json.dumps(opts),
            json.dumps(packet["evidence"]), ans["draft_email"], int(needs_approval(ans["recommended_action"], o["criticality"])),
            "OPEN" if ans["verdict"] != "DISMISS" else "DISMISSED", ans.get("source", ""), ans.get("llm_ms", 0),
            str(o["promised_ts"]), int(o["late"])))

    # ---------- main loop ----------
    def run(self, speed, max_sleep):
        prev = None
        start = time.time()
        for i, ev in enumerate(self.events):
            if prev is not None and speed > 0:
                gap = (ev["sim_ts"] - prev).total_seconds() / speed
                time.sleep(min(max(gap, 0), max_sleep))
            prev = ev["sim_ts"]
            self.handle(ev)
            if i % 25 == 0:
                self.meta("sim_clock", ev["sim_ts"])
                self.meta("events_processed", i + 1)
                self.meta("events_total", len(self.events))
                self.db.commit()
        self.meta("sim_clock", prev)
        self.meta("events_processed", len(self.events))
        self.meta("events_total", len(self.events))
        self.meta("finished", "yes")
        self.db.commit()
        print(f"Replayed {len(self.events)} events in {time.time() - start:.1f}s, LLM calls {self.llm_calls}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1500, help="number of test shipments to replay")
    ap.add_argument("--speed", type=float, default=20000, help="simulated seconds per real second, 0 = no waiting")
    ap.add_argument("--max-sleep", type=float, default=0.5)
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--no-scenarios", action="store_true", help="replay only real test period shipments")
    a = ap.parse_args()
    eng = Engine(a.n, with_scenarios=not a.no_scenarios)
    eng.open_db(a.reset)
    try:
        eng.run(a.speed, a.max_sleep)
    except KeyboardInterrupt:
        eng.db.commit()
        print("Stopped.")
