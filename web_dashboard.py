"""ChainSight live dashboard served from LinuxONE with only the Python standard library.

    python web_dashboard.py --port 8501
Open http://localhost:8501 through the SSH tunnel (ssh -L 8501:localhost:8501 user@VM_IP).
Reads chainsight.db written by replay.py. Nothing to install.
"""
import argparse
import json
import mimetypes
import re
import sqlite3
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from config import BREACH_THRESHOLD, DB_PATH

WEB = Path(__file__).resolve().parent / "web"
OPEN = "('OPEN','IN_TRANSIT')"
_rate = {"t": None, "n": 0, "eps": 0.0}


def db(write=False):
    """Read only by default, so the dashboard never creates or locks the database the replay is writing."""
    if not Path(DB_PATH).exists():
        raise sqlite3.OperationalError("database not created yet")
    con = sqlite3.connect(f"file:{DB_PATH}?mode={'rw' if write else 'ro'}", uri=True, timeout=5)
    con.row_factory = sqlite3.Row
    return con


def rows(sql, params=()):
    try:
        con = db()
    except sqlite3.Error:
        return []
    try:
        return [dict(r) for r in con.execute(sql, params).fetchall()]
    except sqlite3.Error:
        return []
    finally:
        con.close()


def one(sql, params=()):
    r = rows(sql, params)
    return r[0] if r else None


def meta():
    return {r["key"]: r["value"] for r in rows("SELECT key, value FROM meta")}


def jload(v, default):
    try:
        return json.loads(v) if v else default
    except (TypeError, ValueError):
        return default


# ---------------- API handlers ----------------
def api_summary(_q):
    m = meta()
    processed = int(m.get("events_processed", 0) or 0)
    now = time.time()
    if _rate["t"] is not None and now > _rate["t"]:
        inst = max(processed - _rate["n"], 0) / (now - _rate["t"])
        _rate["eps"] = 0.6 * _rate["eps"] + 0.4 * inst
    _rate["t"], _rate["n"] = now, processed
    k = one(f"""SELECT
        SUM(CASE WHEN status IN {OPEN} AND essential_goods_type != 'other' AND breach_prob >= ? THEN 1 ELSE 0 END) medical_at_risk,
        SUM(CASE WHEN status IN {OPEN} AND breach_prob >= ? THEN total_sales ELSE 0 END) value_at_risk,
        SUM(CASE WHEN status IN {OPEN} THEN 1 ELSE 0 END) open_shipments
        FROM shipments""", (BREACH_THRESHOLD, BREACH_THRESHOLD)) or {}
    a = one("""SELECT SUM(CASE WHEN requires_approval = 1 AND status = 'OPEN' THEN 1 ELSE 0 END) pending,
                      SUM(CASE WHEN verdict = 'DISMISS' THEN 1 ELSE 0 END) dismissed,
                      SUM(CASE WHEN verdict != 'DISMISS' THEN 1 ELSE 0 END) confirmed FROM alerts""") or {}
    ms = one("SELECT AVG(score_ms) ms FROM events WHERE type = 'ORDER_PLACED'") or {}
    return {
        "sim_clock": m.get("sim_clock", ""), "events_processed": processed,
        "events_total": int(m.get("events_total", 0) or 0), "finished": m.get("finished") == "yes",
        "platform": m.get("platform", ""), "backend": m.get("backend", ""),
        "disruption": jload(m.get("last_disruption"), None),
        "events_per_sec": round(_rate["eps"], 1),
        "medical_at_risk": int(k.get("medical_at_risk") or 0), "value_at_risk": round(k.get("value_at_risk") or 0, 2),
        "open_shipments": int(k.get("open_shipments") or 0),
        "approvals_pending": int(a.get("pending") or 0), "dismissed": int(a.get("dismissed") or 0),
        "confirmed": int(a.get("confirmed") or 0), "avg_ms": round(ms.get("ms") or 0, 2),
        "threshold": BREACH_THRESHOLD,
    }


def api_updates(q):
    """Everything new since the cursors the page last saw (event, alert and anomaly row ids)."""
    ev, al, an = (int(q.get(k, ["-1"])[0]) for k in ("ev", "al", "an"))
    init = ev < 0
    if init:  # first load: send recent history only, no notifications
        cur = one("SELECT (SELECT COALESCE(MAX(rowid),0) FROM events) ev, (SELECT COALESCE(MAX(rowid),0) FROM alerts) al, "
                  "(SELECT COALESCE(MAX(id),0) FROM anomalies) an") or {"ev": 0, "al": 0, "an": 0}
        events = rows("""SELECT e.rowid rid, e.event_id, e.shipment_id, e.type, e.sim_ts, e.payload, s.product_name,
                                s.essential_goods_type goods, s.scenario FROM events e LEFT JOIN shipments s USING(shipment_id)
                         ORDER BY e.rowid DESC LIMIT 40""")[::-1]
        return {"init": True, "events": events, "alerts": [], "anomalies": [], "cursor": cur}
    events = rows("""SELECT e.rowid rid, e.event_id, e.shipment_id, e.type, e.sim_ts, e.payload, s.product_name,
                            s.essential_goods_type goods, s.scenario FROM events e LEFT JOIN shipments s USING(shipment_id)
                     WHERE e.rowid > ? ORDER BY e.rowid LIMIT 120""", (ev,))
    alerts = rows("""SELECT a.rowid rid, a.alert_id, a.shipment_id, a.verdict, a.priority, a.recommended_action, a.root_cause,
                            a.requires_approval, a.status, s.product_name, s.essential_goods_type goods, s.criticality,
                            s.scenario, s.supplier_name FROM alerts a LEFT JOIN shipments s USING(shipment_id)
                     WHERE a.rowid > ? ORDER BY a.rowid LIMIT 40""", (al,))
    anoms = rows("""SELECT n.id, n.shipment_id, n.kind, n.detail, n.sim_ts, s.product_name, s.essential_goods_type goods
                    FROM anomalies n LEFT JOIN shipments s USING(shipment_id) WHERE n.id > ? ORDER BY n.id LIMIT 40""", (an,))
    cur = {"ev": events[-1]["rid"] if events else ev, "al": alerts[-1]["rid"] if alerts else al,
           "an": anoms[-1]["id"] if anoms else an}
    return {"init": False, "events": events, "alerts": alerts, "anomalies": anoms, "cursor": cur}


def api_risk(q):
    scope = q.get("scope", ["all"])[0]
    where = "AND s.scenario IS NOT NULL" if scope == "scenarios" else ""
    goods = q.get("goods", ["all"])[0]
    params = []
    if goods == "essential":
        where += " AND s.essential_goods_type != 'other'"
    return rows(f"""SELECT s.shipment_id, s.scenario, s.product_name, s.essential_goods_type goods, s.criticality,
                           s.supplier_name, sp.score supplier_score, s.ship_mode, s.region, s.eta_p10, s.eta_p50, s.eta_p90,
                           s.breach_prob, s.priority, s.status, s.inventory_cover, s.order_ts, s.promised_ts,
                           a.verdict, a.recommended_action, a.requires_approval, a.status alert_status
                    FROM shipments s LEFT JOIN alerts a USING(shipment_id)
                    LEFT JOIN suppliers sp ON sp.supplier_id = s.supplier_id
                    WHERE {"1=1" if where else f"s.status IN {OPEN}"} {where}
                    ORDER BY (s.status IN {OPEN}) DESC, COALESCE(a.priority, s.priority) DESC LIMIT 40""", params)


def api_shipment(sid):
    s = one("""SELECT s.*, sp.score supplier_score, sp.on_time_rate supplier_on_time, sp.n_orders supplier_orders
               FROM shipments s LEFT JOIN suppliers sp ON sp.supplier_id = s.supplier_id WHERE shipment_id = ?""", (sid,))
    if not s:
        return None
    s["drivers"] = jload(s.get("drivers"), [])
    s["priority_detail"] = jload(s.get("priority_detail"), {})
    a = one("SELECT * FROM alerts WHERE shipment_id = ?", (sid,))
    if a:
        for k, d in (("options", []), ("citations", []), ("evidence", [])):
            a[k] = jload(a.get(k), d)
    trail = rows("SELECT event_id, type, sim_ts, payload FROM events WHERE shipment_id = ? ORDER BY sim_ts", (sid,))
    anoms = rows("SELECT kind, detail, sim_ts FROM anomalies WHERE shipment_id = ? ORDER BY id", (sid,))
    return {"shipment": s, "alert": a, "events": trail, "anomalies": anoms}


def api_scenarios(_q):
    out = []
    for sc in rows("SELECT * FROM scenarios ORDER BY id"):
        ids = [x["shipment_id"] for x in jload(sc["shipments"], [])]
        ships = []
        if ids:
            marks = ",".join("?" * len(ids))
            ships = rows(f"""SELECT s.shipment_id, s.product_name, s.essential_goods_type goods, s.supplier_name,
                                    sp.score supplier_score, s.inventory_cover, s.status,
                                    COALESCE(a.breach_prob, s.breach_prob) breach_prob, COALESCE(a.priority, s.priority) priority,
                                    a.verdict, a.recommended_action, a.requires_approval, a.status alert_status
                             FROM shipments s LEFT JOIN alerts a USING(shipment_id)
                             LEFT JOIN suppliers sp ON sp.supplier_id = s.supplier_id
                             WHERE s.shipment_id IN ({marks}) ORDER BY priority DESC""", tuple(ids))
        out.append({**sc, "shipment_ids": ids, "rows": ships})
    return out


def api_suppliers(_q):
    return rows("SELECT * FROM suppliers ORDER BY score DESC")


def api_anomalies(_q):
    return rows("""SELECT n.*, s.product_name, s.essential_goods_type goods, s.supplier_name FROM anomalies n
                   LEFT JOIN shipments s USING(shipment_id) ORDER BY n.id DESC LIMIT 200""")


def api_platform(_q):
    m = meta()
    return {"platform": m.get("platform", ""), "backend": m.get("backend", ""),
            "by_type": rows("""SELECT type, COUNT(*) n, ROUND(AVG(score_ms),2) avg_ms, ROUND(MAX(score_ms),2) max_ms
                               FROM events GROUP BY type ORDER BY n DESC"""),
            "sources": rows("SELECT source, COUNT(*) n FROM alerts GROUP BY source")}


ROUTES = {"/api/summary": api_summary, "/api/updates": api_updates, "/api/risk": api_risk,
          "/api/scenarios": api_scenarios, "/api/suppliers": api_suppliers, "/api/anomalies": api_anomalies,
          "/api/platform": api_platform}


class Handler(BaseHTTPRequestHandler):
    def send_json(self, obj, code=200):
        body = json.dumps(obj, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path in ROUTES:
            return self.send_json(ROUTES[u.path](q))
        m = re.fullmatch(r"/api/shipment/(\d+)", u.path)
        if m:
            res = api_shipment(int(m.group(1)))
            return self.send_json(res or {"error": "not found"}, 200 if res else 404)
        name = "index.html" if u.path in ("/", "/index.html") else u.path.lstrip("/")
        f = (WEB / name).resolve()
        if WEB.resolve() not in f.parents or not f.is_file():
            self.send_error(404)
            return
        body = f.read_bytes()
        self.send_response(200)
        types = {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8", ".css": "text/css; charset=utf-8"}
        self.send_header("Content-Type", types.get(f.suffix) or mimetypes.guess_type(str(f))[0] or "application/octet-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        m = re.fullmatch(r"/api/alerts/(A\d+)/(approve|reject)", urlparse(self.path).path)
        if not m:
            return self.send_json({"error": "not found"}, 404)
        status = "APPROVED" if m.group(2) == "approve" else "REJECTED"
        try:
            con = db(write=True)
            try:
                cur = con.execute("UPDATE alerts SET status = ? WHERE alert_id = ? AND status = 'OPEN'", (status, m.group(1)))
                con.commit()
                changed = cur.rowcount
            finally:
                con.close()
        except sqlite3.Error as exc:
            return self.send_json({"error": str(exc)}, 503)
        self.send_json({"alert_id": m.group(1), "status": status, "changed": changed})

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8502)
    ap.add_argument("--host", default="0.0.0.0")
    a = ap.parse_args()
    print(f"ChainSight dashboard: open http://localhost:{a.port}  (database: {DB_PATH})")
    ThreadingHTTPServer((a.host, a.port), Handler).serve_forever()
