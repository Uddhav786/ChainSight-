# ChainSight: step by step run guide

ChainSight replays supply chain events as a live stream on IBM LinuxONE. Every event is scored by predictive models: delivery date band, calibrated SLA breach probability, supplier score and anomaly checks. Each risky shipment gets fix options rescored as counterfactuals, and a generative AI reviewer has to cite its evidence. A live dashboard shows everything.

The whole pipeline has been run end to end on sample data, including the notebook.

## Files

| File | What it does | Owner |
| --- | --- | --- |
| `ChainSight.ipynb` | JupyterLab notebook that runs the whole pipeline with charts (the "ML on LinuxONE" demo) | Everyone |
| `check_env.py` | Prints the architecture, packages and a timing test (first screenshot for judges) | A |
| `make_sample_data.py` | Creates a sample CSV with the DataCo columns, so everyone can start before the real data arrives | B |
| `prepare_data.py` | Turns DataCo order items into one row per shipment, adds supplier and criticality columns and the supplier history feature | B |
| `features.py` | One feature builder shared by training and live scoring | C |
| `train.py` | Quantile delivery models (P10, P50, P90) and the calibrated breach classifier, on a time based split | C |
| `books.py` | Bayesian supplier scores, robust z price check, quantity check | B |
| `scoring.py` | Scores one shipment and explains it (TreeSHAP from LightGBM) | C |
| `decision.py` | Priority formula, counterfactual options, approval policy | C |
| `reasoner.py` | LLM evidence packet, prompt, validator, mock and real backends, rule fallback | D |
| `replay.py` | Builds the event stream, scores every event, writes to SQLite | A |
| `app.py` | Streamlit dashboard | D |
| `dashboard_lite.py` | Fallback dashboard that needs only the Python standard library | A |
| `evaluate.py` | Evaluation report built from real runs | B |
| `config.py` | All settings: thresholds, criticality map, LLM backend | Everyone |

## Step 1: log in to the LinuxONE VM

Create the VM with the image **Ubuntu24.04-Datathon** and the flavor **AI_LAB**, and download the SSH key. Then, from your laptop:

```bash
chmod 600 chainsight.pem
scp -i chainsight.pem ChainSight_code.zip ubuntu@<VM_IP>:~/      # the user may be linux1 instead of ubuntu
ssh -i chainsight.pem ubuntu@<VM_IP>
```

To let teammates in, add each person's public key to `~/.ssh/authorized_keys` on the VM. Never share the private key.

## Step 2: install (one time, about 15 minutes)

On the VM:

```bash
sudo apt update && sudo apt install -y python3-venv python3-pip unzip
unzip ChainSight_code.zip && cd chainsight
python3 -m venv .venv && source .venv/bin/activate
pip install --upgrade pip
pip install numpy pandas scikit-learn joblib requests matplotlib jupyterlab
pip install lightgbm      # optional: if it fails or takes forever, skip it (scikit-learn is used instead)
pip install streamlit     # optional: if it fails, use dashboard_lite.py
python check_env.py       # SCREENSHOT: it shows s390x
```

If a package has no s390x build and pip tries to compile it for too long, ask the organizers which Python environment the IBM AI labs used and install into that one instead.

## Step 3: open JupyterLab

On the VM, in the `chainsight` folder:

```bash
source .venv/bin/activate
jupyter lab --no-browser --port 8888
```

Copy the link with `token=` that it prints. Then on your laptop, open a tunnel. It also forwards the dashboard port you'll use later.

```bash
ssh -i chainsight.pem -L 8888:localhost:8888 -L 8501:localhost:8501 ubuntu@<VM_IP>
```

Paste the link into your browser, replacing the host part with `localhost:8888`. If the VM image already has JupyterLab running from the IBM lab, just open it and upload the zip there.

## Step 4: get the data

1. On a laptop, download "DataCo Smart Supply Chain for Big Data Analysis" from Kaggle. You need the file `DataCoSupplyChainDataset.csv`.
2. Upload it into `chainsight/data/` with JupyterLab's upload button, or copy it over with scp:
   ```bash
   scp -i chainsight.pem DataCoSupplyChainDataset.csv ubuntu@<VM_IP>:~/chainsight/data/
   ```
3. If you skip this step, the notebook generates sample data automatically, so nobody has to wait.

## Step 5: run the notebook

Open `ChainSight.ipynb` and choose Run > Run All Cells. It takes about a minute on sample data and a few minutes on the full DataCo file.

| Section | What you get |
| --- | --- |
| 1 Platform check | s390x proof (screenshot) |
| 2 Data | Shipments table, late rate, supplier count |
| 3 Train | Metrics: delivery MAE against promised days, band coverage, PR AUC against the late rate, Brier before and after calibration |
| 4 Inside the models | Calibration chart, delivery band chart, supplier leaderboard, the newcomer vs proven supplier example |
| 5 One shipment | Drivers, counterfactual options, GenAI verdict with citations, validator rejecting a fake citation |
| 6 Replay | A short live replay so there is data to evaluate |
| 7 Evaluation | The report to use on slides |

The scripts also run on their own from a terminal (`python train.py` and so on), and the results are the same.

## Step 6: live demo (two JupyterLab terminals)

In JupyterLab, choose File > New > Terminal twice.

Terminal 1, the event stream:
```bash
cd ~/chainsight && source .venv/bin/activate
python replay.py --n 1500 --speed 20000 --reset
```

Terminal 2, the dashboard:
```bash
cd ~/chainsight && source .venv/bin/activate
streamlit run app.py --server.port 8501 --server.address 0.0.0.0
# fallback: python dashboard_lite.py --port 8501
```

Open http://localhost:8501 on your laptop (through the tunnel from Step 3). The dashboard has five tabs: Live risk, Alert detail (delivery band, drivers, options, GenAI verdict, citations, draft email, Approve button), Suppliers, Anomalies and Platform.

How the replay flags work:
* `--speed 20000` means one simulated day takes about 4 seconds. Use `--speed 0` for a fast full run.
* `--n` sets how many test period shipments to replay.
* Each shipment emits ORDER_PLACED, INVOICE, DISPATCHED, sometimes DELAYED, and then DELIVERED or CANCELED.

## Step 7: connect a real LLM

The default `LLM_BACKEND=mock` works offline with the same contract, so the demo never breaks. To use a real model, set these variables in the terminal before you start the replay or JupyterLab:

```bash
# Any OpenAI compatible endpoint
export LLM_BACKEND=openai LLM_BASE_URL=https://.../v1 LLM_API_KEY=... LLM_MODEL=...

# IBM watsonx.ai (Granite)
pip install ibm-watsonx-ai
export LLM_BACKEND=watsonx WATSONX_URL=https://us-south.ml.cloud.ibm.com WATSONX_APIKEY=... WATSONX_PROJECT_ID=... LLM_MODEL=ibm/granite-3-8b-instruct
```

Check the watsonx call in `reasoner.py` against the SDK version used in the IBM lab. `LLM_MAX_CALLS` (default 40) caps LLM calls per run; lower priority alerts get rule based text instead. Every LLM answer goes through `validate()`. A wrong schema, an action that isn't one of the options, or a citation missing from the evidence packet gets the answer rejected and replaced with a rule alert.

If the VM can't reach the LLM API, run the GenAI part on a laptop with the same files, and say so in the pitch.

## Step 8: final numbers

```bash
python replay.py --n 1500 --speed 0 --reset
python evaluate.py          # writes artifacts/eval_report.md
```

Use only numbers from this report on slides, and only GenAI numbers from runs with a real LLM.

## Hour by hour plan (four people, about 10 hours)

| Hour | A: Platform | B: Data and eval | C: Models | D: GenAI and product |
| --- | --- | --- | --- | --- |
| 0 to 1 | Steps 1 to 3, share VM access | Download DataCo | Run the notebook on sample data | Choose the LLM, get keys |
| 1 to 3 | Replay on sample data | Real data through the notebook | Train on real data, tune | Prompt and validator with the real LLM |
| 3 to 4 | **Integration 1:** real models in the replay | Check the supplier table makes sense | Check drivers and options | Dashboard running |
| 4 to 7 | Event timing, two replays in parallel for a scaling screenshot | `evaluate.py`, metric slides | Better features if time allows | Polish Alert detail, pick the demo shipment |
| 7 to 8 | **Integration 2:** full run with the real LLM | Final eval report | Freeze models | Demo script |
| 8 to 10 | Evidence screenshots | Video help | Final metrics slide | Record and edit the video |

Freeze features at hour 8 no matter what.

## Evidence screenshots for judging criterion 3

1. `check_env.py` output showing s390x and the core count
2. The notebook's training metrics and charts, run on the VM
3. The replay terminal next to the dashboard
4. The Platform tab with per event processing time
5. Two replays at once, using different `CHAINSIGHT_DB` files, to show scaling
6. If time allows, the app running in a Podman container (`podman ps`)
7. Keys held in environment variables, never in code

## Assumptions to state honestly in the pitch

1. DataCo has no supplier field. A supplier is a department fulfilment hub per market (`prepare_data.py`).
2. Criticality comes from a department mapping in `config.py`. Health and Beauty stands in for medical goods.
3. Carrier DELAYED events and invoice or quantity anomalies are simulated in `replay.py` with known labels, so detection can be measured.
4. A DELAYED event updates breach probability with a stated rule (`DELAY_EVENT_LIFT`), not a retrained model.
5. The mock reviewer is a stand in. Report GenAI results only from real LLM runs.
6. Kafka, PostgreSQL, FastAPI and Machine Learning for z/OS are the production design. The datathon build uses an in process event loop and SQLite.

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `lightgbm` won't install | Ignore it. `train.py` reports `"backend": "sklearn"` and everything else works. |
| `streamlit` won't install | Run `python dashboard_lite.py` instead. |
| `st.fragment` error | Streamlit is older than 1.37. Upgrade it, or use the lite dashboard. |
| Notebook can't find modules | Open the notebook from inside the `chainsight` folder. |
| Too many alerts | Raise `BREACH_THRESHOLD`, for example `export BREACH_THRESHOLD=0.8`. DataCo has a high late rate. |
| Replay too slow for the video | Use a smaller `--n` or a higher `--speed`. |
| Date parsing error | Check the format of the `order date (DateOrders)` column. |
| Can't open the dashboard | Make sure the SSH tunnel from Step 3 is open, then use http://localhost:8501. |

## Essential goods priority update

See [`README_MEDICAL_PRIORITY.md`](README_MEDICAL_PRIORITY.md) for the targeted medical and essential goods prioritization changes, regression tests, and copy/paste commands to upload and run this version on the LinuxONE VM. The classification and inventory cover remain demo proxies, not verified medical catalog or live inventory data.
