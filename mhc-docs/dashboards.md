# Admin & provider dashboards

Professional, responsive dashboards built with **HTML + vanilla JS** and shared `static/css/dashboard.css` — no React/Vue dependency.

## Design choices

| Choice | Why |
|--------|-----|
| **KPI strip** (not large cards) | Compact numbers that stay readable on mobile |
| **Scrollable tables** | Scale to hundreds of clients without messy card grids |
| **CSS bar / donut charts** | No chart library required for v1; optional Chart.js later for lines only |
| **Traceable metrics** | Every KPI maps to a Firestore field or `/health` check |

## Admin portal (`/admin/portal`)

### APIs (session required)

| Endpoint | Purpose |
|----------|---------|
| `GET /api/admin/stats?cohort=all\|week\|whatsapp\|ussd\|provider` | Full analytics payload |
| `GET /api/admin/export/clients.csv` | CSV export |
| `GET /api/admin/pending_providers` | Approval queue |
| `POST /api/admin/approve_provider/:id` | Approve CHW/clinician |

### Stats payload highlights

- `kpis` — total clients, matches this week, pending approvals, active CHWs, system health
- `registration_trend` — 30 daily counts
- `channels`, `languages` — breakdowns
- `completion` — started / completed / failed / rate
- `method_distribution` — from `method_category_primary` (set on new completions)
- `geography` — analytics-only country/region
- `recent_completions` — table rows
- `safety_inbox` — side effects + Method Match / triage failures
- `health_checks` — Firebase, Gemini, Twilio, Chroma, Redis

### Cohort tabs

Filter the cohort before aggregating channel, language, completion, methods, geography, and recent completions. Trend chart always uses all users (program-wide).

## Provider portal (`/provider`)

### Where to click (CHW)

| Goal | Navigation |
|------|------------|
| **Method cards, Select, Refer, LLM explanation** | Sidebar **Method Match** → finish wizard → result screen (not only the yellow MEC box). Also **My Clients** → click row → drawer. |
| **Send follow-up (one message per client)** | Sidebar **Follow-ups** → compose box at top → **Send follow-up** on each client row. |
| **Side effect reports** | Sidebar **Side Effects** |

After deploying backend changes, restart **both** `python main.py` and `python worker.py`, then run a **new** Method Match. Old completed jobs may not have `method_cards` saved.

| Endpoint | Purpose |
|----------|---------|
| `GET /api/provider/roster` | Assigned clients with `match_status`, `method_category_primary` |
| `GET /api/provider/clients/<phone>` | Drawer detail + recommendation + side effects |
| `GET /api/provider/side_effects` | CHW safety queue |
| `GET /api/provider/methods` | Deterministic method education library |
| `POST /api/provider/clients/<phone>/select_method` | Save selected method and create follow-up tasks |
| `POST /api/provider/clients/<phone>/send_selection_message` | Send WhatsApp/SMS method instructions to client |
| `POST /api/provider/clients/<phone>/compose_followup` | Send one composed follow-up WhatsApp/SMS to client |
| `POST /api/provider/clients/<phone>/referral` | Create referral record |
| `GET /api/provider/followups` | CHW follow-up queue |
| `POST /api/provider/followups/<task_id>/outcome` | Record continuation outcome |

### CHW features

- Roster search and status filter
- Click row → **client drawer** (recommendation, MEC summary, side effects)
- **Side Effects** nav section
- **Follow-ups** nav section
- Method cards with **Select this method**, **Read more**, referral flags, use instructions, side effects, follow-up timing, and citations
- Client instructions sent after method selection with WhatsApp and SMS fallback when configured

## Response cards

Provider triage responses use rich `[METHOD_CARD]` blocks:

```text
[METHOD_CARD]
NAME: Contraceptive implant
CATEGORY: Implant
SUMMARY: ...
WHY_IT_FITS: ...
HOW_IT_WORKS: ...
HOW_TO_USE: ...
COMMON_SIDE_EFFECTS: ...
DURATION_OR_REVISIT: ...
REFERRAL_REQUIRED: Yes
REFERRAL_REASON: Insertion requires a trained provider.
FOLLOW_UP_SCHEDULE: Day 14, Day 90, annual review.
CITATIONS: S1, S2
[/METHOD_CARD]
```

The dashboard collapses detail under **Read more** so full clinical content is available without truncating the response.

## Method selection and follow-up

When a CHW selects a method:

1. `contraceptive_users/{phone}` is updated with `selected_method`, `selected_method_category`, `selected_by_provider_id`, and `continuation_status`.
2. A `method_selection_events` subcollection entry is created.
3. Referral details are required for methods that need trained provider insertion/removal.
4. `followup_tasks` documents are created from `method_library.py`.
5. A client-facing WhatsApp/SMS message can be sent with method instructions, side effects, warning signs, referral facility, and follow-up timing.

Follow-up outcomes include continuing, side-effect reassurance, referred, switched, stopped, and unreachable.

## Admin real-time updates

`GET /api/admin/events` streams dashboard stats using Server-Sent Events. The frontend falls back to normal fetch if the stream closes. Geography statistics render all-time registered countries by default via `geography_all_time`, while cohort-specific geography remains available as `geography_current_cohort`.

## Backend modules

- `admin_analytics.py` — aggregations
- `method_categories.py` — `method_category_primary` classification
- `method_library.py` — deterministic counseling and follow-up schedules
- `method_selection.py` — selection/referral/follow-up services
- `response_cards.py` — method card parsing
- `client_messages.py` — client-facing message composition
- Writes on: WhatsApp worker, USSD save, provider triage job

## Running tests

```bash
cd mhc-backend
python -m unittest test_geography.py test_method_categories.py test_response_cards.py test_method_library.py test_method_selection.py test_admin_analytics.py -v
```

## Success checklist

- [ ] Admin loads on phone / tablet / desktop
- [ ] “Matches this week” matches Firestore completions in last 7 days
- [ ] Method chart shows categories, not dominant “Unmatched”
- [ ] CHW opens client drawer from roster
- [ ] Side effect reports visible in admin Safety inbox and CHW queue
