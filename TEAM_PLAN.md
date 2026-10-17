# ChainSight: two person plan

Two people work in parallel and integrate twice. Only two contracts are shared, so neither person ever waits on the other.

## The contract between the two of you

| Shared item | Owner | Rule |
| --- | --- | --- |
| `data/orders.pkl` columns | Person 1 | Never remove or rename existing columns. New columns are fine. |
| `artifacts/models.joblib`, `metrics.json`, `split.json` | Person 1 | Rebuild with `python train.py`. Person 2 only reads them. |
| `Scorer.score(record)` in `scoring.py` | Person 1 | Keep the output keys: `eta_p10`, `eta_p50`, `eta_p90`, `breach_prob`, `drivers`. |
| `features.py` | Person 1 | A new feature must also be filled in `replay.py` `record()` if it depends on live history (tell Person 2). |
| `replay.py`, `scenarios.py`, `app.py`, `decision.py` | Person 2 | Person 1 never edits these. |

After every model change, Person 1 runs `python -m unittest test_scenarios.py test_medical_priority.py`. If those pass, the demo still works.

## Person 1: models and more data

| Hour | Task | Done when |
| --- | --- | --- |
| 0 to 1 | Run `prepare_data.py` and `train.py` on the real DataCo file on the VM. Save `metrics.json` as the baseline. | Baseline metrics screenshot |
| 1 to 4 | Add the USAID Supply Chain Shipment Pricing dataset (real HIV and malaria medicine shipments, with vendors and scheduled vs delivered dates) in a new `prepare_usaid.py`. Map it to the same columns as `orders.pkl`, add `source` = "usaid", and set `essential_goods_type` from the product group (antiretrovirals and antimalarials as medicine, test kits as medical equipment). Concatenate with DataCo. | `orders.pkl` holds both sources, and the medical rows are real, not keyword guesses |
| 4 to 6 | Tuning: lane late rate (region x ship mode history), quantity and value buckets, `source` as a feature, learning rate and leaves. Use the time based split only. | PR AUC and MAE beat the baseline in `metrics.json` |
| 6 to 7 | Check calibration (notebook section 4), retrain, hand over the artifacts. | **Integration 2** |
| 7 to 8 | Metrics slide: before and after, per source | Slide ready |

Check the USAID column names after downloading; the file uses names like vendor, scheduled delivery date, delivered to client date, shipment mode, country and product group. If USAID integration runs over 3 hours, stop and keep DataCo only. The scenarios already cover the medical story.

## Person 2: UI and replay (use cases)

Already done in this version:

1. `scenarios.py`: seven labeled use cases injected into the live stream and scored by the real models.
2. Supplier aware priority: priority = breach x criticality x stockout x urgency x supplier factor (0.75 for a perfect supplier, 1.25 for the worst).
3. New event types: TEMP_EXCURSION (cold chain) and REGION_DISRUPTION (one event delays every open shipment in a region).
4. New options: `replace_shipment` for spoiled or short stock, and `hold_invoice` for price spikes.
5. Dashboard: a Scenarios tab, a storm banner, goods labels, priority bars, and a priority factor breakdown on each alert.
6. `test_scenarios.py`: one test per scenario.

| Scenario | Use case | What the demo shows |
| --- | --- | --- |
| S1 | Priority by product type | Insulin and office paper, same lane, same delay: insulin ranks far higher |
| S2 | Priority by supplier | Identical vaccine orders: QuickShip (unreliable) ranks above CarePath, with a switch supplier option |
| S3 | Fair supplier scoring | A newcomer with 2 of 2 on time stays below a proven 480 of 500 supplier |
| S4 | Cold chain break | Temperature logger event: insulin pens flagged, replacement shipment needs one click approval |
| S5 | Finance anomaly | Antimalarial invoice at 1.7 times the usual price: hold invoice |
| S6 | Short shipment | 320 of 500 HIV test kits dispatched: replace the missing units |
| S7 | Regional disruption | A storm delays every open shipment in a region; relief supplies rank above general goods |

Next UI tasks, in order of demo value:

| Hour | Task |
| --- | --- |
| 0 to 2 | Top KPI row: medical shipments at risk, value at risk, alerts waiting for approval |
| 2 to 3 | **Integration 1:** rerun with Person 1's first real data artifacts, check the scenarios still pass |
| 3 to 5 | Live alert feed (newest first, colored by goods type), and an approval queue with Approve and Reject buttons |
| 5 to 6 | Supplier tab chart: score vs number of orders, so the shrinkage is visible |
| 6 to 7 | Demo speed control and a "start from scenario" button; connect the real LLM (`test_llm.py`) |
| 7 to 8 | **Integration 2**, full rehearsal with the real LLM |
| 8 to 10 | Record the video following the demo script below |

More scenario ideas, if time allows: a GenAI false alarm dismissal with the real LLM, a supplier whose score recovers over a week of deliveries, and an approval queue with three critical alerts at once.

## Demo script (about 3 minutes)

1. Platform tab: s390x, model backend, milliseconds per event (LinuxONE proof).
2. Live risk: events streaming, shipments ranked by priority.
3. Scenarios S1 and S2: same delay, but medicine and unreliable suppliers rise to the top.
4. Alert detail for S1 insulin: delivery band, drivers, priority breakdown, options, GenAI verdict with citations, draft email.
5. S4 cold chain: replacement needs one click approval. Click Approve.
6. S7 storm banner: many shipments delayed at once, relief supplies on top.
7. Suppliers: CarePath vs the newcomer.
8. Close with the evaluation report numbers.

## Honest labels for the pitch

The scenario shipments and the medical suppliers are scripted demo data, clearly marked (scenario column, SUPM supplier ids, shipment ids from 900001). Their risk scores come from the same trained models. DataCo has no medicines, so real medical evidence comes from the USAID data if Person 1 adds it. Inventory cover is simulated.
