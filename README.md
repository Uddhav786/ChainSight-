# ChainSight

### Health-First, Dynamic Supply-Chain Risk Intelligence on IBM LinuxONE

**ChainSight prioritizes what matters most when supply chains are under pressure.** Not every delayed shipment has the same consequences. A delay affecting essential medicines or other critical health products can be far more consequential than a delay affecting a routine package.

ChainSight continuously evaluates shipment events and dynamically ranks shipments based on **health criticality, delivery-breach risk, urgency, stockout exposure, and supplier reliability**. As operational conditions change, shipment priorities can change too, helping teams identify which shipments need attention first and where intervention may be necessary.

The platform combines predictive delivery-risk models, event-driven scoring, explainable priority rankings, counterfactual intervention options, and an optional generative-AI reviewer. A live dashboard makes shipment priorities, risk drivers, anomalies, recommendations, and approval status visible to decision-makers.

Running on **IBM LinuxONE with Linux on `s390x`**, ChainSight demonstrates an explainable, event-driven approach to supply-chain risk intelligence on an enterprise computing platform.

**Our core idea:** Prioritize shipments by the potential consequences of failure, not just by their delivery status. Protect essential health products first while dynamically adapting to changing operational risks.

> **Demo status:** The project uses public/sample supply-chain data and
> simulated events. Medical classification and inventory coverage are
> demo proxies, not verified medical catalog data or live inventory
> feeds. See [Assumptions and
> limitations](#assumptions-and-limitations).

## What ChainSight Does

1. **Prioritizes essential health shipments:** Uses configurable criticality signals to give greater attention to shipments where delays or failures may have more serious consequences.
2. **Dynamically re-ranks shipments:** Updates operational priorities using delivery-breach risk, urgency, stockout exposure, supplier reliability, and shipment criticality.
3. **Predicts delivery risk:** Estimates delivery-time ranges and the probability of an SLA breach.
4. **Explains risk drivers:** Presents available model and scoring evidence to help teams understand why a shipment is prioritized.
5. **Detects operational disruptions:** Identifies or simulates delays, invoice-price spikes, quantity mismatches, and cold-chain excursions.
6. **Evaluates possible interventions:** Scores counterfactual options such as monitoring, shipment upgrades, supplier switching, shipment splitting, and replacement where applicable.
7. **Supports explainable decisions:** An optional LLM reviewer evaluates permitted actions against an evidence packet, with output validation and rule-based fallback.
8. **Keeps humans in control:** Persists alerts, recommendations, and approval states so consequential interventions can be reviewed.

For cold-chain scenarios, the safety policy can recommend replacement and require human approval even when the estimated financial net value is negative. This reflects the principle that protecting potentially compromised health products can take precedence over short-term shipment economics. It is a demonstration policy, not a substitute for clinical, regulatory, or quality-system approval.

## Architecture

```text
Shipment Data + Simulated Events
              |
              v
Feature Processing and ML Scoring
  - Delivery-time estimates (P10/P50/P90)
  - Calibrated SLA-breach probability
  - Model drivers, where supported
              |
              v
Event and Anomaly Processing
              |
              v
Dynamic Priority Engine
  - Health criticality
  - Delivery-breach risk
  - Urgency and stockout exposure
  - Supplier-aware ranking
              |
              v
Decision and Intervention Engine
  - Counterfactual action options
  - Safety and approval policies
              |
              v
Optional LLM Reviewer
  - Evidence-bounded recommendations
  - Schema, action, and citation validation
  - Rule-based fallback
              |
              v
SQLite Database
              |
              v
Live Dashboard
  - Ranked shipments
  - Risk drivers and alerts
  - Recommended interventions
  - Approval status
```
### IBM LinuxONE deployment

The Python pipeline is intended to run on an IBM LinuxONE VM using Linux
on `s390x`. `check_env.py` reports runtime architecture and package
information. Running on LinuxONE demonstrates deployment compatibility;
it does **not** by itself prove IBM-specific ML acceleration, configured
confidential computing, or production high availability.

## Repository map

  -----------------------------------------------------------------------
  File                                Purpose
  ----------------------------------- -----------------------------------
  `ChainSight.ipynb`                  Notebook walkthrough for platform,
                                      data, training, replay, and
                                      evaluation

  `check_env.py`                      Reports architecture, package
                                      environment, and timing check

  `make_sample_data.py`               Generates sample data for
                                      development

  `prepare_data.py`                   Converts DataCo order data to
                                      shipment-level records and features

  `features.py`                       Shared feature builder

  `train.py`                          Trains delivery quantile models and
                                      calibrated breach classifier

  `books.py`                          Supplier statistics and
                                      price/quantity checks

  `scoring.py`                        Shipment scoring and model-driver
                                      explanations

  `decision.py`                       Priority calculation,
                                      counterfactual options,
                                      safety/approval policy

  `reasoner.py`                       Evidence packet, LLM backends,
                                      validation, fallback logic

  `scenarios.py`                      Labeled demo scenarios

  `replay.py`                         Event replay, scoring, and SQLite
                                      persistence

  `web_dashboard.py`                  Lightweight dashboard server using
                                      Python standard library

  `web/`                              Dashboard HTML, CSS, and JavaScript

  `app.py`                            Optional Streamlit dashboard

  `dashboard_lite.py`                 Alternative lightweight dashboard

  `evaluate.py`                       Evaluation report generation

  `config.py`                         Runtime settings and thresholds

  `test_scenarios.py`                 Scenario and priority regression
                                      tests

  `test_medical_priority.py`          Medical/essential-goods tests, if
                                      present

  `test_llm.py`                       LLM configuration smoke test

  -----------------------------------------------------------------------

## Requirements

-   IBM LinuxONE VM with a supported Linux image; the hackathon setup
    used Ubuntu 24.04 on `s390x`.
-   Python 3, `venv`, and compatible builds of NumPy, pandas,
    scikit-learn, joblib, requests, and Matplotlib.
-   Optional: LightGBM, if a compatible `s390x` build is available.
-   Optional: a real LLM endpoint. The mock reviewer supports offline
    demos.
-   SSH access to the VM and a browser on your laptop.

Package availability on `s390x` can differ from x86_64. Prefer versions
supported by the hackathon VM image.

## Quick start on IBM LinuxONE

### 1. Connect to the VM

Create the VM using the hackathon-provided Ubuntu image and download its
SSH key. The username may be `linux1` or `ubuntu`.

``` bash
chmod 600 chainsight.pem
scp -i chainsight.pem ChainSight_code.zip <VM_USER>@<VM_IP>:~/
ssh -i chainsight.pem <VM_USER>@<VM_IP>
```

Replace `<VM_USER>` and `<VM_IP>` with your VM details. Never share your
private SSH key.

### 2. Install dependencies

Run on the VM:

``` bash
sudo apt update
sudo apt install -y python3-venv python3-pip unzip
unzip ChainSight_code.zip
cd chainsight
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install numpy pandas scikit-learn joblib requests matplotlib jupyterlab
```

Optional:

``` bash
pip install lightgbm  # Skip if a compatible s390x build is unavailable
```

Check the environment:

``` bash
python check_env.py
python -c "import platform; print(platform.machine())"
```

On an `s390x` VM, the architecture should print `s390x`.

### 3. Prepare data

For the public DataCo dataset: 1. Obtain **DataCo Smart Supply Chain for
Big Data Analysis** from its source. 2. Place
`DataCoSupplyChainDataset.csv` in `data/`. 3. Follow the notebook or
data-preparation/training workflow in the current checkout.

Expected location: `chainsight/data/DataCoSupplyChainDataset.csv`.

If the source dataset is unavailable, use the sample-data workflow.
Check `make_sample_data.py` and `ChainSight.ipynb` for the exact
sequence.

### 4. Optional: run the notebook

On the VM:

``` bash
source .venv/bin/activate
jupyter lab --no-browser --port 8888
```

From a separate laptop terminal, open a tunnel:

``` bash
ssh -i chainsight.pem -L 8888:127.0.0.1:8888 <VM_USER>@<VM_IP>
```

Open the Jupyter token URL, replacing the host with `localhost:8888`.
Open `ChainSight.ipynb` and choose **Run → Run All Cells**.

## Run the live demo

Use two terminals on the VM, from the repository root, with `.venv`
activated.

### Terminal 1: replay events

``` bash
python replay.py --n 300 --speed 20000 --reset
```

Useful flags: - `--n 300`: number of test-period shipments to replay, in
addition to configured demo scenarios. - `--speed 20000`: simulated
seconds per real second. - `--speed 0`: replay without simulated
waiting. - `--reset`: recreates the configured SQLite database. Back up
any database you need before using it. - `--no-scenarios`: disables
injected demo scenarios. - `--n 0`: scenario-only workflow if supported
by the current checkout.

### Terminal 2: dashboard

``` bash
python web_dashboard.py --port 8501
```

The lightweight dashboard uses the Python standard library and avoids
the optional Streamlit/PyArrow dependency path. Keep it running.

### Laptop: SSH tunnel

``` bash
ssh -i chainsight.pem -N -L 8501:127.0.0.1:8501 <VM_USER>@<VM_IP>
```

Open **http://localhost:8501**. Keep the tunnel and dashboard processes
running during the demo.

Depending on the current checkout, the dashboard includes ranked at-risk
shipments, priority breakdown, alert details, model drivers,
counterfactual options, reviewer evidence, approval controls, scenarios,
suppliers, anomalies, and platform information.

## Configure the LLM reviewer

The mock backend supports offline demos. For a real LLM, configure
credentials before starting replay. Never commit API keys.

### OpenAI-compatible endpoint

``` bash
export LLM_BACKEND=openai
export LLM_BASE_URL="https://<your-endpoint>/v1"
export LLM_API_KEY="<your-api-key>"
export LLM_MODEL="<your-model>"
```

### IBM watsonx.ai

``` bash
pip install ibm-watsonx-ai
export LLM_BACKEND=watsonx
export WATSONX_URL="https://us-south.ml.cloud.ibm.com"
export WATSONX_APIKEY="<your-watsonx-api-key>"
export WATSONX_PROJECT_ID="<your-project-id>"
export LLM_MODEL="ibm/granite-3-8b-instruct"
```

Confirm the SDK call and supported model in `reasoner.py` for the
installed SDK version. The configured LLM call limit may send
lower-priority alerts through rule-based text. Invalid schema,
disallowed actions, or unsupported citations should be rejected by the
validator. If the VM cannot reach the endpoint, use the mock backend or
clearly disclose that the LLM component ran elsewhere.

## Tests and evaluation

Run available regression tests:

``` bash
python -m unittest -v test_scenarios.py test_medical_priority.py
```

If `test_medical_priority.py` is absent, run the tests that exist.
Smoke-test the LLM configuration:

``` bash
python test_llm.py
```

Generate an evaluation report:

``` bash
python replay.py --n 300 --speed 0 --reset
python evaluate.py
```

Check the report path emitted by `evaluate.py`; the current checkout may
write to `artifacts/eval_report.md`. Use only numbers from actual
evaluation outputs in slides. Clearly distinguish mock-reviewer results
from real-LLM results and state the dataset/split and scenario setup.

## Benchmarking on LinuxONE

For a reproducible systems benchmark, fix the workload and record: -
Events processed per second - Total replay duration - Per-event
processing latency - Model scoring latency - Dashboard/API latency -
Peak memory and CPU utilization - Errors and output consistency

Start with the same input and scenario configuration at several values
of `--n`, using `--speed 0` to remove simulated waiting. Repeat runs and
record the VM flavor, architecture, Python/package versions, model
artifacts, LLM backend, and database-reset policy.

For a fair cross-platform comparison, keep code revision, data, model
artifacts, dependency versions, VM sizing, and workload as comparable as
possible. A single run or different VM sizes do not establish an IBM
hardware speedup. This application benchmark is not, by itself, an
AssetOpsBench result.


## Assumptions and limitations

1.  **Supplier identity:** DataCo does not provide a verified supplier
    field for this implementation; a supplier proxy is derived from
    fulfillment/department and market information.
2.  **Criticality and medical classification:** A department mapping is
    used as a demo proxy, not a verified medical product catalog.
3.  **Inventory coverage:** Inventory cover is simulated, not connected
    to a live inventory system.
4.  **Anomalies and disruptions:** Delay events, price spikes, quantity
    mismatches, cold-chain excursions, and scenario labels are
    simulated. They are not live carrier or sensor feeds.
5.  **Event updates:** Some breach-probability changes use configured
    rules, not a model retrained after each event.
6.  **LLM evaluation:** Mock output is not evidence of real-LLM
    performance. Report real-LLM results only for runs that used a real
    endpoint.
7.  **Data infrastructure:** The hackathon build uses an in-process
    event loop and SQLite. Kafka, PostgreSQL, FastAPI, and Machine
    Learning for z/OS are production-design possibilities, not current
    implementation claims unless separately deployed.
8.  **Platform claims:** Running on LinuxONE demonstrates compatibility.
    It does not automatically demonstrate IBM-specific ML acceleration,
    configured confidential computing, or production high availability.
9.  **Operational use:** This demo is not a clinical,
    quality-management, or regulatory decision system. Consequential
    actions require human review.

## Security notes

-   Keep SSH private keys private and use restrictive permissions such
    as `chmod 600`.
-   Store API keys in environment variables or a secrets manager, not
    source files, notebooks, screenshots, or Git history.
-   Avoid committing `chainsight.db`, private datasets, `.venv/`, local
    logs, backups, or generated sensitive data unless intentionally
    publishing them.
-   Check dataset license and redistribution terms before committing or
    sharing it.
-   Prefer accessing services through an SSH tunnel. Expose ports
    publicly only when explicitly allowed by the environment's security
    policy.



**ChainSight's proposition:** turn shipment events into ranked,
explainable operational decisions, with explicit safety rules and human
oversight, in a reproducible IBM LinuxONE demo environment.
