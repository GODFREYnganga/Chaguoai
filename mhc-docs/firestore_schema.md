# Firestore Schema for Contraception DSS

## 1. `users` Collection
- **Document ID:** User phone number (hashed for de-identification in transit).
- **Fields:**
    - `name`: String (Encrypted at rest).
    - `phone`: String (Encrypted at rest).
    - `county`: String.
    - `language`: String (`english`/`swahili`).
    - `consent_given`: Boolean.
    - `created_at`: Timestamp.

## 2. `conversations` Collection
- **Document ID:** KMHFL Facility ID.
- **Fields:**
    - `name`: String.
    - `facility_type`: String (Level 2, 3, 4).
    - `lat`: Number.
    - `lng`: Number.
    - `emergency_phone`: String.
    - `is_active`: Boolean.

    - `timestamp`: Timestamp.
