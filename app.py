"""Step 5: live dashboard. Run the replay in one terminal and this in another:

    streamlit run app.py --server.port 8501 --server.address 0.0.0.0
Then open http://<VM_IP>:8501 (or tunnel: ssh -L 8501:localhost:8501 user@VM_IP).
"""
import json
import sqlite3
from datetime import datetime, timezone

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

# Persistent audit trail for human approval decisions.
with sqlite3.connect(DB_PATH) as _con:
    _con.execute("""
        CREATE TABLE IF NOT EXISTS approval_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_id TEXT NOT NULL,
            shipment_id INTEGER NOT NULL,
            decision TEXT NOT NULL CHECK(decision IN ('APPROVED', 'REJECTED')),
            reviewer TEXT NOT NULL,
            reason TEXT NOT NULL DEFAULT '',
            decided_ts TEXT NOT NULL
        )
    """)

tab_live, tab_scn, tab_alert, tab_sup, tab_anom, tab_plat = st.tabs(
    ["Live risk", "Scenarios", "Alert detail", "Suppliers", "Anomalies", "Platform"])

GOODS_LABEL = {"medicine": "Medicine", "medical_equipment": "Medical equipment", "relief_supplies": "Relief supplies",
               "other": "General goods"}
PRIORITY_COL = {"priority": st.column_config.ProgressColumn("priority", min_value=0.0, max_value=1.0, format="%.3f")}


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
    storm = m.get("last_disruption")
    if storm:
        d = json.loads(storm)
        st.error(f"Regional disruption in {d['region']}: {d['affected']} open shipments delayed at {d['at'][:16]}")
    st.subheader("Open shipments at risk, highest priority first")
    only_scn = st.toggle("Show demo scenario shipments only", value=False, key="only_scn")
    where = "AND s.scenario IS NOT NULL" if only_scn else ""
    df = q(f"""SELECT s.shipment_id, s.scenario, s.product_name, s.essential_goods_type goods, s.supplier_name, s.ship_mode, s.criticality,
                     ROUND(s.inventory_cover,1) inventory_cover_days, ROUND(s.breach_prob,2) breach_prob, ROUND(s.priority,3) priority,
                     ROUND(s.eta_p50,1) eta_days, s.status, a.verdict, a.recommended_action
              FROM shipments s LEFT JOIN alerts a ON a.shipment_id = s.shipment_id
              WHERE s.status IN ('OPEN','IN_TRANSIT') {where} ORDER BY s.priority DESC LIMIT 25""")
    if len(df):
        df["goods"] = df["goods"].map(GOODS_LABEL).fillna(df["goods"])
    st.dataframe(df, hide_index=True, column_config=PRIORITY_COL)


with tab_live:
    live()

with tab_scn:
    @st.fragment(run_every="3s")
    def scenarios_view():
        scn = q("SELECT * FROM scenarios ORDER BY id")
        if scn.empty:
            st.info("No scenarios in this run. Start the replay without --no-scenarios.")
            return
        st.caption("Scripted demo shipments, scored by the same models as every real shipment. "
                   "DataCo has no medicines, so these show the medical, supplier and disruption use cases.")
        for r in scn.itertuples():
            with st.expander(f"{r.id}  {r.name}", expanded=r.id in ("S1", "S2")):
                st.markdown(r.story)
                st.markdown(f"**Expected:** {r.expected}")
                ids = [x["shipment_id"] for x in json.loads(r.shipments)]
                marks = ",".join("?" * len(ids))
                df = q(f"""SELECT s.shipment_id, s.product_name, s.essential_goods_type goods, s.supplier_name,
                                  sp.score supplier_score, ROUND(s.inventory_cover,1) cover_days,
                                  ROUND(COALESCE(a.breach_prob, s.breach_prob),2) breach_prob,
                                  ROUND(COALESCE(a.priority, s.priority),3) priority, s.status, a.verdict,
                                  a.recommended_action action, a.requires_approval needs_approval
                           FROM shipments s LEFT JOIN alerts a USING(shipment_id)
                           LEFT JOIN suppliers sp ON sp.supplier_id = s.supplier_id
                           WHERE s.shipment_id IN ({marks}) ORDER BY priority DESC""", tuple(ids))
                if df.empty:
                    st.caption("Waiting for these shipments to appear in the stream...")
                else:
                    df["goods"] = df["goods"].map(GOODS_LABEL).fillna(df["goods"])
                    st.dataframe(df, hide_index=True, column_config=PRIORITY_COL)
    scenarios_view()

with tab_alert:
    alerts = q("SELECT * FROM alerts ORDER BY priority DESC")
    if alerts.empty:
        st.info("No alerts yet.")
    else:
        names = dict(q("SELECT shipment_id, COALESCE(scenario || ' ', '') || product_name FROM shipments").values.tolist())
        labels = [f"{names.get(r.shipment_id, r.alert_id)}  |  {r.verdict}  |  priority {r.priority:.3f}  |  {r.recommended_action}"
                  for r in alerts.itertuples()]
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
            pdet = json.loads(s.priority_detail) if s.get("priority_detail") else {}
            if pdet:
                st.caption("Priority = breach x criticality x stockout x urgency x supplier factor")
                st.bar_chart(pd.Series({k: v for k, v in pdet.items() if k != "priority"}, name="factor"), height=220)
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
            if a.requires_approval and a.status == "PENDING_APPROVAL":
                st.warning("Human approval required. Approval authorizes the recommendation; it does not execute the shipment change.")

                reviewer = st.text_input(
                    "Reviewer name",
                    key=f"reviewer_{a.alert_id}",
                    placeholder="Enter your name",
                )
                rejection_reason = st.text_area(
                    "Reason for rejection (required to reject)",
                    key=f"reject_reason_{a.alert_id}",
                    height=80,
                )

                approve_col, reject_col = st.columns(2)

                with approve_col:
                    if st.button("Approve recommendation", type="primary", key=f"approve_{a.alert_id}"):
                        if not reviewer.strip():
                            st.error("Enter the reviewer name before approving.")
                        else:
                            now = datetime.now(timezone.utc).isoformat()
                            with sqlite3.connect(DB_PATH, timeout=10) as con:
                                con.execute("BEGIN IMMEDIATE")
                                cur = con.execute(
                                    """UPDATE alerts SET status='APPROVED'
                                       WHERE alert_id=? AND status='PENDING_APPROVAL'""",
                                    (a.alert_id,),
                                )
                                if cur.rowcount == 1:
                                    con.execute(
                                        """INSERT INTO approval_decisions
                                           (alert_id, shipment_id, decision, reviewer, reason, decided_ts)
                                           VALUES (?, ?, 'APPROVED', ?, ?, ?)""",
                                        (a.alert_id, int(a.shipment_id), reviewer.strip(),
                                         "Approved recommendation; execution not confirmed.", now),
                                    )
                                    st.success("Recommendation approved. No shipment change was executed.")
                                else:
                                    st.error("This alert is no longer pending. Refresh and review its current status.")

                            st.rerun()

                with reject_col:
                    if st.button("Reject recommendation", key=f"reject_{a.alert_id}"):
                        if not reviewer.strip():
                            st.error("Enter the reviewer name before rejecting.")
                        elif not rejection_reason.strip():
                            st.error("Enter a reason for rejection.")
                        else:
                            now = datetime.now(timezone.utc).isoformat()
                            with sqlite3.connect(DB_PATH, timeout=10) as con:
                                con.execute("BEGIN IMMEDIATE")
                                cur = con.execute(
                                    """UPDATE alerts SET status='REJECTED'
                                       WHERE alert_id=? AND status='PENDING_APPROVAL'""",
                                    (a.alert_id,),
                                )
                                if cur.rowcount == 1:
                                    con.execute(
                                        """INSERT INTO approval_decisions
                                           (alert_id, shipment_id, decision, reviewer, reason, decided_ts)
                                           VALUES (?, ?, 'REJECTED', ?, ?, ?)""",
                                        (a.alert_id, int(a.shipment_id), reviewer.strip(),
                                         rejection_reason.strip(), now),
                                    )
                                    st.success("Recommendation rejected and reason recorded.")
                                else:
                                    st.error("This alert is no longer pending. Refresh and review its current status.")

                            st.rerun()

            else:
                st.caption(f"Status: {a.status}")


    st.divider()
    st.subheader("Human approval audit trail")
    audit = q(
        """SELECT alert_id, shipment_id, decision, reviewer, reason, decided_ts
           FROM approval_decisions ORDER BY id DESC LIMIT 50"""
    )
    if audit.empty:
        st.caption("No human approval decisions recorded yet.")
    else:
        st.dataframe(audit, hide_index=True, use_container_width=True)

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
