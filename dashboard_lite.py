"""Fallback dashboard with only the Python standard library (use if Streamlit will not install on s390x).

    python dashboard_lite.py --port 8501
Open http://<VM_IP>:8501. The page refreshes every 3 seconds.
"""
import argparse
import html
import json
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from config import DB_PATH

QUERIES = [
    ("Open shipments at risk", """SELECT s.shipment_id, s.department, s.supplier_name, s.ship_mode, s.criticality,
        ROUND(s.breach_prob,2) breach, ROUND(s.priority,3) priority, ROUND(s.eta_p50,1) eta_days, s.status
        FROM shipments s WHERE s.status IN ('OPEN','IN_TRANSIT') ORDER BY s.priority DESC LIMIT 20"""),
    ("Latest alerts", """SELECT alert_id, verdict, ROUND(priority,3) priority, recommended_action, root_cause,
        citations, requires_approval, source FROM alerts ORDER BY created_ts DESC LIMIT 15"""),
    ("Suppliers", "SELECT name, n_orders, on_time_rate, quality_rate, score FROM suppliers ORDER BY score DESC LIMIT 20"),
    ("Anomalies", "SELECT shipment_id, kind, detail, sim_ts FROM anomalies ORDER BY id DESC LIMIT 15"),
]


def table(cur, title, sql):
    try:
        rows = cur.execute(sql).fetchall()
        cols = [d[0] for d in cur.description]
    except sqlite3.Error as exc:
        return f"<h2>{title}</h2><p>{html.escape(str(exc))}</p>"
    head = "".join(f"<th>{c}</th>" for c in cols)
    body = "".join("<tr>" + "".join(f"<td>{html.escape(str(v))}</td>" for v in r) + "</tr>" for r in rows)
    return f"<h2>{title}</h2><table><tr>{head}</tr>{body}</table>"


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        try:
            meta = dict(cur.execute("SELECT key, value FROM meta").fetchall())
        except sqlite3.Error:
            meta = {}
        parts = [table(cur, t, s) for t, s in QUERIES]
        con.close()
        page = f"""<html><head><meta http-equiv="refresh" content="3"><title>ChainSight</title>
<style>body{{font-family:sans-serif;margin:24px}}table{{border-collapse:collapse;font-size:13px}}
td,th{{border:1px solid #ccc;padding:4px 8px}}th{{background:#eee}}</style></head><body>
<h1>ChainSight</h1><p>Clock {html.escape(meta.get('sim_clock',''))} | events {meta.get('events_processed',0)} /
{meta.get('events_total',0)} | {html.escape(meta.get('platform',''))}</p>{''.join(parts)}</body></html>"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(page.encode())

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8501)
    a = ap.parse_args()
    print(f"Serving on http://0.0.0.0:{a.port}")
    ThreadingHTTPServer(("0.0.0.0", a.port), H).serve_forever()
