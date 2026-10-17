"""Generate a small CSV with the same columns as the Kaggle DataCo dataset.

Use it to test the whole pipeline before the real dataset is downloaded:
    python make_sample_data.py --orders 6000
"""
import argparse

import numpy as np
import pandas as pd

from config import RAW_CSV

DEPARTMENTS = {
    "Health and Beauty": ["Health and Beauty", "Personal Care"],
    "Outdoors": ["Camping & Hiking", "Hunting & Shooting"],
    "Technology": ["Computers", "Electronics"],
    "Fitness": ["Cardio Equipment", "Fitness Accessories"],
    "Apparel": ["Men's Clothing", "Women's Apparel"],
    "Footwear": ["Cleats", "Shoes"],
    "Golf": ["Golf Balls", "Golf Gloves"],
    "Fan Shop": ["Fishing", "Water Sports"],
    "Pet Shop": ["Pet Supplies"],
}
MARKETS = {
    "LATAM": ["Central America", "South America", "Caribbean"],
    "Europe": ["Western Europe", "Northern Europe"],
    "Pacific Asia": ["Southeast Asia", "South Asia"],
    "USCA": ["US Center", "East of USA", "West of USA"],
    "Africa": ["West Africa", "East Africa"],
}
MODES = ["Standard Class", "Second Class", "First Class", "Same Day"]
MODE_P = [0.60, 0.20, 0.15, 0.05]
SCHED = {"Standard Class": 4, "Second Class": 2, "First Class": 1, "Same Day": 0}
BASE_LATE = {"Standard Class": 0.38, "Second Class": 0.75, "First Class": 0.90, "Same Day": 0.45}


def main(n_orders: int, seed: int) -> None:
    rng = np.random.default_rng(seed)
    products = []
    pid = 1000
    for dept, cats in DEPARTMENTS.items():
        for cat in cats:
            for k in range(4):
                products.append((pid, f"{cat} item {k + 1}", dept, cat, float(rng.choice([19.99, 39.99, 59.99, 129.99, 299.99]))))
                pid += 1
    bias = {(d, m): rng.normal(0, 0.08) for d in DEPARTMENTS for m in MARKETS}

    start = pd.Timestamp("2015-01-01")
    span_min = int((pd.Timestamp("2017-12-31") - start).total_seconds() // 60)
    order_minutes = np.sort(rng.integers(0, span_min, n_orders))

    rows = []
    item_id = 1
    for i, om in enumerate(order_minutes):
        order_id = 10000 + i
        ts = start + pd.Timedelta(minutes=int(om))
        market = rng.choice(list(MARKETS))
        region = rng.choice(MARKETS[market])
        mode = rng.choice(MODES, p=MODE_P)
        segment = rng.choice(["Consumer", "Corporate", "Home Office"], p=[0.5, 0.3, 0.2])
        n_items = int(rng.integers(1, 4))
        items = [products[int(rng.integers(0, len(products)))] for _ in range(n_items)]
        dept = items[0][2]
        p_late = float(np.clip(BASE_LATE[mode] + bias[(dept, market)], 0.02, 0.98))
        sched = SCHED[mode]
        canceled = rng.random() < 0.02
        late = rng.random() < p_late
        if late:
            real = sched + int(rng.integers(1, 3))
        else:
            real = max(0, sched - int(rng.integers(0, 2)))
        if canceled:
            status, order_status = "Shipping canceled", "CANCELED"
        elif late:
            status, order_status = "Late delivery", "COMPLETE"
        elif real < sched:
            status, order_status = "Advance shipping", "COMPLETE"
        else:
            status, order_status = "Shipping on time", "COMPLETE"
        for p in items:
            qty = int(rng.integers(1, 5))
            rows.append({
                "Type": "DEBIT",
                "Days for shipping (real)": real,
                "Days for shipment (scheduled)": sched,
                "Delivery Status": status,
                "Late_delivery_risk": int(real > sched),
                "Category Name": p[3],
                "Customer Segment": segment,
                "Department Name": p[2],
                "Market": market,
                "Order Country": region,
                "order date (DateOrders)": ts.strftime("%m/%d/%Y %H:%M"),
                "Order Id": order_id,
                "Order Item Id": item_id,
                "Order Item Product Price": p[4],
                "Order Item Quantity": qty,
                "Sales": round(p[4] * qty, 2),
                "Order Region": region,
                "Order Status": order_status,
                "Product Card Id": p[0],
                "Product Name": p[1],
                "Product Price": p[4],
                "shipping date (DateOrders)": (ts + pd.Timedelta(days=real)).strftime("%m/%d/%Y %H:%M"),
                "Shipping Mode": mode,
            })
            item_id += 1
    RAW_CSV.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(RAW_CSV, index=False, encoding="latin-1")
    print(f"Wrote {len(rows)} order items for {n_orders} orders to {RAW_CSV}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--orders", type=int, default=6000)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    main(a.orders, a.seed)
