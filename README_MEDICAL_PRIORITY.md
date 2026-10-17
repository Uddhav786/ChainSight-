# ChainSight essential goods priority update

This update makes essential goods prioritization more explicit while preserving the existing model and dashboard architecture.

## What changed

- `config.py`: Health and Beauty is now a broad category fallback of criticality 3, not an automatic medical criticality 5. Configurable product-name keyword groups identify possible medicines, medical equipment, and relief supplies.
- `prepare_data.py`: adds `essential_goods_type` and assigns criticality 5 to keyword-matched medicines, 4 to medical equipment/relief supplies, and otherwise uses the department fallback. Product-name matching is a demo heuristic, not verified catalog data.
- `decision.py`: clamps breach probability and criticality to valid ranges and documents the priority inputs. Formula remains breach probability × criticality × stockout severity × urgency.
- `replay.py`: stores product name and goods classification in SQLite and uses reproducible simulated inventory cover, with lower cover for classified essential goods. This is explicitly simulated because DataCo has no inventory feed.
- `app.py`: shows product, classification, criticality, and inventory-cover estimate on the dashboard.
- `test_medical_priority.py`: regression tests for classification, priority ordering, and approval policy.

## Important limitations

DataCo does not reliably identify real medicines, suppliers, or inventory. Product-name keyword matches can miss medical items or misclassify unrelated products. Inventory cover remains a simulated demo value. Do not describe these fields as verified medical data or live hospital stock. For production, replace these heuristics with a validated product catalog and an inventory/ERP feed.

## Run on LinuxONE VM

Commands below assume Ubuntu, an SSH key file named `chainsight.pem`, and a VM login user of `ubuntu`. Use the username supplied by your VM administrator if different.

### 1. Upload the zip from your Mac terminal

Run from the directory containing `ChainSight_Medical_Priority.zip` and your SSH key:

```bash
chmod 600 chainsight.pem
scp -i chainsight.pem ChainSight_Medical_Priority.zip ubuntu@<VM_PUBLIC_IP>:~/
ssh -i chainsight.pem ubuntu@<VM_PUBLIC_IP>
```

Replace `<VM_PUBLIC_IP>` with the VM's public IP. Keep the private SSH key private.

### 2. Install system dependencies on the VM

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip unzip
cd ~
unzip -o ChainSight_Medical_Priority.zip
cd chainsight
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If optional LightGBM cannot be installed on s390x, follow the fallback described in the main README. The project still needs its configured supported model backend and trained artifacts.

### 3. Upload the DataCo CSV

From a second terminal on your Mac, upload the dataset to the VM (adjust the local filename):

```bash
scp -i chainsight.pem ./DataCoSupplyChainDataset.csv ubuntu@<VM_PUBLIC_IP>:~/chainsight/data/
```

If `data/` does not exist yet, create it on the VM first:

```bash
mkdir -p ~/chainsight/data
```

### 4. Prepare data and train models

Back on the VM, in `~/chainsight` with `.venv` active:

```bash
python check_env.py
python prepare_data.py
python train.py
```

Do not skip training unless compatible artifacts already exist in `artifacts/`.

### 5. Run the essential goods tests

```bash
python -m unittest -v test_medical_priority.py
```

### 6. Run the replay

Use a small replay first:

```bash
python replay.py --n 300 --speed 20000 --reset
```

Leave this terminal running until the replay completes. For the demo, the replay creates a SQLite database at the configured path.

### 7. Start the dashboard in a second SSH session

```bash
ssh -i chainsight.pem ubuntu@<VM_PUBLIC_IP>
cd ~/chainsight
source .venv/bin/activate
streamlit run app.py --server.port 8501 --server.address 0.0.0.0
```

Open `http://<VM_PUBLIC_IP>:8501` only if the VM network/security rules allow port 8501. Safer alternative: from your Mac, open an SSH tunnel:

```bash
ssh -i chainsight.pem -L 8501:localhost:8501 ubuntu@<VM_PUBLIC_IP>
```

Then browse to `http://localhost:8501` on your Mac. If the VM uses a different login username, replace `ubuntu` in every command.

### Troubleshooting

- `FileNotFoundError` for DataCo CSV: check `data/DataCoSupplyChainDataset.csv` exists and set `DATACO_CSV` if the name/path differs.
- Missing model artifacts: run `python prepare_data.py` and `python train.py` before replay.
- Database schema changed: use `python replay.py --reset` (or `--reset` on the replay command) to recreate the demo database. Back up any database you need before resetting.
- Streamlit unavailable: install it with `pip install streamlit` inside the active virtual environment.
