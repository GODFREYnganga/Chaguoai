# ChaguoAI Adherence Model Integration

The ChaguoAI model is a discontinuation/adherence support model. It must run
after WHO MEC filtering and must never make clinical eligibility decisions.

## Serving Role

The backend service in `backend/model_adherence.py` loads the trained
LightGBM artifact, encoders, feature metadata, and model metadata from
`chaguoai_model/outputs`.

Recommendation Packets use the model in shadow mode:

- Existing WHO MEC and recommendation ordering remains intact.
- Each MEC-safe method can receive an `adherence_prediction`.
- CHWs see continuation-support wording.
- Clinicians see discontinuation probability, model version, and applicability.

## Applicability

The current model was trained on historical Siaya and Busia service statistics.
Scores outside those validated counties must be treated as support guidance only.

Returned applicability values:

- `validated_geography`
- `out_of_distribution`
- `insufficient_data`

## Retraining Events

Operational outcomes are normalized into `model_training_events`.

Rows include intake profile, recommendation context, confirmed method, follow-up
status, structured outcome, and a retraining label when available.

Label rules:

- `continuing` -> `label_discontinued = 0`
- `switched` or `stopped` -> `label_discontinued = 1`
- `pregnancy_reported` -> `label_discontinued = 1` when linked to method failure/discontinuation
- `lost_to_followup` -> censored, not treated as discontinued
- `referred` -> not a discontinuation label unless a final outcome confirms it

## Governance

Retraining should not begin until there are at least 500 labelled platform
outcomes. For subgroup bias audit, prefer 2,000+ labelled outcomes.

Promotion checks:

- AUC-ROC is not worse than the current model.
- Calibration error remains acceptable.
- Recall for discontinuation remains acceptable.
- Subgroup performance is checked by age, geography, fertility intention, and method category.
- Geography drift is reviewed before expanding model use outside validated areas.

The model should continue to support informed choice, not optimize clients into
one method category.
