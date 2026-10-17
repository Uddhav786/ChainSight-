# ChainSight Deep ML Evaluation

Evaluation uses the existing trained artifacts and saved chronological test IDs.
No model retraining was performed.

## Test set

- Uncanceled shipments: 9437
- Period: 2017-09-05 12:59:00 to 2018-01-31 23:38:00
- Late rate: 0.575

## ETA prediction

- P50 MAE: 1.044 days
- Scheduled baseline MAE: 1.292 days
- Improvement vs scheduled baseline: 19.2%
- P10 to P90 coverage: 0.954 (nominal target 0.800)
- Mean interval width: 3.149 days

## Breach ranking and calibration

- ROC AUC: 0.777
- PR AUC: 0.837
- Prevalence baseline PR AUC: 0.575
- Calibrated Brier score: 0.1746
- Prevalence-only Brier baseline: 0.2443
- Brier skill vs prevalence baseline: 0.285
- Expected calibration error (10 bins): 0.0106

### Top-risk capture

|   top_fraction |   shipments_flagged |   precision |    recall |   late_shipments_captured |   late_shipments_total |   risk_cutoff |
|---------------:|--------------------:|------------:|----------:|--------------------------:|-----------------------:|--------------:|
|           0.05 |                 472 |    0.997881 | 0.0867403 |                       471 |                   5430 |      1        |
|           0.1  |                 944 |    0.998941 | 0.173665  |                       943 |                   5430 |      1        |
|           0.2  |                1888 |    0.980932 | 0.341068  |                      1852 |                   5430 |      0.853659 |

Interpretation: precision is the share of selected shipments that were late. Recall is the share of all late shipments captured in that top-risk slice.

## Criticality and medical subgroup

Not evaluable from this test dataset: no explicit usable criticality or medical label was found. Do not treat synthetic demo scenarios as evidence of real medical subgroup performance.

## Department and shipping mode breakdowns

| feature    | group             |   count |   late_rate |    roc_auc |   pr_auc |       brier |   eta_p50_mae_days |   p10_p90_coverage |
|:-----------|:------------------|--------:|------------:|-----------:|---------:|------------:|-------------------:|-------------------:|
| department | Apparel           |    2321 |    0.573029 |   0.772315 | 0.827452 | 0.177227    |        1.07165     |           0.970702 |
| department | Book Shop         |     391 |    0.585678 |   0.778492 | 0.845623 | 0.175014    |        1.05753     |           0.849105 |
| department | Discs Shop        |    1943 |    0.567679 |   0.745074 | 0.807108 | 0.184813    |        1.06632     |           0.941843 |
| department | Fan Shop          |    1260 |    0.566667 |   0.768547 | 0.831165 | 0.17714     |        1.04768     |           0.922222 |
| department | Fitness           |     400 |    0.59     |   0.786585 | 0.853492 | 0.167404    |        1.00634     |           0.97     |
| department | Footwear          |     210 |    0.533333 |   0.771319 | 0.813962 | 0.169664    |        0.908522    |           0.985714 |
| department | Golf              |     141 |    0.58156  |   0.75     | 0.820545 | 0.186557    |        1.07919     |           0.992908 |
| department | Health and Beauty |     346 |    0.583815 |   0.777778 | 0.836586 | 0.173096    |        0.990422    |           0.976879 |
| department | Outdoors          |     557 |    0.585278 |   0.78096  | 0.838985 | 0.173664    |        1.06816     |           0.962298 |
| department | Pet Shop          |     472 |    0.614407 |   0.802368 | 0.872141 | 0.160985    |        1.0066      |           0.96822  |
| department | Technology        |    1396 |    0.577364 |   0.818846 | 0.866531 | 0.160464    |        1.0071      |           0.972063 |
| ship_mode  | First Class       |    1438 |    1        | nan        | 1        | 0           |        7.53402e-06 |           1        |
| ship_mode  | Same Day          |     509 |    0.532417 |   1        | 1        | 4.36358e-07 |        1.46759     |           0.532417 |
| ship_mode  | Second Class      |    1843 |    0.802496 |   0.505249 | 0.802842 | 0.159174    |        1.21047     |           0.974498 |
| ship_mode  | Standard Class    |    5647 |    0.397025 |   0.505029 | 0.401945 | 0.239812    |        1.21817     |           0.973083 |

## Calibration bins

| bin           |   count |   mean_predicted |   observed_late_rate |
|:--------------|--------:|-----------------:|---------------------:|
| (-0.001, 0.1] |     238 |      9.30442e-05 |             0        |
| (0.1, 0.2]    |       0 |    nan           |           nan        |
| (0.2, 0.3]    |       0 |    nan           |           nan        |
| (0.3, 0.4]    |    3506 |      0.384405    |             0.394752 |
| (0.4, 0.5]    |    2129 |      0.413591    |             0.400658 |
| (0.5, 0.6]    |       8 |      0.544882    |             0.5      |
| (0.6, 0.7]    |       2 |      0.659424    |             0        |
| (0.7, 0.8]    |    1569 |      0.789842    |             0.803059 |
| (0.8, 0.9]    |     268 |      0.841149    |             0.798507 |
| (0.9, 1.0]    |    1717 |      1           |             0.998835 |

## Limitations

- These results describe this historical test set, not current logistics conditions.
- High-risk precision and recall depend on the chosen top-risk capacity.
- Good ranking does not prove that predicted probabilities are calibrated.
- High P10 to P90 coverage alone is not enough; interval width must also be considered.
- Medical safety performance cannot be claimed without real labeled medical shipments and sufficient subgroup examples.