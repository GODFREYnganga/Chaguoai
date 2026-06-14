# Firestore Schema for ChaguoAI

This document describes the production collections used by the current DSS.
Field lists are intentionally focused on stable contract fields; operational
documents may include additional timestamps or delivery metadata.

## `contraceptive_users`

Document ID: client phone number in E.164 format.

Core fields:

- `name`
- `language`
- `source`
- `country`, `admin_area`, `admin_area_type`
- Intake answers: `age`, `last_period`, `baby_under_6m`, `breastfeeding_only`, `living_children`, `more_children`, `health_conditions`, `hiv_status`, `smoke`, `previous_use`, `stop_reason`, `partner_support`, `facility_access`, `sti_concern`, `prefer_not_to_use`
- Method Match fields: `matched_method`, `method_cards`, `recommendation_packet`, `latest_mec_text`, `method_match_status`, `method_match_completed_at`
- Provider assignment: `assigned_provider_id`
- Care plan fields: `selected_method`, `selected_method_category`, `care_plan_status`, `continuation_status`, `next_followup_at`, `automation_enabled`, `followup_consent`, `no_response_count`
- Referral summary: `referral_required`, `referral_status`, `latest_referral_id`, `latest_referral_facility`
- Outcome summary: `latest_followup_outcome`, `latest_structured_outcome`

Subcollections:

- `method_selection_events`
- `referrals`
- `followup_events`
- `side_effects`
- `audit_trail`

## `providers`

Provider portal users.

Fields:

- `fullName`
- `email`
- `phone`
- `role` (`chw` or `clinician`)
- `credentials`
- `password_hash`
- `status` (`pending`, `approved`, `rejected`)
- `created_at`

Never return `password_hash` from provider APIs.

## `triage_jobs`

Provider Method Match background jobs.

Fields:

- `status`
- `data`
- `recommendation`
- `mec_result`
- `method_cards`
- `recommendation_packet`
- `recommendation_citations`
- `fhir_view`
- `error`
- `created_at`, `started_at`, `completed_at`

## `followup_tasks`

Global scheduled follow-up queue.

Fields:

- `phone`
- `client_name`
- `provider_id`
- `method`
- `due_at`
- `status` (`due`, `sent`, `client_replied`, `completed`, `no_response`, `paused`, `send_failed`)
- `reason`
- `days_after_start`
- `attempts`
- `response_due_at`
- `sent_at`
- `last_response_at`
- `structured_outcome`

## `analytics_events`

Append-only event stream used for dashboard metrics.

Examples:

- `method_selected`
- `referral_created`
- `referral_status_updated`
- `followup_sent`
- `followup_no_response`
- `followup_client_replied`
- `followup_outcome_recorded`

## `model_training_events`

Retraining-ready rows generated from structured outcomes and no-response events.

Important fields:

- `client_id_hash`
- `country`, `admin_area`
- `age`, `noofchildren`, `education_level`, `fertility_intention`, `previous_method`
- `recommended_methods`
- `confirmed_method`
- `followup_status`
- `outcome_type`
- `continuation_status`
- `lost_to_followup`
- `label_discontinued`
- `label_status`

Rows with `lost_to_followup` are censored and must not be treated as confirmed
discontinuation without a later outcome.
