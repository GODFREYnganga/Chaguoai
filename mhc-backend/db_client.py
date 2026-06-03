import json
import os

from firebase_admin import credentials, firestore, initialize_app

_db = None
_initialized = False


def init_firebase():
    global _db, _initialized
    if _initialized:
        return _db

    bucket_name = os.environ.get("FIREBASE_STORAGE_BUCKET")
    creds_val = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")

    try:
        if creds_val and creds_val.strip().startswith("{"):
            creds_dict = json.loads(creds_val)
            firebase_creds = credentials.Certificate(creds_dict)
            initialize_app(firebase_creds, {"storageBucket": bucket_name} if bucket_name else {})
        elif creds_val and os.path.exists(creds_val):
            firebase_creds = credentials.Certificate(creds_val)
            initialize_app(firebase_creds, {"storageBucket": bucket_name} if bucket_name else {})
        else:
            initialize_app(options={"storageBucket": bucket_name} if bucket_name else {})
        _db = firestore.client()
        print("[DEBUG] Firebase Initialized Successfully.")
    except ValueError:
        _db = firestore.client()
    except Exception as exc:
        print(f"CRITICAL Warning: Could not initialize firebase. {exc}")
        _db = None

    _initialized = True
    return _db


def get_db():
    if _db is None and not _initialized:
        init_firebase()
    return _db
