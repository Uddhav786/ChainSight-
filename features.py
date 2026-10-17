"""One feature builder shared by training and live scoring, so the two can never drift apart."""
import pandas as pd

CAT_COLS = ["ship_mode", "market", "order_region", "department", "category", "customer_segment", "supplier_id"]
NUM_COLS = ["scheduled_days", "total_qty", "total_sales", "unit_price", "order_dow", "order_month",
            "order_hour", "sup_late_rate", "sup_n_orders"]
FEATURES = CAT_COLS + NUM_COLS


def fit_encoders(df: pd.DataFrame) -> dict:
    return {c: {v: i for i, v in enumerate(sorted(df[c].astype(str).unique()))} for c in CAT_COLS}


def build_matrix(df: pd.DataFrame, enc: dict) -> pd.DataFrame:
    X = pd.DataFrame(index=df.index)
    for c in CAT_COLS:
        X[c] = df[c].astype(str).map(enc[c]).fillna(-1).astype(int)  # unseen value -> -1 (missing)
    for c in NUM_COLS:
        X[c] = df[c].astype(float)
    return X[FEATURES]


def decode(enc: dict, col: str, code) -> str:
    if col not in enc:
        return code
    inv = {v: k for k, v in enc[col].items()}
    return inv.get(int(code), "unknown")
