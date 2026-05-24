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
