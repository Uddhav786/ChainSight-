"""Priority, counterfactual options and the approval policy."""
import numpy as np

from config import MODE_COST_RATE, SWITCH_SUPPLIER_COST_RATE

FASTER = {"Standard Class": ["Second Class", "First Class", "Same Day"],
          "Second Class": ["First Class", "Same Day"], "First Class": ["Same Day"], "Same Day": []}


def priority(breach_prob, criticality, eta_days_left, cover_days, days_to_promise):
    """Risk priority: breach probability x criticality x stockout severity x urgency.

    Inventory cover is an estimate in days, not a substitute for live inventory.
    """
    breach_prob = float(np.clip(breach_prob, 0.0, 1.0))
    criticality = int(np.clip(criticality, 1, 5))
    stockout = float(np.clip(max(float(eta_days_left), 0.0) / max(float(cover_days), 0.5), 0.2, 1.0))
    urgency = 1.0 / (1.0 + max(float(days_to_promise), 0.0))
    urgency = 0.4 + 0.6 * urgency  # never fully zero
    return round(breach_prob * (criticality / 5) * stockout * urgency, 4)


def _benefit(p_before, p_after, days_saved, criticality, value):
    return (p_before - p_after) * criticality * value * 0.5 + max(days_saved, 0) * criticality * 2


def options(scorer, book, record, base):
    """Rescore the same shipment under each option and rank by net value."""
    value = max(float(record["total_sales"]), 50.0)
    crit = int(record["criticality"])
    mode = record["ship_mode"]
    opts = []

    for new_mode in FASTER.get(mode, []):
        r = dict(record, ship_mode=new_mode)
        cf = scorer.score(r, explain=False)
        cost = (MODE_COST_RATE.get(new_mode, 0.05) - MODE_COST_RATE.get(mode, 0)) * value
        days = base["eta_p50"] - cf["eta_p50"]
        name = "expedite" if new_mode == "Same Day" else "upgrade_mode"
        opts.append({"action": name, "detail": f"switch {mode} to {new_mode}",
                     "breach_prob_after": round(cf["breach_prob"], 3), "days_saved": round(days, 2),
                     "added_cost": round(cost, 2),
                     "net_value": round(_benefit(base["breach_prob"], cf["breach_prob"], days, crit, value) - cost, 2)})

    if FASTER.get(mode):
        fastest = FASTER[mode][-1]
        cf = scorer.score(dict(record, ship_mode=fastest), explain=False)
        p_after = 0.5 * (base["breach_prob"] + cf["breach_prob"])
        days = 0.5 * (base["eta_p50"] - cf["eta_p50"])
        cost = 0.5 * (MODE_COST_RATE.get(fastest, 0.05) - MODE_COST_RATE.get(mode, 0)) * value + 0.01 * value
        opts.append({"action": "split_shipment", "detail": f"send half now by {fastest}, rest by {mode}",
                     "breach_prob_after": round(p_after, 3), "days_saved": round(days, 2), "added_cost": round(cost, 2),
                     "net_value": round(_benefit(base["breach_prob"], p_after, days, crit, value) - cost, 2)})

    alt = book.best_in_department(record["department"], exclude=record["supplier_id"])
    if alt and book.score(alt) > book.score(record["supplier_id"]):
        r = dict(record, supplier_id=alt, sup_late_rate=book.late_rate(alt), sup_n_orders=book.n_orders(alt))
        cf = scorer.score(r, explain=False)
        cost = SWITCH_SUPPLIER_COST_RATE * value
        days = base["eta_p50"] - cf["eta_p50"]
        opts.append({"action": "switch_supplier", "detail": f"move to {book.meta[alt]['name']} (score {book.score(alt)})",
                     "supplier_id": alt, "breach_prob_after": round(cf["breach_prob"], 3), "days_saved": round(days, 2),
                     "added_cost": round(cost, 2),
                     "net_value": round(_benefit(base["breach_prob"], cf["breach_prob"], days, crit, value) - cost, 2)})

    opts.append({"action": "monitor", "detail": "keep plan, alert buyer and watch carrier events",
                 "breach_prob_after": round(base["breach_prob"], 3), "days_saved": 0.0, "added_cost": 0.0, "net_value": 0.0})
    return sorted(opts, key=lambda o: o["net_value"], reverse=True)


def needs_approval(action, criticality):
    """Alerts and draft emails run automatically; supplier switches and lifesaving goods need one click approval."""
    return action == "switch_supplier" or (criticality >= 5 and action != "monitor")
