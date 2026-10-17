"""Shared settings for ChainSight. Override anything with environment variables."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
RAW_CSV = Path(os.getenv("DATACO_CSV", DATA_DIR / "DataCoSupplyChainDataset.csv"))
ORDERS_PKL = DATA_DIR / "orders.pkl"
ART_DIR = ROOT / "artifacts"
DB_PATH = Path(os.getenv("CHAINSIGHT_DB", ROOT / "chainsight.db"))

# Time based split (fractions of orders sorted by order time)
TRAIN_FRAC, VAL_FRAC = 0.70, 0.15

# Supplier score: Bayesian shrinkage strength (pseudo orders at the prior)
PRIOR_K = 20

# Alerting
BREACH_THRESHOLD = float(os.getenv("BREACH_THRESHOLD", "0.70"))
PRIORITY_ALERT = float(os.getenv("PRIORITY_ALERT", "0.30"))  # also alert when priority is high even if breach risk is moderate
DELAY_EVENT_LIFT = 0.75          # a carrier DELAYED event removes 75% of the remaining on time chance

# LLM reasoning
LLM_BACKEND = os.getenv("LLM_BACKEND", "mock")       # mock | openai | watsonx
LLM_MAX_CALLS = int(os.getenv("LLM_MAX_CALLS", "40"))  # cap real LLM calls per replay run
LLM_MIN_PRIORITY = float(os.getenv("LLM_MIN_PRIORITY", "0.15"))

# Criticality by DataCo department is only a broad fallback. DataCo does not
# reliably identify medicines, so product-name keywords are used only as a demo
# proxy and must not be treated as verified medical-product classification.
CRITICALITY = {
    "Health and Beauty": 3,
    "Pet Shop": 3,
    "Outdoors": 3,
    "Technology": 3,
    "Fitness": 2,
    "Footwear": 2,
    "Apparel": 2,
    "Golf": 1,
    "Fan Shop": 1,
    "Book Shop": 1,
    "Discs Shop": 1,
}
DEFAULT_CRITICALITY = 2

# Conservative keyword-based demo classification. Extend only with validated catalog data.
ESSENTIAL_GOODS_KEYWORDS = {
    "medicine": ("medicine", "medication", "drug", "pharmaceutical", "pharma", "insulin", "vaccine", "hiv", "malaria", "antibiotic"),
    "medical_equipment": ("medical equipment", "syringe", "diagnostic", "medical device", "surgical"),
    "relief_supplies": ("relief", "emergency food", "food aid", "water aid"),
}
ESSENTIAL_GOODS_CRITICALITY = {"medicine": 5, "medical_equipment": 4, "relief_supplies": 4, "other": DEFAULT_CRITICALITY}

# Relative cost of shipping modes as a share of order value (used for net value of options)
MODE_COST_RATE = {"Standard Class": 0.00, "Second Class": 0.02, "First Class": 0.05, "Same Day": 0.10}
SWITCH_SUPPLIER_COST_RATE = 0.04
