"""Step 1: turn the DataCo order item CSV into one row per shipment (order).

    python prepare_data.py
Output: data/orders.pkl
"""
import numpy as np
import pandas as pd

from config import CRITICALITY, DEFAULT_CRITICALITY, ESSENTIAL_GOODS_CRITICALITY, ESSENTIAL_GOODS_KEYWORDS, ORDERS_PKL, PRIOR_K, RAW_CSV

COLS = [
    "Order Id", "order date (DateOrders)", "Days for shipping (real)", "Days for shipment (scheduled)",
    "Late_delivery_risk", "Delivery Status", "Shipping Mode", "Market", "Order Region",
    "Department Name", "Category Name", "Customer Segment", "Order Item Quantity", "Sales",
    "Order Item Product Price", "Product Card Id", "Product Name", "Order Status",
]


def load_raw(path=RAW_CSV) -> pd.DataFrame:
    df = pd.read_csv(path, encoding="latin-1", usecols=lambda c: c in COLS)
    missing = set(COLS) - set(df.columns)
    if missing:
        raise SystemExit(f"CSV is missing columns: {sorted(missing)}")
    df["order_ts"] = pd.to_datetime(df["order date (DateOrders)"], format="%m/%d/%Y %H:%M", errors="coerce")
    if df["order_ts"].isna().mean() > 0.5:  # fall back to automatic parsing
        df["order_ts"] = pd.to_datetime(df["order date (DateOrders)"], errors="coerce")
    return df.dropna(subset=["order_ts"])


def to_orders(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values(["Order Id", "Sales"], ascending=[True, False])
    g = df.groupby("Order Id", sort=False)
    main = g.first()  # the highest value item represents the shipment
    o = pd.DataFrame({
        "order_id": main.index.astype(int),
        "order_ts": main["order_ts"].values,
        "scheduled_days": main["Days for shipment (scheduled)"].astype(float).values,
        "real_days": main["Days for shipping (real)"].astype(float).values,
        "late": main["Late_delivery_risk"].astype(int).values,
        "canceled": (main["Delivery Status"] == "Shipping canceled").astype(int).values,
        "ship_mode": main["Shipping Mode"].values,
        "market": main["Market"].values,
        "order_region": main["Order Region"].values,
        "department": main["Department Name"].values,
        "category": main["Category Name"].values,
        "customer_segment": main["Customer Segment"].values,
        "product_id": main["Product Card Id"].astype(int).values,
        "product_name": main["Product Name"].values,
        "unit_price": main["Order Item Product Price"].astype(float).values,
        "total_qty": g["Order Item Quantity"].sum().values,
        "total_sales": g["Sales"].sum().round(2).values,
    })
    # DataCo has no supplier field: a supplier = department fulfilment hub per market (documented assumption)
    o["supplier_name"] = o["department"] + " Supply " + o["market"]
    names = sorted(o["supplier_name"].unique())
    sid = {n: f"SUP{i:03d}" for i, n in enumerate(names)}
    o["supplier_id"] = o["supplier_name"].map(sid)
    def classify_essential_goods(product_name):
        name = str(product_name).lower()
        for goods_type, keywords in ESSENTIAL_GOODS_KEYWORDS.items():
            if any(keyword in name for keyword in keywords):
                return goods_type
        return "other"

    o["essential_goods_type"] = o["product_name"].map(classify_essential_goods)
    # Product-name matches take precedence. Otherwise use a lower, broad department
    # fallback; Health and Beauty alone is not proof that an item is medicine.
    o["criticality"] = o["department"].map(CRITICALITY).fillna(DEFAULT_CRITICALITY).astype(int)
    matched = o["essential_goods_type"] != "other"
    o.loc[matched, "criticality"] = o.loc[matched, "essential_goods_type"].map(ESSENTIAL_GOODS_CRITICALITY).astype(int)
    o["promised_ts"] = o["order_ts"] + pd.to_timedelta(o["scheduled_days"], unit="D")
    o["order_dow"] = o["order_ts"].dt.dayofweek
    o["order_month"] = o["order_ts"].dt.month
    o["order_hour"] = o["order_ts"].dt.hour
    o = o.sort_values("order_ts").reset_index(drop=True)

    # Supplier history known before each order (Bayesian shrunk late rate, no look ahead)
    prior = o["late"].mean()
    past_late = o.groupby("supplier_id")["late"].cumsum() - o["late"]
    past_n = o.groupby("supplier_id").cumcount()
    o["sup_late_rate"] = (past_late + PRIOR_K * prior) / (past_n + PRIOR_K)
    o["sup_n_orders"] = past_n
    return o


if __name__ == "__main__":
    raw = load_raw()
    orders = to_orders(raw)
    ORDERS_PKL.parent.mkdir(parents=True, exist_ok=True)
    orders.to_pickle(ORDERS_PKL)
    print(f"{len(raw)} items -> {len(orders)} shipments, {orders['supplier_id'].nunique()} suppliers")
    print(f"Late rate {orders['late'].mean():.3f}, canceled {orders['canceled'].mean():.3f}")
    print(orders.head(3).T)
