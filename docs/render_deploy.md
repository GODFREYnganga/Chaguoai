# Deploy ChaguoAI on Render

This project needs **three Render resources**:

1. **Web service** — Flask API + dashboards + webhooks  
2. **Background worker** — Redis Queue (provider triage, WhatsApp method match)  
3. **Redis** — job queue shared by web and worker  

---

## 1. Push code to GitHub

Render deploys from Git. Commit and push your repo (do **not** commit `.env` or Firebase JSON files).

**RAG on deploy:** Commit `backend/knowledge_base/chunks/*_chunks.json` so the build can rebuild Chroma without PDFs.  
(`chroma_db/` stays gitignored.)

---

## 2. Create Redis on Render

1. Render Dashboard → **New +** → **Redis** (or **Key Value** if Redis is under that name).  
2. Name it e.g. `chaguoai-redis`.  
3. Copy the **Internal Redis URL** (starts with `redis://`).  
4. Use this as `REDIS_URL` on both web and worker services.

---

## 3. Web service (API + dashboards)

**New +** → **Web Service** → connect your GitHub repo.

| Setting | Value |
|--------|--------|
| **Name** | `chaguoai-web` |
| **Region** | Closest to your users (e.g. Frankfurt) |
| **Root Directory** | `backend` |
| **Runtime** | Python 3 |
| **Build Command** | `pip install -r requirements.txt && python rag_ingestor.py --from-chunks` |
| **Start Command** | `gunicorn main:app --bind 0.0.0.0:$PORT` |
| **Health Check Path** | `/health` |

### Required environment variables (Web)

Set these under **Environment** (use **Secret** for keys):

| Variable | Notes |
|----------|--------|
| `APP_ENV` | `production` |
| `FLASK_SECRET_KEY` | Long random string (required in production) |
| `ADMIN_ACCESS_CODE` | Long random string |
| `PUBLIC_BASE_URL` | `https://<your-web-service>.onrender.com` (no trailing slash) |
| `BASE_URL` | Same as `PUBLIC_BASE_URL` |
| `REDIS_URL` | Internal Redis URL from step 2 |
| `GOOGLE_APPLICATION_CREDENTIALS` | **Paste full Firebase service account JSON** (one line is fine) |
| `FIREBASE_STORAGE_BUCKET` | `your-project.appspot.com` |
| `GEMINI_API_KEY` | Gemini API key |
| `OPENAI_API_KEY` | For RAG embeddings |
| `TWILIO_ACCOUNT_SID` | Twilio |
| `TWILIO_AUTH_TOKEN` | Twilio |
| `TWILIO_WHATSAPP_NUMBER` | e.g. `whatsapp:+14155238886` |
| `TRIAGE_QUEUE_NAME` | `triage` (default) |

Optional but recommended: all `TWILIO_CONTENT_*_SID` variables, `CHAGUOAI_ADHERENCE_MODEL_DIR`, PDF paths if you run full ingest instead of `--from-chunks`.

### Twilio webhook URLs (after deploy)

- WhatsApp: `https://<your-app>.onrender.com/webhook` or `/whatsapp`  
- Status callback: same base URL if needed  

### USSD (Africa's Talking)

- Callback URL: `https://<your-app>.onrender.com/ussd`  

---

## 4. Background worker service

**New +** → **Background Worker** → same repo.

| Setting | Value |
|--------|--------|
| **Root Directory** | `backend` |
| **Build Command** | `pip install -r requirements.txt` |
| **Start Command** | `python worker.py` |

Copy **the same environment variables** as the web service (especially `REDIS_URL`, Firebase JSON, `GEMINI_API_KEY`, `OPENAI_API_KEY`, `PUBLIC_BASE_URL`).  
The worker does not need to be public; it only talks to Redis and external APIs.

---

## 5. Verify deployment

1. Open `https://<your-app>.onrender.com/health` — should return JSON with `"ok": true` for Firebase, Redis, Chroma when configured.  
2. Open `https://<your-app>.onrender.com/provider` — provider portal.  
3. Open `https://<your-app>.onrender.com/admin` — admin login.  
4. Submit a **provider triage** job — worker logs should show job processing (not Chroma `tenants` errors).  

---

## 6. Common issues

| Problem | Fix |
|---------|-----|
| `no such table: tenants` (Chroma) | Build command must include `python rag_ingestor.py --from-chunks`, and chunk JSON must exist in the repo. |
| Triage stays `queued` | Worker not running, wrong `REDIS_URL`, or web/worker use different Redis instances. |
| Twilio `Invalid signature` | Set `PUBLIC_BASE_URL` to exact public URL Twilio calls (https, no trailing `/`). |
| `FLASK_SECRET_KEY must be set` | Set `APP_ENV=production` and `FLASK_SECRET_KEY`. |
| Chroma missing after restart (free tier) | Ephemeral disk — rebuild runs on each deploy via build command, or add a **persistent disk** for `knowledge_base/chroma_db`. |
| Provider login fails | Re-register providers after password-hashing migration. |

---

## 7. Optional: follow-up automation cron

To run automated follow-ups on a schedule, add a **Cron Job** on Render:

- **Root Directory:** `backend`  
- **Schedule:** e.g. `0 */6 * * *` (every 6 hours)  
- **Command:** `python followup_tasks.py`  

Use the same Firebase and Twilio env vars as the web service.

---

## 8. Production checklist

- [ ] `APP_ENV=production`, strong `FLASK_SECRET_KEY`, `ADMIN_ACCESS_CODE`  
- [ ] `PUBLIC_BASE_URL` set to Render URL  
- [ ] Redis + worker running  
- [ ] Chroma built (`--from-chunks` or full PDF ingest)  
- [ ] Twilio webhooks pointed at Render  
- [ ] Approve at least one provider in admin portal  
- [ ] Do not set `DISABLE_TWILIO_SIGNATURE_VALIDATION=1` in production  
