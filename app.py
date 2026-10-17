"""Step 5: live dashboard. Run the replay in one terminal and this in another:

    streamlit run app.py --server.port 8501 --server.address 0.0.0.0
Then open http://<VM_IP>:8501 (or tunnel: ssh -L 8501:localhost:8501 user@VM_IP).
"""
import json
import sqlite3

import pandas as pd
import streamlit as st

from config import DB_PATH

st.set_page_config(page_title="ChainSight", layout="wide")


def q(sql, params=()):
    con = sqlite3.connect(DB_PATH)
    try:
        return pd.read_sql(sql, con, params=params)
    except Exception:  # noqa: BLE001
        return pd.DataFrame()
    finally:
        con.close()


def meta():
    df = q("SELECT * FROM meta")
    return dict(zip(df.key, df.value)) if len(df) else {}


st.title("ChainSight")
st.caption("Real time delivery risk, supplier scoring and grounded recommendations on IBM LinuxONE")

if not DB_PATH.exists():
    st.warning("No data yet. Start the replay: python replay.py --reset")
    st.stop()

tab_live, tab_alert, tab_sup, tab_anom, tab_plat = st.tabs(
    ["Live risk", "Alert detail", "Suppliers", "Anomalies", "Platform"])


@st.fragment(run_every="2s")
def live():
    m = meta()
    ev = q("SELECT COUNT(*) n, AVG(score_ms) ms FROM events")
    al = q("SELECT verdict, COUNT(*) n FROM alerts GROUP BY verdict")
    c = st.columns(5)
    c[0].metric("Simulated clock", str(m.get("sim_clock", ""))[:16])
    c[1].metric("Events processed", f"{m.get('events_processed', 0)} / {m.get('events_total', 0)}")
    c[2].metric("Avg ms per event", f"{ev.ms.iloc[0]:.1f}" if len(ev) and ev.ms.iloc[0] else "0")
    c[3].metric("Confirmed alerts", int(al[al.verdict != "DISMISS"].n.sum()) if len(al) else 0)
    c[4].metric("Dismissed by GenAI", int(al[al.verdict == "DISMISS"].n.sum()) if len(al) else 0)
    st.subheader("Open shipments at risk, highest priority first")
    df = q("""SELECT s.shipment_id, s.product_name, s.essential_goods_type, s.department, s.supplier_name, s.ship_mode, s.criticality,
                     ROUND(s.inventory_cover,1) inventory_cover_days, ROUND(s.breach_prob,2) breach_prob, ROUND(s.priority,3) priority,
                     ROUND(s.eta_p50,1) eta_days, s.status, a.verdict, a.recommended_action
              FROM shipments s LEFT JOIN alerts a ON a.shipment_id = s.shipment_id
              WHERE s.status IN ('OPEN','IN_TRANSIT') ORDER BY s.priority DESC LIMIT 25""")
    st.dataframe(df, hide_index=True)


with tab_live:
    live()

with tab_alert:
    alerts = q("SELECT * FROM alerts ORDER BY priority DESC")
    if alerts.empty:
        st.info("No alerts yet.")
    else:
        labels = [f"{r.alert_id}  |  {r.verdict}  |  priority {r.priority:.3f}  |  {r.recommended_action}" for r in alerts.itertuples()]
        pick = st.selectbox("Alert", range(len(labels)), format_func=lambda i: labels[i])
        a = alerts.iloc[pick]
        s = q("SELECT * FROM shipments WHERE shipment_id = ?", (int(a.shipment_id),)).iloc[0]
        c1, c2 = st.columns([1, 1])
        with c1:
            st.markdown(f"**Shipment {a.shipment_id}** | {s.get('product_name', 'Unknown product')} | {s.department} | {s.supplier_name} | criticality {s.criticality}/5")
            st.caption(f"Goods classification: {s.get('essential_goods_type', 'other')} · Inventory cover: {s.inventory_cover:.1f} days (simulated estimate, not live inventory)")
            st.markdown(f"Delivery days P10 / P50 / P90: **{s.eta_p10:.1f} / {s.eta_p50:.1f} / {s.eta_p90:.1f}** "
                        f"(promised by {str(s.promised_ts)[:16]})")
            st.markdown(f"Breach probability **{a.breach_prob:.2f}**, priority **{a.priority:.3f}**")
            drivers = pd.DataFrame(json.loads(s.drivers))
            if len(drivers):
                st.caption("Top model drivers")
                st.bar_chart(drivers.set_index("label")["contribution"])
            st.caption("Options rescored counterfactually")
            st.dataframe(pd.DataFrame(json.loads(a.options)), hide_index=True)
        with c2:
            st.markdown(f"**GenAI verdict: {a.verdict}** (source: {a.source}, {a.llm_ms:.0f} ms)")
            st.markdown(f"**Root cause:** {a.root_cause}")
            st.markdown(f"**Recommended action:** {a.recommended_action}")
            st.markdown(a.justification)
            ev = {e["id"]: e["text"] for e in json.loads(a.evidence)}
            st.caption("Citations (each one is checked against the evidence packet)")
            for cid in json.loads(a.citations):
                st.markdown(f"- `{cid}`: {ev.get(cid, 'not found')}")
            st.text_area("Draft email (sent automatically)", a.draft_email, height=110)
            if a.requires_approval and a.status == "OPEN":
                if st.button("Approve action", type="primary"):
                    con = sqlite3.connect(DB_PATH)
                    con.execute("UPDATE alerts SET status='APPROVED' WHERE alert_id=?", (a.alert_id,))
                    con.commit()
                    con.close()
                    st.success("Approved")
            else:
                st.caption(f"Status: {a.status}")

with tab_sup:
    st.subheader("Live supplier scores (Bayesian shrinkage, updated on every delivery)")
    st.dataframe(q("SELECT * FROM suppliers ORDER BY score DESC"), hide_index=True)

with tab_anom:
    st.subheader("Transaction anomalies")
    st.dataframe(q("SELECT * FROM anomalies ORDER BY id DESC LIMIT 200"), hide_index=True)

with tab_plat:
    m = meta()
    st.markdown(f"**Platform:** {m.get('platform', '')}")
    st.markdown(f"**Model backend:** {m.get('backend', '')}")
    t = q("SELECT type, COUNT(*) n, ROUND(AVG(score_ms),2) avg_ms, ROUND(MAX(score_ms),2) max_ms FROM events GROUP BY type")
    st.dataframe(t, hide_index=True)
