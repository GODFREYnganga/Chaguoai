# USSD Setup (Africa's Talking)

ChaguoAI exposes `POST /ussd` for Africa's Talking (or any gateway that forwards `sessionId`, `serviceCode`, `phoneNumber`, and `text`).

## Architecture

1. User completes Method Match questions on USSD (synchronous, fast).
2. On the final answer, the server **queues** an async job (`ussd_tasks.process_ussd_method_match_job`) on the same Redis/RQ worker as provider triage.
3. USSD returns immediately: *"Your match is being prepared…"*
4. User dials again and presses **3 — Check Method** to read the result.
5. If Redis is unavailable (local dev), a **fast MEC-only summary** is returned synchronously (no Gemini timeout).

## Languages

USSD supports **English, Kiswahili, French, and Portuguese** (menu option 5 to change language).

## Africa's Talking callback

| Setting | Value |
|---------|--------|
| Callback URL | `https://<your-host>/ussd` |
| Method | `POST` |

## Local simulation

```bash
# Language menu
curl -X POST http://127.0.0.1:8080/ussd \
  -d "sessionId=dev1" -d "serviceCode=*384*1#" \
  -d "phoneNumber=+254700000001" -d "text="

# Select English, then main menu
curl -X POST http://127.0.0.1:8080/ussd \
  -d "sessionId=dev1" -d "serviceCode=*384*1#" \
  -d "phoneNumber=+254700000001" -d "text=1"
```

## Production requirements

- **Redis** + `python worker.py` running (same as provider triage).
- Firebase credentials configured.
- Gemini + OpenAI keys for full async recommendations (worker uses full clinical pipeline).

## Tests

```bash
python -m unittest discover -s tests/unit -t . -v -p "test_ussd_logic.py"
```
