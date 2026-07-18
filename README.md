# ChaguoAI: Clinical Decision Support for Safe Contraception

ChaguoAI is a professional-grade clinical decision support system (DSS) designed to help healthcare providers and individuals in Kenya make safe, grounded choices about contraception. The system combines the **WHO Medical Eligibility Criteria (MEC)** with a robust **RAG (Retrieval-Augmented Generation)** pipeline fueled by the latest Kenya National Family Planning Guidelines.

## Key Features

- **WHO MEC Engine:** A hardcoded, clinical logic layer that enforces safety boundaries (Category 1-4) for over 20 contraceptive methods.
- **RAG-Powered Chatbot:** Deep integration with guidelines to provide evidence-based answers on side effects, myths, and procedures.
- **Cross-Lingual Support:** Native support for English, Swahili, French, and Portuguese.
- **Unified Provider Portal:** A professional web interface for Community Health Workers (CHWs) and Clinicians to manage user rosters and run advanced assessments.
- **Multi-Channel Delivery:** Seamless interaction across WhatsApp (Twilio), USSD (Africa's Talking), and Web.
- **Analytics Geography:** Optional country and region capture for dashboards only — never used in WHO MEC or Method Match logic. See [docs/geography.md](docs/geography.md).
- **ML Adherence Model:** LightGBM continuation-support annotations (shadow mode) trained on Western Kenya service statistics.

## Architecture

The system follows a strict clinical safety pipeline:
`User Message -> Intent Detection -> WHO MEC Assessment -> RAG Guideline Retrieval -> Gemini LLM Framing -> Multi-Channel Response`

## Getting Started

### 1. Prerequisites
- Python 3.10+
- Firebase Project (Firestore & Storage)
- Twilio Account (for WhatsApp/SMS)
- GCP Service Account Key

### 2. Installation
```bash
git clone <your-fork-or-upstream-url>
cd Contraceptives_DSS/backend
pip install -r requirements.txt
```

### 3. Configuration
1. Copy `config/.env.example` to `backend/.env`.
2. Populate the `.env` file with your API keys and project IDs.
3. Set `GOOGLE_APPLICATION_CREDENTIALS` to a Firebase service account path outside the repository, or provide inline JSON through your deployment secret manager.
4. Set a strong `FLASK_SECRET_KEY` and `ADMIN_ACCESS_CODE`; production startup/login should not rely on defaults.

### 4. Build the Knowledge Base
Run the ingestor to process the clinical PDFs into the vector store:
```bash
python rag_ingestor.py --from-chunks   # rebuild from committed chunk JSON (no PDFs)
# or
python rag_ingestor.py                 # full PDF ingest
```
The clinical PDFs are not committed to the open-source repository. Place them in `knowledge/` or update the `KENYA_FP_PDF`, `WHO_MEC_PDF`, and `WHO_SPR_PDF` environment variables. For judges without PDFs, use `--from-chunks`.

### 5. Start the Server
```bash
cd backend
python main.py
```

In **development** (`APP_ENV` / `FLASK_ENV` not set to `production`), `main.py` binds to `0.0.0.0` and enables auto-reload when you save code. Set `FLASK_DEBUG=0` or `FLASK_RUN_HOST=127.0.0.1` in `backend/.env` to override.

### 6. Background Triage Worker
Provider triage recommendations run through Redis Queue (RQ), so production needs both a web service and a worker service.

Required environment variables:
```bash
REDIS_URL=redis://...
TRIAGE_QUEUE_NAME=triage
TRIAGE_JOB_TIMEOUT_SECONDS=180
GEMINI_TIMEOUT_MS=20000
```

Local worker:
```bash
cd backend
python worker.py
```

On **Windows**, `worker.py` automatically uses RQ's `SimpleWorker` (no `os.fork`). On Linux/macOS/Render it uses the standard fork-based worker.

Render setup:
- Web service start command: `gunicorn main:app --bind 0.0.0.0:$PORT`
- Worker service start command: `python worker.py`
- Both services must use the same `REDIS_URL`, Firebase credentials, Gemini credentials, and Twilio credentials.

### 7. Security-sensitive webhooks

Twilio webhooks validate `X-Twilio-Signature` when `TWILIO_AUTH_TOKEN` is configured. For local ngrok testing, set `PUBLIC_BASE_URL` to the exact public URL Twilio calls. Do not disable signature validation in production.

### 8. WhatsApp Interactive Menus (Buttons)

Buttons require **Twilio Content templates** — one template per option count. A 3-button template will **not** work for Yes/No (2 options) or the 5-item main menu.

**Full setup guide:** [docs/twilio_content_templates.md](docs/twilio_content_templates.md)

Create these five templates in Twilio Console → Content Template Builder:

| Env variable | Rows/buttons | Used for |
|--------------|--------------|----------|
| `TWILIO_CONTENT_QUICK_REPLY_2_SID` | 2 | Q3, Q8, Q9, Q12 (Yes/No) |
| `TWILIO_CONTENT_QUICK_REPLY_3_SID` | 3 | Q2, Q5, Q7, Q10, Q11 |
| `TWILIO_CONTENT_LIST_PICKER_4_SID` | 4 | Language menu, Q4, Q9a |
| `TWILIO_CONTENT_LIST_PICKER_5_SID` | 5 | Main menu, Q13 |
| `TWILIO_CONTENT_LIST_PICKER_7_SID` | 7 | Q6 health conditions |

On startup, the server logs which templates are set vs missing. If a template is missing, that question falls back to numbered text (reply `1`, `2`, etc.).

Main WhatsApp menu:
```text
1. Method Match
2. Ask Question
3. Myths & Facts
4. Report Side Effects
5. Change Language
```

Single-choice survey questions use quick replies when they have 2-3 options and list pickers when they have 4+ options. Multi-select questions (Q6, Q13) use list pickers; reply with numbers like `1,3` for multiple selections.

See also: [docs/twilio_setup.md](docs/twilio_setup.md) for webhook/ngrok setup.

### 9. Geography (analytics only)

WhatsApp users **type** country and region (no long list menus). The CHW provider portal uses a **dropdown** of 54 African countries plus a text field for region. USSD collects geography **before** the 13 clinical questions.

Full design, Firestore fields, and APIs: [docs/geography.md](docs/geography.md).

USSD Method Match runs **asynchronously** via the Redis worker (press **3** to check results). Setup: [docs/ussd_setup.md](docs/ussd_setup.md).

Run geography unit tests:

```bash
python -m unittest discover -s tests/unit -t . -v -p "test_geography.py"
```

## Project Structure

- `backend/`: Flask application (`application.py`, `main.py` entrypoint).
  - `routes/`: HTTP route handlers grouped by public, admin, and provider APIs.
  - `core/`: Shared HTTP, auth, and serialization helpers.
  - `whatsapp/`: WhatsApp survey constants, helpers, and webhook flow.
- `dashboard/`: HTML templates for provider and admin portals.
- `static/`: Global CSS, JS, and clinical media assets.
- `tests/unit/` and `tests/integration/`: Offline and opt-in live tests.
- `config/`: Environment template (`config/.env.example` → copy to `backend/.env`).
- `docs/`: Technical deployment guides and schema documentation.
- `knowledge/`: Local-only clinical PDFs for RAG retrieval (not committed).
- `chaguoai_model/`: Optional ML training project; raw data and generated outputs are gitignored.

## Accessing the Dashboards

Once the server is running (locally or on cloud), you can access the professional interfaces at the following URLs:

### 1. Provider (CHW) Portal
For community health workers to perform triage and manage rosters.
- **URL:** `/provider`
- **Login:** Requires an approved provider email. Use the registration page (`/provider/register`) to apply.

### 2. Admin Portal
For system administrators to approve providers and view analytics.
- **URL:** `/admin` → `/admin/portal` after login
- **Access Code:** Set `ADMIN_ACCESS_CODE` in the environment.
- **Dashboard guide:** [docs/dashboards.md](docs/dashboards.md)

> [!IMPORTANT]
> The Admin Access Code is required to enter the protected management area. Set it via the `ADMIN_ACCESS_CODE` environment variable and do not commit real codes.

## Running Tests

Offline unit tests should pass without live external credentials:

```bash
python -m unittest discover -s tests/unit -t . -v -p "test_*.py"
```

Live Gemini/Twilio/Firebase checks are integration tests and should be gated by environment variables, for example:

```bash
RUN_INTEGRATION_TESTS=1 python -m unittest discover -s tests/integration -t . -v -p "test_*.py"
```

## Optional Adherence Model

The adherence/discontinuation model runs downstream of WHO MEC filtering and is optional. Set `CHAGUOAI_ADHERENCE_MODEL_DIR` to a folder containing:

- `models/05_best_model.pkl`
- `models/05_best_model_metadata.json`
- `processed/04_encoders.pkl`
- `processed/04_feature_meta.json`

If artifacts are missing, the app remains functional and marks the adherence model as unavailable.

---
**Disclaimer:** ChaguoAI provides clinical decision support and is NOT a substitute for professional medical advice. Always consult a healthcare provider for prescriptions.
