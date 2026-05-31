# ChaguoAI: Clinical Decision Support for Safe Contraception

ChaguoAI is a professional-grade clinical decision support system (DSS) designed to help healthcare providers and individuals in Kenya make safe, grounded choices about contraception. The system combines the **WHO Medical Eligibility Criteria (MEC)** with a robust **RAG (Retrieval-Augmented Generation)** pipeline fueled by the latest Kenya National Family Planning Guidelines.

## Key Features

- **WHO MEC Engine:** A hardcoded, clinical logic layer that enforces safety boundaries (Category 1-4) for over 20 contraceptive methods.
- **RAG-Powered Chatbot:** Deep integration with guidelines to provide evidence-based answers on side effects, myths, and procedures.
- **Cross-Lingual Support:** Native support for English, Swahili, French, and Portuguese.
- **Unified Provider Portal:** A professional web interface for Community Health Workers (CHWs) and Clinicians to manage user rosters and run advanced assessments.
- **Multi-Channel Delivery:** Seamless interaction across WhatsApp (Twilio), USSD (Africa's Talking), and Web.

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
git clone https://github.com/your-repo/ChaguoAI.git
cd ChaguoAI/mhc-backend
pip install -r requirements.txt
```

### 3. Configuration
1. Copy `mhc-backend/.env.example` to `mhc-backend/.env`.
2. Populate the `.env` file with your API keys and project IDs.
3. Place your Firebase `serviceAccountKey.json` in the `mhc-backend/` directory.

### 4. Build the Knowledge Base
Run the ingestor to process the clinical PDFs into the vector store:
```bash
python rag_ingestor.py
```

### 5. Start the Server
```bash
python main.py
```

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
cd mhc-backend
python worker.py
```

Render setup:
- Web service start command: `gunicorn main:app --bind 0.0.0.0:$PORT`
- Worker service start command: `python worker.py`
- Both services must use the same `REDIS_URL`, Firebase credentials, Gemini credentials, and Twilio credentials.

### 7. WhatsApp Interactive Menus (Buttons)

Buttons require **Twilio Content templates** — one template per option count. A 3-button template will **not** work for Yes/No (2 options) or the 5-item main menu.

**Full setup guide:** [mhc-docs/twilio_content_templates.md](mhc-docs/twilio_content_templates.md)

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

See also: [mhc-docs/twilio_setup.md](mhc-docs/twilio_setup.md) for webhook/ngrok setup.

## Project Structure

- `mhc-backend/`: Core logic (Flask server, RAG logic, and WHO MEC engine).
- **`mhc-dashboard/`**: Centralized HTML templates (Provider and Admin portals).
- **`static/`**: Global assets (CSS, JS, and clinical media).
- `mhc-knowledge/`: Official Clinical PDF guidelines for RAG retrieval.
- `mhc-docs/`: Technical deployment guides.

## Accessing the Dashboards

Once the server is running (locally or on cloud), you can access the professional interfaces at the following URLs:

### 1. Provider (CHW) Portal
For community health workers to perform triage and manage rosters.
- **URL:** `/provider`
- **Login:** Requires an approved provider email. Use the registration page (`/provider/register`) to apply.

### 2. Admin Portal
For system administrators to approve providers and view analytics.
- **URL:** `/admin`
- **Access Code:** `ADMIN2026`

> [!IMPORTANT]
> The Admin Access Code is required to enter the protected management area. In a production setting, this should be set via the `ADMIN_SECRET` environment variable.

---
**Disclaimer:** ChaguoAI provides clinical decision support and is NOT a substitute for professional medical advice. Always consult a healthcare provider for prescriptions.
