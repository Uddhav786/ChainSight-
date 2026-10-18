import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    roc_auc_score,
    mean_absolute_error,
)

from config import ART_DIR, ORDERS_PKL
from scoring import Scorer
from features import build_matrix

OUT = ART_DIR
OUT.mkdir(parents=True, exist_ok=True)


def safe_auc(y, p):
    return float(roc_auc_score(y, p)) if len(np.unique(y)) == 2 else float("nan")


def calibration_table(y, p, bins=10):
    df = pd.DataFrame({"actual": y, "predicted": p})
    df["bin"] = pd.cut(
        df["predicted"],
        bins=np.linspace(0, 1, bins + 1),
        include_lowest=True,
        duplicates="drop",
    )
    return (
        df.groupby("bin", observed=False)
        .agg(
            count=("actual", "size"),
            mean_predicted=("predicted", "mean"),
            observed_late_rate=("actual", "mean"),
        )
        .reset_index()
    )


def top_risk_table(y, p):
    order = np.argsort(-p)
    rows = []
    total_positive = int(np.sum(y))
    for pct in (0.05, 0.10, 0.20):
        k = max(1, math.ceil(len(y) * pct))
        chosen = order[:k]
        tp = int(np.sum(y[chosen]))
        rows.append({
            "top_fraction": pct,
            "shipments_flagged": k,
            "precision": tp / k,
            "recall": tp / total_positive if total_positive else float("nan"),
            "late_shipments_captured": tp,
            "late_shipments_total": total_positive,
            "risk_cutoff": float(p[chosen[-1]]),
        })
    return pd.DataFrame(rows)


def main():
    orders_path = Path(ORDERS_PKL)
    model_path = OUT / "models.joblib"
    split_path = OUT / "split.json"

    for path in (orders_path, model_path, split_path):
        if not path.exists():
            raise FileNotFoundError(f"Required file missing: {path}")

    orders = pd.read_pickle(orders_path)
    split = json.loads(split_path.read_text())
    test_ids = set(split["test_order_ids"])

    test = orders[orders["order_id"].isin(test_ids)].copy()
    test = test[test["canceled"] == 0].sort_values("order_ts").reset_index(drop=True)

    if test.empty:
        raise ValueError("No uncanceled test shipments found.")
    for col in ("real_days", "late", "scheduled_days", "order_id"):
        if col not in test.columns:
            raise ValueError(f"Required test label/column missing: {col}")

    scorer = Scorer()
    X = build_matrix(test, scorer.enc)

    # Predictions from the already trained model. No retraining.
    q = np.sort(
        np.column_stack([
            scorer.regs[a].predict(X) for a in (0.1, 0.5, 0.9)
        ]),
        axis=1,
    )
    q = np.clip(q, 0, None)
    raw = scorer.clf.predict_proba(X)[:, 1]
    prob = np.clip(scorer.iso.predict(raw), 0, 1)

    y_days = test["real_days"].astype(float).to_numpy()
    y_late = test["late"].astype(int).to_numpy()
    scheduled = test["scheduled_days"].astype(float).to_numpy()

    # Overall metrics.
    coverage = (y_days >= q[:, 0]) & (y_days <= q[:, 2])
    brier = brier_score_loss(y_late, prob)
    prevalence = float(y_late.mean())
    baseline_brier = brier_score_loss(y_late, np.full(len(y_late), prevalence))
    ece_table = calibration_table(y_late, prob)
    valid_bins = ece_table.dropna(subset=["mean_predicted", "observed_late_rate"])
    ece = float(
        (
            valid_bins["count"]
            * (valid_bins["mean_predicted"] - valid_bins["observed_late_rate"]).abs()
        ).sum() / max(len(y_late), 1)
    )

    top = top_risk_table(y_late, prob)
    metrics = {
        "test_shipments_uncanceled": int(len(test)),
        "test_period_start": str(test["order_ts"].min()),
        "test_period_end": str(test["order_ts"].max()),
        "late_rate": prevalence,
        "eta_p50_mae_days": float(mean_absolute_error(y_days, q[:, 1])),
        "scheduled_baseline_mae_days": float(mean_absolute_error(y_days, scheduled)),
        "eta_mae_improvement_vs_scheduled": float(
            1 - mean_absolute_error(y_days, q[:, 1])
            / max(mean_absolute_error(y_days, scheduled), 1e-12)
        ),
        "p10_p90_coverage": float(coverage.mean()),
        "p10_p90_target_coverage": 0.80,
        "mean_p10_p90_interval_width_days": float(np.mean(q[:, 2] - q[:, 0])),
        "breach_roc_auc": safe_auc(y_late, prob),
        "breach_pr_auc": float(average_precision_score(y_late, prob)),
        "prevalence_baseline_pr_auc": prevalence,
        "brier_calibrated": float(brier),
        "brier_prevalence_baseline": float(baseline_brier),
        "brier_skill_vs_prevalence": float(
            1 - brier / baseline_brier if baseline_brier > 0 else float("nan")
        ),
        "expected_calibration_error_10_bins": ece,
    }

    # Evaluate groups only when explicit labels exist in the test data.
    subgroup_rows = []
    criticality_col = next(
        (c for c in ("criticality", "clinical_criticality") if c in test.columns),
        None,
    )
    if criticality_col:
        values = pd.to_numeric(test[criticality_col], errors="coerce")
        if values.notna().any():
            max_value = values.max()
            high_cutoff = 4 if max_value <= 5 else values.quantile(0.80)
            mask = values >= high_cutoff
            if mask.sum():
                subgroup_rows.append({
                    "group": f"High criticality ({criticality_col} >= {high_cutoff:g})",
                    "count": int(mask.sum()),
                    "late_rate": float(y_late[mask.to_numpy()].mean()),
                    "roc_auc": safe_auc(y_late[mask.to_numpy()], prob[mask.to_numpy()]),
                    "pr_auc": float(average_precision_score(
                        y_late[mask.to_numpy()], prob[mask.to_numpy()]
                    )),
                    "brier": float(brier_score_loss(
                        y_late[mask.to_numpy()], prob[mask.to_numpy()]
                    )),
                    "eta_p50_mae_days": float(mean_absolute_error(
                        y_days[mask.to_numpy()], q[mask.to_numpy(), 1]
                    )),
                    "p10_p90_coverage": float(coverage[mask.to_numpy()].mean()),
                })

    medical_col = next(
        (c for c in ("essential_goods_type", "goods_type", "clinical_category")
         if c in test.columns),
        None,
    )
    medical_found = False
    if medical_col:
        labels = test[medical_col].astype(str).str.lower()
        medical_mask = labels.str.contains(
            r"medical|medicine|medication|pharmaceutical|vaccine|clinical",
            regex=True,
            na=False,
        )
        if medical_mask.any():
            medical_found = True
            mask = medical_mask.to_numpy()
            subgroup_rows.append({
                "group": f"Medical label ({medical_col})",
                "count": int(mask.sum()),
                "late_rate": float(y_late[mask].mean()),
                "roc_auc": safe_auc(y_late[mask], prob[mask]),
                "pr_auc": float(average_precision_score(y_late[mask], prob[mask])),
                "brier": float(brier_score_loss(y_late[mask], prob[mask])),
                "eta_p50_mae_days": float(mean_absolute_error(y_days[mask], q[mask, 1])),
                "p10_p90_coverage": float(coverage[mask].mean()),
            })

    # Useful additional breakdowns for the actual DataCo test set.
    breakdown_rows = []
    for col in ("department", "ship_mode"):
        if col not in test.columns:
            continue
        for label, idx in test.groupby(col, dropna=False).groups.items():
            idx = np.asarray(list(idx), dtype=int)
            if len(idx) < 30:
                continue
            breakdown_rows.append({
                "feature": col,
                "group": str(label),
                "count": int(len(idx)),
                "late_rate": float(y_late[idx].mean()),
                "roc_auc": safe_auc(y_late[idx], prob[idx]),
                "pr_auc": float(average_precision_score(y_late[idx], prob[idx])),
                "brier": float(brier_score_loss(y_late[idx], prob[idx])),
                "eta_p50_mae_days": float(mean_absolute_error(y_days[idx], q[idx, 1])),
                "p10_p90_coverage": float(coverage[idx].mean()),
            })

    top.to_csv(OUT / "deep_eval_top_risk.csv", index=False)
    ece_table.to_csv(OUT / "deep_eval_calibration.csv", index=False)
    pd.DataFrame(subgroup_rows).to_csv(OUT / "deep_eval_criticality_medical.csv", index=False)
    pd.DataFrame(breakdown_rows).to_csv(OUT / "deep_eval_subgroups.csv", index=False)

    lines = [
        "# ChainSight Deep ML Evaluation",
        "",
        "Evaluation uses the existing trained artifacts and saved chronological test IDs.",
        "No model retraining was performed.",
        "",
        "## Test set",
        "",
        f"- Uncanceled shipments: {metrics['test_shipments_uncanceled']}",
        f"- Period: {metrics['test_period_start']} to {metrics['test_period_end']}",
        f"- Late rate: {prevalence:.3f}",
        "",
        "## ETA prediction",
        "",
        f"- P50 MAE: {metrics['eta_p50_mae_days']:.3f} days",
        f"- Scheduled baseline MAE: {metrics['scheduled_baseline_mae_days']:.3f} days",
        f"- Improvement vs scheduled baseline: {metrics['eta_mae_improvement_vs_scheduled']:.1%}",
        f"- P10 to P90 coverage: {metrics['p10_p90_coverage']:.3f} (nominal target 0.800)",
        f"- Mean interval width: {metrics['mean_p10_p90_interval_width_days']:.3f} days",
        "",
        "## Breach ranking and calibration",
        "",
        f"- ROC AUC: {metrics['breach_roc_auc']:.3f}",
        f"- PR AUC: {metrics['breach_pr_auc']:.3f}",
        f"- Prevalence baseline PR AUC: {metrics['prevalence_baseline_pr_auc']:.3f}",
        f"- Calibrated Brier score: {metrics['brier_calibrated']:.4f}",
        f"- Prevalence-only Brier baseline: {metrics['brier_prevalence_baseline']:.4f}",
        f"- Brier skill vs prevalence baseline: {metrics['brier_skill_vs_prevalence']:.3f}",
        f"- Expected calibration error (10 bins): {metrics['expected_calibration_error_10_bins']:.4f}",
        "",
        "### Top-risk capture",
        "",
        top.to_markdown(index=False),
        "",
        "Interpretation: precision is the share of selected shipments that were late. Recall is the share of all late shipments captured in that top-risk slice.",
        "",
        "## Criticality and medical subgroup",
        "",
    ]

    if subgroup_rows:
        lines.append(pd.DataFrame(subgroup_rows).to_markdown(index=False))
    else:
        lines.append(
            "Not evaluable from this test dataset: no explicit usable criticality or medical label was found. "
            "Do not treat synthetic demo scenarios as evidence of real medical subgroup performance."
        )

    lines += [
        "",
        "## Department and shipping mode breakdowns",
        "",
        pd.DataFrame(breakdown_rows).to_markdown(index=False)
        if breakdown_rows else "No eligible subgroup breakdowns were available.",
        "",
        "## Calibration bins",
        "",
        ece_table.to_markdown(index=False),
        "",
        "## Limitations",
        "",
        "- These results describe this historical test set, not current logistics conditions.",
        "- High-risk precision and recall depend on the chosen top-risk capacity.",
        "- Good ranking does not prove that predicted probabilities are calibrated.",
        "- High P10 to P90 coverage alone is not enough; interval width must also be considered.",
        "- Medical safety performance cannot be claimed without real labeled medical shipments and sufficient subgroup examples.",
    ]

    (OUT / "deep_eval_report.md").write_text("\n".join(lines))
    (OUT / "deep_eval_metrics.json").write_text(json.dumps(metrics, indent=2))

    print("\n".join(lines[:42]))
    print("\nSaved report:", OUT / "deep_eval_report.md")
    print("Saved metrics:", OUT / "deep_eval_metrics.json")
    print("Saved top-risk table:", OUT / "deep_eval_top_risk.csv")
    print("Saved calibration table:", OUT / "deep_eval_calibration.csv")
    print("Saved subgroup tables in artifacts/.")


if __name__ == "__main__":
    main()
