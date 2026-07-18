# Contributing

Thank you for improving ChaguoAI.

## Local Setup

1. Create a Python virtual environment.
2. Install backend dependencies from `backend/requirements.txt`.
3. Copy `config/.env.example` to `backend/.env` and fill local values.
4. Keep Firebase service account files and real secrets outside the repository.

## Checks Before Opening a PR

```bash
python -m compileall backend
python -m unittest discover -s tests/unit -t . -v -p "test_*.py"
```

Live provider checks should be run only when the required credentials are
available and `RUN_INTEGRATION_TESTS=1` is set.

## Security

Do not commit `.env`, Firebase service account keys, Twilio credentials, Gemini
keys, raw clinical data, model pickle files, generated vector databases, or
client exports.

Clinical decision logic must preserve WHO MEC safety rules. ML outputs may
support counselling and follow-up prioritization, but must not override MEC
contraindications.

## Repository layout

- Add HTTP handlers under `backend/routes/`.
- Add shared utilities under `backend/core/`.
- Add WhatsApp workflow code under `backend/whatsapp/`.
- Add tests under `tests/unit/` (offline) or `tests/integration/` (live credentials).
- Add documentation under `docs/`.
