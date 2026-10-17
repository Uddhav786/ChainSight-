"""Step 4: evaluation report from the trained models and the replay database.

    python evaluate.py
Prints and saves artifacts/eval_report.md. Numbers come only from real runs, never typed by hand.
"""
import json
import sqlite3

import pandas as pd

from config import ART_DIR, DB_PATH


def main():
    m = json.loads((ART_DIR / "metrics.json").read_text())
    db = sqlite3.connect(DB_PATH)
    alerts = pd.read_sql("SELECT * FROM alerts", db)
    ships = pd.read_sql("SELECT * FROM shipments", db)
    events = pd.read_sql("SELECT type, score_ms FROM events", db)
    anoms = pd.read_sql("SELECT kind FROM anomalies", db)

    done = ships[ships.status == "DELIVERED"]
    late_ids = set(done[done.actual_late == 1].shipment_id)
    raised = alerts.copy()
    kept = raised[raised.verdict != "DISMISS"]

    def recall(df):
        return len(set(df.shipment_id) & late_ids) / max(len(late_ids), 1)

    def precision(df):
        return df.actual_late.mean() if len(df) else float("nan")

    lead = []
    for r in kept[kept.actual_late == 1].itertuples():
        lead.append((pd.Timestamp(r.promised_ts) - pd.Timestamp(r.created_ts)).total_seconds() / 86400)
    false_raw = int((raised.actual_late == 0).sum())
    false_kept = int((kept.actual_late == 0).sum())

    lines = [
        "# ChainSight evaluation report", "",
        f"Model backend: {m['backend']}. Test period {m['test_period'][0]} to {m['test_period'][1]}.", "",
        "## Predictive models (test period)", "",
        "| Metric | Model | Baseline |", "| --- | --- | --- |",
        f"| Delivery days MAE | {m['eta_mae_days_model_p50']} | {m['eta_mae_days_baseline_scheduled']} (promised days) |",
        f"| P10 to P90 band coverage | {m['eta_p10_p90_coverage']} | target about 0.80 |",
        f"| Breach PR AUC | {m['breach_pr_auc']} | {m['breach_pr_auc_baseline_rate']} (late rate) |",
        f"| Breach ROC AUC | {m['breach_roc_auc']} | 0.5 |",
        f"| Brier score | {m['brier_calibrated']} calibrated | {m['brier_raw']} raw |", "",
        "## Live replay", "",
        "| Metric | Value |", "| --- | --- |",
        f"| Events scored | {len(events)} |",
        f"| Median processing time per event | {events.score_ms.median():.2f} ms |",
        f"| 95th percentile processing time | {events.score_ms.quantile(0.95):.2f} ms |",
        f"| Shipments delivered / late | {len(done)} / {len(late_ids)} |",
        f"| Alerts raised by models | {len(raised)} (precision {precision(raised):.2f}, recall {recall(raised):.2f}) |",
        f"| Alerts kept after GenAI review | {len(kept)} (precision {precision(kept):.2f}, recall {recall(kept):.2f}) |",
        f"| False alarms removed by review | {false_raw - false_kept} of {false_raw} |",
        f"| Median warning before promised date (true breaches) | {pd.Series(lead).median():.2f} days |" if lead else "| Median warning | n/a |",
        f"| Alerts needing one click approval | {int(kept.requires_approval.sum())} |",
        f"| Anomalies flagged | {len(anoms)} ({', '.join(f'{k}: {v}' for k, v in anoms.kind.value_counts().items())}) |",
        f"| Alert source mix | {', '.join(f'{k}: {v}' for k, v in raised.source.value_counts().items())} |",
    ]
    report = "\n".join(lines)
    (ART_DIR / "eval_report.md").write_text(report)
    print(report)


if __name__ == "__main__":
    main()
