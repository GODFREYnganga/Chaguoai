# ChaguoAI Adherence Model

This folder contains the offline ML pipeline for the ChaguoAI contraceptive
discontinuation/adherence model.

The model predicts the probability that a client will switch or stop a candidate
contraceptive method. In the app, it is used only after WHO MEC safety filtering
and only as continuation-support guidance.

## Important Open-Source Note

Raw datasets and generated model artifacts are not committed by default.

Ignored paths include:

- `data/raw/`
- `outputs/processed/`
- `outputs/models/`
- `outputs/figures/`

Use the reports in `outputs/reports/` and the backend documentation in
`../docs/model_integration.md` to understand model performance and governance.

## Setup

```bash
cd chaguoai_model
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

On Linux/macOS:

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

For interactive notebooks, install Jupyter in the same environment:

```bash
pip install jupyter ipykernel
python -m ipykernel install --user --name chaguoai --display-name "ChaguoAI"
```

## Data

Place source CSVs under `data/raw/` (at minimum `Client_Service_Statistics.csv`) or set:

```bash
CHAGUOAI_DATA_DIR=/path/to/raw/data
CHAGUOAI_OUTPUTS_DIR=/path/to/generated/outputs
```

Paths are resolved by `src/config.py` via `get_paths()`. Each notebook discovers
the project root automatically (looks for `src/config.py`), so you can open
notebooks from `chaguoai_model/` or `chaguoai_model/notebooks/`.

Expected service-statistics columns are documented in
`outputs/reports/06_scalability_guide.txt` after you run the pipeline.

## Pipeline (Jupyter notebooks)

Run the notebooks **in order** from `notebooks/`:

| Step | Notebook | Purpose |
|------|----------|---------|
| 01 | `01_raw_data_profiling.ipynb` | Read-only profiling; no data changes |
| 02 | `02_data_cleaning.ipynb` | Clean dataset → `02_cleaned.parquet` |
| 03 | `03_eda.ipynb` | Exploratory analysis and EDA figures |
| 04 | `04_feature_engineering.ipynb` | Train/val/test splits and encoders |
| 05 | `05_model_training.ipynb` | Train and select best model |
| 06 | `06_final_evaluation.ipynb` | One-time sealed test evaluation |

### How to run

**Option A — Jupyter Lab / Notebook**

```bash
cd chaguoai_model
jupyter lab notebooks/
```

Open each notebook and run all cells top to bottom.

**Option B — Code Editor**

Open any `notebooks/*.ipynb` file, select the **ChaguoAI** (or your venv) kernel,
and run cells in order.

**Option C — Execute without the UI** (CI or batch)

```bash
cd chaguoai_model
jupyter nbconvert --execute --inplace notebooks/01_raw_data_profiling.ipynb
jupyter nbconvert --execute --inplace notebooks/02_data_cleaning.ipynb
jupyter nbconvert --execute --inplace notebooks/03_eda.ipynb
jupyter nbconvert --execute --inplace notebooks/04_feature_engineering.ipynb
jupyter nbconvert --execute --inplace notebooks/05_model_training.ipynb
jupyter nbconvert --execute --inplace notebooks/06_final_evaluation.ipynb
```

Notebook 06 opens the test set once. Do not re-run it to tune the model after
seeing test metrics.



## Connect the trained model to the app

Training is **offline only**. The live backend does **not** run this folder at
request time — it loads saved artifacts.

After notebooks 01–06 complete, these files must exist:

- `outputs/models/05_best_model.pkl`
- `outputs/models/05_best_model_metadata.json`
- `outputs/processed/04_encoders.pkl`
- `outputs/processed/04_feature_meta.json`

Point the backend at the `outputs` directory in `backend/.env`:

```bash
CHAGUOAI_ADHERENCE_MODEL_DIR=../chaguoai_model/outputs
```

Restart the backend. `backend/model_adherence.py` loads the model, encoders, and
metadata and attaches adherence scores to recommendation packets (shadow mode —
WHO MEC safety ordering is unchanged).

If artifacts are missing, the app still runs; adherence predictions are reported
as unavailable. Serving behaviour is covered by `tests/unit/test_model_adherence.py`
at the repo root.

## Project layout

```
chaguoai_model/
  data/raw/           # Source CSVs (gitignored)
  notebooks/          # Pipeline notebooks 01–06
  outputs/
    figures/          # Generated charts (gitignored)
    models/           # Trained model + metadata (gitignored)
    processed/        # Clean data, splits, encoders (gitignored)
    reports/          # Profiling, metrics, model card inputs
  scripts/            # Utilities (e.g. py_to_notebook.py)
  src/
    config.py         # Paths, constants, feature mappings
```

## Docs

- **Integration docs** — `../docs/model_integration.md` (governance, retraining, applicability).
