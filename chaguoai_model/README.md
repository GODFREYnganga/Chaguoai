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
`../docs/model_integration.md` to understand model performance and
governance.

## Setup

```bash
cd chaguoai_model
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

On Linux/macOS, use:

```bash
source .venv/bin/activate
```

## Data

Place source CSVs under `data/raw/` or set:

```bash
CHAGUOAI_DATA_DIR=/path/to/raw/data
CHAGUOAI_OUTPUTS_DIR=/path/to/generated/outputs
```

Expected service-statistics columns are documented in
`outputs/reports/06_scalability_guide.txt`.

## Pipeline

Run the Python notebook exports in order:

```bash
python notebooks/01_raw_data_profiling.py
python notebooks/02_data_cleaning.py
python notebooks/03_eda.py
python notebooks/04_feature_engineering.py
python notebooks/05_model_training.py
python notebooks/06_final_evaluation.py
```

The backend expects these artifacts when model serving is enabled:

- `outputs/models/05_best_model.pkl`
- `outputs/models/05_best_model_metadata.json`
- `outputs/processed/04_encoders.pkl`
- `outputs/processed/04_feature_meta.json`

Set `CHAGUOAI_ADHERENCE_MODEL_DIR` in `mhc-backend/.env` to the `outputs`
directory containing those artifacts.
