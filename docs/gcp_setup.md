# GCP Setup Guide for Contraception DSS

To build the Contraception DSS, you will need a Google Cloud Project with the following APIs enabled:

## 1. Required APIs
- **Vertex AI API:** For Gemini Pro and Vector Search (RAG).
- **Google Cloud Firestore API:** For database storage.
- **Cloud Functions API:** For backend webhooks and logic.
- **Cloud Run API:** For hosting the dashboard or larger services.

## 2. Authentication
1.  **Service Account:** Create a service account named `mhc-backend-sa`.
2.  **Roles:** Assign the following roles:
    - `Vertex AI User`
    - `Cloud Datastore User` (for Firestore)
    - `Cloud Functions Developer`
3.  **Key File:** Generate a JSON key for this service account to be used locally during development.

## 3. Storage Setup
- **Firestore:** Create a database in **Native Mode**. Select a region close to Kenya (e.g., `europe-west1` or `europe-west2` as currently there are no GCP regions in East Africa).
- **Cloud Storage:** Create a bucket `mhc-knowledge-base` for storing raw PDFs.
