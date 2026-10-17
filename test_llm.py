"""Check that the configured LLM is reachable and that its answer passes the validator.

    python test_llm.py
Uses the same LLM_BACKEND and variables as the rest of ChainSight. Screenshot a passing run.
"""
import json
import os
import time

import reasoner
from config import LLM_BACKEND

print("Backend:", LLM_BACKEND, "| model:", os.getenv("LLM_MODEL", "(default)"))
need = {"watsonx": ["WATSONX_URL", "WATSONX_APIKEY"], "openai": ["LLM_BASE_URL", "LLM_MODEL"]}.get(LLM_BACKEND, [])
missing = [v for v in need if not os.getenv(v)]
if LLM_BACKEND == "watsonx" and not (os.getenv("WATSONX_PROJECT_ID") or os.getenv("WATSONX_SPACE_ID")):
    missing.append("WATSONX_PROJECT_ID")
if missing:
    raise SystemExit(f"Missing environment variables: {missing}")

opts = [{"action": "expedite", "detail": "switch Standard Class to Same Day", "breach_prob_after": 0.31, "days_saved": 2.1,
         "added_cost": 25.0, "net_value": 180.0},
        {"action": "monitor", "detail": "keep plan, alert buyer", "breach_prob_after": 0.82, "days_saved": 0.0,
         "added_cost": 0.0, "net_value": 0.0}]
base = {"breach_prob": 0.82, "eta_p10": 4.0, "eta_p50": 5.5, "eta_p90": 7.0}
drivers = [{"feature": "ship_mode", "label": "shipping mode", "value": "Standard Class", "contribution": 0.9, "unit": "log odds"},
           {"feature": "sup_late_rate", "label": "supplier late rate", "value": 0.61, "contribution": 0.4, "unit": "log odds"}]
events = [{"event_id": "E000101", "type": "ORDER_PLACED", "sim_ts": "2017-09-01 10:00", "note": ""},
          {"event_id": "E000140", "type": "DELAYED", "sim_ts": "2017-09-03 08:00", "note": "delay 2 day(s)"}]
packet = reasoner.evidence_packet({"shipment_id": 12345, "criticality": 5, "ship_mode": "Standard Class", "scheduled_days": 4},
                                  base, drivers, events, opts, {"name": "Health and Beauty Supply LATAM", "score": 58.2, "n_orders": 340},
                                  2.5, [])

fn = {"mock": reasoner._mock, "openai": reasoner._call_openai, "watsonx": reasoner._call_watsonx}[LLM_BACKEND]
t = time.time()
try:
    text = fn(packet)
except Exception as exc:  # noqa: BLE001
    raise SystemExit(f"FAILED to reach the LLM: {exc.__class__.__name__}: {exc}")
print(f"Reply in {time.time() - t:.1f} s:\n{text}\n")
ans = reasoner._extract_json(text)
errs = reasoner.validate(ans, packet)
print("Validator:", "PASS" if not errs else f"REJECTED {errs}")
if not errs:
    print(json.dumps(ans, indent=2))
