"""Scripted demo scenarios injected into the live replay.

DataCo sells sports goods, apparel and electronics, so it contains no real medicines. To demonstrate
medical priority, supplier priority and the other use cases, these scenario shipments are added on top
of the real test period stream. Each one is clearly labeled (scenario column, SCN product ids, Medical
Supplies suppliers) and is scored by the same trained models as every real shipment. Only the shipment
attributes, supplier histories and events below are scripted; the model outputs are not.

Edit SCENARIOS to change the story. Each shipment needs a unique `key`.
"""
import json

import pandas as pd

# Synthetic suppliers with known histories: (id, name, department, delivered, on_time, total, quality_ok)
SUPPLIERS = [
    ("SUPM01", "CarePath Medical Distributors", "Medical Supplies", 500, 480, 505, 503),
    ("SUPM02", "NovaMed Express (new)", "Medical Supplies", 2, 2, 2, 2),
    ("SUPM03", "QuickShip Pharma", "Medical Supplies", 220, 120, 230, 214),
    ("SUPM04", "Metro General Freight", "General Freight", 400, 300, 400, 396),
]

# Goods tiers: lower number = served first when everything else is equal
GOODS_TIER = {"medicine": 1, "medical_equipment": 2, "relief_supplies": 3, "other": 4}

SCENARIOS = [
    {
        "id": "S1", "name": "Medical goods first",
        "story": "Insulin and office paper ship on the same lane with the same carrier and both get delayed. "
                 "Insulin has 1.5 days of stock left at the clinic, paper has 15.",
        "expected": "Insulin is ranked far above office paper",
        "shipments": [
            {"key": "S1_insulin", "product_name": "Insulin glargine 100 IU/mL vials", "essential_goods_type": "medicine",
             "criticality": 5, "supplier_id": "SUPM04", "ship_mode": "Standard Class", "scheduled_days": 4, "real_days": 6,
             "total_qty": 200, "unit_price": 30.0, "cover_days": 1.5, "start_h": 2,
             "events": [(24, "DELAYED", {"delay_days": 2, "reason": "carrier exception"})]},
            {"key": "S1_paper", "product_name": "A4 office paper, 10 reams", "essential_goods_type": "other",
             "criticality": 1, "supplier_id": "SUPM04", "ship_mode": "Standard Class", "scheduled_days": 4, "real_days": 6,
             "total_qty": 200, "unit_price": 30.0, "cover_days": 15, "start_h": 2.2,
             "events": [(24, "DELAYED", {"delay_days": 2, "reason": "carrier exception"})]},
        ],
    },
    {
        "id": "S2", "name": "Unreliable supplier gets attention",
        "story": "Two identical vaccine orders: one from QuickShip Pharma (55% on time), one from CarePath (96% on time).",
        "expected": "The QuickShip order has higher priority and a switch supplier option to CarePath",
        "shipments": [
            {"key": "S2_quickship", "product_name": "Measles vaccine vials (cold chain)", "essential_goods_type": "medicine",
             "criticality": 5, "supplier_id": "SUPM03", "ship_mode": "Second Class", "scheduled_days": 2, "real_days": 4,
             "total_qty": 300, "unit_price": 12.0, "cover_days": 4, "start_h": 5, "events": []},
            {"key": "S2_carepath", "product_name": "Measles vaccine vials (cold chain)", "essential_goods_type": "medicine",
             "criticality": 5, "supplier_id": "SUPM01", "ship_mode": "Second Class", "scheduled_days": 2, "real_days": 2,
             "total_qty": 300, "unit_price": 12.0, "cover_days": 4, "start_h": 5.2, "events": []},
        ],
    },
    {
        "id": "S3", "name": "Newcomer cannot outrank a proven supplier",
        "story": "NovaMed Express has 2 of 2 orders on time. CarePath has 480 of 500. Bayesian shrinkage keeps the newcomer near the average.",
        "expected": "CarePath scores above NovaMed on the supplier leaderboard",
        "shipments": [
            {"key": "S3_novamed", "product_name": "Surgical gloves, sterile, box of 100", "essential_goods_type": "medical_equipment",
             "criticality": 4, "supplier_id": "SUPM02", "ship_mode": "Standard Class", "scheduled_days": 4, "real_days": 4,
             "total_qty": 120, "unit_price": 9.0, "cover_days": 8, "start_h": 8, "events": []},
        ],
    },
    {
        "id": "S4", "name": "Cold chain break",
        "story": "A temperature logger reports 14 C on an insulin pen shipment that must stay between 2 and 8 C.",
        "expected": "Temperature anomaly flagged, breach risk jumps, alert raised with a replacement option",
        "shipments": [
            {"key": "S4_coldchain", "product_name": "Insulin pens, prefilled (cold chain)", "essential_goods_type": "medicine",
             "criticality": 5, "supplier_id": "SUPM01", "ship_mode": "Second Class", "scheduled_days": 2, "real_days": 3,
             "total_qty": 150, "unit_price": 25.0, "cover_days": 3, "start_h": 11,
             "events": [(14, "TEMP_EXCURSION", {"temp_c": 14.0, "limit": "2 to 8 C", "minutes": 95})]},
        ],
    },
    {
        "id": "S5", "name": "Invoice price spike",
        "story": "An antimalarial invoice arrives at 1.7 times the usual unit price.",
        "expected": "Price anomaly flagged for finance with a robust z score",
        "shipments": [
            {"key": "S5_price", "product_name": "Artemether lumefantrine tablets (antimalarial)", "essential_goods_type": "medicine",
             "criticality": 5, "supplier_id": "SUPM01", "ship_mode": "Standard Class", "scheduled_days": 4, "real_days": 4,
             "total_qty": 400, "unit_price": 4.0, "invoice_multiplier": 1.7, "cover_days": 10, "start_h": 14, "events": []},
        ],
    },
    {
        "id": "S6", "name": "Short shipment of test kits",
        "story": "500 HIV rapid test kits were ordered but only 320 were dispatched.",
        "expected": "Quantity anomaly flagged and the shipment escalated",
        "shipments": [
            {"key": "S6_short", "product_name": "HIV rapid diagnostic test kits", "essential_goods_type": "medical_equipment",
             "criticality": 4, "supplier_id": "SUPM03", "ship_mode": "Standard Class", "scheduled_days": 4, "real_days": 5,
             "total_qty": 500, "shipped_qty": 320, "unit_price": 1.5, "cover_days": 3, "start_h": 17, "events": []},
        ],
    },
    {
        "id": "S7", "name": "Regional disruption",
        "story": "A storm closes roads in one region. Every open shipment there is delayed 3 days at once.",
        "expected": "Relief supplies rank above general goods among the affected shipments",
        "shipments": [
            {"key": "S7_ors", "product_name": "Oral rehydration salts, relief kits", "essential_goods_type": "relief_supplies",
             "criticality": 4, "supplier_id": "SUPM01", "ship_mode": "Standard Class", "scheduled_days": 4, "real_days": 7,
             "total_qty": 1000, "unit_price": 2.0, "cover_days": 2, "start_h": 20, "events": []},
            {"key": "S7_general", "product_name": "Folding chairs, set of 4", "essential_goods_type": "other",
             "criticality": 1, "supplier_id": "SUPM04", "ship_mode": "Standard Class", "scheduled_days": 4, "real_days": 7,
             "total_qty": 50, "unit_price": 20.0, "cover_days": 20, "start_h": 20.2, "events": []},
        ],
        "broadcast": (40, "REGION_DISRUPTION", {"delay_days": 3, "reason": "storm, roads closed"}),
    },
]


def inject(engine, start_ts, base_row, storm_region=None):
    """Add scenario suppliers, shipments and events to a replay Engine. Returns the scenario table rows."""
    for sid, name, dept, delivered, on_time, total, quality in SUPPLIERS:
        engine.book.seed(sid, name, dept, delivered, on_time, total, quality)

    events, rows, next_id = [], [], 900001
    calm_region = base_row["order_region"]
    storm_region = storm_region or calm_region
    for sc in SCENARIOS:
        region = storm_region if "broadcast" in sc else calm_region
        keys = []
        for i, s in enumerate(sc["shipments"]):
            oid = next_id
            next_id += 1
            ts = start_ts + pd.Timedelta(hours=s["start_h"])
            pid = 990000 + oid % 1000
            rec = dict(base_row)
            rec.update({
                "order_id": oid, "order_ts": ts, "scheduled_days": float(s["scheduled_days"]),
                "real_days": float(s["real_days"]), "late": int(s["real_days"] > s["scheduled_days"]), "canceled": 0,
                "ship_mode": s["ship_mode"], "order_region": region, "department": engine.book.meta[s["supplier_id"]]["department"],
                "category": s["essential_goods_type"], "product_id": pid, "product_name": s["product_name"],
                "unit_price": s["unit_price"], "total_qty": s["total_qty"], "total_sales": round(s["unit_price"] * s["total_qty"], 2),
                "supplier_id": s["supplier_id"], "supplier_name": engine.book.meta[s["supplier_id"]]["name"],
                "criticality": int(s["criticality"]), "essential_goods_type": s["essential_goods_type"],
                "promised_ts": ts + pd.Timedelta(days=s["scheduled_days"]),
                "order_dow": ts.dayofweek, "order_month": ts.month, "order_hour": ts.hour,
                "scenario": sc["id"], "scenario_key": s["key"],
            })
            engine.orders[oid] = rec
            engine.cover[oid] = float(s["cover_days"])
            engine.prices.median[pid] = s["unit_price"]
            engine.prices.mad[pid] = 0.0
            keys.append({"key": s["key"], "shipment_id": oid})

            inv_price = round(s["unit_price"] * s.get("invoice_multiplier", 1.0), 2)
            seq = [(0, "ORDER_PLACED", {}), (0.5, "INVOICE", {"unit_price": inv_price}),
                   (3, "DISPATCHED", {"shipped_qty": int(s.get("shipped_qty", s["total_qty"]))})]
            seq += list(s["events"])
            seq.append((24 * s["real_days"] + 2, "DELIVERED", {}))
            for h, kind, payload in seq:
                events.append({"sim_ts": ts + pd.Timedelta(hours=h), "shipment_id": oid, "type": kind, "payload": dict(payload)})
        if "broadcast" in sc:
            h, kind, payload = sc["broadcast"]
            payload = dict(payload, region=region)
            events.append({"sim_ts": start_ts + pd.Timedelta(hours=h), "shipment_id": 0, "type": kind, "payload": payload})
        rows.append({"id": sc["id"], "name": sc["name"], "story": sc["story"], "expected": sc["expected"],
                     "shipments": json.dumps(keys)})
    for e in events:
        e["event_id"] = f"E{next_id:06d}"
        next_id += 1
    return events, rows
