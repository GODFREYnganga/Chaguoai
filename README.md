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

- `mhc-backend/`: Core Flask server, RAG logic, and MEC engine.
- `mhc-knowledge/`: Official Clinical PDF guidelines and documentation.
- `mhc-docs/`: Technical setup and deployment guides.
- `templates/`: Modern, clinical-grade UI for the Provider and Admin portals.



---
**Disclaimer:** ChaguoAI provides clinical decision support and is NOT a substitute for professional medical advice. Always consult a healthcare provider for prescriptions.
