"""Generative reasoning layer: the LLM reviews each alert and must cite its evidence.

Backends (set LLM_BACKEND):
  mock    deterministic offline reviewer, no network (default, good for demos and tests)
  openai  any OpenAI compatible endpoint: LLM_BASE_URL, LLM_API_KEY, LLM_MODEL
  watsonx IBM watsonx.ai via the ibm-watsonx-ai SDK: WATSONX_URL, WATSONX_APIKEY, WATSONX_PROJECT_ID, LLM_MODEL
Every answer passes through validate(); anything invalid falls back to a rule based alert.
"""
import json
import os
import re
import time

from config import LLM_BACKEND

SYSTEM = (
    "You are a supply chain risk reviewer. You receive a JSON evidence packet about one shipment. "
    "Use ONLY that evidence. Return ONLY a JSON object with keys: "
    "verdict (CONFIRM, DOWNGRADE or DISMISS), root_cause (one sentence), "
    "recommended_action (must be one of the option actions in the packet), justification (two sentences max), "
    "citations (list of evidence ids you relied on, taken from evidence_ids), "
    "draft_email (short message to the supplier or carrier, under 90 words). "
    "Every claim must be supported by a cited evidence id. Do not invent numbers."
)

VERDICTS = {"CONFIRM", "DOWNGRADE", "DISMISS"}


def evidence_packet(shipment, base, drivers, events, opts, supplier, cover_days, anomalies):
    ev = []
    for d in drivers:
        ev.append({"id": f"feature:{d['feature']}", "text": f"{d['label']} = {d['value']} (contribution {d['contribution']:+.3f} {d['unit']})"})
    for e in events:
        ev.append({"id": e["event_id"], "text": f"{e['type']} at {e['sim_ts']} {e.get('note', '')}".strip()})
    for a in anomalies:
        ev.append({"id": f"anomaly:{a['event_id']}", "text": f"{a['kind']}: {a['detail']}"})
    ev.append({"id": "supplier_score", "text": f"{supplier['name']} score {supplier['score']} on {supplier['n_orders']} delivered orders"})
    ev.append({"id": "inventory_cover", "text": f"destination inventory covers {cover_days:.1f} days"})
    ev.append({"id": "model_breach", "text": f"calibrated breach probability {base['breach_prob']:.2f}, "
                                              f"delivery days P10/P50/P90 {base['eta_p10']:.1f}/{base['eta_p50']:.1f}/{base['eta_p90']:.1f}"})
    for o in opts:
        ev.append({"id": f"option:{o['action']}", "text": f"{o['detail']}: breach after {o['breach_prob_after']}, "
                                                           f"days saved {o['days_saved']}, cost {o['added_cost']}, net {o['net_value']}"})
    return {
        "shipment_id": shipment["shipment_id"], "criticality": shipment["criticality"],
        "ship_mode": shipment["ship_mode"], "promised_days": shipment["scheduled_days"],
        "options": [o["action"] for o in opts], "evidence": ev, "evidence_ids": [e["id"] for e in ev],
    }


def validate(ans, packet):
    """Schema check plus grounding check: every citation must exist in the packet."""
    errs = []
    if not isinstance(ans, dict):
        return ["not a JSON object"]
    for k in ["verdict", "root_cause", "recommended_action", "justification", "citations", "draft_email"]:
        if k not in ans:
            errs.append(f"missing {k}")
    if errs:
        return errs
    if ans["verdict"] not in VERDICTS:
        errs.append("bad verdict")
    if ans["recommended_action"] not in packet["options"]:
        errs.append("action not in options")
    cites = ans["citations"] if isinstance(ans["citations"], list) else []
    if not cites:
        errs.append("no citations")
    allowed = set(packet["evidence_ids"])
    bad = [c for c in cites if c not in allowed]
    if bad:
        errs.append(f"uncited or unknown evidence {bad[:3]}")
    mentioned = set(re.findall(r"\bE\d{6}\b", json.dumps(ans)))
    if mentioned - allowed:
        errs.append("mentions event ids not in evidence")
    return errs


def _extract_json(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _call_openai(packet):
    import requests
    base = os.environ["LLM_BASE_URL"].rstrip("/")
    r = requests.post(f"{base}/chat/completions", timeout=60,
                      headers={"Authorization": f"Bearer {os.environ.get('LLM_API_KEY', '')}"},
                      json={"model": os.environ["LLM_MODEL"], "temperature": 0,
                            "messages": [{"role": "system", "content": SYSTEM},
                                         {"role": "user", "content": json.dumps(packet)}]})
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _call_watsonx(packet):
    # Verify against the SDK version from the IBM lab; this follows ibm-watsonx-ai 1.x
    from ibm_watsonx_ai import Credentials
    from ibm_watsonx_ai.foundation_models import ModelInference
    model = ModelInference(model_id=os.getenv("LLM_MODEL", "ibm/granite-3-8b-instruct"),
                           credentials=Credentials(url=os.environ["WATSONX_URL"], api_key=os.environ["WATSONX_APIKEY"]),
                           project_id=os.environ["WATSONX_PROJECT_ID"], params={"temperature": 0, "max_tokens": 600})
    out = model.chat(messages=[{"role": "system", "content": SYSTEM},
                               {"role": "user", "content": json.dumps(packet)}])
    return out["choices"][0]["message"]["content"]


def _mock(packet):
    """Offline reviewer with the same contract as the LLM, so the pipeline and UI work without keys."""
    ev = {e["id"]: e["text"] for e in packet["evidence"]}
    delays = [i for i in ev if i.startswith("E") and "DELAYED" in ev[i]]
    feats = [i for i in ev if i.startswith("feature:")]
    prob = float(re.search(r"probability ([0-9.]+)", ev["model_breach"]).group(1))
    sup = float(re.search(r"score ([0-9.]+)", ev["supplier_score"]).group(1))
    if delays or prob >= 0.85:
        verdict = "CONFIRM"
    elif prob < 0.78 and sup >= 62:
        verdict = "DISMISS"
    else:
        verdict = "DOWNGRADE"
    action = packet["options"][0] if verdict != "DISMISS" else "monitor"
    cites = (delays[:1] + feats[:2] + ["model_breach", f"option:{action}"])
    top = ev[feats[0]].split(" (")[0] if feats else "model risk"
    cause = "carrier reported a delay" if delays else f"risk driven mainly by {top}"
    return json.dumps({
        "verdict": verdict, "root_cause": cause.capitalize() + ".",
        "recommended_action": action,
        "justification": f"Breach probability is {prob:.2f} and the supplier score is {sup:.0f}. "
                         f"The chosen option has the best net value among the rescored options.",
        "citations": cites,
        "draft_email": f"Hello, shipment {packet['shipment_id']} is at risk of missing its promised date "
                       f"({cause}). Please confirm the current status today and whether {action.replace('_', ' ')} is possible.",
    })


def rule_alert(packet, opts, reason):
    best = opts[0]
    return {"verdict": "CONFIRM", "root_cause": "Model risk above threshold.", "recommended_action": best["action"],
            "justification": f"Rule based alert ({reason}). Best option by net value: {best['detail']}.",
            "citations": ["model_breach", f"option:{best['action']}"],
            "draft_email": f"Shipment {packet['shipment_id']} is at risk. Please confirm status.", "source": "rule"}


def review(packet, opts, use_llm=True):
    t = time.perf_counter()
    if not use_llm:
        ans = rule_alert(packet, opts, "LLM budget reached")
        ans["llm_ms"] = 0
        return ans
    backend = LLM_BACKEND
    try:
        text = {"mock": _mock, "openai": _call_openai, "watsonx": _call_watsonx}[backend](packet)
        ans = _extract_json(text)
        errs = validate(ans, packet)
        if errs:
            ans = rule_alert(packet, opts, "validator rejected LLM output: " + "; ".join(errs))
        else:
            ans["source"] = backend
    except Exception as exc:  # noqa: BLE001
        ans = rule_alert(packet, opts, f"LLM error {exc.__class__.__name__}")
    ans["llm_ms"] = round((time.perf_counter() - t) * 1000, 1)
    return ans
