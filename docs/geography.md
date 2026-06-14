# Geography capture (analytics only)

ChaguoAI collects **country** and **administrative region** (county, state, district, etc.) for program analytics and dashboards. These fields **do not** affect:

- WHO Medical Eligibility Criteria (MEC) assessment
- RAG retrieval scope (still Kenya/global guidelines as configured)
- Method Match recommendations or clinical LLM prompts

## Design principles

| Principle | Implementation |
|-----------|----------------|
| Clinical separation | `geography.strip_analytics_fields()` removes location from MEC mapping and LLM survey context |
| Channel-appropriate UX | WhatsApp: free text + fuzzy confirm; USSD: free text before Q1; Provider portal: 54-country dropdown + region text |
| Raw + normalized storage | `country_raw` / `country` and `admin_area_raw` / `admin_area` for audit and charts |
| Single source of truth | `backend/geography.py` + `data/geography_aliases.json` |

## Firestore fields

| Field | Description |
|-------|-------------|
| `country_raw` | Exactly what the user typed or selected |
| `country` | Canonical name from `AFRICAN_COUNTRIES`, or `Other` |
| `country_match_confidence` | `exact`, `alias`, `fuzzy`, or `unmatched` |
| `admin_area_raw` | User-entered region |
| `admin_area` | Normalized (title-cased) region label |
| `admin_area_type` | e.g. `county` (Kenya), `state` (Nigeria) |
| `location_capture_purpose` | Always `analytics_only` |
| `location_source` | `whatsapp`, `ussd`, or `provider` |
| `location_captured_at` | Timestamp when region step completes (WhatsApp) |

## WhatsApp flow

1. After name → prompt: type your country (plain message, no list picker).
2. Input is validated (min 2 chars, not junk).
3. `normalize_country()` runs:
   - **Exact / alias** → save and ask for region.
   - **Fuzzy** (e.g. `keny` → Kenya) → `AWAITING_COUNTRY_CONFIRM`: reply `1` to confirm, `2` to re-enter.
   - **Unmatched** → stored as `Other` with raw text preserved; continue to region.
4. Region → free text, then clinical questions Q1–Q13 unchanged.

Legacy numeric replies `1`–`54` still map to the canonical list for users who have old menus cached.

## USSD flow

After choosing **Method Match** (menu `1`), before Q1:

1. `CON Analytics only: Enter your country (e.g. Kenya):`
2. `CON Analytics only: Enter your county/region:` (label depends on country)

Fuzzy matches are **auto-accepted** on USSD (no confirm step) to keep the session short; confidence is still stored.

## Provider (CHW) portal

- **Country**: dropdown loaded from `GET /api/geography/countries` (54 African countries).
- **Region**: free text; prompt label updates from selected country.

Backend normalizes provider submissions on `POST /api/provider/submit_triage`.

## Admin analytics

`GET /api/admin/stats` includes:

```json
{
  "geography": {
    "clients_with_location": 120,
    "by_country": { "Kenya": 80, "Uganda": 25 },
    "top_regions_by_country": { "Kenya": { "Nairobi": 40 } },
    "unmatched_country_count": 3,
    "unmatched_rate_percent": 2.5
  }
}
```

## API

| Endpoint | Auth | Purpose |
|----------|------|---------|
| `GET /api/geography/countries` | Public | Canonical list for provider dropdown |
| `GET /api/admin/stats` | Admin session | Includes `geography` block |

## Extending aliases

Edit `backend/data/geography_aliases.json`:

```json
{
  "country_aliases": {
    "ivory coast": "Cote d'Ivoire"
  }
}
```

Restart the web service after changes (aliases are loaded at import time).

## Privacy note

Country and region are **self-reported** and used in aggregate reporting. Do not use them as the sole basis for clinical decisions. For production deployments, align retention and access with your data protection policy and national health data guidelines.

## Tests

```bash
cd backend
python -m unittest test_geography.py -v
```

## Related code

- `geography.py` — normalization, prompts, aggregation
- `main.py` — WhatsApp stages `AWAITING_COUNTRY`, `AWAITING_COUNTRY_CONFIRM`, `AWAITING_ADMIN_AREA`
- `ussd_logic.py` — geography before Method Match questions
- `user_profile_mapper.py` — strips analytics fields from clinical mapping
- `triage_tasks.py` — strips analytics from provider triage LLM JSON
